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
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import Browser, async_playwright


@asynccontextmanager
async def launch_browser() -> AsyncIterator[Browser]:
    """Async context manager yielding a launched headless Chromium Browser,
    closed (and its Playwright driver stopped) on exit."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            await browser.close()
