"""Record every source response once, replay it later: a deterministic way to compare two copies of the scraper
(or two versions of the code) on exactly the same inputs, with no network.

    FOOTBALL_RECORD=cassette.json  python -m football.cli "Arsenal"     live run; every HTTP response and browser call is saved
    FOOTBALL_REPLAY=cassette.json  python -m football.cli "Arsenal"     offline run from the cassette (a call that was never recorded fails)

Two choke points carry all traffic: http.new_client() (httpx) and browser.launch_browser() (goto/evaluate). Entries are keyed by
request content, not by order, so the concurrent fetches replay correctly; a request repeated with different answers replays them in order.
"""
from __future__ import annotations

import asyncio
import atexit
import base64
import gzip
import hashlib
import json
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx

_HTTP: dict[str, list[dict]] = {}
_BROWSER: dict[str, list[dict]] = {}
_cursor: dict[str, int] = {}
_loaded = False


def mode() -> str | None:
    if os.environ.get("FOOTBALL_REPLAY"):
        return "replay"
    if os.environ.get("FOOTBALL_RECORD"):
        return "record"
    return None


def _path() -> str:
    return os.environ.get("FOOTBALL_REPLAY") or os.environ["FOOTBALL_RECORD"]


def _key(*parts: Any) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8", "replace")).hexdigest()


def _open(path: str, write: bool):
    """A path ending in .gz is gzip-compressed (a cassette is about 80 MB raw, about a tenth of that packed)."""
    return gzip.open(path, "wt" if write else "rt", encoding="utf-8") if path.endswith(".gz") else open(path, "w" if write else "r", encoding="utf-8")


def _save() -> None:
    if mode() == "record":
        with _open(_path(), True) as fh:
            json.dump({"http": _HTTP, "browser": _BROWSER}, fh)


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    if mode() == "replay":
        with _open(_path(), False) as fh:
            data = json.load(fh)
        _HTTP.update(data["http"])
        _BROWSER.update(data["browser"])
        _real_sleep = asyncio.sleep

        async def _fast_sleep(delay, result=None):          # the sources' politeness pauses have no point offline
            return await _real_sleep(0, result)
        asyncio.sleep = _fast_sleep                          # type: ignore[assignment]
    else:
        atexit.register(_save)


def _next(store: dict[str, list[dict]], key: str) -> dict | None:
    entries = store.get(key)
    if not entries:
        return None
    i = _cursor.get(key, 0)
    _cursor[key] = i + 1
    return entries[min(i, len(entries) - 1)]


# ---- httpx ---------------------------------------------------------------------------------------------------

class _RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.inner = httpx.AsyncHTTPTransport(http2=True)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        key = _key(request.method, str(request.url), hashlib.sha1(body).hexdigest())
        try:
            resp = await self.inner.handle_async_request(request)
            content = await resp.aread()
        except Exception as err:                              # noqa: BLE001 - a failure is part of the recording too
            _HTTP.setdefault(key, []).append({"error": type(err).__name__, "message": str(err)[:200]})
            raise
        headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
        _HTTP.setdefault(key, []).append({"status": resp.status_code, "headers": headers, "content": base64.b64encode(content).decode()})
        return httpx.Response(resp.status_code, headers=headers, content=content, request=request)


class _ReplayTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        entry = _next(_HTTP, _key(request.method, str(request.url), hashlib.sha1(body).hexdigest()))
        if entry is None:
            raise httpx.ConnectError(f"not in the cassette: {request.method} {request.url}", request=request)
        if "error" in entry:
            raise httpx.ConnectError(f"recorded failure {entry['error']}: {entry['message']}", request=request)
        return httpx.Response(entry["status"], headers=entry["headers"], content=base64.b64decode(entry["content"]), request=request)


def http_transport() -> httpx.AsyncBaseTransport | None:
    m = mode()
    if not m:
        return None
    _load()
    return _RecordingTransport() if m == "record" else _ReplayTransport()


# ---- browser -------------------------------------------------------------------------------------------------

class _Page:
    def __init__(self, page: Any | None) -> None:
        self.page = page
        self.url = ""                                         # the last page opened: an evaluate() answer belongs to it

    async def goto(self, url: str, **kw: Any) -> Any:
        self.url = url
        key = _key("goto", url)
        if self.page is None:
            entry = _next(_BROWSER, key)
            if entry is None:
                raise RuntimeError(f"not in the cassette: goto {url}")
            if "error" in entry:
                raise RuntimeError(f"recorded failure: {entry['error']}")
            return None
        try:
            await self.page.goto(url, **kw)
        except Exception as err:                              # noqa: BLE001
            _BROWSER.setdefault(key, []).append({"error": f"{type(err).__name__}: {str(err)[:200]}"})
            raise
        _BROWSER.setdefault(key, []).append({"value": None})

    async def evaluate(self, js: str, arg: Any = None) -> Any:
        base = (js, json.dumps(arg, sort_keys=True, default=str))
        key = _key("evaluate", self.url, *base)               # keyed by the open page too, so concurrent pages cannot swap answers
        if self.page is None:
            entry = _next(_BROWSER, key) or _next(_BROWSER, _key("evaluate", *base))      # older cassettes have no page in the key
            if entry is None:
                raise RuntimeError("not in the cassette: evaluate " + js.strip()[:60])
            if "error" in entry:
                raise RuntimeError(f"recorded failure: {entry['error']}")
            return entry["value"]
        try:
            value = await (self.page.evaluate(js, arg) if arg is not None else self.page.evaluate(js))
        except Exception as err:                              # noqa: BLE001
            _BROWSER.setdefault(key, []).append({"error": f"{type(err).__name__}: {str(err)[:200]}"})
            raise
        _BROWSER.setdefault(key, []).append({"value": value})
        return value

    def __getattr__(self, name: str) -> Any:                  # anything else (content, wait_for_*) goes to the real page when recording
        if self.page is None:
            raise AttributeError(name)
        return getattr(self.page, name)


class _Context:
    def __init__(self, ctx: Any | None) -> None:
        self.ctx = ctx

    async def new_page(self) -> _Page:
        return _Page(await self.ctx.new_page() if self.ctx is not None else None)

    def __getattr__(self, name: str) -> Any:                  # add_init_script / new_cdp_session exist only on a real context: replay skips them (sofascore checks hasattr)
        if self.ctx is None:
            raise AttributeError(name)
        return getattr(self.ctx, name)


class _Browser:
    def __init__(self, browser: Any | None) -> None:
        self.browser = browser

    async def new_context(self, **kw: Any) -> _Context:
        return _Context(await self.browser.new_context(**kw) if self.browser is not None else None)

    async def close(self) -> None:
        if self.browser is not None:
            await self.browser.close()


def wrap_browser_cm(real_cm_factory):
    """Returns an async context manager yielding the recording or replaying browser, or None when neither mode is on."""
    m = mode()
    if not m:
        return None
    _load()

    @asynccontextmanager
    async def cm():
        if m == "replay":
            yield _Browser(None)
            return
        async with real_cm_factory() as real:
            yield _Browser(real)
    return cm()
