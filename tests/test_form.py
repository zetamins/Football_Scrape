import asyncio
from dataclasses import fields as _dc_fields
from datetime import UTC, datetime, timedelta

import pytest

from football.form import (
    _both_scored,
    _compute_clean_sheet_and_scoreless_streaks,
    _compute_current_streak,
    _compute_form_by_competition,
    _compute_half_split,
    _compute_last10_stats,
    _compute_momentum,
    _compute_next5_with_gaps,
    _points_for_result,
    _sum_xa,
    _tally_player_stats,
    _team_goals,
    _to_form_result,
    _total_goals,
    _win_rate,
    all_form_results,
    compute_form_summary,
    day_diff,
    enrich_form_with_venue_classification,
    format_when,
    is_team_home,
    next_match,
    parse_leading_float,
    parse_leading_int,
    result_goals,
    stat_for,
    stat_for_float,
)
from football.types import FormResult, MatchInfo, MatchStatItem


def _all_none(cls, **overrides):
    base = {f.name: None for f in _dc_fields(cls)}
    base.update(overrides)
    return cls(**base)


def _match(home_team="Home FC", away_team="Away FC", **overrides):
    base = {
        "source": "sofascore", "source_url": "https://x", "competition": "Premier League",
        "home_team": home_team, "away_team": away_team, "kickoff_utc": "2026-01-01T15:00:00.000Z",
        "venue": None, "status": "finished", "home_score": 1, "away_score": 1,
        "home_score_ht": None, "away_score_ht": None, "season": None, "round": None, "match_id": "1",
    }
    base.update(overrides)
    return MatchInfo(**base)


def _result(**overrides):
    base = {
        "opponent": "Rival FC", "competition": "Premier League", "date": "2026-01-01T15:00:00.000Z", "result": "W",
        "scoreline": "2-1", "venue": "home", "margin": 1, "neutral_venue": None, "ht_scoreline": None, "xg_for": None, "xg_against": None,
    }
    base.update(overrides)
    return FormResult(**base)


# --- is_team_home (pre-existing tests, kept) --------------------------------


def test_direct_substring_match_still_works():
    m = _match("Arsenal FC", "Chelsea FC")
    assert is_team_home(m, "Arsenal") is True
    assert is_team_home(m, "Chelsea") is False


def test_alias_table_resolves_name_with_no_shared_substring():
    # Fotmob's own literal stored name for Nottingham Forest is "Nottm
    # Forest" -- confirmed live -- which shares no substring with
    # "Nottingham Forest" in either direction, so only the alias-table
    # fallback in is_team_home can resolve this.
    m = _match("Nottm Forest", "Arsenal")
    assert is_team_home(m, "Nottingham Forest") is True
    assert is_team_home(m, "Nott'm Forest") is True


def test_unrelated_team_returns_none():
    m = _match("Nottm Forest", "Arsenal")
    assert is_team_home(m, "Chelsea") is None


def test_alias_table_resolves_away_team_with_no_shared_substring():
    # Same alias-table fallback as the home-team case above, but for the
    # away team specifically -- a distinct branch (own if/return) from
    # the home-team alias check just above it.
    m = _match("Arsenal", "Nottm Forest")
    assert is_team_home(m, "Nottingham Forest") is False


# --- next_match / format_when / day_diff ------------------------------------


def test_next_match_picks_earliest_future_fixture():
    now = datetime.now(tz=UTC)
    future1 = (now + timedelta(days=10)).isoformat()
    future2 = (now + timedelta(days=3)).isoformat()
    past = (now - timedelta(days=1)).isoformat()
    m1 = _match(kickoff_utc=future1, status="scheduled")
    m2 = _match(kickoff_utc=future2, status="scheduled")
    m3 = _match(kickoff_utc=past)
    assert next_match([m1, m2, m3]) is m2


def test_next_match_none_without_future_fixtures():
    past = (datetime.now(tz=UTC) - timedelta(days=1)).isoformat()
    assert next_match([_match(kickoff_utc=past)]) is None


# Confirmed live: a real reported bug for Everton -- next_match() picked
# a postponed "Everton vs Man Utd" fixture over the genuinely next
# scheduled "Tottenham vs Everton" one. Root cause: a postponed/
# interrupted/live match can still carry its original, now-stale
# kickoff_utc value (simply never updated once the match stopped being
# on schedule), so a pure future-kickoff-time sort with no status check
# let it silently outrank the real next fixture. See next_match's own
# doc comment (football/form.py) and NOT_STARTED_STATUSES for the fix.


def test_next_match_ignores_a_nearer_postponed_fixture_with_a_stale_future_kickoff():
    now = datetime.now(tz=UTC)
    nearer_but_postponed = _match(
        home_team="Everton", away_team="Man Utd", kickoff_utc=(now + timedelta(days=1)).isoformat(), status="postponed",
    )
    genuinely_next = _match(
        home_team="Tottenham", away_team="Everton", kickoff_utc=(now + timedelta(days=5)).isoformat(), status="scheduled",
    )
    assert next_match([nearer_but_postponed, genuinely_next]) is genuinely_next


def test_next_match_ignores_a_nearer_interrupted_or_live_fixture_with_a_stale_future_kickoff():
    now = datetime.now(tz=UTC)
    interrupted = _match(kickoff_utc=(now + timedelta(hours=1)).isoformat(), status="interrupted")
    live = _match(kickoff_utc=(now + timedelta(hours=2)).isoformat(), status="inprogress")
    genuinely_next = _match(kickoff_utc=(now + timedelta(days=2)).isoformat(), status="scheduled")
    assert next_match([interrupted, live, genuinely_next]) is genuinely_next


def test_next_match_recognizes_sofascores_notstarted_status_too():
    # Sofascore's own vocabulary uses "notstarted" where every other
    # source in this codebase uses "scheduled" -- both must be
    # recognized as genuinely upcoming.
    future = (datetime.now(tz=UTC) + timedelta(days=3)).isoformat()
    m = _match(kickoff_utc=future, status="notstarted")
    assert next_match([m]) is m


def test_next_match_none_when_every_future_looking_fixture_has_a_non_upcoming_status():
    now = datetime.now(tz=UTC)
    cancelled = _match(kickoff_utc=(now + timedelta(days=1)).isoformat(), status="cancelled")
    unknown_status = _match(kickoff_utc=(now + timedelta(days=2)).isoformat(), status=None)
    assert next_match([cancelled, unknown_status]) is None


def test_format_when_formats_a_real_date():
    assert format_when("2026-03-01T15:30:00.000Z") == "2026-03-01 15:30 UTC"


def test_format_when_tbd_without_kickoff():
    assert format_when(None) == "TBD"


def test_day_diff_computes_whole_days():
    assert day_diff("2026-01-10T00:00:00.000Z", "2026-01-01T00:00:00.000Z") == 9


# --- _to_form_result ----------------------------------------------------------


def test_to_form_result_win_at_home():
    m = _match(home_team="Home FC", away_team="Away FC", home_score=2, away_score=0)
    r = _to_form_result(m, "Home FC")
    assert r.result == "W"
    assert r.opponent == "Away FC"
    assert r.venue == "home"
    assert r.margin == 2


def test_to_form_result_loss_away():
    m = _match(home_team="Home FC", away_team="Away FC", home_score=2, away_score=0)
    r = _to_form_result(m, "Away FC")
    assert r.result == "L"
    assert r.venue == "away"


def test_to_form_result_draw():
    m = _match(home_score=1, away_score=1)
    assert _to_form_result(m, "Home FC").result == "D"


def test_to_form_result_none_when_team_unrelated():
    m = _match(home_team="Home FC", away_team="Away FC")
    assert _to_form_result(m, "Chelsea") is None


# --- _team_goals / _total_goals / _both_scored / _points_for_result --------


def test_team_goals_from_home_perspective():
    r = _result(scoreline="3-1", venue="home")
    assert _team_goals(r) == {"for": 3, "against": 1}


def test_team_goals_from_away_perspective():
    r = _result(scoreline="3-1", venue="away")
    assert _team_goals(r) == {"for": 1, "against": 3}


def test_total_goals():
    assert _total_goals(_result(scoreline="2-3")) == 5


def test_both_scored_true_when_both_sides_score():
    assert _both_scored(_result(scoreline="1-1")) is True
    assert _both_scored(_result(scoreline="1-0")) is False


def test_points_for_result():
    assert _points_for_result(_result(result="W")) == 3
    assert _points_for_result(_result(result="D")) == 1
    assert _points_for_result(_result(result="L")) == 0


def test_result_goals_matches_team_goals():
    r = _result(scoreline="2-1", venue="away")
    assert result_goals(r) == _team_goals(r)


# --- _win_rate ------------------------------------------------------------------


def test_win_rate_computes_percentage():
    results = [_result(result="W"), _result(result="W"), _result(result="L"), _result(result="D")]
    assert _win_rate(results) == 50


def test_win_rate_none_without_results():
    assert _win_rate([]) is None


# --- _compute_next5_with_gaps -------------------------------------------------


def test_next5_with_gaps_computes_days_since_previous():
    now = datetime.now(tz=UTC)
    past = _match(home_team="Home FC", away_team="Prev Opp", kickoff_utc=(now - timedelta(days=2)).isoformat())
    future1 = _match(home_team="Home FC", away_team="Next Opp1", kickoff_utc=(now + timedelta(days=3)).isoformat(), status="scheduled")
    gaps = _compute_next5_with_gaps([past, future1], now, "Home FC")
    assert len(gaps) == 1
    assert gaps[0].opponent == "Next Opp1"
    assert gaps[0].days_since_previous == 5


def test_next5_with_gaps_caps_at_five():
    now = datetime.now(tz=UTC)
    matches = [
        _match(home_team="Home FC", away_team=f"Opp{i}", kickoff_utc=(now + timedelta(days=i)).isoformat(), status="scheduled")
        for i in range(1, 8)
    ]
    gaps = _compute_next5_with_gaps(matches, now, "Home FC")
    assert len(gaps) == 5


def test_next5_with_gaps_ignores_postponed_fixture_with_stale_future_kickoff():
    # Same bug class as next_match: a postponed fixture keeps its original
    # future kickoff_utc and must not occupy a next5 slot / rest-day gap.
    now = datetime.now(tz=UTC)
    postponed = _match(
        home_team="Home FC", away_team="Postponed Opp",
        kickoff_utc=(now + timedelta(days=1)).isoformat(), status="postponed",
    )
    scheduled = _match(
        home_team="Home FC", away_team="Scheduled Opp",
        kickoff_utc=(now + timedelta(days=3)).isoformat(), status="scheduled",
    )
    gaps = _compute_next5_with_gaps([postponed, scheduled], now, "Home FC")
    assert [g.opponent for g in gaps] == ["Scheduled Opp"]


def test_details_cache_key_includes_team_names_not_just_kickoff():
    from football.form import _details_cache_key

    now = datetime.now(tz=UTC).isoformat()
    a = _match(home_team="Team A", away_team="Team B", kickoff_utc=now)
    b = _match(home_team="Team C", away_team="Team D", kickoff_utc=now)
    assert _details_cache_key(a) is not None
    assert _details_cache_key(a) != _details_cache_key(b)
    assert _details_cache_key(_match(home_team="Team A", away_team="Team B", kickoff_utc=None)) is None


# --- _compute_half_split -------------------------------------------------------


def test_half_split_computes_first_and_second_half_goals():
    played = [
        _match(home_team="Home FC", away_team="X", home_score=2, away_score=1, home_score_ht=1, away_score_ht=0),
    ]
    split = _compute_half_split(played, "Home FC")
    assert split.sample_size == 1
    assert split.first_half_goals_for == 1
    assert split.second_half_goals_for == 1  # 2 total - 1 HT
    assert split.first_half_goals_against == 0
    assert split.second_half_goals_against == 1


def test_half_split_none_without_ht_data():
    played = [_match(home_score_ht=None, away_score_ht=None)]
    assert _compute_half_split(played, "Home FC") is None


def test_half_split_skips_a_match_where_the_team_cannot_be_identified():
    # A match whose home/away teams don't resolve to the searched team at
    # all (is_team_home returns None) must be skipped, not miscounted as
    # a home or away result.
    unrelated = _match(home_team="Team X", away_team="Team Y", home_score_ht=1, away_score_ht=0)
    real = _match(home_team="Home FC", away_team="Z", home_score=2, away_score=1, home_score_ht=1, away_score_ht=0)
    split = _compute_half_split([unrelated, real], "Home FC")
    assert split.sample_size == 1


# --- _compute_current_streak ---------------------------------------------------


def test_current_streak_counts_consecutive_same_results():
    results = [_result(result="W"), _result(result="W"), _result(result="L")]
    streak = _compute_current_streak(results)
    assert streak.result == "W"
    assert streak.count == 2


def test_current_streak_none_without_results():
    assert _compute_current_streak([]) is None


# --- _compute_momentum ---------------------------------------------------------


def test_momentum_improving_when_recent_ppg_up():
    # recent 3: W W W (3.0 ppg), prior 3: L L L (0.0 ppg) -- big improvement.
    results = [_result(result="W")] * 3 + [_result(result="L")] * 3
    momentum = _compute_momentum(results)
    assert momentum.trend == "improving"
    assert momentum.recent_ppg == 3.0
    assert momentum.prior_ppg == 0.0


def test_momentum_declining():
    results = [_result(result="L")] * 3 + [_result(result="W")] * 3
    assert _compute_momentum(results).trend == "declining"


def test_momentum_stable_with_small_diff():
    results = [_result(result="D")] * 3 + [_result(result="D")] * 3
    assert _compute_momentum(results).trend == "stable"


def test_momentum_none_with_fewer_than_six_results():
    assert _compute_momentum([_result()] * 5) is None


# --- _compute_clean_sheet_and_scoreless_streaks --------------------------------


def test_clean_sheet_and_scoreless_streaks():
    # most recent first: two clean sheets then a conceded match
    results = [
        _result(scoreline="1-0", venue="home"),
        _result(scoreline="2-0", venue="home"),
        _result(scoreline="1-1", venue="home"),
    ]
    cs, ss = _compute_clean_sheet_and_scoreless_streaks(results)
    assert cs == 2  # two matches conceding 0
    assert ss == 0  # most recent match scored (1), so scoreless streak is 0


def test_scoreless_streak_counts_when_recent_matches_failed_to_score():
    results = [
        _result(scoreline="0-1", venue="home"),
        _result(scoreline="0-2", venue="home"),
        _result(scoreline="1-1", venue="home"),
    ]
    _cs, ss = _compute_clean_sheet_and_scoreless_streaks(results)
    assert ss == 2


def test_clean_sheet_streak_none_without_results():
    assert _compute_clean_sheet_and_scoreless_streaks([]) == (None, None)


# --- _compute_form_by_competition -----------------------------------------------


def test_form_by_competition_splits_by_competition():
    results = [
        _result(competition="Premier League", result="W", scoreline="2-0", venue="home"),
        _result(competition="Premier League", result="L", scoreline="0-1", venue="away"),
        _result(competition="FA Cup", result="D", scoreline="1-1", venue="home"),
    ]
    records = _compute_form_by_competition(results)
    by_comp = {r.competition: r for r in records}
    assert by_comp["Premier League"].played == 2
    assert by_comp["Premier League"].wins == 1
    assert by_comp["Premier League"].losses == 1
    assert by_comp["FA Cup"].draws == 1


def test_form_by_competition_skips_results_without_competition():
    results = [_result(competition=None)]
    assert _compute_form_by_competition(results) == []


def test_form_by_competition_folds_stage_suffixes_into_base_name():
    results = [
        _result(competition="UEFA Champions League, Knockout stage", result="W", scoreline="2-0", venue="home"),
        _result(competition="UEFA Champions League", result="D", scoreline="1-1", venue="away"),
    ]
    records = _compute_form_by_competition(results)
    assert [r.competition for r in records] == ["UEFA Champions League"]
    assert records[0].played == 2


# --- _compute_last10_stats -------------------------------------------------------


def test_last10_stats_narrow_win_share():
    # A 1-0 win is a "narrow win" (margin 1, total goals <= 3); a 3-2 win is not narrow enough by margin.
    results = [_result(result="W", scoreline="1-0", margin=1), _result(result="W", scoreline="3-2", margin=1)]
    stats = _compute_last10_stats(results)
    assert stats.narrow_win_share_pct == 50


def test_last10_stats_btts_and_over_lines():
    results = [_result(scoreline="2-2"), _result(scoreline="0-0")]
    stats = _compute_last10_stats(results)
    assert stats.btts_share_pct == 50
    # 2-2 = 4 total goals: over both the 1.5 and 3.5 lines; 0-0 is over neither.
    assert stats.over15_share_pct == 50
    assert stats.over35_share_pct == 50


def test_last10_stats_empty_without_results():
    stats = _compute_last10_stats([])
    assert stats.win_rate_pct is None
    assert stats.points_per_game is None


# --- all_form_results -------------------------------------------------------------


def test_all_form_results_reaches_further_back_than_compute_form_summary_slices():
    now = datetime.now(tz=UTC)
    # 21 competitive wins followed by an older meeting against a specific
    # opponent -- outside last20_overall's window, but still real history.
    played = [
        _match(home_team="Home FC", away_team=f"Filler{i}", home_score=1, away_score=0, kickoff_utc=(now - timedelta(days=i)).isoformat())
        for i in range(21)
    ]
    played.append(_match(home_team="Home FC", away_team="Old Rival", home_score=2, away_score=2, kickoff_utc=(now - timedelta(days=400)).isoformat()))
    results = all_form_results("Home FC", played)
    summary = compute_form_summary("Home FC", played)
    assert any(r.opponent == "Old Rival" for r in results)
    assert not any(r.opponent == "Old Rival" for r in summary.last20_overall)


def test_all_form_results_includes_friendlies_unlike_compute_form_summary():
    now = datetime.now(tz=UTC)
    played = [_match(home_team="Home FC", away_team="Friendly Opp", home_score=1, away_score=1, competition="Club Friendly Games", kickoff_utc=(now - timedelta(days=1)).isoformat())]
    results = all_form_results("Home FC", played)
    assert len(results) == 1
    assert results[0].opponent == "Friendly Opp"


def test_all_form_results_sorted_most_recent_first():
    now = datetime.now(tz=UTC)
    played = [
        _match(home_team="Home FC", away_team="Older", home_score=1, away_score=0, kickoff_utc=(now - timedelta(days=10)).isoformat()),
        _match(home_team="Home FC", away_team="Newer", home_score=2, away_score=0, kickoff_utc=(now - timedelta(days=1)).isoformat()),
    ]
    results = all_form_results("Home FC", played)
    assert [r.opponent for r in results] == ["Newer", "Older"]


def test_all_form_results_empty_without_matches():
    assert all_form_results("Home FC", []) == []


# --- compute_form_summary (integration) -------------------------------------------


def test_compute_form_summary_end_to_end():
    now = datetime.now(tz=UTC)
    played = [
        _match(home_team="Home FC", away_team="Opp1", home_score=2, away_score=0, kickoff_utc=(now - timedelta(days=3)).isoformat()),
        _match(home_team="Opp2", away_team="Home FC", home_score=1, away_score=1, kickoff_utc=(now - timedelta(days=10)).isoformat()),
    ]
    summary = compute_form_summary("Home FC", played)
    assert len(summary.last5_overall) == 2
    assert summary.last5_overall[0].opponent == "Opp1"  # sorted most-recent first
    assert summary.current_streak.result == "W"
    assert summary.recent_competitions == ["Premier League"]


def test_compute_form_summary_with_no_matches():
    summary = compute_form_summary("Home FC", [])
    assert summary.last5_overall == []
    assert summary.current_streak is None
    assert summary.momentum is None


def test_compute_form_summary_excludes_friendlies_from_form_but_not_scheduling():
    now = datetime.now(tz=UTC)
    played = [
        # Most recent, but a friendly loss -- should NOT count toward form.
        _match(home_team="Home FC", away_team="Opp1", home_score=0, away_score=2, competition="Club Friendly Games", kickoff_utc=(now - timedelta(days=1)).isoformat()),
        # Older, a competitive win -- should be the only match form reflects.
        _match(home_team="Home FC", away_team="Opp2", home_score=2, away_score=0, competition="Premier League", kickoff_utc=(now - timedelta(days=3)).isoformat()),
    ]
    summary = compute_form_summary("Home FC", played)
    assert len(summary.last5_overall) == 1
    assert summary.last5_overall[0].opponent == "Opp2"
    assert summary.current_streak.result == "W"
    assert summary.win_rate_pct == 100.0
    # Scheduling/fitness stats still count the friendly.
    assert summary.matches_last7_days == 2


def test_compute_form_summary_falls_back_to_friendlies_when_thats_all_there_is():
    now = datetime.now(tz=UTC)
    played = [
        _match(home_team="Home FC", away_team="Opp1", home_score=2, away_score=0, competition="Club Friendly Games", kickoff_utc=(now - timedelta(days=1)).isoformat()),
    ]
    summary = compute_form_summary("Home FC", played)
    assert len(summary.last5_overall) == 1  # falls back rather than going empty


# --- parse_leading_int / parse_leading_float / stat_for / stat_for_float ---------


def test_parse_leading_int_handles_plain_and_percentage_suffix():
    assert parse_leading_int("3") == 3
    assert parse_leading_int("21 (58%)") == 21


def test_parse_leading_int_none_for_empty_or_unparseable():
    assert parse_leading_int("") is None
    assert parse_leading_int(None) is None
    assert parse_leading_int("N/A") is None


def test_parse_leading_float_preserves_decimals():
    assert parse_leading_float("1.19") == 1.19


def test_parse_leading_float_none_for_empty():
    assert parse_leading_float(None) is None


def test_stat_for_reads_own_venue_value():
    stats = [MatchStatItem(name="Total shots", home="12", away="8")]
    assert stat_for(stats, "Total shots", "home") == 12
    assert stat_for(stats, "Total shots", "away") == 8


def test_stat_for_none_when_stat_missing():
    assert stat_for([], "Total shots", "home") is None
    assert stat_for(None, "Total shots", "home") is None


def test_stat_for_float_none_when_stat_missing():
    assert stat_for_float([], "Expected goals (xG)", "home") is None
    assert stat_for_float(None, "Expected goals (xG)", "home") is None


# --- _compute_venue_split_form away-side bucket -----------------------------------------


def test_compute_venue_split_form_away_bucket():
    from football.form import _compute_venue_split_form

    away_result = _result(scoreline="1-2", venue="away", neutral_venue=False, result="W")
    home_result = _result(scoreline="2-1", venue="home", neutral_venue=False, result="W")
    split = _compute_venue_split_form([home_result, away_result])
    assert split.away_sample_size == 1
    assert split.away_wins == 1


# --- _process_one_result / enrich_form_with_venue_classification (async) -----------------


def _match_details_for_enrichment(**overrides):
    from football.types import (
        MatchDetails,
        MatchStatItem,
        SetPieceGoalCounts,
        SetPieceGoals,
        ShotmapSideStats,
        ShotmapStats,
    )

    match_stats = [
        MatchStatItem(name="Expected goals", home="1.8", away="0.9"),
        MatchStatItem(name="Total shots", home="15", away="10"),
        MatchStatItem(name="Shots on target", home="6", away="3"),
        MatchStatItem(name="Ball possession", home="55", away="45"),
        MatchStatItem(name="Corner kicks", home="7", away="4"),
        MatchStatItem(name="Fouls", home="9", away="11"),
        MatchStatItem(name="Yellow cards", home="2", away="3"),
        MatchStatItem(name="Red cards", home="0", away="0"),
        MatchStatItem(name="Big chances", home="3", away="1"),
        MatchStatItem(name="Touches in penalty area", home="20", away="12"),
    ]
    base = {
        "source": "sofascore", "source_url": "https://x", "competition": "Premier League",
        "home_team": "Home FC", "away_team": "Away FC", "kickoff_utc": "2026-01-01T15:00:00.000Z",
        "venue": None, "venue_lat": None, "venue_lon": None, "status": "finished",
        "home_score": 2, "away_score": 1, "home_score_ht": 1, "away_score_ht": 0,
        "season": None, "round": None, "match_id": "1", "venue_name": None, "venue_city": None,
        "venue_country": "England", "home_team_country": "England", "away_team_country": "Spain",
        "referee": None, "referee_stats": None, "attendance": None, "weather": None, "weather_detail": None,
        "head_to_head_summary": None, "head_to_head_streaks": None, "recent_meetings": None,
        "home_lineup": [_lineup_player(name="Home P1", xa=0.3)], "away_lineup": [_lineup_player(name="Away P1", xa=0.1)],
        "home_bench": [], "away_bench": [],
        "home_team_standing": None, "away_team_standing": None, "home_team_season_stats": None, "away_team_season_stats": None,
        "match_stats": match_stats, "event_timeline": None,
        "set_piece_goals": SetPieceGoals(home=SetPieceGoalCounts(corner=1, penalty=0, free_kick=0), away=SetPieceGoalCounts(corner=0, penalty=1, free_kick=0)),
        "shotmap_stats": ShotmapStats(home=ShotmapSideStats(non_penalty_xg=1.5, set_piece_xg=0.3, penalties_awarded=1), away=ShotmapSideStats(non_penalty_xg=0.7, set_piece_xg=0.2, penalties_awarded=0)),
        "player_of_the_match": None, "home_formation": None, "away_formation": None, "lineup_confirmed": None,
        "home_manager": None, "away_manager": None, "home_manager_vs_away_club": None, "away_manager_vs_home_club": None,
        "standings_table": None, "home_suspended_players": None, "away_suspended_players": None, "note": None,
    }
    base.update(overrides)
    return MatchDetails(**base)


def test_enrich_form_with_venue_classification_success_path(monkeypatch):
    from football import orchestrate

    raw_match = _match(home_team="Home FC", away_team="Away FC", kickoff_utc="2026-01-01T15:00:00.000Z")
    details = _match_details_for_enrichment()

    async def fake_details(_match_info):
        return details

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(fake_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    result = _result(opponent="Away FC", date="2026-01-01T15:00:00.000Z", venue="home", scoreline="2-1", result="W")
    form = _form_summary_for_enrichment(last20_overall=[result])

    enriched = asyncio.run(enrich_form_with_venue_classification([raw_match], form, "sofascore"))
    # result.venue="home" -> own_country=details.home_team_country="England", which
    # matches details.venue_country="England" -- a real (non-neutral) home fixture.
    assert enriched.form.last20_overall[0].neutral_venue is False
    assert enriched.form.last20_overall[0].ht_scoreline == "1-0"
    assert enriched.advanced_stats is not None
    assert "home p1" in enriched.usage_by_player


def test_enrich_form_with_venue_classification_falls_back_when_no_raw_match_found():
    from football.form import VenueEnrichmentResult

    result = _result(opponent="Unmatched Opp", date="2099-01-01T00:00:00.000Z")
    form = _form_summary_for_enrichment(last20_overall=[result])

    enriched = asyncio.run(enrich_form_with_venue_classification([], form, "sofascore"))
    assert enriched.form.last20_overall[0] is result
    assert isinstance(enriched, VenueEnrichmentResult)


def test_enrich_form_with_venue_classification_none_ht_scoreline_without_ht_data(monkeypatch):
    from football import orchestrate

    raw_match = _match(home_team="Home FC", away_team="Away FC", kickoff_utc="2026-01-01T15:00:00.000Z")
    details = _match_details_for_enrichment(home_score_ht=None, away_score_ht=None)

    async def fake_details(_match_info):
        return details

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(fake_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    result = _result(opponent="Away FC", date="2026-01-01T15:00:00.000Z", venue="home")
    form = _form_summary_for_enrichment(last20_overall=[result])

    enriched = asyncio.run(enrich_form_with_venue_classification([raw_match], form, "sofascore"))
    assert enriched.form.last20_overall[0].ht_scoreline is None


def test_enrich_form_with_venue_classification_falls_back_on_details_failure(monkeypatch):
    from football import orchestrate

    raw_match = _match(home_team="Home FC", away_team="Away FC", kickoff_utc="2026-01-01T15:00:00.000Z")

    async def failing_details(_match_info):
        raise RuntimeError("blocked")

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(failing_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    result = _result(opponent="Away FC", date="2026-01-01T15:00:00.000Z", venue="home")
    form = _form_summary_for_enrichment(last20_overall=[result])

    enriched = asyncio.run(enrich_form_with_venue_classification([raw_match], form, "sofascore"))
    assert enriched.form.last20_overall[0] is result


def test_enrich_form_with_venue_classification_also_reenriches_last5_and_last10_overall(monkeypatch):
    """Regression test for a real bug: last5_overall/last10_overall/
    last5_home/last5_away are separate list slices taken from
    all_results in compute_form_summary, BEFORE this function runs --
    only last20_overall was ever re-pointed at the enriched results,
    so every one of these other windows kept serving the original,
    unenriched FormResult objects (ht_scoreline/xg_for/xg_against
    always None) even for a match that WAS successfully enriched."""
    from football import orchestrate

    raw_match = _match(home_team="Home FC", away_team="Away FC", kickoff_utc="2026-01-01T15:00:00.000Z")
    details = _match_details_for_enrichment()

    async def fake_details(_match_info):
        return details

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(fake_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    # Same match (identified by date+opponent), appearing -- as it
    # genuinely would -- in last5_overall, last10_overall, last20_overall,
    # and last5_home all at once, since they're overlapping windows over
    # the same match history.
    result = _result(opponent="Away FC", date="2026-01-01T15:00:00.000Z", venue="home", scoreline="2-1", result="W")
    form = _form_summary_for_enrichment(
        last5_overall=[result], last10_overall=[result], last20_overall=[result], last5_home=[result], last5_away=[],
    )

    enriched = asyncio.run(enrich_form_with_venue_classification([raw_match], form, "sofascore"))

    for window in (enriched.form.last5_overall, enriched.form.last10_overall, enriched.form.last20_overall, enriched.form.last5_home):
        assert window[0].ht_scoreline == "1-0"
        assert window[0].xg_for == 1.8
        assert window[0].xg_against == 0.9


def test_enrich_form_with_venue_classification_leaves_out_of_window_entries_alone(monkeypatch):
    """An entry in last5_home/last5_away that falls outside the bounded
    last20_overall enrichment scan (e.g. a team's 5 most recent home
    games reach further back than its last 20 overall) has no enriched
    counterpart to match against -- it must stay exactly as it was,
    not be dropped or crash the lookup."""
    from football import orchestrate

    raw_match = _match(home_team="Home FC", away_team="Away FC", kickoff_utc="2026-01-01T15:00:00.000Z")
    details = _match_details_for_enrichment()

    async def fake_details(_match_info):
        return details

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(fake_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    in_window = _result(opponent="Away FC", date="2026-01-01T15:00:00.000Z", venue="home")
    out_of_window = _result(opponent="Older Opp", date="2020-01-01T00:00:00.000Z", venue="home")
    form = _form_summary_for_enrichment(last20_overall=[in_window], last5_home=[out_of_window])

    enriched = asyncio.run(enrich_form_with_venue_classification([raw_match], form, "sofascore"))
    assert enriched.form.last5_home[0] is out_of_window


def test_sofascore_form_enrichment_fetches_only_the_recent_detail_budget(monkeypatch):
    """One details() call is a browser session + ~15 paced API endpoints.
    A 20-match loop for both teams was ~600 Sofascore requests and got
    clients blocked -- only the first FORM_ENRICH_DETAIL_LIMIT of
    last20_overall may cost a details() fetch when source is sofascore."""
    from football import orchestrate
    from football.form import FORM_ENRICH_DETAIL_LIMIT

    raw_matches = [
        _match(home_team="Home FC", away_team=f"Opp{i}", kickoff_utc=f"2026-01-{i:02d}T15:00:00.000Z")
        for i in range(1, 21)
    ]
    details = _match_details_for_enrichment()
    calls: list[str] = []

    async def counting_details(match_info):
        calls.append(match_info.away_team)
        return details

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(counting_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    results = [
        _result(opponent=f"Opp{i}", date=f"2026-01-{i:02d}T15:00:00.000Z", venue="home")
        for i in range(1, 21)
    ]
    form = _form_summary_for_enrichment(last20_overall=results)

    enriched = asyncio.run(enrich_form_with_venue_classification(raw_matches, form, "sofascore"))
    assert len(calls) == FORM_ENRICH_DETAIL_LIMIT
    assert len(enriched.form.last20_overall) == 20


def test_plain_http_sources_still_enrich_the_full_last20_window(monkeypatch):
    """The request-budget cap is Sofascore-only: goal/soccerdesk details()
    is a single small HTTP request, not a browser session."""
    from football import orchestrate
    from football.form import FORM_ENRICH_DETAIL_LIMIT

    raw_matches = [
        _match(home_team="Home FC", away_team=f"Opp{i}", kickoff_utc=f"2026-01-{i:02d}T15:00:00.000Z")
        for i in range(1, 21)
    ]
    details = _match_details_for_enrichment()
    calls: list[str] = []

    async def counting_details(match_info):
        calls.append(match_info.away_team)
        return details

    fake_scrapers = {"goal": type("G", (), {"details": staticmethod(counting_details)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    results = [
        _result(opponent=f"Opp{i}", date=f"2026-01-{i:02d}T15:00:00.000Z", venue="home")
        for i in range(1, 21)
    ]
    form = _form_summary_for_enrichment(last20_overall=results)

    enriched = asyncio.run(enrich_form_with_venue_classification(raw_matches, form, "goal"))
    assert len(calls) == 20
    assert len(calls) > FORM_ENRICH_DETAIL_LIMIT
    assert len(enriched.form.last20_overall) == 20


def test_sofascore_form_enrichment_stops_calling_details_once_the_breaker_trips(monkeypatch):
    """After the first block, remaining last-20 entries must not each
    open another browser session (the pre-fix path kept launching until
    the window was exhausted)."""
    from football import orchestrate
    from football.sites import sofascore

    raw_matches = [
        _match(home_team="Home FC", away_team=f"Opp{i}", kickoff_utc=f"2026-01-{i:02d}T15:00:00.000Z")
        for i in range(1, 8)
    ]
    details = _match_details_for_enrichment()
    calls: list[str] = []

    async def details_then_block(match_info):
        calls.append(match_info.away_team)
        if len(calls) == 1:
            sofascore._block_reason = "HTTP 403 Forbidden"
            return details
        raise AssertionError("details() must not be called after the breaker trips")

    fake_scrapers = {"sofascore": type("S", (), {"details": staticmethod(details_then_block)})()}
    monkeypatch.setattr(orchestrate, "SCRAPERS", fake_scrapers)

    results = [
        _result(opponent=f"Opp{i}", date=f"2026-01-{i:02d}T15:00:00.000Z", venue="home")
        for i in range(1, 8)
    ]
    form = _form_summary_for_enrichment(last20_overall=results)

    enriched = asyncio.run(enrich_form_with_venue_classification(raw_matches, form, "sofascore"))
    assert len(calls) == 1
    assert len(enriched.form.last20_overall) == 7
    assert enriched.form.last20_overall[0].ht_scoreline == "1-0"
    assert enriched.form.last20_overall[1] is results[1]


def _form_summary_for_enrichment(**overrides):
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


def test_stat_for_float_reads_decimal_value():
    stats = [MatchStatItem(name="Expected goals (xG)", home="1.42", away="0.88")]
    assert stat_for_float(stats, "Expected goals (xG)", "home") == 1.42


# --- _tally_player_stats / _tally_usage --------------------------------------


def _lineup_player(**overrides):
    from football.types import LineupPlayer

    base = {"name": "Player X", "substitute": False, "minutes_played": 90}
    base.update(overrides)
    return _all_none(LineupPlayer, **base)


def test_tally_player_stats_sums_onto_accumulator():
    from football.form import _UsageAccumulator

    entry = _UsageAccumulator()
    p = _lineup_player(goals=2, assists=1, xg=1.5, rating=7.5)
    _tally_player_stats(entry, p)
    assert entry.total_goals == 2
    assert entry.total_assists == 1
    assert entry.total_xg == 1.5
    assert entry.rating_sum == 7.5
    assert entry.appearances_with_stats == 1


def test_tally_player_stats_treats_none_fields_as_zero():
    from football.form import _UsageAccumulator

    entry = _UsageAccumulator()
    _tally_player_stats(entry, _lineup_player(goals=None, assists=None))
    assert entry.total_goals == 0
    assert entry.appearances_with_stats == 0  # rating is None, not counted


def test_tally_usage_counts_starts_and_bench():
    from football.form import _tally_usage
    from football.merge import normalize_team_name

    usage: dict = {}
    lineup = [_lineup_player(name="Starter", minutes_played=90)]
    bench = [_lineup_player(name="Used Sub", minutes_played=15), _lineup_player(name="Unused Sub", minutes_played=None)]
    _tally_usage(usage, lineup, bench)
    starter = usage[normalize_team_name("Starter")]
    assert starter.starts == 1
    assert starter.total_minutes == 90
    used_sub = usage[normalize_team_name("Used Sub")]
    assert used_sub.sub_appearances == 1
    unused_sub = usage[normalize_team_name("Unused Sub")]
    assert unused_sub.unused_bench == 1
    assert unused_sub.total_minutes == 0


# --- _sum_xa -------------------------------------------------------------------


def test_sum_xa_combines_lineup_and_bench():
    lineup = [_lineup_player(xa=0.3), _lineup_player(xa=0.2)]
    bench = [_lineup_player(xa=None)]
    assert _sum_xa(lineup, bench) == pytest.approx(0.5)


def test_sum_xa_empty_without_players():
    assert _sum_xa(None, None) == 0


# --- _compute_venue_split_form / _finalize_venue_bucket / _compute_detailed_venue_split --


def test_venue_split_form_buckets_by_neutral_flag():
    from football.form import _compute_venue_split_form

    home_result = _result(venue="home", neutral_venue=False, result="W", scoreline="2-0")
    neutral_result = _result(venue="home", neutral_venue=True, result="D", scoreline="1-1")
    split = _compute_venue_split_form([home_result, neutral_result])
    assert split.home_sample_size == 1
    assert split.home_wins == 1
    assert split.neutral_sample_size == 1
    assert split.neutral_draws == 1


def test_venue_split_form_none_when_no_result_has_neutral_flag_set():
    from football.form import _compute_venue_split_form

    assert _compute_venue_split_form([_result(neutral_venue=None)]) is None


def test_finalize_venue_bucket_averages_possession():
    from football.form import _empty_venue_bucket, _finalize_venue_bucket

    bucket = _empty_venue_bucket()
    bucket["sample_size"] = 2
    bucket["possession_sum"] = 110
    bucket["possession_n"] = 2
    stats = _finalize_venue_bucket(bucket)
    assert stats.sample_size == 2
    assert stats.possession_pct_avg == 55.0


def test_compute_detailed_venue_split_none_when_all_buckets_empty():
    from football.form import _compute_detailed_venue_split, _empty_venue_bucket

    buckets = {"home": _empty_venue_bucket(), "away": _empty_venue_bucket(), "neutral": _empty_venue_bucket()}
    assert _compute_detailed_venue_split(buckets) is None


def test_compute_detailed_venue_split_real_when_any_bucket_populated():
    from football.form import _compute_detailed_venue_split, _empty_venue_bucket

    home = _empty_venue_bucket()
    home["sample_size"] = 3
    buckets = {"home": home, "away": _empty_venue_bucket(), "neutral": _empty_venue_bucket()}
    result = _compute_detailed_venue_split(buckets)
    assert result.home.sample_size == 3


# --- _per90 / _finalize_usage --------------------------------------------------


def test_per90_scales_to_a_90_minute_rate():
    from football.form import _per90

    assert _per90(9, 810) == 1.0  # 9 goals over 810 minutes = 1 per 90


def test_per90_none_without_minutes():
    from football.form import _per90

    assert _per90(5, 0) is None


def test_finalize_usage_computes_averages_and_per90_rates():
    from football.form import _finalize_usage, _UsageAccumulator

    entry = _UsageAccumulator()
    entry.matches_in_squad = 2
    entry.starts = 2
    entry.total_minutes = 180
    entry.total_goals = 2
    entry.rating_sum = 14.0
    entry.appearances_with_stats = 2
    finalized = _finalize_usage({"player x": entry})
    pattern = finalized["player x"]
    assert pattern.avg_rating == 7.0
    assert pattern.goals_per_90 == 1.0


# --- stat-name synonyms / distance-unit fix / big-chances-scored derivation ----------------


def test_stat_for_any_falls_back_to_a_later_source_synonym():
    from football.form import _stat_for_any
    from football.types import MatchStatItem

    stats = [MatchStatItem(name="Tackles", home="16", away="15")]  # Fotmob's own label, not Sofascore's "Total tackles"
    assert _stat_for_any(stats, ("Total tackles", "Tackles"), "home") == 16
    assert _stat_for_any(stats, ("Total tackles", "Tackles"), "away") == 15
    assert _stat_for_any(stats, ("Total tackles",), "home") is None  # no synonym listed -> genuinely absent


def test_stat_for_any_prefers_the_first_matching_name():
    from football.form import _stat_for_any
    from football.types import MatchStatItem

    stats = [MatchStatItem(name="Total tackles", home="10", away="9"), MatchStatItem(name="Tackles", home="99", away="99")]
    assert _stat_for_any(stats, ("Total tackles", "Tackles"), "home") == 10


def test_km_from_distance_stat_converts_a_meters_scale_value_but_leaves_km_alone():
    from football.form import _km_from_distance_stat

    assert _km_from_distance_stat(118485) == 118  # Fotmob: meters, confirmed live
    assert _km_from_distance_stat(108) == 108  # Sofascore: already km
    assert _km_from_distance_stat(None) is None
    assert _km_from_distance_stat(200) == 200  # exactly at the plausible-max boundary


def test_big_chances_scored_derives_from_big_chances_minus_missed():
    from football.form import _big_chances_scored
    from football.types import MatchStatItem

    stats = [MatchStatItem(name="Big chances", home="3", away="1"), MatchStatItem(name="Big chances missed", home="1", away="1")]
    assert _big_chances_scored(stats, "home") == 2
    assert _big_chances_scored(stats, "away") == 0
    assert _big_chances_scored([MatchStatItem(name="Big chances", home="3", away="1")], "home") is None  # missing half the pair


def test_accumulate_stat_totals_reads_fotmob_labels_and_fixes_distance_units():
    from football.form import ADVANCED_STAT_NAMES, _accumulate_stat_totals
    from football.types import MatchStatItem

    fotmob_shaped = [
        MatchStatItem(name="Tackles", home="16", away="15"),
        MatchStatItem(name="Touches in opposition box", home="11", away="10"),
        MatchStatItem(name="Corners", home="8", away="4"),
        MatchStatItem(name="Fouls committed", home="9", away="11"),
        MatchStatItem(name="Distance covered", home="118485", away="116595"),
        MatchStatItem(name="Interceptions", home="10", away="9"),
        MatchStatItem(name="Big chances", home="3", away="1"),
        MatchStatItem(name="Big chances missed", home="1", away="1"),
    ]
    details = _match_details_for_enrichment(match_stats=fotmob_shaped)
    result = _result(venue="home")
    stat_totals = {key: {"for": 0, "against": 0, "n": 0} for key in ADVANCED_STAT_NAMES}
    _accumulate_stat_totals(stat_totals, details, result, "away")

    assert stat_totals["team_tackles"] == {"for": 16, "against": 15, "n": 1}
    assert stat_totals["touches_in_box"] == {"for": 11, "against": 10, "n": 1}
    assert stat_totals["corner_kicks"] == {"for": 8, "against": 4, "n": 1}
    assert stat_totals["fouls"] == {"for": 9, "against": 11, "n": 1}
    assert stat_totals["distance_covered_km"] == {"for": 118, "against": 117, "n": 1}  # not 118485/116595
    assert stat_totals["big_chances_scored"] == {"for": 2, "against": 0, "n": 1}
    assert stat_totals["through_balls"] == {"for": 0, "against": 0, "n": 0}  # genuinely absent from Fotmob


def test_compute_advanced_stats_names_the_stats_this_sources_sample_never_reported():
    from football.form import (
        ADVANCED_STAT_NAMES,
        _compute_advanced_stats,
        _SetPieceAccumulator,
    )

    stat_totals = {key: {"for": 1, "against": 1, "n": 3} for key in ADVANCED_STAT_NAMES}
    stat_totals["through_balls"] = {"for": 0, "against": 0, "n": 0}
    stat_totals["recoveries"] = {"for": 0, "against": 0, "n": 0}
    estimate = _compute_advanced_stats(stat_totals, _SetPieceAccumulator(), "fotmob")
    assert estimate.unavailable_stats == ["recoveries", "through_balls"]
    assert estimate.through_balls_for is None  # null, not a fabricated 0
    assert estimate.through_balls_against is None
    assert estimate.recoveries_for is None
    assert estimate.touches_in_box_for == 1  # available stats keep real values


def test_compute_advanced_stats_nulls_red_cards_pair_when_source_never_reported_them():
    from football.form import ADVANCED_STAT_NAMES, _compute_advanced_stats, _SetPieceAccumulator
    from dataclasses import asdict

    stat_totals = {k: {"n": 5, "for": 2.0, "against": 1.0} for k in ADVANCED_STAT_NAMES}
    stat_totals["red_cards"] = {"n": 0, "for": 0.0, "against": 0.0}
    estimate = _compute_advanced_stats(stat_totals, _SetPieceAccumulator(), "sofascore")
    assert estimate is not None
    assert estimate.unavailable_stats == ["red_cards"]
    assert estimate.red_cards_for is None
    assert estimate.red_cards_against is None
    assert estimate.yellow_cards_for == 2
    # acc-derived fields stay a real 0, never null
    d = asdict(estimate)
    assert d["red_cards_for"] is None
    assert d["xa_for"] == 0.0
    assert d["penalties_awarded_for"] == 0


def test_compute_advanced_stats_unavailable_stats_none_when_every_stat_had_data():
    from football.form import (
        ADVANCED_STAT_NAMES,
        _compute_advanced_stats,
        _SetPieceAccumulator,
    )

    stat_totals = {key: {"for": 1, "against": 1, "n": 3} for key in ADVANCED_STAT_NAMES}
    assert _compute_advanced_stats(stat_totals, _SetPieceAccumulator(), "sofascore").unavailable_stats is None


# --- _compute_advanced_stats -----------------------------------------------------


def test_compute_advanced_stats_builds_estimate_from_full_stat_totals():
    from football.form import (
        ADVANCED_STAT_NAMES,
        _compute_advanced_stats,
        _SetPieceAccumulator,
    )

    stat_totals = {key: {"for": 1, "against": 1, "n": 3} for key in ADVANCED_STAT_NAMES}
    acc = _SetPieceAccumulator()
    estimate = _compute_advanced_stats(stat_totals, acc, "sofascore")
    assert estimate.sample_size == 3
    assert estimate.touches_in_box_for == 1
    assert estimate.source == "sofascore"


def test_compute_advanced_stats_none_without_any_sample():
    from football.form import (
        ADVANCED_STAT_NAMES,
        _compute_advanced_stats,
        _SetPieceAccumulator,
    )

    stat_totals = {key: {"for": 0, "against": 0, "n": 0} for key in ADVANCED_STAT_NAMES}
    assert _compute_advanced_stats(stat_totals, _SetPieceAccumulator(), "sofascore") is None


def _played_series(count, competition="Premier League", start_day=1):
    now = datetime.now(tz=UTC)
    return [
        _match(home_team="Home FC", away_team=f"Opp{i}", home_score=1, away_score=0, home_score_ht=1, away_score_ht=0, competition=competition,
               kickoff_utc=(now - timedelta(days=start_day + i)).isoformat())
        for i in range(count)
    ]


def test_windowed_breakdowns_all_use_the_same_last_20_competitive_matches():
    summary = compute_form_summary("Home FC", _played_series(25))
    assert len(summary.last20_overall) == 20
    assert sum(r.played for r in summary.form_by_competition) == 20
    assert summary.half_split.sample_size == 20


def test_recent_competitions_excludes_friendlies_like_form_by_competition():
    friendlies = _played_series(3, competition="Club Friendly Games", start_day=1)
    league = _played_series(3, competition="UEFA Champions League", start_day=10)
    summary = compute_form_summary("Home FC", friendlies + league)
    assert summary.recent_competitions == ["UEFA Champions League"]
    assert [r.competition for r in summary.form_by_competition] == ["UEFA Champions League"]


def test_recent_competitions_uses_the_same_window_as_form_by_competition():
    # Confirmed live: recent_competitions used a 10-match window while
    # form_by_competition used 20, so a competition (a Champions League
    # tie) falling between the two was silently missing from one but not
    # the other.
    older_cup_match = _played_series(1, competition="UEFA Champions League", start_day=15)
    recent_league = _played_series(14, competition="Premier League", start_day=1)
    summary = compute_form_summary("Home FC", older_cup_match + recent_league)
    assert "UEFA Champions League" in summary.recent_competitions
    assert "UEFA Champions League" in [r.competition for r in summary.form_by_competition]


def test_recent_competitions_strips_stage_suffixes_to_align_with_form_by_competition():
    staged = _played_series(3, competition="UEFA Champions League, Knockout stage", start_day=1)
    summary = compute_form_summary("Home FC", staged)
    assert summary.recent_competitions == ["UEFA Champions League"]
    assert [r.competition for r in summary.form_by_competition] == ["UEFA Champions League"]


# --- _back_line_slots: real lineups (Sofascore order: GK, back line right-to-left) ---


def _xi(*pairs):
    return [_lineup_player(name=n, position=pos) for n, pos in pairs]


def test_back_line_slots_marks_the_first_and_last_of_a_back_four_as_wide():
    from football.form import _back_line_slots

    man_utd = _xi(("Senne Lammens", "G"), ("Diogo Dalot", "D"), ("Harry Maguire", "D"), ("Lisandro Martinez", "D"), ("Luke Shaw", "D"),
                  ("Casemiro", "M"), ("Kobbie Mainoo", "M"), ("Amad Diallo", "M"), ("Bruno Fernandes", "M"), ("Bryan Mbeumo", "F"), ("Matheus Cunha", "F"))
    slots = {p.name: wide for p, wide in _back_line_slots(man_utd, "4-2-3-1")}
    assert slots == {"Diogo Dalot": True, "Harry Maguire": False, "Lisandro Martinez": False, "Luke Shaw": True}


def test_back_line_slots_counts_a_midfielder_listed_player_playing_right_back_as_wide():
    from football.form import _back_line_slots

    spurs = _xi(("Guglielmo Vicario", "G"), ("Archie Gray", "M"), ("Cristian Romero", "D"), ("Micky van de Ven", "D"), ("Destiny Udogie", "D"),
                ("Conor Gallagher", "M"), ("Joao Palhinha", "M"), ("Pape Matar Sarr", "M"), ("Wilson Odobert", "F"), ("Dominic Solanke", "F"), ("Xavi Simons", "M"))
    slots = {p.name: wide for p, wide in _back_line_slots(spurs, "4-3-3")}
    assert slots["Archie Gray"] is True
    assert slots["Destiny Udogie"] is True
    assert slots["Cristian Romero"] is False


def test_back_line_slots_three_at_the_back_is_all_central_and_five_has_wing_backs():
    from football.form import _back_line_slots

    three = _xi(("GK", "G"), ("A", "D"), ("B", "D"), ("C", "D"), ("M1", "M"), ("M2", "M"), ("M3", "M"), ("M4", "M"), ("F1", "F"), ("F2", "F"), ("F3", "F"))
    assert [w for _, w in _back_line_slots(three, "3-4-3")] == [False, False, False]
    five = _xi(("GK", "G"), ("A", "D"), ("B", "D"), ("C", "D"), ("D", "D"), ("E", "D"), ("M1", "M"), ("M2", "M"), ("M3", "M"), ("F1", "F"), ("F2", "F"))
    assert [w for _, w in _back_line_slots(five, "5-3-2")] == [True, False, False, False, True]


def test_back_line_slots_empty_when_the_shape_cannot_be_trusted():
    from football.form import _back_line_slots

    xi = _xi(("GK", "G"), ("A", "D"), ("B", "D"), ("C", "D"), ("D", "D"))
    assert _back_line_slots(None, "4-4-2") == []
    assert _back_line_slots(xi, None) == []
    assert _back_line_slots(xi, "not-a-formation") == []
    assert _back_line_slots(_xi(("A", "D"), ("B", "D")), "4-4-2") == []  # first player isn't a keeper
    assert _back_line_slots(xi[:3], "4-4-2") == []  # lineup shorter than the back line


def test_tally_usage_records_wide_and_central_back_starts_across_matches():
    from football.form import _tally_usage
    from football.merge import normalize_team_name

    usage: dict = {}
    xi = _xi(("GK", "G"), ("Right Back", "D"), ("Centre One", "D"), ("Centre Two", "D"), ("Left Back", "D"),
             ("M1", "M"), ("M2", "M"), ("M3", "M"), ("F1", "F"), ("F2", "F"), ("F3", "F"))
    _tally_usage(usage, xi, [], "4-3-3")
    _tally_usage(usage, xi, [], "4-3-3")
    assert usage[normalize_team_name("Right Back")].wide_back_starts == 2
    assert usage[normalize_team_name("Centre One")].central_back_starts == 2
    assert usage[normalize_team_name("Centre One")].wide_back_starts == 0
    assert usage[normalize_team_name("M1")].wide_back_starts == 0


def test_outcome_rates_always_add_up_to_exactly_100():
    from football.form import _outcome_rates

    def results(w, d, l):
        return [_result(result="W")] * w + [_result(result="D")] * d + [_result(result="L")] * l

    assert _outcome_rates([]) == (None, None, None)
    assert _outcome_rates(results(3, 2, 2)) == (43, 29, 28)  # naive rounding gave 43+29+29 = 101
    assert sum(_outcome_rates(results(1, 1, 1))) == 100  # naive rounding gave 99
    assert _outcome_rates(results(10, 0, 0)) == (100, 0, 0)
    assert _outcome_rates(results(5, 3, 2)) == (50, 30, 20)
    for w in range(0, 11):
        for d in range(0, 11 - w):
            assert sum(_outcome_rates(results(w, d, 10 - w - d))) == 100
