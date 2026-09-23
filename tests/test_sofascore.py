import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from football.sites import sofascore
from football.sites.sofascore import (
    _age_from_timestamp,
    _apply_category_stat,
    _empty_goal_counts,
    _empty_shotmap_side_stats,
    _extract_bench,
    _extract_betting_odds,
    _extract_incidents,
    _extract_lineup,
    _extract_lineup_player,
    _extract_manager,
    _extract_match_stats,
    _extract_missing_players,
    _extract_player_of_the_match,
    _extract_referee_stats,
    _extract_season_stats,
    _extract_set_piece_goals,
    _extract_shotmap_stats,
    _extract_standing,
    _extract_streaks,
    _fetch_manager_club_record,
    _fetch_standings_and_season_stats,
    _fetch_top_player_stats,
    _lineup_note,
    _manager_event_outcome,
    _match_details_note,
    _normalize,
    _standings_table_from,
    _summary_from_duel,
    _to_iso_z,
    _to_match_info,
    get_sofascore_match_details,
    get_sofascore_matches,
    get_sofascore_team_profile,
)


class _FakePage:
    async def goto(self, *_args, **_kwargs):
        return None


def _mock_fetch_json(response: dict, urls_seen: list[str]):
    async def fake(page, url):
        urls_seen.append(url)
        return response

    return fake


def _mock_fetch_json_router(url_map: dict[str, dict], default: dict | None = None):
    """Routes by the first url_map key found as a substring of the
    requested URL -- used for the multi-endpoint orchestrators
    (get_sofascore_match_details/get_sofascore_team_profile), where each
    call targets a different real endpoint path."""
    async def fake(page, url):
        for key, response in url_map.items():
            if key in url:
                return response
        return default

    return fake


class _FakeContext:
    async def new_page(self):
        return _FakePage()


class _FakeBrowser:
    async def new_context(self, **_kwargs):
        return _FakeContext()


class _FakeBrowserCM:
    async def __aenter__(self):
        return _FakeBrowser()

    async def __aexit__(self, *_exc):
        return False


async def _no_sleep(_ms):
    return None


def test_alias_translates_to_canonical_query_in_one_request(monkeypatch):
    # "Nott'm Forest" (football-data.co.uk's short form) returns no team
    # result from Sofascore's own search -- confirmed live -- while the
    # canonical "Nottingham Forest" resolves immediately. The alias
    # translation must still cost exactly one search request.
    urls_seen: list[str] = []
    response = {"results": [{"type": "team", "entity": {"id": 14, "name": "Nottingham Forest", "slug": "nottingham-forest"}}]}
    monkeypatch.setattr(sofascore, "_fetch_json", _mock_fetch_json(response, urls_seen))

    team = asyncio.run(sofascore._find_team(_FakePage(), "Nott'm Forest"))

    assert team is not None
    assert team.name == "Nottingham Forest"
    assert len(urls_seen) == 1
    assert "nottingham" in urls_seen[0].lower()
    assert "forest" in urls_seen[0].lower()


def test_unknown_team_query_is_passed_through_unchanged(monkeypatch):
    urls_seen: list[str] = []
    response = {"results": [{"type": "team", "entity": {"id": 99, "name": "Some Club", "slug": "some-club"}}]}
    monkeypatch.setattr(sofascore, "_fetch_json", _mock_fetch_json(response, urls_seen))

    asyncio.run(sofascore._find_team(_FakePage(), "Some Club"))

    assert len(urls_seen) == 1
    assert "Some%20Club" in urls_seen[0] or "Some+Club" in urls_seen[0]


def test_block_response_raises_with_exactly_one_request(monkeypatch):
    urls_seen: list[str] = []
    response = {"error": {"code": 403, "reason": "Forbidden"}}
    monkeypatch.setattr(sofascore, "_fetch_json", _mock_fetch_json(response, urls_seen))

    coro = sofascore._find_team(_FakePage(), "Nott'm Forest")
    with pytest.raises(ValueError, match="blocked"):
        asyncio.run(coro)

    assert len(urls_seen) == 1


def test_no_results_returns_none_with_exactly_one_request(monkeypatch):
    urls_seen: list[str] = []
    response = {"results": []}
    monkeypatch.setattr(sofascore, "_fetch_json", _mock_fetch_json(response, urls_seen))

    team = asyncio.run(sofascore._find_team(_FakePage(), "Nonexistent FC"))

    assert team is None
    assert len(urls_seen) == 1


# --- _to_iso_z / _normalize -----------------------------------------------------


def test_to_iso_z_always_has_3_digit_millis_and_trailing_z():
    dt = datetime(2026, 3, 1, 15, 30, 0, tzinfo=UTC)
    assert _to_iso_z(dt) == "2026-03-01T15:30:00.000Z"


def test_normalize_strips_diacritics_and_punctuation():
    assert _normalize("Álvarez FC!") == "alvarez fc"


# --- _to_match_info -----------------------------------------------------------------


def _raw_event(**overrides):
    base = {
        "slug": "home-fc-away-fc", "id": 999, "tournament": {"name": "Premier League"},
        "homeTeam": {"name": "Home FC"}, "awayTeam": {"name": "Away FC"},
        "startTimestamp": 1767283800, "status": {"type": "finished"},
        "homeScore": {"current": 2, "period1": 1}, "awayScore": {"current": 1, "period1": 0},
        "season": {"name": "25/26"}, "roundInfo": {"round": 10},
    }
    base.update(overrides)
    return base


def test_to_match_info_extracts_scores_and_ht_scores():
    m = _to_match_info(_raw_event())
    assert m.home_score == 2
    assert m.home_score_ht == 1
    assert m.competition == "Premier League"
    assert m.round == 10


def test_to_match_info_handles_missing_round_and_season():
    m = _to_match_info(_raw_event(season={}, roundInfo={}))
    assert m.season is None
    assert m.round is None


# --- _age_from_timestamp -------------------------------------------------------------


def test_age_from_timestamp_computes_whole_years():
    ts = int((datetime.now(tz=UTC) - timedelta(days=365.25 * 25 + 3)).timestamp())
    assert _age_from_timestamp(ts) == 25


def test_age_from_timestamp_none_without_timestamp():
    assert _age_from_timestamp(None) is None
    assert _age_from_timestamp(0) is None


# --- _extract_lineup_player / _extract_lineup / _extract_bench --------------------------


def _raw_player(**overrides):
    base = {"player": {"name": "Player A", "position": "F"}, "statistics": {"rating": 7.5, "goals": 1}, "shirtNumber": "9", "substitute": False}
    base.update(overrides)
    return base


def test_extract_lineup_player_reads_stats_and_parses_shirt_number():
    p = _extract_lineup_player(_raw_player(), substitute=False)
    assert p.name == "Player A"
    assert p.rating == 7.5
    assert p.shirt_number == 9
    assert p.substitute is False


def test_extract_lineup_filters_to_non_substitutes_only():
    side = {"players": [_raw_player(substitute=False), _raw_player(player={"name": "Sub", "position": "M"}, substitute=True)]}
    lineup = _extract_lineup(side)
    assert len(lineup) == 1
    assert lineup[0].name == "Player A"


def test_extract_bench_filters_to_substitutes_only():
    side = {"players": [_raw_player(substitute=False), _raw_player(player={"name": "Sub", "position": "M"}, substitute=True)]}
    bench = _extract_bench(side)
    assert len(bench) == 1
    assert bench[0].name == "Sub"


def test_extract_bench_none_when_no_substitutes():
    side = {"players": [_raw_player(substitute=False)]}
    assert _extract_bench(side) is None


def test_extract_lineup_none_without_side():
    assert _extract_lineup(None) is None
    assert _extract_lineup({"players": []}) is None


# --- _extract_missing_players ---------------------------------------------------------


def test_extract_missing_players():
    side = {"missingPlayers": [{"player": {"name": "Injured Player"}, "description": "Knee Injury", "expectedEndDate": "2026-03-01"}]}
    missing = _extract_missing_players(side)
    assert missing[0].name == "Injured Player"
    assert missing[0].description == "Knee Injury"


def test_extract_missing_players_none_when_empty():
    assert _extract_missing_players({"missingPlayers": []}) is None
    assert _extract_missing_players(None) is None


def test_extract_suspended_players_filters_by_suspension_absence_type():
    from football.sites.sofascore import _extract_suspended_players

    side = {
        "missingPlayers": [
            {"player": {"name": "Banned Player"}, "description": "Suspension", "expectedEndDate": "2026-03-01"},
            {"player": {"name": "Injured Player"}, "description": "Knee Injury", "expectedEndDate": None},
            {"player": {"name": "Red Carded"}, "description": "red card", "expectedEndDate": None},
        ]
    }
    assert _extract_suspended_players(side) == ["Banned Player", "Red Carded"]


def test_extract_suspended_players_confirmed_empty_vs_absent_key():
    from football.sites.sofascore import _extract_suspended_players

    assert _extract_suspended_players({"missingPlayers": []}) == []
    assert _extract_suspended_players({"missingPlayers": [{"player": {"name": "X"}, "description": "Knee Injury"}]}) == []
    assert _extract_suspended_players({}) is None
    assert _extract_suspended_players(None) is None


# --- _extract_referee_stats / _extract_season_stats / _extract_standing --------------------


def test_extract_referee_stats_computes_yellow_cards_per_game():
    stats = _extract_referee_stats({"games": 20, "yellowCards": 50, "redCards": 2})
    assert stats.yellow_cards_per_game == "2.5"


def test_extract_referee_stats_none_without_games():
    assert _extract_referee_stats({"games": 0}) is None
    assert _extract_referee_stats(None) is None


def test_extract_season_stats():
    stats = _extract_season_stats({"statistics": {"goalsScored": 40, "goalsConceded": 20, "cleanSheets": 10}})
    assert stats.goals_scored == 40
    assert stats.clean_sheets == 10


def test_extract_season_stats_rounds_unrounded_possession_to_one_decimal():
    # Confirmed live: Sofascore can return e.g. 42.666666666667, which
    # leaked into markdown as "42.666666666667% avg possession".
    stats = _extract_season_stats({"statistics": {"averageBallPossession": 42.666666666667}})
    assert stats.average_ball_possession == 42.7


def test_extract_season_stats_preserves_whole_number_possession():
    stats = _extract_season_stats({"statistics": {"averageBallPossession": 59}})
    assert stats.average_ball_possession == 59.0


def test_extract_season_stats_none_without_statistics():
    assert _extract_season_stats(None) is None
    assert _extract_season_stats({}) is None


def test_extract_standing_finds_row_by_team_id():
    rows = [{"team": {"id": 42}, "position": 3, "matches": 20, "wins": 12, "draws": 5, "losses": 3, "points": 41, "scoreDiffFormatted": "+15"}]
    standing = _extract_standing(rows, 42)
    assert standing.position == 3
    assert standing.total_teams == 1


def test_extract_standing_none_when_team_missing():
    assert _extract_standing([], 42) is None


# --- _extract_streaks / _extract_match_stats / _extract_player_of_the_match -----------------


def test_extract_streaks_formats_each_entry():
    streaks = {"head2head": [{"name": "Win streak", "team": "Home FC", "value": "3"}]}
    assert _extract_streaks(streaks) == ["Win streak (Home FC): 3"]


def test_extract_streaks_none_without_head2head():
    assert _extract_streaks(None) is None
    assert _extract_streaks({}) is None


def test_extract_streaks_none_on_live_empty_head2head_list():
    # Confirmed live 2026-09-24 (event 16363879 /team-streaks after the
    # human-like rewrite): payload is {"general": [], "head2head": []} --
    # empty list, not missing key. Must yield honest null, not [].
    assert _extract_streaks({"general": [], "head2head": []}) is None


def test_extract_match_stats_flattens_groups():
    stats = {"statistics": [{"groups": [{"statisticsItems": [{"name": "Possession", "home": "60%", "away": "40%"}]}]}]}
    items = _extract_match_stats(stats)
    assert items[0].name == "Possession"


def test_extract_match_stats_none_without_groups():
    assert _extract_match_stats(None) is None
    assert _extract_match_stats({"statistics": []}) is None


def test_extract_player_of_the_match_picks_higher_rated():
    best = {"bestHomeTeamPlayer": {"player": {"name": "Home Star"}, "value": "8.5"}, "bestAwayTeamPlayer": {"player": {"name": "Away Star"}, "value": "7.2"}}
    potm = _extract_player_of_the_match(best)
    assert potm.name == "Home Star"


def test_extract_player_of_the_match_none_without_candidates():
    assert _extract_player_of_the_match(None) is None
    assert _extract_player_of_the_match({}) is None


# --- _extract_incidents ---------------------------------------------------------------


def test_extract_incidents_filters_period_markers():
    incidents = {"incidents": [
        {"incidentType": "period", "time": 45},
        {"incidentType": "goal", "time": 30, "isHome": True, "player": {"name": "Scorer"}},
    ]}
    events = _extract_incidents(incidents)
    assert len(events) == 1
    assert events[0].team == "home"
    assert events[0].player == "Scorer"


def test_extract_incidents_none_without_real_events():
    assert _extract_incidents({"incidents": [{"incidentType": "period"}]}) is None
    assert _extract_incidents(None) is None


def test_extract_incidents_filters_injury_time_markers():
    # Real bug confirmed live 2026-09-04: injuryTime incidents ("6 minutes
    # added") carry no player/team at all -- {"length": 6, "time": 90,
    # "addedTime": 0, "incidentType": "injuryTime", "reversedPeriodTime": 1}
    # -- and weren't filtered, producing a meaningless timeline entry
    # (minute 90, type "injuryTime", player=None, team=None) in every real
    # match checked.
    incidents = {"incidents": [
        {"length": 6, "time": 90, "addedTime": 0, "incidentType": "injuryTime", "reversedPeriodTime": 1},
        {"incidentType": "goal", "time": 30, "isHome": True, "player": {"name": "Scorer"}},
    ]}
    events = _extract_incidents(incidents)
    assert len(events) == 1
    assert events[0].type == "goal"


# --- _extract_set_piece_goals / _extract_shotmap_stats -----------------------------------


def test_extract_set_piece_goals_classifies_by_situation():
    shotmap = {"shotmap": [
        {"shotType": "goal", "isHome": True, "situation": "corner"},
        {"shotType": "goal", "isHome": False, "situation": "penalty"},
        {"shotType": "save", "isHome": True, "situation": "corner"},  # not a goal -- ignored
    ]}
    result = _extract_set_piece_goals(shotmap)
    assert result.home.corner == 1
    assert result.away.penalty == 1
    assert result.home.free_kick == 0


def test_extract_set_piece_goals_empty_shell_without_shots():
    result = _extract_set_piece_goals(None)
    assert result.home == _empty_goal_counts()


def test_extract_shotmap_stats_splits_penalty_and_non_penalty_xg():
    shotmap = {"shotmap": [
        {"isHome": True, "xg": 0.5, "situation": "regular"},
        {"isHome": True, "xg": 0.8, "situation": "penalty"},
    ]}
    result = _extract_shotmap_stats(shotmap)
    assert result.home.non_penalty_xg == 0.5
    assert result.home.set_piece_xg == 0.8
    assert result.home.penalties_awarded == 1


def test_extract_shotmap_stats_empty_shell_without_shots():
    result = _extract_shotmap_stats(None)
    assert result.home == _empty_shotmap_side_stats()


# --- _extract_manager / _manager_event_outcome ---------------------------------------------


def test_extract_manager():
    manager = _extract_manager({"name": "Coach A", "country": {"name": "England"}})
    assert manager.name == "Coach A"
    assert manager.country == "England"


def test_extract_manager_none_without_name():
    assert _extract_manager(None) is None
    assert _extract_manager({}) is None


def test_manager_event_outcome_win_for_manager():
    ev = {
        "status": {"type": "finished"}, "homeTeam": {"name": "Opponent FC"}, "awayTeam": {"name": "Managers FC"},
        "homeScore": {"current": 1}, "awayScore": {"current": 2},
    }
    assert _manager_event_outcome(ev, "opponent fc") == "win"  # manager's team (away) scored more


def test_manager_event_outcome_none_when_unfinished():
    ev = {"status": {"type": "notstarted"}}
    assert _manager_event_outcome(ev, "opponent fc") is None


def test_manager_event_outcome_none_when_ambiguous():
    ev = {"status": {"type": "finished"}, "homeTeam": {"name": "Opponent FC"}, "awayTeam": {"name": "Opponent FC"}}
    assert _manager_event_outcome(ev, "opponent fc") is None


# --- _summary_from_duel / _standings_table_from / _lineup_note / _match_details_note --------


def test_summary_from_duel():
    summary = _summary_from_duel({"homeWins": 3, "awayWins": 1, "draws": 2})
    assert summary.home_wins == 3


def test_summary_from_live_h2h_payload_shape():
    # Confirmed live 2026-09-24 (event 16363879 /h2h after the human-like
    # rewrite): teamDuel is {"homeWins": 2, "awayWins": 5, "draws": 3};
    # managerDuel is JSON null (not missing, not an error object).
    team = _summary_from_duel({"homeWins": 2, "awayWins": 5, "draws": 3})
    assert (team.home_wins, team.away_wins, team.draws, team.sample_size) == (2, 5, 3, 10)
    assert _summary_from_duel(None) is None  # managerDuel: null


def test_summary_from_duel_none_without_data():
    assert _summary_from_duel(None) is None


def test_standings_table_from():
    rows = [{"team": {"name": "Home FC"}, "position": 1, "points": 50}]
    table = _standings_table_from(rows)
    assert table[0].team_name == "Home FC"


def test_standings_table_from_none_without_rows():
    assert _standings_table_from(None) is None


def test_standings_table_from_reads_actual_sofascore_field_names():
    # Regression: confirmed live against the real API -- Sofascore's
    # standings rows use scoresFor/scoresAgainst/scoreDiffFormatted
    # (the last pre-formatted as a signed string), not goalsFor/
    # goalsAgainst/goalDiff. The wrong keys silently returned None
    # forever, independent of how far into the season the table was.
    rows = [{
        "team": {"name": "Manchester City"}, "position": 1, "points": 15,
        "matches": 5, "wins": 5, "draws": 0, "losses": 0,
        "scoresFor": 13, "scoresAgainst": 5, "scoreDiffFormatted": "+8",
    }]
    table = _standings_table_from(rows)
    assert table[0].goals_for == 13
    assert table[0].goals_against == 5
    assert table[0].goal_difference == 8


def test_standings_table_from_negative_goal_difference():
    rows = [{"team": {"name": "Team"}, "position": 20, "points": 1, "scoreDiffFormatted": "-9"}]
    table = _standings_table_from(rows)
    assert table[0].goal_difference == -9
    assert _standings_table_from([]) is None


def _odds_market(market_id, choices, choice_group=None):
    market = {"marketId": market_id, "choices": [{"name": name, "fractionalValue": frac} for name, frac in choices.items()]}
    if choice_group is not None:
        market["choiceGroup"] = choice_group
    return market


def test_extract_betting_odds_full_time_and_over_under():
    odds = {
        "markets": [
            _odds_market(1, {"1": "91/100", "X": "13/5", "2": "29/10"}),
            _odds_market(9, {"Over": "8/11", "Under": "11/10"}, choice_group="2.5"),
        ]
    }
    result = _extract_betting_odds(odds)
    assert result.home_win_odds == 1.91
    assert result.draw_odds == 3.6
    assert result.away_win_odds == 3.9
    assert result.over_2_5_odds == 1.73
    assert result.under_2_5_odds == 2.1
    assert result.overround_pct > 100.0
    assert result.home_win_implied_pct != result.home_win_fair_pct  # raw vs de-vigged
    assert result.over_under_2_5_overround_pct > 100.0
    assert result.over_2_5_fair_pct + result.under_2_5_fair_pct == 100.0


def test_extract_betting_odds_works_without_over_under_market():
    odds = {"markets": [_odds_market(1, {"1": "1/1", "X": "2/1", "2": "3/1"})]}
    result = _extract_betting_odds(odds)
    assert result.home_win_odds == 2.0
    assert result.over_2_5_odds is None
    assert result.under_2_5_odds is None


def test_extract_betting_odds_none_without_full_time_market():
    odds = {"markets": [_odds_market(9, {"Over": "8/11", "Under": "11/10"}, choice_group="2.5")]}
    assert _extract_betting_odds(odds) is None


def test_extract_betting_odds_none_without_odds_data():
    assert _extract_betting_odds(None) is None
    assert _extract_betting_odds({}) is None


def test_lineup_note_confirmed_vs_predicted_vs_not_published():
    assert _lineup_note({"confirmed": True}) == "lineup confirmed"
    assert _lineup_note({"confirmed": False, "home": {"players": [{"name": "Some Player"}]}}) == "lineup predicted, not yet confirmed"
    assert _lineup_note(None) == "lineup not published yet"


def test_lineup_note_not_published_when_confirmed_false_but_no_players_yet():
    """Regression: confirmed live 20 days before kickoff -- Sofascore
    publishes confirmed=false with home/away keys present but their
    players list genuinely empty ([]), well before any predicted XI
    exists. Previously this said "predicted, not yet confirmed",
    promising a lineup that home_lineup/away_lineup never surfaced."""
    assert _lineup_note({"confirmed": False, "home": {"players": []}, "away": {"players": []}}) == "lineup not published yet"
    assert _lineup_note({"confirmed": False}) == "lineup not published yet"


def test_match_details_note_combines_all_three_gaps():
    note = _match_details_note(None, None, None)
    assert "lineup not published yet" in note
    assert "match statistics not available yet" in note
    assert "no league standings" in note


def test_match_details_note_omits_satisfied_conditions():
    note = _match_details_note({"confirmed": True}, {"some": "stats"}, [{"row": 1}])
    assert note == "lineup confirmed"


# --- _apply_category_stat -----------------------------------------------------------------


def test_apply_category_stat_sets_count_field_with_zero_default():
    from football.types import SeasonPlayerStats

    entry = SeasonPlayerStats(appearances=0, goals=0, assists=0, yellow_cards=0, red_cards=0, rating=None, expected_goals=None)
    _apply_category_stat(entry, "goals", {})  # missing from statistics -- defaults to 0
    assert entry.goals == 0
    _apply_category_stat(entry, "goals", {"goals": 5})
    assert entry.goals == 5


def test_apply_category_stat_rating_has_no_zero_default():
    from football.types import SeasonPlayerStats

    entry = SeasonPlayerStats(appearances=0, goals=0, assists=0, yellow_cards=0, red_cards=0, rating=None, expected_goals=None)
    _apply_category_stat(entry, "rating", {})
    assert entry.rating is None  # not 0 -- rating has no sensible zero default


def test_extract_set_piece_goals_counts_free_kick_situation():
    shotmap = {"shotmap": [{"shotType": "goal", "isHome": True, "situation": "set-piece"}]}
    result = _extract_set_piece_goals(shotmap)
    assert result.home.free_kick == 1


# --- _sleep / _fetch_json / _fetch_json_optional (direct, unmocked) -------------------------


def test_sleep_awaits_the_real_asyncio_sleep():
    from football.sites.sofascore import _sleep

    asyncio.run(_sleep(0))  # just confirms it runs to completion without error


def test_fetch_json_parses_page_body_as_json():
    from football.sites.sofascore import _fetch_json, _FETCH_JSON_JS

    class _RealFetchPage:
        def __init__(self):
            self.goto_calls = []
            self.evaluated_urls = []
            self.scripts = []

        async def goto(self, url, **_kwargs):
            self.goto_calls.append(url)

        async def evaluate(self, _script, arg=None):
            self.scripts.append(_script)
            self.evaluated_urls.append(arg)
            return '{"ok": true}'

    page = _RealFetchPage()
    result = asyncio.run(_fetch_json(page, "https://example.com/api"))
    assert result == {"ok": True}
    # Human-like: same-origin fetch from the page, never navigate to the API URL.
    assert page.goto_calls == []
    assert page.evaluated_urls == ["https://example.com/api"]
    # In-page fetch must be bounded -- an unbounded fetch() pins
    # page.evaluate (no default timeout on desktop Playwright) forever.
    assert page.scripts == [_FETCH_JSON_JS]
    assert "AbortSignal.timeout" in _FETCH_JSON_JS
    assert "goto" not in _FETCH_JSON_JS


def test_fetch_json_optional_none_on_error_payload(monkeypatch):
    from football.sites.sofascore import _fetch_json_optional

    monkeypatch.setattr(sofascore, "_fetch_json", _mock_fetch_json({"error": {"code": 404}}, []))
    result = asyncio.run(_fetch_json_optional(_FakePage(), "https://example.com/api"))
    assert result is None


def test_apply_category_stat_ignores_unknown_category():
    from football.types import SeasonPlayerStats

    entry = SeasonPlayerStats(appearances=0, goals=0, assists=0, yellow_cards=0, red_cards=0, rating=None, expected_goals=None)
    _apply_category_stat(entry, "unknownCategory", {"unknownCategory": 99})
    assert entry.goals == 0  # untouched


# --- _find_team query-override branch ------------------------------------------------------


def test_find_team_uses_query_override_for_known_mismatched_search(monkeypatch):
    # "estrela" resolves to a B/C reserve team on Sofascore's own search
    # (confirmed live) -- the override swaps in "estrela amadora" instead,
    # a branch distinct from both the plain-passthrough and
    # canonical-alias-translation paths already tested above.
    urls_seen: list[str] = []
    response = {"results": [{"type": "team", "entity": {"id": 1, "name": "Estrela Amadora", "slug": "estrela-amadora"}}]}
    monkeypatch.setattr(sofascore, "_fetch_json", _mock_fetch_json(response, urls_seen))
    team = asyncio.run(sofascore._find_team(_FakePage(), "Estrela"))
    assert team is not None
    assert "amadora" in urls_seen[0].lower()


# --- _extract_bench --------------------------------------------------------------------------


def test_extract_bench_none_when_no_substitutes_at_all():
    # Every listed player is a starter -- side.get("players") is truthy
    # (non-empty), but filtering for substitute=True leaves nothing.
    side = {"players": [{"player": {"name": "A"}, "substitute": False, "statistics": {}}]}
    assert _extract_bench(side) is None


# --- _manager_event_outcome remaining branches -----------------------------------------------


def test_manager_event_outcome_none_without_recorded_score():
    ev = {"status": {"type": "finished"}, "homeTeam": {"name": "Opponent FC"}, "awayTeam": {"name": "Other FC"}, "homeScore": {}, "awayScore": {"current": 1}}
    assert _manager_event_outcome(ev, "opponent fc") is None


def test_manager_event_outcome_loss_and_draw():
    won_by_opponent = {
        "status": {"type": "finished"}, "homeTeam": {"name": "Opponent FC"}, "awayTeam": {"name": "Manager's Club"},
        "homeScore": {"current": 3}, "awayScore": {"current": 1},
    }
    # Opponent is home, so the manager's own side is away -- 1 < 3 is a loss for the manager.
    assert _manager_event_outcome(won_by_opponent, "opponent fc") == "loss"

    drawn = {
        "status": {"type": "finished"}, "homeTeam": {"name": "Opponent FC"}, "awayTeam": {"name": "Manager's Club"},
        "homeScore": {"current": 2}, "awayScore": {"current": 2},
    }
    assert _manager_event_outcome(drawn, "opponent fc") == "draw"


# --- _fetch_manager_club_record (async) -----------------------------------------------------


def test_fetch_manager_club_record_none_without_manager_id_or_name():
    assert asyncio.run(_fetch_manager_club_record(_FakePage(), None, "Opponent FC")) is None
    assert asyncio.run(_fetch_manager_club_record(_FakePage(), {"id": 1}, "Opponent FC")) is None


def test_fetch_manager_club_record_tallies_outcomes(monkeypatch):
    events = {
        "events": [
            {"status": {"type": "finished"}, "homeTeam": {"name": "Opponent FC"}, "awayTeam": {"name": "Manager's Club"}, "homeScore": {"current": 0}, "awayScore": {"current": 2}},
            {"status": {"type": "finished"}, "homeTeam": {"name": "Opponent FC"}, "awayTeam": {"name": "Manager's Club"}, "homeScore": {"current": 1}, "awayScore": {"current": 1}},
            {"status": {"type": "notstarted"}, "homeTeam": {"name": "Opponent FC"}, "awayTeam": {"name": "Manager's Club"}, "homeScore": {}, "awayScore": {}},
        ]
    }
    monkeypatch.setattr(sofascore, "_fetch_json", _mock_fetch_json(events, []))
    record = asyncio.run(_fetch_manager_club_record(_FakePage(), {"id": 1, "name": "Some Boss"}, "Opponent FC"))
    assert record is not None
    assert record.sample_size == 2
    assert record.wins == 1
    assert record.draws == 1


# --- _fetch_standings_and_season_stats (async) ----------------------------------------------


def test_fetch_standings_and_season_stats_none_without_tournament_or_season():
    e = {"homeTeam": {"id": 1}, "awayTeam": {"id": 2}}
    result = asyncio.run(_fetch_standings_and_season_stats(_FakePage(), e, None, None))
    assert result == (None, None, None)


def test_fetch_standings_and_season_stats_fetches_all_three(monkeypatch):
    monkeypatch.setattr(sofascore, "_sleep", _no_sleep)
    e = {"homeTeam": {"id": 1}, "awayTeam": {"id": 2}}
    router = _mock_fetch_json_router({
        "standings/total": {"standings": [{"rows": []}]},
        "team/1/unique-tournament": {"statistics": {"goals": 40}},
        "team/2/unique-tournament": {"statistics": {"goals": 30}},
    })
    monkeypatch.setattr(sofascore, "_fetch_json", router)
    standings, home_stats, away_stats = asyncio.run(_fetch_standings_and_season_stats(_FakePage(), e, 10, 20))
    assert standings is not None
    assert home_stats["statistics"]["goals"] == 40
    assert away_stats["statistics"]["goals"] == 30


# --- _fetch_top_player_stats (async) --------------------------------------------------------


def test_fetch_top_player_stats_empty_without_a_primary_season(monkeypatch):
    monkeypatch.setattr(sofascore, "_fetch_json", _mock_fetch_json({"uniqueTournamentSeasons": []}, []))
    result = asyncio.run(_fetch_top_player_stats(_FakePage(), 123))
    assert result == {}


def test_fetch_top_player_stats_builds_leaderboard(monkeypatch):
    monkeypatch.setattr(sofascore, "_sleep", _no_sleep)
    seasons_response = {"uniqueTournamentSeasons": [{"uniqueTournament": {"id": 10}, "seasons": [{"id": 20}]}]}
    top_players_response = {"topPlayers": {
        "goals": [{"player": {"name": "Star Player"}, "statistics": {"appearances": 20, "goals": 15}}],
        "assists": [{"player": {"name": "Star Player"}, "statistics": {"appearances": 20, "assists": 5}}],
    }}
    router = _mock_fetch_json_router({"seasons": seasons_response, "top-players": top_players_response})
    monkeypatch.setattr(sofascore, "_fetch_json", router)
    result = asyncio.run(_fetch_top_player_stats(_FakePage(), 123))
    assert result["Star Player"].goals == 15
    assert result["Star Player"].assists == 5
    assert result["Star Player"].appearances == 20


# --- get_sofascore_matches (async, full orchestration) --------------------------------------


def _sofascore_event(id_=1, home="Home FC", away="Away FC", start=None):
    return {
        "id": id_, "slug": "home-fc-vs-away-fc", "startTimestamp": int((start or datetime.now(tz=UTC)).timestamp()),
        "homeTeam": {"name": home}, "awayTeam": {"name": away}, "homeScore": {}, "awayScore": {},
        "tournament": {"name": "Premier League"}, "status": {"type": "notstarted"}, "season": {}, "roundInfo": {},
    }


def test_get_sofascore_matches_raises_when_team_not_found(monkeypatch):
    monkeypatch.setattr(sofascore, "launch_browser", lambda: _FakeBrowserCM())
    monkeypatch.setattr(sofascore, "_fetch_json", _mock_fetch_json({"results": []}, []))
    with pytest.raises(ValueError, match="No Sofascore team found"):
        asyncio.run(get_sofascore_matches("Unknown Team"))


def test_get_sofascore_matches_combines_next_and_last(monkeypatch):
    monkeypatch.setattr(sofascore, "launch_browser", lambda: _FakeBrowserCM())
    monkeypatch.setattr(sofascore, "_sleep", _no_sleep)
    router = _mock_fetch_json_router({
        "search/all": {"results": [{"type": "team", "entity": {"id": 1, "name": "Home FC", "slug": "home-fc"}}]},
        "events/next": {"events": [_sofascore_event(id_=1)]},
        "events/last": {"events": [_sofascore_event(id_=2)]},
    })
    monkeypatch.setattr(sofascore, "_fetch_json", router)
    matches = asyncio.run(get_sofascore_matches("Home FC"))
    assert len(matches) == 2
    assert {m.match_id for m in matches} == {"1", "2"}


# --- get_sofascore_match_details (async, full orchestration) --------------------------------


def test_get_sofascore_match_details_builds_full_details(monkeypatch):
    from football.types import MatchInfo

    match = MatchInfo(
        source="sofascore", source_url="https://www.sofascore.com/event/home-fc-vs-away-fc/999", competition="Premier League",
        home_team="Home FC", away_team="Away FC", kickoff_utc="2026-01-01T15:00:00.000Z", venue=None, status="notstarted",
        home_score=None, away_score=None, home_score_ht=None, away_score_ht=None, season=None, round=None, match_id="999",
    )
    event_response = {"event": {
        "homeTeam": {"id": 1, "name": "Home FC", "manager": None, "country": {"name": "England"}},
        "awayTeam": {"id": 2, "name": "Away FC", "manager": None, "country": {"name": "England"}},
        "venue": {"name": "Some Stadium", "city": {"name": "Somewhere"}, "country": {"name": "England"}, "venueCoordinates": {"latitude": 51.5, "longitude": -0.1}, "capacity": 60000},
        "referee": {"name": "Some Ref"},
        "attendance": 55000,
        "tournament": {"uniqueTournament": {"id": None}},
        "season": {},
    }}
    # More specific sub-endpoint keys are listed FIRST so they win over
    # the bare "event/999" key below (a substring of every one of them,
    # since the router picks the first substring match by dict order) --
    # every one of these left unmapped here just falls through to
    # default=None, same as the real endpoint being unpublished yet.
    router = _mock_fetch_json_router(
        {
            "event/999/h2h": None, "event/999/team-streaks": None, "event/999/lineups": None,
            "event/999/statistics": None, "event/999/incidents": None, "event/999/shotmap": None,
            "event/999/best-players": None,
            "event/999": event_response,
        },
        default=None,
    )
    monkeypatch.setattr(sofascore, "launch_browser", lambda: _FakeBrowserCM())
    monkeypatch.setattr(sofascore, "_sleep", _no_sleep)
    monkeypatch.setattr(sofascore, "_fetch_json", router)
    details = asyncio.run(get_sofascore_match_details(match))
    assert details.venue_name == "Some Stadium"
    assert details.referee == "Some Ref"
    assert details.attendance == 55000
    assert details.home_team_country == "England"
    assert "lineup not published yet" in details.note


# --- get_sofascore_team_profile (async, full orchestration) ---------------------------------


def test_get_sofascore_team_profile_raises_when_team_not_found(monkeypatch):
    monkeypatch.setattr(sofascore, "launch_browser", lambda: _FakeBrowserCM())
    monkeypatch.setattr(sofascore, "_fetch_json", _mock_fetch_json({"results": []}, []))
    with pytest.raises(ValueError, match="No Sofascore team found"):
        asyncio.run(get_sofascore_team_profile("Unknown Team"))


def test_get_sofascore_team_profile_builds_squad_and_transfers(monkeypatch):
    monkeypatch.setattr(sofascore, "launch_browser", lambda: _FakeBrowserCM())
    monkeypatch.setattr(sofascore, "_sleep", _no_sleep)
    router = _mock_fetch_json_router({
        "search/all": {"results": [{"type": "team", "entity": {"id": 1, "name": "Home FC", "slug": "home-fc"}}]},
        "players": {"players": [
            {"player": {"name": "Star Player", "position": "F", "injury": None, "dateOfBirthTimestamp": None, "proposedMarketValueRaw": None}},
        ]},
        "transfers": {
            "transfersIn": [{"player": {"name": "New Signing"}, "fromTeamName": "Old Club", "toTeamName": "Home FC", "transferDateTimestamp": 1735689600}],
            "transfersOut": [{"player": {"name": "Departed Player"}, "fromTeamName": "Home FC", "toTeamName": "New Club", "transferDateTimestamp": None}],
        },
        "player-statistics/seasons": {"uniqueTournamentSeasons": []},
    })
    monkeypatch.setattr(sofascore, "_fetch_json", router)
    profile = asyncio.run(get_sofascore_team_profile("Home FC"))
    assert profile.team_name == "Home FC"
    assert len(profile.squad) == 1
    assert profile.squad[0].name == "Star Player"
    assert profile.recent_transfers is not None
    assert {t.player_name for t in profile.recent_transfers} == {"New Signing", "Departed Player"}
    assert any(t.direction == "out" for t in profile.recent_transfers)


def test_team_standing_derives_numeric_goal_difference_from_the_string():
    from football.types import TeamStanding

    def standing(gd):
        return TeamStanding(position=1, played=1, wins=1, draws=0, losses=0, points=3, goal_diff=gd, total_teams=20)

    assert standing("+8").goal_difference == 8
    assert standing("-6").goal_difference == -6
    assert standing("0").goal_difference == 0
    assert standing("n/a").goal_difference is None
    assert standing("+8").goal_diff == "+8"


# --- _pick_team_hit --------------------------------------------------------------------------------


def _hit(name, gender=None, kind="team"):
    entity = {"id": 1, "name": name, "slug": name.lower().replace(" ", "-")}
    if gender:
        entity["gender"] = gender
    return {"type": kind, "entity": entity}


def test_pick_team_hit_prefers_the_hit_matching_the_searched_club_over_a_higher_ranked_other():
    from football.sites.sofascore import _pick_team_hit

    results = [_hit("Tottenham Hotspur Academy"), _hit("Tottenham Hotspur")]
    # both contain "tottenham": the alias-table exact match (the club itself) wins
    assert _pick_team_hit(results, "Tottenham", "tottenham hotspur")["entity"]["name"] == "Tottenham Hotspur"


def test_pick_team_hit_prefers_a_mens_team_over_a_womens_team():
    from football.sites.sofascore import _pick_team_hit

    results = [_hit("Arsenal Women", gender="F"), _hit("Arsenal", gender="M")]
    assert _pick_team_hit(results, "Arsenal", "arsenal")["entity"]["name"] == "Arsenal"


def test_pick_team_hit_falls_back_to_the_first_team_and_ignores_non_team_results():
    from football.sites.sofascore import _pick_team_hit

    results = [_hit("Some Player", kind="player"), _hit("Completely Different FC"), _hit("Other FC")]
    assert _pick_team_hit(results, "Xyz", "xyz")["entity"]["name"] == "Completely Different FC"
    assert _pick_team_hit([_hit("Some Player", kind="player")], "Xyz", "xyz") is None
    assert _pick_team_hit([], "Xyz", "xyz") is None


# --- older-meeting venue lookup ----------------------------------------------------------------


def _full_event(id_, home, away, home_country, away_country, venue_country, day, round_name=None):
    e = _sofascore_event(id_=id_, home=home, away=away, start=datetime.fromisoformat(day + "T19:00:00+00:00"))
    e["homeTeam"] = {"name": home, "country": {"name": home_country}}
    e["awayTeam"] = {"name": away, "country": {"name": away_country}}
    e["venue"] = {"name": "Some Stadium", "country": {"name": venue_country}}
    e["roundInfo"] = {"name": round_name} if round_name else {}
    return e


def test_older_meeting_info_marks_a_third_country_venue_neutral():
    from football.sites.sofascore import _older_meeting_info

    info = _older_meeting_info(_full_event(7, "Tottenham Hotspur", "Manchester United", "England", "England", "Spain", "2025-05-21", "Final"))
    assert info.neutral is True
    assert (info.home_team, info.away_team, info.venue_country, info.round_name) == ("Tottenham Hotspur", "Manchester United", "Spain", "Final")


def test_older_meeting_info_is_not_neutral_at_one_teams_own_country_and_unknown_when_a_country_is_missing():
    from football.sites.sofascore import _older_meeting_info

    assert _older_meeting_info(_full_event(1, "A", "B", "England", "England", "England", "2026-02-07")).neutral is False
    missing = _full_event(2, "A", "B", "England", "England", "England", "2026-02-07")
    missing["venue"] = {"name": "X"}
    assert _older_meeting_info(missing).neutral is None


def test_older_meeting_lookup_pages_back_and_reads_only_the_events_it_needs(monkeypatch):
    from football.sites.sofascore import get_sofascore_older_meeting_info

    monkeypatch.setattr(sofascore, "launch_browser", lambda: _FakeBrowserCM())
    monkeypatch.setattr(sofascore, "_sleep", _no_sleep)
    final = _full_event(50, "Tottenham Hotspur", "Manchester United", "England", "England", "Spain", "2025-05-21", "Final")
    other = _full_event(51, "Tottenham Hotspur", "Chelsea", "England", "England", "England", "2025-06-01")
    requested: list[str] = []

    async def fake_fetch(_page, url):
        requested.append(url)
        if "search/all" in url:
            return {"results": [{"type": "team", "entity": {"id": 9, "name": "Tottenham Hotspur", "slug": "tottenham"}}]}
        if "events/last/1" in url:
            return {"events": [other], "hasNextPage": True}
        if "events/last/2" in url:
            return {"events": [final], "hasNextPage": True}
        if "/event/50" in url:
            return {"event": final}
        raise AssertionError(f"unexpected request {url}")

    monkeypatch.setattr(sofascore, "_fetch_json", fake_fetch)
    result = asyncio.run(get_sofascore_older_meeting_info("Tottenham", "Man Utd", {"2025-05-21"}))
    assert list(result) == ["2025-05-21"]
    assert result["2025-05-21"].neutral is True
    assert not any("events/last/3" in u for u in requested)  # stopped once everything wanted was found
    assert sum("/event/" in u for u in requested) == 1  # only the one meeting's own record


def test_older_meeting_lookup_stops_paging_once_past_the_oldest_wanted_day(monkeypatch):
    from football.sites.sofascore import get_sofascore_older_meeting_info

    monkeypatch.setattr(sofascore, "launch_browser", lambda: _FakeBrowserCM())
    monkeypatch.setattr(sofascore, "_sleep", _no_sleep)
    old = _full_event(60, "Tottenham Hotspur", "Arsenal", "England", "England", "England", "2020-01-01")
    pages: list[str] = []

    async def fake_fetch(_page, url):
        if "search/all" in url:
            return {"results": [{"type": "team", "entity": {"id": 9, "name": "Tottenham Hotspur", "slug": "t"}}]}
        pages.append(url)
        return {"events": [old], "hasNextPage": True}

    monkeypatch.setattr(sofascore, "_fetch_json", fake_fetch)
    assert asyncio.run(get_sofascore_older_meeting_info("Tottenham", "Man Utd", {"2025-05-21"})) == {}
    assert len(pages) == 1  # page 1 already ended before the wanted day -> no point going further


def test_older_meeting_lookup_makes_no_request_when_nothing_is_wanted_and_handles_an_unknown_team(monkeypatch):
    from football.sites.sofascore import get_sofascore_older_meeting_info

    monkeypatch.setattr(sofascore, "launch_browser", lambda: _FakeBrowserCM())
    monkeypatch.setattr(sofascore, "_sleep", _no_sleep)
    monkeypatch.setattr(sofascore, "_fetch_json", lambda *_a: (_ for _ in ()).throw(AssertionError("no request expected")))
    assert asyncio.run(get_sofascore_older_meeting_info("X", "Y", set())) == {}

    monkeypatch.setattr(sofascore, "_fetch_json", _mock_fetch_json({"results": []}, []))
    assert asyncio.run(get_sofascore_older_meeting_info("Nobody", "Y", {"2025-05-21"})) == {}


# --- circuit breaker checked before any browser / warm-up / search --------------------


def test_get_sofascore_match_details_opens_no_browser_when_run_already_blocked(monkeypatch):
    from football.types import MatchInfo

    sofascore._block_reason = "HTTP 403 Forbidden"
    launched = []
    monkeypatch.setattr(sofascore, "launch_browser", lambda: launched.append("launch") or _FakeBrowserCM())
    match = MatchInfo(
        source="sofascore", source_url="https://www.sofascore.com/event/x/1", competition="Premier League",
        home_team="Home FC", away_team="Away FC", kickoff_utc="2026-01-01T15:00:00.000Z",
        venue=None, status="finished", home_score=1, away_score=0, home_score_ht=None, away_score_ht=None,
        season=None, round=None, match_id="1",
    )
    with pytest.raises(sofascore.SofascoreBlockedError):
        asyncio.run(get_sofascore_match_details(match))
    assert launched == []


def test_get_sofascore_matches_opens_no_browser_when_run_already_blocked(monkeypatch):
    sofascore._block_reason = "HTTP 429 Too Many Requests"
    launched = []
    monkeypatch.setattr(sofascore, "launch_browser", lambda: launched.append("launch") or _FakeBrowserCM())
    with pytest.raises(sofascore.SofascoreBlockedError):
        asyncio.run(get_sofascore_matches("Home FC"))
    assert launched == []


def test_warm_up_refuses_to_hit_the_homepage_when_run_already_blocked(monkeypatch):
    sofascore._block_reason = "HTTP 403 Forbidden"
    gotos = []

    async def fake_goto(*_a, **_k):
        gotos.append("goto")

    page = type("P", (), {"goto": fake_goto})()
    with pytest.raises(sofascore.SofascoreBlockedError):
        asyncio.run(sofascore._warm_up(page))
    assert gotos == []


def test_fetch_json_paces_requests_at_the_configured_floor(monkeypatch):
    """_pace enforces _MIN_INTERVAL_S (plus proportional jitter) across
    sessions even when no per-call-site _sleep sits between two
    _fetch_json calls (the gap that warm-up -> first API used to leave
    wide open). Network calls are in-page evaluate(), not goto()."""
    from football.sites import sofascore as sc

    class _JsonPage:
        def __init__(self):
            self.evaluates = 0

        async def goto(self, *_a, **_k):
            raise AssertionError("must not navigate to raw API URLs")

        async def evaluate(self, *_a, **_k):
            self.evaluates += 1
            return "{}"

    monkeypatch.setattr(sc, "_MIN_INTERVAL_S", 0.05)
    page = _JsonPage()
    real_fetch = sc._fetch_json
    delays: list[float] = []
    original_sleep = sc.asyncio.sleep

    async def timed_sleep(seconds):
        delays.append(seconds)
        await original_sleep(seconds)

    monkeypatch.setattr(sc.asyncio, "sleep", timed_sleep)
    sc.reset_block_state()
    asyncio.run(real_fetch(page, "https://www.sofascore.com/api/v1/a"))
    asyncio.run(real_fetch(page, "https://www.sofascore.com/api/v1/b"))
    assert page.evaluates == 2
    assert delays and delays[0] >= 0.04  # second call waited for the floor


def test_reset_block_state_clears_the_pacing_floor_timestamp():
    sofascore._block_reason = "HTTP 403 Forbidden"
    sofascore._last_request_at = 999.0
    sofascore.reset_block_state()
    assert sofascore._block_reason is None
    assert sofascore._last_request_at == 0.0
