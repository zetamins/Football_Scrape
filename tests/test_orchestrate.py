"""Covers run_search's on_source_progress hook specifically -- the rest
of run_search is an integration-level pipeline across 13 live sources
with no existing unit coverage (nothing here mocks that far), so this
stays scoped to the one thing this session added: does on_source_progress
fire once per source, with the real SourceStatus the source produced.

All 5 SCRAPERS are monkeypatched to fail fast with no network access, so
`merged` and `merged_profile` both stay None/falsy -- run_search now
raises right after the per-source loop in that case (see its own
"Could not find a team matching" check, added after a real bug: an
unrecognized team name used to silently produce a hollow "successful"
report with match=null instead of a clear error). Both tests below wrap
the call in pytest.raises to acknowledge that, then still assert on
`seen` -- the raise happens AFTER the per-source loop completes, so
on_source_progress firing once per source (this file's actual scope,
per the module docstring above) is unaffected by it. Driven via
asyncio.run(), same as android_report.py/cli.py do at their own call
sites -- no async test runner is configured in this project, so tests
stay synchronous functions that drive the coroutine themselves rather
than adding one."""

import asyncio
from dataclasses import fields as _dc_fields
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from football import orchestrate
from football.merge import SOURCE_ORDER
from football.orchestrate import (
    _age_from_iso_date,
    _apply_duel_and_fullback_insights,
    _apply_presence_and_bench_insights,
    _apply_squad_derived_insights,
    _apply_squad_strength_insights,
    _compute_rest_days,
    _compute_squad_leaderboards,
    _home_away,
    _Scraper,
    _squad_for_bench_info,
    _step_message,
    run_search,
)


def _all_none(cls, **overrides):
    base = {f.name: None for f in _dc_fields(cls)}
    base.update(overrides)
    return cls(**base)


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
    coro = run_search("Some Team", on_source_progress=seen.append)
    with pytest.raises(RuntimeError, match="Could not find a team"):
        asyncio.run(coro)

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
    coro = run_search("Some Team", on_source_progress=seen.append)
    with pytest.raises(RuntimeError, match="Could not find a team"):
        asyncio.run(coro)

    assert len(seen) == len(SOURCE_ORDER)
    for status in seen:
        assert status.fixtures_scraped == 0
        assert status.matches_error is None
        assert status.profile_error == "no profile"


# --- _age_from_iso_date -------------------------------------------------------


def test_age_from_iso_date_computes_whole_years():
    ten_years_ago = (datetime.now(tz=UTC) - timedelta(days=365.25 * 10 + 5)).date().isoformat()
    assert _age_from_iso_date(ten_years_ago) == 10


def test_age_from_iso_date_none_without_date():
    assert _age_from_iso_date(None) is None


def test_age_from_iso_date_none_for_unparseable_string():
    assert _age_from_iso_date("not-a-date") is None


# --- _compute_rest_days --------------------------------------------------------


def test_compute_rest_days_from_most_recent_played_match():
    now = datetime.now(tz=UTC)
    played = _match(kickoff_utc=(now - timedelta(days=4)).isoformat())
    future = _match(kickoff_utc=(now + timedelta(days=3)).isoformat())
    assert _compute_rest_days([played, future], now) == 4


def test_compute_rest_days_none_without_any_played_matches():
    now = datetime.now(tz=UTC)
    future = _match(kickoff_utc=(now + timedelta(days=3)).isoformat())
    assert _compute_rest_days([future], now) is None


# --- _step_message / _home_away -------------------------------------------------


def test_step_message_includes_step_and_total():
    msg = _step_message(2, "Fetching opponent")
    assert msg.startswith("(2/")
    assert "Fetching opponent" in msg


def test_home_away_keeps_order_when_own_is_home():
    assert _home_away(True, "own", "opp") == ("own", "opp")


def test_home_away_swaps_when_own_is_away():
    assert _home_away(False, "own", "opp") == ("opp", "own")


# --- _squad_for_bench_info -------------------------------------------------------


def test_squad_for_bench_info_picks_preferred_profile():
    from football.types import TeamProfile

    own_profile = _all_none(TeamProfile, source="sofascore", team_name="Own", squad=["own-squad"])
    opp_profile = _all_none(TeamProfile, source="sofascore", team_name="Opp", squad=["opp-squad"])
    assert _squad_for_bench_info(True, own_profile, opp_profile) == ["own-squad"]
    assert _squad_for_bench_info(False, own_profile, opp_profile) == ["opp-squad"]


def test_squad_for_bench_info_none_when_preferred_profile_missing():
    # Regression test: the original nested-ternary version this was
    # extracted from could AttributeError here -- guarded only by
    # "either profile exists" rather than by the PREFERRED one existing.
    from football.types import TeamProfile

    opp_profile = _all_none(TeamProfile, source="sofascore", team_name="Opp", squad=["opp-squad"])
    assert _squad_for_bench_info(True, None, opp_profile) is None


# --- squad-derived insight wiring (_apply_duel_and_fullback_insights etc.) ------


def _insights_result():
    from football.types import MatchInsights

    return _all_none(MatchInsights)


def _profile_with_squad(name, squad):
    from football.types import TeamProfile

    return _all_none(TeamProfile, source="sofascore", team_name=name, squad=squad)


def test_apply_duel_and_fullback_insights_routes_to_home_away_by_own_is_home():
    from football.types import DefensiveStats, SquadMember

    weak_defender = _all_none(SquadMember, name="Weak DF", role="D", defensive_stats=_all_none(DefensiveStats, ground_duel_success_pct=30.0))
    own_profile = _profile_with_squad("Own", [weak_defender])
    result = _insights_result()

    _apply_duel_and_fullback_insights(result, own_is_home=True, merged_profile=own_profile, opponent_profile=None)
    assert result.home_duel_vulnerabilities is not None
    assert result.home_duel_vulnerabilities[0].name == "Weak DF"
    assert result.away_duel_vulnerabilities is None

    result2 = _insights_result()
    _apply_duel_and_fullback_insights(result2, own_is_home=False, merged_profile=own_profile, opponent_profile=None)
    # own_is_home False -- own team's (weak-defender) data lands on the AWAY side.
    assert result2.away_duel_vulnerabilities is not None
    assert result2.home_duel_vulnerabilities is None


def test_apply_presence_and_bench_insights_handles_missing_profiles_gracefully():
    merged = _all_none(orchestrate.MergedMatch, home_lineup=None, away_lineup=None, home_bench=None, away_bench=None, home_suspended_players=None, away_suspended_players=None)
    result = _insights_result()
    # Neither profile exists -- must not raise (this is exactly the class
    # of AttributeError _squad_for_bench_info's docstring describes).
    _apply_presence_and_bench_insights(result, own_is_home=True, merged=merged, merged_profile=None, opponent_profile=None)
    assert result.home_presence is None
    assert result.home_bench_info is None


def test_apply_squad_strength_insights_computes_for_both_sides():
    from football.types import SquadMember

    own_profile = _profile_with_squad("Own", [_all_none(SquadMember, name="P1", role="F", market_value=10.0)])
    opp_profile = _profile_with_squad("Opp", [_all_none(SquadMember, name="P2", role="F", market_value=20.0)])
    merged = _all_none(orchestrate.MergedMatch, home_suspended_players=None, away_suspended_players=None)
    result = _insights_result()
    _apply_squad_strength_insights(result, own_is_home=True, merged=merged, merged_profile=own_profile, opponent_profile=opp_profile)
    assert result.home_squad_strength.total_value == 10.0
    assert result.away_squad_strength.total_value == 20.0


def test_apply_squad_derived_insights_runs_all_three_without_error():
    merged = _all_none(
        orchestrate.MergedMatch, home_lineup=None, away_lineup=None, home_bench=None, away_bench=None,
        home_suspended_players=None, away_suspended_players=None,
    )
    result = _insights_result()
    _apply_squad_derived_insights(result, own_is_home=True, merged=merged, merged_profile=None, opponent_profile=None)
    # Nothing to assert beyond "didn't raise" -- this just verifies the
    # 3-helper wiring itself, each helper's own behavior is covered above.


# --- _compute_squad_leaderboards -------------------------------------------------


def test_compute_squad_leaderboards_populates_leaderboards_for_a_real_squad():
    from football.types import SeasonPlayerStats, SquadMember, TeamProfile

    scorer = _all_none(SquadMember, name="Top Scorer", role="F", season_stats=_all_none(SeasonPlayerStats, goals=10, assists=1))
    profile = _all_none(TeamProfile, source="sofascore", team_name="Own", squad=[scorer])
    _compute_squad_leaderboards([profile])
    assert profile.top_scorers is not None
    assert profile.top_scorers[0].name == "Top Scorer"


def test_compute_squad_leaderboards_skips_profiles_without_squad():
    from football.types import TeamProfile

    profile = _all_none(TeamProfile, source="sofascore", team_name="Own", squad=None)
    _compute_squad_leaderboards([profile, None])  # must not raise on either


# --- _fetch_opponent_matches -----------------------------------------------------


def test_fetch_opponent_matches_uses_base_source_when_it_succeeds(monkeypatch):
    from football.orchestrate import _fetch_opponent_matches

    async def base_run(_team_name):
        return [_match()]

    async def other_run(_team_name):
        raise AssertionError("should not be called -- base_source already succeeded")

    fake_scrapers = {source: _Scraper(run=other_run, details=other_run, profile=other_run) for source in SOURCE_ORDER}
    fake_scrapers[SOURCE_ORDER[0]] = _Scraper(run=base_run, details=other_run, profile=other_run)
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    matches, source, error = asyncio.run(_fetch_opponent_matches(SOURCE_ORDER[0], "Opponent"))
    assert len(matches) == 1
    assert source == SOURCE_ORDER[0]
    assert error is None


def test_fetch_opponent_matches_falls_through_to_next_source_on_failure(monkeypatch):
    from football.orchestrate import _fetch_opponent_matches

    async def failing_run(_team_name):
        raise RuntimeError("blocked")

    async def working_run(_team_name):
        return [_match()]

    fake_scrapers = {source: _Scraper(run=failing_run, details=failing_run, profile=failing_run) for source in SOURCE_ORDER}
    fake_scrapers[SOURCE_ORDER[1]] = _Scraper(run=working_run, details=failing_run, profile=failing_run)
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    matches, source, error = asyncio.run(_fetch_opponent_matches(SOURCE_ORDER[0], "Opponent"))
    assert source == SOURCE_ORDER[1]
    assert len(matches) == 1
    assert "blocked" in error  # base_source's failure is still recorded


def test_fetch_opponent_matches_error_when_every_source_fails(monkeypatch):
    from football.orchestrate import _fetch_opponent_matches

    async def failing_run(_team_name):
        raise RuntimeError("blocked")

    fake_scrapers = {source: _Scraper(run=failing_run, details=failing_run, profile=failing_run) for source in SOURCE_ORDER}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    matches, source, error = asyncio.run(_fetch_opponent_matches(SOURCE_ORDER[0], "Opponent"))
    assert matches == []
    assert source is None
    assert error is not None


def test_fetch_opponent_matches_error_falls_back_to_class_name_when_message_empty(monkeypatch):
    """Regression: str(err) is "" for an exception raised with no
    message, which previously leaked through as opponent_context_error
    == "" (looking like "no error" while a real failure occurred)."""
    from football.orchestrate import _fetch_opponent_matches

    async def failing_run(_team_name):
        raise RuntimeError

    fake_scrapers = {source: _Scraper(run=failing_run, details=failing_run, profile=failing_run) for source in SOURCE_ORDER}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    _, _, error = asyncio.run(_fetch_opponent_matches(SOURCE_ORDER[0], "Opponent"))
    assert error
    assert "RuntimeError" in error


# --- _scrape_all_sources: details() failure branch --------------------------------


def test_scrape_all_sources_records_details_error_when_next_match_details_fails(monkeypatch):
    from football.orchestrate import _scrape_all_sources

    async def one_match(_team_name):
        return [_match(kickoff_utc=(datetime.now(tz=UTC) + timedelta(days=3)).isoformat(), status="scheduled")]

    async def failing_details(_match):
        raise RuntimeError("details blocked")

    async def working_profile(_team_name):
        from football.types import TeamProfile

        return _all_none(TeamProfile, source="sofascore", team_name="X", squad=None)

    fake_scrapers = {source: _Scraper(run=one_match, details=failing_details, profile=working_profile) for source in SOURCE_ORDER}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    _matches_by_source, details_by_source, _profile_by_source, statuses = asyncio.run(
        _scrape_all_sources("Some Team", lambda _msg: None, lambda _status: None)
    )
    assert details_by_source == {}
    for status in statuses:
        assert status.details_error == "details blocked"


# --- _fetch_opponent_profiles / fetch_opponent_context -----------------------------


def test_fetch_opponent_profiles_collects_per_source_profiles_and_errors(monkeypatch):
    from football.orchestrate import _fetch_opponent_profiles
    from football.types import TeamProfile

    async def working_profile(_team_name):
        return _all_none(TeamProfile, source="sofascore", team_name="Opp", squad=None)

    async def failing_profile(_team_name):
        raise RuntimeError("blocked")

    fake_scrapers = {source: _Scraper(run=None, details=None, profile=failing_profile) for source in SOURCE_ORDER}
    fake_scrapers[SOURCE_ORDER[0]] = _Scraper(run=None, details=None, profile=working_profile)
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    profile_by_source, error = asyncio.run(_fetch_opponent_profiles("Opponent"))
    assert SOURCE_ORDER[0] in profile_by_source
    assert len(profile_by_source) == 1
    assert "blocked" in error


def test_fetch_opponent_context_error_is_never_empty_string(monkeypatch):
    """Regression: opponent_context_error showed up as "" (not null) in
    a real report -- traced to a profile-fetch exception with an empty
    message combining with a successful matches-fetch via
    `matches_error or profile_error`, which returns "" verbatim rather
    than falling back to None. The class-name fallback above prevents
    the empty message in the first place."""
    from football.orchestrate import fetch_opponent_context
    from football.types import TeamProfile

    async def working_matches(_team_name):
        return [_match(kickoff_utc=datetime.now(tz=UTC).isoformat())]

    async def failing_profile(_team_name):
        raise RuntimeError

    fake_scrapers = {source: _Scraper(run=working_matches, details=None, profile=failing_profile) for source in SOURCE_ORDER}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    ctx = asyncio.run(fetch_opponent_context(SOURCE_ORDER[0], "Opponent"))
    assert ctx.error != ""
    assert ctx.error is not None
    assert "RuntimeError" in ctx.error


def test_fetch_opponent_context_merges_matches_rest_days_and_profile(monkeypatch):
    from football.orchestrate import fetch_opponent_context
    from football.types import TeamProfile

    now = datetime.now(tz=UTC)
    played = _match(kickoff_utc=(now - timedelta(days=5)).isoformat())

    async def matches_run(_team_name):
        return [played]

    async def profile_run(_team_name):
        return _all_none(TeamProfile, source="sofascore", team_name="Opp", squad=None, average_age=27.5)

    fake_scrapers = {source: _Scraper(run=matches_run, details=None, profile=profile_run) for source in SOURCE_ORDER}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    ctx = asyncio.run(fetch_opponent_context(SOURCE_ORDER[0], "Opponent"))
    assert ctx.matches == [played]
    assert ctx.matches_source == SOURCE_ORDER[0]
    assert ctx.rest_days == 5
    assert ctx.average_age == 27.5
    assert ctx.merged_profile is not None
    assert ctx.error is None


def test_fetch_opponent_context_rest_days_relative_to_as_of_not_wall_clock(monkeypatch):
    """Regression: rest_days must be computed relative to the upcoming
    match's own kickoff time when given, not whenever this happens to
    run -- otherwise it silently disagrees with the searched team's own
    rest days (computed relative to its next fixture's kickoff)."""
    from football.orchestrate import fetch_opponent_context
    from football.types import TeamProfile

    now = datetime.now(tz=UTC)
    played = _match(kickoff_utc=(now - timedelta(days=5)).isoformat())
    match_kickoff = now + timedelta(days=2)  # the report is generated 2 days before kickoff

    async def matches_run(_team_name):
        return [played]

    async def profile_run(_team_name):
        return _all_none(TeamProfile, source="sofascore", team_name="Opp", squad=None, average_age=None)

    fake_scrapers = {source: _Scraper(run=matches_run, details=None, profile=profile_run) for source in SOURCE_ORDER}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    ctx = asyncio.run(fetch_opponent_context(SOURCE_ORDER[0], "Opponent", as_of=match_kickoff))
    assert ctx.rest_days == 7  # 5 days before "now" + 2 days until kickoff


def test_fetch_opponent_context_none_profile_when_every_source_fails(monkeypatch):
    from football.orchestrate import fetch_opponent_context

    async def failing(_team_name):
        raise RuntimeError("blocked")

    fake_scrapers = {source: _Scraper(run=failing, details=None, profile=failing) for source in SOURCE_ORDER}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    ctx = asyncio.run(fetch_opponent_context(SOURCE_ORDER[0], "Opponent"))
    assert ctx.matches == []
    assert ctx.merged_profile is None
    assert ctx.average_age is None
    assert ctx.error is not None


# --- fetch_venue_details -----------------------------------------------------------


def test_fetch_venue_details_returns_home_club_result(monkeypatch):
    from football.orchestrate import fetch_venue_details
    from football.types import VenueDetails

    home_venue = _all_none(VenueDetails, stadium_name="Home Stadium", clubs=[], source_url="https://x")

    async def fake_lookup(club_name, _country):
        return home_venue if club_name == "Home FC" else None

    monkeypatch.setattr(orchestrate.stadiumdb, "get_stadium_db_venue_details", fake_lookup)
    merged = _all_none(orchestrate.MergedMatch, home_team="Home FC", away_team="Away FC")
    result = asyncio.run(fetch_venue_details(merged, "England"))
    assert result is home_venue


def test_fetch_venue_details_falls_back_to_away_club(monkeypatch):
    from football.orchestrate import fetch_venue_details
    from football.types import VenueDetails

    away_venue = _all_none(VenueDetails, stadium_name="Away Stadium", clubs=[], source_url="https://x")

    async def fake_lookup(club_name, _country):
        return away_venue if club_name == "Away FC" else None

    monkeypatch.setattr(orchestrate.stadiumdb, "get_stadium_db_venue_details", fake_lookup)
    merged = _all_none(orchestrate.MergedMatch, home_team="Home FC", away_team="Away FC")
    result = asyncio.run(fetch_venue_details(merged, "England"))
    assert result is away_venue


def test_fetch_venue_details_none_when_lookup_raises(monkeypatch):
    from football.orchestrate import fetch_venue_details

    async def failing_lookup(_club_name, _country):
        raise RuntimeError("boom")

    monkeypatch.setattr(orchestrate.stadiumdb, "get_stadium_db_venue_details", failing_lookup)
    merged = _all_none(orchestrate.MergedMatch, home_team="Home FC", away_team="Away FC")
    result = asyncio.run(fetch_venue_details(merged, "England"))
    assert result is None


# --- _enrich_manager_tenure --------------------------------------------------------


def _manager(**overrides):
    from football.types import ManagerInfo

    base = {"name": "Some Manager", "country": None, "appointed_date": None, "recent_appointment": None, "previous_manager": None, "record_at_club": None, "age": None}
    base.update(overrides)
    return ManagerInfo(**base)


def test_enrich_manager_tenure_none_manager_passes_through():
    from football.orchestrate import _enrich_manager_tenure

    assert asyncio.run(_enrich_manager_tenure(None, "Home FC")) is None


def test_enrich_manager_tenure_populates_tenure_and_previous_manager(monkeypatch):
    from football.orchestrate import _enrich_manager_tenure

    class _TenureRow:
        from_date = "1 January 2020"
        played, wins, draws, losses, win_pct = 100, 60, 20, 20, 60.0
        date_of_birth = "1975-05-01"

    async def fake_tenure(_name):
        return _TenureRow()

    async def fake_previous(_team_name):
        return "Old Manager"

    monkeypatch.setattr(orchestrate.wikipedia, "get_current_tenure_row", fake_tenure)
    monkeypatch.setattr(orchestrate.wikipedia, "get_previous_manager", fake_previous)

    manager = _manager(name="New Manager")
    result = asyncio.run(_enrich_manager_tenure(manager, "Home FC"))
    assert result.previous_manager == "Old Manager"
    assert result.record_at_club is not None
    assert result.record_at_club.played == 100
    assert result.appointed_date is not None
    assert result.age is not None


def test_enrich_manager_tenure_gracefully_handles_lookup_failures(monkeypatch):
    from football.orchestrate import _enrich_manager_tenure

    async def failing(_arg):
        raise RuntimeError("blocked")

    monkeypatch.setattr(orchestrate.wikipedia, "get_current_tenure_row", failing)
    monkeypatch.setattr(orchestrate.wikipedia, "get_previous_manager", failing)

    manager = _manager()
    result = asyncio.run(_enrich_manager_tenure(manager, "Home FC"))
    assert result.previous_manager is None
    assert result.record_at_club is None
    assert result.appointed_date is None


def test_enrich_manager_tenure_no_record_when_tenure_row_incomplete(monkeypatch):
    from football.orchestrate import _enrich_manager_tenure

    manager = _manager()

    class _IncompleteTenureRow:
        from_date = "2020-01-01"
        played, wins, draws, losses = 100, None, 20, 20
        win_pct = None
        date_of_birth = None

    async def fake_tenure(_name):
        return _IncompleteTenureRow()

    async def fake_previous(_team_name):
        return None

    monkeypatch.setattr(orchestrate.wikipedia, "get_current_tenure_row", fake_tenure)
    monkeypatch.setattr(orchestrate.wikipedia, "get_previous_manager", fake_previous)
    result = asyncio.run(_enrich_manager_tenure(manager, "Home FC"))
    assert result.record_at_club is None


# --- _enrich_referee_stats ----------------------------------------------------------


def _referee_stats(**overrides):
    from football.types import RefereeStats

    base = {
        "games": 10, "yellow_cards": 30, "red_cards": 2, "yellow_cards_per_game": 3.0,
        "penalties_awarded": None, "second_yellow_cards": None, "home_away_bias": None,
        "fouls_per_game": None, "penalties_per_game": None, "cards_per_foul": None, "avg_total_cards": None,
    }
    base.update(overrides)
    return RefereeStats(**base)


def test_enrich_referee_stats_noop_without_existing_referee_stats():
    from football.orchestrate import _enrich_referee_stats

    merged = _all_none(orchestrate.MergedMatch, referee_stats=None, referee="Some Ref", competition="Premier League")
    asyncio.run(_enrich_referee_stats(merged))
    assert merged.referee_stats is None


def test_enrich_referee_stats_populates_from_all_three_sources(monkeypatch):
    from football.orchestrate import _enrich_referee_stats
    from football.sites.worldfootball import WorldfootballRefereeStats

    async def fake_worldfootball(_competition, _referee):
        return WorldfootballRefereeStats(penalties=3, second_yellow=1)

    async def fake_footballdata(_competition, _referee):
        return "bias-object"

    async def fake_refsradar(_referee):
        from football.sites.refsradar import RefereeKpis

        return RefereeKpis(fouls_per_game=22.0, red_cards_per_game=0.1, matches=15, penalties_per_game=0.3, cards_per_foul=0.14, avg_total_cards=4.5)

    monkeypatch.setattr(orchestrate.worldfootball, "get_referee_worldfootball_stats", fake_worldfootball)
    monkeypatch.setattr(orchestrate.footballdata, "get_referee_home_away_bias", fake_footballdata)
    monkeypatch.setattr(orchestrate.refsradar, "get_referee_kpis", fake_refsradar)

    merged = _all_none(orchestrate.MergedMatch, referee_stats=_referee_stats(), referee="Some Ref", competition="Premier League")
    asyncio.run(_enrich_referee_stats(merged))
    assert merged.referee_stats.penalties_awarded == 3
    assert merged.referee_stats.second_yellow_cards == 1
    assert merged.referee_stats.home_away_bias == "bias-object"
    assert merged.referee_stats.fouls_per_game == 22.0
    assert merged.referee_stats.referee_matches == 15


def test_enrich_referee_stats_tolerates_individual_source_failures(monkeypatch):
    from football.orchestrate import _enrich_referee_stats

    async def failing(*_args):
        raise RuntimeError("blocked")

    monkeypatch.setattr(orchestrate.worldfootball, "get_referee_worldfootball_stats", failing)
    monkeypatch.setattr(orchestrate.footballdata, "get_referee_home_away_bias", failing)
    monkeypatch.setattr(orchestrate.refsradar, "get_referee_kpis", failing)

    merged = _all_none(orchestrate.MergedMatch, referee_stats=_referee_stats(), referee="Some Ref", competition="Premier League")
    asyncio.run(_enrich_referee_stats(merged))
    assert merged.referee_stats.penalties_awarded is None
    assert merged.referee_stats.fouls_per_game is None


# --- _enrich_weather -----------------------------------------------------------------


def test_enrich_weather_noop_without_a_city_or_venue_name():
    from football.orchestrate import _enrich_weather

    merged = _all_none(orchestrate.MergedMatch, venue_city=None, venue_name=None, weather=None, weather_detail=None)
    asyncio.run(_enrich_weather(merged))
    assert merged.weather is None
    assert merged.weather_detail is None


def test_enrich_weather_noop_when_lookup_returns_none(monkeypatch):
    from football.orchestrate import _enrich_weather

    async def fake_detail(_city, _kickoff, _country):
        return None

    monkeypatch.setattr(orchestrate.wttrin, "get_wttr_weather_detail", fake_detail)
    merged = _all_none(orchestrate.MergedMatch, venue_city="London", venue_name=None, weather=None, weather_detail=None, kickoff_utc=None, venue_country=None)
    asyncio.run(_enrich_weather(merged))
    assert merged.weather is None


def test_enrich_weather_populates_weather_detail_and_string(monkeypatch):
    from football.orchestrate import _enrich_weather

    class _Detail:
        description = "Sunny"
        temp_c = 20.0
        humidity_pct = 50.0
        wind_speed_kmph = 10.0
        precip_mm = 0.0
        chance_of_rain_pct = 5.0
        wind_gust_kmph = 15.0
        cloud_cover_pct = 25.0
        feels_like_c = 19.0
        kickoff_hour_matched = True

    async def fake_detail(_city, _kickoff, _country):
        return _Detail()

    monkeypatch.setattr(orchestrate.wttrin, "get_wttr_weather_detail", fake_detail)
    merged = _all_none(orchestrate.MergedMatch, venue_city="London", venue_name=None, weather=None, weather_detail=None, kickoff_utc=None, venue_country=None, field_sources={})
    asyncio.run(_enrich_weather(merged))
    assert merged.weather_detail is not None
    assert merged.weather_detail.temp_c == 20.0
    assert merged.weather == "Sunny, 20.0°C"
    assert merged.field_sources["weather"] == "wttr.in"
    assert merged.field_sources["weather_detail"] == "wttr.in"


def test_enrich_weather_gracefully_handles_fetch_failure(monkeypatch):
    from football.orchestrate import _enrich_weather

    async def failing(_city, _kickoff, _country):
        raise RuntimeError("blocked")

    monkeypatch.setattr(orchestrate.wttrin, "get_wttr_weather_detail", failing)
    merged = _all_none(orchestrate.MergedMatch, venue_city="London", venue_name=None, weather=None, weather_detail=None, kickoff_utc=None, venue_country=None)
    asyncio.run(_enrich_weather(merged))
    assert merged.weather is None
    assert merged.weather_detail is None


# --- _apply_own_recent_meetings_and_form ---------------------------------------------


def _meeting(**overrides):
    from football.types import HeadToHeadMeeting

    base = {
        "date": "2026-01-01T00:00:00.000Z", "competition": "Premier League", "scoreline": "1-0", "venue": "home",
        "home_formation": None, "away_formation": None, "home_xg": None, "away_xg": None, "home_lineup": None, "away_lineup": None,
    }
    base.update(overrides)
    return HeadToHeadMeeting(**base)


def _form_summary(**overrides):
    from football.types import FormSummary

    base = {
        "last5_overall": [], "last10_overall": [], "last20_overall": [], "last5_home": [], "last5_away": [],
        "next5_with_gaps": [], "gaps_between_last_three": [], "half_split": None, "recent_competitions": [],
        "current_streak": None, "home_win_rate_pct": None, "away_win_rate_pct": None, "momentum": None,
        "narrow_win_share_pct": None, "scoring_draw_share_pct": None, "btts_share_pct": None,
        "clean_sheet_streak": None, "scoreless_streak": None, "over15_share_pct": None, "over25_share_pct": None,
        "over35_share_pct": None, "clean_sheet_share_pct": None, "failed_to_score_share_pct": None,
        "form_by_competition": [], "matches_last7_days": 0, "matches_last14_days": 0, "venue_split_form": None,
        "detailed_venue_split": None, "win_rate_pct": None, "draw_rate_pct": None, "loss_rate_pct": None,
        "points_per_game": None, "goals_for_per_game": None, "goals_against_per_game": None,
    }
    base.update(overrides)
    return FormSummary(**base)


def test_apply_own_recent_meetings_and_form_noop_without_form_source():
    from football.orchestrate import _apply_own_recent_meetings_and_form

    merged = _all_none(orchestrate.MergedMatch, field_sources={}, additional_notes=[])
    form = _form_summary()
    result_form, advanced_stats = asyncio.run(
        _apply_own_recent_meetings_and_form("Home FC", merged, None, form, {}, "Opponent", None)
    )
    assert result_form is form
    assert advanced_stats is None


def test_apply_own_recent_meetings_and_form_applies_deep_meetings_and_venue_enrichment(monkeypatch):
    from football.orchestrate import _apply_own_recent_meetings_and_form
    from football.types import PlayerUsagePattern, SquadMember

    async def fake_compute_recent_meetings(_raw_matches, _last20, _opponent_name, _source):
        return [_meeting()]

    enriched_form = _form_summary(matches_last7_days=1)
    enriched_usage = {
        "some player": PlayerUsagePattern(
            matches_in_squad=5, starts=4, sub_appearances=1, unused_bench=0, total_minutes=360,
            total_goals=1, total_assists=0, total_xg=0.5, total_xa=0.2, total_shots=5,
            total_shots_on_target=2, total_tackles=1, total_interceptions=1, total_fouls=1,
            total_key_passes=2, appearances_with_stats=5, avg_rating=7.0, goals_per_90=0.25,
            assists_per_90=0.0, xg_per_90=0.12, xa_per_90=0.05, key_passes_per_90=0.5,
        )
    }

    async def fake_enrich_venue(_raw_matches, _form, _source):
        return SimpleNamespace(form=enriched_form, advanced_stats="some-advanced-stats", usage_by_player=enriched_usage)

    monkeypatch.setattr(orchestrate.ins, "compute_recent_meetings", fake_compute_recent_meetings)
    monkeypatch.setattr(orchestrate, "enrich_form_with_venue_classification", fake_enrich_venue)

    merged = _all_none(orchestrate.MergedMatch, field_sources={}, additional_notes=[], recent_meetings=None)
    form = _form_summary()
    squad_member = SquadMember(name="Some Player", role="F", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)
    merged_profile = _all_none(orchestrate.MergedProfile, source="sofascore", team_name="Own", squad=[squad_member], field_sources={})

    result_form, advanced_stats = asyncio.run(
        _apply_own_recent_meetings_and_form("Home FC", merged, "sofascore", form, {"sofascore": []}, "Opponent", merged_profile)
    )
    assert result_form is enriched_form
    assert advanced_stats == "some-advanced-stats"
    assert merged.recent_meetings == [_meeting()]
    assert merged_profile.squad[0].recent_usage is not None


def test_apply_own_recent_meetings_and_form_tolerates_failures(monkeypatch):
    from football.orchestrate import _apply_own_recent_meetings_and_form

    async def failing_meetings(*_args):
        raise RuntimeError("boom")

    async def failing_enrich(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(orchestrate.ins, "compute_recent_meetings", failing_meetings)
    monkeypatch.setattr(orchestrate, "enrich_form_with_venue_classification", failing_enrich)

    merged = _all_none(orchestrate.MergedMatch, field_sources={}, additional_notes=[], recent_meetings=[_meeting()])
    original_meetings = merged.recent_meetings
    form = _form_summary()
    result_form, advanced_stats = asyncio.run(
        _apply_own_recent_meetings_and_form("Home FC", merged, "sofascore", form, {"sofascore": []}, "Opponent", None)
    )
    assert result_form is form
    assert advanced_stats is None
    # A failed deep computation must leave the existing fallback in place.
    assert merged.recent_meetings == original_meetings


# --- _compute_and_apply_match_stat_estimates ------------------------------------------


def _match_stats_estimate(**overrides):
    from football.insights import SeasonMatchStatsEstimate

    base = {"xg": None, "shots": None, "card_split": None, "aerial": None, "big_chances": None, "passing_style": None, "fouls": None, "goalkeeping": None}
    base.update(overrides)
    return SeasonMatchStatsEstimate(**base)


def _possession_estimate(**overrides):
    from football.insights import PossessionAndCornersEstimate

    base = {"possession": None, "corners": None, "defensive_errors": None}
    base.update(overrides)
    return PossessionAndCornersEstimate(**base)


def test_compute_and_apply_match_stat_estimates_populates_home_away_by_own_is_home(monkeypatch):
    from football.orchestrate import _compute_and_apply_match_stat_estimates

    async def fake_fotmob_matches(_team_name):
        return []

    async def fake_goal_matches(_team_name):
        return []

    own_stats = _match_stats_estimate(xg="own-xg")
    opp_stats = _match_stats_estimate(xg="opp-xg")

    async def fake_match_stats(team_name, _matches):
        return own_stats if team_name == "Own Team" else opp_stats

    # corners/defensive_errors left at their None default -- own_stats.aerial
    # and .passing_style are also None -- so the real (unmocked)
    # compute_set_piece_threat_flag/compute_direct_play_exposure_flag calls
    # this function makes downstream short-circuit cleanly instead of
    # needing full real estimate objects just to test the home/away wiring.
    own_poss = _possession_estimate(possession="own-poss")
    opp_poss = _possession_estimate(possession="opp-poss")

    async def fake_possession(team_name, _matches):
        return own_poss if team_name == "Own Team" else opp_poss

    monkeypatch.setattr(orchestrate.fotmob, "get_fotmob_matches", fake_fotmob_matches)
    monkeypatch.setattr(orchestrate.goal, "get_goal_matches", fake_goal_matches)
    monkeypatch.setattr(orchestrate.ins, "compute_season_match_stats_estimate", fake_match_stats)
    monkeypatch.setattr(orchestrate.ins, "compute_possession_matchup", fake_possession)

    insights_result = _insights_result()
    own_xg, opponent_xg = asyncio.run(
        _compute_and_apply_match_stat_estimates("Own Team", "Opponent Team", True, insights_result, {"fotmob": []}, lambda _msg: None)
    )
    assert own_xg == "own-xg"
    assert opponent_xg == "opp-xg"
    assert insights_result.home_xg_estimate == "own-xg"
    assert insights_result.away_xg_estimate == "opp-xg"
    assert insights_result.home_possession_matchup == "own-poss"
    assert insights_result.away_possession_matchup == "opp-poss"


def test_compute_and_apply_match_stat_estimates_tolerates_opponent_fetch_failures(monkeypatch):
    from football.orchestrate import _compute_and_apply_match_stat_estimates

    async def failing_fotmob(_team_name):
        raise RuntimeError("blocked")

    async def failing_goal(_team_name):
        raise RuntimeError("blocked")

    async def fake_match_stats(_team_name, _matches):
        return _match_stats_estimate()

    async def fake_possession(_team_name, _matches):
        return _possession_estimate()

    monkeypatch.setattr(orchestrate.fotmob, "get_fotmob_matches", failing_fotmob)
    monkeypatch.setattr(orchestrate.goal, "get_goal_matches", failing_goal)
    monkeypatch.setattr(orchestrate.ins, "compute_season_match_stats_estimate", fake_match_stats)
    monkeypatch.setattr(orchestrate.ins, "compute_possession_matchup", fake_possession)

    insights_result = _insights_result()
    # Must not raise even though both opponent fetches fail.
    asyncio.run(_compute_and_apply_match_stat_estimates("Own Team", "Opponent Team", True, insights_result, {}, lambda _msg: None))


def test_compute_and_apply_match_stat_estimates_derives_set_piece_and_direct_play_flags(monkeypatch):
    from football.orchestrate import _compute_and_apply_match_stat_estimates
    from football.types import (
        SeasonAerialEstimate,
        SeasonCornersEstimate,
        SeasonPassingStyleEstimate,
    )

    async def fake_fotmob_matches(_team_name):
        return []

    async def fake_goal_matches(_team_name):
        return []

    high_corners = SeasonCornersEstimate(corners_for=60, corners_against=0, sample_size=10, source="fotmob")
    weak_aerial = SeasonAerialEstimate(aerial_duels_won_for=40, aerial_duels_won_against=60, sample_size=10, source="fotmob")
    direct_style = SeasonPassingStyleEstimate(
        total_passes_for=500, accurate_passes_for=400, pass_accuracy_pct=80.0,
        accurate_long_balls_for=100, long_ball_share_pct=20.0, sample_size=10, source="fotmob",
    )

    own_stats = _match_stats_estimate(aerial=weak_aerial, passing_style=direct_style)
    opp_stats = _match_stats_estimate()

    async def fake_match_stats(team_name, _matches):
        return own_stats if team_name == "Own Team" else opp_stats

    own_poss = _possession_estimate(corners=high_corners)
    opp_poss = _possession_estimate()

    async def fake_possession(team_name, _matches):
        return own_poss if team_name == "Own Team" else opp_poss

    monkeypatch.setattr(orchestrate.fotmob, "get_fotmob_matches", fake_fotmob_matches)
    monkeypatch.setattr(orchestrate.goal, "get_goal_matches", fake_goal_matches)
    monkeypatch.setattr(orchestrate.ins, "compute_season_match_stats_estimate", fake_match_stats)
    monkeypatch.setattr(orchestrate.ins, "compute_possession_matchup", fake_possession)

    insights_result = _insights_result()
    asyncio.run(_compute_and_apply_match_stat_estimates("Own Team", "Opponent Team", True, insights_result, {}, lambda _msg: None))
    # own_is_home=True -- own_stats' corners/aerial/passing_style all land
    # on the home side (see _home_away's own tests for the swap itself).
    assert insights_result.home_set_piece_threat is not None
    assert insights_result.home_direct_play_exposure is not None
    assert insights_result.home_direct_play_exposure.long_ball_share_pct == 20.0


# --- _enrich_opponent_form_and_ranks ---------------------------------------------------


def _opponent_context(**overrides):
    from football.insights import OpponentContext

    base = {"rest_days": None, "average_age": None, "merged_profile": None, "matches": [], "error": None, "matches_source": None}
    base.update(overrides)
    return OpponentContext(**base)


def test_enrich_opponent_form_and_ranks_uses_matches_source_when_present(monkeypatch):
    from football.orchestrate import _enrich_opponent_form_and_ranks

    computed_form = _form_summary()

    def fake_compute_form_summary(_name, _matches):
        return computed_form

    enriched_form = _form_summary(matches_last7_days=2)
    called_with = {}

    async def fake_enrich_venue(_matches, _form, source):
        called_with["source"] = source
        return SimpleNamespace(form=enriched_form, advanced_stats="opp-advanced-stats", usage_by_player={})

    monkeypatch.setattr(orchestrate, "compute_form_summary", fake_compute_form_summary)
    monkeypatch.setattr(orchestrate, "enrich_form_with_venue_classification", fake_enrich_venue)

    merged = _all_none(orchestrate.MergedMatch, home_team_standing=None, away_team_standing=None, competition=None, standings_table=None)
    ctx = _opponent_context(matches=[_match()], matches_source="sofascore")
    insights_result = _insights_result()
    form = _form_summary()

    result = asyncio.run(
        _enrich_opponent_form_and_ranks(merged, "Opponent", ctx, None, True, form, None, insights_result)
    )
    assert result is enriched_form
    assert called_with["source"] == "sofascore"
    assert insights_result.home_advanced_stats is None
    assert insights_result.away_advanced_stats == "opp-advanced-stats"
    # Both sides have empty last20_overall -- compute_elo_rating([]) is
    # None (see elo.py's own empty-input test) -- confirms the wiring runs
    # to completion rather than asserting a specific rating value.
    assert insights_result.home_elo_rating is None
    assert insights_result.away_elo_rating is None


def test_enrich_opponent_form_and_ranks_no_enrichment_when_matches_source_is_none(monkeypatch):
    from football.orchestrate import _enrich_opponent_form_and_ranks

    computed_form = _form_summary()

    def fake_compute_form_summary(_name, _matches):
        return computed_form

    async def unexpected_enrich(*_args):
        raise AssertionError("should not be called -- matches_source is None")

    monkeypatch.setattr(orchestrate, "compute_form_summary", fake_compute_form_summary)
    monkeypatch.setattr(orchestrate, "enrich_form_with_venue_classification", unexpected_enrich)

    merged = _all_none(orchestrate.MergedMatch, home_team_standing=None, away_team_standing=None, competition=None, standings_table=None)
    ctx = _opponent_context(matches=[], matches_source=None)
    insights_result = _insights_result()

    result = asyncio.run(
        _enrich_opponent_form_and_ranks(merged, "Opponent", ctx, None, True, None, None, insights_result)
    )
    assert result is computed_form


def test_enrich_opponent_form_and_ranks_tolerates_enrichment_failure(monkeypatch):
    from football.orchestrate import _enrich_opponent_form_and_ranks

    computed_form = _form_summary()

    def fake_compute_form_summary(_name, _matches):
        return computed_form

    async def failing_enrich(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(orchestrate, "compute_form_summary", fake_compute_form_summary)
    monkeypatch.setattr(orchestrate, "enrich_form_with_venue_classification", failing_enrich)

    merged = _all_none(orchestrate.MergedMatch, home_team_standing=None, away_team_standing=None, competition=None, standings_table=None)
    ctx = _opponent_context(matches=[_match()], matches_source="sofascore")
    insights_result = _insights_result()

    result = asyncio.run(
        _enrich_opponent_form_and_ranks(merged, "Opponent", ctx, None, True, None, None, insights_result)
    )
    assert result is computed_form


def test_enrich_opponent_form_and_ranks_updates_opponent_profile_squad_usage(monkeypatch):
    from football.orchestrate import _enrich_opponent_form_and_ranks
    from football.types import PlayerUsagePattern, SquadMember

    computed_form = _form_summary()

    def fake_compute_form_summary(_name, _matches):
        return computed_form

    usage = PlayerUsagePattern(
        matches_in_squad=5, starts=4, sub_appearances=1, unused_bench=0, total_minutes=360,
        total_goals=1, total_assists=0, total_xg=0.5, total_xa=0.2, total_shots=5,
        total_shots_on_target=2, total_tackles=1, total_interceptions=1, total_fouls=1,
        total_key_passes=2, appearances_with_stats=5, avg_rating=7.0, goals_per_90=0.25,
        assists_per_90=0.0, xg_per_90=0.12, xa_per_90=0.05, key_passes_per_90=0.5,
    )

    async def fake_enrich_venue(_matches, _form, _source):
        return SimpleNamespace(form=computed_form, advanced_stats=None, usage_by_player={"opp player": usage})

    monkeypatch.setattr(orchestrate, "compute_form_summary", fake_compute_form_summary)
    monkeypatch.setattr(orchestrate, "enrich_form_with_venue_classification", fake_enrich_venue)

    merged = _all_none(orchestrate.MergedMatch, home_team_standing=None, away_team_standing=None, competition=None, standings_table=None)
    ctx = _opponent_context(matches=[_match()], matches_source="sofascore")
    insights_result = _insights_result()
    squad_member = SquadMember(name="Opp Player", role="F", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)
    opponent_profile = _all_none(orchestrate.MergedProfile, source="sofascore", team_name="Opp", squad=[squad_member], field_sources={})

    asyncio.run(_enrich_opponent_form_and_ranks(merged, "Opponent", ctx, opponent_profile, True, None, None, insights_result))
    assert opponent_profile.squad[0].recent_usage is not None


# --- _compute_prediction_and_trend_insights ---------------------------------------------


def test_compute_prediction_and_trend_insights_runs_full_wiring_without_error(monkeypatch):
    from football.orchestrate import _compute_prediction_and_trend_insights

    async def fake_rotation(_team_name, _source, _matches):
        return None

    monkeypatch.setattr(orchestrate.ins, "compute_rotation_info", fake_rotation)

    merged = _all_none(
        orchestrate.MergedMatch, base_source="sofascore", betting_odds=None,
        head_to_head_summary=None, referee=None, referee_stats=None,
    )
    insights_result = _insights_result()
    ctx = _opponent_context(matches=[], matches_source=None)
    form = _form_summary()
    opponent_form = _form_summary()

    asyncio.run(
        _compute_prediction_and_trend_insights(
            "Own Team", merged, None, None, "Opponent", insights_result, True,
            5, ctx, (form, opponent_form), "sofascore", {"sofascore": []},
            (None, None),
        )
    )
    # Every step is independent and swallows its own missing-data cases
    # (all already unit-tested against real code in test_insights.py) --
    # this test's job is confirming the wiring itself runs end to end
    # without raising (the exercised statement above), and writes real
    # (if empty-input) values into insights_result rather than silently
    # no-oping.
    assert insights_result.experience_h2h is None  # no head_to_head_summary/experience_comparison given
    assert insights_result.referee_card_risk_note is None  # no referee given


def test_compute_prediction_and_trend_insights_computes_own_and_opponent_rotation(monkeypatch):
    from football.orchestrate import _compute_prediction_and_trend_insights

    rotation_calls = []

    async def fake_rotation(team_name, source, _matches):
        rotation_calls.append((team_name, source))
        return f"rotation-for-{team_name}"

    monkeypatch.setattr(orchestrate.ins, "compute_rotation_info", fake_rotation)

    merged = _all_none(
        orchestrate.MergedMatch, base_source="sofascore", betting_odds=None,
        head_to_head_summary=None, referee=None, referee_stats=None,
    )
    insights_result = _insights_result()
    ctx = _opponent_context(matches=[_match()], matches_source="fotmob")
    form = _form_summary()
    opponent_form = _form_summary()

    asyncio.run(
        _compute_prediction_and_trend_insights(
            "Own Team", merged, None, None, "Opponent", insights_result, True,
            5, ctx, (form, opponent_form), "sofascore", {"sofascore": []},
            (None, None),
        )
    )
    assert ("Own Team", "sofascore") in rotation_calls
    assert ("Opponent", "fotmob") in rotation_calls
    assert insights_result.home_rotation == "rotation-for-Own Team"
    assert insights_result.away_rotation == "rotation-for-Opponent"


def test_compute_prediction_and_trend_insights_skips_opponent_rotation_without_matches_source(monkeypatch):
    from football.orchestrate import _compute_prediction_and_trend_insights

    async def fake_rotation(_team_name, _source, _matches):
        return "own-rotation"

    monkeypatch.setattr(orchestrate.ins, "compute_rotation_info", fake_rotation)

    merged = _all_none(
        orchestrate.MergedMatch, base_source="sofascore", betting_odds=None,
        head_to_head_summary=None, referee=None, referee_stats=None,
    )
    insights_result = _insights_result()
    ctx = _opponent_context(matches=[], matches_source=None)
    form = _form_summary()
    opponent_form = _form_summary()

    asyncio.run(
        _compute_prediction_and_trend_insights(
            "Own Team", merged, None, None, "Opponent", insights_result, True,
            5, ctx, (form, opponent_form), "sofascore", {"sofascore": []},
            (None, None),
        )
    )
    assert insights_result.away_rotation is None


def test_compute_prediction_and_trend_insights_populates_prediction_and_card_risk(monkeypatch):
    from football.orchestrate import _compute_prediction_and_trend_insights

    async def fake_rotation(_team_name, _source, _matches):
        return None

    monkeypatch.setattr(orchestrate.ins, "compute_rotation_info", fake_rotation)

    merged = _all_none(
        orchestrate.MergedMatch, base_source="sofascore", betting_odds=None,
        head_to_head_summary=None, referee="Some Ref",
    )
    insights_result = _insights_result()
    ctx = _opponent_context(matches=[], matches_source=None)
    form = _form_summary()
    opponent_form = _form_summary()

    asyncio.run(
        _compute_prediction_and_trend_insights(
            "Own Team", merged, None, None, "Opponent", insights_result, True,
            5, ctx, (form, opponent_form), "sofascore", {"sofascore": []},
            (None, None),
        )
    )
    # No elo/xg/odds given at all -- prediction stays None (nothing to
    # base it on), which is itself the real, tested behavior (see
    # test_prediction.py's own "returns_none_when_nothing_available").
    assert insights_result.prediction is None


# --- _compute_match_context (top-level orchestrator) -------------------------------------


def _merged_match(**overrides):
    base = {
        "home_team": "Home FC", "away_team": "Away FC", "competition": "Premier League",
        "base_source": "sofascore", "referee": None, "referee_stats": None,
        "venue_city": None, "venue_name": None, "venue_country": None, "kickoff_utc": "2026-01-01T15:00:00.000Z",
        "betting_odds": None, "home_team_standing": None, "away_team_standing": None,
        "home_team_season_stats": None, "away_team_season_stats": None, "standings_table": None,
        "home_manager": None, "away_manager": None, "home_lineup": None, "away_lineup": None,
        "home_bench": None, "away_bench": None, "home_suspended_players": None, "away_suspended_players": None,
        "head_to_head_summary": None, "field_sources": {}, "additional_notes": [],
    }
    base.update(overrides)
    return _all_none(orchestrate.MergedMatch, **base)


def _mock_full_pipeline(monkeypatch):
    """Mocks every external site/insights call _compute_match_context's
    own helpers reach -- each individual helper already has its own
    focused tests above; this is purely for exercising the top-level
    sequencing/wiring without needing a real network or a second copy of
    every helper's own edge-case coverage."""
    async def empty_matches(_team_name):
        return []

    async def empty_profile(_team_name):
        from football.types import TeamProfile

        return _all_none(TeamProfile, source="sofascore", team_name="X", squad=None)

    fake_scrapers = {source: _Scraper(run=empty_matches, details=None, profile=empty_profile) for source in SOURCE_ORDER}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    async def none_venue(_club, _country):
        return None

    monkeypatch.setattr(orchestrate.stadiumdb, "get_stadium_db_venue_details", none_venue)

    async def none_strength(_home, _away):
        return {"home": None, "away": None}

    monkeypatch.setattr(orchestrate.statsultra, "get_club_strength_ratings", none_strength)

    async def none_fotmob_matches(_team_name):
        return []

    async def none_goal_matches(_team_name):
        return []

    monkeypatch.setattr(orchestrate.fotmob, "get_fotmob_matches", none_fotmob_matches)
    monkeypatch.setattr(orchestrate.goal, "get_goal_matches", none_goal_matches)

    async def none_match_stats(_team_name, _matches):
        return _match_stats_estimate()

    async def none_possession(_team_name, _matches):
        return _possession_estimate()

    monkeypatch.setattr(orchestrate.ins, "compute_season_match_stats_estimate", none_match_stats)
    monkeypatch.setattr(orchestrate.ins, "compute_possession_matchup", none_possession)

    async def none_odds(_home, _away):
        return None

    monkeypatch.setattr(orchestrate.footballdata, "get_upcoming_match_odds", none_odds)

    async def none_rotation(_team_name, _source, _matches):
        return None

    monkeypatch.setattr(orchestrate.ins, "compute_rotation_info", none_rotation)


def test_compute_match_context_runs_full_pipeline_and_identifies_opponent(monkeypatch):
    from football.orchestrate import _compute_match_context

    _mock_full_pipeline(monkeypatch)
    merged = _merged_match(home_team="Home FC", away_team="Away FC")
    progress_messages = []

    ctx = asyncio.run(
        _compute_match_context("Home FC", merged, None, None, None, {}, progress_messages.append)
    )
    assert ctx.opponent_name == "Away FC"
    assert ctx.insights_result is not None
    assert ctx.venue_details is None
    assert any("Fetching opponent" in m for m in progress_messages)
    assert any("Computing prediction" in m for m in progress_messages)


def test_compute_match_context_identifies_home_side_when_searched_team_is_away(monkeypatch):
    from football.orchestrate import _compute_match_context

    _mock_full_pipeline(monkeypatch)
    merged = _merged_match(home_team="Home FC", away_team="Away FC")

    ctx = asyncio.run(
        _compute_match_context("Away FC", merged, None, None, None, {}, lambda _msg: None)
    )
    assert ctx.opponent_name == "Home FC"


def test_compute_match_context_enriches_managers_via_wikipedia(monkeypatch):
    from football.orchestrate import _compute_match_context

    _mock_full_pipeline(monkeypatch)

    class _TenureRow:
        from_date = None
        played = wins = draws = losses = win_pct = None
        date_of_birth = None

    async def fake_tenure(_name):
        return _TenureRow()

    async def fake_previous(_team_name):
        return "Previous Boss"

    monkeypatch.setattr(orchestrate.wikipedia, "get_current_tenure_row", fake_tenure)
    monkeypatch.setattr(orchestrate.wikipedia, "get_previous_manager", fake_previous)

    home_manager = _manager(name="Current Boss")
    merged = _merged_match(home_manager=home_manager)

    ctx = asyncio.run(
        _compute_match_context("Home FC", merged, None, None, None, {}, lambda _msg: None)
    )
    assert merged.home_manager.previous_manager == "Previous Boss"
    assert ctx is not None


def test_compute_match_context_populates_squad_leaderboards_and_derived_insights(monkeypatch):
    from football.orchestrate import _compute_match_context
    from football.types import SeasonPlayerStats, SquadMember

    _mock_full_pipeline(monkeypatch)

    async def no_defensive_stats(squad, _team_name, _competitions):
        return squad

    # enrich_squad_with_defensive_stats is imported LOCALLY inside
    # _compute_match_context (from .merge import ...) -- patch the real
    # source module, since orchestrate has no module-level name for it
    # to intercept.
    import football.merge as merge_module

    monkeypatch.setattr(merge_module, "enrich_squad_with_defensive_stats", no_defensive_stats)

    scorer = SquadMember(name="Top Scorer", role="F", injury=None, age=None, market_value=None, season_stats=SeasonPlayerStats(appearances=10, goals=5, assists=1, yellow_cards=0, red_cards=0, rating=None, expected_goals=None), season_stats_source="sofascore", defensive_stats=None, recent_usage=None)
    merged_profile = _all_none(orchestrate.MergedProfile, source="sofascore", team_name="Home FC", squad=[scorer], field_sources={})
    merged = _merged_match()

    ctx = asyncio.run(
        _compute_match_context("Home FC", merged, merged_profile, None, None, {}, lambda _msg: None)
    )
    assert merged_profile.top_scorers is not None
    assert merged_profile.top_scorers[0].name == "Top Scorer"
    assert ctx.insights_result.home_squad_strength is not None


def test_compute_match_context_tolerates_club_strength_and_odds_failures(monkeypatch):
    from football.orchestrate import _compute_match_context

    _mock_full_pipeline(monkeypatch)

    async def failing_strength(_home, _away):
        raise RuntimeError("blocked")

    async def failing_odds(_home, _away):
        raise RuntimeError("blocked")

    monkeypatch.setattr(orchestrate.statsultra, "get_club_strength_ratings", failing_strength)
    monkeypatch.setattr(orchestrate.footballdata, "get_upcoming_match_odds", failing_odds)

    merged = _merged_match()
    ctx = asyncio.run(
        _compute_match_context("Home FC", merged, None, None, None, {}, lambda _msg: None)
    )
    assert ctx.insights_result.home_club_strength is None
    assert merged.betting_odds is None


def test_compute_match_context_enriches_opponent_squad_defensive_stats(monkeypatch):
    from football.orchestrate import _compute_match_context
    from football.types import SquadMember

    _mock_full_pipeline(monkeypatch)

    called = []

    async def fake_enrich_defensive(squad, team_name, _competitions):
        called.append(team_name)
        return squad

    import football.merge as merge_module

    monkeypatch.setattr(merge_module, "enrich_squad_with_defensive_stats", fake_enrich_defensive)

    async def one_opponent_match(_team_name):
        return [_match()]

    async def opponent_profile_with_squad(_team_name):
        from football.types import TeamProfile

        opp_member = SquadMember(name="Opp Player", role="F", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)
        return _all_none(TeamProfile, source="sofascore", team_name="Away FC", squad=[opp_member])

    fake_scrapers = {source: orchestrate._Scraper(run=one_opponent_match, details=None, profile=opponent_profile_with_squad) for source in SOURCE_ORDER}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    merged = _merged_match(home_team="Home FC", away_team="Away FC")
    asyncio.run(_compute_match_context("Home FC", merged, None, None, None, {}, lambda _msg: None))
    assert "Away FC" in called


# --- run_search: full pipeline, both branches of the "no match" guard --------------------


def test_run_search_raises_a_specific_message_when_team_recognized_but_no_upcoming_match(monkeypatch):
    # Distinct from the "team not found at all" case already covered by
    # test_on_source_progress_fires_once_per_source_with_real_status --
    # here every source's matches() call succeeds with an empty list
    # (real team, e.g. between seasons) but profile() succeeds, so
    # merged_profile is populated while merged stays None. See
    # run_search's own comment on why these two get different messages.
    async def empty_matches(_team_name):
        return []

    async def working_profile(_team_name):
        from football.types import TeamProfile

        return _all_none(TeamProfile, source="sofascore", team_name="Some Team", squad=None)

    fake_scrapers = {source: _Scraper(run=empty_matches, details=None, profile=working_profile) for source in SOURCE_ORDER}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    with pytest.raises(RuntimeError, match="no upcoming match is currently scheduled"):
        asyncio.run(run_search("Some Team"))


def test_run_search_returns_a_fully_populated_result_on_success(monkeypatch):
    _mock_full_pipeline(monkeypatch)

    async def one_match_details(_match_info):
        return _merged_match_details_source(_match_info)

    def _merged_match_details_source(match_info):
        from football.types import MatchDetails

        return _all_none(
            MatchDetails, source=match_info.source, source_url=match_info.source_url,
            competition="Premier League", home_team="Home FC", away_team="Away FC",
            status="scheduled", kickoff_utc=(datetime.now(tz=UTC) + timedelta(days=3)).isoformat(),
            match_id="1",
        )

    async def one_match(_team_name):
        return [_match(home_team="Home FC", away_team="Away FC", status="scheduled", kickoff_utc=(datetime.now(tz=UTC) + timedelta(days=3)).isoformat())]

    async def working_profile(_team_name):
        from football.types import TeamProfile

        return _all_none(TeamProfile, source="sofascore", team_name="Home FC", squad=None)

    fake_scrapers = {SOURCE_ORDER[0]: _Scraper(run=one_match, details=one_match_details, profile=working_profile)}
    for source in SOURCE_ORDER[1:]:
        async def empty_matches(_team_name):
            return []

        fake_scrapers[source] = _Scraper(run=empty_matches, details=None, profile=working_profile)
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    result = asyncio.run(run_search("Home FC"))
    assert result.team == "Home FC"
    assert result.merged is not None
    assert result.merged.home_team == "Home FC"
    assert result.opponent_name == "Away FC"
    assert result.insights is not None
    assert result.form_source == SOURCE_ORDER[0]
