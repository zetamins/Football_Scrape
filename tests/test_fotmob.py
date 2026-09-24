import asyncio
import json

import pytest

from football.sites import fotmob
from football.sites.fotmob import (
    _build_teams_index,
    _extract_lineup,
    _extract_manager,
    _extract_match_stat_item,
    _extract_match_stats,
    _extract_next_data,
    _extract_player_of_the_match,
    _extract_recent_meetings,
    _extract_squad,
    _extract_suspended_players,
    _extract_timeline,
    _extract_transfers,
    _extract_unavailable,
    _find_best_team_match,
    _fixture_status,
    _h2h_meeting_from,
    _load_teams_index,
    _minutes_from_sub_events,
    _stat_value,
    _TeamIndexEntry,
    _to_match_info,
    get_fotmob_match_details,
    get_fotmob_matches,
    get_fotmob_team_profile,
)


def _entry(id_, slug):
    return _TeamIndexEntry(id=id_, slug=slug, url=f"https://www.fotmob.com/teams/{id_}/overview/{slug}")


def test_liverpool_resolves_to_the_english_club_not_the_uruguayan_one():
    # Confirmed live, directly (fetching each team's own Fotmob page and
    # reading details.country, not guessed from slug/title -- both are
    # misleading here): a real Uruguayan club is ALSO officially named
    # "Liverpool FC" and holds the Fotmob slug "liverpool-fc" (id 2219,
    # country="URU"). team_aliases.py's canonical alias for this
    # project's "Liverpool" is "Liverpool FC", which normalizes to
    # exactly that slug -- the alias loop's exact-match branch hit the
    # Uruguayan club first and returned before ever trying the plain
    # "liverpool" alias, which is the real English club (id 8650,
    # confirmed country="ENG"). This silently corrupted every
    # Fotmob-derived insight (season xG/shots/aerial/passing/fouls/
    # goalkeeping/possession/corners estimates) for "Liverpool" searches.
    entries = [
        _entry(8650, "liverpool"),  # the real English Premier League club
        _entry(2219, "liverpool-fc"),  # a same-named Uruguayan club (Montevideo)
        _entry(1070259, "liverpool-u21"),
        _entry(258665, "liverpool"),  # Liverpool's own women's team, same bare slug
        _entry(1113546, "liverpool-u18"),
    ]
    match = _find_best_team_match(entries, "Liverpool")
    assert match is not None
    assert match.id == 8650
    assert match.slug == "liverpool"


def test_general_algorithm_prefers_a_later_aliass_exact_match_over_an_earlier_aliass_substring():
    # Same structural fix as goal.py's equivalent test, using
    # team_aliases.py's "leicester city" -> "leicester" pair: the
    # canonical alias ("leicester-city", tried first) would
    # substring-match a longer, wrong entity if checked in isolation, but
    # the exact-match pass now runs across every alias before any
    # substring fallback runs for any of them.
    entries = [
        _entry("real", "leicester"),
        _entry("wrong", "leicester-city-academy"),
    ]
    match = _find_best_team_match(entries, "Leicester City")
    assert match is not None
    assert match.id == "real"


def test_override_is_still_required_for_liverpool_unlike_goal_dot_com():
    # Confirmed live by temporarily clearing _FOTMOB_SLUG_OVERRIDE and
    # re-running the Liverpool case above: unlike goal.py (where the
    # equivalent override turned out to be fully redundant with the
    # general fix and was removed), Fotmob's Uruguayan club holds a
    # GENUINE exact slug "liverpool-fc" -- not a substring false-positive
    # -- so even a full exact-match-across-every-alias pass hits that
    # real, exact, wrong match on the canonical alias before the shorter
    # "liverpool" alias (tried second) is ever reached. This test proves
    # the override is load-bearing, not belt-and-braces -- if it were
    # ever removed under the assumption the general fix alone covers it,
    # this would catch the regression.
    from football.sites.fotmob import _FOTMOB_SLUG_OVERRIDE

    entries = [
        _entry(8650, "liverpool"),
        _entry(2219, "liverpool-fc"),
    ]
    saved = dict(_FOTMOB_SLUG_OVERRIDE)
    _FOTMOB_SLUG_OVERRIDE.clear()
    try:
        match = _find_best_team_match(entries, "Liverpool")
        assert match is not None
        assert match.id == 2219  # the WRONG club -- proves the override is necessary
    finally:
        _FOTMOB_SLUG_OVERRIDE.update(saved)


def test_find_best_team_match_falls_back_to_substring_candidates():
    # No exact match for any alias, but a substring match exists --
    # prefers the shortest matching slug (main club over a variant page).
    entries = [_entry(1, "some-totally-unrelated-club-2-fc"), _entry(2, "some-totally-unrelated-club-fc")]
    match = _find_best_team_match(entries, "Some Totally Unrelated Club")
    assert match is not None
    assert match.id == 2


def test_find_best_team_match_falls_back_to_reverse_direction():
    # Sofascore's own name is longer than this source's short slug --
    # neither an exact nor a forward-substring match exists, only a
    # reverse one (the slug is a substring of the searched name).
    entries = [_entry(1, "girona")]
    match = _find_best_team_match(entries, "Girona Futbol Club")
    assert match is not None
    assert match.id == 1


def test_find_best_team_match_none_without_any_candidate():
    entries = [_entry(1, "totally-different-club")]
    assert _find_best_team_match(entries, "Some Unrelated Team") is None


def test_other_teams_still_resolve_via_the_normal_alias_exact_match():
    # The override table is scoped to specific known collisions -- this
    # confirms it doesn't interfere with the general case.
    entries = [
        _entry(1, "arsenal"),
        _entry(2, "arsenal-women"),
    ]
    match = _find_best_team_match(entries, "Arsenal")
    assert match is not None
    assert match.id == 1


# --- _extract_next_data ------------------------------------------------------------


def test_extract_next_data_parses_embedded_json():
    html = '<html><script id="__NEXT_DATA__" type="application/json">{"props": {"a": 1}}</script></html>'
    data = _extract_next_data(html)
    assert data["props"]["a"] == 1


def test_extract_next_data_raises_when_marker_missing():
    import pytest

    with pytest.raises(ValueError, match="__NEXT_DATA__"):
        _extract_next_data("<html>no marker here</html>")


# --- _fixture_status / _to_match_info -----------------------------------------------


def test_fixture_status_priority_cancelled_over_finished():
    assert _fixture_status({"cancelled": True}, finished=True) == "cancelled"


def test_fixture_status_finished():
    assert _fixture_status({}, finished=True) == "finished"


def test_fixture_status_live_when_started_not_finished():
    assert _fixture_status({"started": True}, finished=False) == "live"


def test_fixture_status_scheduled_by_default():
    assert _fixture_status({}, finished=False) == "scheduled"


def _raw_fixture(**overrides):
    base = {
        "status": {"finished": True, "utcTime": "2026-01-01T15:00:00.000Z"},
        "pageUrl": "/matches/home-vs-away/abc123#1234567",
        "tournament": {"name": "Premier League"},
        "home": {"name": "Home FC", "score": 2},
        "away": {"name": "Away FC", "score": 1},
        "id": 1234567,
    }
    base.update(overrides)
    return base


def test_to_match_info_only_trusts_score_once_finished():
    m = _to_match_info(_raw_fixture())
    assert m.home_score == 2
    assert m.status == "finished"


def test_to_match_info_ignores_placeholder_zero_score_before_kickoff():
    m = _to_match_info(_raw_fixture(status={"finished": False, "started": False, "utcTime": "2026-06-01T15:00:00.000Z"}, home={"name": "Home FC", "score": 0}, away={"name": "Away FC", "score": 0}))
    assert m.home_score is None
    assert m.status == "scheduled"


# --- _minutes_from_sub_events / _extract_lineup -------------------------------------


def test_minutes_from_sub_events_starter_full_90_without_sub_out():
    assert _minutes_from_sub_events([], is_bench=False) == 90


def test_minutes_from_sub_events_starter_subbed_off():
    events = [{"type": "subOut", "time": 70}]
    assert _minutes_from_sub_events(events, is_bench=False) == 70


def test_minutes_from_sub_events_bench_unused_stays_none():
    assert _minutes_from_sub_events([], is_bench=True) is None


def test_minutes_from_sub_events_bench_used_computes_from_90():
    events = [{"type": "subIn", "time": 75}]
    assert _minutes_from_sub_events(events, is_bench=True) == 15


def test_extract_lineup_reads_goals_and_assists_from_events():
    team = {"starters": [{"name": "Player A", "positionId": 4, "performance": {"events": [{"type": "goal"}, {"type": "goal"}, {"type": "assist"}]}}]}
    lineup = _extract_lineup(team)
    assert lineup[0].goals == 2
    assert lineup[0].assists == 1


def test_extract_lineup_none_without_group():
    assert _extract_lineup(None) is None
    assert _extract_lineup({"starters": []}) is None


# --- _extract_manager / _extract_unavailable ------------------------------------------


def test_extract_manager():
    assert _extract_manager({"name": "Coach A", "countryName": "England"}).name == "Coach A"


def test_extract_manager_none_without_name():
    assert _extract_manager(None) is None
    assert _extract_manager({}) is None


def test_extract_unavailable():
    team = {"unavailable": [{"name": "Injured Player", "unavailability": {"type": "injury", "expectedReturn": "2026-03-01"}}]}
    missing = _extract_unavailable(team)
    assert missing[0].description == "injury"


def test_extract_unavailable_none_when_empty():
    # Key present + empty list = CONFIRMED_EMPTY ("checked, nobody out"),
    # matching sofascore's missingPlayers semantics.
    assert _extract_unavailable({"unavailable": []}) == []
    assert _extract_unavailable(None) is None
    assert _extract_unavailable({}) is None


def test_extract_suspended_players_filters_by_suspension_type():
    team = {
        "unavailable": [
            {"name": "Banned Player", "unavailability": {"type": "suspension"}},
            {"name": "Injured Player", "unavailability": {"type": "injury"}},
            {"name": "Other Absent", "unavailability": {}},
        ]
    }
    assert _extract_suspended_players(team) == ["Banned Player"]


def test_extract_suspended_players_confirmed_empty_vs_absent_key():
    assert _extract_suspended_players({"unavailable": []}) == []
    assert _extract_suspended_players({"unavailable": [{"name": "X", "unavailability": {"type": "injury"}}]}) == []
    assert _extract_suspended_players({}) is None
    assert _extract_suspended_players(None) is None


# --- _h2h_meeting_from / _extract_recent_meetings -------------------------------------


def test_h2h_meeting_from_parses_score_string():
    m = {"status": {"scoreStr": "2 - 1"}, "home": {"name": "Home FC"}, "away": {"name": "Away FC"}, "time": {"utcTime": "2025-01-01T00:00:00.000Z"}, "league": {"name": "Premier League"}}
    meeting = _h2h_meeting_from(m, "home fc")
    assert meeting.scoreline == "2-1"
    assert meeting.venue == "home"
    assert (meeting.home_team, meeting.away_team) == ("Home FC", "Away FC")


def test_h2h_meeting_from_none_without_recorded_score():
    m = {"status": {"scoreStr": None}, "home": {"name": "Home FC"}, "away": {"name": "Away FC"}}
    assert _h2h_meeting_from(m, "home fc") is None


def test_h2h_meeting_from_none_without_team_names():
    m = {"status": {"scoreStr": "2 - 1"}, "home": {}, "away": {"name": "Away FC"}}
    assert _h2h_meeting_from(m, "home fc") is None


def test_extract_recent_meetings_filters_unfinished_and_caps_at_three():
    matches = [
        {"status": {"finished": True, "scoreStr": "1 - 0"}, "home": {"name": "Home FC"}, "away": {"name": "Away FC"}, "time": {}, "league": {}},
        {"status": {"finished": False}},
    ] * 3
    meetings = _extract_recent_meetings(matches, "Home FC")
    assert len(meetings) == 3


def test_extract_recent_meetings_none_without_h2h_matches():
    assert _extract_recent_meetings(None, "Home FC") is None
    assert _extract_recent_meetings([], "Home FC") is None


# --- _extract_timeline -----------------------------------------------------------------


def test_extract_timeline_maps_is_home_to_team():
    facts = {"events": {"events": [{"isHome": True, "time": 30, "type": "Goal", "player": {"name": "Scorer"}}]}}
    events = _extract_timeline(facts)
    assert events[0].team == "home"
    assert events[0].player == "Scorer"


def test_extract_timeline_added_time_detail():
    facts = {"events": {"events": [{"isHome": False, "time": 90, "type": "AddedTime", "minutesAddedStr": "+3"}]}}
    events = _extract_timeline(facts)
    assert events[0].detail == "+3"


def test_extract_timeline_none_without_events():
    assert _extract_timeline(None) is None
    assert _extract_timeline({"events": {}}) is None


# --- _stat_value / _extract_match_stat_item / _extract_match_stats ----------------------


def test_stat_value_returns_empty_string_when_index_out_of_range():
    assert _stat_value([], 0) == ""
    assert _stat_value(["10", "8"], 0) == "10"


def test_extract_match_stat_item():
    item = _extract_match_stat_item({"title": "Possession", "stats": ["60%", "40%"]})
    assert item.name == "Possession"
    assert item.home == "60%"
    assert item.away == "40%"


def test_extract_match_stats_flattens_periods():
    stats = {"Periods": {"All": {"stats": [{"stats": [{"title": "Possession", "stats": ["60%", "40%"]}]}]}}}
    items = _extract_match_stats(stats)
    assert items[0].name == "Possession"


def test_extract_match_stats_none_without_groups():
    assert _extract_match_stats(None) is None
    assert _extract_match_stats({"Periods": {}}) is None


# --- _extract_player_of_the_match -----------------------------------------------------


def test_extract_player_of_the_match_handles_dict_name_field():
    potm = {"name": {"fullName": "Player A"}, "rating": {"num": 8.5}}
    result = _extract_player_of_the_match(potm)
    assert result.name == "Player A"
    assert result.rating == 8.5


def test_extract_player_of_the_match_handles_plain_string_name():
    potm = {"name": "Player B", "rating": {"num": 7.5}}
    assert _extract_player_of_the_match(potm).name == "Player B"


def test_extract_player_of_the_match_none_before_match_starts():
    assert _extract_player_of_the_match(None) is None
    assert _extract_player_of_the_match({"name": None}) is None


# --- _extract_squad / _extract_transfers -----------------------------------------------


def test_extract_squad_skips_coaching_staff_group():
    squad_data = {
        "squad": [
            {"title": "Coach", "members": [{"name": "Manager A"}]},
            {"title": "Forwards", "members": [{"name": "Player A", "goals": 10, "assists": 2, "role": {"fallback": "Forward"}}]},
        ]
    }
    squad = _extract_squad(squad_data)
    assert len(squad) == 1
    assert squad[0].name == "Player A"
    assert squad[0].season_stats.goals == 10


def test_extract_squad_reports_injury_expected_return():
    squad_data = {"squad": [{"title": "Defenders", "members": [{"name": "Injured DF", "injury": {"expectedReturn": "2026-03-01"}}]}]}
    squad = _extract_squad(squad_data)
    assert "2026-03-01" in squad[0].injury


def test_extract_squad_none_without_groups():
    assert _extract_squad(None) is None
    assert _extract_squad({"squad": []}) is None


def test_extract_transfers_classifies_in_and_out():
    transfers_data = {"data": {"transfersIn": [{"name": "New Player", "fromClub": "Old Club", "toClub": "New Club", "transferDate": "2026-01-01"}]}}
    transfers = _extract_transfers(transfers_data)
    assert transfers[0].direction == "in"
    assert transfers[0].player_name == "New Player"


def test_extract_transfers_none_without_data():
    assert _extract_transfers(None) is None
    assert _extract_transfers({"data": {}}) is None


# --- _build_teams_index / _load_teams_index (async, filesystem-touching) ---------------


_SITEMAP_INDEX_XML = "<loc>https://www.fotmob.com/sitemap/en/teams-1.xml</loc>"
_SITEMAP_SHARD_XML = (
    "<loc>https://www.fotmob.com/teams/8650/overview/liverpool</loc>"
    "<loc>https://www.fotmob.com/teams/9825/overview/arsenal</loc>"
)


def test_build_teams_index_parses_sitemap_shards(monkeypatch):
    async def fake_fetch_text(url):
        return _SITEMAP_SHARD_XML if "teams-1" in url else _SITEMAP_INDEX_XML

    monkeypatch.setattr(fotmob, "fetch_text", fake_fetch_text)
    entries = asyncio.run(_build_teams_index())
    assert [e.id for e in entries] == [8650, 9825]
    assert entries[0].slug == "liverpool"


def test_load_teams_index_writes_seed_file_on_cache_miss(monkeypatch, tmp_path):
    async def fake_fetch_text(url):
        return _SITEMAP_SHARD_XML if "teams-1" in url else _SITEMAP_INDEX_XML

    monkeypatch.setattr(fotmob, "fetch_text", fake_fetch_text)
    monkeypatch.setattr(fotmob, "data_dir", lambda: tmp_path)

    entries = asyncio.run(_load_teams_index())
    assert len(entries) == 2
    seed_path = tmp_path / "fotmob-teams.json"
    assert seed_path.exists()


def test_load_teams_index_reads_existing_seed_file_without_fetching(monkeypatch, tmp_path):
    seed_path = tmp_path / "fotmob-teams.json"
    seed_path.write_text(json.dumps([{"id": 8650, "slug": "liverpool", "url": "https://www.fotmob.com/teams/8650/overview/liverpool"}]), encoding="utf-8")

    async def unexpected_fetch(_url):
        raise AssertionError("should not fetch -- seed file already exists")

    monkeypatch.setattr(fotmob, "fetch_text", unexpected_fetch)
    monkeypatch.setattr(fotmob, "data_dir", lambda: tmp_path)

    entries = asyncio.run(_load_teams_index())
    assert entries == [_entry(8650, "liverpool")]


# --- get_fotmob_matches (async) ----------------------------------------------------------


def _next_data_html(payload: dict) -> str:
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script></html>'


def _fixture(id_=1, home="Home FC", away="Away FC", finished=True, home_score=2, away_score=1):
    return {
        "id": id_, "pageUrl": f"/matches/{id_}",
        "tournament": {"name": "Premier League"},
        "home": {"name": home, "score": home_score}, "away": {"name": away, "score": away_score},
        "status": {"finished": finished, "started": True, "cancelled": False, "utcTime": "2026-01-01T15:00:00.000Z"},
    }


def test_get_fotmob_matches_raises_when_team_not_found(monkeypatch, tmp_path):
    seed_path = tmp_path / "fotmob-teams.json"
    seed_path.write_text(json.dumps([]), encoding="utf-8")
    monkeypatch.setattr(fotmob, "data_dir", lambda: tmp_path)

    with pytest.raises(ValueError, match="No Fotmob team found"):
        asyncio.run(get_fotmob_matches("Some Unknown Club"))


def test_get_fotmob_matches_builds_match_info_list(monkeypatch, tmp_path):
    seed_path = tmp_path / "fotmob-teams.json"
    seed_path.write_text(json.dumps([{"id": 8650, "slug": "liverpool", "url": "https://www.fotmob.com/teams/8650/overview/liverpool"}]), encoding="utf-8")
    monkeypatch.setattr(fotmob, "data_dir", lambda: tmp_path)

    next_data = {"props": {"pageProps": {"fallback": {"team-8650": {"fixtures": {"allFixtures": {"fixtures": [_fixture()]}}}}}}}

    async def fake_fetch_text(_url):
        return _next_data_html(next_data)

    monkeypatch.setattr(fotmob, "fetch_text", fake_fetch_text)
    matches = asyncio.run(get_fotmob_matches("Liverpool"))
    assert len(matches) == 1
    assert matches[0].home_team == "Home FC"
    assert matches[0].status == "finished"


def test_fetch_team_fixtures_raises_without_team_fallback_key(monkeypatch, tmp_path):
    seed_path = tmp_path / "fotmob-teams.json"
    seed_path.write_text(json.dumps([{"id": 8650, "slug": "liverpool", "url": "https://www.fotmob.com/teams/8650/overview/liverpool"}]), encoding="utf-8")
    monkeypatch.setattr(fotmob, "data_dir", lambda: tmp_path)

    next_data = {"props": {"pageProps": {"fallback": {"unrelated-key": {}}}}}

    async def fake_fetch_text(_url):
        return _next_data_html(next_data)

    monkeypatch.setattr(fotmob, "fetch_text", fake_fetch_text)
    with pytest.raises(ValueError, match="team fallback key not found"):
        asyncio.run(get_fotmob_matches("Liverpool"))


# --- get_fotmob_team_profile (async) -----------------------------------------------------


def test_get_fotmob_team_profile_raises_when_team_not_found(monkeypatch, tmp_path):
    seed_path = tmp_path / "fotmob-teams.json"
    seed_path.write_text(json.dumps([]), encoding="utf-8")
    monkeypatch.setattr(fotmob, "data_dir", lambda: tmp_path)

    with pytest.raises(ValueError, match="No Fotmob team found"):
        asyncio.run(get_fotmob_team_profile("Some Unknown Club"))


def test_get_fotmob_team_profile_builds_squad_and_injuries(monkeypatch, tmp_path):
    seed_path = tmp_path / "fotmob-teams.json"
    seed_path.write_text(json.dumps([{"id": 8650, "slug": "liverpool", "url": "https://www.fotmob.com/teams/8650/overview/liverpool"}]), encoding="utf-8")
    monkeypatch.setattr(fotmob, "data_dir", lambda: tmp_path)

    next_data = {
        "props": {"pageProps": {"fallback": {"team-8650": {
            "details": {"name": "Liverpool FC"},
            "squad": {"squad": [{"title": "Attackers", "members": [
                {"name": "Star Player", "age": 26, "goals": 10, "assists": 5, "ycards": 2, "rcards": 0, "rating": 7.5, "injury": {"id": 1, "expectedReturn": "2026-02-01"}},
            ]}]},
            "transfers": None,
        }}}}
    }

    async def fake_fetch_text(_url):
        return _next_data_html(next_data)

    monkeypatch.setattr(fotmob, "fetch_text", fake_fetch_text)
    profile = asyncio.run(get_fotmob_team_profile("Liverpool"))
    assert profile.team_name == "Liverpool FC"
    assert len(profile.squad) == 1
    assert profile.injuries is not None
    assert profile.key_injuries is not None
    assert profile.average_age == 26.0


def test_get_fotmob_team_profile_raises_without_team_fallback_key(monkeypatch, tmp_path):
    seed_path = tmp_path / "fotmob-teams.json"
    seed_path.write_text(json.dumps([{"id": 8650, "slug": "liverpool", "url": "https://www.fotmob.com/teams/8650/overview/liverpool"}]), encoding="utf-8")
    monkeypatch.setattr(fotmob, "data_dir", lambda: tmp_path)

    next_data = {"props": {"pageProps": {"fallback": {"unrelated-key": {}}}}}

    async def fake_fetch_text(_url):
        return _next_data_html(next_data)

    monkeypatch.setattr(fotmob, "fetch_text", fake_fetch_text)
    with pytest.raises(ValueError, match="team fallback key not found"):
        asyncio.run(get_fotmob_team_profile("Liverpool"))


# --- get_fotmob_match_details (async) ------------------------------------------------------


def test_get_fotmob_match_details_builds_full_details(monkeypatch):
    from football.types import MatchInfo

    match = MatchInfo(
        source="fotmob", source_url="https://www.fotmob.com/matches/1", competition="Premier League",
        home_team="Home FC", away_team="Away FC", kickoff_utc="2026-01-01T15:00:00.000Z", venue=None,
        status="scheduled", home_score=None, away_score=None, home_score_ht=None, away_score_ht=None,
        season=None, round=None, match_id="1",
    )
    next_data = {
        "props": {"pageProps": {"content": {
            "matchFacts": {"infoBox": {"Stadium": {"name": "Anfield", "city": "Liverpool", "country": "England"}, "Referee": {"text": "Some Ref"}, "Attendance": 53000}, "playerOfTheMatch": None, "events": {"events": []}},
            "weather": {"description": "Sunny", "temperature": 15},
            "lineup": {"homeTeam": None, "awayTeam": None, "lineupType": "lastStartingLineups"},
            "h2h": {"matches": None},
            "stats": None,
        }}}
    }

    async def fake_fetch_text(_url):
        return _next_data_html(next_data)

    monkeypatch.setattr(fotmob, "fetch_text", fake_fetch_text)
    details = asyncio.run(get_fotmob_match_details(match))
    assert details.venue_name == "Anfield"
    assert details.referee == "Some Ref"
    assert details.weather == "Sunny, 15°C"
    assert details.attendance == 53000
    assert details.note == "lineup is last known XI, not confirmed"
