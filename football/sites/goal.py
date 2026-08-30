"""Goal.com scraper. Ported from src/sites/goal.ts.

Plain fetch works throughout (no Cloudflare-style block encountered).
robots.txt is `Allow: /` for all user-agents -- fully permissive.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from ..data_dir import data_dir
from ..http import fetch_text
from ..team_aliases import known_aliases_for
from ..team_name_match import strip_diacritics
from ..types import (
    HeadToHeadSummary,
    LineupPlayer,
    MatchDetails,
    MatchInfo,
    MatchStatItem,
    SeasonPlayerStats,
    SquadMember,
    TeamProfile,
    TeamStanding,
    TimelineEvent,
)

_TEAMS_SITEMAP_URL = "https://www.goal.com/en/sitemap/teams.xml"
_NEXT_DATA_MARKER = "__NEXT_DATA__"
_TEAM_SITEMAP_RE = re.compile(r"<loc>(https://www\.goal\.com/en/team/([^/]+)/([^<]+))</loc>")


def _extract_next_data(html: str) -> Any:
    i = html.find(_NEXT_DATA_MARKER)
    if i == -1:
        raise ValueError("__NEXT_DATA__ not found in Goal.com page")
    start = html.find(">", i) + 1
    end = html.find("</script>", start)
    return json.loads(html[start:end])


@dataclass
class _TeamIndexEntry:
    id: str
    slug: str
    url: str


async def _build_teams_index() -> list[_TeamIndexEntry]:
    """Goal.com's own teams sitemap is the only non-search way to resolve
    a team name to its id."""
    xml = await fetch_text(_TEAMS_SITEMAP_URL)
    return [_TeamIndexEntry(url=m.group(1), slug=m.group(2), id=m.group(3)) for m in _TEAM_SITEMAP_RE.finditer(xml)]


async def _load_teams_index() -> list[_TeamIndexEntry]:
    seed_path = data_dir() / "goal-teams.json"
    try:
        raw = json.loads(seed_path.read_text(encoding="utf-8"))
        return [_TeamIndexEntry(**e) for e in raw]
    except (FileNotFoundError, json.JSONDecodeError):
        entries = await _build_teams_index()
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_text(json.dumps([{"id": e.id, "slug": e.slug, "url": e.url} for e in entries]), encoding="utf-8")
        return entries


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", strip_diacritics(s).lower()).strip()


# Goal.com-specific slug overrides: normalized team name -> the exact
# slug to search for instead, checked before the alias loop below.
# Confirmed live: team_aliases.py's canonical alias for "Liverpool" is
# "Liverpool FC", normalizing to "liverpool fc" -- Goal.com has no
# "liverpool-fc" slug at all, so the exact-match branch misses, but the
# SUBSTRING branch right after it doesn't: "liverpool fc" is contained
# in the normalized form of "liverpool-fc-women" ("liverpool fc women"),
# so that becomes the first (and only, since the loop returns on the
# first alias that yields any candidate) candidate tried -- the men's
# team's own bare "liverpool" slug, a separate and more precise entry,
# is never reached. get_goal_matches("Liverpool") returned 36 fixtures,
# ALL of them Liverpool FC Women's WSL/FA Cup matches, none of them the
# men's Premier League team -- same bug class as fotmob.py's Uruguayan-
# club collision, different mechanism (a substring false-positive here,
# not a colliding exact match).
_GOAL_SLUG_OVERRIDE: dict[str, str] = {
    "liverpool": "liverpool",
    "liverpool fc": "liverpool",
}


def _find_best_team_match(entries: list[_TeamIndexEntry], team_name: str) -> _TeamIndexEntry | None:
    override_slug = _GOAL_SLUG_OVERRIDE.get(_normalize(team_name))
    if override_slug:
        exact = next((e for e in entries if e.slug == override_slug), None)
        if exact:
            return exact

    # Try the searched name and every known alias (team_aliases.py) before
    # falling back to reverse-substring guessing -- see fotmob.py's own
    # copy of this fix for the exact failure mode (a connective word like
    # "and" in the canonical name breaking the forward substring match and
    # falling through to an unrelated short-slug false match). Same risk
    # applies here since this is the same index+substring pattern.
    for target in known_aliases_for(team_name):
        target_slug = target.replace(" ", "-")

        exact = next((e for e in entries if e.slug == target_slug), None)
        if exact:
            return exact

        candidates = [e for e in entries if target in _normalize(e.slug)]
        if candidates:
            candidates.sort(key=lambda e: len(e.slug))
            return candidates[0]

    # Reverse direction: Sofascore's official name is sometimes longer than
    # this source's short slug ("Girona FC" vs slug "girona") -- a 4-char
    # floor (same convention as stadiumdb.py) keeps this from letting a
    # generic short slug false-match an unrelated longer query.
    target = _normalize(team_name)
    reverse_candidates = [e for e in entries if len(_normalize(e.slug)) >= 4 and _normalize(e.slug) in target]
    if not reverse_candidates:
        return None
    reverse_candidates.sort(key=lambda e: len(e.slug), reverse=True)
    return reverse_candidates[0]


def _to_match_info(m: dict[str, Any]) -> MatchInfo:
    finished = m.get("status") == "RESULT"
    status_raw = m.get("status")
    score = m.get("score") or {}
    return MatchInfo(
        source="goal",
        source_url=f"https://www.goal.com/en/match/{m['link']['slug']}/{m['link']['id']}",
        competition=(m.get("competition") or {}).get("name"),
        home_team=m["teamA"]["name"],
        away_team=m["teamB"]["name"],
        kickoff_utc=m.get("startDate"),
        venue=(m.get("venue") or {}).get("name"),
        status=("finished" if finished else "scheduled" if status_raw == "FIXTURE" else (status_raw.lower() if status_raw else None)),
        home_score=(score.get("teamA") if finished else None),
        away_score=(score.get("teamB") if finished else None),
        home_score_ht=None,
        away_score_ht=None,
        season=None,
        round=None,
        match_id=str(m["link"]["id"]),
    )


async def get_goal_matches(team_name: str) -> list[MatchInfo]:
    index = await _load_teams_index()
    team = _find_best_team_match(index, team_name)
    if team is None:
        raise ValueError(f'No Goal.com team found matching "{team_name}"')

    url = f"https://www.goal.com/en/team/{team.slug}/fixtures-results/{team.id}"
    html = await fetch_text(url)
    data = _extract_next_data(html)
    matches = data["props"]["pageProps"]["content"].get("matches") or []
    # teamA/teamB is None for a fixture with an unconfirmed opponent (a cup
    # draw slot still TBD) -- confirmed live for Inter and AC Milan's own
    # schedules. Skip those rather than crashing on the rest of the list.
    matches = [m for m in matches if m.get("teamA") and m.get("teamB")]
    return [_to_match_info(m) for m in matches]


def _build_player_event_stats(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """One pass over the match's own full event list (goals/cards/subs,
    confirmed live to exist at `match.events` -- separate from and richer
    than `match.keyEvents`, which only ever carries goals) keyed by player
    id. Reused for every player on both sides rather than re-deriving the
    same facts per player from each player's own (identical, just
    pre-filtered to that player) nested `events` array."""
    stats: dict[str, dict[str, Any]] = {}

    def entry(player_id: str) -> dict[str, Any]:
        return stats.setdefault(player_id, {"goals": 0, "assists": 0, "sub_on_minute": None, "sub_off_minute": None})

    for e in events:
        typename = e.get("__typename")
        if typename == "MatchGoalEvent":
            scorer_id = (e.get("scorer") or {}).get("id")
            if scorer_id:
                entry(scorer_id)["goals"] += 1
            assist_id = (e.get("assist") or {}).get("id")
            if assist_id:
                entry(assist_id)["assists"] += 1
        elif typename == "MatchSubstitutionEvent":
            minute = (e.get("period") or {}).get("minute")
            out_id = (e.get("out") or {}).get("id")
            in_id = (e.get("in") or {}).get("id")
            if out_id:
                entry(out_id)["sub_off_minute"] = minute
            if in_id:
                entry(in_id)["sub_on_minute"] = minute
    return stats


def _extract_lineup_side(
    side: dict[str, Any] | None, event_stats: dict[str, dict[str, Any]], is_bench: bool = False
) -> list[LineupPlayer] | None:
    group = "substitutes" if is_bench else "lineup"
    if not side or not side.get(group):
        return None
    players: list[LineupPlayer] = []
    for p in side[group]:
        es = event_stats.get(p["person"]["id"], {})
        if is_bench:
            # Unused substitute stays null (not 0), same convention as
            # every other source -- null means "never came on", not "came
            # on and recorded 0 minutes". No exact stoppage-time tracking
            # here, so an entered sub's minutes is a 90-minute-match
            # approximation, same precision as the rest of this module.
            on_minute = es.get("sub_on_minute")
            minutes_played = (90 - on_minute) if on_minute is not None else None
        else:
            off_minute = es.get("sub_off_minute")
            minutes_played = off_minute if off_minute is not None else 90
        players.append(
            LineupPlayer(
                name=p["person"]["name"],
                position=None,
                substitute=is_bench,
                minutes_played=minutes_played,
                goals=es.get("goals", 0),
                assists=es.get("assists", 0),
                xg=None,
                xa=None,
                shots=None,
                shots_on_target=None,
                tackles=None,
                interceptions=None,
                fouls=None,
                rating=None,
                key_passes=None,
                shirt_number=p.get("shirtNumber"),
                age=None,
            )
        )
    return players


def _format_formation(f: str | None) -> str | None:
    if not f:
        return None
    return "-".join(f)


_STAT_CATEGORIES = ["summary", "attacking", "passing", "duels", "defence", "discipline"]


def _humanize_stat_type(type_: str) -> str:
    lowered = type_.lower().replace("_", " ")
    return lowered[:1].upper() + lowered[1:] if lowered else lowered


def _extract_match_stats(stats: dict[str, Any] | None) -> list[MatchStatItem] | None:
    if not stats:
        return None
    out: list[MatchStatItem] = []
    seen: set[str] = set()
    for cat in _STAT_CATEGORIES:
        for item in stats.get(cat) or []:
            if item["type"] in seen:  # "summary" duplicates some entries from other categories
                continue
            seen.add(item["type"])
            out.append(MatchStatItem(name=_humanize_stat_type(item["type"]), home=str(item["teamA"]), away=str(item["teamB"])))
    return out if out else None


def _extract_timeline(match_events: list[dict[str, Any]] | None) -> list[TimelineEvent] | None:
    """`match.events` (distinct from `match.keyEvents`, which only ever
    carries goals -- confirmed live) is the fuller match-wide event list:
    goals, cards, and substitutions, each with a `period.minute`. Period
    markers (kickoff/half-time/full-time) are the only other type observed
    and are filtered out as not real match events."""
    if not match_events:
        return None
    result: list[TimelineEvent] = []
    for e in match_events:
        typename = e.get("__typename")
        minute = (e.get("period") or {}).get("minute", 0)
        team = "home" if e.get("side") == "TEAM_A" else "away" if e.get("side") == "TEAM_B" else None
        if typename == "MatchGoalEvent":
            result.append(
                TimelineEvent(
                    minute=minute,
                    type="Goal",
                    detail=(f"Assist: {e['assist']['name']}" if e.get("assist") else None),
                    player=(e.get("scorer") or {}).get("name"),
                    team=team,
                )
            )
        elif typename == "MatchCardEvent":
            card_type = e.get("type") or ""
            result.append(
                TimelineEvent(
                    minute=minute,
                    type=("Red Card" if "RED" in card_type else "Yellow Card"),
                    detail=None,
                    player=(e.get("player") or {}).get("name"),
                    team=team,
                )
            )
        elif typename == "MatchSubstitutionEvent":
            in_name = (e.get("in") or {}).get("name")
            out_name = (e.get("out") or {}).get("name")
            result.append(
                TimelineEvent(
                    minute=minute,
                    type="Substitution",
                    detail=(f"{in_name} on for {out_name}" if in_name and out_name else None),
                    player=out_name,
                    team=team,
                )
            )
    return sorted(result, key=lambda e: e.minute) if result else None


def _extract_standing(rankings: list[dict[str, Any]] | None, team_id: str | None) -> TeamStanding | None:
    row = next((r for r in (rankings or []) if r["team"]["id"] == team_id), None)
    if row is None:
        return None
    return TeamStanding(
        position=row["position"],
        played=row["played"],
        wins=row["win"],
        draws=row["draw"],
        losses=row["lose"],
        points=row["points"],
        goal_diff=str(row["goalsDifference"]),
        total_teams=(len(rankings) if rankings else None),
    )


async def get_goal_match_details(match: MatchInfo) -> MatchDetails:
    """Goal.com has no venue/referee gap like SoccerDesk -- venue is
    present, but `referee` was an empty array on every match checked
    during research (friendlies and competitive Champions League/Premier
    League fixtures alike), so it's treated as genuinely unpopulated by
    this source rather than retried or guessed at."""
    html = await fetch_text(match.source_url)
    data = _extract_next_data(html)
    content = data["props"]["pageProps"]["content"]
    m = content["match"]

    rankings = ((content.get("summaryStandings") or {}).get("table") or {}).get("rankings")
    home_team_id = (m.get("teamA") or {}).get("id")
    away_team_id = (m.get("teamB") or {}).get("id")

    h2h_stats = (content.get("h2h") or {}).get("stats")
    lineups = m.get("lineups") or {}
    event_stats = _build_player_event_stats(m.get("events") or [])

    return MatchDetails(
        **asdict(match),
        venue_name=(m.get("venue") or {}).get("name"),
        venue_city=None,
        venue_country=None,
        venue_lat=None,
        venue_lon=None,
        referee=None,
        referee_stats=None,
        attendance=None,
        weather=None,
        weather_detail=None,
        head_to_head_summary=(
            HeadToHeadSummary(
                home_wins=h2h_stats.get("teamAWins", 0),
                away_wins=h2h_stats.get("teamBWins", 0),
                draws=h2h_stats.get("draws", 0),
            )
            if h2h_stats
            else None
        ),
        head_to_head_streaks=None,
        recent_meetings=None,
        home_lineup=_extract_lineup_side(lineups.get("teamA"), event_stats),
        away_lineup=_extract_lineup_side(lineups.get("teamB"), event_stats),
        home_bench=_extract_lineup_side(lineups.get("teamA"), event_stats, is_bench=True),
        away_bench=_extract_lineup_side(lineups.get("teamB"), event_stats, is_bench=True),
        home_formation=_format_formation((lineups.get("teamA") or {}).get("formation")),
        away_formation=_format_formation((lineups.get("teamB") or {}).get("formation")),
        home_team_country=None,
        away_team_country=None,
        home_manager=None,
        away_manager=None,
        home_manager_vs_away_club=None,
        away_manager_vs_home_club=None,
        standings_table=None,
        home_suspended_players=None,
        away_suspended_players=None,
        home_team_standing=_extract_standing(rankings, home_team_id),
        away_team_standing=_extract_standing(rankings, away_team_id),
        home_team_season_stats=None,
        away_team_season_stats=None,
        match_stats=_extract_match_stats(m.get("stats")),
        event_timeline=_extract_timeline(m.get("events")),
        set_piece_goals=None,
        shotmap_stats=None,
        lineup_confirmed=None,
        player_of_the_match=None,
        note="referee not populated by Goal.com for any match checked; lineups include a `confirmed` flag not surfaced here",
    )


async def get_goal_team_profile(team_name: str) -> TeamProfile:
    """Squad comes from the team's own /squad/ sub-page (same
    __NEXT_DATA__ pattern as fixtures) -- includes each player's season
    stats (appearances/goals/assists/cards), captured in season_stats. No
    injury status, age, or market value here, and no transfers endpoint
    was found. Names are abbreviated ("A. Becker") not full names, which
    matters for cross-source enrichment (surname match, not exact match)."""
    index = await _load_teams_index()
    team = _find_best_team_match(index, team_name)
    if team is None:
        raise ValueError(f'No Goal.com team found matching "{team_name}"')

    url = f"https://www.goal.com/en/team/{team.slug}/squad/{team.id}"
    html = await fetch_text(url)
    data = _extract_next_data(html)
    content = data["props"]["pageProps"]["content"]
    players = (content.get("squad") or {}).get("players") or []

    squad: list[SquadMember] = []
    for p in players:
        stats = p.get("stats")
        squad.append(
            SquadMember(
                name=p["player"]["name"],
                role=p["player"].get("position"),
                injury=None,
                age=None,
                market_value=None,
                season_stats=(
                    SeasonPlayerStats(
                        appearances=stats.get("appearances", 0),
                        goals=stats.get("goals", 0),
                        assists=stats.get("assists", 0),
                        yellow_cards=stats.get("yellowCards", 0),
                        red_cards=stats.get("redCards", 0),
                        rating=None,
                        expected_goals=None,
                    )
                    if stats
                    else None
                ),
                season_stats_source=("goal" if stats else None),
                defensive_stats=None,
                recent_usage=None,
            )
        )

    return TeamProfile(
        source="goal",
        team_name=(content.get("team") or {}).get("name") or team_name,
        squad=squad if squad else None,
        average_age=None,
        injuries=None,
        key_injuries=None,
        recent_transfers=None,
        missing_midfielders=None,  # computed centrally once search.py's orchestrator is ported
        missing_attackers=None,
        missing_defenders=None,
        missing_goalkeepers=None,
    )
