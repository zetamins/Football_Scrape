import asyncio
from types import SimpleNamespace

from football import android_test
from football.android_test import (
    run_full_report,
    run_sofascore_match_details,
    run_sofascore_matches,
    run_sofascore_team_profile,
    run_squawka_defensive_stats,
    run_worldfootball_referee_stats,
)
from football.sites.worldfootball import WorldfootballRefereeStats


def _match(**overrides):
    from football.types import MatchInfo

    base = {
        "source": "sofascore", "source_url": "https://x", "competition": "Premier League",
        "home_team": "Home FC", "away_team": "Away FC", "kickoff_utc": "2026-01-01T12:00:00.000Z",
        "venue": None, "status": "finished", "home_score": 1, "away_score": 0,
        "home_score_ht": None, "away_score_ht": None, "season": None, "round": None, "match_id": "1",
    }
    base.update(overrides)
    return MatchInfo(**base)


# --- run_worldfootball_referee_stats ---------------------------------------------------------


def test_run_worldfootball_referee_stats_formats_a_real_match(monkeypatch):
    async def fake_get_stats(_competition, _referee_name):
        return WorldfootballRefereeStats(penalties=3, second_yellow=1)

    monkeypatch.setattr(android_test, "get_referee_worldfootball_stats", fake_get_stats)
    result = run_worldfootball_referee_stats("Premier League", "C Pawson")
    assert result == "penalties=3, second_yellow=1"


def test_run_worldfootball_referee_stats_falls_back_to_diagnosis_when_no_match(monkeypatch):
    async def fake_get_stats(_competition, _referee_name):
        return None

    async def fake_diagnose(_competition):
        return "some diagnosis"

    monkeypatch.setattr(android_test, "get_referee_worldfootball_stats", fake_get_stats)
    monkeypatch.setattr(android_test, "_diagnose", fake_diagnose)
    result = run_worldfootball_referee_stats("Premier League", "Unknown Ref")
    assert result == "No match for 'Unknown Ref'. Diagnosis: some diagnosis"


# --- run_sofascore_matches ---------------------------------------------------------------------


def test_run_sofascore_matches_formats_first_match(monkeypatch):
    matches = [_match(home_team="Liverpool", away_team="Arsenal"), _match()]

    async def fake_get_matches(_team_name):
        return matches

    monkeypatch.setattr(android_test, "get_sofascore_matches", fake_get_matches)
    result = run_sofascore_matches("Liverpool")
    assert result == "2 matches. First: Liverpool vs Arsenal (2026-01-01T12:00:00.000Z)"


def test_run_sofascore_matches_reports_zero_matches(monkeypatch):
    async def fake_get_matches(_team_name):
        return []

    monkeypatch.setattr(android_test, "get_sofascore_matches", fake_get_matches)
    result = run_sofascore_matches("Some Team")
    assert result.startswith("0 matches returned")


def test_run_sofascore_matches_reports_exception(monkeypatch):
    async def failing(_team_name):
        raise RuntimeError("boom")

    monkeypatch.setattr(android_test, "get_sofascore_matches", failing)
    result = run_sofascore_matches("Some Team")
    assert result == "FAILED: RuntimeError: boom"


# --- run_sofascore_match_details --------------------------------------------------------------


def test_run_sofascore_match_details_formats_success(monkeypatch):
    match = _match(home_team="Liverpool", away_team="Arsenal")
    details = SimpleNamespace(referee="C Pawson", venue_name="Anfield", head_to_head_summary={"x": 1})

    async def fake_get_matches(_team_name):
        return [match]

    async def fake_get_details(_match):
        return details

    monkeypatch.setattr(android_test, "get_sofascore_matches", fake_get_matches)
    monkeypatch.setattr(android_test, "get_sofascore_match_details", fake_get_details)
    result = run_sofascore_match_details("Liverpool")
    assert result == "OK -- Liverpool vs Arsenal: referee=C Pawson, venue=Anfield, h2h_summary_present=True"


def test_run_sofascore_match_details_fails_without_matches(monkeypatch):
    async def fake_get_matches(_team_name):
        return []

    monkeypatch.setattr(android_test, "get_sofascore_matches", fake_get_matches)
    result = run_sofascore_match_details("Some Team")
    assert "0 matches" in result


def test_run_sofascore_match_details_reports_exception(monkeypatch):
    async def failing(_team_name):
        raise RuntimeError("boom")

    monkeypatch.setattr(android_test, "get_sofascore_matches", failing)
    result = run_sofascore_match_details("Some Team")
    assert result == "FAILED: RuntimeError: boom"


# --- run_sofascore_team_profile -----------------------------------------------------------------


def test_run_sofascore_team_profile_formats_success(monkeypatch):
    profile = SimpleNamespace(squad=[1, 2, 3], recent_transfers=[1], average_age=26.4)

    async def fake_get_profile(_team_name):
        return profile

    monkeypatch.setattr(android_test, "get_sofascore_team_profile", fake_get_profile)
    result = run_sofascore_team_profile("Liverpool")
    assert result == "OK -- squad_size=3, recent_transfers=1, average_age=26.4"


def test_run_sofascore_team_profile_handles_empty_squad_and_transfers(monkeypatch):
    profile = SimpleNamespace(squad=None, recent_transfers=None, average_age=None)

    async def fake_get_profile(_team_name):
        return profile

    monkeypatch.setattr(android_test, "get_sofascore_team_profile", fake_get_profile)
    result = run_sofascore_team_profile("Liverpool")
    assert result == "OK -- squad_size=0, recent_transfers=0, average_age=None"


def test_run_sofascore_team_profile_reports_exception(monkeypatch):
    async def failing(_team_name):
        raise RuntimeError("boom")

    monkeypatch.setattr(android_test, "get_sofascore_team_profile", failing)
    result = run_sofascore_team_profile("Liverpool")
    assert result == "FAILED: RuntimeError: boom"


# --- run_squawka_defensive_stats ----------------------------------------------------------------


def test_run_squawka_defensive_stats_formats_success(monkeypatch):
    async def fake_get_stats(_team_name, _competitions):
        return {"mohamed salah": object(), "virgil van dijk": object()}

    monkeypatch.setattr(android_test, "get_squawka_defensive_stats", fake_get_stats)
    result = run_squawka_defensive_stats("Liverpool", "Premier League")
    assert result.startswith("2 players. First few:")
    assert "mohamed salah" in result


def test_run_squawka_defensive_stats_falls_back_to_diagnosis_when_empty(monkeypatch):
    async def fake_get_stats(_team_name, _competitions):
        return {}

    async def fake_diagnose(_team_name, _competition):
        return "some diagnosis"

    monkeypatch.setattr(android_test, "get_squawka_defensive_stats", fake_get_stats)
    monkeypatch.setattr(android_test, "_diagnose_squawka", fake_diagnose)
    result = run_squawka_defensive_stats("Liverpool", "Premier League")
    assert result == "0 players. Diagnosis: some diagnosis"


def test_run_squawka_defensive_stats_reports_top_level_exception(monkeypatch):
    async def failing(_team_name, _competitions):
        raise RuntimeError("boom")

    monkeypatch.setattr(android_test, "get_squawka_defensive_stats", failing)
    result = run_squawka_defensive_stats("Liverpool", "Premier League")
    assert result == "FAILED: RuntimeError: boom"


def test_run_squawka_defensive_stats_reports_when_diagnosis_itself_fails(monkeypatch):
    async def fake_get_stats(_team_name, _competitions):
        return {}

    async def failing_diagnose(_team_name, _competition):
        raise RuntimeError("diag boom")

    monkeypatch.setattr(android_test, "get_squawka_defensive_stats", fake_get_stats)
    monkeypatch.setattr(android_test, "_diagnose_squawka", failing_diagnose)
    result = run_squawka_defensive_stats("Liverpool", "Premier League")
    assert result == "0 players. Diagnosis: diagnose itself failed: RuntimeError: diag boom"


# --- run_full_report -------------------------------------------------------------------------


def test_run_full_report_fails_when_run_search_raises(monkeypatch):
    async def failing_run_search(_team_name):
        raise RuntimeError("boom")

    monkeypatch.setattr(android_test, "run_search", failing_run_search)
    result = run_full_report("Liverpool")
    assert result == "FAILED during run_search: RuntimeError: boom"


def test_run_full_report_fails_when_build_report_json_raises(monkeypatch):
    async def fake_run_search(_team_name):
        return SimpleNamespace(merged=None)

    def failing_build_report_json(_result):
        raise RuntimeError("boom")

    monkeypatch.setattr(android_test, "run_search", fake_run_search)
    monkeypatch.setattr(android_test, "build_report_json", failing_build_report_json)
    result = run_full_report("Liverpool")
    assert result == "FAILED during build_report_json/serialization: RuntimeError: boom"


def _fake_files_dir(tmp_path):
    class _Files:
        def getAbsolutePath(self):
            return str(tmp_path)

    class _Context:
        def getFilesDir(self):
            return _Files()

    return _Context()


def test_run_full_report_ok_without_upcoming_match(monkeypatch, tmp_path):
    async def fake_run_search(_team_name):
        return SimpleNamespace(merged=None)

    monkeypatch.setattr(android_test, "run_search", fake_run_search)
    monkeypatch.setattr(android_test, "build_report_json", lambda _result: {"a": 1})
    monkeypatch.setattr(android_test, "get_application_context", lambda: _fake_files_dir(tmp_path))
    result = run_full_report("Liverpool")
    assert "no upcoming match found" in result
    assert (tmp_path / "report.json").exists()


def test_run_full_report_ok_with_upcoming_match(monkeypatch, tmp_path):
    merged = SimpleNamespace(home_team="Liverpool", away_team="Arsenal")
    statuses = [SimpleNamespace(source="sofascore", fixtures_scraped=5), SimpleNamespace(source="fotmob", fixtures_scraped=3)]
    result_obj = SimpleNamespace(merged=merged, statuses=statuses, insights=None)

    async def fake_run_search(_team_name):
        return result_obj

    monkeypatch.setattr(android_test, "run_search", fake_run_search)
    monkeypatch.setattr(android_test, "build_report_json", lambda _result: {"a": 1})
    monkeypatch.setattr(android_test, "get_application_context", lambda: _fake_files_dir(tmp_path))
    monkeypatch.setattr(android_test, "compute_data_completeness", lambda _merged, _insights: {"populated": 10, "total": 20})
    result = run_full_report("Liverpool")
    assert "Liverpool vs Arsenal" in result
    assert "10/20 fields populated" in result
    assert "sofascore=5" in result
    assert "fotmob=3" in result


# --- _diagnose / _diagnose_squawka (browser-driven helpers) -----------------------------------


class _FakePage:
    async def goto(self, *_a, **_kw):
        return None

    async def evaluate(self, *_a, **_kw):
        return None


class _FakeContext:
    async def new_page(self):
        return _FakePage()


class _FakeBrowser:
    async def new_context(self, **_kw):
        return _FakeContext()


class _FakeBrowserCM:
    async def __aenter__(self):
        return _FakeBrowser()

    async def __aexit__(self, *_exc):
        return False


def test_diagnose_reports_unknown_competition():
    result = asyncio.run(android_test._diagnose("Not A Real League"))
    assert result == "Unknown competition: Not A Real League"


def test_diagnose_reports_scraped_row_count(monkeypatch):
    from football.sites.worldfootball import _RefereeRow

    rows = [_RefereeRow(name="C Pawson", penalties=1, second_yellow=0)]

    async def fake_fetch_referee_table(_page, _path):
        return rows

    monkeypatch.setattr(android_test, "launch_browser", lambda: _FakeBrowserCM())
    monkeypatch.setattr(android_test, "_fetch_referee_table", fake_fetch_referee_table)
    result = asyncio.run(android_test._diagnose("Premier League"))
    assert result == "1 rows scraped. First few: C Pawson"


def test_diagnose_squawka_reports_missing_nonce(monkeypatch):
    async def fake_load_page_context(_page):
        return None, []

    monkeypatch.setattr(android_test, "launch_browser", lambda: _FakeBrowserCM())
    monkeypatch.setattr(android_test, "_load_page_context", fake_load_page_context)
    result = asyncio.run(android_test._diagnose_squawka("Liverpool", "Premier League"))
    assert "no nonce" in result


def test_diagnose_squawka_reports_unresolved_competition(monkeypatch):
    async def fake_load_page_context(_page):
        return "nonce123", [{"competition": "Serie A"}]

    monkeypatch.setattr(android_test, "launch_browser", lambda: _FakeBrowserCM())
    monkeypatch.setattr(android_test, "_load_page_context", fake_load_page_context)
    monkeypatch.setattr(android_test, "_resolve_competition_id", lambda _competitions, _name: None)
    result = asyncio.run(android_test._diagnose_squawka("Liverpool", "Premier League"))
    assert "didn't resolve" in result
    assert "Serie A" in result


def test_diagnose_squawka_reports_empty_stat_fetch(monkeypatch):
    async def fake_load_page_context(_page):
        return "nonce123", []

    async def fake_fetch_stat_values(_page, _nonce, _competition_id, _label):
        return {}

    monkeypatch.setattr(android_test, "launch_browser", lambda: _FakeBrowserCM())
    monkeypatch.setattr(android_test, "_load_page_context", fake_load_page_context)
    monkeypatch.setattr(android_test, "_resolve_competition_id", lambda _competitions, _name: "comp1")
    monkeypatch.setattr(android_test, "_fetch_stat_values", fake_fetch_stat_values)
    result = asyncio.run(android_test._diagnose_squawka("Liverpool", "Premier League"))
    assert "returned 0 values" in result


def test_diagnose_squawka_reports_matched_team_aliases(monkeypatch):
    async def fake_load_page_context(_page):
        return "nonce123", []

    async def fake_fetch_stat_values(_page, _nonce, _competition_id, _label):
        return {"mohamed salah::liverpool": 3}

    monkeypatch.setattr(android_test, "launch_browser", lambda: _FakeBrowserCM())
    monkeypatch.setattr(android_test, "_load_page_context", fake_load_page_context)
    monkeypatch.setattr(android_test, "_resolve_competition_id", lambda _competitions, _name: "comp1")
    monkeypatch.setattr(android_test, "_fetch_stat_values", fake_fetch_stat_values)
    monkeypatch.setattr(android_test, "known_aliases_for", lambda _name: ["liverpool"])
    result = asyncio.run(android_test._diagnose_squawka("Liverpool", "Premier League"))
    assert "matched team aliases" in result
    assert "mohamed salah::liverpool" in result


def test_diagnose_squawka_reports_no_alias_match_with_closest_names(monkeypatch):
    async def fake_load_page_context(_page):
        return "nonce123", []

    async def fake_fetch_stat_values(_page, _nonce, _competition_id, _label):
        return {"mohamed salah::liverfc": 3}

    monkeypatch.setattr(android_test, "launch_browser", lambda: _FakeBrowserCM())
    monkeypatch.setattr(android_test, "_load_page_context", fake_load_page_context)
    monkeypatch.setattr(android_test, "_resolve_competition_id", lambda _competitions, _name: "comp1")
    monkeypatch.setattr(android_test, "_fetch_stat_values", fake_fetch_stat_values)
    monkeypatch.setattr(android_test, "known_aliases_for", lambda _name: ["liverpool"])
    result = asyncio.run(android_test._diagnose_squawka("Liverpool", "Premier League"))
    assert "NONE matched" in result
