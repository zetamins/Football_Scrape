import asyncio

import pytest

from football.sites import three65scores
from football.sites.three65scores import (
    _extract_lineup_side,
    _extract_player_of_the_match,
    _extract_standing,
    _extract_timeline,
    _fetch_standings_for,
    _find_team,
    _forward_match,
    _parse_365_stat_value,
    _pool_competitors,
    _real_rating,
    _reverse_match,
    _shortest,
    _slugify,
    _stat_lookup,
    _to_match_info,
    get365_scores_match_details,
    get365_scores_matches,
    get365_scores_team_profile,
)

# --- _slugify -------------------------------------------------------------------------


def test_slugify_hyphenates_and_trims():
    assert _slugify("Premier League!") == "premier-league"


# --- _shortest / _reverse_match / _forward_match ---------------------------------------


def test_shortest_picks_shortest_name():
    candidates = {1: {"id": 1, "name": "Nottingham Forest", "nameForURL": "x", "type": "team"}, 2: {"id": 2, "name": "NFFC", "nameForURL": "y", "type": "team"}}
    result = _shortest(candidates)
    assert result.name == "NFFC"


def test_reverse_match_finds_club_whose_name_is_a_substring_of_target():
    competitors = [{"id": 1, "name": "Girona", "nameForURL": "x", "type": "team"}]
    result = _reverse_match(["girona fc"], competitors)
    assert result is not None
    assert result.name == "Girona"


def test_reverse_match_none_below_4_char_floor():
    competitors = [{"id": 1, "name": "PSG", "nameForURL": "x", "type": "team"}]
    assert _reverse_match(["some psg target"], competitors) is None


def test_forward_match_finds_target_as_substring_of_name():
    competitors = [{"id": 1, "name": "N.E.C. Nijmegen", "nameForURL": "x", "type": "team"}]
    result = _forward_match(["nijmegen"], competitors)
    assert result is not None
    assert result.name == "N.E.C. Nijmegen"


def test_forward_match_ignores_short_targets():
    competitors = [{"id": 1, "name": "Necaxa", "nameForURL": "x", "type": "team"}]
    assert _forward_match(["nec"], competitors) is None


# --- _to_match_info -----------------------------------------------------------------


def _raw_game(**overrides):
    base = {
        "id": 555, "homeCompetitor": {"id": 1, "name": "Home FC", "score": 2}, "awayCompetitor": {"id": 2, "name": "Away FC", "score": 1},
        "competitionId": 7, "competitionDisplayName": "Premier League", "statusText": "Ended", "startTime": "2026-01-01T15:00:00.000Z", "venue": {"name": "Home Stadium"},
    }
    base.update(overrides)
    return base


def test_to_match_info_finished_match():
    m = _to_match_info(_raw_game())
    assert m.status == "finished"
    assert m.home_score == 2


def test_to_match_info_scheduled_match_has_no_score():
    m = _to_match_info(_raw_game(statusText="Scheduled", homeCompetitor={"id": 1, "name": "Home FC", "score": 0}, awayCompetitor={"id": 2, "name": "Away FC", "score": 0}))
    assert m.status == "scheduled"
    assert m.home_score is None


def test_to_match_info_falls_back_to_lowercased_status_text():
    m = _to_match_info(_raw_game(statusText="Postponed"))
    assert m.status == "postponed"


# --- _parse_365_stat_value ------------------------------------------------------------


def test_parse_365_stat_value_plain_number():
    assert _parse_365_stat_value("4") == 4.0


def test_parse_365_stat_value_fraction_takes_successful_count():
    assert _parse_365_stat_value("3/5 (60%)") == 3.0


def test_parse_365_stat_value_minutes_with_trailing_quote():
    assert _parse_365_stat_value("90'") == 90.0


def test_parse_365_stat_value_none_for_missing():
    assert _parse_365_stat_value(None) is None
    assert _parse_365_stat_value("") is None


def test_parse_365_stat_value_none_for_unparseable_text():
    assert _parse_365_stat_value("n/a") is None


# --- _stat_lookup / _real_rating -------------------------------------------------------


def test_stat_lookup_builds_name_to_value_map():
    member = {"stats": [{"name": "Goals", "value": "2"}, {"name": "Assists", "value": "1"}]}
    assert _stat_lookup(member) == {"Goals": "2", "Assists": "1"}


def test_real_rating_normalizes_sentinel_to_none():
    assert _real_rating(-1) is None


def test_real_rating_passes_through_real_value():
    assert _real_rating(7.5) == 7.5


def test_real_rating_none_when_missing():
    assert _real_rating(None) is None


# --- _extract_lineup_side --------------------------------------------------------------


def test_extract_lineup_side_starting_xi():
    competitor = {"lineups": {"members": [
        {"id": 1, "status": 1, "position": {"name": "F"}, "stats": [{"name": "Minutes", "value": "90"}, {"name": "Goals", "value": "2"}], "ranking": 8.2},
    ]}}
    lineup = _extract_lineup_side(competitor, {1: "Player A"})
    assert lineup[0].name == "Player A"
    assert lineup[0].minutes_played == 90
    assert lineup[0].goals == 2
    assert lineup[0].rating == 8.2


def test_extract_lineup_side_filters_by_status():
    competitor = {"lineups": {"members": [
        {"id": 1, "status": 3, "stats": []},  # missing/injured -- not lineup or bench
    ]}}
    assert _extract_lineup_side(competitor, {}, is_bench=False) is None


def test_extract_lineup_side_none_without_members():
    assert _extract_lineup_side(None, {}) is None
    assert _extract_lineup_side({"lineups": {}}, {}) is None


# --- _extract_player_of_the_match ------------------------------------------------------


def test_extract_player_of_the_match_picks_highest_ranking():
    home = {"lineups": {"members": [{"id": 1, "status": 1, "ranking": 8.5}]}}
    away = {"lineups": {"members": [{"id": 2, "status": 1, "ranking": 7.0}]}}
    potm = _extract_player_of_the_match(home, away, {1: "Home Star", 2: "Away Star"})
    assert potm.name == "Home Star"


def test_extract_player_of_the_match_excludes_unused_subs():
    home = {"lineups": {"members": [{"id": 1, "status": 2, "ranking": None}]}}  # unused sub, no ranking
    assert _extract_player_of_the_match(home, None, {1: "Sub"}) is None


def test_extract_player_of_the_match_none_without_candidates():
    assert _extract_player_of_the_match(None, None, {}) is None


def test_extract_player_of_the_match_none_when_top_player_name_unresolvable():
    # A candidate with a real ranking but whose id has no entry in
    # name_by_id -- genuinely unusual but must degrade to None, not KeyError.
    home = {"lineups": {"members": [{"id": 1, "status": 1, "ranking": 8.5}]}}
    assert _extract_player_of_the_match(home, None, {}) is None


# --- _extract_timeline ---------------------------------------------------------------


def test_extract_timeline_filters_to_major_events_sorted_by_minute():
    events = [
        {"isMajor": True, "gameTime": 60, "eventType": {"id": 1, "name": "Goal"}, "playerId": 1, "competitorId": 10},
        {"isMajor": False, "gameTime": 30, "eventType": {"id": 5}},  # not major -- excluded
        {"isMajor": True, "gameTime": 10, "eventType": {"id": 1000}, "playerId": 2, "competitorId": 20},
    ]
    timeline = _extract_timeline(events, home_id=10, name_by_id={1: "Scorer", 2: "Sub"})
    assert [e.minute for e in timeline] == [10, 60]
    assert timeline[1].team == "home"
    assert timeline[0].type == "Substitution"


def test_extract_timeline_none_without_events():
    assert _extract_timeline(None, 10, {}) is None
    assert _extract_timeline([], 10, {}) is None


# --- _extract_standing -----------------------------------------------------------------


def test_extract_standing_finds_row_by_team_id():
    rows = [{"competitor": {"id": 1}, "position": 3, "statsData": [{"key": "points", "value": "41"}]}]
    standing = _extract_standing(rows, 1)
    assert standing.position == 3
    assert standing.points == 41


def test_extract_standing_none_when_team_missing():
    assert _extract_standing([], 1) is None
    assert _extract_standing(None, 1) is None


# --- _pool_competitors / _find_team (async) ---------------------------------------------


def _competitor(id_, name, type_=1):
    return {"id": id_, "name": name, "nameForURL": name.lower().replace(" ", "-"), "type": type_}


def test_pool_competitors_dedupes_across_variants(monkeypatch):
    calls = []

    async def fake_fetch_json(url):
        calls.append(url)
        return {"competitors": [_competitor(1, "Arsenal"), _competitor(2, "Arsenal Women")]}

    monkeypatch.setattr(three65scores, "fetch_json", fake_fetch_json)
    pool = asyncio.run(_pool_competitors(["Arsenal", "Arsenal FC"]))
    assert len(pool) == 2
    assert len(calls) == 2


def test_find_team_none_without_any_competitors(monkeypatch):
    async def fake_fetch_json(_url):
        return {"competitors": []}

    monkeypatch.setattr(three65scores, "fetch_json", fake_fetch_json)
    assert asyncio.run(_find_team("Some Unknown Club")) is None


def test_find_team_exact_match_wins(monkeypatch):
    async def fake_fetch_json(_url):
        return {"competitors": [_competitor(1, "Arsenal"), _competitor(2, "Arsenal Women")]}

    monkeypatch.setattr(three65scores, "fetch_json", fake_fetch_json)
    team = asyncio.run(_find_team("Arsenal"))
    assert team.id == 1


def test_find_team_falls_back_to_reverse_then_forward_then_shortest(monkeypatch):
    # No exact match, but a reverse-match candidate exists (a real club's
    # own name is a substring of the searched name).
    async def fake_fetch_json(_url):
        return {"competitors": [_competitor(1, "Man United")]}

    monkeypatch.setattr(three65scores, "fetch_json", fake_fetch_json)
    team = asyncio.run(_find_team("Manchester United FC"))
    assert team.id == 1


# --- get365_scores_matches (async) -------------------------------------------------------


def test_get365_scores_matches_raises_when_team_not_found(monkeypatch):
    async def fake_fetch_json(_url):
        return {"competitors": []}

    monkeypatch.setattr(three65scores, "fetch_json", fake_fetch_json)
    with pytest.raises(ValueError, match="No 365scores team found"):
        asyncio.run(get365_scores_matches("Unknown Team"))


def test_get365_scores_matches_dedupes_recent_and_current(monkeypatch):
    game = _raw_game(id=999)

    async def fake_fetch_json(url):
        if "search" in url:
            return {"competitors": [_competitor(1, "Home FC")]}
        if "recentForm" in url:
            return {"games": [game]}
        if "games/current" in url:
            return {"games": [game]}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(three65scores, "fetch_json", fake_fetch_json)
    matches = asyncio.run(get365_scores_matches("Home FC"))
    assert len(matches) == 1
    assert matches[0].match_id == "999"


# --- _fetch_standings_for (async) --------------------------------------------------------


def test_fetch_standings_for_prefers_matching_competition_table(monkeypatch):
    async def fake_fetch_json(_url):
        return {
            "standings": [
                {"competitionId": 99, "rows": [{"competitor": {"id": 1}, "position": 5, "statsData": [{"key": "points", "value": "20"}]}]},
                {"competitionId": 7, "rows": [{"competitor": {"id": 1}, "position": 3, "statsData": [{"key": "points", "value": "41"}]}]},
            ]
        }

    monkeypatch.setattr(three65scores, "fetch_json", fake_fetch_json)
    result = asyncio.run(_fetch_standings_for(1, competition_id=7))
    assert result.position == 3


def test_fetch_standings_for_falls_back_to_first_table_without_a_competition_match(monkeypatch):
    async def fake_fetch_json(_url):
        return {"standings": [{"competitionId": 99, "rows": [{"competitor": {"id": 1}, "position": 5, "statsData": [{"key": "points", "value": "20"}]}]}]}

    monkeypatch.setattr(three65scores, "fetch_json", fake_fetch_json)
    result = asyncio.run(_fetch_standings_for(1, competition_id=7))
    assert result.position == 5


def test_fetch_standings_for_none_when_fetch_raises(monkeypatch):
    async def failing_fetch_json(_url):
        raise RuntimeError("blocked")

    monkeypatch.setattr(three65scores, "fetch_json", failing_fetch_json)
    assert asyncio.run(_fetch_standings_for(1, competition_id=7)) is None


# --- get365_scores_match_details (async) -------------------------------------------------


def test_get365_scores_match_details_raises_without_cached_meta():
    from football.types import MatchInfo

    match = MatchInfo(
        source="365scores", source_url="https://x#id=123456", competition=None, home_team="Home FC", away_team="Away FC",
        kickoff_utc=None, venue=None, status=None, home_score=None, away_score=None, home_score_ht=None,
        away_score_ht=None, season=None, round=None, match_id="123456",
    )
    with pytest.raises(ValueError, match="metadata not found"):
        asyncio.run(get365_scores_match_details(match))


def test_get365_scores_match_details_builds_full_details(monkeypatch):
    # Populate _match_meta_cache via get365_scores_matches first, same as
    # the real pipeline does (matches() runs before details() in the same
    # process).
    async def fake_matches_fetch(url):
        if "search" in url:
            return {"competitors": [_competitor(42, "Home FC")]}
        if "recentForm" in url:
            return {"games": [_raw_game(id=777, homeCompetitor={"id": 42, "name": "Home FC", "score": 2}, awayCompetitor={"id": 2, "name": "Away FC", "score": 1})]}
        return {"games": []}

    monkeypatch.setattr(three65scores, "fetch_json", fake_matches_fetch)
    asyncio.run(get365_scores_matches("Home FC"))

    match = _to_match_info(_raw_game(id=777, homeCompetitor={"id": 42, "name": "Home FC", "score": 2}, awayCompetitor={"id": 2, "name": "Away FC", "score": 1}))

    async def fake_details_fetch(url):
        if "standings" in url:
            return {"standings": []}
        return {
            "game": {
                "members": [{"id": 10, "name": "Some Player"}],
                "homeCompetitor": {"lineups": {"members": [], "formation": "4-3-3"}},
                "awayCompetitor": {"lineups": {"members": [], "formation": "4-4-2"}},
                "venue": {"name": "Home Stadium", "attendance": 45000},
                "officials": [{"name": "Some Ref"}],
                "events": None,
            }
        }

    monkeypatch.setattr(three65scores, "fetch_json", fake_details_fetch)
    details = asyncio.run(get365_scores_match_details(match))
    assert details.referee == "Some Ref"
    assert details.attendance == 45000
    assert details.home_formation == "4-3-3"
    assert details.note.startswith("match stats and head-to-head not available")


# --- get365_scores_team_profile (async) --------------------------------------------------


def test_get365_scores_team_profile_raises_when_team_not_found(monkeypatch):
    async def fake_fetch_json(_url):
        return {"competitors": []}

    monkeypatch.setattr(three65scores, "fetch_json", fake_fetch_json)
    with pytest.raises(ValueError, match="No 365scores team found"):
        asyncio.run(get365_scores_team_profile("Unknown Team"))


def test_get365_scores_team_profile_builds_squad_with_average_age(monkeypatch):
    async def fake_fetch_json(url):
        if "search" in url:
            return {"competitors": [_competitor(1, "Home FC")]}
        if "squads" in url:
            return {"squads": [{"athletes": [
                {"id": 1, "name": "Player A", "age": 24, "position": {"name": "Forward"}},
                {"id": 2, "name": "Player B", "age": 26, "position": {"name": "Midfielder"}},
            ]}]}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(three65scores, "fetch_json", fake_fetch_json)
    profile = asyncio.run(get365_scores_team_profile("Home FC"))
    assert len(profile.squad) == 2
    assert profile.average_age == 25.0


def test_get365_scores_team_profile_empty_squad_when_no_athletes(monkeypatch):
    async def fake_fetch_json(url):
        if "search" in url:
            return {"competitors": [_competitor(1, "Home FC")]}
        return {"squads": []}

    monkeypatch.setattr(three65scores, "fetch_json", fake_fetch_json)
    profile = asyncio.run(get365_scores_team_profile("Home FC"))
    assert profile.squad is None
    assert profile.average_age is None
