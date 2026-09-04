"""365Scores scraper. Ported from src/sites/365scores.ts.

Module named `three65scores` since Python identifiers can't start with a
digit -- imported as `from football.sites import three65scores`.

Plain fetch works throughout, no browser needed. webws.365scores.com (the
actual data API) has no robots.txt at all (a 404) -- per RFC 9309 that
means no crawling restrictions apply. www.365scores.com's own robots.txt
has no /api/-style disallow either, and even explicitly allows team pages.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote

from .._jsmath import js_number_or, js_number_to_string, js_round, js_round_to
from ..http import fetch_json
from ..team_aliases import known_aliases_for
from ..team_name_match import name_query_variants, strip_diacritics
from ..types import (
    LineupPlayer,
    MatchDetails,
    MatchInfo,
    PlayerOfTheMatch,
    SquadMember,
    TeamProfile,
    TeamStanding,
    TimelineEvent,
)

_BASE = "https://webws.365scores.com/web"
_COMMON = "appTypeId=5&langId=1&timezoneName=UTC&userCountryId=190"


@dataclass
class _Competitor:
    id: int
    name: str
    name_for_url: str
    type: int


def _dedupe_variants(team_name: str) -> list[str]:
    """Diacritics/generic-suffix-stripped variants (team_name_match.py)
    plus any known alias (team_aliases.py), case-insensitively deduped so
    the search below doesn't repeat a request for the same query text."""
    seen = set()
    variants = []
    for variant in [*name_query_variants(team_name), *known_aliases_for(team_name)]:
        key = variant.lower()
        if key in seen:
            continue
        seen.add(key)
        variants.append(variant)
    return variants


async def _pool_competitors(variants: list[str]) -> list[dict[str, Any]]:
    """Every variant is queried and pooled BEFORE picking a winner -- e.g.
    querying "Queens Park Rangers" alone returns ['QPR', 'Queens Park
    Rangers (W)'], and stopping there picks the women's team (W) since
    it's the only one that forward-substring-matches the full query --
    "QPR" itself never gets compared against its own "qpr" alias because
    the loop already broke. Same for "Paris Saint Germain" resolving to
    "Paris Saint-Germain B" (the reserve team) instead of "PSG". Both
    confirmed live."""
    pool: dict[int, dict[str, Any]] = {}
    for variant in variants:
        data = await fetch_json(f"{_BASE}/search/?{_COMMON}&query={quote(variant)}&filter=all")
        for c in data.get("competitors") or []:
            pool.setdefault(c["id"], c)
    return list(pool.values())


def _as_competitor(c: dict[str, Any]) -> _Competitor:
    return _Competitor(id=c["id"], name=c["name"], name_for_url=c["nameForURL"], type=c["type"])


def _shortest(candidates: dict[int, dict[str, Any]]) -> _Competitor:
    return _as_competitor(min(candidates.values(), key=lambda c: len(c["name"])))


def _reverse_match(targets: list[str], competitors: list[dict[str, Any]]) -> _Competitor | None:
    """The real senior club's name is sometimes shorter than the query
    itself. A 4-char floor (same convention as stadiumdb.py) guards
    against a too-short name false-matching an unrelated longer query."""
    reverse_pool: dict[int, dict[str, Any]] = {}
    for target in targets:
        for c in competitors:
            if len(strip_diacritics(c["name"])) >= 4 and strip_diacritics(c["name"]).lower() in target:
                reverse_pool.setdefault(c["id"], c)
    return _shortest(reverse_pool) if reverse_pool else None


def _forward_match(targets: list[str], competitors: list[dict[str, Any]]) -> _Competitor | None:
    """Same 4-char floor, applied to the TARGET this time: a short alias
    like "nec" (kept for other sites' exact-match use, e.g. StadiumDB's
    literal "NEC" row) is too easy to false-positive as a forward
    substring probe here -- confirmed live, it matched "Necaxa" (a wholly
    unrelated Mexican club) and, being short, won the shortest-name
    tiebreak over the real, longer "N.E.C. Nijmegen"."""
    forward_pool: dict[int, dict[str, Any]] = {}
    for target in targets:
        if len(target) < 4:
            continue
        for c in competitors:
            if target in strip_diacritics(c["name"]).lower():
                forward_pool.setdefault(c["id"], c)
    return _shortest(forward_pool) if forward_pool else None


async def _find_team(team_name: str) -> _Competitor | None:
    """See team_name_match.py -- retries with diacritics/generic-suffix-
    stripped variants when the exact query returns nothing, same as
    soccerdesk.py. Split into several small helpers above purely to keep
    this function's own cognitive complexity readable (each helper is
    itself a documented, previously-live-confirmed fix -- see their own
    doc comments); the matching behavior is unchanged."""
    competitors = await _pool_competitors(_dedupe_variants(team_name))
    if not competitors:
        return None

    # Diacritic-insensitive, and checked against every known alias too
    # (not just the searched name) -- "QPR" only exactly matches the "qpr"
    # alias, not "Queens Park Rangers" itself.
    target_set = {strip_diacritics(v).lower().strip() for v in [team_name, *known_aliases_for(team_name)]}
    exact = next((c for c in competitors if strip_diacritics(c["name"]).lower() in target_set), None)
    if exact:
        return _as_competitor(exact)

    # Reverse and forward candidate matching are tried across EVERY known
    # alias, not just the original team_name, and candidates are POOLED
    # across all targets before picking (not returned as soon as any one
    # target matches something) -- confirmed live both matter: querying
    # "NEC Nijmegen" pools both "N.E.C. Nijmegen" (real club) and "NEC
    # Nijmegen Jeugd" (youth team); the punctuation in "N.E.C." breaks a
    # forward-substring match against the full alias "nec nijmegen", so
    # trying that target ALONE finds only the wrong youth team -- and
    # returning immediately on that match, before the shorter canonical
    # alias "nijmegen" (which matches both, and correctly prefers the
    # real club via the shortest-name tiebreak) ever gets a chance, is
    # exactly the bug this pooling avoids.
    targets = [strip_diacritics(v).lower().strip() for v in [team_name, *known_aliases_for(team_name)]]

    return _reverse_match(targets, competitors) or _forward_match(targets, competitors) or _shortest({c["id"]: c for c in competitors})


def _slugify(s: str) -> str:
    return re.sub(r"(?:^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", s.lower()))


@dataclass
class _MatchMeta:
    home_id: int
    away_id: int
    competition_id: int


# Match-detail lookups need home_id/away_id/competition_id, none of which
# fit MatchInfo -- cached here by game id (populated in get_matches, read
# in get_match_details, both called in the same process run by the
# orchestrator).
_match_meta_cache: dict[int, _MatchMeta] = {}


def _to_match_info(g: dict[str, Any]) -> MatchInfo:
    home = g["homeCompetitor"]
    away = g["awayCompetitor"]
    _match_meta_cache[g["id"]] = _MatchMeta(home_id=home["id"], away_id=away["id"], competition_id=g["competitionId"])

    finished = g.get("statusText") == "Ended"
    comp_slug = _slugify(g.get("competitionDisplayName") or "competition")
    match_slug = f"{_slugify(home['name'])}-{_slugify(away['name'])}-{home['id']}-{away['id']}-{g['competitionId']}"
    status_text = g.get("statusText")

    return MatchInfo(
        source="365scores",
        source_url=f"https://www.365scores.com/football/match/{comp_slug}-{g['competitionId']}/{match_slug}#id={g['id']}",
        competition=g.get("competitionDisplayName"),
        home_team=home["name"],
        away_team=away["name"],
        kickoff_utc=g.get("startTime"),
        venue=(g.get("venue") or {}).get("name"),
        status=("finished" if finished else "scheduled" if status_text == "Scheduled" else (status_text.lower() if status_text else None)),
        home_score=(js_round(home["score"]) if finished else None),
        away_score=(js_round(away["score"]) if finished else None),
        home_score_ht=None,
        away_score_ht=None,
        season=None,
        round=None,
        match_id=str(g["id"]),
    )


async def get365_scores_matches(team_name: str) -> list[MatchInfo]:
    """Combines two endpoints: recentForm (real match history, requested
    15 back) and games/current (a narrow window that also covers near-term
    upcoming fixtures) -- recentForm alone doesn't include future games,
    and games/current alone only covers a handful of games either side of
    "now"."""
    team = await _find_team(team_name)
    if team is None:
        raise ValueError(f'No 365scores team found matching "{team_name}"')

    recent, current = await asyncio.gather(
        fetch_json(f"{_BASE}/competitors/recentForm?{_COMMON}&competitor={team.id}&numOfGames=15"),
        fetch_json(f"{_BASE}/games/current/?{_COMMON}&competitors={team.id}&showOdds=false"),
    )

    by_id: dict[int, dict[str, Any]] = {}
    for g in [*(recent.get("games") or []), *(current.get("games") or [])]:
        by_id[g["id"]] = g
    return [_to_match_info(g) for g in by_id.values()]


def _parse_365_stat_value(raw: str | None) -> float | None:
    """365scores' per-player match stats come in three shapes, confirmed
    live: a plain number ("4"), a "successful/attempted (pct%)" fraction
    ("3/5 (60%)" -- the successful count is the useful figure, matching
    e.g. "Tackles Won"), and minutes with a trailing quote mark ("90'").
    Returns None (not 0) for anything that doesn't parse, since a missing
    stat category for a given player is "not tracked for them", not
    "genuinely zero"."""
    if not raw:
        return None
    raw = raw.strip().rstrip("'")
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    try:
        return float(raw)
    except ValueError:
        return None


def _stat_lookup(member: dict[str, Any]) -> dict[str, str]:
    return {s["name"]: s.get("value") for s in member.get("stats") or [] if s.get("name")}


def _real_rating(raw: float | None) -> float | None:
    """Confirmed live: 365scores uses -1 as a sentinel for "not enough
    playing time to generate a rating" (seen on a player who came on in
    90+5') rather than omitting the field -- a real match rating is never
    negative, so this normalizes the sentinel to null instead of passing
    it through as a fake negative rating."""
    return raw if raw is not None and raw >= 0 else None


def _extract_lineup_side(
    competitor: dict[str, Any] | None, name_by_id: dict[int, str], is_bench: bool = False
) -> list[LineupPlayer] | None:
    """status: 1 = Starting XI, 2 = Substitute (both used -- has a real
    `stats` array and a `substitution` time -- and unused, confirmed live:
    same status but no `stats`/`substitution` present), 3 = Missing
    (injured/unavailable, not part of the matchday squad), 4 = Management
    (the coach entry). Only 1 and 2 are lineup/bench members."""
    members = ((competitor or {}).get("lineups") or {}).get("members")
    if not members:
        return None
    target_status = 2 if is_bench else 1
    result = []
    for m in members:
        if m.get("status") != target_status:
            continue
        stats = _stat_lookup(m)

        def stat(name: str) -> float | None:
            return _parse_365_stat_value(stats.get(name))  # noqa: B023 - fully used within this same loop iteration, not stored for later

        def int_stat(name: str) -> int | None:
            value = stat(name)
            return int(value) if value is not None else None

        result.append(
            LineupPlayer(
                name=name_by_id.get(m["id"], "Unknown"),
                position=(m.get("position") or {}).get("name"),
                substitute=is_bench,
                minutes_played=int_stat("Minutes"),
                goals=int_stat("Goals"),
                assists=int_stat("Assists"),
                xg=stat("Expected Goals"),
                xa=stat("Expected Assists"),
                shots=int_stat("Total Shots"),
                shots_on_target=int_stat("Shots On Target"),
                tackles=int_stat("Tackles Won"),
                interceptions=int_stat("Interceptions"),
                fouls=int_stat("Fouls Made"),
                rating=_real_rating(m.get("ranking")),
                key_passes=int_stat("Key Passes"),
                shirt_number=None,
                age=None,
            )
        )
    return result if result else None


def _extract_player_of_the_match(home_competitor: dict[str, Any] | None, away_competitor: dict[str, Any] | None, name_by_id: dict[int, str]):
    """No single "player of the match" field exists on 365scores -- but
    every starter's AND every used substitute's own `ranking` (confirmed
    live: a real 0-10ish match rating, same concept as Sofascore's
    per-player rating) is already fetched here for the lineup/bench.
    Taking the single highest-ranked player across both sides is the same
    "closest honest equivalent" approach Sofascore's own
    extract_player_of_the_match uses (there: higher-rated of each side's
    own best-player pick). status 2 (Substitute) covers both used and
    unused subs -- an unused sub has no `ranking` at all, so the None
    check below excludes them without needing a separate check."""
    candidates = []
    for side in (home_competitor, away_competitor):
        for m in ((side or {}).get("lineups") or {}).get("members") or []:
            if m.get("status") in (1, 2) and _real_rating(m.get("ranking")) is not None:
                candidates.append(m)
    if not candidates:
        return None
    top = max(candidates, key=lambda m: m["ranking"])
    name = name_by_id.get(top["id"])
    if not name:
        return None
    return PlayerOfTheMatch(name=name, rating=str(top["ranking"]))



_EVENT_TYPE_NAMES: dict[int, str] = {1: "Goal", 1000: "Substitution"}


def _extract_timeline(events: list[dict[str, Any]] | None, home_id: int, name_by_id: dict[int, str]) -> list[TimelineEvent] | None:
    if not events:
        return None
    majors = [e for e in events if e.get("isMajor") or (e.get("eventType") or {}).get("id") == 1000]
    result = [
        TimelineEvent(
            minute=e.get("gameTime", 0),
            type=(e.get("eventType") or {}).get("name") or _EVENT_TYPE_NAMES.get((e.get("eventType") or {}).get("id"), f"type {(e.get('eventType') or {}).get('id')}"),
            detail=None,
            player=name_by_id.get(e.get("playerId")),
            team=("home" if e.get("competitorId") == home_id else "away"),
        )
        for e in majors
    ]
    return sorted(result, key=lambda e: e.minute)


def _extract_standing(rows: list[dict[str, Any]] | None, team_id: int) -> TeamStanding | None:
    row = next((r for r in (rows or []) if r["competitor"]["id"] == team_id), None)
    if row is None:
        return None

    def stat(key: str) -> float:
        stats_data = row.get("statsData") or []
        found = next((s for s in stats_data if s.get("key") == key), None)
        raw = found["value"] if found else row.get(key, 0)
        return js_number_or(str(raw), 0)

    return TeamStanding(
        position=row.get("position") or row.get("rank"),
        played=int(stat("gamePlayed")),
        wins=int(stat("gamesWon")),
        draws=int(stat("gamesEven")),
        losses=int(stat("gamesLost")),
        points=int(stat("points")),
        goal_diff=js_number_to_string(stat("ratio")),
        total_teams=(len(rows) if rows else None),
    )


async def _fetch_standings_for(team_id: int, competition_id: int) -> TeamStanding | None:
    try:
        data = await fetch_json(f"{_BASE}/standings/?{_COMMON}&competitions=&competitor={team_id}&live=false")
    except Exception:  # noqa: BLE001 - mirrors TS's .catch(() => null)
        return None
    standings = data.get("standings") or []
    table = next((s for s in standings if s.get("competitionId") == competition_id), None)
    if table is None and standings:
        table = standings[0]
    return _extract_standing((table or {}).get("rows"), team_id)


async def get365_scores_match_details(match: MatchInfo) -> MatchDetails:
    """No team-level match-stats (possession, shot totals) or head-to-head
    endpoint was found during research within reasonable effort -- rather
    than keep guessing endpoint names, those stay null here. Per-player
    stats (goals/assists/xg/xa/shots/tackles/rating) ARE available via
    each lineup member's own `stats` array and `ranking` field, and are
    populated in home_lineup/away_lineup/player_of_the_match. Venue/
    referee/lineups/timeline/standings are all confirmed working from real
    endpoints."""
    game_id = int(match.source_url.split("#id=")[1])
    meta = _match_meta_cache.get(game_id)
    if meta is None:
        raise ValueError("365scores match metadata not found -- get365_scores_matches() must run in the same process first")

    matchup_id = f"{meta.home_id}-{meta.away_id}-{meta.competition_id}"
    data = await fetch_json(f"{_BASE}/game/?{_COMMON}&gameId={game_id}&matchupId={matchup_id}")
    g = data["game"]

    name_by_id: dict[int, str] = {m["id"]: m["name"] for m in g.get("members") or []}
    home_lineup = _extract_lineup_side(g.get("homeCompetitor"), name_by_id)
    away_lineup = _extract_lineup_side(g.get("awayCompetitor"), name_by_id)
    home_bench = _extract_lineup_side(g.get("homeCompetitor"), name_by_id, is_bench=True)
    away_bench = _extract_lineup_side(g.get("awayCompetitor"), name_by_id, is_bench=True)
    player_of_the_match = _extract_player_of_the_match(g.get("homeCompetitor"), g.get("awayCompetitor"), name_by_id)

    home_standing, away_standing = await asyncio.gather(
        _fetch_standings_for(meta.home_id, meta.competition_id),
        _fetch_standings_for(meta.away_id, meta.competition_id),
    )

    officials = g.get("officials") or []

    return MatchDetails(
        **asdict(match),
        venue_name=(g.get("venue") or {}).get("name"),
        venue_city=None,
        venue_country=None,
        venue_lat=None,
        venue_lon=None,
        referee=(officials[0]["name"] if officials else None),
        referee_stats=None,
        attendance=(g.get("venue") or {}).get("attendance"),
        weather=None,
        weather_detail=None,
        head_to_head_summary=None,
        head_to_head_streaks=None,
        recent_meetings=None,
        home_lineup=home_lineup,
        away_lineup=away_lineup,
        home_bench=home_bench,
        away_bench=away_bench,
        home_formation=((g.get("homeCompetitor") or {}).get("lineups") or {}).get("formation"),
        away_formation=((g.get("awayCompetitor") or {}).get("lineups") or {}).get("formation"),
        home_team_country=None,
        away_team_country=None,
        home_manager=None,
        away_manager=None,
        home_manager_vs_away_club=None,
        away_manager_vs_home_club=None,
        standings_table=None,
        home_suspended_players=None,
        away_suspended_players=None,
        home_team_standing=home_standing,
        away_team_standing=away_standing,
        home_team_season_stats=None,
        away_team_season_stats=None,
        match_stats=None,
        event_timeline=_extract_timeline(g.get("events"), meta.home_id, name_by_id),
        set_piece_goals=None,
        shotmap_stats=None,
        lineup_confirmed=None,
        player_of_the_match=player_of_the_match,
        note="match stats and head-to-head not available from 365scores (no endpoint found)",
    )


async def get365_scores_team_profile(team_name: str) -> TeamProfile:
    """/web/squads/?competitors={id} gives age/position/height directly
    per player -- no injury status or transfers endpoint was found during
    research."""
    team = await _find_team(team_name)
    if team is None:
        raise ValueError(f'No 365scores team found matching "{team_name}"')

    data = await fetch_json(f"{_BASE}/squads/?{_COMMON}&competitors={team.id}")
    squads = data.get("squads") or []
    athletes = squads[0].get("athletes") if squads else []
    athletes = athletes or []

    squad: list[SquadMember] = [
        SquadMember(
            name=a["name"],
            role=(a.get("position") or {}).get("name"),
            injury=None,
            age=a.get("age"),
            market_value=None,
            season_stats=None,
            season_stats_source=None,
            defensive_stats=None,
            recent_usage=None,
        )
        for a in athletes
    ]

    ages = [s.age for s in squad if s.age is not None]

    return TeamProfile(
        source="365scores",
        team_name=team.name,
        squad=squad if squad else None,
        average_age=(js_round_to(sum(ages) / len(ages), 1) if ages else None),
        injuries=None,
        key_injuries=None,
        recent_transfers=None,
        missing_midfielders=None,  # computed centrally once search.py's orchestrator is ported
        missing_attackers=None,
        missing_defenders=None,
        missing_goalkeepers=None,
    )
