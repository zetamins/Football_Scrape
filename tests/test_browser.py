import asyncio
import builtins
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

import football.browser as browser_module
from football.browser import (
    _is_android,
    _WebViewBrowser,
    _WebViewContext,
    _WebViewPage,
    launch_browser,
)


def test_launch_browser_raises_clear_error_when_playwright_unavailable(monkeypatch):
    # Simulates Chaquopy (Python-on-Android), where Playwright can't be
    # installed at all -- confirms football.browser (and, transitively,
    # football.orchestrate and the plain-HTTP sources) still imports fine,
    # and only actually trying to use a browser-based source fails, with a
    # clear message rather than a raw ModuleNotFoundError.
    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "playwright" or name.startswith("playwright."):
            raise ModuleNotFoundError("No module named 'playwright'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    async def _use_it():
        async with launch_browser():
            pass

    # Only the one call actually expected to raise (asyncio.run) is
    # inside the pytest.raises block -- the closure/coroutine setup
    # above runs unconditionally, so a failure there would show up as an
    # ordinary test error rather than being ambiguously attributed to
    # "the exception under test". Constructing the coroutine object
    # (_use_it()) is hoisted out too -- it can't itself raise (no code
    # inside a coroutine runs until awaited), but python:S5778 flags any
    # nested call expression inside pytest.raises regardless.
    coro = _use_it()
    with pytest.raises(RuntimeError, match="isn't available on this platform"):
        asyncio.run(coro)


def test_launch_browser_uses_real_playwright_chromium_end_to_end():
    # No mocking here at all -- Playwright and its Chromium binary are
    # actually installed in this environment (confirmed live), so this
    # exercises the genuine success path (_launch_playwright_browser's
    # own launch/close, not just the ImportError fallback the test above
    # covers) exactly the way sofascore.py/squawka.py/worldfootball.py
    # use it: async with launch_browser() as browser, then
    # new_context()/new_page()/goto()/evaluate().
    async def _use_it():
        async with launch_browser() as browser:
            context = await browser.new_context(user_agent="test-agent")
            page = await context.new_page()
            await page.goto("about:blank")
            return await page.evaluate("() => 1 + 1")

    assert asyncio.run(_use_it()) == 2


# --- _is_android -----------------------------------------------------------------------------


def test_is_android_false_when_java_module_unavailable():
    assert "java" not in sys.modules
    assert _is_android() is False


def test_is_android_true_when_java_module_importable(monkeypatch):
    fake_java = ModuleType("java")
    monkeypatch.setitem(sys.modules, "java", fake_java)
    assert _is_android() is True


# --- launch_browser dispatch ------------------------------------------------------------------


def test_launch_browser_dispatches_to_webview_backend_on_android(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(browser_module, "_is_android", lambda: True)
    monkeypatch.setattr(browser_module, "_launch_webview_browser", lambda: sentinel)
    assert launch_browser() is sentinel


def test_launch_browser_dispatches_to_playwright_backend_off_android(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(browser_module, "_is_android", lambda: False)
    monkeypatch.setattr(browser_module, "_launch_playwright_browser", lambda: sentinel)
    assert launch_browser() is sentinel


# --- _WebViewPage ------------------------------------------------------------------------------


class _FakeRenderer:
    def __init__(self, goto_result=True, evaluate_result='{"ok": true, "value": 42}'):
        self._goto_result = goto_result
        self._evaluate_result = evaluate_result
        self.goto_calls = []
        self.evaluate_calls = []
        self.open_calls = []
        self.close_calls = 0

    def goto(self, url, timeout):
        self.goto_calls.append((url, timeout))
        return self._goto_result

    def evaluate(self, script, arg_json, timeout):
        self.evaluate_calls.append((script, arg_json, timeout))
        return self._evaluate_result

    def open(self, url):
        self.open_calls.append(url)

    def close(self):
        self.close_calls += 1


def test_webview_page_goto_succeeds_and_floors_the_timeout():
    renderer = _FakeRenderer(goto_result=True)
    page = _WebViewPage(renderer)
    asyncio.run(page.goto("https://example.com", timeout=1000))
    url, timeout = renderer.goto_calls[0]
    assert url == "https://example.com"
    # A 1000ms request must be floored to the Android WebView minimum,
    # not passed straight through -- see _ANDROID_MIN_GOTO_TIMEOUT_MS's
    # own comment for why the desktop-tuned per-call values aren't
    # trustworthy under WebView/emulation.
    assert timeout == 90000


def test_webview_page_goto_raises_when_navigation_does_not_finish():
    renderer = _FakeRenderer(goto_result=False)
    page = _WebViewPage(renderer)
    with pytest.raises(RuntimeError, match="did not finish"):
        asyncio.run(page.goto("https://example.com"))


def test_webview_page_evaluate_returns_value_on_success():
    renderer = _FakeRenderer(evaluate_result='{"ok": true, "value": [1, 2, 3]}')
    page = _WebViewPage(renderer)
    result = asyncio.run(page.evaluate("() => [1,2,3]"))
    assert result == [1, 2, 3]


def test_webview_page_evaluate_serializes_the_arg_as_json():
    renderer = _FakeRenderer()
    page = _WebViewPage(renderer)
    asyncio.run(page.evaluate("(x) => x", arg={"a": 1}))
    _script, arg_json, _timeout = renderer.evaluate_calls[0]
    assert json.loads(arg_json) == {"a": 1}


def test_webview_page_evaluate_omits_arg_json_when_no_arg_given():
    renderer = _FakeRenderer()
    page = _WebViewPage(renderer)
    asyncio.run(page.evaluate("() => 1"))
    _script, arg_json, _timeout = renderer.evaluate_calls[0]
    assert arg_json is None


def test_webview_page_evaluate_raises_when_result_not_ok():
    renderer = _FakeRenderer(evaluate_result='{"ok": false, "error": "boom"}')
    page = _WebViewPage(renderer)
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(page.evaluate("() => 1"))


# --- _WebViewContext / _WebViewBrowser -----------------------------------------------------


def test_webview_context_new_page_wraps_same_renderer():
    renderer = _FakeRenderer()
    context = _WebViewContext(renderer)
    page = asyncio.run(context.new_page())
    assert isinstance(page, _WebViewPage)
    assert page._renderer is renderer


def test_webview_browser_new_context_opens_with_empty_url_ignoring_user_agent():
    # Deliberately does NOT forward user_agent to the renderer -- see
    # new_context's own comment on why overriding WebView's real Android
    # UA is itself a bot-detection trigger.
    renderer = _FakeRenderer()
    browser = _WebViewBrowser(renderer)
    context = asyncio.run(browser.new_context(user_agent="Desktop Chrome UA"))
    assert isinstance(context, _WebViewContext)
    assert renderer.open_calls == [""]


def test_webview_browser_close_closes_the_renderer():
    renderer = _FakeRenderer()
    browser = _WebViewBrowser(renderer)
    asyncio.run(browser.close())
    assert renderer.close_calls == 1


# --- _launch_webview_browser (Android bridge, java module faked) -----------------------------


def test_launch_webview_browser_creates_renderer_and_closes_on_exit(monkeypatch):
    created_with = []

    class _FakeRendererClass:
        def __init__(self, context):
            created_with.append(context)
            self.closed = False

        def close(self):
            self.closed = True

    def fake_jclass(name):
        assert name == "com.football.app.WebViewRenderer"
        return _FakeRendererClass

    fake_java = ModuleType("java")
    fake_java.jclass = fake_jclass
    monkeypatch.setitem(sys.modules, "java", fake_java)

    fake_context = object()
    fake_android_bridge = SimpleNamespace(get_application_context=lambda: fake_context)
    monkeypatch.setitem(sys.modules, "football.android_bridge", fake_android_bridge)

    async def _use_it():
        async with browser_module._launch_webview_browser() as browser:
            assert isinstance(browser, _WebViewBrowser)
            return browser._renderer

    renderer = asyncio.run(_use_it())
    assert created_with == [fake_context]
    assert renderer.closed is True
