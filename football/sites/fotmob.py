"""Fotmob scraper. Ported from src/sites/fotmob.ts.

Fotmob's own sitemap (allowed by robots.txt) is the only non-API way to
resolve a team name to its numeric id + canonical page URL.
`match.sourceUrl` from get_fotmob_matches() is a full page URL. That page's
own __NEXT_DATA__ embeds venue, referee, weather, predicted lineups, and
h2h -- still a plain page GET, no /api/ involved.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from .._jsmath import js_round_to
from ..data_dir import data_dir
from ..http import fetch_text
from ..team_aliases import find_best_slug_match
from ..team_name_match import normalize_for_match as _normalize
from ..types import (
    HeadToHeadMeeting,
    LineupPlayer,
    ManagerInfo,
    MatchDetails,
    MatchInfo,
    MatchStatItem,
    MissingPlayer,
    PlayerOfTheMatch,
    SeasonPlayerStats,
    SquadMember,
    TeamProfile,
    TimelineEvent,
    TransferRecord,
)

_SITEMAP_INDEX_URL = "https://www.fotmob.com/sitemap/en/teams.xml"
_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
_TEAM_URL_RE = re.compile(r"/teams/(\d+)/overview/([^/?#]+)")


@dataclass
class _TeamIndexEntry:
    id: int
    slug: str
    url: str


def _extract_locs(xml: str) -> list[str]:
    return _LOC_RE.findall(xml)


async def _build_teams_index() -> list[_TeamIndexEntry]:
    index_xml = await fetch_text(_SITEMAP_INDEX_URL)
    shard_urls = _extract_locs(index_xml)

    entries: list[_TeamIndexEntry] = []
    for shard_url in shard_urls:
        xml = await fetch_text(shard_url)
        for url in _extract_locs(xml):
            m = _TEAM_URL_RE.search(url)
            if m:
                entries.append(_TeamIndexEntry(id=int(m.group(1)), slug=m.group(2), url=url))
    return entries


async def _load_teams_index() -> list[_TeamIndexEntry]:
    seed_path = data_dir() / "fotmob-teams.json"
    try:
        raw = json.loads(seed_path.read_text(encoding="utf-8"))
        return [_TeamIndexEntry(**e) for e in raw]
    except (FileNotFoundError, json.JSONDecodeError):
        entries = await _build_teams_index()
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_text(json.dumps([{"id": e.id, "slug": e.slug, "url": e.url} for e in entries]), encoding="utf-8")
        return entries


# Fotmob-specific slug overrides: normalized team name -> the exact slug
# to search for instead, checked BEFORE the alias loop below (which would
# otherwise reach the wrong exact match first and return immediately).
#
# Confirmed live, directly, by fetching each candidate team's own Fotmob
# page and reading its `details.country` field (not guessed from the
# slug or title, both of which are misleading here): a real Uruguayan
# club (Montevideo, stadium Estadio Belvedere) is ALSO officially named
# "Liverpool FC" and happens to hold the Fotmob slug "liverpool-fc" (id
# 2219, country="URU") -- team_aliases.py's canonical alias for this
# project's "Liverpool" is "Liverpool FC", normalizing to exactly that
# slug, so the alias loop's exact-match branch hit the Uruguayan club
# first and returned before ever trying the plain "liverpool" alias.
# The real English Premier League club is the plain slug "liverpool"
# (id 8650, confirmed country="ENG") -- lower priority in the alias
# list, never reached. This silently poisoned every Fotmob-derived
# insight for "Liverpool" searches (season xG/shots/aerial/passing/
# fouls/goalkeeping/possession/corners estimates all computed from the
# Uruguayan club's matches, coming back None only because those
# specific matches happen to lack the relevant Fotmob stat fields --
# not because data was genuinely unavailable for the real club).
_FOTMOB_SLUG_OVERRIDE: dict[str, str] = {
    "liverpool": "liverpool",
    "liverpool fc": "liverpool",
}


def _find_best_team_match(entries: list[_TeamIndexEntry], team_name: str) -> _TeamIndexEntry | None:
    # Still REQUIRED even after find_best_slug_match's own general
    # exact-match-across-all-aliases pass below -- confirmed live by
    # removing it and re-testing: Fotmob's Uruguayan club is stored under
    # the literal slug "liverpool-fc" (a genuine exact match, not a
    # substring false-positive), and known_aliases_for() tries the
    # canonical alias ("liverpool fc") before the shorter alias
    # ("liverpool") that would reach the real English club -- so even a
    # full exact-match pass across every alias hits the wrong team's
    # real, exact slug first. This is a different failure mode than the
    # substring-collision bug find_best_slug_match's own algorithm
    # addresses (see goal.py, where the equivalent override turned out to
    # be genuinely redundant and was removed after the same live test).
    # See find_best_slug_match's own docstring (team_aliases.py) for the
    # full 3-pass algorithm this delegates to -- was duplicated verbatim
    # here before being consolidated.
    override_slug = _FOTMOB_SLUG_OVERRIDE.get(_normalize(team_name))
    if override_slug:
        exact = next((e for e in entries if e.slug == override_slug), None)
        if exact:
            return exact

    return find_best_slug_match(entries, team_name)


_NEXT_DATA_MARKER = "__NEXT_DATA__"


def _extract_next_data(html: str) -> Any:
    i = html.find(_NEXT_DATA_MARKER)
    if i == -1:
        raise ValueError("__NEXT_DATA__ not found in Fotmob page")
    start = html.find(">", i) + 1
    end = html.find("</script>", start)
    return json.loads(html[start:end])


async def _fetch_team_fixtures(entry: _TeamIndexEntry) -> list[dict[str, Any]]:
    html = await fetch_text(entry.url)
    data = _extract_next_data(html)

    fallback = data["props"]["pageProps"]["fallback"]
    key = next((k for k in fallback if k.startswith("team-")), None)
    if key is None:
        raise ValueError("team fallback key not found in Fotmob __NEXT_DATA__")

    return fallback[key]["fixtures"]["allFixtures"]["fixtures"]


def _fixture_status(status: dict[str, Any], finished: bool) -> str:
    """Extracted from get_fotmob_matches to replace a nested ternary
    (python:S3358) and keep the caller's own cognitive complexity down
    (python:S3776); behavior unchanged."""
    if status.get("cancelled"):
        return "cancelled"
    if finished:
        return "finished"
    if status.get("started"):
        return "live"
    return "scheduled"


def _to_match_info(f: dict[str, Any]) -> MatchInfo:
    """Extracted from get_fotmob_matches to keep its own cognitive
    complexity down (python:S3776); behavior unchanged."""
    status = f["status"]
    finished = status.get("finished", False)
    return MatchInfo(
        source="fotmob",
        source_url=f"https://www.fotmob.com{f['pageUrl']}",
        competition=(f.get("tournament") or {}).get("name"),
        home_team=f["home"]["name"],
        away_team=f["away"]["name"],
        kickoff_utc=status.get("utcTime"),
        venue=None,
        status=_fixture_status(status, finished),
        # Fotmob's raw fixture data sets score to 0 (not null/absent)
        # for matches that haven't been played yet -- only trust it
        # once finished.
        home_score=(f["home"].get("score") if finished else None),
        away_score=(f["away"].get("score") if finished else None),
        # Fotmob's fixtures-list entries don't include a half-time
        # split (only full-time score); Sofascore's do.
        home_score_ht=None,
        away_score_ht=None,
        # Fotmob doesn't publish a distinct season label or round
        # number on this fixture-list payload -- Sofascore-only field.
        season=None,
        round=None,
        match_id=str(f["id"]),
    )


async def get_fotmob_matches(team_name: str) -> list[MatchInfo]:
    index = await _load_teams_index()
    team = _find_best_team_match(index, team_name)
    if team is None:
        raise ValueError(f'No Fotmob team found matching "{team_name}"')

    fixtures = await _fetch_team_fixtures(team)
    return [_to_match_info(f) for f in fixtures]


def _minutes_from_sub_events(sub_events: list[dict[str, Any]], is_bench: bool) -> int | None:
    """No exact stoppage-time tracking here (same precision as this
    project's other event-derived minutes estimates) -- a starter with no
    subOut event is assumed to have played the full 90; an unused sub
    (no subIn event) stays null, not 0, same convention as every other
    source."""
    for e in sub_events:
        if is_bench and e.get("type") == "subIn":
            on_minute = e.get("time")
            return (90 - on_minute) if on_minute is not None else None
        if not is_bench and e.get("type") == "subOut":
            return e.get("time")
    return None if is_bench else 90


def _extract_lineup(team: dict[str, Any] | None, is_bench: bool = False) -> list[LineupPlayer] | None:
    group = "subs" if is_bench else "starters"
    if not team or not team.get(group):
        return None
    # Fotmob only gives a numeric positionId here with no legend on this
    # page to translate it (e.g. GK/DF/MF/FW) -- storing the raw id rather
    # than guessing a mapping that could be wrong.
    out: list[LineupPlayer] = []
    for p in team[group]:
        perf = p.get("performance") or {}
        events = perf.get("events") or []
        shirt_raw = p.get("shirtNumber")
        out.append(
            LineupPlayer(
                name=p["name"],
                position=(str(p["positionId"]) if p.get("positionId") is not None else None),
                substitute=is_bench,
                minutes_played=_minutes_from_sub_events(perf.get("substitutionEvents") or [], is_bench),
                goals=sum(1 for e in events if e.get("type") == "goal"),
                assists=sum(1 for e in events if e.get("type") == "assist"),
                xg=None,
                xa=None,
                shots=None,
                shots_on_target=None,
                tackles=None,
                interceptions=None,
                fouls=None,
                rating=perf.get("rating"),
                key_passes=None,
                shirt_number=(int(shirt_raw) if shirt_raw not in (None, "") else None),
                age=p.get("age"),
            )
        )
    return out


def _extract_manager(coach: dict[str, Any] | None) -> ManagerInfo | None:
    """Same match-page `lineup.{home,away}Team.coach` object already
    fetched for the starting XI -- zero extra requests. Fotmob has no
    appointment-date/previous-manager data (Sofascore/Wikipedia-only), so
    those stay None here."""
    if not coach or not coach.get("name"):
        return None
    return ManagerInfo(
        name=coach["name"],
        country=coach.get("countryName"),
        appointed_date=None,
        previous_manager=None,
        recent_appointment=None,
    )


def _extract_unavailable(team: dict[str, Any] | None) -> list[MissingPlayer] | None:
    """Same match-page lineup object already fetched -- Fotmob's own
    match-specific unavailability list, analogous to Sofascore's
    missingPlayers. `unavailability.type` ("injury"/"suspension"/etc) is
    the closest Fotmob equivalent to Sofascore's description text."""
    unavailable = (team or {}).get("unavailable")
    if not unavailable:
        return None
    result = []
    for p in unavailable:
        u = p.get("unavailability") or {}
        result.append(MissingPlayer(name=p["name"], description=u.get("type"), expected_return=u.get("expectedReturn")))
    return result


def _extract_recent_meetings(h2h_matches: list[dict[str, Any]] | None, own_team_name: str) -> list[HeadToHeadMeeting] | None:
    """Same match-page h2h fetch already made for headToHeadSummary --
    zero extra requests. Caught live: each entry's own top-level
    `finished` key is stale/always-false; the real "did this happen"
    flag and score live nested under `status` (`status.finished`,
    `status.scoreStr` as "H - A") -- confirmed against real historical
    Liverpool/Sunderland meetings spanning 2017-2026. Capped at 3, same
    convention as every other source's recent-meetings extraction.

    `own_team_name` is the CURRENT match's home team, not necessarily the
    originally searched team (this function has no way to know that) --
    correct whenever the searched team is home in the upcoming fixture,
    "backwards" otherwise. Low-risk: `venue` isn't read by any downstream
    computation or display string, it's informational-only on the type."""
    if not h2h_matches:
        return None
    target = _normalize(own_team_name)
    finished = [m for m in h2h_matches if (m.get("status") or {}).get("finished")]
    out = [meeting for m in finished[:3] if (meeting := _h2h_meeting_from(m, target)) is not None]
    return out if out else None


def _h2h_meeting_from(m: dict[str, Any], target: str) -> HeadToHeadMeeting | None:
    """Extracted from _extract_recent_meetings to keep its own cognitive
    complexity down (python:S3776); behavior unchanged. Returns None for
    an entry with no recorded score or missing team names, same as the
    original loop's `continue` cases."""
    status = m.get("status") or {}
    score_str = status.get("scoreStr")
    if not score_str or " - " not in score_str:
        return None  # no recorded score -- skip rather than guess
    home_score, away_score = score_str.split(" - ", 1)
    home = m.get("home") or {}
    away = m.get("away") or {}
    if not home.get("name") or not away.get("name"):
        return None
    own_is_home = _normalize(home["name"]) == target
    return HeadToHeadMeeting(
        date=(m.get("time") or {}).get("utcTime"),
        competition=(m.get("league") or {}).get("name"),
        scoreline=f"{home_score}-{away_score}",
        venue=("home" if own_is_home else "away"),
        home_formation=None,
        away_formation=None,
        home_xg=None,
        away_xg=None,
        home_lineup=None,
        away_lineup=None,
    )


def _extract_timeline(match_facts: dict[str, Any] | None) -> list[TimelineEvent] | None:
    """Field names (type/time/player/isHome/newScore) confirmed against a
    finished match's real events array -- this match's own array is empty
    pre-kickoff, which is expected (nothing has happened yet), not a bug."""
    events = ((match_facts or {}).get("events") or {}).get("events")
    if not events:
        return None
    result = []
    for e in events:
        is_home = e.get("isHome")
        team = {True: "home", False: "away"}.get(is_home)
        result.append(
            TimelineEvent(
                minute=e.get("time", 0),
                type=e.get("type", "unknown"),
                detail=(e.get("minutesAddedStr") if e.get("type") == "AddedTime" else None),
                player=(e.get("player") or {}).get("name"),
                team=team,
            )
        )
    return result


def _stat_value(values: list[Any], idx: int) -> str:
    return str(values[idx] if len(values) > idx and values[idx] is not None else "")


def _extract_match_stat_item(it: dict[str, Any]) -> MatchStatItem:
    values = it.get("stats") or []
    return MatchStatItem(name=it["title"], home=_stat_value(values, 0), away=_stat_value(values, 1))


def _extract_match_stats(stats: dict[str, Any] | None) -> list[MatchStatItem] | None:
    groups = ((stats or {}).get("Periods") or {}).get("All", {}).get("stats")
    if not groups:
        return None
    return [_extract_match_stat_item(it) for g in groups for it in g.get("stats") or []]


def _extract_player_of_the_match(potm: dict[str, Any] | None) -> PlayerOfTheMatch | None:
    if not potm:
        return None
    name_field = potm.get("name")
    name = name_field.get("fullName") if isinstance(name_field, dict) else name_field
    if not name:
        return None  # not populated until the match is live/finished
    return PlayerOfTheMatch(name=name, rating=(potm.get("rating") or {}).get("num"))


def _extract_squad(squad_data: dict[str, Any] | None) -> list[SquadMember] | None:
    groups = (squad_data or {}).get("squad")
    if not groups:
        return None
    out = []
    for g in groups:
        if g.get("title", "").lower() == "coach":
            continue  # coaching staff, not squad players -- has no goals/assists/cards fields at all
        for m in g.get("members") or []:
            injury = m.get("injury")
            out.append(
                SquadMember(
                    name=m["name"],
                    role=(m.get("role") or {}).get("fallback"),
                    # Fotmob's injury object here only has an id +
                    # expectedReturn, no reason text (unlike Sofascore's),
                    # so that's all there is to report.
                    injury=(f"Injured, expected return: {injury.get('expectedReturn', 'unknown')}" if injury else None),
                    age=m.get("age"),
                    market_value=m.get("transferValue"),
                    # Same squad member object -- Fotmob publishes real
                    # per-player rating/goals/assists/cards for the whole
                    # squad here (confirmed live), not just a top-3
                    # leaderboard -- zero extra requests. No appearances
                    # count anywhere on this page (see SeasonPlayerStats'
                    # doc comment) or expected-goals per player, so those
                    # stay None rather than guessed.
                    season_stats=SeasonPlayerStats(
                        appearances=None,
                        goals=m.get("goals", 0),
                        assists=m.get("assists", 0),
                        yellow_cards=m.get("ycards", 0),
                        red_cards=m.get("rcards", 0),
                        rating=m.get("rating"),
                        expected_goals=None,
                    ),
                    season_stats_source="fotmob",
                    defensive_stats=None,
                    recent_usage=None,
                )
            )
    return out


def _extract_transfers(transfers_data: dict[str, Any] | None) -> list[TransferRecord] | None:
    groups = (transfers_data or {}).get("data")
    if not groups:
        return None
    out = []
    for key, lst in groups.items():
        direction = "out" if "out" in key.lower() else "in"
        for t in lst:
            out.append(
                TransferRecord(
                    player_name=t["name"],
                    direction=direction,
                    from_club=t.get("fromClub"),
                    to_club=t.get("toClub"),
                    date=t.get("transferDate"),
                )
            )
    return out if out else None


async def get_fotmob_team_profile(team_name: str) -> TeamProfile:
    """Reuses the same team page fetched for get_fotmob_matches() -- squad
    and transfers are embedded in the same __NEXT_DATA__ fallback object,
    so this is just a second GET of a page already established as in
    scope."""
    index = await _load_teams_index()
    team = _find_best_team_match(index, team_name)
    if team is None:
        raise ValueError(f'No Fotmob team found matching "{team_name}"')

    html = await fetch_text(team.url)
    data = _extract_next_data(html)
    fallback = data["props"]["pageProps"]["fallback"]
    key = next((k for k in fallback if k.startswith("team-")), None)
    if key is None:
        raise ValueError("team fallback key not found in Fotmob __NEXT_DATA__")
    team_data = fallback[key]

    squad = _extract_squad(team_data.get("squad"))
    ages = [s.age for s in squad if s.age is not None] if squad else []
    injuries = [s for s in squad if s.injury is not None] if squad else None
    key_injuries = sorted(injuries, key=lambda s: s.market_value or 0, reverse=True)[:3] if injuries else None

    return TeamProfile(
        source="fotmob",
        team_name=(team_data.get("details") or {}).get("name") or team_name,
        squad=squad,
        average_age=(js_round_to(sum(ages) / len(ages), 1) if ages else None),
        injuries=injuries,
        key_injuries=key_injuries,
        recent_transfers=_extract_transfers(team_data.get("transfers")),
        missing_midfielders=None,  # computed centrally once search.py's orchestrator is ported
        missing_attackers=None,
        missing_defenders=None,
        missing_goalkeepers=None,
    )


async def get_fotmob_match_details(match: MatchInfo) -> MatchDetails:
    html = await fetch_text(match.source_url)
    data = _extract_next_data(html)
    content = data["props"]["pageProps"]["content"]
    info_box = (content.get("matchFacts") or {}).get("infoBox") or {}
    stadium = info_box.get("Stadium") or {}
    weather = content.get("weather")
    lineup = content.get("lineup") or {}
    home_lineup_raw = lineup.get("homeTeam")
    away_lineup_raw = lineup.get("awayTeam")
    referee = info_box.get("Referee") or {}
    h2h_matches = (content.get("h2h") or {}).get("matches")

    return MatchDetails(
        **{**asdict(match), "venue": stadium.get("name")},
        venue_name=stadium.get("name"),
        venue_city=stadium.get("city"),
        venue_country=stadium.get("country"),
        venue_lat=None,
        venue_lon=None,
        referee=referee.get("text") or None,
        # Fotmob's referee object only has name/country/image, no career
        # stats (unlike Sofascore's, which includes games/cards) -- nothing
        # to report.
        referee_stats=None,
        attendance=info_box.get("Attendance"),
        weather=(f"{weather['description']}, {weather['temperature']}°C" if weather else None),
        # Fotmob's own weather blob only carries description+temperature,
        # no humidity/wind/precip -- structured detail only ever comes
        # from the wttr.in enrichment step.
        weather_detail=None,
        # Fotmob's h2h.summary is an undocumented 3-number array with no
        # way to verify which number is home/away/draws from this page
        # alone -- leaving unset rather than guessing at an attribution
        # that could be wrong.
        head_to_head_summary=None,
        head_to_head_streaks=None,
        recent_meetings=_extract_recent_meetings(h2h_matches, own_team_name=match.home_team),
        home_lineup=_extract_lineup(home_lineup_raw),
        away_lineup=_extract_lineup(away_lineup_raw),
        home_bench=_extract_lineup(home_lineup_raw, is_bench=True),
        away_bench=_extract_lineup(away_lineup_raw, is_bench=True),
        home_formation=(home_lineup_raw or {}).get("formation"),
        away_formation=(away_lineup_raw or {}).get("formation"),
        home_team_country=None,
        away_team_country=None,
        home_manager=_extract_manager((home_lineup_raw or {}).get("coach")),
        away_manager=_extract_manager((away_lineup_raw or {}).get("coach")),
        home_manager_vs_away_club=None,
        away_manager_vs_home_club=None,
        standings_table=None,
        home_suspended_players=None,
        away_suspended_players=None,
        home_missing_players=_extract_unavailable(home_lineup_raw),
        away_missing_players=_extract_unavailable(away_lineup_raw),
        # Fotmob's `table` field is just a pointer to a table file on a
        # separate data.fotmob.com host, out of scope here (Sofascore
        # already covers standings), so these stay null for this source.
        home_team_standing=None,
        away_team_standing=None,
        # Fotmob's team-page `stats` field gives per-player leaderboards
        # (top scorer etc.) with actual values on data.fotmob.com, not
        # team-aggregate season card/goal totals -- confirmed checking a
        # mid-season team.
        home_team_season_stats=None,
        away_team_season_stats=None,
        match_stats=_extract_match_stats(content.get("stats")),
        event_timeline=_extract_timeline(content.get("matchFacts")),
        set_piece_goals=None,
        shotmap_stats=None,
        lineup_confirmed=None,
        player_of_the_match=_extract_player_of_the_match((content.get("matchFacts") or {}).get("playerOfTheMatch")),
        note=("lineup is last known XI, not confirmed" if lineup.get("lineupType") == "lastStartingLineups" else None),
    )
