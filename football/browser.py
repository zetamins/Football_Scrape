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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Browser

_DEFAULT_TIMEOUT_MS = 30000
# See _WebViewPage.goto()'s comment. Not a guess: live navigation-event
# logging against worldfootball.net (Cloudflare-protected) showed its
# challenge triggering a second same-URL navigation that took ~51s
# end-to-end to complete on this emulator's constrained CPU -- a 60000ms
# floor passed by a matter of seconds in that run and failed outright in
# earlier ones. 90s gives real margin above the observed worst case
# rather than sitting right at its edge.
_ANDROID_MIN_GOTO_TIMEOUT_MS = 90000


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

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = _DEFAULT_TIMEOUT_MS) -> None:  # NOSONAR(S7483)
        # wait_until is accepted for call-site parity with the Playwright
        # API but not distinguished here -- WebView's onPageFinished is a
        # single approximation of "the page is ready" (see
        # WebViewRenderer.kt's goto() docstring), not a menu of Playwright's
        # finer-grained load-state options.
        #
        # SonarQube's S7483 wants an asyncio.timeout() context manager
        # instead of a plain `timeout` parameter -- not applicable here:
        # this timeout is a plain value forwarded to WebViewRenderer.kt's
        # own Kotlin-side wait/timeout handling (via asyncio.to_thread
        # below), not something this coroutine cancels itself. The actual
        # enforcement happens in Kotlin, outside asyncio's reach.
        #
        # timeout is floored, not passed straight through: worldfootball.py
        # hard-codes timeout=30000 in its one page.goto() call, written
        # against the desktop Playwright backend (real Chromium). Confirmed
        # live, twice, that WebView running under an Android emulator hits
        # that exact 30s ceiling against the same Cloudflare-protected site
        # Playwright handles within it -- consistent with, not contradicting,
        # this project's own prior finding (sofascore.py's docstring) that
        # this kind of challenge can take "2s to 40s+". The floor is scoped
        # to this backend only, not a change to worldfootball.py's own
        # platform-neutral call, since the slowness is specifically the
        # WebView-under-emulation execution environment, not the site.
        effective_timeout = max(timeout, _ANDROID_MIN_GOTO_TIMEOUT_MS)
        ok = await asyncio.to_thread(self._renderer.goto, url, effective_timeout)
        if not ok:
            raise RuntimeError(f"WebView navigation to {url} did not finish within {effective_timeout}ms")

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

    # Must stay async -- callers do `await context.new_page()` for parity
    # with Playwright's real (genuinely async) BrowserContext.new_page(),
    # even though this particular implementation has nothing to await.
    async def new_page(self) -> _WebViewPage:  # NOSONAR(S7503)
        return _WebViewPage(self._renderer)


class _WebViewBrowser:
    """Playwright Browser-compatible subset (new_context, close)."""

    def __init__(self, renderer: Any) -> None:
        self._renderer = renderer

    async def new_context(self, user_agent: str | None = None) -> _WebViewContext:
        # Deliberately NOT passing user_agent through, even though every
        # call site sets one -- they all use http.py's USER_AGENT, a
        # desktop Windows Chrome string, chosen when this project only
        # targeted Playwright's real desktop Chromium. Overriding WebView's
        # own UA with that string produces a fingerprint that CLAIMS
        # desktop Windows Chrome while every other signal (touch events,
        # mobile screen dimensions, navigator.platform, Android's own TLS
        # stack) still says Android -- a strong, well-known bot-detection
        # trigger, and a very plausible explanation for goto() hanging
        # against Cloudflare-protected sites specifically (worldfootball.net
        # confirmed live) far longer than the challenge itself should take.
        # WebView's own default UA already correctly, consistently
        # describes itself as Android Chrome, matching every other signal
        # it presents -- so it's used unmodified here instead.
        await asyncio.to_thread(self._renderer.open, "")
        return _WebViewContext(self._renderer)

    async def close(self) -> None:
        await asyncio.to_thread(self._renderer.close)


@asynccontextmanager
async def _launch_webview_browser() -> AsyncIterator[_WebViewBrowser]:
    from java import jclass

    from .android_bridge import get_application_context

    web_view_renderer_class = jclass("com.football.app.WebViewRenderer")
    renderer = web_view_renderer_class(get_application_context())
    browser = _WebViewBrowser(renderer)
    try:
        yield browser
    finally:
        await browser.close()


@asynccontextmanager
async def _launch_playwright_browser() -> AsyncIterator[Browser]:
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
