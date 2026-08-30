"""Covers run_search's on_source_progress hook specifically -- the rest
of run_search is an integration-level pipeline across 13 live sources
with no existing unit coverage (nothing here mocks that far), so this
stays scoped to the one thing this session added: does on_source_progress
fire once per source, with the real SourceStatus the source produced.

All 5 SCRAPERS are monkeypatched to fail fast with no network access, so
`merged` stays None and run_search returns right after the per-source
loop -- keeps this test isolated to that loop instead of exercising the
whole downstream pipeline. Driven via asyncio.run(), same as
android_report.py/cli.py do at their own call sites -- no async test
runner is configured in this project, so tests stay synchronous
functions that drive the coroutine themselves rather than adding one."""

import asyncio

from football import orchestrate
from football.merge import SOURCE_ORDER
from football.orchestrate import _Scraper, run_search


def test_on_source_progress_fires_once_per_source_with_real_status(monkeypatch):
    async def failing_run(_team_name):
        raise RuntimeError("boom")

    async def failing_profile(_team_name):
        raise RuntimeError("boom")

    fake_scrapers = {
        source: _Scraper(run=failing_run, details=failing_run, profile=failing_profile)
        for source in SOURCE_ORDER
    }
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    seen = []
    asyncio.run(run_search("Some Team", on_source_progress=seen.append))

    assert [status.source for status in seen] == list(SOURCE_ORDER)
    for status in seen:
        assert status.fixtures_scraped == 0
        assert status.matches_error == "boom"
        assert status.profile_error == "boom"


def test_on_source_progress_reports_fixtures_scraped(monkeypatch):
    async def one_match(_team_name):
        return []  # empty list is enough: exercises the success path, no MatchInfo shape needed

    async def failing(_team_name):
        raise RuntimeError("no profile")

    async def details(_match):
        raise AssertionError("should not be called -- no matches means no next_match()")

    fake_scrapers = {
        source: _Scraper(run=one_match, details=details, profile=failing)
        for source in SOURCE_ORDER
    }
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    seen = []
    asyncio.run(run_search("Some Team", on_source_progress=seen.append))

    assert len(seen) == len(SOURCE_ORDER)
    for status in seen:
        assert status.fixtures_scraped == 0
        assert status.matches_error is None
        assert status.profile_error == "no profile"
