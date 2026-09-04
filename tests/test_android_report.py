"""Covers android_report.run_report's own wrapper logic -- JSON
serialization of the final report, and marshaling SourceStatus into the
JSON string on_source_progress hands to Kotlin. run_search itself is
mocked out (see test_orchestrate.py for coverage of run_search's own
on_source_progress call site) so this test is isolated to what this
module actually adds: the callback-shape translation + JSON output."""

import json

from football import android_report
from football.orchestrate import RunSearchResult, SourceStatus


def _fake_result() -> RunSearchResult:
    return RunSearchResult(
        team="Brentford", generated_at="2026-01-01T00:00:00.000Z", statuses=[],
        merged=None, opponent_name=None, form=None, form_source=None,
        opponent_form=None, opponent_form_source=None, merged_profile=None,
        opponent_profile=None, insights=None, venue_details=None,
    )


def test_run_report_returns_valid_json_matching_build_report_json_shape(monkeypatch):
    async def fake_run_search(_team_name, _on_progress, _on_source_progress):
        return _fake_result()

    monkeypatch.setattr(android_report, "run_search", fake_run_search)

    out = android_report.run_report("Brentford")

    assert isinstance(out, str)
    parsed = json.loads(out)
    assert parsed["team"] == "Brentford"
    assert parsed["generatedAt"] == "2026-01-01T00:00:00.000Z"


def test_run_report_forwards_progress_messages_unchanged(monkeypatch):
    async def fake_run_search(_team_name, on_progress, _on_source_progress):
        on_progress("Scraping fotmob...")
        on_progress("Done.")
        return _fake_result()

    monkeypatch.setattr(android_report, "run_search", fake_run_search)

    seen = []
    android_report.run_report("Brentford", on_progress=seen.append)

    assert seen == ["Scraping fotmob...", "Done."]


def test_run_report_serializes_source_status_to_json(monkeypatch):
    async def fake_run_search(_team_name, _on_progress, on_source_progress):
        on_source_progress(SourceStatus(source="fotmob", fixtures_scraped=42))
        on_source_progress(SourceStatus(source="sofascore", fixtures_scraped=0, matches_error="403 blocked"))
        return _fake_result()

    monkeypatch.setattr(android_report, "run_search", fake_run_search)

    seen = []
    android_report.run_report("Brentford", on_source_progress=seen.append)

    assert len(seen) == 2
    first = json.loads(seen[0])
    assert first == {
        "source": "fotmob", "fixtures_scraped": 42,
        "matches_error": None, "details_error": None, "profile_error": None,
    }
    second = json.loads(seen[1])
    assert second["source"] == "sofascore"
    assert second["matches_error"] == "403 blocked"


def test_run_report_defaults_are_noop_when_no_callbacks_given(monkeypatch):
    """Kotlin passing neither callback (a plain status check, e.g.) must
    not raise -- both parameters have working no-op defaults."""

    async def fake_run_search(_team_name, on_progress, on_source_progress):
        on_progress("hello")
        on_source_progress(SourceStatus(source="goal", fixtures_scraped=1))
        return _fake_result()

    monkeypatch.setattr(android_report, "run_search", fake_run_search)

    out = android_report.run_report("Brentford")
    assert json.loads(out)["team"] == "Brentford"
