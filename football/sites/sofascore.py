"""Sofascore scraper. Ported from src/sites/sofascore.ts -- the user's
confirmed-working reference implementation; behavior preserved exactly,
only the language changed.

Sofascore blocks plain HTTP clients at the CDN (Cloudflare) level, so a
real headless browser is required just to load any page, including
robots.txt itself. Its robots.txt does NOT disallow /api/ (unlike Fotmob
and Livescore) -- only standings pages and dated archive URLs are
disallowed -- so hitting the same-origin JSON endpoints the site's own
pages call (search, team events) is in scope here.

Cloudflare's challenge response time is variable -- observed anywhere from
~2s to 40s+ under repeated automated traffic -- so every navigation here
goes through retry_with_backoff rather than a single fixed-timeout attempt.
Requests within a session are also paced ~800ms apart (see sleep() calls
below) and the orchestrator (search.py, once ported) should never run this
concurrently with another source, to keep our own traffic pattern from
looking bursty.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from playwright.async_api import Page

from .._jsmath import js_round_to, js_to_fixed
from ..browser import launch_browser
from ..fetch_log import record_failure
from ..form import parse_leading_int
from ..odds_math import fractional_to_decimal, implied_and_fair_percentages, implied_and_fair_percentages_2way
from ..retry import retry_with_backoff
from ..team_aliases import canonical_for
from ..team_aliases import normalize as _normalize_alias
from ..team_name_match import normalize_for_match as _normalize
from ..types import (
    BettingOdds,
    HeadToHeadSummary,
    LineupPlayer,
    ManagerClubRecord,
    ManagerInfo,
    MatchDetails,
    MatchInfo,
    MatchStatItem,
    MissingPlayer,
    PlayerOfTheMatch,
    RefereeStats,
    SeasonPlayerStats,
    SetPieceGoalCounts,
    SetPieceGoals,
    ShotmapSideStats,
    ShotmapStats,
    SquadMember,
    StandingsTableRow,
    TeamProfile,
    TeamSeasonStats,
    TeamStanding,
    TimelineEvent,
    TransferRecord,
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def _sleep(ms: int) -> None:
    await asyncio.sleep(ms / 1000)


async def _warm_up(page: Page) -> None:
    await retry_with_backoff(
        lambda: page.goto("https://www.sofascore.com/", wait_until="domcontentloaded", timeout=30000)
    )


# A CDN-level block answers 200 with {"error":{"code":403,...}} (see
# _find_team) -- a 404 in the same shape just means "not published yet".
_BLOCK_ERROR_CODES = frozenset({403, 429})


async def _fetch_json(page: Page, url: str) -> Any:
    async def attempt() -> Any:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        text = await page.evaluate("() => document.body.innerText")
        return json.loads(text)

    try:
        data = await retry_with_backoff(attempt)
    except Exception as err:
        record_failure(url, err)
        raise
    if isinstance(data, dict) and isinstance(data.get("error"), dict) and data["error"].get("code") in _BLOCK_ERROR_CODES:
        record_failure(url, f"HTTP {data['error']['code']} {data['error'].get('reason', 'blocked')}")
    return data


async def _fetch_json_optional(page: Page, url: str) -> Any | None:
    """Sofascore's 404 responses are still valid JSON
    (`{"error":{"code":404,...}}`), so goto()/json.loads() never raises for
    them -- this is for endpoints like lineups/statistics that are only
    published closer to/after kickoff, where a 404 means "not published
    yet", not a fetch failure worth retrying."""
    data = await _fetch_json(page, url)
    if isinstance(data, dict) and data.get("error"):
        return None
    return data


def _to_iso_z(dt: datetime) -> str:
    """Match JS's Date.toISOString() exactly (always 3-digit milliseconds,
    trailing "Z") -- Python's isoformat() omits the fractional part
    entirely when microsecond == 0, which every other source's date
    strings (and any downstream string-prefix comparison) don't expect."""
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class _SofascoreTeam:
    id: int
    name: str
    slug: str


# Normalized alias strings whose canonical translation (team_aliases.py)
# is confirmed live to NOT exist on Sofascore's own search, even though
# the alias itself does -- see _find_team's docstring for the Lommel case.
_SOFASCORE_STALE_CANONICAL: frozenset[str] = frozenset({
    "lommel sk", "lommel",
    # "internazionale" (the canonical full name) returns an unrelated
    # Swedish club, "FC Stockholm Internazionale", as Sofascore's own
    # top/only match -- confirmed live, consistently reproducible. The
    # short alias "inter" correctly finds the real Milan club instead,
    # the reverse of the usual canonical-is-better case.
    "inter",
    # "Brighton and Hove Albion" (the canonical full name) finds ONLY the
    # U21 side on Sofascore -- confirmed live, no senior-team result at
    # all for that exact phrase. The short alias "brighton" correctly
    # finds the real senior club instead, so these ALIASES (not the
    # canonical itself, which is never the redirect target here) must
    # stay unredirected.
    "brighton", "brighton hove albion",
})

# Sofascore-specific query overrides: normalized input -> the exact query
# string Sofascore's own search needs, for cases neither the canonical
# name nor an existing team_aliases.py alias reaches. Checked BEFORE the
# canonical_for()-based logic below, so it also covers cases where the
# canonical itself is the searched name (team_aliases.py's alias list
# only helps when a non-canonical alias is what's searched).
_SOFASCORE_QUERY_OVERRIDE: dict[str, str] = {
    # "Amedspor" (the canonical) matches two unrelated German/Swiss clubs
    # first on Sofascore -- confirmed live. "Amed Sportif" (a
    # team_aliases.py alias, not the canonical) correctly finds the real
    # Turkish club instead -- the reverse of the usual direction, since
    # canonical_for() only redirects a non-canonical alias to canonical,
    # never the other way.
    "amedspor": "amed sportif",
    # Neither "Estrela" nor the canonical "Estrela da Amadora" ranks the
    # real senior club first on Sofascore (both return B/C reserve teams
    # ahead of it) -- confirmed live. "Estrela Amadora" (without "da") is
    # a third, distinct spelling that does.
    "estrela": "estrela amadora",
    "estrela da amadora": "estrela amadora",
}


async def _find_team(page: Page, team_name: str) -> _SofascoreTeam | None:
    """On Vercel specifically, this endpoint reliably came back
    `{"error":{"code":403,"reason":"challenge"}}` in the original TS
    project -- Sofascore/Cloudflare actively identifying datacenter IP
    ranges. Not applicable here (no server deployment), kept as historical
    context: this scraper is meant to run from a normal residential/
    non-datacenter connection.

    Exactly one search request, no retry -- matches the original TS
    findTeam() exactly (a prior version of this function added a 3-attempt
    retry-with-backoff loop on the hypothesis that an empty search result
    was a transient rate-limit; confirmed live it's actually a CDN-level
    403 block instead, which a retry doesn't clear -- it only sends more
    requests at an already-blocked connection. Reverted to match the
    original's single-attempt behavior exactly, per explicit instruction
    to not deviate from it here.

    Confirmed live: an actual CDN-level block returns 200 OK with a JSON
    body of `{"error":{"code":403,"reason":"Forbidden"}}` -- no "results"
    key at all -- rather than a real HTTP error page/status _fetch_json
    would raise on. Distinguished from a genuine empty search below so a
    block surfaces as what it is (no extra requests either way -- this is
    purely a clearer error message on the one response already fetched)."""
    # Sofascore's own search handles a full canonical name much better
    # than an abbreviated one -- confirmed live: "Nott'm Forest" and
    # "Paris SG" (football-data.co.uk's own short forms) both return no
    # team result at all, while "Nottingham Forest"/"Paris Saint-Germain"
    # resolve immediately. Swapping in the canonical form (team_aliases.py)
    # ONLY when team_name is a recognized alias -- not on every call, and
    # never more than the one search request below -- so this is
    # unaffected by, and doesn't reintroduce, the no-retry rule above.
    #
    # Not universal, though -- confirmed live this backfires for "Lommel
    # SK": team_aliases.py's canonical for that club is "Lommel United"
    # (the real current name, confirmed via 365Scores/StadiumDB), but
    # Sofascore's own search still only recognizes the old "Lommel SK"
    # name and returns nothing for "Lommel United" at all. Excluded here
    # rather than changed project-wide, since the canonical choice is
    # correct for every other site that consults team_aliases.py.
    normalized_input = _normalize_alias(team_name)
    if normalized_input in _SOFASCORE_QUERY_OVERRIDE:
        query = _SOFASCORE_QUERY_OVERRIDE[normalized_input]
    else:
        canonical = canonical_for(team_name)
        query = canonical if (canonical != normalized_input and normalized_input not in _SOFASCORE_STALE_CANONICAL) else team_name
    data = await _fetch_json(
        page, f"https://www.sofascore.com/api/v1/search/all?q={quote(query)}&page=0"
    )
    if isinstance(data, dict) and data.get("error"):
        error = data["error"]
        raise ValueError(
            f'Sofascore search blocked for "{team_name}": '
            f'{error.get("code", "unknown")} {error.get("reason", "unknown")}'
        )
    hit = next((r for r in data.get("results", []) if r.get("type") == "team"), None)
    if not hit:
        return None
    entity = hit["entity"]
    return _SofascoreTeam(id=entity["id"], name=entity["name"], slug=entity["slug"])


def _to_match_info(e: dict[str, Any]) -> MatchInfo:
    home_score = e.get("homeScore") or {}
    away_score = e.get("awayScore") or {}
    tournament = e.get("tournament") or {}
    status = e.get("status") or {}
    season = e.get("season") or {}
    round_info = e.get("roundInfo") or {}
    kickoff = datetime.fromtimestamp(e["startTimestamp"], tz=UTC)
    return MatchInfo(
        source="sofascore",
        source_url=f"https://www.sofascore.com/event/{e['slug']}/{e['id']}",
        competition=tournament.get("name"),
        home_team=e["homeTeam"]["name"],
        away_team=e["awayTeam"]["name"],
        kickoff_utc=_to_iso_z(kickoff),
        venue=None,
        status=status.get("type"),
        home_score=home_score.get("current"),
        away_score=away_score.get("current"),
        home_score_ht=home_score.get("period1"),
        away_score_ht=away_score.get("period1"),
        # Undefined (not just absent) for friendlies/cups with no round.
        season=season.get("name"),
        round=round_info.get("round"),
        match_id=str(e["id"]),
    )


async def get_sofascore_matches(team_name: str) -> list[MatchInfo]:
    async with launch_browser() as browser:
        context = await browser.new_context(user_agent=_USER_AGENT)
        page = await context.new_page()
        await _warm_up(page)

        team = await _find_team(page, team_name)
        if team is None:
            raise ValueError(f'No Sofascore team found matching "{team_name}"')

        await _sleep(800)
        next_data = await _fetch_json(page, f"https://www.sofascore.com/api/v1/team/{team.id}/events/next/0")
        await _sleep(800)
        last_data = await _fetch_json(page, f"https://www.sofascore.com/api/v1/team/{team.id}/events/last/0")

        events = [*next_data.get("events", []), *last_data.get("events", [])]
        return [_to_match_info(e) for e in events]


# side.players carries the FULL matchday squad (starting XI + bench, both
# used and unused subs) -- confirmed live: a 20-player array for a normal
# matchday (11 + 9), each with its own `substitute` boolean and (once
# played) a `statistics.minutesPlayed`. Filtering here keeps home_lineup/
# away_lineup meaning exactly "starting XI" as every existing caller
# already assumes -- see _extract_bench below for the other half.
def _age_from_timestamp(ts: int | None) -> int | None:
    if not ts:
        return None
    return int((datetime.now(tz=UTC).timestamp() - ts) / (365.25 * 24 * 3600))


def _extract_lineup_player(p: dict[str, Any], substitute: bool) -> LineupPlayer:
    s = p.get("statistics") or {}
    return LineupPlayer(
        name=p["player"]["name"],
        position=p["player"].get("position"),
        substitute=substitute,
        minutes_played=s.get("minutesPlayed"),
        goals=s.get("goals"),
        assists=s.get("goalAssist"),
        xg=s.get("expectedGoals"),
        xa=s.get("expectedAssists"),
        shots=s.get("totalShots"),
        shots_on_target=s.get("onTargetScoringAttempt"),
        tackles=s.get("totalTackle"),
        interceptions=s.get("interceptionWon"),
        fouls=s.get("fouls"),
        rating=s.get("rating"),
        key_passes=s.get("keyPass"),
        shirt_number=(int(p["shirtNumber"]) if p.get("shirtNumber") is not None else None),
        age=_age_from_timestamp(p["player"].get("dateOfBirthTimestamp")),
    )


def _extract_lineup(side: dict[str, Any] | None) -> list[LineupPlayer] | None:
    if not side or not side.get("players"):
        return None
    return [_extract_lineup_player(p, False) for p in side["players"] if p.get("substitute") is False]


def _extract_bench(side: dict[str, Any] | None) -> list[LineupPlayer] | None:
    if not side or not side.get("players"):
        return None
    bench = [p for p in side["players"] if p.get("substitute") is True]
    if not bench:
        return None
    return [_extract_lineup_player(p, True) for p in bench]


def _extract_missing_players(side: dict[str, Any] | None) -> list[MissingPlayer] | None:
    """Confirmed live: `description` is inconsistently either a category
    slug ("coach_decision") or a real description ("Knee Injury") -- see
    MissingPlayer's doc comment. The numeric `reason` code has no
    published lookup table and is dropped."""
    missing = (side or {}).get("missingPlayers")
    if not missing:
        return None
    return [
        MissingPlayer(
            name=m["player"]["name"],
            description=m.get("description"),
            expected_return=m.get("expectedEndDate"),
        )
        for m in missing
    ]


def _extract_referee_stats(referee: dict[str, Any] | None) -> RefereeStats | None:
    if not referee or not referee.get("games"):
        return None
    return RefereeStats(
        games=referee["games"],
        yellow_cards=referee.get("yellowCards", 0),
        red_cards=referee.get("redCards", 0),
        yellow_cards_per_game=js_to_fixed(referee.get("yellowCards", 0) / referee["games"], 1),
        penalties_awarded=None,  # computed centrally once search.py's orchestrator is ported
        home_away_bias=None,
        fouls_per_game=None,
    )


def _extract_season_stats(data: dict[str, Any] | None) -> TeamSeasonStats | None:
    s = (data or {}).get("statistics")
    if not s:
        return None
    return TeamSeasonStats(
        goals_scored=s.get("goalsScored", 0),
        goals_conceded=s.get("goalsConceded", 0),
        clean_sheets=s.get("cleanSheets", 0),
        yellow_cards=s.get("yellowCards", 0),
        red_cards=s.get("redCards", 0),
        average_ball_possession=s.get("averageBallPossession"),
    )


def _extract_standing(rows: list[dict[str, Any]] | None, team_id: int) -> TeamStanding | None:
    row = next((r for r in (rows or []) if r["team"]["id"] == team_id), None)
    if row is None:
        return None
    return TeamStanding(
        position=row["position"],
        played=row["matches"],
        wins=row["wins"],
        draws=row["draws"],
        losses=row["losses"],
        points=row["points"],
        goal_diff=row["scoreDiffFormatted"],
        total_teams=len(rows) if rows else None,
    )


def _extract_streaks(streaks: dict[str, Any] | None) -> list[str] | None:
    items = (streaks or {}).get("head2head")
    if not items:
        return None
    return [f"{s['name']} ({s['team']}): {s['value']}" for s in items]


def _extract_match_stats(stats: dict[str, Any] | None) -> list[MatchStatItem] | None:
    groups = ((stats or {}).get("statistics") or [{}])[0].get("groups") if stats else None
    if not groups:
        return None
    return [
        MatchStatItem(name=it["name"], home=it["home"], away=it["away"])
        for g in groups
        for it in g["statisticsItems"]
    ]


def _extract_player_of_the_match(best: dict[str, Any] | None) -> PlayerOfTheMatch | None:
    """Sofascore has no single "player of the match" field, only a best
    player per side -- taking the higher-rated of the two as the closest
    equivalent."""
    home = (best or {}).get("bestHomeTeamPlayer")
    away = (best or {}).get("bestAwayTeamPlayer")
    candidates = [c for c in (home, away) if c]
    if not candidates:
        return None
    top = max(candidates, key=lambda c: float(c.get("value", 0)))
    return PlayerOfTheMatch(name=top["player"]["name"], rating=top.get("value"))


_NON_EVENT_INCIDENT_TYPES = frozenset({
    "period",  # HT/FT markers, not real match events
    # Added-time announcements ("6 minutes added"), confirmed live 2026-09-04
    # -- shape is {"length": 6, "time": 90, "addedTime": 0, "incidentType":
    # "injuryTime", "reversedPeriodTime": 1}, no player/team at all, so
    # without this filter it produced a meaningless timeline entry (minute
    # 90, type "injuryTime", no player, no team) -- same category "period"
    # was already excluded for.
    "injuryTime",
})


def _extract_incidents(incidents: dict[str, Any] | None) -> list[TimelineEvent] | None:
    """"period"/"injuryTime" incidents are clock markers, not real match
    events -- filtered out."""
    items = [i for i in (incidents or {}).get("incidents", []) if i.get("incidentType") not in _NON_EVENT_INCIDENT_TYPES]
    if not items:
        return None
    result = []
    for i in items:
        is_home = i.get("isHome")
        team = {True: "home", False: "away"}.get(is_home)
        player = (i.get("player") or {}).get("name") or (i.get("playerIn") or {}).get("name")
        result.append(
            TimelineEvent(
                minute=i.get("time", 0),
                type=i.get("incidentType", "unknown"),
                detail=i.get("incidentClass") or i.get("reason"),
                player=player,
                team=team,
            )
        )
    return result


def _empty_goal_counts() -> SetPieceGoalCounts:
    return SetPieceGoalCounts(corner=0, penalty=0, free_kick=0)


def _extract_set_piece_goals(shotmap: dict[str, Any] | None) -> SetPieceGoals:
    """Confirmed live: shotmap's own `situation` field on a goal-type shot
    carries "corner", "penalty", "set-piece" (direct free-kicks) alongside
    open-play values ("regular", "assisted", "fast-break") -- a real
    classification the incidents/goal-events endpoint doesn't have. Only
    present once a match has actually been played -- empty (not null) for
    the not-yet-played upcoming match, same as other match-in-progress
    fields."""
    shots = (shotmap or {}).get("shotmap", [])
    home = _empty_goal_counts()
    away = _empty_goal_counts()
    for s in shots:
        if s.get("shotType") != "goal":
            continue
        side = home if s.get("isHome") else away
        situation = s.get("situation")
        if situation == "corner":
            side.corner += 1
        elif situation == "penalty":
            side.penalty += 1
        elif situation == "set-piece":
            side.free_kick += 1
    return SetPieceGoals(home=home, away=away)


def _empty_shotmap_side_stats() -> ShotmapSideStats:
    return ShotmapSideStats(non_penalty_xg=0, set_piece_xg=0, penalties_awarded=0)


def _extract_shotmap_stats(shotmap: dict[str, Any] | None) -> ShotmapStats:
    """Same shotmap fetch/loop as _extract_set_piece_goals, a different
    rollup: non-penalty xG (every shot except penalty-situation ones),
    set-piece xG (corner/penalty/direct-free-kick situations), and a raw
    count of penalty-situation shots regardless of outcome (goal, miss, or
    save -- "how often this team wins a penalty", not just how often they
    score one)."""
    shots = (shotmap or {}).get("shotmap", [])
    home = _empty_shotmap_side_stats()
    away = _empty_shotmap_side_stats()
    for s in shots:
        side = home if s.get("isHome") else away
        xg = s.get("xg") if isinstance(s.get("xg"), (int, float)) else 0
        situation = s.get("situation")
        if situation != "penalty":
            side.non_penalty_xg += xg
        if situation in ("corner", "penalty", "set-piece"):
            side.set_piece_xg += xg
        if situation == "penalty":
            side.penalties_awarded += 1
    home.non_penalty_xg = js_round_to(home.non_penalty_xg, 3)
    away.non_penalty_xg = js_round_to(away.non_penalty_xg, 3)
    home.set_piece_xg = js_round_to(home.set_piece_xg, 3)
    away.set_piece_xg = js_round_to(away.set_piece_xg, 3)
    return ShotmapStats(home=home, away=away)


def _extract_manager(raw_manager: dict[str, Any] | None) -> ManagerInfo | None:
    if not raw_manager or not raw_manager.get("name"):
        return None
    return ManagerInfo(
        name=raw_manager["name"],
        country=(raw_manager.get("country") or {}).get("name"),
        appointed_date=None,
        previous_manager=None,
        recent_appointment=None,
    )


def _manager_event_outcome(ev: dict[str, Any], target: str) -> str | None:
    """Extracted from _fetch_manager_club_record to keep its own
    cognitive complexity down (python:S3776); behavior unchanged.
    Returns "win"/"draw"/"loss" for the manager's team in this event, or
    None if the event should be skipped (unfinished, ambiguous opponent
    match, or missing score) -- same cases the original loop's
    `continue` handled."""
    if (ev.get("status") or {}).get("type") != "finished":
        return None
    home_is_opponent = _normalize((ev.get("homeTeam") or {}).get("name", "")) == target
    away_is_opponent = _normalize((ev.get("awayTeam") or {}).get("name", "")) == target
    if home_is_opponent == away_is_opponent:
        return None  # neither, or ambiguous
    home_goals = (ev.get("homeScore") or {}).get("current")
    away_goals = (ev.get("awayScore") or {}).get("current")
    if home_goals is None or away_goals is None:
        return None
    manager_goals = away_goals if home_is_opponent else home_goals
    opponent_goals = home_goals if home_is_opponent else away_goals
    if manager_goals > opponent_goals:
        return "win"
    if manager_goals < opponent_goals:
        return "loss"
    return "draw"


async def _fetch_manager_club_record(
    page: Page, raw_manager: dict[str, Any] | None, opponent_club: str
) -> ManagerClubRecord | None:
    """See ManagerClubRecord's doc comment for exactly what this is (and
    isn't). The manager's own event history is scanned for finished
    matches against opponent_club; since a manager can't be in charge of
    both sides in the same match, whichever team ISN'T the opponent is
    treated as "his" team."""
    if not raw_manager or not raw_manager.get("id") or not raw_manager.get("name"):
        return None
    data = await _fetch_json_optional(
        page, f"https://www.sofascore.com/api/v1/manager/{raw_manager['id']}/events/last/0"
    )
    events = (data or {}).get("events", [])
    target = _normalize(opponent_club)
    outcomes = [o for ev in events if (o := _manager_event_outcome(ev, target)) is not None]
    sample_size = len(outcomes)
    wins = outcomes.count("win")
    draws = outcomes.count("draw")
    losses = outcomes.count("loss")
    return ManagerClubRecord(
        manager_name=raw_manager["name"],
        opponent_club=opponent_club,
        sample_size=sample_size,
        wins=wins,
        draws=draws,
        losses=losses,
    )


async def _fetch_standings_and_season_stats(
    page: Page, e: dict[str, Any], ut_id: int | None, season_id: int | None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Returns (standings, home_season_stats, away_season_stats). Extracted
    from get_sofascore_match_details to keep its own cognitive complexity
    down (python:S3776); behavior unchanged -- only fetched when the
    event resolves to a tournament+season (not every competition has a
    league table, e.g. friendlies/one-off cups)."""
    if not (ut_id and season_id):
        return None, None, None
    await _sleep(800)
    standings = await _fetch_json_optional(
        page, f"https://www.sofascore.com/api/v1/unique-tournament/{ut_id}/season/{season_id}/standings/total"
    )

    # Team-level season stats (goals, cards, possession) -- found by
    # observing the team page's own "Statistics" tab network calls,
    # same same-origin /api/ pattern as everything else here.
    await _sleep(800)
    home_season_stats = await _fetch_json_optional(
        page,
        f"https://www.sofascore.com/api/v1/team/{e['homeTeam']['id']}/unique-tournament/{ut_id}/season/{season_id}/statistics/overall",
    )
    await _sleep(800)
    away_season_stats = await _fetch_json_optional(
        page,
        f"https://www.sofascore.com/api/v1/team/{e['awayTeam']['id']}/unique-tournament/{ut_id}/season/{season_id}/statistics/overall",
    )
    return standings, home_season_stats, away_season_stats


def _summary_from_duel(duel: dict[str, Any] | None) -> HeadToHeadSummary | None:
    """Extracted from get_sofascore_match_details -- shared by both
    head_to_head_summary (teamDuel) and manager_duel (managerDuel), which
    have the same shape; behavior unchanged."""
    if not duel:
        return None
    home_wins = duel.get("homeWins", 0)
    away_wins = duel.get("awayWins", 0)
    draws = duel.get("draws", 0)
    return HeadToHeadSummary(
        home_wins=home_wins, away_wins=away_wins, draws=draws,
        sample_size=home_wins + away_wins + draws,
    )


def _standings_table_from(standing_rows: list[dict[str, Any]] | None) -> list[StandingsTableRow] | None:
    """Extracted from get_sofascore_match_details to keep its own
    cognitive complexity down (python:S3776).

    goals_for/against/difference confirmed live against the raw
    standings row shape: Sofascore's actual keys are scoresFor/
    scoresAgainst/scoreDiffFormatted (the last pre-formatted as a
    string, "+8"/"-9") -- goalsFor/goalsAgainst/goalDiff (the previous
    lookup keys) don't exist in the payload at all, so these three were
    always silently None regardless of how far into the season the
    table was. _extract_standing (TeamStanding, above) already used the
    correct scoreDiffFormatted key; this function just had the wrong
    guesses. "form" isn't a bug -- confirmed absent from this endpoint's
    response entirely, not available from Sofascore here."""
    if not standing_rows:
        return None
    result = []
    for r in standing_rows:
        result.append(StandingsTableRow(
            team_name=r["team"]["name"],
            position=r["position"],
            points=r["points"],
            played=r.get("matches"),
            wins=r.get("wins"),
            draws=r.get("draws"),
            losses=r.get("losses"),
            goals_for=r.get("scoresFor"),
            goals_against=r.get("scoresAgainst"),
            goal_difference=parse_leading_int(r.get("scoreDiffFormatted")),
            form=r.get("form"),
        ))
    return result


def _lineup_note(lineups: dict[str, Any] | None) -> str:
    """Extracted from get_sofascore_match_details to replace a nested
    ternary (python:S3358).

    Confirmed live (20 days before kickoff): Sofascore publishes a
    lineups object with confirmed=false and populated missingPlayers
    well before any actual predicted starting XI exists -- home/away
    are present as keys but their players list is genuinely empty ([]),
    not missing. Previously this said "predicted, not yet confirmed"
    for that case too, promising a predicted lineup that
    home_lineup/away_lineup never actually surfaced. Now checks for at
    least one actual player before claiming "predicted"."""
    if not lineups:
        return "lineup not published yet"
    has_predicted_players = bool((lineups.get("home") or {}).get("players")) or bool((lineups.get("away") or {}).get("players"))
    if lineups.get("confirmed"):
        return "lineup confirmed"
    if has_predicted_players:
        return "lineup predicted, not yet confirmed"
    return "lineup not published yet"


def _match_details_note(lineups: dict[str, Any] | None, stats: dict[str, Any] | None, standing_rows: list[dict[str, Any]] | None) -> str:
    """Extracted from get_sofascore_match_details to keep its own
    cognitive complexity down (python:S3776); behavior unchanged."""
    return "; ".join(
        filter(
            None,
            [
                _lineup_note(lineups),
                (None if stats else "match statistics not available yet (match hasn't started)"),
                (None if standing_rows else "no league standings for this competition"),
            ],
        )
    )


def _find_odds_market(markets: list[dict[str, Any]], market_id: int, choice_group: str | None = None) -> dict[str, Any] | None:
    for m in markets:
        if m.get("marketId") != market_id:
            continue
        if choice_group is not None and m.get("choiceGroup") != choice_group:
            continue
        return m
    return None


def _odds_choice_decimal(market: dict[str, Any] | None, name: str) -> float | None:
    if not market:
        return None
    for c in market.get("choices", []):
        if c.get("name") == name:
            fractional = c.get("fractionalValue")
            return js_round_to(fractional_to_decimal(fractional), 2) if fractional else None
    return None


def _extract_betting_odds(odds: dict[str, Any] | None) -> BettingOdds | None:
    """Sofascore's own single-bookmaker price (provider "1" -- whichever
    book Sofascore's own site treats as the default), fractional-odds
    format converted to decimal. A different methodology from
    footballdata.py's cross-bookmaker average (BettingOdds.betting_odds),
    so this is exposed as the separate sofascore_betting_odds field
    rather than merged with it -- the two can legitimately disagree.
    marketId 1 is the full-time 1X2 market ("1"/"X"/"2" choices);
    marketId 9 with choiceGroup "2.5" is the Over/Under 2.5 goals market.
    None if the core 1X2 market isn't present (odds not yet posted, or
    the match has no bookmaker coverage)."""
    markets = (odds or {}).get("markets") or []
    full_time = _find_odds_market(markets, market_id=1)
    home_odds = _odds_choice_decimal(full_time, "1")
    draw_odds = _odds_choice_decimal(full_time, "X")
    away_odds = _odds_choice_decimal(full_time, "2")
    if not (home_odds and draw_odds and away_odds):
        return None

    over_under = _find_odds_market(markets, market_id=9, choice_group="2.5")
    over_odds = _odds_choice_decimal(over_under, "Over")
    under_odds = _odds_choice_decimal(over_under, "Under")

    home_pct, draw_pct, away_pct, overround, home_fair, draw_fair, away_fair = implied_and_fair_percentages(
        home_odds, draw_odds, away_odds
    )
    over_pct, under_pct, ou_overround, over_fair, under_fair = implied_and_fair_percentages_2way(over_odds, under_odds)
    return BettingOdds(
        home_win_odds=home_odds, draw_odds=draw_odds, away_win_odds=away_odds,
        home_win_implied_pct=home_pct, draw_implied_pct=draw_pct, away_win_implied_pct=away_pct,
        over_2_5_odds=over_odds, under_2_5_odds=under_odds,
        overround_pct=overround, home_win_fair_pct=home_fair, draw_fair_pct=draw_fair, away_win_fair_pct=away_fair,
        over_2_5_implied_pct=over_pct, under_2_5_implied_pct=under_pct,
        over_under_2_5_overround_pct=ou_overround, over_2_5_fair_pct=over_fair, under_2_5_fair_pct=under_fair,
    )


@dataclass
class _SofascoreRawMatchData:
    """Everything get_sofascore_match_details fetches before building the
    final MatchDetails -- bundled so _build_sofascore_match_details below
    can take it as one parameter instead of ~10, keeping that function
    itself under kotlin:S107's parameter threshold."""

    h2h: dict[str, Any] | None
    streaks: dict[str, Any] | None
    lineups: dict[str, Any] | None
    stats: dict[str, Any] | None
    incidents: dict[str, Any] | None
    shotmap: dict[str, Any] | None
    best_players: dict[str, Any] | None
    standing_rows: list[dict[str, Any]] | None
    home_season_stats: dict[str, Any] | None
    away_season_stats: dict[str, Any] | None
    home_manager_vs_away_club: ManagerClubRecord | None
    away_manager_vs_home_club: ManagerClubRecord | None
    odds: dict[str, Any] | None
    home_team_venue: dict[str, Any] | None
    away_team_venue: dict[str, Any] | None


def _team_venue_coordinates(team_data: dict[str, Any] | None) -> tuple[float, float] | None:
    """Extracts a team's own home-venue lat/lon from /api/v1/team/{id}'s
    venue.venueCoordinates -- confirmed live (Newcastle -> St James' Park,
    54.975469/-1.621874). Distinct from the match's own venue coordinates
    (e["venue"]["venueCoordinates"], already used for venue_lat/venue_lon
    elsewhere in this function)."""
    coords = (((team_data or {}).get("team") or {}).get("venue") or {}).get("venueCoordinates") or {}
    lat, lon = coords.get("latitude"), coords.get("longitude")
    return (lat, lon) if lat is not None and lon is not None else None


def _both_teams_venue_lat_lon(
    home_team_venue: dict[str, Any] | None, away_team_venue: dict[str, Any] | None
) -> tuple[float | None, float | None, float | None, float | None]:
    """(home_lat, home_lon, away_lat, away_lon) for MatchDetails'
    home/away_team_venue_lat/lon fields. Extracted from
    _build_sofascore_match_details to keep its own cognitive complexity
    down (python:S3776); behavior unchanged."""
    home = _team_venue_coordinates(home_team_venue)
    away = _team_venue_coordinates(away_team_venue)
    return (
        home[0] if home else None, home[1] if home else None,
        away[0] if away else None, away[1] if away else None,
    )


def _build_sofascore_match_details(match: MatchInfo, e: dict[str, Any], raw: _SofascoreRawMatchData) -> MatchDetails:
    """The local-derivation + final MatchDetails(...) construction half of
    get_sofascore_match_details, extracted to keep that function's own
    cognitive complexity down (python:S3776) -- most of the complexity
    here is the many `or {}`/ternary fallback expressions needed to read
    Sofascore's own deeply-optional JSON shape, not real branching logic.
    Behavior unchanged."""
    venue = e.get("venue") or {}
    venue_coords = venue.get("venueCoordinates") or {}
    referee = e.get("referee") or {}
    h2h_duel = (raw.h2h or {}).get("teamDuel")
    h2h_manager_duel = (raw.h2h or {}).get("managerDuel")
    lineups_home = (raw.lineups or {}).get("home")
    lineups_away = (raw.lineups or {}).get("away")
    home_venue_lat, home_venue_lon, away_venue_lat, away_venue_lon = _both_teams_venue_lat_lon(
        raw.home_team_venue, raw.away_team_venue
    )

    return MatchDetails(
        **{**asdict(match), "venue": venue.get("name")},
        venue_name=venue.get("name"),
        venue_city=(venue.get("city") or {}).get("name"),
        venue_country=(venue.get("country") or {}).get("name"),
        venue_lat=venue_coords.get("latitude"),
        venue_lon=venue_coords.get("longitude"),
        venue_capacity=venue.get("capacity"),
        home_team_venue_lat=home_venue_lat,
        home_team_venue_lon=home_venue_lon,
        away_team_venue_lat=away_venue_lat,
        away_team_venue_lon=away_venue_lon,
        referee=referee.get("name"),
        referee_stats=_extract_referee_stats(e.get("referee")),
        attendance=e.get("attendance"),
        weather=None,
        weather_detail=None,
        head_to_head_summary=_summary_from_duel(h2h_duel),
        head_to_head_streaks=_extract_streaks(raw.streaks),
        recent_meetings=None,  # computed centrally once search.py's orchestrator is ported
        home_lineup=_extract_lineup(lineups_home),
        away_lineup=_extract_lineup(lineups_away),
        home_bench=_extract_bench(lineups_home),
        away_bench=_extract_bench(lineups_away),
        home_formation=(lineups_home or {}).get("formation"),
        away_formation=(lineups_away or {}).get("formation"),
        home_team_country=(e["homeTeam"].get("country") or {}).get("name"),
        away_team_country=(e["awayTeam"].get("country") or {}).get("name"),
        home_manager=_extract_manager(e["homeTeam"].get("manager")),
        away_manager=_extract_manager(e["awayTeam"].get("manager")),
        home_manager_vs_away_club=raw.home_manager_vs_away_club,
        away_manager_vs_home_club=raw.away_manager_vs_home_club,
        standings_table=_standings_table_from(raw.standing_rows),
        home_suspended_players=None,
        away_suspended_players=None,
        home_missing_players=_extract_missing_players(lineups_home),
        away_missing_players=_extract_missing_players(lineups_away),
        manager_duel=_summary_from_duel(h2h_manager_duel),
        home_team_standing=_extract_standing(raw.standing_rows, e["homeTeam"]["id"]),
        away_team_standing=_extract_standing(raw.standing_rows, e["awayTeam"]["id"]),
        home_team_season_stats=_extract_season_stats(raw.home_season_stats),
        away_team_season_stats=_extract_season_stats(raw.away_season_stats),
        match_stats=_extract_match_stats(raw.stats),
        event_timeline=_extract_incidents(raw.incidents),
        set_piece_goals=_extract_set_piece_goals(raw.shotmap),
        shotmap_stats=_extract_shotmap_stats(raw.shotmap),
        lineup_confirmed=(raw.lineups.get("confirmed", False) if raw.lineups else None),
        player_of_the_match=_extract_player_of_the_match(raw.best_players),
        sofascore_betting_odds=_extract_betting_odds(raw.odds),
        note=_match_details_note(raw.lineups, raw.stats, raw.standing_rows),
    )


async def get_sofascore_match_details(match: MatchInfo) -> MatchDetails:
    """Every endpoint below is same-origin /api/v1/..., in scope since
    Sofascore's robots.txt (unlike Fotmob's) doesn't disallow /api/.
    Several are genuinely time-gated by the match itself, not scraper
    limitations: lineups go from absent -> predicted -> confirmed as
    kickoff approaches; statistics only exist once the match has actually
    started; standings only exist for competitions that have a league
    table (not friendlies/one-off cups), resolved via the event's own
    tournament+season ids. All handled with _fetch_json_optional rather
    than retried as transient failures."""
    event_id = [p for p in match.source_url.split("/") if p][-1]
    async with launch_browser() as browser:
        context = await browser.new_context(user_agent=_USER_AGENT)
        page = await context.new_page()
        await _warm_up(page)

        event_data = await _fetch_json(page, f"https://www.sofascore.com/api/v1/event/{event_id}")
        e = event_data["event"]

        await _sleep(800)
        h2h = await _fetch_json_optional(page, f"https://www.sofascore.com/api/v1/event/{event_id}/h2h")

        await _sleep(800)
        streaks = await _fetch_json_optional(page, f"https://www.sofascore.com/api/v1/event/{event_id}/team-streaks")

        await _sleep(800)
        lineups = await _fetch_json_optional(page, f"https://www.sofascore.com/api/v1/event/{event_id}/lineups")

        await _sleep(800)
        stats = await _fetch_json_optional(page, f"https://www.sofascore.com/api/v1/event/{event_id}/statistics")

        await _sleep(800)
        incidents = await _fetch_json_optional(page, f"https://www.sofascore.com/api/v1/event/{event_id}/incidents")

        await _sleep(800)
        shotmap = await _fetch_json_optional(page, f"https://www.sofascore.com/api/v1/event/{event_id}/shotmap")

        await _sleep(800)
        best_players = await _fetch_json_optional(page, f"https://www.sofascore.com/api/v1/event/{event_id}/best-players")

        ut_id = (e.get("tournament") or {}).get("uniqueTournament", {}).get("id")
        season_id = (e.get("season") or {}).get("id")
        standings, home_season_stats, away_season_stats = await _fetch_standings_and_season_stats(page, e, ut_id, season_id)
        standing_rows = ((standings or {}).get("standings") or [None])[0]
        standing_rows = standing_rows.get("rows") if standing_rows else None

        await _sleep(800)
        home_manager_vs_away_club = await _fetch_manager_club_record(page, e["homeTeam"].get("manager"), e["awayTeam"]["name"])
        await _sleep(800)
        away_manager_vs_home_club = await _fetch_manager_club_record(page, e["awayTeam"].get("manager"), e["homeTeam"]["name"])

        await _sleep(800)
        odds = await _fetch_json_optional(page, f"https://www.sofascore.com/api/v1/event/{event_id}/odds/1/all")

        # Each team's OWN home venue -- distinct from the match's venue
        # (already on `e["venue"]`, which is the home team's ground in
        # the normal case). Needed to compute the AWAY team's real
        # travel distance (see _extract_travel_coordinates/
        # compute_travel_info): confirmed live that country-level
        # comparison alone reports 0km for every same-country match
        # regardless of actual distance (e.g. Newcastle away at
        # Coventry, a genuine ~250km trip, previously showed 0).
        await _sleep(800)
        home_team_venue = await _fetch_json_optional(page, f"https://www.sofascore.com/api/v1/team/{e['homeTeam']['id']}")
        await _sleep(800)
        away_team_venue = await _fetch_json_optional(page, f"https://www.sofascore.com/api/v1/team/{e['awayTeam']['id']}")

        raw = _SofascoreRawMatchData(
            h2h=h2h, streaks=streaks, lineups=lineups, stats=stats, incidents=incidents, shotmap=shotmap,
            best_players=best_players, standing_rows=standing_rows, home_season_stats=home_season_stats,
            away_season_stats=away_season_stats, home_manager_vs_away_club=home_manager_vs_away_club,
            away_manager_vs_home_club=away_manager_vs_home_club, odds=odds,
            home_team_venue=home_team_venue, away_team_venue=away_team_venue,
        )
        return _build_sofascore_match_details(match, e, raw)


def _resolve_primary_season(seasons: dict[str, Any] | None) -> tuple[int | None, int | None]:
    """The ut_id/season_id resolution from the seasons list's own deeply-
    optional shape, extracted from _fetch_top_player_stats to keep its
    cognitive complexity down (python:S3776); behavior unchanged."""
    primary = ((seasons or {}).get("uniqueTournamentSeasons") or [None])[0]
    if not primary:
        return None, None
    ut_id = primary.get("uniqueTournament", {}).get("id")
    season_id = (primary.get("seasons") or [None])[0]
    season_id = season_id.get("id") if season_id else None
    return ut_id, season_id


async def _fetch_top_player_stats(page: Page, team_id: int) -> dict[str, SeasonPlayerStats]:
    """/api/v1/team/{id}/player-statistics/seasons lists every competition
    this team has season stats for, most recent first -- [0] is the team's
    primary current competition. /top-players/overall for that
    competition+season gives per-category leaderboards (goals, assists,
    rating, xG, cards, etc), each entry carrying the player's own
    appearance count for that category. Only ~20-25 notable players show
    up (fringe/youth players with too few minutes are excluded from every
    category), not the full squad -- same general coverage Goal.com's squad
    stats give, just via Sofascore itself so names match the squad list
    exactly (no cross-source name-matching needed)."""
    result: dict[str, SeasonPlayerStats] = {}
    seasons = await _fetch_json_optional(page, f"https://www.sofascore.com/api/v1/team/{team_id}/player-statistics/seasons")
    ut_id, season_id = _resolve_primary_season(seasons)
    if not ut_id or not season_id:
        return result

    await _sleep(800)
    data = await _fetch_json_optional(
        page, f"https://www.sofascore.com/api/v1/team/{team_id}/unique-tournament/{ut_id}/season/{season_id}/top-players/overall"
    )
    top_players = (data or {}).get("topPlayers", {})

    def get(name: str) -> SeasonPlayerStats:
        entry = result.get(name)
        if entry is None:
            entry = SeasonPlayerStats(appearances=0, goals=0, assists=0, yellow_cards=0, red_cards=0, rating=None, expected_goals=None)
            result[name] = entry
        return entry

    for category, entries in top_players.items():
        for e in entries:
            entry = get(e["player"]["name"])
            entry.appearances = max(entry.appearances, e["statistics"].get("appearances", 0))
            _apply_category_stat(entry, category, e["statistics"])

    return result


_CATEGORY_STAT_FIELDS = {
    "goals": "goals",
    "assists": "assists",
    "yellowCards": "yellow_cards",
    "redCards": "red_cards",
    "rating": "rating",
    "expectedGoals": "expected_goals",
}


def _apply_category_stat(entry: SeasonPlayerStats, category: str, statistics: dict[str, Any]) -> None:
    """Extracted from _fetch_top_player_stats to keep its own cognitive
    complexity down (python:S3776); behavior unchanged. `rating`/
    `expectedGoals` have no sensible zero default (unlike the count
    fields), so they use `.get(name)` with no fallback, same as the
    original per-category branches."""
    field = _CATEGORY_STAT_FIELDS.get(category)
    if field is None:
        return
    default = None if field in ("rating", "expected_goals") else 0
    setattr(entry, field, statistics.get(category, default))


def _build_sofascore_squad(players_data: dict[str, Any], top_player_stats: dict[str, SeasonPlayerStats]) -> list[SquadMember]:
    """The squad-building loop, extracted from get_sofascore_team_profile
    to keep its own cognitive complexity down (python:S3776); behavior
    unchanged."""
    squad: list[SquadMember] = []
    for p in players_data.get("players", []):
        player = p["player"]
        injury = player.get("injury")
        squad.append(
            SquadMember(
                name=player["name"],
                role=player.get("position"),
                injury=(f"{injury.get('reason', 'Injured')} ({injury.get('status', 'out')})" if injury else None),
                age=_age_from_timestamp(player.get("dateOfBirthTimestamp")),
                market_value=(player.get("proposedMarketValueRaw") or {}).get("value"),
                season_stats=top_player_stats.get(player["name"]),
                season_stats_source=("sofascore" if player["name"] in top_player_stats else None),
                defensive_stats=None,
                recent_usage=None,
            )
        )
    return squad


def _sofascore_transfer_date(t: dict[str, Any]) -> str | None:
    ts = t.get("transferDateTimestamp")
    if not ts:
        return None
    return _to_iso_z(datetime.fromtimestamp(ts, tz=UTC))


def _build_sofascore_transfers(transfers_data: dict[str, Any] | None) -> list[TransferRecord]:
    """The transfers-building loops + sort, extracted from
    get_sofascore_team_profile -- see _build_sofascore_squad's own doc
    comment for why. Behavior unchanged, including the most-recent-first
    sort (see this function's original inline comment on the sort line
    for why Sofascore's own transfers endpoint needs it)."""
    transfers: list[TransferRecord] = []
    for t in (transfers_data or {}).get("transfersIn", []):
        transfers.append(
            TransferRecord(
                player_name=t["player"]["name"],
                direction="in",
                from_club=t.get("fromTeamName"),
                to_club=t.get("toTeamName"),
                date=_sofascore_transfer_date(t),
            )
        )
    for t in (transfers_data or {}).get("transfersOut", []):
        transfers.append(
            TransferRecord(
                player_name=t["player"]["name"],
                direction="out",
                from_club=t.get("fromTeamName"),
                to_club=t.get("toTeamName"),
                date=_sofascore_transfer_date(t),
            )
        )
    # Sofascore's transfers endpoint isn't scoped to "recent" at all -- it
    # returns entries spanning multiple transfer windows (confirmed live:
    # ~11 months back for Arsenal), unsorted. Without sorting, genuinely
    # distinct dated events (e.g. a player signed, then loaned back to
    # their old club, then signed again the following window) interleave
    # in API order and read as exact duplicates. Sorting most-recent-first
    # fixes the ordering.
    transfers.sort(key=lambda t: t.date or "", reverse=True)
    return transfers


async def get_sofascore_team_profile(team_name: str) -> TeamProfile:
    """/api/v1/team/{id}/players (squad, with per-player injury field) and
    /api/v1/team/{id}/transfers -- both same-origin /api/, in scope. No
    separate /injuries endpoint exists (confirmed: 404) -- injury status is
    embedded per player instead."""
    async with launch_browser() as browser:
        context = await browser.new_context(user_agent=_USER_AGENT)
        page = await context.new_page()
        await _warm_up(page)

        team = await _find_team(page, team_name)
        if team is None:
            raise ValueError(f'No Sofascore team found matching "{team_name}"')

        await _sleep(800)
        players_data = await _fetch_json(page, f"https://www.sofascore.com/api/v1/team/{team.id}/players")

        await _sleep(800)
        transfers_data = await _fetch_json_optional(page, f"https://www.sofascore.com/api/v1/team/{team.id}/transfers")

        await _sleep(800)
        top_player_stats = await _fetch_top_player_stats(page, team.id)

        squad = _build_sofascore_squad(players_data, top_player_stats)
        transfers = _build_sofascore_transfers(transfers_data)

        ages = [s.age for s in squad if s.age is not None]
        injuries = [s for s in squad if s.injury is not None]
        key_injuries = sorted(injuries, key=lambda s: s.market_value or 0, reverse=True)[:3] if injuries else None

        return TeamProfile(
            source="sofascore",
            team_name=team.name,
            squad=squad,
            average_age=(js_round_to(sum(ages) / len(ages), 1) if ages else None),
            injuries=injuries,
            key_injuries=key_injuries,
            recent_transfers=transfers if transfers else None,
            missing_midfielders=None,  # computed centrally once search.py's orchestrator is ported
            missing_attackers=None,
            missing_defenders=None,
            missing_goalkeepers=None,
        )
