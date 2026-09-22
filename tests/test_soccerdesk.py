import asyncio

import httpx
import pytest

from football.sites import soccerdesk
from football.sites.soccerdesk import (
    _apply_event_to_stats,
    _build_name_to_id,
    _build_player_event_stats,
    _extract_lineup_side,
    _extract_manager,
    _extract_recent_meetings,
    _extract_standing,
    _extract_timeline,
    _fetch_h2h,
    _fetch_json,
    _find_team,
    _normalize,
    _parse_timestamp,
    _slugify,
    _to_match_info,
    get_soccerdesk_match_details,
    get_soccerdesk_matches,
    get_soccerdesk_team_profile,
)


async def _no_sleep(*_args, **_kwargs):
    return None

# --- _normalize / _slugify / _parse_timestamp -------------------------------------


def test_normalize_strips_punctuation_and_lowercases():
    assert _normalize("Real Madrid CF!") == "real madrid cf"


def test_slugify_is_hyphen_separated_no_leading_trailing_hyphen():
    assert _slugify("Premier League 25/26") == "premier-league-25-26"


def test_parse_timestamp_splits_a_14_digit_datetime_int():
    assert _parse_timestamp(20260301153000) == "2026-03-01T15:30:00.000Z"


def test_parse_timestamp_none_for_falsy_input():
    assert _parse_timestamp(None) is None
    assert _parse_timestamp(0) is None


# --- _to_match_info -----------------------------------------------------------------


def _raw_match(**overrides):
    base = {
        "id": 12345,
        "teams": [{"pos": 0, "id": "t-1", "name": "Home FC"}, {"pos": 1, "id": "t-2", "name": "Away FC"}],
        "c_name": "Premier League",
        "st_name": "Premier League 25/26",
        "st_id": "stage-1",
        "start": 20260301153000,
        "score": None,
    }
    base.update(overrides)
    return base


def test_to_match_info_scheduled_for_future_match():
    m = _to_match_info(_raw_match(start=99991231235900))
    assert m.status == "scheduled"
    assert m.home_team == "Home FC"
    assert m.away_team == "Away FC"


def test_to_match_info_finished_when_past_with_score():
    m = _to_match_info(_raw_match(start=20200101120000, score=[2, 1]))
    assert m.status == "finished"
    assert m.home_score == 2
    assert m.away_score == 1


def test_to_match_info_unknown_when_past_without_score():
    m = _to_match_info(_raw_match(start=20200101120000, score=None))
    assert m.status == "unknown"
    assert m.home_score is None


def test_to_match_info_competition_includes_stage_when_present():
    m = _to_match_info(_raw_match(c_name="Premier League", st_name="Premier League 25/26"))
    assert m.competition == "Premier League - Premier League 25/26"


def test_to_match_info_competition_omits_stage_when_absent():
    m = _to_match_info(_raw_match(st_name=None))
    assert m.competition == "Premier League"


# --- _apply_event_to_stats / _build_player_event_stats -----------------------------


def test_apply_event_to_stats_goal_credits_scorer_and_assist():
    stats: dict = {}

    def entry(player_id):
        return stats.setdefault(player_id, {"goals": 0, "assists": 0, "sub_on_minute": None, "sub_off_minute": None})

    name_to_id = {"Assist Player": "p-assist"}
    event = {"type": 4, "pl_id": "p-scorer", "assists": [{"pl_name": "Assist Player"}]}
    _apply_event_to_stats(event, entry, name_to_id)
    assert stats["p-scorer"]["goals"] == 1
    assert stats["p-assist"]["assists"] == 1


def test_apply_event_to_stats_substitution_sets_minutes():
    stats: dict = {}

    def entry(player_id):
        return stats.setdefault(player_id, {"goals": 0, "assists": 0, "sub_on_minute": None, "sub_off_minute": None})

    event = {"type": 1, "min": 65, "pl_id": "p-in", "pl_id_o": "p-out"}
    _apply_event_to_stats(event, entry, {})
    assert stats["p-in"]["sub_on_minute"] == 65
    assert stats["p-out"]["sub_off_minute"] == 65


def test_build_player_event_stats_empty_without_incidents():
    assert _build_player_event_stats(None, {}) == {}


def test_build_player_event_stats_aggregates_across_minutes():
    incs = {"period1": {"45": [{"type": 4, "pl_id": "p-1", "assists": []}]}}
    stats = _build_player_event_stats(incs, {})
    assert stats["p-1"]["goals"] == 1


# --- _extract_lineup_side -----------------------------------------------------------


def test_extract_lineup_side_starting_defaults_to_90_minutes():
    side = {"starting": [{"id": "p-1", "name": "Player A", "j_num": 7}]}
    players = _extract_lineup_side(side, {})
    assert players[0].minutes_played == 90
    assert players[0].shirt_number == 7


def test_extract_lineup_side_starting_uses_sub_off_minute_when_present():
    side = {"starting": [{"id": "p-1", "name": "Player A", "j_num": 7}]}
    event_stats = {"p-1": {"sub_off_minute": 60}}
    players = _extract_lineup_side(side, event_stats)
    assert players[0].minutes_played == 60


def test_extract_lineup_side_bench_unused_sub_has_no_minutes():
    side = {"substitutes": [{"id": "p-2", "name": "Sub Player", "j_num": 15}]}
    players = _extract_lineup_side(side, {}, is_bench=True)
    assert players[0].minutes_played is None


def test_extract_lineup_side_bench_used_sub_computes_minutes_from_90():
    side = {"substitutes": [{"id": "p-2", "name": "Sub Player", "j_num": 15}]}
    event_stats = {"p-2": {"sub_on_minute": 70}}
    players = _extract_lineup_side(side, event_stats, is_bench=True)
    assert players[0].minutes_played == 20  # 90 - 70


def test_extract_lineup_side_none_without_group():
    assert _extract_lineup_side(None, {}) is None
    assert _extract_lineup_side({"starting": []}, {}) is None


# --- _extract_timeline ---------------------------------------------------------------


def test_extract_timeline_sorted_by_minute_with_known_types():
    incs = {
        "p1": {
            "60": [{"min": 60, "type": 4, "pos": 0, "pl_name": "Scorer"}],
            "10": [{"min": 10, "type": 1, "pos": 1, "pl_name": "In Player", "pl_name_o": "Out Player"}],
        }
    }
    events = _extract_timeline(incs)
    assert [e.minute for e in events] == [10, 60]
    assert events[0].type == "Substitution"
    assert events[0].detail == "In Player on for Out Player"
    assert events[1].team == "home"


def test_extract_timeline_unknown_type_falls_back_to_type_n():
    incs = {"p1": {"30": [{"min": 30, "type": 99, "pos": 0, "pl_name": "X"}]}}
    events = _extract_timeline(incs)
    assert events[0].type == "type 99"


def test_extract_timeline_none_without_incidents():
    assert _extract_timeline(None) is None
    assert _extract_timeline({}) is None


# --- _extract_recent_meetings ---------------------------------------------------------


def test_extract_recent_meetings_skips_matches_without_a_score():
    h2h_matches = [
        {"teams": [{"pos": 0, "name": "Home FC"}, {"pos": 1, "name": "Away FC"}], "score": None, "start": 20260101120000, "st_name": "Cup"},
        {"teams": [{"pos": 0, "name": "Home FC"}, {"pos": 1, "name": "Away FC"}], "score": [2, 1], "start": 20260101120000, "st_name": "League"},
    ]
    meetings = _extract_recent_meetings(h2h_matches, "Home FC")
    assert len(meetings) == 1
    assert meetings[0].scoreline == "2-1"
    assert meetings[0].venue == "home"
    assert (meetings[0].home_team, meetings[0].away_team) == ("Home FC", "Away FC")


def test_extract_recent_meetings_skips_a_match_missing_a_team_side():
    h2h_matches = [
        {"teams": [{"pos": 0, "name": "Home FC"}], "score": [2, 1], "start": 20260101120000, "st_name": "League"},  # missing away side
        {"teams": [{"pos": 0, "name": "Home FC"}, {"pos": 1, "name": "Away FC"}], "score": [1, 0], "start": 20260101120000, "st_name": "League"},
    ]
    meetings = _extract_recent_meetings(h2h_matches, "Home FC")
    assert len(meetings) == 1


def test_extract_recent_meetings_capped_at_three():
    h2h_matches = [
        {"teams": [{"pos": 0, "name": "Home FC"}, {"pos": 1, "name": "Away FC"}], "score": [1, 0], "start": 20260101120000, "st_name": "League"}
    ] * 5
    meetings = _extract_recent_meetings(h2h_matches, "Home FC")
    assert len(meetings) == 3


def test_extract_recent_meetings_none_without_matches():
    assert _extract_recent_meetings([], "Home FC") is None


# --- _extract_standing / _extract_manager / _build_name_to_id -------------------------


def test_extract_standing_finds_row_by_team_id():
    rows = [
        {"team_id": "t-1", "ranking": 3, "played": 10, "wins": 6, "draws": 2, "loss": 2, "points": 20, "goal_difference": "+8"},
        {"team_id": "t-2", "ranking": 5, "played": 10, "wins": 4, "draws": 3, "loss": 3, "points": 15, "goal_difference": "+1"},
    ]
    standing = _extract_standing(rows, "t-1")
    assert standing.position == 3
    assert standing.points == 20
    assert standing.total_teams == 2


def test_extract_standing_none_when_team_not_in_rows():
    assert _extract_standing([], "t-1") is None
    assert _extract_standing(None, "t-1") is None


def test_extract_manager_uses_first_coach():
    assert _extract_manager([{"name": "Coach A"}, {"name": "Coach B"}]).name == "Coach A"


def test_extract_manager_none_without_coaches_or_name():
    assert _extract_manager(None) is None
    assert _extract_manager([{"name": None}]) is None


def test_build_name_to_id_combines_starting_and_substitutes_both_sides():
    home = {"starting": [{"id": "h-1", "name": "Home Starter"}], "substitutes": [{"id": "h-2", "name": "Home Sub"}]}
    away = {"starting": [{"id": "a-1", "name": "Away Starter"}]}
    result = _build_name_to_id(home, away)
    assert result == {"Home Starter": "h-1", "Home Sub": "h-2", "Away Starter": "a-1"}


def test_build_name_to_id_handles_missing_sides():
    assert _build_name_to_id(None, None) == {}


# --- _fetch_json (async, retry logic) ------------------------------------------------------


def _mock_client_factory(handler):
    def factory():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return factory


def test_fetch_json_returns_on_first_success(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    result = asyncio.run(_fetch_json("https://example.com"))
    assert result == {"ok": True}


def test_fetch_json_retries_then_succeeds(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    monkeypatch.setattr(soccerdesk.asyncio, "sleep", _no_sleep)
    result = asyncio.run(_fetch_json("https://example.com"))
    assert result == {"ok": True}
    assert len(calls) == 3


def test_fetch_json_raises_last_error_after_exhausting_retries(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    monkeypatch.setattr(soccerdesk.asyncio, "sleep", _no_sleep)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(_fetch_json("https://example.com"))


# --- _find_team (async) -------------------------------------------------------------------


def _team(id_, name):
    return {"id": id_, "name": name}


def test_find_team_none_without_any_results(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"teams": []})

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    assert asyncio.run(_find_team("Some Unknown Club")) is None


def test_find_team_exact_match_wins(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"teams": [_team("t1", "Arsenal"), _team("t2", "Arsenal Women")]})

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    team = asyncio.run(_find_team("Arsenal"))
    assert team.id == "t1"


def test_find_team_reverse_direction_fallback(monkeypatch):
    # "Girona Futbol Club" has no known alias table entry, so this only
    # resolves via the reverse-direction fallback (the source's own
    # entry name, "Girona", is a substring of the searched name).
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"teams": [_team("t1", "Girona")]})

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    team = asyncio.run(_find_team("Girona Futbol Club"))
    assert team.id == "t1"


def test_find_team_falls_back_to_first_team_without_any_match(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"teams": [_team("t1", "Totally Unrelated FC")]})

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    team = asyncio.run(_find_team("Some Other Query"))
    assert team.id == "t1"


# --- get_soccerdesk_matches (async) -------------------------------------------------------


def test_get_soccerdesk_matches_raises_when_team_not_found(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"teams": []})

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    with pytest.raises(ValueError, match="No SoccerDesk team found"):
        asyncio.run(get_soccerdesk_matches("Unknown Team"))


def test_get_soccerdesk_matches_combines_fixtures_and_results(monkeypatch):
    fixture = {"id": 1, "teams": [{"pos": 0, "id": "t-1", "name": "Home FC"}, {"pos": 1, "id": "t-2", "name": "Away FC"}], "c_name": "Premier League", "st_name": None, "st_id": "s1", "start": 20990101120000, "score": None}
    result_match = {"id": 2, "teams": [{"pos": 0, "id": "t-1", "name": "Home FC"}, {"pos": 1, "id": "t-2", "name": "Away FC"}], "c_name": "Premier League", "st_name": None, "st_id": "s1", "start": 20200101120000, "score": [2, 1]}

    def handler(request: httpx.Request) -> httpx.Response:
        if "search" in str(request.url):
            return httpx.Response(200, json={"teams": [_team("t-1", "Home FC")]})
        return httpx.Response(200, json={"fixtures": [fixture], "results": [result_match]})

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    matches = asyncio.run(get_soccerdesk_matches("Home FC"))
    assert len(matches) == 2
    assert {m.match_id for m in matches} == {"1", "2"}


# --- _fetch_h2h (async) -------------------------------------------------------------------


def test_fetch_h2h_none_without_matches(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"h2h": {"matches": []}})

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    summary, matches = asyncio.run(_fetch_h2h("team-1", "team-2"))
    assert summary is None
    assert matches == []


def test_fetch_h2h_tallies_wins_and_draws(monkeypatch):
    h2h_matches = [{"win": 1}, {"win": 1}, {"win": 2}, {"win": 0}, {"win": None}]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"h2h": {"matches": h2h_matches}})

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    summary, matches = asyncio.run(_fetch_h2h("team-1", "team-2"))
    assert summary.home_wins == 2
    assert summary.away_wins == 1
    assert summary.draws == 1
    assert len(matches) == 5


# --- get_soccerdesk_match_details (async) -------------------------------------------------


def test_get_soccerdesk_match_details_builds_full_details(monkeypatch):
    from football.types import MatchInfo

    match = MatchInfo(
        source="soccerdesk", source_url="https://www.soccerdesk.com/football/premier-league/x/home-fc-vs-away-fc/999",
        competition="Premier League", home_team="Home FC", away_team="Away FC", kickoff_utc="2026-01-01T15:00:00.000Z",
        venue=None, status="scheduled", home_score=None, away_score=None, home_score_ht=None, away_score_ht=None,
        season=None, round=None, match_id="999",
    )
    match_data = {
        "lineup": [
            {"pos": 0, "starting": [], "substitutes": [], "coaches": [{"name": "Home Boss"}], "injured": [], "suspended": []},
            {"pos": 1, "starting": [], "substitutes": [], "coaches": [{"name": "Away Boss"}], "injured": [], "suspended": []},
        ],
        "has_venue": True,
        "venue": {"name": "Some Stadium", "city": "Somewhere", "lat": "51.5", "long": "-0.1"},
        "incs": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=match_data)

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    details = asyncio.run(get_soccerdesk_match_details(match))
    assert details.venue_name == "Some Stadium"
    assert details.venue_lat == 51.5
    assert details.home_manager.name == "Home Boss"
    assert "referee/attendance/weather/match-stats not available" in details.note
    # The site published an empty suspended list for both sides: that is
    # "checked, nobody suspended", not "unknown".
    assert details.home_suspended_players == []
    assert details.away_suspended_players == []


def test_get_soccerdesk_match_details_notes_injured_and_suspended_players(monkeypatch):
    from football.types import MatchInfo

    match = MatchInfo(
        source="soccerdesk", source_url="https://www.soccerdesk.com/football/premier-league/x/home-fc-vs-away-fc/999",
        competition="Premier League", home_team="Home FC", away_team="Away FC", kickoff_utc="2026-01-01T15:00:00.000Z",
        venue=None, status="scheduled", home_score=None, away_score=None, home_score_ht=None, away_score_ht=None,
        season=None, round=None, match_id="999",
    )
    match_data = {
        "lineup": [
            {"pos": 0, "starting": [], "substitutes": [], "coaches": [], "injured": [{"name": "Injured Player"}], "suspended": [{"name": "Suspended Player"}]},
            {"pos": 1, "starting": [], "substitutes": [], "coaches": [], "injured": [], "suspended": []},
        ],
        "has_venue": False,
        "incs": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=match_data)

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    details = asyncio.run(get_soccerdesk_match_details(match))
    assert details.venue_name is None
    assert "Injured (not playing): Injured Player" in details.note
    assert "Suspended: Suspended Player" in details.note
    assert details.home_suspended_players == ["Suspended Player"]


# --- get_soccerdesk_team_profile (async) --------------------------------------------------


def test_get_soccerdesk_team_profile_raises_when_team_not_found(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"teams": []})

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    with pytest.raises(ValueError, match="No SoccerDesk team found"):
        asyncio.run(get_soccerdesk_team_profile("Unknown Team"))


# --- _fetch_standings_and_h2h (async) -----------------------------------------------------


def test_fetch_standings_and_h2h_none_without_meta():
    from football.sites.soccerdesk import _fetch_standings_and_h2h
    from football.types import MatchInfo

    match = MatchInfo(
        source="soccerdesk", source_url="https://x", competition=None, home_team="Home FC", away_team="Away FC",
        kickoff_utc=None, venue=None, status=None, home_score=None, away_score=None, home_score_ht=None,
        away_score_ht=None, season=None, round=None, match_id="1",
    )
    result = asyncio.run(_fetch_standings_and_h2h(None, match))
    assert result == (None, None, None, None)


def test_fetch_standings_and_h2h_tolerates_h2h_fetch_failure(monkeypatch):
    from football.sites.soccerdesk import _fetch_standings_and_h2h, _MatchMeta
    from football.types import MatchInfo

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    monkeypatch.setattr(soccerdesk.asyncio, "sleep", _no_sleep)
    match = MatchInfo(
        source="soccerdesk", source_url="https://x", competition=None, home_team="Home FC", away_team="Away FC",
        kickoff_utc=None, venue=None, status=None, home_score=None, away_score=None, home_score_ht=None,
        away_score_ht=None, season=None, round=None, match_id="1",
    )
    meta = _MatchMeta(home_id="team-1", away_id="team-2", stage_id=None)
    head_to_head_summary, _recent_meetings, home_standing, _away_standing = asyncio.run(_fetch_standings_and_h2h(meta, match))
    assert head_to_head_summary is None
    assert home_standing is None


def test_fetch_standings_and_h2h_builds_standings_from_stage(monkeypatch):
    from football.sites.soccerdesk import _fetch_standings_and_h2h, _MatchMeta
    from football.types import MatchInfo

    def handler(request: httpx.Request) -> httpx.Response:
        if "h2h" in str(request.url):
            return httpx.Response(200, json={"h2h": {"matches": []}})
        return httpx.Response(200, json={"L": {"tables": [{"teams": [
            {"team_id": "team-1", "ranking": 3, "played": "20", "wins": "12", "draws": "4", "loss": "4", "points": "40", "goal_difference": "+15"},
        ]}]}})

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    match = MatchInfo(
        source="soccerdesk", source_url="https://x", competition=None, home_team="Home FC", away_team="Away FC",
        kickoff_utc=None, venue=None, status=None, home_score=None, away_score=None, home_score_ht=None,
        away_score_ht=None, season=None, round=None, match_id="1",
    )
    meta = _MatchMeta(home_id="team-1", away_id="team-2", stage_id="stage-1")
    _summary, _recent, home_standing, away_standing = asyncio.run(_fetch_standings_and_h2h(meta, match))
    assert home_standing.position == 3
    assert away_standing is None


def test_fetch_standings_and_h2h_tolerates_stage_fetch_failure(monkeypatch):
    from football.sites.soccerdesk import _fetch_standings_and_h2h, _MatchMeta
    from football.types import MatchInfo

    def handler(request: httpx.Request) -> httpx.Response:
        if "h2h" in str(request.url):
            return httpx.Response(200, json={"h2h": {"matches": []}})
        return httpx.Response(500)

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    monkeypatch.setattr(soccerdesk.asyncio, "sleep", _no_sleep)
    match = MatchInfo(
        source="soccerdesk", source_url="https://x", competition=None, home_team="Home FC", away_team="Away FC",
        kickoff_utc=None, venue=None, status=None, home_score=None, away_score=None, home_score_ht=None,
        away_score_ht=None, season=None, round=None, match_id="1",
    )
    meta = _MatchMeta(home_id="team-1", away_id="team-2", stage_id="stage-1")
    _summary, _recent, home_standing, away_standing = asyncio.run(_fetch_standings_and_h2h(meta, match))
    assert home_standing is None
    assert away_standing is None


def test_get_soccerdesk_team_profile_builds_squad(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if "search" in str(request.url):
            return httpx.Response(200, json={"teams": [_team("t-1", "Home FC")]})
        return httpx.Response(200, json={"name": "Home FC", "participants": [{"name": "Player A"}, {"name": "Player B"}]})

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(handler))
    profile = asyncio.run(get_soccerdesk_team_profile("Home FC"))
    assert profile.team_name == "Home FC"
    assert len(profile.squad) == 2
