"""Real headless-Chromium access, isolated behind one module.

Ported from src/browserLaunch.ts, simplified: the original branched on
`process.env.VERCEL` to swap in a Lambda-compatible Chromium build for a
server deployment. This project no longer targets a server at all (backend
runs embedded in a client, per the user), so that branch is gone -- this
just launches the local Playwright-installed Chromium.

Deliberately kept as the ONE module the browser-dependent scrapers
(sofascore, squawka, worldfootball) import for browser access, rather than
importing Playwright directly -- on Android, headless Chromium can't run
inside the app sandbox at all, so this module instead drives Android's
built-in WebView (android/app/src/main/java/com/football/app/
WebViewRenderer.kt) through Chaquopy's Java interop. Isolating the
dependency here means the swap only touches this file, not the three call
sites -- sofascore.py/squawka.py/worldfootball.py call launch_browser()
and use browser.new_context()/context.new_page()/page.goto()/
page.evaluate() exactly the same way regardless of which backend answers.

Playwright itself is imported lazily, inside _launch_playwright_browser(),
rather than at module level -- Playwright needs a full Chromium binary +
Node-based driver subprocess, which can't run inside an Android app sandbox
at all (not just "hard to pip install"; architecturally unavailable
regardless of packaging). A module-level import would make importing this
module -- and therefore importing football.orchestrate, and therefore
every plain-HTTP source that has nothing to do with a browser -- fail
outright wherever Playwright isn't installed. Now football.browser imports
cleanly everywhere; only actually calling launch_browser() (i.e. actually
trying to use one of the 3 browser-based sources) requires either
Playwright or (on Android) the WebView bridge, and fails with a clear
error rather than a raw ModuleNotFoundError if neither is available."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

if TYPE_CHECKING:
    from playwright.async_api import Browser

_DEFAULT_TIMEOUT_MS = 30000


def _is_android() -> bool:
    """Chaquopy always provides a builtin `java` module for Java interop;
    it's only ever importable when actually running under Chaquopy on
    Android, which makes it a reliable, dependency-free platform check --
    no undocumented sys.platform value or env var needed."""
    try:
        import java  # noqa: F401
        return True
    except ImportError:
        return False


class _WebViewPage:
    """Playwright Page-compatible subset (goto, evaluate) backed by
    WebViewRenderer.kt. Every call is a blocking Java method invocation
    handed to a worker thread via asyncio.to_thread, since Chaquopy calls
    into Kotlin block the calling Python thread, and blocking the asyncio
    event loop thread directly would stall every other concurrent
    coroutine (there normally aren't any here, but this keeps the
    contract honest regardless)."""

    def __init__(self, renderer: Any) -> None:
        self._renderer = renderer

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = _DEFAULT_TIMEOUT_MS) -> None:
        # wait_until is accepted for call-site parity with the Playwright
        # API but not distinguished here -- WebView's onPageFinished is a
        # single approximation of "the page is ready" (see
        # WebViewRenderer.kt's goto() docstring), not a menu of Playwright's
        # finer-grained load-state options.
        ok = await asyncio.to_thread(self._renderer.goto, url, timeout)
        if not ok:
            raise RuntimeError(f"WebView navigation to {url} did not finish within {timeout}ms")

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        arg_json = json.dumps(arg) if arg is not None else None
        raw = await asyncio.to_thread(self._renderer.evaluate, script, arg_json, _DEFAULT_TIMEOUT_MS)
        result = json.loads(str(raw))
        if not result.get("ok"):
            raise RuntimeError(f"WebView evaluate() failed: {result.get('error')}")
        return result.get("value")


class _WebViewContext:
    def __init__(self, renderer: Any) -> None:
        self._renderer = renderer

    async def new_page(self) -> _WebViewPage:
        return _WebViewPage(self._renderer)


class _WebViewBrowser:
    """Playwright Browser-compatible subset (new_context, close)."""

    def __init__(self, renderer: Any) -> None:
        self._renderer = renderer

    async def new_context(self, user_agent: Optional[str] = None) -> _WebViewContext:
        await asyncio.to_thread(self._renderer.open, user_agent or "")
        return _WebViewContext(self._renderer)

    async def close(self) -> None:
        await asyncio.to_thread(self._renderer.close)


@asynccontextmanager
async def _launch_webview_browser() -> AsyncIterator[_WebViewBrowser]:
    from java import jclass

    from .android_bridge import get_application_context

    WebViewRenderer = jclass("com.football.app.WebViewRenderer")
    renderer = WebViewRenderer(get_application_context())
    browser = _WebViewBrowser(renderer)
    try:
        yield browser
    finally:
        await browser.close()


@asynccontextmanager
async def _launch_playwright_browser() -> AsyncIterator["Browser"]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as err:
        raise RuntimeError(
            "Real-browser access (Sofascore/Squawka/worldfootball) isn't "
            "available on this platform -- Playwright isn't installed."
        ) from err
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            await browser.close()


def launch_browser() -> AsyncIterator[Any]:
    """Async context manager yielding a launched browser -- real headless
    Chromium via Playwright everywhere except Android, WebView-backed on
    Android. Callers (sofascore.py/squawka.py/worldfootball.py) don't
    branch on platform themselves; this is the one place that does."""
    if _is_android():
        return _launch_webview_browser()
    return _launch_playwright_browser()
