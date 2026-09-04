import asyncio

import httpx
import pytest

from football.http import USER_AGENT, fetch_json, fetch_text, new_client


def _client_with(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- new_client --------------------------------------------------------------------------


def test_new_client_uses_http2_and_follows_redirects():
    client = new_client()
    assert client.follow_redirects is True
    asyncio.run(client.aclose())


# --- fetch_text ----------------------------------------------------------------------------


def test_fetch_text_returns_body_and_sends_user_agent():
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, text="hello world")

    client = _client_with(handler)
    result = asyncio.run(fetch_text("https://example.com/page", client=client))
    asyncio.run(client.aclose())
    assert result == "hello world"
    assert seen_headers.get("user-agent") == USER_AGENT


def test_fetch_text_raises_on_http_error_status():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    client = _client_with(handler)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(fetch_text("https://example.com/missing", client=client))
    asyncio.run(client.aclose())


def test_fetch_text_creates_and_closes_its_own_client_when_none_given(monkeypatch):
    closed = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="hi")

    class _TrackedClient(httpx.AsyncClient):
        async def aclose(self):
            closed.append(True)
            await super().aclose()

    def fake_new_client():
        return _TrackedClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("football.http.new_client", fake_new_client)
    result = asyncio.run(fetch_text("https://example.com/page"))
    assert result == "hi"
    assert closed == [True]


def test_fetch_text_does_not_close_a_caller_supplied_client():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="hi")

    client = _client_with(handler)
    asyncio.run(fetch_text("https://example.com/page", client=client))
    assert client.is_closed is False
    asyncio.run(client.aclose())


# --- fetch_json ----------------------------------------------------------------------------


def test_fetch_json_returns_parsed_body():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"a": 1, "b": [2, 3]})

    client = _client_with(handler)
    result = asyncio.run(fetch_json("https://example.com/api", client=client))
    asyncio.run(client.aclose())
    assert result == {"a": 1, "b": [2, 3]}


def test_fetch_json_raises_on_http_error_status():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = _client_with(handler)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(fetch_json("https://example.com/api", client=client))
    asyncio.run(client.aclose())


def test_fetch_json_creates_and_closes_its_own_client_when_none_given(monkeypatch):
    closed = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    class _TrackedClient(httpx.AsyncClient):
        async def aclose(self):
            closed.append(True)
            await super().aclose()

    def fake_new_client():
        return _TrackedClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("football.http.new_client", fake_new_client)
    result = asyncio.run(fetch_json("https://example.com/api"))
    assert result == {"ok": True}
    assert closed == [True]
