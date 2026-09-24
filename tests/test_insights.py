import asyncio
from dataclasses import fields as _dc_fields

import pytest

from football.insights import (
    _compute_experience_comparison,
    _compute_rest_comparison,
    _defender_count,
    _median,
    _parse_xg_stat_value,
    _points_for_match,
    _result_letter,
    _simulate_new_position,
    _simulated_points,
    _split_rest_performance,
    _travel_km,
    aerial_win_pct,
    apply_usage_pattern,
    classify_card_discipline,
    classify_match_type,
    classify_standings_zone,
    compute_bench_info,
    compute_card_risks,
    compute_data_completeness,
    compute_direct_play_exposure_flag,
    compute_duel_vulnerabilities,
    compute_experience_h2h,
    compute_fatigue_flag,
    compute_fullback_exposure,
    compute_home_advantage,
    compute_losing_streak_context,
    compute_opponent_rank_record,
    compute_presence,
    compute_recent_meetings,
    compute_referee_card_risk_note,
    compute_resilience,
    compute_rest_performance,
    compute_set_piece_threat_flag,
    compute_squad_strength,
    compute_standings_impact,
    compute_streak_stability,
    compute_travel_info,
    is_recent_appointment,
)
from football.types import (
    DefensiveStats,
    ExperienceComparison,
    FormSummary,
    HeadToHeadSummary,
    MatchDetails,
    MatchInfo,
    MatchInsights,
    RefereeStats,
    RotationInfo,
    SeasonAerialEstimate,
    SeasonCornersEstimate,
    SeasonPassingStyleEstimate,
    SeasonPlayerStats,
    SeasonXGEstimate,
    SquadMember,
    StandingsTableRow,
    StreakInfo,
    TeamStanding,
)


def _all_none(cls, **overrides):
    """Constructs a dataclass instance with every field defaulted to
    None, overridden as needed -- avoids hand-listing dozens of fields
    just to test one function that only cares about a handful. Works for
    any dataclass here (types.py doesn't enforce its type hints at
    runtime), not just MatchDetails/MatchInsights."""
    base = {f.name: None for f in _dc_fields(cls)}
    base.update(overrides)
    return cls(**base)


def _standing(**overrides):
    base = {"position": 1, "played": 10, "wins": 5, "draws": 3, "losses": 2, "points": 18, "goal_diff": "+5", "total_teams": 20}
    base.update(overrides)
    return _all_none(TeamStanding, **base)


def _match(**overrides):
    base = {"source": "sofascore", "source_url": "https://x", "home_team": "Home FC", "away_team": "Away FC"}
    base.update(overrides)
    return _all_none(MatchInfo, **base)


def test_parses_genuine_zero_xg_as_zero_not_none():
    # Regression test: a prior `float(raw) or None` implementation turned
    # a real 0.0 xG (Python falsy-zero) into a misleading null, silently
    # conflating "the team had 0.00 xG" with "xG wasn't published".
    assert _parse_xg_stat_value("0") == 0.0
    assert _parse_xg_stat_value("0.0") == 0.0


def test_parses_real_nonzero_xg():
    assert _parse_xg_stat_value("1.85") == 1.85


def test_returns_none_for_unparseable_value():
    assert _parse_xg_stat_value("N/A") is None


# --- compute_recent_meetings (async) -------------------------------------------------


def test_compute_recent_meetings_none_without_any_matching_opponent_in_form():
    result = asyncio.run(compute_recent_meetings([], [_form_result(opponent="Someone Else")], "Rival FC", "sofascore"))
    assert result is None


def test_compute_recent_meetings_fetches_details_for_matching_raw_fixtures(monkeypatch):
    from football import orchestrate
    from football.types import MatchStatItem

    raw_match = _match(home_team="Home FC", away_team="Rival FC", kickoff_utc="2026-01-01T15:00:00.000Z")
    details = _all_none(
        MatchDetails, source="sofascore", source_url="https://x", home_team="Home FC", away_team="Rival FC",
        home_formation="4-3-3", away_formation="4-4-2", home_lineup=None, away_lineup=None,
        match_stats=[MatchStatItem(name="Expected goals (xG)", home="1.8", away="0.9")],
    )

    async def fake_details(_match_info):
        return details

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(fake_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    form_results = [_form_result(opponent="Rival FC", date="2026-01-01T15:00:00.000Z", scoreline="2-1")]
    meetings = asyncio.run(compute_recent_meetings([raw_match], form_results, "Rival FC", "sofascore"))
    assert len(meetings) == 1
    assert meetings[0].home_formation == "4-3-3"
    assert meetings[0].home_xg == 1.8
    assert meetings[0].away_xg == 0.9
    assert (meetings[0].home_team, meetings[0].away_team) == ("Home FC", "Rival FC")


def test_compute_recent_meetings_detects_neutral_venue(monkeypatch):
    """Regression: a cup final at a neutral venue was previously forced
    into "home"/"away" -- HeadToHeadMeeting.venue had no third option and
    nothing checked venue country against either team's own country."""
    from football import orchestrate

    raw_match = _match(home_team="Home FC", away_team="Rival FC", kickoff_utc="2026-01-01T15:00:00.000Z")
    details = _all_none(
        MatchDetails, source="sofascore", source_url="https://x", home_team="Home FC", away_team="Rival FC",
        venue_country="Germany", home_team_country="England", away_team_country="Spain",
    )

    async def fake_details(_match_info):
        return details

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(fake_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    form_results = [_form_result(opponent="Rival FC", date="2026-01-01T15:00:00.000Z", venue="away")]
    meetings = asyncio.run(compute_recent_meetings([raw_match], form_results, "Rival FC", "sofascore"))
    assert meetings[0].venue == "neutral"


def test_compute_recent_meetings_keeps_home_away_when_one_team_matches_venue_country(monkeypatch):
    from football import orchestrate

    raw_match = _match(home_team="Home FC", away_team="Rival FC", kickoff_utc="2026-01-01T15:00:00.000Z")
    details = _all_none(
        MatchDetails, source="sofascore", source_url="https://x", home_team="Home FC", away_team="Rival FC",
        venue_country="England", home_team_country="England", away_team_country="Spain",
    )

    async def fake_details(_match_info):
        return details

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(fake_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    form_results = [_form_result(opponent="Rival FC", date="2026-01-01T15:00:00.000Z", venue="away")]
    meetings = asyncio.run(compute_recent_meetings([raw_match], form_results, "Rival FC", "sofascore"))
    assert meetings[0].venue == "away"


def test_compute_recent_meetings_keeps_form_only_row_when_no_raw_fixture_matches():
    # Regression (F8b): a form-window result against the opponent with no
    # matching raw fixture used to be dropped entirely, losing a real
    # scoreline. Now published form-only (no formations/lineups).
    form_results = [_form_result(opponent="Rival FC", date="2026-01-01T15:00:00.000Z", scoreline="1-0", venue="home")]
    result = asyncio.run(compute_recent_meetings([], form_results, "Rival FC", "sofascore", team_name="Home FC"))
    assert result is not None and len(result) == 1
    assert result[0].scoreline == "1-0"
    assert result[0].home_formation is None
    assert result[0].away_lineup is None
    assert (result[0].home_team, result[0].away_team) == ("Home FC", "Rival FC")


def test_compute_recent_meetings_form_only_maps_away_venue_home_first():
    form_results = [_form_result(opponent="Rival FC", date="2026-01-01T15:00:00.000Z", venue="away")]
    result = asyncio.run(compute_recent_meetings([], form_results, "Rival FC", "sofascore", team_name="Home FC"))
    assert result is not None and len(result) == 1
    assert (result[0].home_team, result[0].away_team) == ("Rival FC", "Home FC")


def test_compute_recent_meetings_form_only_leaves_team_names_none_without_team_name():
    form_results = [_form_result(opponent="Rival FC", date="2026-01-01T15:00:00.000Z")]
    result = asyncio.run(compute_recent_meetings([], form_results, "Rival FC", "sofascore"))
    assert result is not None and len(result) == 1
    assert result[0].home_team is None
    assert result[0].away_team is None


def test_compute_recent_meetings_tolerates_details_fetch_failure(monkeypatch):
    from football import orchestrate

    raw_match = _match(home_team="Home FC", away_team="Rival FC", kickoff_utc="2026-01-01T15:00:00.000Z")

    async def failing_details(_match_info):
        raise RuntimeError("blocked")

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(failing_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    form_results = [_form_result(opponent="Rival FC", date="2026-01-01T15:00:00.000Z", scoreline="2-1")]
    result = asyncio.run(compute_recent_meetings([raw_match], form_results, "Rival FC", "sofascore"))
    # Details failed, but the scoreline/teams still come from form+raw --
    # do not drop the head-to-head row just because box score is gone.
    assert result is not None and len(result) == 1
    assert result[0].scoreline == "2-1"
    assert (result[0].home_team, result[0].away_team) == ("Home FC", "Rival FC")
    assert result[0].home_formation is None
    assert result[0].home_lineup is None


def test_compute_recent_meetings_falls_back_to_form_xg_when_details_lack_match_stats(monkeypatch):
    from football import orchestrate
    from football.types import MatchStatItem  # noqa: F401 - documents intent

    raw_match = _match(home_team="Home FC", away_team="Rival FC", kickoff_utc="2026-01-01T15:00:00.000Z")
    details = _all_none(
        MatchDetails, source="sofascore", source_url="https://x",
        home_team="Home FC", away_team="Rival FC",
        match_stats=None,
    )

    async def fake_details(_match_info):
        return details

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(fake_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    # Searched team was the away side: xg_for/xg_against swap into home-first.
    form_results = [_form_result(
        opponent="Rival FC", date="2026-01-01T15:00:00.000Z",
        venue="away", xg_for=1.1, xg_against=2.4,
    )]
    meetings = asyncio.run(compute_recent_meetings([raw_match], form_results, "Rival FC", "sofascore"))
    assert meetings[0].home_xg == 2.4
    assert meetings[0].away_xg == 1.1


def test_compute_recent_meetings_prefers_details_xg_over_form_when_both_present(monkeypatch):
    from football import orchestrate
    from football.types import MatchStatItem

    raw_match = _match(home_team="Home FC", away_team="Rival FC", kickoff_utc="2026-01-01T15:00:00.000Z")
    details = _all_none(
        MatchDetails, source="sofascore", source_url="https://x",
        home_team="Home FC", away_team="Rival FC",
        match_stats=[MatchStatItem(name="Expected goals (xG)", home="1.8", away="0.9")],
    )

    async def fake_details(_match_info):
        return details

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(fake_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    form_results = [_form_result(
        opponent="Rival FC", date="2026-01-01T15:00:00.000Z",
        venue="home", xg_for=9.9, xg_against=0.1,
    )]
    meetings = asyncio.run(compute_recent_meetings([raw_match], form_results, "Rival FC", "sofascore"))
    assert meetings[0].home_xg == 1.8
    assert meetings[0].away_xg == 0.9


def test_compute_recent_meetings_caps_at_three(monkeypatch):
    from football import orchestrate

    raw_matches = [_match(home_team="Home FC", away_team="Rival FC", kickoff_utc=f"2026-01-0{i}T15:00:00.000Z") for i in range(1, 5)]
    details = _all_none(MatchDetails, source="sofascore", source_url="https://x", home_team="Home FC", away_team="Rival FC", home_lineup=None, away_lineup=None, match_stats=None)

    async def fake_details(_match_info):
        return details

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(fake_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    form_results = [_form_result(opponent="Rival FC", date=f"2026-01-0{i}T15:00:00.000Z") for i in range(1, 5)]
    meetings = asyncio.run(compute_recent_meetings(raw_matches, form_results, "Rival FC", "sofascore"))
    assert len(meetings) == 3


# --- compute_rotation_info (async) ------------------------------------------------------


def test_compute_rotation_info_none_with_fewer_than_two_played_matches():
    from football.insights import compute_rotation_info

    single_played = _match(home_team="Home FC", away_team="X", home_score=1, away_score=0, kickoff_utc="2026-01-01T00:00:00.000Z")
    result = asyncio.run(compute_rotation_info("Home FC", "sofascore", [single_played]))
    assert result is None


def test_compute_rotation_info_diffs_starting_xi_between_last_two_played(monkeypatch):
    from football import orchestrate
    from football.types import LineupPlayer

    last = _match(home_team="Home FC", away_team="X", home_score=2, away_score=0, kickoff_utc="2026-01-08T00:00:00.000Z")
    prev = _match(home_team="Home FC", away_team="Y", home_score=1, away_score=1, kickoff_utc="2026-01-01T00:00:00.000Z")
    not_yet_played = _match(home_team="Home FC", away_team="Z", home_score=None, away_score=None, kickoff_utc="2026-01-15T00:00:00.000Z")

    last_details = _all_none(
        MatchDetails, source="sofascore", source_url="https://x", home_team="Home FC", away_team="X",
        home_formation="4-3-3", away_formation=None,
        home_lineup=[_all_none(LineupPlayer, name="A"), _all_none(LineupPlayer, name="B")], away_lineup=None,
    )
    prev_details = _all_none(
        MatchDetails, source="sofascore", source_url="https://x", home_team="Home FC", away_team="Y",
        home_formation="4-4-2", away_formation=None,
        home_lineup=[_all_none(LineupPlayer, name="A"), _all_none(LineupPlayer, name="C")], away_lineup=None,
    )

    async def fake_details(match_info):
        return last_details if match_info is last else prev_details

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(fake_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    from football.insights import compute_rotation_info

    result = asyncio.run(compute_rotation_info("Home FC", "sofascore", [not_yet_played, last, prev]))
    assert result is not None
    assert result.changed_players == 1  # "B" is new, "A" carried over
    assert result.starting_xi_size == 2
    assert result.formation_changed is True
    assert result.preceding_result == "D"  # prev match was 1-1


def test_compute_rotation_info_none_when_lineup_data_missing(monkeypatch):
    from football import orchestrate

    last = _match(home_team="Home FC", away_team="X", home_score=2, away_score=0, kickoff_utc="2026-01-08T00:00:00.000Z")
    prev = _match(home_team="Home FC", away_team="Y", home_score=1, away_score=1, kickoff_utc="2026-01-01T00:00:00.000Z")
    empty_details = _all_none(MatchDetails, source="sofascore", source_url="https://x", home_team="Home FC", away_team="X", home_lineup=None, away_lineup=None)

    async def fake_details(_match_info):
        return empty_details

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(fake_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    from football.insights import compute_rotation_info

    result = asyncio.run(compute_rotation_info("Home FC", "sofascore", [last, prev]))
    assert result is None


def test_compute_rotation_info_none_when_details_fetch_fails(monkeypatch):
    from football import orchestrate

    last = _match(home_team="Home FC", away_team="X", home_score=2, away_score=0, kickoff_utc="2026-01-08T00:00:00.000Z")
    prev = _match(home_team="Home FC", away_team="Y", home_score=1, away_score=1, kickoff_utc="2026-01-01T00:00:00.000Z")

    async def failing_details(_match_info):
        raise RuntimeError("blocked")

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(failing_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    from football.insights import compute_rotation_info

    result = asyncio.run(compute_rotation_info("Home FC", "sofascore", [last, prev]))
    assert result is None


def test_build_rotation_info_none_when_team_unresolvable():
    from football.insights import _build_rotation_info

    last = _match(home_team="Unrelated", away_team="X", kickoff_utc="2026-01-08T00:00:00.000Z")
    prev = _match(home_team="Home FC", away_team="Y", kickoff_utc="2026-01-01T00:00:00.000Z")
    result = _build_rotation_info("Home FC", last, prev, None, None)
    assert result is None


def test_returns_none_for_missing_value():
    assert _parse_xg_stat_value(None) is None


def test_completeness_does_not_count_outcome_only_fields_for_an_unplayed_match():
    # An upcoming fixture's real analytical value is pre-match
    # (difficulty/rest/form comparisons) -- fields that can only exist
    # once a match is live or finished (attendance, in-match stats,
    # timeline, player of the match) shouldn't count against its
    # completeness at all when the match genuinely hasn't kicked off,
    # the same way home_score/away_score already didn't
    # (_COMPLETENESS_EXCLUDE, unconditionally) -- this extends that same
    # idea to the rest of the TRUE outcome-only fields, but only while
    # not-yet-started, since they become real data once the match is
    # live or finished. Lineup/bench/formation are deliberately NOT in
    # this set -- see the next test.
    merged = _all_none(MatchDetails, status="notstarted", referee="Some Ref")
    insights = _all_none(MatchInsights)
    result = compute_data_completeness(merged, insights)

    merged_finished = _all_none(MatchDetails, status="finished", referee="Some Ref")
    result_finished = compute_data_completeness(merged_finished, insights)

    # Same underlying (all-null) data, but the not-started run should
    # have a strictly smaller total -- outcome-only fields were removed
    # from the denominator, not merely scored as unpopulated.
    assert result["total"] < result_finished["total"]


def test_completeness_still_counts_lineup_and_bench_info_for_an_unplayed_match():
    # Sofascore's own lineups payload goes absent -> predicted ->
    # confirmed (football/sites/sofascore.py's `lineup_confirmed`
    # field/comment) -- a predicted starting XI, built from recent
    # matches and injury news, can legitimately exist well before
    # kickoff. So unlike attendance/match_stats/event_timeline/
    # player_of_the_match, home_lineup/away_lineup/home_bench/
    # away_bench/home_formation/away_formation (and the insights-level
    # home_bench_info/away_bench_info computed from them) must NOT be
    # excluded from the denominator for a not-started match -- their
    # absence there is real, informative "not published yet", the same
    # as referee/odds, not a category error.
    merged_not_started = _all_none(MatchDetails, status="notstarted")
    merged_finished = _all_none(MatchDetails, status="finished")
    insights = _all_none(MatchInsights)

    result_not_started = compute_data_completeness(merged_not_started, insights)
    result_finished = compute_data_completeness(merged_finished, insights)

    # The not-started total is still smaller than finished's -- but only
    # by the 6 TRUE outcome-only fields (attendance, match_stats,
    # event_timeline, player_of_the_match, set_piece_goals,
    # shotmap_stats), not by lineup/bench/formation/bench_info too. If
    # those were still being excluded pre-kickoff, the gap would be
    # larger than 6.
    assert result_finished["total"] - result_not_started["total"] == 6


def test_completeness_ignores_set_piece_goals_zero_shell_for_an_unplayed_match():
    # sofascore.py's _extract_set_piece_goals/_extract_shotmap_stats
    # deliberately return a zero-filled dataclass, never None, for an
    # unplayed match (confirmed live) -- _is_populated treats any
    # dataclass as populated unconditionally, so without excluding these
    # two from the not-started denominator they'd always look
    # "populated" even though nothing was actually fetched/computed.
    from football.types import (
        SetPieceGoalCounts,
        SetPieceGoals,
        ShotmapSideStats,
        ShotmapStats,
    )

    zero_shell = SetPieceGoals(home=SetPieceGoalCounts(corner=0, penalty=0, free_kick=0), away=SetPieceGoalCounts(corner=0, penalty=0, free_kick=0))
    zero_shotmap = ShotmapStats(
        home=ShotmapSideStats(non_penalty_xg=0, set_piece_xg=0, penalties_awarded=0),
        away=ShotmapSideStats(non_penalty_xg=0, set_piece_xg=0, penalties_awarded=0),
    )
    merged_with_shell = _all_none(MatchDetails, status="notstarted", set_piece_goals=zero_shell, shotmap_stats=zero_shotmap)
    merged_without = _all_none(MatchDetails, status="notstarted", set_piece_goals=None, shotmap_stats=None)
    insights = _all_none(MatchInsights)

    result_with = compute_data_completeness(merged_with_shell, insights)
    result_without = compute_data_completeness(merged_without, insights)

    # Same total either way (both excluded from the denominator while
    # not-started), and the same populated count -- the zero shell must
    # NOT count as populated data for an unplayed match.
    assert result_with["total"] == result_without["total"]
    assert result_with["populated"] == result_without["populated"]


def test_completeness_none_insights_contributes_zero():
    # None insights contributes 0/0 -- the total must equal exactly
    # merged's own total, not merged's total plus every insights field
    # (which is what a *present-but-all-null* MatchInsights would add).
    merged = _all_none(MatchDetails, status="finished")
    from football.insights import _count_merged_completeness

    merged_total, merged_missing = _count_merged_completeness(merged, not_started=False)
    result = compute_data_completeness(merged, None)
    assert result["populated"] == merged_total - len(merged_missing)
    assert result["total"] == merged_total
    assert result["missing"] == merged_missing
    assert result["denominator"]  # documents what total counts
    assert result["outcome_fields_excluded_pre_match"] == []  # finished match: nothing excluded


def test_completeness_missing_names_exactly_the_fields_without_data():
    merged = _all_none(MatchDetails, status="finished", referee="Some Ref")
    insights = _all_none(MatchInsights, match_type="competitive")
    result = compute_data_completeness(merged, insights)
    assert "referee" not in result["missing"]
    assert "weather" in result["missing"]
    assert "match_type" not in result["missing"]
    assert "home_bench_info" in result["missing"]
    assert result["populated"] + len(result["missing"]) == result["total"]


def test_completeness_excludes_notes_that_are_null_by_design_when_theres_nothing_to_flag():
    # squad_value_basis_note/projected_xi_basis are null in the common
    # case (both squads from the same source; a real lineup already
    # exists) -- that's a checked "nothing to report", not an unknown gap.
    # corners_cross_source_note: null when the two corner series agree.
    merged = _all_none(MatchDetails, status="finished")
    insights = _all_none(
        MatchInsights, squad_value_basis_note=None, projected_xi_basis=None, corners_cross_source_note=None
    )
    result = compute_data_completeness(merged, insights)
    assert "squad_value_basis_note" not in result["missing"]
    assert "projected_xi_basis" not in result["missing"]
    assert "corners_cross_source_note" not in result["missing"]


def test_completeness_counts_losing_streak_context_checked_fine_as_populated():
    from football.types import LosingStreakContextInfo

    merged = _all_none(MatchDetails, status="finished")
    sentinel = LosingStreakContextInfo(streak_count=0, xg_delta=None, potential_turnaround=None)
    insights = _all_none(MatchInsights, home_losing_streak_context=sentinel, away_losing_streak_context=sentinel)
    result = compute_data_completeness(merged, insights)
    assert "home_losing_streak_context" not in result["missing"]
    assert "away_losing_streak_context" not in result["missing"]


def test_completeness_lists_losing_streak_context_as_missing_when_no_streak_data():
    merged = _all_none(MatchDetails, status="finished")
    insights = _all_none(MatchInsights, home_losing_streak_context=None, away_losing_streak_context=None)
    result = compute_data_completeness(merged, insights)
    assert "home_losing_streak_context" in result["missing"]
    assert "away_losing_streak_context" in result["missing"]


def test_completeness_counts_a_real_populated_scalar_insights_field():
    merged = _all_none(MatchDetails, status="finished")
    insights_with = _all_none(MatchInsights, match_type="competitive")
    insights_without = _all_none(MatchInsights, match_type=None)
    result_with = compute_data_completeness(merged, insights_with)
    result_without = compute_data_completeness(merged, insights_without)
    assert result_with["populated"] == result_without["populated"] + 1


def test_completeness_counts_a_real_nonempty_list_insights_field():
    from football.types import PresenceEntry

    merged = _all_none(MatchDetails, status="finished")
    presence = [PresenceEntry(name="A", status="P", starting=True, on_bench=False, reason=None)]
    insights_with = _all_none(MatchInsights, home_presence=presence)
    insights_without = _all_none(MatchInsights, home_presence=None)
    result_with = compute_data_completeness(merged, insights_with)
    result_without = compute_data_completeness(merged, insights_without)
    assert result_with["populated"] == result_without["populated"] + 1


def test_completeness_counts_a_real_dataclass_valued_insights_field():
    from football.types import EloRating

    merged = _all_none(MatchDetails, status="finished")
    insights_with = _all_none(MatchInsights, home_elo_rating=EloRating(elo=1500.0, as_of="2026-01-01"))
    insights_without = _all_none(MatchInsights, home_elo_rating=None)
    result_with = compute_data_completeness(merged, insights_with)
    result_without = compute_data_completeness(merged, insights_without)
    assert result_with["populated"] == result_without["populated"] + 1


# --- is_empty_value -------------------------------------------------------------------


def test_is_empty_value_catches_none_empty_list_and_empty_string():
    from football.insights import is_empty_value

    assert is_empty_value(None) is True
    assert is_empty_value([]) is True
    assert is_empty_value("") is True


def test_completeness_counts_a_real_populated_int_field_as_populated():
    # attendance is a bare int field (not a list/dict/str/dataclass) --
    # _is_populated's final unconditional `return True` fallback is the
    # only branch that handles a genuinely scalar non-string value like
    # this one.
    merged_with = _all_none(MatchDetails, status="finished", attendance=45000)
    merged_without = _all_none(MatchDetails, status="finished", attendance=None)
    insights = _all_none(MatchInsights)
    result_with = compute_data_completeness(merged_with, insights)
    result_without = compute_data_completeness(merged_without, insights)
    assert result_with["populated"] == result_without["populated"] + 1


def test_is_empty_value_false_for_real_values():
    from football.insights import is_empty_value

    assert is_empty_value("some value") is False
    assert is_empty_value([1, 2]) is False
    assert is_empty_value(0) is False


def test_completeness_counts_a_real_checked_empty_card_risks_list_as_populated():
    # Confirmed live: a Liverpool/Ipswich run returned home_card_risks
    # == away_card_risks == [] (not None) -- both squads genuinely have
    # no player at 4+ yellows or a red card yet this season, a real,
    # checked result from compute_card_risks, not missing data. The
    # generic list-emptiness check in _is_populated would otherwise
    # score this identically to never having squad data at all.
    merged = _all_none(MatchDetails, status="finished")
    insights_with_real_empty = _all_none(MatchInsights, home_card_risks=[], away_card_risks=[])
    insights_with_none = _all_none(MatchInsights, home_card_risks=None, away_card_risks=None)

    result_with = compute_data_completeness(merged, insights_with_real_empty)
    result_without = compute_data_completeness(merged, insights_with_none)

    assert result_with["total"] == result_without["total"]
    assert result_with["populated"] == result_without["populated"] + 2


def test_completeness_counts_duel_vulnerabilities_and_fullback_exposure_the_same_way():
    merged = _all_none(MatchDetails, status="finished")
    insights = _all_none(
        MatchInsights,
        home_duel_vulnerabilities=[], away_duel_vulnerabilities=[],
        home_fullback_exposure=[], away_fullback_exposure=[],
    )
    insights_none = _all_none(MatchInsights)

    result = compute_data_completeness(merged, insights)
    result_none = compute_data_completeness(merged, insights_none)

    assert result["populated"] == result_none["populated"] + 4


def test_completeness_credits_a_real_predicted_formation_for_a_not_started_match():
    # A predicted formation published ahead of kickoff is real,
    # meaningful data -- it should raise the populated count for a
    # not-started match, not be discarded/ignored just because the
    # match hasn't happened yet.
    merged_with = _all_none(MatchDetails, status="notstarted", home_formation="4-3-3")
    merged_without = _all_none(MatchDetails, status="notstarted", home_formation=None)
    insights = _all_none(MatchInsights)

    result_with = compute_data_completeness(merged_with, insights)
    result_without = compute_data_completeness(merged_without, insights)

    # Same total either way (the field is always counted at every
    # status now), but populated is strictly higher when a real
    # predicted formation is present.
    assert result_with["total"] == result_without["total"]
    assert result_with["populated"] > result_without["populated"]


def _form_result(**overrides):
    base = {
        "opponent": "Rival FC", "competition": "Premier League", "date": None, "result": "W", "scoreline": "2-1",
        "venue": "home", "margin": 1, "neutral_venue": None, "ht_scoreline": None, "xg_for": None, "xg_against": None,
    }
    base.update(overrides)
    from football.types import FormResult

    return FormResult(**base)


# --- classify_standings_zone ---------------------------------------------


def test_standings_zone_top_of_table():
    zone = classify_standings_zone(_standing(position=2, total_teams=20), "Premier League", None)
    assert zone.zone == "top-of-table"


def test_standings_zone_relegation():
    zone = classify_standings_zone(_standing(position=19, total_teams=20), "Premier League", None)
    assert zone.zone == "relegation-zone"


def test_standings_zone_midtable():
    zone = classify_standings_zone(_standing(position=10, total_teams=20), "Premier League", None)
    assert zone.zone == "midtable"


def test_standings_zone_unknown_competition_uses_generic_4_3_rule():
    # 4 continental / 3 relegation spots is the fallback for a competition
    # not in LEAGUE_STAKES.
    zone = classify_standings_zone(_standing(position=4, total_teams=20), "Some Obscure League", None)
    assert zone.zone == "top-of-table"
    zone2 = classify_standings_zone(_standing(position=5, total_teams=20), "Some Obscure League", None)
    assert zone2.zone == "midtable"


def test_standings_zone_none_without_standing_or_total_teams():
    assert classify_standings_zone(None, "Premier League", None) is None
    assert classify_standings_zone(_standing(total_teams=None), "Premier League", None) is None


def test_standings_zone_points_from_boundary_uses_closest_gap():
    table = [
        StandingsTableRow(team_name="A", position=4, points=50),
        StandingsTableRow(team_name="B", position=17, points=20),
    ]
    zone = classify_standings_zone(_standing(position=10, points=30, total_teams=20), "Premier League", table)
    # distance to continental boundary (50) = 20, to relegation boundary (20) = 10
    assert zone.points_from_boundary == 10
    # in_the_mix requires <= 6 points from a boundary -- 10 is not close enough.
    assert zone.in_the_mix is False


# --- classify_match_type --------------------------------------------------


def test_match_type_friendly_variants():
    assert classify_match_type("Club Friendly Games") == "friendly"
    assert classify_match_type("Pre-Season Cup") == "friendly"
    assert classify_match_type("Preseason Tournament") == "friendly"


def test_match_type_competitive():
    assert classify_match_type("Premier League") == "competitive"


def test_match_type_none_without_competition():
    assert classify_match_type(None) is None


# --- classify_card_discipline ---------------------------------------------


def test_card_discipline_elevated_risk_on_high_yellow_rate():
    stats = _all_none(RefereeStats, yellow_cards=30, red_cards=1)  # unused fields fine as None here (dataclass doesn't enforce)
    discipline = classify_card_discipline(stats, _standing(played=10))
    assert discipline.elevated_risk is True
    assert discipline.yellow_per_game == 3.0


def test_card_discipline_not_elevated():
    stats = _all_none(RefereeStats, yellow_cards=10, red_cards=0)
    discipline = classify_card_discipline(stats, _standing(played=10))
    assert discipline.elevated_risk is False


def test_card_discipline_none_without_stats_or_played():
    assert classify_card_discipline(None, _standing()) is None
    assert classify_card_discipline(_all_none(RefereeStats, yellow_cards=1, red_cards=0), None) is None


# --- _travel_km / compute_travel_info --------------------------------------


def test_travel_km_none_traveling_is_zero():
    assert _travel_km(False, "England", "England") == 0


def test_travel_km_none_when_unknown():
    assert _travel_km(None, "England", "England") is None


def test_travel_km_none_without_from_country_even_if_traveling():
    assert _travel_km(True, None, "England") is None


def test_compute_travel_info_none_without_venue_country():
    merged = _all_none(MatchDetails, venue_country=None, home_team_country="England", away_team_country="Spain")
    assert compute_travel_info(merged) is None


def test_compute_travel_info_none_without_either_team_country():
    merged = _all_none(MatchDetails, venue_country="England", home_team_country=None, away_team_country=None)
    assert compute_travel_info(merged) is None


def test_compute_travel_info_home_not_traveling_in_own_country():
    merged = _all_none(MatchDetails, venue_country="England", home_team_country="England", away_team_country="Spain")
    info = compute_travel_info(merged)
    assert info.home_traveling is False
    assert info.home_travel_distance_km == 0
    assert info.away_traveling is True


def test_compute_travel_info_uses_exact_distance_for_same_country_travel():
    """Regression: Newcastle away at Coventry (confirmed live) previously
    showed away_traveling=False, away_travel_distance_km=0 for a genuine
    ~250km trip, since the country-only check can never detect intra-
    country travel. Exact venue coordinates (both England here) must
    override that and report the real distance."""
    merged = _all_none(
        MatchDetails, venue_country="England", home_team_country="England", away_team_country="England",
        venue_lat=52.4478, venue_lon=-1.4952,  # Coventry Building Society Arena
        home_team_venue_lat=52.4478, home_team_venue_lon=-1.4952,  # home team plays at the match venue
        away_team_venue_lat=54.975469, away_team_venue_lon=-1.621874,  # Newcastle's St James' Park
    )
    info = compute_travel_info(merged)
    assert info.away_traveling is True
    assert info.away_travel_distance_km > 200
    assert info.home_traveling is False
    assert info.home_travel_distance_km == 0


def test_compute_travel_info_falls_back_to_country_approximation_without_coordinates():
    merged = _all_none(
        MatchDetails, venue_country="England", home_team_country="England", away_team_country="England",
        venue_lat=None, venue_lon=None, home_team_venue_lat=None, away_team_venue_lat=None,
    )
    info = compute_travel_info(merged)
    assert info.away_traveling is False
    assert info.away_travel_distance_km == 0


# --- _defender_count / _result_letter --------------------------------------


def test_defender_count_parses_leading_formation_number():
    assert _defender_count("4-3-3") == 4
    assert _defender_count("3-4-3") == 3


def test_defender_count_none_without_formation():
    assert _defender_count(None) is None


def test_result_letter_win_loss_draw():
    assert _result_letter(2, 1) == "W"
    assert _result_letter(1, 2) == "L"
    assert _result_letter(1, 1) == "D"


def test_result_letter_none_with_missing_score():
    assert _result_letter(None, 1) is None
    assert _result_letter(1, None) is None


# --- compute_resilience ----------------------------------------------------


def test_resilience_computes_draw_share_of_non_wins():
    results = [_form_result(result="W"), _form_result(result="D"), _form_result(result="D"), _form_result(result="L")]
    info = compute_resilience(results)
    # non-wins: D, D, L -- 2 of 3 are draws
    assert info.non_win_sample_size == 3
    assert info.draw_share_pct == 67


def test_resilience_none_with_no_non_win_results():
    results = [_form_result(result="W"), _form_result(result="W")]
    assert compute_resilience(results) is None


# --- _points_for_match / _split_rest_performance / compute_rest_performance -


def test_points_for_match_home_win():
    m = _match(home_team="Home FC", away_team="Away FC", home_score=2, away_score=0)
    assert _points_for_match(m, "Home FC") == 3


def test_points_for_match_away_draw():
    m = _match(home_team="Home FC", away_team="Away FC", home_score=1, away_score=1)
    assert _points_for_match(m, "Away FC") == 1


def test_points_for_match_loss():
    m = _match(home_team="Home FC", away_team="Away FC", home_score=0, away_score=2)
    assert _points_for_match(m, "Home FC") == 0


def test_points_for_match_none_when_team_not_in_match():
    m = _match(home_team="Home FC", away_team="Away FC", home_score=1, away_score=0)
    assert _points_for_match(m, "Unrelated FC") is None


def test_split_rest_performance_short_vs_long_rest():
    played = [
        _match(home_team="X", away_team="Home FC", kickoff_utc="2026-01-01T00:00:00.000Z", home_score=0, away_score=0),
        # 2 days rest -- short
        _match(home_team="Home FC", away_team="Y", kickoff_utc="2026-01-03T00:00:00.000Z", home_score=2, away_score=0),
        # 10 days rest -- long
        _match(home_team="Home FC", away_team="Z", kickoff_utc="2026-01-13T00:00:00.000Z", home_score=1, away_score=1),
    ]
    short_pts, short_count, long_pts, long_count = _split_rest_performance(played, "Home FC")
    assert (short_pts, short_count) == (3, 1)
    assert (long_pts, long_count) == (1, 1)


def test_compute_rest_performance_none_with_fewer_than_two_played_matches():
    played = [_match(home_team="Home FC", away_team="Y", kickoff_utc="2026-01-01T00:00:00.000Z", home_score=1, away_score=0)]
    assert compute_rest_performance("Home FC", played) is None


def test_compute_rest_performance_computes_ppg_for_both_buckets():
    matches = [
        _match(home_team="X", away_team="Home FC", kickoff_utc="2026-01-01T00:00:00.000Z", home_score=0, away_score=0),
        _match(home_team="Home FC", away_team="Y", kickoff_utc="2026-01-03T00:00:00.000Z", home_score=2, away_score=0),
        _match(home_team="Home FC", away_team="Z", kickoff_utc="2026-01-13T00:00:00.000Z", home_score=1, away_score=1),
    ]
    result = compute_rest_performance("Home FC", matches)
    assert result.short_rest_ppg == 3.0
    assert result.short_rest_sample_size == 1
    assert result.long_rest_ppg == 1.0
    assert result.long_rest_sample_size == 1


def test_compute_rest_performance_none_when_team_unresolvable_in_every_match():
    matches = [
        _match(home_team="X", away_team="Y", kickoff_utc="2026-01-01T00:00:00.000Z", home_score=0, away_score=0),
        _match(home_team="A", away_team="B", kickoff_utc="2026-01-03T00:00:00.000Z", home_score=1, away_score=1),
    ]
    assert compute_rest_performance("Home FC", matches) is None


def test_split_rest_performance_skips_matches_where_team_is_unresolvable():
    played = [
        _match(home_team="X", away_team="Y", kickoff_utc="2026-01-01T00:00:00.000Z", home_score=0, away_score=0),
        # "Home FC" isn't in this match at all -- pts is None, must be skipped not counted.
        _match(home_team="A", away_team="B", kickoff_utc="2026-01-03T00:00:00.000Z", home_score=1, away_score=1),
    ]
    short_pts, short_count, long_pts, long_count = _split_rest_performance(played, "Home FC")
    assert (short_pts, short_count, long_pts, long_count) == (0, 0, 0, 0)


# --- compute_experience_h2h -------------------------------------------------


def test_experience_h2h_aligned_when_own_more_experienced_and_leads_h2h():
    exp = _all_none(ExperienceComparison, more_experienced="own")
    h2h = HeadToHeadSummary(home_wins=3, away_wins=1, draws=0)
    note = compute_experience_h2h(exp, h2h, own_is_home=True)
    assert note.h2h_leader == "own"
    assert note.aligned is True


def test_experience_h2h_not_aligned_when_experience_and_h2h_disagree():
    exp = _all_none(ExperienceComparison, more_experienced="own")
    h2h = HeadToHeadSummary(home_wins=1, away_wins=3, draws=0)
    note = compute_experience_h2h(exp, h2h, own_is_home=True)
    assert note.h2h_leader == "opponent"
    assert note.aligned is False


def test_experience_h2h_aligned_is_none_when_experience_is_even():
    # A real note is still returned (h2h_leader is always computed when
    # h2h data exists) -- only `aligned` is unknowable when either side
    # of the comparison is "even".
    exp = _all_none(ExperienceComparison, more_experienced="even")
    h2h = HeadToHeadSummary(home_wins=3, away_wins=1, draws=0)
    note = compute_experience_h2h(exp, h2h, own_is_home=True)
    assert note.h2h_leader == "own"
    assert note.aligned is None


def test_experience_h2h_none_without_h2h_data():
    exp = _all_none(ExperienceComparison, more_experienced="own")
    assert compute_experience_h2h(exp, None, own_is_home=True) is None


def test_experience_h2h_none_without_own_is_home():
    exp = _all_none(ExperienceComparison, more_experienced="own")
    h2h = HeadToHeadSummary(home_wins=3, away_wins=1, draws=0)
    assert compute_experience_h2h(exp, h2h, own_is_home=None) is None


def test_experience_h2h_leader_even_on_tied_record():
    exp = _all_none(ExperienceComparison, more_experienced="own")
    h2h = HeadToHeadSummary(home_wins=2, away_wins=2, draws=1)
    note = compute_experience_h2h(exp, h2h, own_is_home=True)
    assert note.h2h_leader == "even"
    assert note.aligned is None


# --- compute_fatigue_flag ---------------------------------------------------


def test_fatigue_flag_requires_multi_competition_and_short_gap():
    flag = compute_fatigue_flag(["Premier League", "FA Cup"], [3, 4, 3])
    assert flag.multi_competition is True
    assert flag.flagged is True


def test_fatigue_flag_not_flagged_with_single_competition():
    flag = compute_fatigue_flag(["Premier League"], [3, 4, 3])
    assert flag.multi_competition is False
    assert flag.flagged is False


def test_fatigue_flag_not_flagged_with_long_gaps():
    flag = compute_fatigue_flag(["Premier League", "FA Cup"], [7, 8, 9])
    assert flag.flagged is False


def test_fatigue_flag_none_without_gaps():
    assert compute_fatigue_flag(["Premier League"], []) is None


# --- compute_home_advantage --------------------------------------------------


def test_home_advantage_strong():
    form = _all_none(FormSummary, home_win_rate_pct=70.0, away_win_rate_pct=30.0)
    assert compute_home_advantage(form).strength == "strong"


def test_home_advantage_slight():
    form = _all_none(FormSummary, home_win_rate_pct=55.0, away_win_rate_pct=45.0)
    assert compute_home_advantage(form).strength == "slight"


def test_home_advantage_negligible():
    form = _all_none(FormSummary, home_win_rate_pct=50.0, away_win_rate_pct=48.0)
    assert compute_home_advantage(form).strength == "negligible"


def test_home_advantage_reverse():
    form = _all_none(FormSummary, home_win_rate_pct=30.0, away_win_rate_pct=50.0)
    assert compute_home_advantage(form).strength == "reverse"


def test_home_advantage_none_without_rates():
    assert compute_home_advantage(None) is None
    assert compute_home_advantage(_all_none(FormSummary, home_win_rate_pct=None, away_win_rate_pct=50.0)) is None


def test_home_advantage_label_withheld_when_either_sample_under_floor():
    # Confirmed live (Germany): "strong" was computed off home n=1 (a
    # single 100% win rate). Sample sizes ride along so a consumer can
    # see why the categorical label is absent.
    form = _all_none(
        FormSummary, home_win_rate_pct=100.0, away_win_rate_pct=30.0,
        home_win_rate_sample_size=1, away_win_rate_sample_size=10,
    )
    info = compute_home_advantage(form)
    assert info.strength is None
    assert info.gap_pct == 70.0  # rates/gap still reported
    assert info.home_sample_size == 1
    assert info.away_sample_size == 10


def test_home_advantage_label_kept_when_both_samples_meet_floor():
    form = _all_none(
        FormSummary, home_win_rate_pct=70.0, away_win_rate_pct=30.0,
        home_win_rate_sample_size=5, away_win_rate_sample_size=5,
    )
    info = compute_home_advantage(form)
    assert info.strength == "strong"
    assert info.home_sample_size == 5


def test_home_advantage_floor_not_applied_when_sample_sizes_are_none():
    # No form at all for a side's rates -> sample is None, floor is
    # skipped (the rates themselves would already have been None).
    form = _all_none(FormSummary, home_win_rate_pct=70.0, away_win_rate_pct=30.0)
    assert compute_home_advantage(form).strength == "strong"


# --- compute_streak_stability -----------------------------------------------


def test_streak_stability_stable_win_streak_with_low_rotation():
    streak = _all_none(StreakInfo, result="W", count=3)
    rotation = _all_none(RotationInfo, changed_players=1)
    info = compute_streak_stability(streak, rotation)
    assert info.stable is True


def test_streak_stability_none_rotation_data_gives_unknown_stability():
    streak = _all_none(StreakInfo, result="W", count=3)
    info = compute_streak_stability(streak, None)
    assert info.stable is None


def test_streak_stability_short_win_streak_is_unknown():
    # count < 2 -- the streak.result == "W" and streak.count >= 2 branch
    # isn't taken, so it falls to the elif (still "W", stable=None).
    streak = _all_none(StreakInfo, result="W", count=1)
    info = compute_streak_stability(streak, None)
    assert info.stable is None


def test_streak_stability_losing_streak_is_not_stable():
    streak = _all_none(StreakInfo, result="L", count=3)
    info = compute_streak_stability(streak, None)
    assert info.stable is False


def test_streak_stability_none_without_streak():
    assert compute_streak_stability(None, None) is None


# --- compute_losing_streak_context ------------------------------------------


def test_losing_streak_context_potential_turnaround():
    streak = _all_none(StreakInfo, result="L", count=3)
    xg = _all_none(SeasonXGEstimate, actual_goals_for=2, xg_for=4.5)
    info = compute_losing_streak_context(streak, xg)
    assert info.xg_delta == -2.5
    assert info.potential_turnaround is True


def test_losing_streak_context_no_turnaround_when_close_to_xg():
    streak = _all_none(StreakInfo, result="L", count=3)
    xg = _all_none(SeasonXGEstimate, actual_goals_for=4, xg_for=4.5)
    info = compute_losing_streak_context(streak, xg)
    assert info.potential_turnaround is False


def test_losing_streak_context_sentinel_when_not_a_losing_streak():
    streak = _all_none(StreakInfo, result="W", count=3)
    info = compute_losing_streak_context(streak, None)
    assert info is not None
    assert info.streak_count == 0
    assert info.xg_delta is None
    assert info.potential_turnaround is None


def test_losing_streak_context_sentinel_when_streak_too_short():
    streak = _all_none(StreakInfo, result="L", count=1)
    info = compute_losing_streak_context(streak, None)
    assert info is not None
    assert info.streak_count == 0
    assert info.potential_turnaround is None


def test_losing_streak_context_none_only_when_no_streak_data_at_all():
    assert compute_losing_streak_context(None, None) is None


# --- compute_card_risks ------------------------------------------------------


def test_card_risks_flags_accumulation_and_dismissal():
    accumulator = _all_none(SquadMember, name="Yellow Magnet", season_stats=_all_none(SeasonPlayerStats, yellow_cards=5, red_cards=0))
    dismissed = _all_none(SquadMember, name="Sent Off", season_stats=_all_none(SeasonPlayerStats, yellow_cards=1, red_cards=1))
    clean = _all_none(SquadMember, name="Clean Sheet Cal", season_stats=_all_none(SeasonPlayerStats, yellow_cards=1, red_cards=0))
    no_stats = _all_none(SquadMember, name="No Data Nate", season_stats=None)
    risks = compute_card_risks([accumulator, dismissed, clean, no_stats])
    names = {r.name for r in risks}
    assert names == {"Yellow Magnet", "Sent Off"}


def test_card_risks_none_without_squad():
    assert compute_card_risks(None) is None


def test_card_risks_empty_list_when_squad_present_but_nobody_flagged():
    clean = _all_none(SquadMember, name="Clean", season_stats=_all_none(SeasonPlayerStats, yellow_cards=1, red_cards=0))
    assert compute_card_risks([clean]) == []


# --- compute_duel_vulnerabilities / compute_fullback_exposure ---------------


def test_duel_vulnerabilities_only_flags_defenders_below_50pct():
    weak_def = _all_none(SquadMember, name="Weak DF", role="D", defensive_stats=_all_none(DefensiveStats, ground_duel_success_pct=40.0))
    strong_def = _all_none(SquadMember, name="Strong DF", role="D", defensive_stats=_all_none(DefensiveStats, ground_duel_success_pct=60.0))
    weak_mid = _all_none(SquadMember, name="Weak MF", role="M", defensive_stats=_all_none(DefensiveStats, ground_duel_success_pct=40.0))
    result = compute_duel_vulnerabilities([weak_def, strong_def, weak_mid])
    assert [v.name for v in result] == ["Weak DF"]


def test_duel_vulnerabilities_none_without_squad():
    assert compute_duel_vulnerabilities(None) is None


def test_fullback_exposure_needs_at_least_two_defenders_with_stats():
    one_def = _all_none(SquadMember, name="Solo DF", role="D", defensive_stats=_all_none(DefensiveStats, chances_created=3, ground_duel_success_pct=40.0))
    assert compute_fullback_exposure([one_def]) is None


def test_fullback_exposure_none_without_squad():
    assert compute_fullback_exposure(None) is None


def test_fullback_exposure_flags_above_median_chances_and_below_55pct_duels():
    exposed = _all_none(SquadMember, name="Exposed FB", role="D", defensive_stats=_all_none(DefensiveStats, chances_created=8, ground_duel_success_pct=45.0))
    baseline = _all_none(SquadMember, name="Baseline DF", role="D", defensive_stats=_all_none(DefensiveStats, chances_created=2, ground_duel_success_pct=60.0))
    result = compute_fullback_exposure([exposed, baseline])
    assert [e.name for e in result] == ["Exposed FB"]


def _usage(wide=0, central=0):
    from football.types import PlayerUsagePattern

    return _all_none(PlayerUsagePattern, wide_back_starts=wide, central_back_starts=central)


def test_fullback_exposure_leaves_out_a_centre_back_who_mostly_starts_centrally():
    # Confirmed live: Harry Maguire (a centre-back) appeared in the
    # "fullback" list. Same stats for both; only where they line up differs.
    stats = _all_none(DefensiveStats, chances_created=8, ground_duel_success_pct=45.0)
    centre_back = _all_none(SquadMember, name="Centre Back", role="D", defensive_stats=stats, recent_usage=_usage(wide=0, central=6))
    full_back = _all_none(SquadMember, name="Full Back", role="D", defensive_stats=stats, recent_usage=_usage(wide=5, central=1))
    baseline_a = _all_none(SquadMember, name="Base A", role="D", defensive_stats=_all_none(DefensiveStats, chances_created=1, ground_duel_success_pct=60.0))
    baseline_b = _all_none(SquadMember, name="Base B", role="D", defensive_stats=_all_none(DefensiveStats, chances_created=2, ground_duel_success_pct=60.0))
    result = compute_fullback_exposure([centre_back, full_back, baseline_a, baseline_b])
    assert [e.name for e in result] == ["Full Back"]


def test_fullback_exposure_keeps_a_defender_with_no_lineup_history():
    stats = _all_none(DefensiveStats, chances_created=8, ground_duel_success_pct=45.0)
    unknown = _all_none(SquadMember, name="No History", role="D", defensive_stats=stats, recent_usage=None)
    baseline = _all_none(SquadMember, name="Base", role="D", defensive_stats=_all_none(DefensiveStats, chances_created=1, ground_duel_success_pct=60.0))
    assert [e.name for e in compute_fullback_exposure([unknown, baseline])] == ["No History"]


# --- compute_referee_card_risk_note -----------------------------------------


def test_referee_card_risk_note_elevated_when_high_yellow_rate():
    home_risk = compute_card_risks(
        [_all_none(SquadMember, name="Risky", season_stats=_all_none(SeasonPlayerStats, yellow_cards=5, red_cards=0))]
    )
    stats = _all_none(RefereeStats, yellow_cards_per_game="3.2")
    note = compute_referee_card_risk_note("Strict Ref", stats, home_risk, None)
    assert note.elevated_card_referee is True
    assert len(note.flagged_players) == 1


def test_referee_card_risk_note_none_without_flagged_players():
    # Empty flagged list is a real "checked, nobody at risk" result now --
    # the note still returns so the field is present whenever a referee
    # and stats exist; only a missing referee/stats stays None.
    stats = _all_none(RefereeStats, yellow_cards_per_game="3.2")
    note = compute_referee_card_risk_note("Ref", stats, [], [])
    assert note is not None
    assert note.flagged_players == []
    assert note.elevated_card_referee is True


def test_referee_card_risk_note_none_without_referee():
    assert compute_referee_card_risk_note(None, _all_none(RefereeStats, yellow_cards_per_game="3.2"), [], []) is None


# --- aerial_win_pct / compute_set_piece_threat_flag / compute_direct_play_exposure_flag --


def test_aerial_win_pct_computes_share():
    aerial = _all_none(SeasonAerialEstimate, aerial_duels_won_for=30, aerial_duels_won_against=20)
    assert aerial_win_pct(aerial) == 60.0


def test_set_piece_threat_flag_none_without_corners():
    assert compute_set_piece_threat_flag(None, None) is None


def test_aerial_win_pct_none_without_data():
    assert aerial_win_pct(None) is None


def test_set_piece_threat_flag_elevated():
    corners = _all_none(SeasonCornersEstimate, corners_for=30, sample_size=5)
    aerial = _all_none(SeasonAerialEstimate, aerial_duels_won_for=10, aerial_duels_won_against=30)
    flag = compute_set_piece_threat_flag(corners, aerial)
    assert flag.corners_per_game == 6.0
    assert flag.elevated is True


def test_direct_play_exposure_flag_elevated():
    passing = _all_none(SeasonPassingStyleEstimate, long_ball_share_pct=20.0)
    aerial = _all_none(SeasonAerialEstimate, aerial_duels_won_for=10, aerial_duels_won_against=30)
    flag = compute_direct_play_exposure_flag(passing, aerial)
    assert flag.elevated is True


def test_direct_play_exposure_flag_none_without_long_ball_data():
    assert compute_direct_play_exposure_flag(_all_none(SeasonPassingStyleEstimate, long_ball_share_pct=None), None) is None


# --- _median -----------------------------------------------------------------


def test_median_odd_length():
    assert _median([1.0, 3.0, 2.0]) == 2.0


def test_median_even_length():
    assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5


# --- _simulated_points / _simulate_new_position / compute_standings_impact --


def test_simulated_points_replaces_own_and_opponent_rows_only():
    row = StandingsTableRow(team_name="Own", position=5, points=20)
    assert _simulated_points(row, own_current_position=5, opponent_current_position=8, new_own_points=23, new_opponent_points=15) == 23
    other_row = StandingsTableRow(team_name="Other", position=1, points=50)
    assert _simulated_points(other_row, own_current_position=5, opponent_current_position=8, new_own_points=23, new_opponent_points=15) == 50


def test_simulate_new_position_reranks_by_points():
    table = [
        StandingsTableRow(team_name="A", position=1, points=30),
        StandingsTableRow(team_name="Own", position=2, points=25),
        StandingsTableRow(team_name="C", position=3, points=20),
    ]
    # Own wins big (25 -> 33), should move to 1st
    new_pos = _simulate_new_position(table, own_current_position=2, opponent_current_position=3, new_own_points=33, new_opponent_points=20)
    assert new_pos == 1


def test_simulate_new_position_none_without_table():
    assert _simulate_new_position(None, 1, 2, 10, 10) is None


def test_standings_impact_covers_win_draw_loss_scenarios():
    table = [
        StandingsTableRow(team_name="Own", position=2, points=25),
        StandingsTableRow(team_name="Opp", position=3, points=24),
    ]
    impact = compute_standings_impact(_standing(position=2, points=25), _standing(position=3, points=24), table)
    outcomes = {s.outcome: s.new_points for s in impact.scenarios}
    assert outcomes == {"win": 28, "draw": 26, "loss": 25}


def test_standings_impact_none_without_data():
    assert compute_standings_impact(None, _standing(), []) is None


# --- is_recent_appointment ---------------------------------------------------


def test_is_recent_appointment_true_for_recent_date():
    from datetime import UTC, datetime, timedelta

    recent = (datetime.now(tz=UTC) - timedelta(days=10)).isoformat()
    assert is_recent_appointment(recent) is True


def test_is_recent_appointment_false_for_old_date():
    from datetime import UTC, datetime, timedelta

    old = (datetime.now(tz=UTC) - timedelta(days=400)).isoformat()
    assert is_recent_appointment(old) is False


def test_is_recent_appointment_none_without_date():
    assert is_recent_appointment(None) is None


# --- _compute_rest_comparison / _compute_experience_comparison --------------


def test_rest_comparison_own_more_rested():
    comp = _compute_rest_comparison(5, 2)
    assert comp.more_rested == "own"


def test_rest_comparison_opponent_more_rested():
    comp = _compute_rest_comparison(2, 5)
    assert comp.more_rested == "opponent"


def test_rest_comparison_even():
    comp = _compute_rest_comparison(3, 3)
    assert comp.more_rested == "even"


def test_rest_comparison_none_when_both_missing():
    assert _compute_rest_comparison(None, None) is None


def test_rest_comparison_unknown_when_one_side_missing():
    comp = _compute_rest_comparison(5, None)
    assert comp.more_rested is None
    assert comp.own_rest_days == 5


def test_experience_comparison_own_more_experienced():
    comp = _compute_experience_comparison(30.0, 24.0)
    assert comp.more_experienced == "own"


def test_experience_comparison_even_within_1_5_years():
    comp = _compute_experience_comparison(26.0, 25.0)
    assert comp.more_experienced == "even"


def test_experience_comparison_opponent_more_experienced():
    comp = _compute_experience_comparison(23.0, 29.0)
    assert comp.more_experienced == "opponent"


def test_experience_comparison_none_when_both_missing():
    assert _compute_experience_comparison(None, None) is None


# --- compute_opponent_rank_record --------------------------------------------


def test_opponent_rank_record_counts_only_wins_against_currently_higher_ranked():
    table = [
        StandingsTableRow(team_name="Rival FC", position=2, points=50),
        StandingsTableRow(team_name="Weaker FC", position=15, points=10),
    ]
    results = [
        _form_result(opponent="Rival FC", competition="Premier League", result="W"),
        _form_result(opponent="Weaker FC", competition="Premier League", result="W"),
        _form_result(opponent="Rival FC", competition="FA Cup", result="L"),  # wrong competition, excluded
    ]
    record = compute_opponent_rank_record(results, "Premier League", table, own_position=8)
    # Only "Rival FC" (position 2 < own 8) counts; Weaker FC (15) doesn't.
    assert record.sample_size == 1
    assert record.wins == 1


def test_opponent_rank_record_none_without_standings_or_position():
    assert compute_opponent_rank_record([], "Premier League", None, own_position=5) is None
    assert compute_opponent_rank_record([], "Premier League", [], own_position=None) is None


def test_opponent_rank_record_counts_draws_and_losses():
    table = [StandingsTableRow(team_name="Rival FC", position=2, points=50)]
    results = [
        _form_result(opponent="Rival FC", competition="Premier League", result="D"),
        _form_result(opponent="Rival FC", competition="Premier League", result="L"),
    ]
    record = compute_opponent_rank_record(results, "Premier League", table, own_position=8)
    assert record.sample_size == 2
    assert record.draws == 1
    assert record.losses == 1


def test_opponent_rank_record_matches_stage_suffixed_competition_labels():
    # Sofascore tags recent results "UEFA Champions League, Knockout
    # stage" while the fixture competition is the plain base name --
    # strict == left this record empty (same bug fill_standings_form had).
    table = [StandingsTableRow(team_name="Rival FC", position=2, points=50)]
    results = [
        _form_result(opponent="Rival FC", competition="UEFA Champions League, Knockout stage", result="W"),
        _form_result(opponent="Rival FC", competition="UEFA Champions League", result="D"),
    ]
    record = compute_opponent_rank_record(results, "UEFA Champions League", table, own_position=8)
    assert record is not None
    assert record.sample_size == 2
    assert record.wins == 1
    assert record.draws == 1


# --- apply_usage_pattern / compute_squad_strength / compute_bench_info / compute_presence --


def test_apply_usage_pattern_attaches_matching_players_only():
    from football.types import PlayerUsagePattern

    matched = _all_none(SquadMember, name="Alex Isak", recent_usage=None)
    unmatched = _all_none(SquadMember, name="Someone Else", recent_usage=None)
    usage = _all_none(PlayerUsagePattern)
    result = apply_usage_pattern([matched, unmatched], {"alex isak": usage})
    by_name = {m.name: m for m in result}
    assert by_name["Alex Isak"].recent_usage is usage
    assert by_name["Someone Else"].recent_usage is None


def test_apply_usage_pattern_returns_squad_unchanged_without_usage_data():
    squad = [_all_none(SquadMember, name="X")]
    assert apply_usage_pattern(squad, {}) is squad
    assert apply_usage_pattern(None, {"x": object()}) is None


def test_squad_strength_sums_by_role_and_excludes_unavailable():
    fw = _all_none(SquadMember, name="Striker", role="F", market_value=50.0)
    df = _all_none(SquadMember, name="Defender", role="D", market_value=30.0)
    injured = _all_none(SquadMember, name="Injured Mid", role="M", market_value=20.0)
    strength = compute_squad_strength([fw, df, injured], injuries=[injured], suspended=None)
    assert strength.total_value == 100.0
    assert strength.attack_value == 50.0
    assert strength.defense_value == 30.0
    assert strength.available_value == 80.0  # excludes the injured player


def test_squad_strength_excludes_match_level_missing_player_not_in_injuries():
    from football.types import MissingPlayer

    fw = _all_none(SquadMember, name="Striker", role="F", market_value=50.0)
    benched = _all_none(SquadMember, name="Richarlison", role="F", market_value=24.0)
    missing = [MissingPlayer(name="Richarlison", description="coach_decision", expected_return=None)]
    strength = compute_squad_strength([fw, benched], injuries=None, suspended=None, missing_players=missing)
    assert strength.total_value == 74.0
    assert strength.available_value == 50.0


def test_squad_strength_none_without_squad():
    assert compute_squad_strength(None, None, None) is None


def test_bench_info_sums_market_values_by_name_match():
    from football.types import LineupPlayer

    squad = [_all_none(SquadMember, name="Sub One", market_value=10.0), _all_none(SquadMember, name="Starter One", market_value=40.0)]
    bench = [_all_none(LineupPlayer, name="Sub One")]
    lineup = [_all_none(LineupPlayer, name="Starter One")]
    info = compute_bench_info(bench, lineup, squad)
    assert info.bench_size == 1
    assert info.bench_total_market_value == 10.0
    assert info.starting_total_market_value == 40.0


def test_bench_info_none_without_bench_or_squad():
    assert compute_bench_info(None, None, [_all_none(SquadMember, name="X")]) is None
    assert compute_bench_info([_all_none(SquadMember, name="X")], None, None) is None


def test_presence_marks_injured_and_suspended_as_absent():
    from football.types import LineupPlayer

    injured = _all_none(SquadMember, name="Hurt Player", injury="Hamstring")
    suspended_player = _all_none(SquadMember, name="Banned Player")
    available = _all_none(SquadMember, name="Fit Player")
    entries = compute_presence(
        squad=[injured, suspended_player, available],
        lineup=[_all_none(LineupPlayer, name="Fit Player")],
        bench=None,
        injuries=[injured],
        suspended=["Banned Player"],
    )
    by_name = {e.name: e for e in entries}
    assert by_name["Hurt Player"].status == "A"
    assert by_name["Hurt Player"].reason == "Hamstring"
    assert by_name["Banned Player"].status == "A"
    assert by_name["Banned Player"].reason == "Suspended"
    assert by_name["Fit Player"].status == "P"
    assert by_name["Fit Player"].starting is True


def test_presence_none_without_squad():
    assert compute_presence(None, None, None, None, None) is None


def test_presence_recognizes_a_real_starter_even_when_the_lineup_spells_the_name_differently():
    # Confirmed live: match.home_lineup listed "Youri Tielemans" (from one
    # source) while merged_profile.squad had him as "Tielemans" (from a
    # different source, after a mid-pipeline fallback) -- exact-match-only
    # `starting` detection missed this, made mark_projected_starters think
    # no real lineup existed, and it derived its own competing, different
    # 11 (picking someone else instead) that then sat alongside the real
    # lineup showing Tielemans in it.
    from football.types import LineupPlayer

    tielemans = _all_none(SquadMember, name="Tielemans")
    other = _all_none(SquadMember, name="Other Player")
    entries = compute_presence(
        squad=[tielemans, other],
        lineup=[_all_none(LineupPlayer, name="Youri Tielemans")],
        bench=[_all_none(LineupPlayer, name="Some Sub")],
        injuries=None,
        suspended=None,
    )
    by_name = {e.name: e for e in entries}
    assert by_name["Tielemans"].starting is True
    assert by_name["Other Player"].starting is False


def test_presence_on_bench_also_uses_the_containment_fallback():
    from football.types import LineupPlayer

    squad_member = _all_none(SquadMember, name="Tielemans")
    entries = compute_presence(
        squad=[squad_member], lineup=[], bench=[_all_none(LineupPlayer, name="Youri Tielemans")], injuries=None, suspended=None,
    )
    assert entries[0].on_bench is True


def test_presence_marks_missing_players_absent_even_without_injury():
    """Regression: confirmed live -- Richarlison was ruled out for
    "coach_decision" (in match.away_missing_players), not an injury, so
    he wasn't in teamProfile.injuries and previously showed status "P"
    despite being explicitly listed as unavailable."""
    from football.types import LineupPlayer, MissingPlayer

    benched_by_coach = _all_none(SquadMember, name="Rested Player")
    available = _all_none(SquadMember, name="Fit Player")
    entries = compute_presence(
        squad=[benched_by_coach, available],
        lineup=[_all_none(LineupPlayer, name="Fit Player")],
        bench=None,
        injuries=None,
        suspended=None,
        missing_players=[MissingPlayer(name="Rested Player", description="coach_decision", expected_return=None)],
    )
    by_name = {e.name: e for e in entries}
    assert by_name["Rested Player"].status == "A"
    assert by_name["Rested Player"].reason == "Coach decision (not injured)"
    assert by_name["Fit Player"].status == "P"


def test_presence_appends_non_squad_missing_players_as_absent():
    """Regression: confirmed live (Germany) -- de Jong/Wieffer/Simons/
    Goretzka/Stiller appeared in match.*_missing_players but never in the
    squad list, so availability undercounted five absences to zero."""
    from football.types import MissingPlayer

    fit = _all_none(SquadMember, name="Fit Player")
    entries = compute_presence(
        squad=[fit],
        lineup=None,
        bench=None,
        injuries=None,
        suspended=None,
        missing_players=[MissingPlayer(name="De Jong", description="Knee Injury", expected_return=None)],
    )
    by_name = {e.name: e for e in entries}
    assert by_name["De Jong"].status == "A"
    assert by_name["De Jong"].starting is False
    assert by_name["Fit Player"].status == "P"


def test_xg_estimate_from_form_builds_from_deduped_rows_with_source_form():
    """Regression: confirmed live -- Germany's fotmob xg sample was empty
    (n=0) while its form had five usable xG rows; away_xg_estimate went
    null while the home side had n=6."""
    from football.insights import xg_estimate_from_form

    form = _all_none(
        FormSummary,
        last10_overall=[
            _form_result(date="2026-01-01", scoreline="2-1", venue="home", xg_for=1.5, xg_against=0.8),
            _form_result(date="2026-01-08", scoreline="1-2", venue="away", xg_for=1.0, xg_against=1.4),
        ],
        last20_overall=[
            # last10 is a prefix of last20 -- same rows must not double-count
            _form_result(date="2026-01-01", scoreline="2-1", venue="home", xg_for=1.5, xg_against=0.8),
            _form_result(date="2026-01-08", scoreline="1-2", venue="away", xg_for=1.0, xg_against=1.4),
            _form_result(date="2025-12-01", scoreline="0-0", venue="home", xg_for=2.0, xg_against=0.5),
        ],
    )
    est = xg_estimate_from_form(form)
    assert est is not None
    assert est.source == "form"
    assert est.sample_size == 3
    assert est.xg_for == 4.5
    assert est.xg_against == 2.7
    # goals parsed off scoreline, away venue swapped to the team's frame
    assert est.actual_goals_for == 4  # 2 + 2 + 0
    assert est.actual_goals_against == 2  # 1 + 1 + 0


def test_xg_estimate_from_form_none_without_xg_annotated_rows():
    from football.insights import xg_estimate_from_form

    assert xg_estimate_from_form(None) is None
    form = _all_none(FormSummary, last10_overall=[_form_result()], last20_overall=[])
    assert xg_estimate_from_form(form) is None


def test_card_discipline_from_venue_split_sample_weighted_average():
    """Regression: confirmed live -- card_discipline was null on both
    sides (national team: no season stats + standing) while
    card_discipline_venue_split was populated."""
    from football.insights import card_discipline_from_venue_split
    from football.types import CardDisciplineVenueSplit

    split = CardDisciplineVenueSplit(
        at_home_sample_size=5, at_home_yellow_per_game=2.0, at_home_red_per_game=0.1,
        away_sample_size=15, away_yellow_per_game=3.0, away_red_per_game=0.3,
        source="fotmob",
    )
    info = card_discipline_from_venue_split(split)
    # weighted: (2*5 + 3*15)/20 = 2.75, (0.1*5 + 0.3*15)/20 = 0.25
    assert info.yellow_per_game == 2.75
    assert info.red_per_game == 0.25
    assert info.elevated_risk is True  # yellow > 2.5 OR red > 0.2


def test_card_discipline_from_venue_split_none_without_sample():
    from football.insights import card_discipline_from_venue_split
    from football.types import CardDisciplineVenueSplit

    assert card_discipline_from_venue_split(None) is None
    empty = CardDisciplineVenueSplit(
        at_home_sample_size=0, at_home_yellow_per_game=None, at_home_red_per_game=None,
        away_sample_size=0, away_yellow_per_game=None, away_red_per_game=None,
        source="fotmob",
    )
    assert card_discipline_from_venue_split(empty) is None


def test_card_discipline_from_venue_split_not_elevated_when_under_thresholds():
    from football.insights import card_discipline_from_venue_split
    from football.types import CardDisciplineVenueSplit

    split = CardDisciplineVenueSplit(
        at_home_sample_size=10, at_home_yellow_per_game=2.0, at_home_red_per_game=0.1,
        away_sample_size=10, away_yellow_per_game=2.0, away_red_per_game=0.1,
        source="fotmob",
    )
    info = card_discipline_from_venue_split(split)
    assert info.yellow_per_game == 2.0
    assert info.red_per_game == 0.1
    assert info.elevated_risk is False


# --- season-stats accumulator family (compute_season_match_stats_estimate's
# --- extracted helpers -- this was the complexity-140 function refactored
# --- this session; previously verified only by a one-off scratchpad
# --- characterization script, not a formal regression test) ---------------


def _stat(name, home, away):
    from football.types import MatchStatItem

    return MatchStatItem(name=name, home=home, away=away)


def test_accumulate_xg_adds_goals_and_xg_for_home_side():
    from football.insights import _accumulate_xg, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    stats = [_stat("Expected goals (xG)", "1.85", "0.92")]
    m = _match(home_score=2, away_score=1)
    _accumulate_xg(acc, stats, m, home=True)
    assert acc.xg_for == 1.85
    assert acc.xg_against == 0.92
    assert acc.goals_for == 2
    assert acc.goals_against == 1
    assert acc.xg_sample_size == 1


def test_accumulate_xg_uses_away_perspective_when_not_home():
    from football.insights import _accumulate_xg, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    stats = [_stat("Expected goals (xG)", "1.85", "0.92")]
    m = _match(home_score=2, away_score=1)
    _accumulate_xg(acc, stats, m, home=False)
    assert acc.xg_for == 0.92
    assert acc.goals_for == 1


def test_accumulate_xg_no_op_when_stat_missing():
    from football.insights import _accumulate_xg, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    _accumulate_xg(acc, [], _match(home_score=1, away_score=0), home=True)
    assert acc.xg_sample_size == 0


def test_accumulate_shots_and_keeper():
    from football.insights import _accumulate_shots_and_keeper, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    stats = [_stat("Total shots", "12", "8"), _stat("Shots on target", "5", "3"), _stat("Keeper saves", "2", "1")]
    m = _match(home_score=1, away_score=0)
    _accumulate_shots_and_keeper(acc, stats, m, home=True)
    assert (acc.shots_for, acc.shots_against) == (12, 8)
    assert (acc.sot_for, acc.sot_against) == (5, 3)
    assert acc.saves_for == 2
    assert acc.shots_on_target_faced == 3  # opponent's shots on target
    assert acc.keeper_goals_conceded == 0  # away_score when home
    assert acc.keeper_sample_size == 1


def test_accumulate_shots_skips_keeper_stat_when_absent():
    from football.insights import _accumulate_shots_and_keeper, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    stats = [_stat("Total shots", "12", "8"), _stat("Shots on target", "5", "3")]
    _accumulate_shots_and_keeper(acc, stats, _match(home_score=1, away_score=0), home=True)
    assert acc.shots_sample_size == 1
    assert acc.keeper_sample_size == 0


def test_accumulate_shots_and_keeper_no_op_when_shots_stat_missing():
    from football.insights import _accumulate_shots_and_keeper, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    _accumulate_shots_and_keeper(acc, [], _match(home_score=1, away_score=0), home=True)
    assert acc.shots_sample_size == 0


def test_accumulate_cards_splits_by_venue():
    from football.insights import _accumulate_cards, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    stats = [_stat("Yellow cards", "3", "1"), _stat("Red cards", "1", "0")]
    _accumulate_cards(acc, stats, home=True)
    assert (acc.at_home_yellow, acc.at_home_red, acc.at_home_sample_size) == (3, 1, 1)
    _accumulate_cards(acc, stats, home=False)
    assert (acc.away_yellow, acc.away_red, acc.away_sample_size) == (1, 0, 1)


def test_accumulate_cards_defaults_red_to_zero_without_stat():
    from football.insights import _accumulate_cards, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    _accumulate_cards(acc, [_stat("Yellow cards", "2", "1")], home=True)
    assert acc.at_home_red == 0


def test_accumulate_cards_no_op_when_yellow_stat_missing():
    from football.insights import _accumulate_cards, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    _accumulate_cards(acc, [], home=True)
    assert acc.at_home_sample_size == 0


def test_accumulate_aerial_parses_leading_int_from_percentage_strings():
    from football.insights import _accumulate_aerial, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    # Fotmob's aerial duel stat is a "won/total" style string -- parse_leading_int reads the leading number.
    _accumulate_aerial(acc, [_stat("Aerial duels won", "14", "9")], home=True)
    assert (acc.aerial_for, acc.aerial_against, acc.aerial_sample_size) == (14, 9, 1)


def test_accumulate_aerial_no_op_when_stat_missing():
    from football.insights import _accumulate_aerial, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    _accumulate_aerial(acc, [], home=True)
    assert acc.aerial_sample_size == 0


def test_accumulate_big_chances():
    from football.insights import _accumulate_big_chances, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    stats = [_stat("Big chances", "3", "2"), _stat("Big chances missed", "1", "1")]
    _accumulate_big_chances(acc, stats, home=True)
    assert (acc.chances_created_for, acc.chances_created_against) == (3, 2)
    assert (acc.chances_missed_for, acc.chances_missed_against) == (1, 1)


def test_accumulate_big_chances_no_op_when_either_stat_missing():
    from football.insights import _accumulate_big_chances, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    _accumulate_big_chances(acc, [_stat("Big chances", "3", "2")], home=True)
    assert acc.big_chances_sample_size == 0


def test_accumulate_passing_skips_the_empty_placeholder_passes_row():
    from football.insights import _accumulate_passing, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    stats = [
        _stat("Passes", "", ""),  # placeholder row -- must be skipped
        _stat("Passes", "450", "380"),  # real total
        _stat("Accurate passes", "410", "340"),
        _stat("Accurate long balls", "30", "25"),
    ]
    _accumulate_passing(acc, stats, home=True)
    assert acc.total_passes_for == 450
    assert acc.accurate_passes_for == 410
    assert acc.accurate_long_balls_for == 30
    assert acc.passing_sample_size == 1


def test_accumulate_passing_no_op_when_any_stat_missing():
    from football.insights import _accumulate_passing, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    _accumulate_passing(acc, [_stat("Passes", "450", "380")], home=True)
    assert acc.passing_sample_size == 0


# --- compute_season_match_stats_estimate (async) ------------------------------------------


def test_compute_season_match_stats_estimate_empty_without_finished_matches():
    from football.insights import compute_season_match_stats_estimate

    unplayed = _match(home_team="Home FC", away_team="X", status="notstarted", kickoff_utc="2026-02-01T00:00:00.000Z")
    result = asyncio.run(compute_season_match_stats_estimate("Home FC", [unplayed]))
    assert result.xg is None
    assert result.shots is None
    assert result.aerial is None


def test_compute_season_match_stats_estimate_aggregates_across_matches(monkeypatch):
    import football.sites.fotmob as fotmob_module

    finished = _match(home_team="Home FC", away_team="X", status="finished", kickoff_utc="2026-01-01T00:00:00.000Z", home_score=2, away_score=1)
    details = _all_none(
        MatchDetails, source="fotmob", source_url="https://x", home_team="Home FC", away_team="X",
        match_stats=[
            _stat("Expected goals (xG)", "1.8", "0.9"), _stat("Total shots", "12", "8"), _stat("Shots on target", "5", "3"),
            _stat("Yellow cards", "2", "1"), _stat("Aerial duels won", "14", "9"),
            _stat("Big chances", "3", "2"), _stat("Big chances missed", "1", "1"),
            _stat("Fouls committed", "10", "12"),
        ],
    )

    async def fake_details(_match_info):
        return details

    monkeypatch.setattr(fotmob_module, "get_fotmob_match_details", fake_details)

    from football.insights import compute_season_match_stats_estimate

    result = asyncio.run(compute_season_match_stats_estimate("Home FC", [finished]))
    assert result.xg.xg_for == 1.8
    assert result.shots.shots_for == 12
    assert result.aerial.aerial_duels_won_for == 14
    assert result.big_chances.big_chances_created_for == 3
    assert result.card_split.at_home_sample_size == 1


def test_compute_season_match_stats_estimate_skips_unresolvable_team():
    from football.insights import compute_season_match_stats_estimate

    finished = _match(home_team="X", away_team="Y", status="finished", kickoff_utc="2026-01-01T00:00:00.000Z")
    result = asyncio.run(compute_season_match_stats_estimate("Home FC", [finished]))
    assert result.xg is None


def test_compute_season_match_stats_estimate_tolerates_one_match_fetch_failure(monkeypatch):
    import football.sites.fotmob as fotmob_module

    finished = _match(home_team="Home FC", away_team="X", status="finished", kickoff_utc="2026-01-01T00:00:00.000Z")

    async def failing_details(_match_info):
        raise RuntimeError("blocked")

    monkeypatch.setattr(fotmob_module, "get_fotmob_match_details", failing_details)

    from football.insights import compute_season_match_stats_estimate

    result = asyncio.run(compute_season_match_stats_estimate("Home FC", [finished]))
    assert result.xg is None


# --- compute_possession_matchup (async) ---------------------------------------------------


def test_compute_possession_matchup_empty_without_finished_matches():
    from football.insights import compute_possession_matchup

    unplayed = _match(home_team="Home FC", away_team="X", status="notstarted", kickoff_utc="2026-02-01T00:00:00.000Z")
    result = asyncio.run(compute_possession_matchup("Home FC", [unplayed]))
    assert result.possession is None
    assert result.corners is None
    assert result.defensive_errors is None


def test_compute_possession_matchup_aggregates_across_matches(monkeypatch):
    import football.sites.goal as goal_module

    high_poss_win = _match(home_team="Home FC", away_team="X", status="finished", kickoff_utc="2026-01-01T00:00:00.000Z", home_score=2, away_score=1)
    low_poss_draw = _match(home_team="Home FC", away_team="Y", status="finished", kickoff_utc="2026-01-08T00:00:00.000Z", home_score=1, away_score=1)

    high_poss_details = _all_none(
        MatchDetails, source="goal", source_url="https://x", home_team="Home FC", away_team="X",
        match_stats=[_stat("Ball Possession", "40", "60"), _stat("Corner total", "6", "3"), _stat("Defensive error", "1", "0")],
    )
    low_poss_details = _all_none(
        MatchDetails, source="goal", source_url="https://x", home_team="Home FC", away_team="Y",
        match_stats=[_stat("Ball Possession", "55", "45"), _stat("Corner total", "4", "5"), _stat("Defensive error", "0", "1")],
    )

    async def fake_details(match_info, _client):
        return high_poss_details if match_info is high_poss_win else low_poss_details

    monkeypatch.setattr(goal_module, "get_goal_match_details", fake_details)

    from football.insights import compute_possession_matchup

    result = asyncio.run(compute_possession_matchup("Home FC", [high_poss_win, low_poss_draw]))
    # Opponent had 60% possession in the first match (>=55 -- "high" bucket, a win = 3pts),
    # and 45% in the second (<55 -- "other" bucket, a draw = 1pt).
    assert result.possession.high_opponent_possession_sample_size == 1
    assert result.possession.high_opponent_possession_ppg == 3.0
    assert result.possession.other_sample_size == 1
    assert result.possession.other_ppg == 1.0
    assert result.corners.corners_for == 10
    assert result.defensive_errors.defensive_errors_for == 1


def test_compute_possession_matchup_skips_unresolvable_team():
    from football.insights import compute_possession_matchup

    finished = _match(home_team="X", away_team="Y", status="finished", kickoff_utc="2026-01-01T00:00:00.000Z")
    result = asyncio.run(compute_possession_matchup("Home FC", [finished]))
    assert result.possession is None


def test_compute_possession_matchup_tolerates_one_match_fetch_failure(monkeypatch):
    import football.sites.goal as goal_module

    finished = _match(home_team="Home FC", away_team="X", status="finished", kickoff_utc="2026-01-01T00:00:00.000Z")

    async def failing_details(_match_info, _client):
        raise RuntimeError("blocked")

    monkeypatch.setattr(goal_module, "get_goal_match_details", failing_details)

    from football.insights import compute_possession_matchup

    result = asyncio.run(compute_possession_matchup("Home FC", [finished]))
    assert result.possession is None


def test_accumulate_possession_stat_no_op_when_stat_missing():
    from football.insights import _accumulate_possession_stat, _PossessionAccumulator

    acc = _PossessionAccumulator()
    details = _all_none(MatchDetails, source="goal", source_url="https://x", home_team="Home FC", away_team="X", match_stats=[])
    _accumulate_possession_stat(acc, details, _match(home_score=1, away_score=0), home=True)
    assert acc.high_count == 0
    assert acc.other_count == 0


def test_accumulate_possession_stat_treats_unparseable_value_as_no_op():
    from football.insights import _accumulate_possession_stat, _PossessionAccumulator

    acc = _PossessionAccumulator()
    details = _all_none(
        MatchDetails, source="goal", source_url="https://x", home_team="Home FC", away_team="X",
        match_stats=[_stat("Ball Possession", "n/a", "n/a")],
    )
    _accumulate_possession_stat(acc, details, _match(home_score=1, away_score=0), home=True)
    assert acc.high_count == 0
    assert acc.other_count == 0


def test_accumulate_possession_stat_draw_scores_one_point():
    from football.insights import _accumulate_possession_stat, _PossessionAccumulator

    acc = _PossessionAccumulator()
    details = _all_none(
        MatchDetails, source="goal", source_url="https://x", home_team="Home FC", away_team="X",
        match_stats=[_stat("Ball Possession", "40", "60")],
    )
    _accumulate_possession_stat(acc, details, _match(home_score=1, away_score=1), home=True)
    assert acc.high_pts == 1
    assert acc.high_count == 1


def test_accumulate_possession_stat_loss_scores_zero_points():
    from football.insights import _accumulate_possession_stat, _PossessionAccumulator

    acc = _PossessionAccumulator()
    details = _all_none(
        MatchDetails, source="goal", source_url="https://x", home_team="Home FC", away_team="X",
        match_stats=[_stat("Ball Possession", "40", "60")],
    )
    _accumulate_possession_stat(acc, details, _match(home_score=0, away_score=2), home=True)
    assert acc.high_pts == 0
    assert acc.high_count == 1


def test_accumulate_fouls():
    from football.insights import _accumulate_fouls, _SeasonStatsAccumulator

    acc = _SeasonStatsAccumulator()
    _accumulate_fouls(acc, [_stat("Fouls committed", "10", "12")], home=True)
    assert (acc.fouls_for, acc.fouls_against, acc.fouls_sample_size) == (10, 12, 1)


def test_build_estimates_from_a_fully_populated_accumulator():
    from football.insights import (
        _accumulate_cards,
        _accumulate_passing,
        _accumulate_shots_and_keeper,
        _accumulate_xg,
        _build_card_split,
        _build_goalkeeping_estimate,
        _build_passing_style,
        _build_shots_estimate,
        _build_xg_estimate,
        _SeasonStatsAccumulator,
    )

    acc = _SeasonStatsAccumulator()
    m = _match(home_score=2, away_score=1)
    _accumulate_xg(acc, [_stat("Expected goals (xG)", "1.5", "1.0")], m, home=True)
    _accumulate_shots_and_keeper(acc, [_stat("Total shots", "10", "8"), _stat("Shots on target", "4", "3"), _stat("Keeper saves", "2", "1")], m, home=True)
    _accumulate_cards(acc, [_stat("Yellow cards", "2", "1")], home=True)
    _accumulate_passing(acc, [_stat("Passes", "400", "350"), _stat("Accurate passes", "360", "300"), _stat("Accurate long balls", "20", "18")], home=True)

    xg = _build_xg_estimate(acc)
    assert xg.sample_size == 1
    assert xg.xg_for == 1.5
    assert xg.actual_goals_for == 2

    shots = _build_shots_estimate(acc)
    assert shots.shots_for == 10
    assert shots.shots_on_target_against == 3

    cards = _build_card_split(acc)
    assert cards.at_home_sample_size == 1
    assert cards.at_home_yellow_per_game == 2.0

    passing = _build_passing_style(acc)
    assert passing.pass_accuracy_pct == 90.0  # 360/400 * 100

    keeper = _build_goalkeeping_estimate(acc)
    assert keeper.goals_conceded == 1
    assert keeper.shots_on_target_faced == 3  # derived 2 saves + 1 conceded
    assert keeper.unreconciled_shots_on_target == 0
    assert keeper.save_pct == pytest.approx(66.7, abs=0.1)  # 2 saves / 3 derived SOT faced


# --- possession/corners accumulator family (compute_possession_matchup's
# --- extracted helpers, complexity 67 after this session's own connection-
# --- reuse edit -- same "previously scratchpad-only" gap as above) --------


def test_accumulate_possession_stat_high_possession_win():
    from football.insights import _accumulate_possession_stat, _PossessionAccumulator

    acc = _PossessionAccumulator()
    details = _all_none(MatchDetails, match_stats=[_stat("Ball possession", "40", "60")])
    m = _match(home_score=2, away_score=0)
    _accumulate_possession_stat(acc, details, m, home=True)  # opponent (away) had 60% possession
    assert (acc.high_pts, acc.high_count) == (3, 1)
    assert (acc.other_pts, acc.other_count) == (0, 0)


def test_accumulate_possession_stat_low_possession_bucket():
    from football.insights import _accumulate_possession_stat, _PossessionAccumulator

    acc = _PossessionAccumulator()
    details = _all_none(MatchDetails, match_stats=[_stat("Ball possession", "60", "40")])
    m = _match(home_score=1, away_score=1)
    _accumulate_possession_stat(acc, details, m, home=True)  # opponent had 40% possession -- "other" bucket
    assert (acc.other_pts, acc.other_count) == (1, 1)


def test_accumulate_possession_stat_skips_unparseable_value():
    from football.insights import _accumulate_possession_stat, _PossessionAccumulator

    acc = _PossessionAccumulator()
    details = _all_none(MatchDetails, match_stats=[_stat("Ball possession", "N/A", "N/A")])
    _accumulate_possession_stat(acc, details, _match(home_score=1, away_score=0), home=True)
    assert acc.high_count == 0
    assert acc.other_count == 0


def test_accumulate_possession_stat_no_op_without_possession_stat():
    from football.insights import _accumulate_possession_stat, _PossessionAccumulator

    acc = _PossessionAccumulator()
    details = _all_none(MatchDetails, match_stats=[])
    _accumulate_possession_stat(acc, details, _match(home_score=1, away_score=0), home=True)
    assert acc.high_count == 0
    assert acc.other_count == 0


def test_accumulate_corners_and_errors():
    from football.insights import _accumulate_corners_and_errors, _PossessionAccumulator

    acc = _PossessionAccumulator()
    details = _all_none(MatchDetails, match_stats=[_stat("Corner total", "7", "3"), _stat("Defensive error", "1", "2")])
    _accumulate_corners_and_errors(acc, details, home=True)
    assert (acc.corners_for, acc.corners_against, acc.corners_sample_size) == (7, 3, 1)
    assert (acc.def_errors_for, acc.def_errors_against, acc.def_errors_sample_size) == (1, 2, 1)


def test_accumulate_corners_and_errors_independent_of_each_other():
    from football.insights import _accumulate_corners_and_errors, _PossessionAccumulator

    acc = _PossessionAccumulator()
    # Only corners present -- defensive errors stat missing shouldn't block it.
    details = _all_none(MatchDetails, match_stats=[_stat("Corner total", "5", "4")])
    _accumulate_corners_and_errors(acc, details, home=True)
    assert acc.corners_sample_size == 1
    assert acc.def_errors_sample_size == 0


# --- compute_insights (top-level orchestrator -- most fields deliberately
# --- None here, filled in later by orchestrate.py; this just verifies the
# --- skeleton is built correctly from what IS available at this stage) ---


def test_compute_insights_builds_skeleton_from_available_data():
    from football.insights import OpponentContext, compute_insights

    merged = _all_none(MatchDetails, competition="Premier League", home_team_standing=_standing(position=2), away_team_standing=_standing(position=15))
    opponent = OpponentContext(rest_days=3, average_age=25.0, merged_profile=None, matches=[], error=None)
    insights = compute_insights(merged, own_average_age=28.0, own_rest_days=6, opponent=opponent)

    assert insights.match_type == "competitive"
    assert insights.rest_comparison.more_rested == "own"
    assert insights.experience_comparison.more_experienced == "own"
    assert insights.home_standings_zone.zone == "top-of-table"
    assert insights.opponent_context_error is None


def test_compute_insights_propagates_opponent_context_error():
    from football.insights import OpponentContext, compute_insights

    merged = _all_none(MatchDetails, competition="Premier League")
    opponent = OpponentContext(rest_days=None, average_age=None, merged_profile=None, matches=[], error="opponent not found")
    insights = compute_insights(merged, own_average_age=None, own_rest_days=None, opponent=opponent)
    assert insights.opponent_context_error == "opponent not found"


def test_build_estimates_return_none_from_an_empty_accumulator():
    from football.insights import (
        _build_card_split,
        _build_goalkeeping_estimate,
        _build_passing_style,
        _build_shots_estimate,
        _build_xg_estimate,
        _SeasonStatsAccumulator,
    )

    acc = _SeasonStatsAccumulator()
    assert _build_xg_estimate(acc) is None
    assert _build_shots_estimate(acc) is None
    assert _build_card_split(acc) is None
    assert _build_passing_style(acc) is None
    assert _build_goalkeeping_estimate(acc) is None


def test_build_goalkeeping_estimate_derives_sot_from_saves_plus_goals_so_arithmetic_reconciles():
    from football.insights import (
        _accumulate_shots_and_keeper,
        _build_goalkeeping_estimate,
        _SeasonStatsAccumulator,
    )

    acc = _SeasonStatsAccumulator()
    m = _match(home_score=5, away_score=3)  # home team concedes away_score=3
    # Provider SOT sum (away=1) deliberately disagrees with saves(2)+conceded(3)=5
    _accumulate_shots_and_keeper(
        acc,
        [_stat("Total shots", "10", "8"), _stat("Shots on target", "6", "1"), _stat("Keeper saves", "2", "4")],
        m,
        home=True,
    )
    keeper = _build_goalkeeping_estimate(acc)
    # Customer bug: "Home: 25 + 16 = 41 != 40" -- derived SOT must equal saves + goals
    assert keeper.saves_for + keeper.goals_conceded == keeper.shots_on_target_faced
    assert keeper.shots_on_target_faced == 5  # 2 saves + 3 conceded, NOT the provider's 1
    assert keeper.unreconciled_shots_on_target == 0
    assert keeper.save_pct == pytest.approx(40.0)  # 2/5 * 100


def test_goalkeeping_estimate_quantifies_the_saves_plus_conceded_gap_when_constructed_directly_with_independent_sot():
    from football.types import SeasonGoalkeepingEstimate

    over = SeasonGoalkeepingEstimate(sample_size=10, saves_for=25, shots_on_target_faced=40, save_pct=62.5, goals_conceded=16, source="fotmob")
    assert over.unreconciled_shots_on_target == -1  # 40 - (25 + 16)
    assert (over.saves_for, over.shots_on_target_faced, over.goals_conceded) == (25, 40, 16)

    under = SeasonGoalkeepingEstimate(sample_size=10, saves_for=20, shots_on_target_faced=33, save_pct=60.6, goals_conceded=12, source="fotmob")
    assert under.unreconciled_shots_on_target == 1  # 33 - (20 + 12)

    exact = SeasonGoalkeepingEstimate(sample_size=10, saves_for=20, shots_on_target_faced=30, save_pct=66.7, goals_conceded=10, source="fotmob")
    assert exact.unreconciled_shots_on_target == 0


def test_missing_player_absence_type_is_derived_from_the_published_description():
    from football.types import MissingPlayer

    def kind(description):
        return MissingPlayer(name="X", description=description, expected_return=None).absence_type

    assert kind("coach_decision") == "coach_decision"
    assert kind("Knee Injury") == "injury"
    assert kind("Cruciate Ligament Injury") == "injury"
    assert kind("Physical Discomfort (out)") == "injury"
    assert kind("Suspended") == "suspension"
    assert kind("Yellow card ban") == "suspension"
    assert kind("Personal reasons") == "other"
    assert kind(None) is None
    assert kind("  ") is None


def test_missing_player_nulls_expected_return_for_a_coach_decision():
    # A fixed far-future date on a coach_decision is not a medical return
    # and reads as a data error -- force it to None.
    from football.types import MissingPlayer

    m = MissingPlayer(name="Richarlison", description="coach_decision", expected_return="2027-01-02T00:00:00+00:00")
    assert m.absence_type == "coach_decision"
    assert m.expected_return is None


def test_completeness_counts_a_confirmed_empty_suspended_list_as_populated():
    checked = _all_none(MatchDetails, status="finished", home_suspended_players=[], away_suspended_players=None)
    result = compute_data_completeness(checked, None)
    assert "home_suspended_players" not in result["missing"]
    assert "away_suspended_players" in result["missing"]


# --- mark_projected_starters --------------------------------------------------------------------


def _squad_with_starts(rows):
    """rows: (name, role, starts, minutes)"""
    from football.types import PlayerUsagePattern

    return [
        _all_none(SquadMember, name=n, role=r, recent_usage=_all_none(PlayerUsagePattern, starts=st, total_minutes=mins))
        for n, r, st, mins in rows
    ]


def _presence(names, absent=()):
    from football.types import PresenceEntry

    return [PresenceEntry(name=n, status=("A" if n in absent else "P"), starting=False, on_bench=None, reason=None) for n in names]


def test_projected_xi_is_one_keeper_plus_the_ten_outfield_players_with_most_starts():
    from football.insights import mark_projected_starters

    rows = [("GK Regular", "G", 9, 810), ("GK Backup", "G", 1, 90)] + [(f"P{i}", "M", 10 - i, 900 - i) for i in range(12)]
    squad = _squad_with_starts(rows)
    presence = _presence([r[0] for r in rows])
    selected = mark_projected_starters(presence, squad)
    assert selected is not None
    assert len(selected) == 11
    chosen = {p.name for p in presence if p.projected_starter}
    assert len(chosen) == 11
    assert "GK Regular" in chosen
    assert "GK Backup" not in chosen
    assert {f"P{i}" for i in range(10)} <= chosen
    assert "P11" not in chosen


def test_projected_xi_skips_unavailable_players_even_if_they_start_the_most():
    from football.insights import mark_projected_starters

    rows = [("GK", "G", 8, 720), ("Star", "F", 10, 900)] + [(f"P{i}", "M", 5, 450) for i in range(10)]
    squad = _squad_with_starts(rows)
    presence = _presence([r[0] for r in rows], absent={"Star"})
    mark_projected_starters(presence, squad)
    assert not next(p for p in presence if p.name == "Star").projected_starter


def test_projected_xi_is_not_made_once_a_real_lineup_is_marked_or_without_usage_history():
    from football.insights import mark_projected_starters
    from football.types import PresenceEntry

    squad = _squad_with_starts([("GK", "G", 8, 720), ("A", "M", 5, 450)])
    confirmed = [PresenceEntry(name="GK", status="P", starting=True, on_bench=None, reason=None)]
    assert mark_projected_starters(confirmed, squad) is None
    assert confirmed[0].projected_starter is False

    no_history = [_all_none(SquadMember, name="GK", role="G", recent_usage=None)]
    assert mark_projected_starters(_presence(["GK"]), no_history) is None
    assert mark_projected_starters(None, squad) is None
    assert mark_projected_starters(_presence(["GK"]), None) is None


def test_projected_xi_tie_on_starts_is_broken_by_minutes():
    from football.insights import mark_projected_starters

    rows = [("GK", "G", 5, 450)] + [(f"P{i}", "M", 5, 450 + i) for i in range(11)]
    squad = _squad_with_starts(rows)
    presence = _presence([r[0] for r in rows])
    mark_projected_starters(presence, squad)
    assert not next(p for p in presence if p.name == "P0").projected_starter  # fewest minutes misses out


# --- fill_standings_form ------------------------------------------------------------------------


def _table_row(position, form=None):
    from football.types import StandingsTableRow

    return StandingsTableRow(team_name=f"T{position}", position=position, points=0, form=form)


def _league_result(result, competition="Premier League", date="2026-01-01T00:00:00.000Z"):
    from football.types import FormResult

    return _all_none(FormResult, result=result, competition=competition, date=date)


def test_fill_standings_form_uses_the_last_five_league_results_oldest_first():
    from football.insights import fill_standings_form

    table = [_table_row(1), _table_row(2)]
    # newest-first, as FormSummary provides them; the cup match is ignored
    results = [_league_result("W"), _league_result("L", competition="EFL Cup"), _league_result("D"), _league_result("L"), _league_result("W"), _league_result("W"), _league_result("L")]
    fill_standings_form(table, 2, results, "Premier League")
    assert table[1].form == "WWLDW"  # last 5 league results (W,D,L,W,W newest-first) reversed to oldest-first
    assert table[0].form is None  # other teams are never guessed


def test_fill_standings_form_leaves_an_existing_value_and_no_op_without_data():
    from football.insights import fill_standings_form

    table = [_table_row(1, form="LLLLL")]
    fill_standings_form(table, 1, [_league_result("W")], "Premier League")
    assert table[0].form == "LLLLL"

    empty = [_table_row(1)]
    fill_standings_form(empty, 1, [_league_result("W", competition="Cup")], "Premier League")
    fill_standings_form(empty, 9, [_league_result("W")], "Premier League")
    fill_standings_form(empty, None, [_league_result("W")], "Premier League")
    fill_standings_form(None, 1, [_league_result("W")], "Premier League")
    assert empty[0].form is None


def test_fill_standings_form_matches_stage_suffixed_competitions():
    # Fixture competition is plain "UEFA Champions League" while the form
    # source tagged a recent result "UEFA Champions League, Knockout stage"
    # -- strict == left form null; base-name match fills it.
    from football.insights import fill_standings_form
    from football.types import FormResult

    table = [_table_row(1), _table_row(2)]
    results = [
        _all_none(FormResult, result="W", competition="UEFA Champions League, Knockout stage", date="2026-01-01T00:00:00.000Z"),
        _all_none(FormResult, result="L", competition="UEFA Champions League, Knockout stage", date="2025-12-01T00:00:00.000Z"),
    ]
    fill_standings_form(table, 2, results, "UEFA Champions League")
    assert table[1].form == "LW"


def test_fill_standings_form_from_map_fills_null_rows_without_overwriting():
    from football.insights import fill_standings_form_from_map
    from football.types import StandingsTableRow

    table = [
        StandingsTableRow(team_name="Manchester United", position=1, points=0, form="WWWWW"),
        StandingsTableRow(team_name="Arsenal", position=2, points=0, form=None),
        StandingsTableRow(team_name="Liverpool", position=3, points=0, form=None),
    ]
    form_map = {"manchester united": "LLLLL", "arsenal": "WDWLD"}
    fill_standings_form_from_map(table, form_map)
    assert table[0].form == "WWWWW"  # existing fixture-team form kept
    assert table[1].form == "WDWLD"
    assert table[2].form is None  # not in the map -- left null, not guessed
    fill_standings_form_from_map(table, None)
    fill_standings_form_from_map(None, form_map)
    fill_standings_form_from_map(table, {})
    assert table[1].form == "WDWLD"


def test_opponent_rank_record_finds_the_opponent_by_alias_not_just_substring():
    # The form source spells it "Man Utd"; the standings table (another
    # source) says "Manchester United" -- neither contains the other, so the
    # old substring-only match silently dropped the result.
    from football.types import FormResult, StandingsTableRow

    def result(opponent):
        return _all_none(FormResult, opponent=opponent, competition="Premier League", result="W")

    table = [StandingsTableRow(team_name="Manchester United", position=1, points=10), StandingsTableRow(team_name="Own FC", position=5, points=5)]
    record = compute_opponent_rank_record([result("Man Utd")], "Premier League", table, own_position=5)
    assert record is not None
    assert record.wins == 1


def test_compute_recent_meetings_matches_the_opponent_by_alias(monkeypatch):
    from football import orchestrate

    raw_match = _match(home_team="Own FC", away_team="Man Utd", kickoff_utc="2026-01-01T15:00:00.000Z")
    details = _all_none(MatchDetails, source="sofascore", source_url="https://x", home_team="Own FC", away_team="Man Utd", match_stats=[])

    async def fake_details(_m):
        return details

    monkeypatch.setattr(orchestrate, "SCRAPERS", {"sofascore": type("S", (), {"details": staticmethod(fake_details)})()})
    results = [_form_result(opponent="Man Utd", date="2026-01-01T15:00:00.000Z", scoreline="1-0")]
    meetings = asyncio.run(compute_recent_meetings([raw_match], results, "Manchester United", "sofascore"))
    assert len(meetings) == 1


# --- derive_lineup_and_formation ------------------------------------------------------------------


def test_derive_lineup_builds_eleven_players_from_the_projected_xi_with_no_fabricated_formation():
    from football.insights import derive_lineup, mark_projected_starters

    rows = [("GK", "G", 8, 720)] + [(f"D{i}", "D", 6, 540) for i in range(4)] + [(f"M{i}", "M", 6, 540) for i in range(3)] + [(f"F{i}", "F", 6, 540) for i in range(3)] + [("Bench", "M", 1, 90)]
    squad = _squad_with_starts(rows)
    presence = _presence([r[0] for r in rows])
    selected = mark_projected_starters(presence, squad)

    lineup = derive_lineup(selected, squad)
    assert lineup is not None
    assert len(lineup) == 11
    positions = {p.name: p.position for p in lineup}
    assert positions["GK"] == "G"
    assert positions["D0"] == "D"
    assert all(p.substitute is False for p in lineup)
    assert all(p.minutes_played is None and p.goals is None for p in lineup)  # no fabricated stats


def test_derive_lineup_uses_the_squad_members_real_age_and_published_shirt_number():
    from football.insights import derive_lineup, mark_projected_starters
    from football.types import PlayerUsagePattern

    squad = [
        _all_none(SquadMember, name="GK", role="G", age=29, shirt_number=1, recent_usage=_all_none(PlayerUsagePattern, starts=8, total_minutes=720)),
    ]
    presence = _presence(["GK"])
    selected = mark_projected_starters(presence, squad)
    lineup = derive_lineup(selected, squad)
    assert lineup[0].age == 29
    assert lineup[0].shirt_number == 1  # published by the squad source (Sofascore shirtNumber)


def test_derive_lineup_leaves_shirt_number_none_when_squad_source_has_none():
    from football.insights import derive_lineup, mark_projected_starters
    from football.types import PlayerUsagePattern

    squad = [
        _all_none(SquadMember, name="GK", role="G", age=29, shirt_number=None, recent_usage=_all_none(PlayerUsagePattern, starts=8, total_minutes=720)),
    ]
    presence = _presence(["GK"])
    selected = mark_projected_starters(presence, squad)
    lineup = derive_lineup(selected, squad)
    assert lineup[0].shirt_number is None


def test_derive_lineup_none_without_a_selection_or_squad():
    from football.insights import derive_lineup

    squad = _squad_with_starts([("GK", "G", 8, 720)])
    assert derive_lineup(None, squad) is None
    assert derive_lineup([], squad) is None
    assert derive_lineup([object()], None) is None


def test_derive_projected_bench_excludes_absent_players():
    from football.insights import derive_projected_bench
    from football.types import LineupPlayer

    rows = [("GK", "G", 8, 720), ("Starter", "M", 6, 540), ("Bench Fit", "M", 1, 90), ("Bench Injured", "F", 1, 90)]
    squad = _squad_with_starts(rows)
    lineup = [_all_none(LineupPlayer, name="GK", substitute=False), _all_none(LineupPlayer, name="Starter", substitute=False)]
    bench = derive_projected_bench(lineup, squad, absent={"bench injured"})
    assert bench is not None
    names = {p.name for p in bench}
    assert "Bench Fit" in names
    assert "Bench Injured" not in names


# --- add_clean_sheets_recent_check --------------------------------------------------------------


def test_add_clean_sheets_recent_check_counts_competitive_clean_sheets():
    from football.insights import add_clean_sheets_recent_check
    from football.types import FormResult, TeamSeasonStats

    stats = TeamSeasonStats(goals_scored=8, goals_conceded=8, clean_sheets=0, yellow_cards=0, red_cards=0, average_ball_possession=None)
    results = [
        _all_none(FormResult, scoreline="0-0", venue="home", competition="Premier League"),
        _all_none(FormResult, scoreline="0-0", venue="away", competition="Premier League"),
        _all_none(FormResult, scoreline="1-1", venue="home", competition="Premier League"),
        _all_none(FormResult, scoreline="0-0", venue="home", competition="Club Friendly Games"),
    ]
    add_clean_sheets_recent_check(stats, results)
    assert stats.clean_sheets_recent_check == 2  # the friendly clean sheet doesn't count
    assert stats.clean_sheets_recent_check_sample_size == 3  # competitive results only
    assert stats.clean_sheets == 0  # season aggregate untouched -- form window is a different slice
    assert stats.clean_sheets_source_aggregate is None  # no reconciliation (never mutates clean_sheets)


def test_add_clean_sheets_recent_check_leaves_source_aggregate_when_already_current():
    from football.insights import add_clean_sheets_recent_check
    from football.types import FormResult, TeamSeasonStats

    stats = TeamSeasonStats(goals_scored=8, goals_conceded=8, clean_sheets=5, yellow_cards=0, red_cards=0, average_ball_possession=None)
    results = [_all_none(FormResult, scoreline="1-0", venue="home", competition="Premier League")]
    add_clean_sheets_recent_check(stats, results)
    assert stats.clean_sheets == 5  # season aggregate unchanged
    assert stats.clean_sheets_source_aggregate is None  # no reconciliation happened
    assert stats.clean_sheets_recent_check == 1
    assert stats.clean_sheets_recent_check_sample_size == 1


def test_add_clean_sheets_recent_check_records_which_source_the_results_came_from():
    # A swing in this count between two runs is usually the results
    # coming from a different source (e.g. a Sofascore block falling back
    # to Fotmob) -- record which one, same reasoning as EloRating.
    # sample_source, so that swing is explained rather than a mystery.
    from football.insights import add_clean_sheets_recent_check
    from football.types import FormResult, TeamSeasonStats

    stats = TeamSeasonStats(goals_scored=0, goals_conceded=0, clean_sheets=0, yellow_cards=0, red_cards=0, average_ball_possession=None)
    results = [_all_none(FormResult, scoreline="0-0", venue="home", competition="Premier League")]
    add_clean_sheets_recent_check(stats, results, "fotmob")
    assert stats.clean_sheets_recent_check_source == "fotmob"
    assert stats.clean_sheets_recent_check == 1
    assert stats.clean_sheets_recent_check_sample_size == 1


def test_add_clean_sheets_recent_check_noop_without_stats_or_results():
    from football.insights import add_clean_sheets_recent_check
    from football.types import FormResult, TeamSeasonStats

    stats = TeamSeasonStats(goals_scored=0, goals_conceded=0, clean_sheets=0, yellow_cards=0, red_cards=0, average_ball_possession=None)
    add_clean_sheets_recent_check(stats, None)
    assert stats.clean_sheets_recent_check is None
    assert stats.clean_sheets_recent_check_sample_size is None
    add_clean_sheets_recent_check(None, [_all_none(FormResult, scoreline="0-0", venue="home", competition="Premier League")])  # must not raise


# --- add_possession_venue_split_check --------------------------------------------------------------


def test_add_possession_venue_split_check_weights_buckets_by_sample_size():
    from football.insights import add_possession_venue_split_check
    from football.types import DetailedVenueSplitForm, TeamSeasonStats, VenueSplitStats

    def bucket(n: int, poss: float | None) -> VenueSplitStats:
        return VenueSplitStats(
            sample_size=n, xg_for=0, xg_against=0, shots_for=0, shots_against=0,
            shots_on_target_for=0, shots_on_target_against=0, possession_pct_avg=poss,
            corners_for=0, corners_against=0, fouls_for=0, fouls_against=0,
            yellow_cards_for=0, yellow_cards_against=0, red_cards_for=0, red_cards_against=0,
            big_chances_created_for=0, big_chances_created_against=0,
        )

    stats = TeamSeasonStats(goals_scored=0, goals_conceded=0, clean_sheets=0, yellow_cards=0, red_cards=0, average_ball_possession=59.0)
    split = DetailedVenueSplitForm(
        home=bucket(9, 56.4), away=bucket(6, 52.5), neutral=bucket(3, 63.0),
    )
    add_possession_venue_split_check(stats, split, "sofascore")
    # (56.4*9 + 52.5*6 + 63.0*3) / 18 = 56.2
    assert stats.possession_venue_split_check == 56.2
    assert stats.possession_venue_split_check_source == "sofascore"
    assert stats.average_ball_possession == 59.0  # gap 2.8pp <= 5: no reconcile
    assert stats.average_ball_possession_source_season is None


def test_add_possession_venue_split_check_replaces_season_when_gap_exceeds_5pp():
    from football.insights import add_possession_venue_split_check
    from football.types import DetailedVenueSplitForm, TeamSeasonStats, VenueSplitStats

    def bucket(n: int, poss: float | None) -> VenueSplitStats:
        return VenueSplitStats(
            sample_size=n, xg_for=0, xg_against=0, shots_for=0, shots_against=0,
            shots_on_target_for=0, shots_on_target_against=0, possession_pct_avg=poss,
            corners_for=0, corners_against=0, fouls_for=0, fouls_against=0,
            yellow_cards_for=0, yellow_cards_against=0, red_cards_for=0, red_cards_against=0,
            big_chances_created_for=0, big_chances_created_against=0,
        )

    # Season 60.0 vs form-window ~53: gap > 5pp, form window wins.
    stats = TeamSeasonStats(goals_scored=0, goals_conceded=0, clean_sheets=0, yellow_cards=0, red_cards=0, average_ball_possession=60.0)
    split = DetailedVenueSplitForm(home=bucket(10, 53.0), away=bucket(10, 53.0), neutral=None)
    add_possession_venue_split_check(stats, split, "sofascore")
    assert stats.possession_venue_split_check == 53.0
    assert stats.average_ball_possession == 53.0
    assert stats.average_ball_possession_source_season == 60.0
    assert stats.possession_venue_split_check_source == "sofascore"


def test_add_possession_venue_split_check_noop_when_no_possession_buckets():
    from football.insights import add_possession_venue_split_check
    from football.types import DetailedVenueSplitForm, TeamSeasonStats, VenueSplitStats

    def empty_bucket() -> VenueSplitStats:
        return VenueSplitStats(
            sample_size=5, xg_for=0, xg_against=0, shots_for=0, shots_against=0,
            shots_on_target_for=0, shots_on_target_against=0, possession_pct_avg=None,
            corners_for=0, corners_against=0, fouls_for=0, fouls_against=0,
            yellow_cards_for=0, yellow_cards_against=0, red_cards_for=0, red_cards_against=0,
            big_chances_created_for=0, big_chances_created_against=0,
        )

    stats = TeamSeasonStats(goals_scored=0, goals_conceded=0, clean_sheets=0, yellow_cards=0, red_cards=0, average_ball_possession=59.0)
    split = DetailedVenueSplitForm(home=empty_bucket(), away=empty_bucket(), neutral=empty_bucket())
    add_possession_venue_split_check(stats, split)
    assert stats.possession_venue_split_check is None
    assert stats.possession_window_note is None
    add_possession_venue_split_check(stats, None)
    add_possession_venue_split_check(None, split)


def test_possession_window_note_names_both_windows_when_gap_exceeds_5pp():
    from football.insights import add_possession_venue_split_check
    from football.types import DetailedVenueSplitForm, TeamSeasonStats, VenueSplitStats

    def bucket(n: int, poss: float) -> VenueSplitStats:
        return VenueSplitStats(
            sample_size=n, xg_for=0, xg_against=0, shots_for=0, shots_against=0,
            shots_on_target_for=0, shots_on_target_against=0, possession_pct_avg=poss,
            corners_for=0, corners_against=0, fouls_for=0, fouls_against=0,
            yellow_cards_for=0, yellow_cards_against=0, red_cards_for=0, red_cards_against=0,
            big_chances_created_for=0, big_chances_created_against=0,
        )

    stats = TeamSeasonStats(goals_scored=0, goals_conceded=0, clean_sheets=0, yellow_cards=0, red_cards=0, average_ball_possession=60.0)
    split = DetailedVenueSplitForm(home=bucket(10, 53.0), away=bucket(10, 53.0), neutral=None)
    add_possession_venue_split_check(stats, split, "sofascore")
    note = stats.possession_window_note
    assert note is not None
    assert "last-20 venue-split" in note
    assert "60" in note and "average_ball_possession_source_season" in note
    assert ">5pp" in note


def test_possession_window_note_names_both_windows_when_gap_is_within_5pp():
    from football.insights import add_possession_venue_split_check
    from football.types import DetailedVenueSplitForm, TeamSeasonStats, VenueSplitStats

    def bucket(n: int, poss: float) -> VenueSplitStats:
        return VenueSplitStats(
            sample_size=n, xg_for=0, xg_against=0, shots_for=0, shots_against=0,
            shots_on_target_for=0, shots_on_target_against=0, possession_pct_avg=poss,
            corners_for=0, corners_against=0, fouls_for=0, fouls_against=0,
            yellow_cards_for=0, yellow_cards_against=0, red_cards_for=0, red_cards_against=0,
            big_chances_created_for=0, big_chances_created_against=0,
        )

    # Man Utd audit case: 60.0 season vs 55.2 check = 4.8pp <=5, season kept.
    stats = TeamSeasonStats(goals_scored=0, goals_conceded=0, clean_sheets=0, yellow_cards=0, red_cards=0, average_ball_possession=60.0)
    split = DetailedVenueSplitForm(home=bucket(10, 55.2), away=bucket(10, 55.2), neutral=None)
    add_possession_venue_split_check(stats, split, "sofascore")
    note = stats.possession_window_note
    assert note is not None
    assert "season-to-date" in note
    assert "55.2" in note
    assert "<=5pp" in note
    assert stats.average_ball_possession == 60.0
    assert stats.average_ball_possession_source_season is None


def test_a_real_lineup_with_a_spelling_mismatch_still_blocks_the_competing_projection():
    # End-to-end version of the two tests above: once `starting` is
    # correctly detected despite the spelling gap, mark_projected_starters'
    # own guard (any(p.starting for p in presence)) must prevent it from
    # deriving a second, competing, different XI.
    from football.insights import mark_projected_starters
    from football.types import LineupPlayer, PlayerUsagePattern

    tielemans = _all_none(SquadMember, name="Tielemans", role="M", recent_usage=_all_none(PlayerUsagePattern, starts=1, total_minutes=90))
    other = _all_none(SquadMember, name="Preferred By Usage", role="M", recent_usage=_all_none(PlayerUsagePattern, starts=10, total_minutes=900))
    squad = [tielemans, other]
    presence = compute_presence(squad=squad, lineup=[_all_none(LineupPlayer, name="Youri Tielemans")], bench=None, injuries=None, suspended=None)
    assert mark_projected_starters(presence, squad) is None
    assert all(p.projected_starter is False for p in presence)
