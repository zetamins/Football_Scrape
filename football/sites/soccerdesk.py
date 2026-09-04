"""SoccerDesk scraper. Ported from src/sites/soccerdesk.ts.

Unlike Sofascore, SoccerDesk needs no browser at all -- plain fetch works
throughout, and www.soccerdesk.com's robots.txt has no real disallow rules
(its one Disallow line is a broken unfilled template: "/[sport]/*", which
matches no real URL). api.soccerdesk.com (used only for team search) has
no robots.txt at all (404) -- per RFC 9309 a missing robots.txt means no
crawling restrictions apply.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from ..http import USER_AGENT, new_client
from ..team_aliases import known_aliases_for
from ..team_name_match import (
    name_query_variants,
    normalize_for_match as _normalize,
    slugify_for_match as _slugify,
    strip_diacritics,
)
from ..types import (
    HeadToHeadMeeting,
    HeadToHeadSummary,
    LineupPlayer,
    ManagerInfo,
    MatchDetails,
    MatchInfo,
    SquadMember,
    TeamProfile,
    TeamStanding,
    TimelineEvent,
)


async def _fetch_json(url: str, attempts: int = 3) -> Any:
    """Observed one-off ETIMEDOUT/ENETUNREACH-style transient failures
    (IPv6-first dual-stack resolution failing before falling back to
    IPv4) that a plain retry immediately resolved -- a couple of quick
    retries absorbs that without needing Sofascore's heavier
    Cloudflare-oriented backoff schedule."""
    last_err: Exception | None = None
    for i in range(attempts):
        try:
            async with new_client() as client:
                resp = await client.get(url, headers={"User-Agent": USER_AGENT})
                resp.raise_for_status()
                return resp.json()
        # Exception, not BaseException -- catching BaseException would also
        # retry-then-delay a genuine KeyboardInterrupt/SystemExit instead of
        # honoring it immediately. Re-raised below once retries (or a
        # non-transient error) exhaust them, mirroring the TS original's
        # catch-all in effect, not in exact exception class.
        except Exception as err:  # noqa: BLE001
            last_err = err
            if i < attempts - 1:
                await asyncio.sleep(1 * (i + 1))
    assert last_err is not None
    raise last_err


@dataclass
class _SoccerdeskTeam:
    id: str
    name: str
    cname: str | None = None


async def _find_team(team_name: str) -> _SoccerdeskTeam | None:
    """SoccerDesk's search endpoint is a strict server-side match, not a
    fuzzy one -- it returns zero results for "Girona FC" but finds
    "Girona", and zero results for "Almeria" (accented) but finds
    "Almeria" (unaccented). Retrying with the diacritics-stripped/
    generic-suffix-stripped variants recovers both without guessing at an
    alias."""
    # After the existing diacritics/suffix variants, also try any known
    # alias (team_aliases.py) -- e.g. SoccerDesk's search returns nothing
    # for "Royale Union Saint-Gilloise" or "Brighton and Hove Albion" but
    # finds "Union SG"/"Brighton", confirmed live. Deduped against what's
    # already queued so this doesn't repeat a request.
    #
    # Every variant is queried and pooled BEFORE picking a winner -- e.g.
    # querying "Leicester City" alone returns six wrong youth/women's
    # entries ("Leicester City Academy"/"U18"/"U23"/"LFC"/"WFC") since
    # SoccerDesk's search is a strict prefix match and the real senior
    # club is named just "Leicester" (shorter than the query, so it never
    # appears in that variant's own results at all); stopping at the
    # first variant with ANY result would return one of those wrong
    # entries before ever trying the "leicester" alias that actually
    # surfaces the real club. Confirmed live.
    seen = set()
    tried_variants = []
    for variant in [*name_query_variants(team_name), *known_aliases_for(team_name)]:
        key = variant.lower()
        if key in seen:
            continue
        seen.add(key)
        tried_variants.append(variant)

    pool: dict[str, dict[str, Any]] = {}
    for variant in tried_variants:
        data = await _fetch_json(f"https://api.soccerdesk.com/v1/en/search/soccer?userInput={quote(variant)}")
        for t in data.get("teams") or []:
            pool.setdefault(t["id"], t)
    teams = list(pool.values())
    if not teams:
        return None

    # Diacritic-insensitive, and checked against every known alias too
    # (not just the searched name) -- e.g. "Espanol" (football-data.co.uk's
    # short form, no "y") exact-matches an unrelated small club "Jove
    # Espanol" (also missing the "y" in its own real name) before the real
    # "Espanyol" (with "y") ever gets compared, since it only exact-matches
    # the "espanyol" alias, not "espanol" itself. Confirmed live.
    target_set = {strip_diacritics(v).lower().strip() for v in [team_name, *known_aliases_for(team_name)]}
    exact = next((t for t in teams if strip_diacritics(t["name"]).lower() in target_set), None)
    if exact:
        return _SoccerdeskTeam(id=exact["id"], name=exact["name"], cname=exact.get("cname"))

    target = strip_diacritics(team_name).lower().strip()

    # Reverse direction: SoccerDesk's senior-club entry is sometimes
    # shorter than the query itself (see "Leicester" above). A 4-char
    # floor (same convention as stadiumdb.py) guards against a too-short
    # name false-matching an unrelated longer query.
    reverse_candidates = [
        t for t in teams if len(strip_diacritics(t["name"])) >= 4 and strip_diacritics(t["name"]).lower() in target
    ]
    if reverse_candidates:
        pick = min(reverse_candidates, key=lambda t: len(t["name"]))
        return _SoccerdeskTeam(id=pick["id"], name=pick["name"], cname=pick.get("cname"))

    # Prefer the shortest name match (main senior club over
    # "-U18"/"Academy"/"Women" variants).
    candidates = [t for t in teams if target in strip_diacritics(t["name"]).lower()]
    pick = min(candidates, key=lambda t: len(t["name"])) if candidates else teams[0]
    return _SoccerdeskTeam(id=pick["id"], name=pick["name"], cname=pick.get("cname"))


def _parse_timestamp(ts: int | None) -> str | None:
    if not ts:
        return None
    s = str(ts)
    y, mo, d, h, mi, sec = s[0:4], s[4:6], s[6:8], s[8:10], s[10:12], s[12:14]
    return f"{y}-{mo}-{d}T{h}:{mi}:{sec}.000Z"


@dataclass
class _MatchMeta:
    home_id: str
    away_id: str
    stage_id: str


# Match-detail lookups (h2h, standings) need the two team ids and the stage
# id, none of which fit cleanly into MatchInfo -- cached here by match id
# (populated during get_soccerdesk_matches, read during
# get_soccerdesk_match_details, both called in the same process run by
# the orchestrator).
_match_meta_cache: dict[str, _MatchMeta] = {}


def _to_match_info(m: dict[str, Any]) -> MatchInfo:
    home = next(t for t in m["teams"] if t["pos"] == 0)
    away = next(t for t in m["teams"] if t["pos"] == 1)
    comp_slug = _slugify(m["c_name"])
    # .get(...) or "" -- st_name can genuinely be missing/None (a match
    # with no stage/round grouping); the competition string below already
    # guards this same field the same way, but this slug construction
    # didn't, so a None st_name crashed here before ever reaching that
    # fallback. Found via a regression test, not observed live.
    stage_slug = _slugify(m.get("st_name") or "")
    match_slug = f"{_slugify(home['name'])}-vs-{_slugify(away['name'])}"
    match_id = m["id"]

    _match_meta_cache[str(match_id)] = _MatchMeta(home_id=home["id"], away_id=away["id"], stage_id=m["st_id"])

    # status: 6 observed for finished friendlies elsewhere in this
    # codebase's research; being conservative and deriving "finished" from
    # score presence plus a past kickoff instead of trusting an
    # undocumented status enum.
    kickoff_utc = _parse_timestamp(m.get("start"))
    score = m.get("score")
    has_score = isinstance(score, list) and len(score) >= 2 and score[0] is not None and score[1] is not None
    is_past = (
        datetime.fromisoformat(kickoff_utc) < datetime.now(tz=UTC)
        if kickoff_utc
        else False
    )
    finished = has_score and is_past
    if finished:
        status = "finished"
    elif is_past:
        status = "unknown"
    else:
        status = "scheduled"

    return MatchInfo(
        source="soccerdesk",
        source_url=f"https://www.soccerdesk.com/football/{comp_slug}/{stage_slug}/{match_slug}/{match_id}",
        competition=(f"{m['c_name']} - {m['st_name']}" if m.get("st_name") else m["c_name"]),
        home_team=home["name"],
        away_team=away["name"],
        kickoff_utc=kickoff_utc,
        venue=None,
        status=status,
        home_score=(score[0] if finished else None),
        away_score=(score[1] if finished else None),
        home_score_ht=None,
        away_score_ht=None,
        season=None,
        round=None,
        match_id=str(match_id),
    )


async def get_soccerdesk_matches(team_name: str) -> list[MatchInfo]:
    team = await _find_team(team_name)
    if team is None:
        raise ValueError(f'No SoccerDesk team found matching "{team_name}"')

    data = await _fetch_json(f"https://www.soccerdesk.com/v1/en/team/soccer/teampage/{team.id}")
    all_matches = [*(data.get("fixtures") or []), *(data.get("results") or [])]
    return [_to_match_info(m) for m in all_matches]


def _apply_event_to_stats(e: dict[str, Any], entry, name_to_id: dict[str, str]) -> None:
    """One incident's effect on the per-player stats dict -- extracted
    from _build_player_event_stats to keep its own cognitive complexity
    down (python:S3776); behavior unchanged."""
    etype = e.get("type")
    if etype == 4:  # goal
        scorer_id = e.get("pl_id")
        if scorer_id:
            entry(scorer_id)["goals"] += 1
        for a in e.get("assists") or []:
            assist_id = name_to_id.get(a.get("pl_name"))
            if assist_id:
                entry(assist_id)["assists"] += 1
    elif etype == 1:  # substitution
        minute = e.get("min")
        in_id = e.get("pl_id")
        out_id = e.get("pl_id_o")
        if in_id:
            entry(in_id)["sub_on_minute"] = minute
        if out_id:
            entry(out_id)["sub_off_minute"] = minute


def _build_player_event_stats(incs: dict[str, Any] | None, name_to_id: dict[str, str]) -> dict[str, dict[str, Any]]:  # NOSONAR(S3516) -- both returns are the same *variable* (`stats`), but it's a dict mutated differently along each path (empty vs. populated), not actually a constant value
    """Goals (type 4) carry the scorer's real pl_id, but each entry in
    their own `assists` array only has a name (confirmed live -- its own
    "id" field is the incident id, a different namespace from a player
    id), so assists are resolved by exact name match against this match's
    combined roster instead. Substitutions (type 1) carry both pl_id (on)
    and pl_id_o (off) directly."""
    stats: dict[str, dict[str, Any]] = {}

    def entry(player_id: str) -> dict[str, Any]:
        return stats.setdefault(player_id, {"goals": 0, "assists": 0, "sub_on_minute": None, "sub_off_minute": None})

    if not incs:
        return stats
    for minutes in incs.values():
        for items in minutes.values():
            for e in items:
                _apply_event_to_stats(e, entry, name_to_id)
    return stats


def _extract_lineup_side(
    side: dict[str, Any] | None, event_stats: dict[str, dict[str, Any]], is_bench: bool = False
) -> list[LineupPlayer] | None:
    group = "substitutes" if is_bench else "starting"
    if not side or not side.get(group):
        return None
    players: list[LineupPlayer] = []
    for p in side[group]:
        es = event_stats.get(p["id"], {})
        if is_bench:
            on_minute = es.get("sub_on_minute")
            minutes_played = (90 - on_minute) if on_minute is not None else None
        else:
            off_minute = es.get("sub_off_minute")
            minutes_played = off_minute if off_minute is not None else 90
        players.append(
            LineupPlayer(
                name=p["name"],
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
                shirt_number=p.get("j_num"),
                age=None,
            )
        )
    return players


# Undocumented incident type codes, reverse-engineered from real match
# data: 1 = substitution (pl_id in, pl_id_o out), 4 = goal (score changes
# at that player). Other codes exist -- confirmed live 2026-09-04, codes
# 10 and 28 both appeared in one real Premier League match (single-player
# events, no score change, no pl_id_o/pl_name_o pair -- consistent with
# cards or a VAR-style incident, but not confirmed against an independent
# source, so not guessed at here) -- unknown codes fall back to "type N"
# rather than a possibly-wrong label.
_INCIDENT_TYPES: dict[int, str] = {1: "Substitution", 4: "Goal"}


def _extract_timeline(incs: dict[str, Any] | None) -> list[TimelineEvent] | None:
    """The outer dict key in `incs` is not team side (it appears to be an
    internal grouping/period id) -- each event's own `pos` field (0/1) is
    what actually marks home/away, confirmed against real match data."""
    if not incs:
        return None
    events: list[TimelineEvent] = []
    pos_to_team = {0: "home", 1: "away"}
    for minutes in incs.values():
        for items in minutes.values():
            for e in items:
                events.append(
                    TimelineEvent(
                        minute=e.get("min", 0),
                        type=_INCIDENT_TYPES.get(e.get("type"), f"type {e.get('type')}"),
                        detail=(f"{e.get('pl_name')} on for {e.get('pl_name_o')}" if e.get("type") == 1 else None),
                        player=e.get("pl_name"),
                        team=pos_to_team.get(e.get("pos")),
                    )
                )
    return sorted(events, key=lambda e: e.minute) if events else None


async def _fetch_h2h(home_id: str, away_id: str) -> tuple[HeadToHeadSummary | None, list[dict[str, Any]]]:
    """Returns both the aggregate tally AND the raw per-meeting match list
    from the same single fetch -- the individual meetings were previously
    discarded after computing the tally; _extract_recent_meetings below
    reuses them at zero extra request cost."""
    data = await _fetch_json(f"https://www.soccerdesk.com/v1/en/match/h2h/soccer/1/{home_id}/{away_id}")
    matches = (data.get("h2h") or {}).get("matches") or []
    if not matches:
        return None, []

    home_num = int(home_id.split("-")[1])
    home_wins = away_wins = draws = 0
    for m in matches:
        win = m.get("win")
        if win is None:
            continue
        if win == 0:
            draws += 1
        elif win == home_num:
            home_wins += 1
        else:
            away_wins += 1
    return HeadToHeadSummary(home_wins=home_wins, away_wins=away_wins, draws=draws), matches


def _extract_recent_meetings(h2h_matches: list[dict[str, Any]], own_team_name: str) -> list[HeadToHeadMeeting] | None:
    """SoccerDesk's own per-meeting H2H list, from the same fetch already
    made for head_to_head_summary -- zero extra requests. Capped at 3,
    same convention as Sofascore's own recent-meetings computation.
    Formation/xG/lineup aren't available for a past H2H meeting on
    SoccerDesk, so those stay None (this is a genuinely lighter-weight
    meeting record than Sofascore's, not a parsing gap)."""
    if not h2h_matches:
        return None
    # `own_team_name` here is the CURRENT match's home team, not
    # necessarily the originally-searched team (this function has no way
    # to know that -- get_soccerdesk_match_details only ever sees one
    # MatchInfo, not the search context). Correct whenever the searched
    # team is home in the upcoming fixture, "backwards" otherwise. Low-risk:
    # `venue` isn't read by any downstream computation or display string,
    # it's informational-only on the type.
    target = _normalize(own_team_name)
    out: list[HeadToHeadMeeting] = []
    for m in h2h_matches[:3]:
        teams = m.get("teams") or []
        home = next((t for t in teams if t.get("pos") == 0), None)
        away = next((t for t in teams if t.get("pos") == 1), None)
        if not home or not away:
            continue
        score = m.get("score")
        if not (isinstance(score, list) and len(score) >= 2 and score[0] is not None and score[1] is not None):
            continue  # not finished / no recorded score -- skip rather than guess
        own_is_home = _normalize(home["name"]) == target
        out.append(
            HeadToHeadMeeting(
                date=_parse_timestamp(m.get("start")),
                competition=m.get("st_name"),
                scoreline=f"{score[0]}-{score[1]}",
                venue=("home" if own_is_home else "away"),
                home_formation=None,
                away_formation=None,
                home_xg=None,
                away_xg=None,
                home_lineup=None,
                away_lineup=None,
            )
        )
    return out if out else None


def _extract_standing(rows: list[dict[str, Any]] | None, team_id: str) -> TeamStanding | None:
    row = next((r for r in (rows or []) if r["team_id"] == team_id), None)
    if row is None:
        return None
    return TeamStanding(
        position=row["ranking"],
        played=int(row["played"]),
        wins=int(row["wins"]),
        draws=int(row["draws"]),
        losses=int(row["loss"]),
        points=int(row["points"]),
        goal_diff=row["goal_difference"],
        total_teams=(len(rows) if rows else None),
    )


def _extract_manager(coaches: list[dict[str, Any]] | None) -> ManagerInfo | None:
    """Same match-page lineup object already fetched for the starting XI
    -- SoccerDesk has no appointment-date/previous-manager/country data,
    so those stay None."""
    if not coaches:
        return None
    name = coaches[0].get("name")
    if not name:
        return None
    return ManagerInfo(name=name, country=None, appointed_date=None, previous_manager=None, recent_appointment=None)


def _build_name_to_id(home, away) -> dict[str, str]:
    """Extracted from get_soccerdesk_match_details to keep its own
    cognitive complexity down (python:S3776); behavior unchanged."""
    name_to_id: dict[str, str] = {}
    for side in (home, away):
        for group in ("starting", "substitutes"):
            for p in (side or {}).get(group) or []:
                name_to_id[p["name"]] = p["id"]
    return name_to_id


async def _fetch_standings_and_h2h(meta, match: MatchInfo):
    """Returns (head_to_head_summary, recent_meetings, home_team_standing,
    away_team_standing). Extracted from get_soccerdesk_match_details to
    keep its own cognitive complexity down (python:S3776); behavior
    unchanged."""
    head_to_head_summary = None
    recent_meetings: list[HeadToHeadMeeting] | None = None
    home_team_standing: TeamStanding | None = None
    away_team_standing: TeamStanding | None = None
    if not meta:
        return head_to_head_summary, recent_meetings, home_team_standing, away_team_standing
    try:
        head_to_head_summary, h2h_matches = await _fetch_h2h(meta.home_id, meta.away_id)
        recent_meetings = _extract_recent_meetings(h2h_matches, own_team_name=match.home_team)
    except Exception:  # noqa: BLE001 - mirrors TS's .catch(() => null)
        head_to_head_summary = None
    if meta.stage_id:
        try:
            stage = await _fetch_json(f"https://www.soccerdesk.com/v1/en/stage/soccer/{meta.stage_id}")
        except Exception:  # noqa: BLE001 - mirrors TS's .catch(() => null)
            stage = None
        tables = ((stage or {}).get("L") or {}).get("tables") or []
        rows = tables[0].get("teams") if tables else None
        home_team_standing = _extract_standing(rows, meta.home_id)
        away_team_standing = _extract_standing(rows, meta.away_id)
    return head_to_head_summary, recent_meetings, home_team_standing, away_team_standing


def _soccerdesk_note(injured_names: list[str], home_suspended_names: list[str], away_suspended_names: list[str]) -> str:
    """The note field's own filter(None, [...]) computation, extracted
    from get_soccerdesk_match_details to keep its cognitive complexity
    down (python:S3776); behavior unchanged."""
    suspended_names = [*home_suspended_names, *away_suspended_names]
    return "; ".join(
        filter(
            None,
            [
                "referee/attendance/weather/match-stats not available on SoccerDesk",
                (f"Injured (not playing): {', '.join(injured_names)}" if injured_names else None),
                (f"Suspended: {', '.join(suspended_names)}" if suspended_names else None),
            ],
        )
    )


async def get_soccerdesk_match_details(match: MatchInfo) -> MatchDetails:
    """SoccerDesk genuinely has no referee/attendance/weather/match stats
    anywhere in its UI (confirmed: the match page only has Info/Lineups/
    H2H tabs, and none of those strings appear in the raw match JSON) --
    those stay null here, not a scraper gap. Venue IS present on this same
    match-detail payload (confirmed live: name/city/lat/long/capacity) --
    an earlier assumption that it wasn't was wrong."""
    match_id = [p for p in match.source_url.split("/") if p][-1]
    data = await _fetch_json(f"https://www.soccerdesk.com/v1/en/match/soccer/full/{match_id}")

    lineup = data.get("lineup") or []
    home = next((l for l in lineup if l.get("pos") == 0), None)
    away = next((l for l in lineup if l.get("pos") == 1), None)
    venue = data.get("venue") if data.get("has_venue") else None

    name_to_id = _build_name_to_id(home, away)
    event_stats = _build_player_event_stats(data.get("incs"), name_to_id)

    meta = _match_meta_cache.get(match_id)
    head_to_head_summary, recent_meetings, home_team_standing, away_team_standing = (
        await _fetch_standings_and_h2h(meta, match)
    )

    injured_names = [p["name"] for p in [*((home or {}).get("injured") or []), *((away or {}).get("injured") or [])]]
    home_suspended_names = [p["name"] for p in (home or {}).get("suspended") or []]
    away_suspended_names = [p["name"] for p in (away or {}).get("suspended") or []]
    venue_lat = float(venue["lat"]) if venue and venue.get("lat") else None
    venue_lon = float(venue["long"]) if venue and venue.get("long") else None

    return MatchDetails(
        **{**asdict(match), "venue": (venue or {}).get("name")},
        venue_name=(venue or {}).get("name"),
        venue_city=(venue or {}).get("city"),
        venue_country=None,
        venue_lat=venue_lat,
        venue_lon=venue_lon,
        referee=None,
        referee_stats=None,
        attendance=None,
        weather=None,
        weather_detail=None,
        head_to_head_summary=head_to_head_summary,
        head_to_head_streaks=None,
        recent_meetings=recent_meetings,
        home_lineup=_extract_lineup_side(home, event_stats),
        away_lineup=_extract_lineup_side(away, event_stats),
        home_bench=_extract_lineup_side(home, event_stats, is_bench=True),
        away_bench=_extract_lineup_side(away, event_stats, is_bench=True),
        home_formation=None,
        away_formation=None,
        home_team_country=None,
        away_team_country=None,
        home_manager=_extract_manager((home or {}).get("coaches")),
        away_manager=_extract_manager((away or {}).get("coaches")),
        home_manager_vs_away_club=None,
        away_manager_vs_home_club=None,
        standings_table=None,
        home_suspended_players=(home_suspended_names or None),
        away_suspended_players=(away_suspended_names or None),
        home_team_standing=home_team_standing,
        away_team_standing=away_team_standing,
        home_team_season_stats=None,
        away_team_season_stats=None,
        match_stats=None,
        event_timeline=_extract_timeline(data.get("incs")),
        set_piece_goals=None,
        shotmap_stats=None,
        lineup_confirmed=None,
        player_of_the_match=None,
        note=_soccerdesk_note(injured_names, home_suspended_names, away_suspended_names),
    )


async def get_soccerdesk_team_profile(team_name: str) -> TeamProfile:
    """SoccerDesk's squad list (from the same teampage response used for
    fixtures) only has name/nationality/jersey number -- no injuries, age,
    or market value at the team level (those only appear per-match, on
    players who were actually named in a squad for that game -- see
    get_soccerdesk_match_details' injured/suspended note). No transfers
    endpoint was found either."""
    team = await _find_team(team_name)
    if team is None:
        raise ValueError(f'No SoccerDesk team found matching "{team_name}"')

    data = await _fetch_json(f"https://www.soccerdesk.com/v1/en/team/soccer/teampage/{team.id}")

    squad: list[SquadMember] = [
        SquadMember(
            name=p["name"],
            role=None,
            injury=None,
            age=None,
            market_value=None,
            season_stats=None,
            season_stats_source=None,
            defensive_stats=None,
            recent_usage=None,
        )
        for p in data.get("participants") or []
    ]

    return TeamProfile(
        source="soccerdesk",
        team_name=data.get("name") or team_name,
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
