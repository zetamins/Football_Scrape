"""Proof-of-concept bridge for MainActivity.kt to call, to verify the
WebView browser backend (browser.py's Android branch) works end to end
against a real site. Not part of the actual scraping pipeline --
orchestrate.py/cli.py call the sites/ modules directly.

Exists as a plain synchronous function because Chaquopy's Java-calls-
Python interop has no concept of awaiting a coroutine -- Kotlin calls a
regular callable and gets a regular return value, so the async entry
point is wrapped in asyncio.run() here rather than asking Kotlin to
understand Python's async machinery."""

from __future__ import annotations

import asyncio

from .browser import launch_browser
from .http import USER_AGENT
from .sites.worldfootball import _COMPETITION_PATHS, _fetch_referee_table, get_referee_worldfootball_stats


async def _diagnose(competition: str, referee_name: str) -> str:
    """Reports the raw row count/names too, not just the final match --
    get_referee_worldfootball_stats itself catches every exception
    internally (mirrors the TS original's catch-all) and returns None for
    both "evaluate failed" and "genuinely no match", which look identical
    from test_worldfootball_referee_stats alone."""
    path = _COMPETITION_PATHS.get(competition)
    if not path:
        return f"Unknown competition: {competition}"
    async with launch_browser() as browser:
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()
        rows = await _fetch_referee_table(page, path)
        names = ", ".join(r.name for r in rows[:5])
        return f"{len(rows)} rows scraped. First few: {names}"


def run_worldfootball_referee_stats(competition: str, referee_name: str) -> str:
    # Not named test_* -- pytest's default collection pattern would try
    # to run this as a test itself (parameters looking like unresolvable
    # fixtures) despite testpaths already excluding this file's directory.
    result = asyncio.run(get_referee_worldfootball_stats(competition, referee_name))
    if result is not None:
        return f"penalties={result.penalties}, second_yellow={result.second_yellow}"
    diagnosis = asyncio.run(_diagnose(competition, referee_name))
    return f"No match for '{referee_name}'. Diagnosis: {diagnosis}"
