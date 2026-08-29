import builtins

import pytest

from football.browser import launch_browser


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

    with pytest.raises(RuntimeError, match="isn't available on this platform"):
        async def _use_it():
            async with launch_browser():
                pass

        import asyncio

        asyncio.run(_use_it())
