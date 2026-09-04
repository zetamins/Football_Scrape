import asyncio
import json

import pytest

from football.browser import _WebViewBrowser, _WebViewContext, _WebViewPage


class _FakeRenderer:
    """Stands in for WebViewRenderer.kt's Java object -- same three
    methods (open/goto/evaluate), same call signatures, same return
    shapes (goto -> bool, evaluate -> JSON string). Lets the Python-side
    marshalling/error-handling logic be tested without Chaquopy/Android."""

    def __init__(self):
        self.opened_with = None
        self.goto_calls = []
        self.evaluate_calls = []
        self.goto_result = True
        self.evaluate_result = json.dumps({"ok": True, "value": None})

    def open(self, user_agent):
        self.opened_with = user_agent

    def goto(self, url, timeout_ms):
        self.goto_calls.append((url, timeout_ms))
        return self.goto_result

    def evaluate(self, script, arg_json, timeout_ms):
        self.evaluate_calls.append((script, arg_json, timeout_ms))
        return self.evaluate_result

    def close(self):
        pass


def test_new_context_never_overrides_webviews_own_user_agent():
    # Confirmed live: overriding WebView's UA with the desktop Chrome
    # string every call site passes (http.py's USER_AGENT, chosen for
    # Playwright's real desktop Chromium) produces a fingerprint that
    # claims desktop Windows while every other WebView signal (touch
    # events, mobile screen, Android's TLS stack) still says Android --
    # a strong bot-detection trigger against Cloudflare-protected sites.
    # WebView's own default UA is used instead, regardless of what the
    # caller asks for -- the parameter stays accepted for Playwright
    # interface parity, just intentionally unused on this backend.
    renderer = _FakeRenderer()
    browser = _WebViewBrowser(renderer)
    ctx = asyncio.run(browser.new_context(user_agent="TestAgent/1.0"))
    assert renderer.opened_with == ""
    assert isinstance(ctx, _WebViewContext)


def test_new_page_returns_a_page_bound_to_the_same_renderer():
    renderer = _FakeRenderer()
    ctx = _WebViewContext(renderer)
    page = asyncio.run(ctx.new_page())
    assert isinstance(page, _WebViewPage)


def test_goto_succeeds_silently_when_renderer_reports_loaded():
    renderer = _FakeRenderer()
    renderer.goto_result = True
    page = _WebViewPage(renderer)
    asyncio.run(page.goto("https://example.com", timeout=90000))
    assert renderer.goto_calls == [("https://example.com", 90000)]


def test_goto_floors_a_short_caller_timeout():
    # Confirmed live: worldfootball.py hard-codes timeout=30000 (written
    # against desktop Playwright), but WebView under an Android emulator
    # measurably needs longer for the same Cloudflare-protected site --
    # navigation-event logging showed its challenge's second same-URL
    # navigation taking ~51s end-to-end on this emulator's constrained CPU.
    renderer = _FakeRenderer()
    renderer.goto_result = True
    page = _WebViewPage(renderer)
    asyncio.run(page.goto("https://example.com", timeout=30000))
    _url, effective_timeout = renderer.goto_calls[0]
    assert effective_timeout >= 90000


def test_goto_does_not_shrink_an_already_generous_caller_timeout():
    renderer = _FakeRenderer()
    renderer.goto_result = True
    page = _WebViewPage(renderer)
    asyncio.run(page.goto("https://example.com", timeout=150000))
    _url, effective_timeout = renderer.goto_calls[0]
    assert effective_timeout == 150000


def test_goto_raises_when_renderer_reports_not_loaded():
    renderer = _FakeRenderer()
    renderer.goto_result = False
    page = _WebViewPage(renderer)
    coro = page.goto("https://example.com", timeout=5000)
    with pytest.raises(RuntimeError, match="did not finish"):
        asyncio.run(coro)


def test_evaluate_with_no_arg_passes_none_as_arg_json():
    renderer = _FakeRenderer()
    renderer.evaluate_result = json.dumps({"ok": True, "value": "hello"})
    page = _WebViewPage(renderer)
    result = asyncio.run(page.evaluate("() => document.title"))
    assert result == "hello"
    _script, arg_json, _timeout = renderer.evaluate_calls[0]
    assert arg_json is None


def test_evaluate_json_encodes_the_arg():
    renderer = _FakeRenderer()
    renderer.evaluate_result = json.dumps({"ok": True, "value": {"items": []}})
    page = _WebViewPage(renderer)
    result = asyncio.run(page.evaluate("(x) => x", {"nonce": "abc", "n": 3}))
    assert result == {"items": []}
    _script, arg_json, _timeout = renderer.evaluate_calls[0]
    assert json.loads(arg_json) == {"nonce": "abc", "n": 3}


def test_evaluate_raises_with_the_js_side_error_message():
    renderer = _FakeRenderer()
    renderer.evaluate_result = json.dumps({"ok": False, "error": "boom"})
    page = _WebViewPage(renderer)
    coro = page.evaluate("() => { throw new Error('boom') }")
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(coro)
