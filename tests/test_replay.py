"""Record/replay cassette: deterministic offline comparison of scraper copies."""
import asyncio
import json

import httpx
import pytest

from football import replay


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    for store in (replay._HTTP, replay._BROWSER, replay._cursor):
        store.clear()
    monkeypatch.setattr(replay, "_loaded", False)
    monkeypatch.delenv("FOOTBALL_RECORD", raising=False)
    monkeypatch.delenv("FOOTBALL_REPLAY", raising=False)
    monkeypatch.setattr(replay.atexit, "register", lambda f: None)
    real_sleep = asyncio.sleep
    yield
    asyncio.sleep = real_sleep


def test_off_by_default():
    assert replay.mode() is None and replay.http_transport() is None and replay.wrap_browser_cm(lambda: None) is None


def test_http_record_then_replay_roundtrip(monkeypatch, tmp_path):
    cassette = tmp_path / "c.json"
    monkeypatch.setenv("FOOTBALL_RECORD", str(cassette))
    rec = replay._RecordingTransport()
    rec.inner = httpx.MockTransport(lambda req: httpx.Response(200, json={"a": 1}, headers={"x-k": "v"}) if req.url.path == "/ok" else httpx.Response(503, text="busy"))

    async def go():
        async with httpx.AsyncClient(transport=rec) as c:
            return (await c.get("https://s.test/ok")).json(), (await c.get("https://s.test/bad")).status_code
    assert asyncio.run(go()) == ({"a": 1}, 503)
    replay._save()
    data = json.loads(cassette.read_text())
    assert len(data["http"]) == 2

    monkeypatch.delenv("FOOTBALL_RECORD")
    monkeypatch.setenv("FOOTBALL_REPLAY", str(cassette))
    replay._HTTP.clear()
    replay._load()

    async def again():
        async with httpx.AsyncClient(transport=replay._ReplayTransport()) as c:
            ok = await c.get("https://s.test/ok")
            bad = await c.get("https://s.test/bad")
            with pytest.raises(httpx.ConnectError):
                await c.get("https://s.test/never-recorded")
            return ok.json(), ok.headers["x-k"], bad.status_code
    assert asyncio.run(again()) == ({"a": 1}, "v", 503)


def test_repeated_request_replays_answers_in_order_then_repeats_last():
    replay._HTTP["k"] = [{"status": 200, "headers": [], "content": ""}, {"status": 500, "headers": [], "content": ""}]
    assert [replay._next(replay._HTTP, "k")["status"] for _ in range(3)] == [200, 500, 500]


class _FakePage:
    def __init__(self):
        self.calls = []

    async def goto(self, url, **kw):
        self.calls.append(("goto", url))

    async def evaluate(self, js, arg=None):
        self.calls.append(("evaluate", js))
        if "boom" in js:
            raise RuntimeError("page crashed")
        return {"nonce": "n1", "arg": arg}


def test_browser_record_then_replay(monkeypatch, tmp_path):
    cassette = tmp_path / "b.json"
    monkeypatch.setenv("FOOTBALL_RECORD", str(cassette))
    page = _FakePage()

    async def record():
        p = replay._Page(page)
        await p.goto("https://x.test/p", timeout=1)
        v = await p.evaluate("() => 1", {"id": 7})
        with pytest.raises(RuntimeError):
            await p.evaluate("boom")
        return v
    assert asyncio.run(record()) == {"nonce": "n1", "arg": {"id": 7}}
    replay._save()
    monkeypatch.delenv("FOOTBALL_RECORD")
    monkeypatch.setenv("FOOTBALL_REPLAY", str(cassette))
    replay._BROWSER.clear()
    replay._cursor.clear()
    replay._load()

    async def play():
        p = replay._Page(None)
        await p.goto("https://x.test/p")
        v = await p.evaluate("() => 1", {"id": 7})
        for js in ("boom", "() => never"):
            with pytest.raises(RuntimeError):
                await p.evaluate(js)
        return v
    assert asyncio.run(play()) == {"nonce": "n1", "arg": {"id": 7}}
    assert not hasattr(replay._Context(None), "add_init_script")      # sofascore skips its stealth setup when replaying


def test_hooks_are_wired(monkeypatch, tmp_path):
    from football import browser, http
    monkeypatch.setenv("FOOTBALL_REPLAY", str(tmp_path / "x.json"))
    (tmp_path / "x.json").write_text(json.dumps({"http": {}, "browser": {}}))
    assert type(http.new_client()._transport).__name__ == "_ReplayTransport"

    async def go():
        async with browser.launch_browser() as b:
            return type(b).__name__
    assert asyncio.run(go()) == "_Browser"


def test_gzip_cassette_roundtrip(monkeypatch, tmp_path):
    path = tmp_path / "c.json.gz"
    monkeypatch.setenv("FOOTBALL_RECORD", str(path))
    replay._HTTP["k"] = [{"status": 200, "headers": [], "content": "aGk="}]
    replay._save()
    assert path.read_bytes()[:2] == b"\x1f\x8b"
    monkeypatch.delenv("FOOTBALL_RECORD")
    monkeypatch.setenv("FOOTBALL_REPLAY", str(path))
    replay._HTTP.clear()
    replay._load()
    assert replay._HTTP["k"][0]["content"] == "aGk="


def test_evaluate_answers_follow_the_open_page_not_the_call_order(monkeypatch, tmp_path):
    cassette = tmp_path / "p.json"
    monkeypatch.setenv("FOOTBALL_RECORD", str(cassette))

    class Page(_FakePage):
        async def evaluate(self, js, arg=None):
            return f"text of {self.url}"

    async def record():
        a, b = replay._Page(Page()), replay._Page(Page())
        a.page.url, b.page.url = "https://a.test/", "https://b.test/"
        await a.goto("https://a.test/")
        await b.goto("https://b.test/")
        return await a.evaluate("() => document.body.innerText"), await b.evaluate("() => document.body.innerText")
    asyncio.run(record())
    replay._save()
    monkeypatch.delenv("FOOTBALL_RECORD")
    monkeypatch.setenv("FOOTBALL_REPLAY", str(cassette))
    replay._BROWSER.clear()
    replay._cursor.clear()
    replay._load()

    async def play():                                         # replay asks b first: with order-based keys the answers would swap
        a, b = replay._Page(None), replay._Page(None)
        await a.goto("https://a.test/")
        await b.goto("https://b.test/")
        return await b.evaluate("() => document.body.innerText"), await a.evaluate("() => document.body.innerText")
    assert asyncio.run(play()) == ("text of https://b.test/", "text of https://a.test/")
