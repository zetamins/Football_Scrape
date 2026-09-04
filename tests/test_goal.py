import asyncio
import json

import pytest

from football.sites import goal
from football.sites.goal import (
    _apply_goal_event,
    _apply_substitution_event,
    _build_player_event_stats,
    _build_teams_index,
    _card_timeline_event,
    _extract_lineup_side,
    _extract_match_stats,
    _extract_next_data,
    _extract_standing,
    _extract_timeline,
    _find_best_team_match,
    _format_formation,
    _goal_timeline_event,
    _humanize_stat_type,
    _load_teams_index,
    _match_status,
    _substitution_timeline_event,
    _TeamIndexEntry,
    _timeline_event_for,
    _to_match_info,
    get_goal_match_details,
    get_goal_matches,
    get_goal_team_profile,
)


def _entry(id_, slug):
    return _TeamIndexEntry(id=id_, slug=slug, url=f"https://www.goal.com/en/team/{slug}/{id_}")


def test_liverpool_resolves_to_the_mens_team_not_the_womens():
    # Confirmed live: get_goal_matches("Liverpool") returned 36 fixtures,
    # ALL of them Liverpool FC Women's WSL/FA Cup matches -- none the
    # men's Premier League team. team_aliases.py's canonical alias for
    # "Liverpool" is "Liverpool FC", normalizing to "liverpool fc".
    # Goal.com has no "liverpool-fc" slug, so the exact-match branch
    # misses, but the SUBSTRING branch right after doesn't: "liverpool
    # fc" is contained in the normalized form of "liverpool-fc-women"
    # ("liverpool fc women"), so that becomes the first candidate tried
    # -- the men's team's own bare "liverpool" slug, a separate and more
    # precise entry, is never reached (the alias loop returns on the
    # first alias that yields any candidate).
    entries = [
        _entry("men123", "liverpool"),  # the real men's Premier League club
        _entry("women456", "liverpool-fc-women"),
    ]
    match = _find_best_team_match(entries, "Liverpool")
    assert match is not None
    assert match.id == "men123"
    assert match.slug == "liverpool"


def test_general_algorithm_prefers_a_later_aliass_exact_match_over_an_earlier_aliass_substring():
    # This is the structural fix itself, using a DIFFERENT known
    # collision shape than the Liverpool test above (team_aliases.py:
    # "leicester city" -> alias "leicester"): the canonical alias
    # ("leicester city", tried first via known_aliases_for's
    # canonical-first ordering) would substring-match a longer, wrong
    # entity ("leicester-city-academy") if checked in isolation, but the
    # exact-match pass now runs across EVERY alias before any substring
    # fallback runs for ANY of them, so the later, shorter alias's exact
    # match ("leicester" -> the real club's actual slug) wins regardless
    # of alias order.
    entries = [
        _entry("real", "leicester"),
        _entry("wrong", "leicester-city-academy"),
    ]
    match = _find_best_team_match(entries, "Leicester City")
    assert match is not None
    assert match.id == "real"


def test_other_teams_still_resolve_via_the_normal_alias_match():
    entries = [
        _entry("1", "arsenal"),
        _entry("2", "arsenal-women"),
    ]
    match = _find_best_team_match(entries, "Arsenal")
    assert match is not None
    assert match.id == "1"


def test_find_best_team_match_falls_back_to_substring_candidates():
    entries = [_entry("1", "some-totally-unrelated-club-2-fc"), _entry("2", "some-totally-unrelated-club-fc")]
    match = _find_best_team_match(entries, "Some Totally Unrelated Club")
    assert match is not None
    assert match.id == "2"  # shorter matching slug preferred


def test_find_best_team_match_falls_back_to_reverse_direction():
    entries = [_entry("1", "girona")]
    match = _find_best_team_match(entries, "Girona Futbol Club")
    assert match is not None
    assert match.id == "1"


def test_find_best_team_match_none_without_any_candidate():
    entries = [_entry("1", "totally-different-club")]
    assert _find_best_team_match(entries, "Some Unrelated Team") is None


# --- _extract_next_data ------------------------------------------------------------


def test_extract_next_data_parses_embedded_json():
    html = '<html><script id="__NEXT_DATA__" type="application/json">{"props": {"a": 1}}</script></html>'
    assert _extract_next_data(html)["props"]["a"] == 1


def test_extract_next_data_raises_when_marker_missing():
    import pytest

    with pytest.raises(ValueError, match="__NEXT_DATA__"):
        _extract_next_data("<html>no marker</html>")


# --- _match_status / _to_match_info -------------------------------------------------


def test_match_status_finished():
    assert _match_status(finished=True, status_raw="RESULT") == "finished"


def test_match_status_scheduled_for_fixture():
    assert _match_status(finished=False, status_raw="FIXTURE") == "scheduled"


def test_match_status_lowercases_other_raw_statuses():
    assert _match_status(finished=False, status_raw="LIVE") == "live"


def test_match_status_none_without_raw_status():
    assert _match_status(finished=False, status_raw=None) is None


def _raw_match(**overrides):
    base = {
        "status": "RESULT", "link": {"slug": "home-vs-away", "id": "12345"},
        "competition": {"name": "Premier League"}, "teamA": {"name": "Home FC"}, "teamB": {"name": "Away FC"},
        "startDate": "2026-01-01T15:00:00.000Z", "venue": {"name": "Home Stadium"}, "score": {"teamA": 2, "teamB": 1},
    }
    base.update(overrides)
    return base


def test_to_match_info_finished_match_has_score():
    m = _to_match_info(_raw_match())
    assert m.home_score == 2
    assert m.status == "finished"


def test_to_match_info_unplayed_fixture_has_no_score():
    m = _to_match_info(_raw_match(status="FIXTURE", score=None))
    assert m.home_score is None
    assert m.status == "scheduled"


# --- _build_player_event_stats / _apply_goal_event / _apply_substitution_event -----------


def test_apply_goal_event_credits_scorer_and_assist():
    stats: dict = {}

    def entry(pid):
        return stats.setdefault(pid, {"goals": 0, "assists": 0, "sub_on_minute": None, "sub_off_minute": None})

    _apply_goal_event({"scorer": {"id": "p1"}, "assist": {"id": "p2"}}, entry)
    assert stats["p1"]["goals"] == 1
    assert stats["p2"]["assists"] == 1


def test_apply_substitution_event_sets_on_and_off_minutes():
    stats: dict = {}

    def entry(pid):
        return stats.setdefault(pid, {"goals": 0, "assists": 0, "sub_on_minute": None, "sub_off_minute": None})

    _apply_substitution_event({"period": {"minute": 60}, "out": {"id": "p1"}, "in": {"id": "p2"}}, entry)
    assert stats["p1"]["sub_off_minute"] == 60
    assert stats["p2"]["sub_on_minute"] == 60


def test_build_player_event_stats_dispatches_by_typename():
    events = [
        {"__typename": "MatchGoalEvent", "scorer": {"id": "p1"}, "assist": None},
        {"__typename": "MatchSubstitutionEvent", "period": {"minute": 70}, "out": {"id": "p1"}, "in": {"id": "p3"}},
    ]
    stats = _build_player_event_stats(events)
    assert stats["p1"]["goals"] == 1
    assert stats["p1"]["sub_off_minute"] == 70


# --- _extract_lineup_side ------------------------------------------------------------


def test_extract_lineup_side_starting_default_90_minutes():
    side = {"lineup": [{"person": {"id": "p1", "name": "Player A"}, "shirtNumber": 9}]}
    players = _extract_lineup_side(side, {})
    assert players[0].minutes_played == 90


def test_extract_lineup_side_bench_unused_stays_none():
    side = {"substitutes": [{"person": {"id": "p2", "name": "Sub"}, "shirtNumber": 15}]}
    players = _extract_lineup_side(side, {}, is_bench=True)
    assert players[0].minutes_played is None


def test_extract_lineup_side_none_without_group():
    assert _extract_lineup_side(None, {}) is None


# --- _format_formation / _humanize_stat_type ------------------------------------------


def test_format_formation_joins_digits_with_hyphens():
    assert _format_formation("442") == "4-4-2"


def test_format_formation_none_without_input():
    assert _format_formation(None) is None


def test_humanize_stat_type_capitalizes_and_replaces_underscores():
    assert _humanize_stat_type("BALL_POSSESSION") == "Ball possession"


# --- _extract_match_stats --------------------------------------------------------------


def test_extract_match_stats_dedupes_across_categories():
    stats = {
        "summary": [{"type": "possession", "teamA": 60, "teamB": 40}],
        "attacking": [{"type": "possession", "teamA": 60, "teamB": 40}],  # duplicate -- skipped
    }
    items = _extract_match_stats(stats)
    assert len(items) == 1
    assert items[0].name == "Possession"


def test_extract_match_stats_none_without_stats():
    assert _extract_match_stats(None) is None
    assert _extract_match_stats({}) is None


# --- timeline event builders + _extract_timeline --------------------------------------


def test_goal_timeline_event_includes_assist():
    event = _goal_timeline_event({"scorer": {"name": "Scorer"}, "assist": {"name": "Assister"}}, 30, "home")
    assert event.detail == "Assist: Assister"


def test_card_timeline_event_distinguishes_red_and_yellow():
    red = _card_timeline_event({"type": "RED_CARD", "player": {"name": "P"}}, 60, "home")
    yellow = _card_timeline_event({"type": "YELLOW_CARD", "player": {"name": "P"}}, 60, "home")
    assert red.type == "Red Card"
    assert yellow.type == "Yellow Card"


def test_substitution_timeline_event_detail():
    event = _substitution_timeline_event({"in": {"name": "In Player"}, "out": {"name": "Out Player"}}, 70, "away")
    assert event.detail == "In Player on for Out Player"
    assert event.player == "Out Player"


def test_timeline_event_for_dispatches_correctly():
    event = _timeline_event_for("MatchGoalEvent", {"scorer": {"name": "S"}, "assist": None}, 10, "home")
    assert event.type == "Goal"


def test_timeline_event_for_none_for_unknown_typename():
    assert _timeline_event_for("SomeOtherEvent", {}, 10, "home") is None


def test_extract_timeline_sorted_by_minute():
    events = [
        {"__typename": "MatchGoalEvent", "period": {"minute": 60}, "side": "TEAM_A", "scorer": {"name": "S"}, "assist": None},
        {"__typename": "MatchGoalEvent", "period": {"minute": 10}, "side": "TEAM_B", "scorer": {"name": "S2"}, "assist": None},
    ]
    timeline = _extract_timeline(events)
    assert [e.minute for e in timeline] == [10, 60]
    assert timeline[0].team == "away"


def test_extract_timeline_none_without_events():
    assert _extract_timeline(None) is None
    assert _extract_timeline([]) is None


# --- _extract_standing -----------------------------------------------------------------


def test_extract_standing_finds_row_by_team_id():
    rankings = [{"team": {"id": "t1"}, "position": 3, "played": 20, "win": 12, "draw": 5, "lose": 3, "points": 41, "goalsDifference": 15}]
    standing = _extract_standing(rankings, "t1")
    assert standing.position == 3
    assert standing.goal_diff == "15"


def test_extract_standing_none_when_team_missing():
    assert _extract_standing([], "t1") is None
    assert _extract_standing(None, "t1") is None


# --- _build_teams_index / _load_teams_index (async, filesystem-touching) ---------------


_TEAMS_SITEMAP_XML = (
    '<loc>https://www.goal.com/en/team/liverpool/abc123</loc>'
    '<loc>https://www.goal.com/en/team/arsenal/def456</loc>'
)


def test_build_teams_index_parses_sitemap(monkeypatch):
    async def fake_fetch_text(_url):
        return _TEAMS_SITEMAP_XML

    monkeypatch.setattr(goal, "fetch_text", fake_fetch_text)
    entries = asyncio.run(_build_teams_index())
    assert entries[0].slug == "liverpool"
    assert entries[0].id == "abc123"
    assert entries[1].slug == "arsenal"


def test_load_teams_index_writes_seed_file_on_cache_miss(monkeypatch, tmp_path):
    async def fake_fetch_text(_url):
        return _TEAMS_SITEMAP_XML

    monkeypatch.setattr(goal, "fetch_text", fake_fetch_text)
    monkeypatch.setattr(goal, "data_dir", lambda: tmp_path)

    entries = asyncio.run(_load_teams_index())
    assert len(entries) == 2
    assert (tmp_path / "goal-teams.json").exists()


def test_load_teams_index_reads_existing_seed_file_without_fetching(monkeypatch, tmp_path):
    seed_path = tmp_path / "goal-teams.json"
    seed_path.write_text(json.dumps([{"id": "abc123", "slug": "liverpool", "url": "https://www.goal.com/en/team/liverpool/abc123"}]), encoding="utf-8")

    async def unexpected_fetch(_url):
        raise AssertionError("should not fetch -- seed file already exists")

    monkeypatch.setattr(goal, "fetch_text", unexpected_fetch)
    monkeypatch.setattr(goal, "data_dir", lambda: tmp_path)

    entries = asyncio.run(_load_teams_index())
    assert entries == [_entry("abc123", "liverpool")]


# --- get_goal_matches (async) -------------------------------------------------------------


def _next_data_html(payload: dict) -> str:
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script></html>'


def _seed_index(tmp_path, monkeypatch, entries):
    seed_path = tmp_path / "goal-teams.json"
    seed_path.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr(goal, "data_dir", lambda: tmp_path)


def test_get_goal_matches_raises_when_team_not_found(monkeypatch, tmp_path):
    _seed_index(tmp_path, monkeypatch, [])
    with pytest.raises(ValueError, match="No Goal.com team found"):
        asyncio.run(get_goal_matches("Some Unknown Club"))


def test_get_goal_matches_skips_unconfirmed_opponent_fixtures(monkeypatch, tmp_path):
    _seed_index(tmp_path, monkeypatch, [{"id": "abc123", "slug": "liverpool", "url": "https://www.goal.com/en/team/liverpool/abc123"}])

    next_data = {"props": {"pageProps": {"content": {"matches": [
        _raw_match(link={"slug": "home-vs-away", "id": 1}),
        _raw_match(link={"slug": "cup-draw-tbd", "id": 2}, teamA=None),
    ]}}}}

    async def fake_fetch_text(_url):
        return _next_data_html(next_data)

    monkeypatch.setattr(goal, "fetch_text", fake_fetch_text)
    matches = asyncio.run(get_goal_matches("Liverpool"))
    assert len(matches) == 1
    assert matches[0].home_team == "Home FC"


# --- get_goal_match_details (async) --------------------------------------------------------


def test_get_goal_match_details_builds_full_details(monkeypatch):
    from football.types import MatchInfo

    match = MatchInfo(
        source="goal", source_url="https://www.goal.com/en/match/home-vs-away/1", competition="Premier League",
        home_team="Home FC", away_team="Away FC", kickoff_utc="2026-01-01T15:00:00.000Z", venue=None,
        status="scheduled", home_score=None, away_score=None, home_score_ht=None, away_score_ht=None,
        season=None, round=None, match_id="1",
    )
    next_data = {
        "props": {"pageProps": {"content": {
            "match": {
                "teamA": {"id": "t1"}, "teamB": {"id": "t2"},
                "venue": {"name": "Home Stadium", "latitude": 51.555, "longitude": -0.106},
                "lineups": {}, "events": [], "stats": None,
            },
            "summaryStandings": None,
            "h2h": {"stats": {"teamAWins": 3, "teamBWins": 1, "draws": 2}},
        }}}
    }

    async def fake_fetch_text(_url, _client=None):
        return _next_data_html(next_data)

    monkeypatch.setattr(goal, "fetch_text", fake_fetch_text)
    details = asyncio.run(get_goal_match_details(match))
    assert details.venue_name == "Home Stadium"
    # Real bug found live (2026-09-04): venue.latitude/longitude are
    # present on every match checked, but this function used to hardcode
    # venue_lat/venue_lon to None regardless -- merge.py explicitly lists
    # these as independently fallback-able fields, so this source silently
    # discarded real, usable data.
    assert details.venue_lat == 51.555
    assert details.venue_lon == -0.106
    assert details.head_to_head_summary.home_wins == 3
    assert details.referee is None
    assert "referee not populated" in details.note


def test_get_goal_match_details_venue_lat_lon_none_when_absent(monkeypatch):
    from football.types import MatchInfo

    match = MatchInfo(
        source="goal", source_url="https://www.goal.com/en/match/home-vs-away/1", competition="Premier League",
        home_team="Home FC", away_team="Away FC", kickoff_utc="2026-01-01T15:00:00.000Z", venue=None,
        status="scheduled", home_score=None, away_score=None, home_score_ht=None, away_score_ht=None,
        season=None, round=None, match_id="1",
    )
    next_data = {
        "props": {"pageProps": {"content": {
            "match": {
                "teamA": {"id": "t1"}, "teamB": {"id": "t2"},
                "venue": {"name": "Home Stadium"},
                "lineups": {}, "events": [], "stats": None,
            },
            "summaryStandings": None,
            "h2h": None,
        }}}
    }

    async def fake_fetch_text(_url, _client=None):
        return _next_data_html(next_data)

    monkeypatch.setattr(goal, "fetch_text", fake_fetch_text)
    details = asyncio.run(get_goal_match_details(match))
    assert details.venue_lat is None
    assert details.venue_lon is None


# --- get_goal_team_profile (async) ---------------------------------------------------------


def test_get_goal_team_profile_raises_when_team_not_found(monkeypatch, tmp_path):
    _seed_index(tmp_path, monkeypatch, [])
    with pytest.raises(ValueError, match="No Goal.com team found"):
        asyncio.run(get_goal_team_profile("Some Unknown Club"))


def test_get_goal_team_profile_builds_squad_with_season_stats(monkeypatch, tmp_path):
    _seed_index(tmp_path, monkeypatch, [{"id": "abc123", "slug": "liverpool", "url": "https://www.goal.com/en/team/liverpool/abc123"}])

    next_data = {
        "props": {"pageProps": {"content": {
            "team": {"name": "Liverpool FC"},
            "squad": {"players": [
                {"player": {"name": "A. Becker", "position": "Goalkeeper"}, "stats": {"appearances": 20, "goals": 0, "assists": 0, "yellowCards": 1, "redCards": 0}},
                {"player": {"name": "M. Salah", "position": "Forward"}, "stats": None},
            ]},
        }}}
    }

    async def fake_fetch_text(_url):
        return _next_data_html(next_data)

    monkeypatch.setattr(goal, "fetch_text", fake_fetch_text)
    profile = asyncio.run(get_goal_team_profile("Liverpool"))
    assert profile.team_name == "Liverpool FC"
    assert len(profile.squad) == 2
    assert profile.squad[0].season_stats.appearances == 20
    assert profile.squad[1].season_stats is None
