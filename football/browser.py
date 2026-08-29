"""Real headless-Chromium access, isolated behind one module.

Ported from src/browserLaunch.ts, simplified: the original branched on
`process.env.VERCEL` to swap in a Lambda-compatible Chromium build for a
server deployment. This project no longer targets a server at all (backend
runs embedded in a client, per the user), so that branch is gone -- this
just launches the local Playwright-installed Chromium.

Deliberately kept as the ONE module the browser-dependent scrapers
(sofascore, squawka, worldfootball) import for browser access, rather than
importing Playwright directly. When this backend is eventually embedded in
an Android app, headless Chromium won't be available as a subprocess the
way it is here -- the plan is to swap this module's implementation for one
driven by Android's built-in WebView instead. Isolating the dependency here
means that swap only touches this file, not the three call sites.

Playwright itself is imported lazily, inside launch_browser(), rather than
at module level -- Playwright needs a full Chromium binary + Node-based
driver subprocess, which can't run inside an Android app sandbox at all
(not just "hard to pip install"; architecturally unavailable regardless of
packaging). A module-level import would make importing this module -- and
therefore importing football.orchestrate, and therefore every plain-HTTP
source that has nothing to do with a browser -- fail outright wherever
Playwright isn't installed, e.g. under Chaquopy (Python-on-Android). Now
football.browser imports cleanly everywhere; only actually calling
launch_browser() (i.e. actually trying to use one of the 3 browser-based
sources) requires Playwright, and does so with a clear error instead of
Python's raw ModuleNotFoundError."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    from playwright.async_api import Browser


@asynccontextmanager
async def launch_browser() -> AsyncIterator["Browser"]:
    """Async context manager yielding a launched headless Chromium Browser,
    closed (and its Playwright driver stopped) on exit."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as err:
        raise RuntimeError(
            "Real-browser access (Sofascore/Squawka/worldfootball) isn't "
            "available on this platform -- Playwright isn't installed. On "
            "Android this is expected: it needs a WebView-backed "
            "implementation of this function instead, not yet built."
        ) from err
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            await browser.close()
