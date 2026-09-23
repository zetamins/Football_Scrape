"""Per-match insight computations: standings zones, card discipline, travel,
rotation, fatigue, card risk, standings-impact simulation, and the two
season-estimate fetch loops (Fotmob match-stats, Goal.com possession).
Ported from src/search.ts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ._jsmath import js_round, js_round_to
from .elo import is_friendly_competition
from .fetch_log import record_step_failure
from .form import NOT_STARTED_STATUSES as _NOT_STARTED_STATUSES
from .form import day_diff, is_team_home, normalize_team_name, parse_leading_int, result_goals
from .geo import country_distance_km, country_timezone_diff_hours, travel_time_hours
from .merge import (
    CONFIRMED_EMPTY_FIELDS,
    is_attacker_role,
    is_defender_role,
    is_goalkeeper_role,
    is_midfield_role,
)
from .team_aliases import same_team
from .types import (
    CardDisciplineInfo,
    CardDisciplineVenueSplit,
    DirectPlayExposureFlag,
    DuelVulnerability,
    ExperienceComparison,
    ExperienceH2HNote,
    FatigueFlag,
    FormResult,
    TeamSeasonStats,
    FullbackExposureInfo,
    HeadToHeadMeeting,
    HeadToHeadSummary,
    HomeAdvantageInfo,
    LineupPlayer,
    LosingStreakContextInfo,
    MatchDetails,
    MatchInfo,
    MatchInsights,
    MatchType,
    OpponentRankRecord,
    PlayerCardRisk,
    PlayerUsagePattern,
    PossessionMatchupInfo,
    PresenceEntry,
    RefereeCardRiskNote,
    RefereeStats,
    ResilienceInfo,
    RestComparison,
    RestPerformanceInfo,
    RotationInfo,
    SeasonAerialEstimate,
    SeasonBigChancesEstimate,
    SeasonCornersEstimate,
    SeasonDefensiveErrorsEstimate,
    SeasonFoulsEstimate,
    SeasonGoalkeepingEstimate,
    SeasonPassingStyleEstimate,
    SeasonShotsEstimate,
    SeasonXGEstimate,
    SetPieceThreatFlag,
    Source,
    SquadMember,
    SquadStrengthInfo,
    StandingsImpactInfo,
    StandingsScenario,
    StandingsTableRow,
    StandingsZoneInfo,
    StreakInfo,
    StreakStabilityInfo,
    TeamStanding,
)

# Real continental/relegation spot counts for competitions we can name
# exactly (matched against Sofascore's own competition name string).
# Falls back to the generic 4/3 rule for anything not in this table.
LEAGUE_STAKES: dict[str, dict[str, int]] = {
    "Premier League": {"continental_spots": 4, "relegation_spots": 3},
    "LaLiga": {"continental_spots": 4, "relegation_spots": 3},
    "La Liga": {"continental_spots": 4, "relegation_spots": 3},
    "Serie A": {"continental_spots": 4, "relegation_spots": 3},
    "Bundesliga": {"continental_spots": 4, "relegation_spots": 2},
    "Ligue 1": {"continental_spots": 3, "relegation_spots": 2},
    "Brasileirão Betano": {"continental_spots": 6, "relegation_spots": 4},
    "Primeira Liga": {"continental_spots": 3, "relegation_spots": 3},
    "Eredivisie": {"continental_spots": 3, "relegation_spots": 2},
}


def classify_standings_zone(
    standing: TeamStanding | None, competition: str | None, standings_table
) -> StandingsZoneInfo | None:
    if not standing or not standing.total_teams:
        return None
    stakes = LEAGUE_STAKES.get(competition) if competition else None
    continental_spots = stakes["continental_spots"] if stakes else 4
    relegation_spots = stakes["relegation_spots"] if stakes else 3
    if standing.position <= continental_spots:
        zone = "top-of-table"
    elif standing.position > standing.total_teams - relegation_spots:
        zone = "relegation-zone"
    else:
        zone = "midtable"

    points_from_boundary: int | None = None
    if standings_table:
        by_position = {r.position: r.points for r in standings_table}
        continental_boundary_pts = by_position.get(continental_spots, by_position.get(continental_spots + 1))
        relegation_boundary_pts = by_position.get(
            standing.total_teams - relegation_spots, by_position.get(standing.total_teams - relegation_spots + 1)
        )
        gaps = [abs(standing.points - p) for p in (continental_boundary_pts, relegation_boundary_pts) if p is not None]
        if gaps:
            points_from_boundary = min(gaps)

    return StandingsZoneInfo(
        position=standing.position,
        total_teams=standing.total_teams,
        zone=zone,
        points_from_boundary=points_from_boundary,
        in_the_mix=(points_from_boundary <= 6 if points_from_boundary is not None else None),
    )


def classify_match_type(competition: str | None) -> MatchType | None:
    """See MatchType's doc comment -- text classification, not a distinct
    field any source publishes as a boolean. Delegates to
    is_friendly_competition (elo.py) so this and form.py's own
    friendly/preseason exclusion never drift apart on what counts as a
    friendly."""
    if not competition:
        return None
    return "friendly" if is_friendly_competition(competition) else "competitive"


def classify_card_discipline(stats, standing: TeamStanding | None) -> CardDisciplineInfo | None:
    played = standing.played if standing else None
    if not stats or not played:
        return None
    yellow_per_game = js_round_to(stats.yellow_cards / played, 2)
    red_per_game = js_round_to(stats.red_cards / played, 2)
    return CardDisciplineInfo(yellow_per_game=yellow_per_game, red_per_game=red_per_game, elevated_risk=(yellow_per_game > 2.5 or red_per_game > 0.2))


def _travel_km(traveling: bool | None, from_country: str | None, to_country: str) -> float | None:
    """Country-level approximation, used only when a team's own exact
    venue coordinates aren't available. Extracted from compute_travel_info
    to keep its own cognitive complexity down (python:S3776)."""
    if traveling and from_country:
        return country_distance_km(from_country, to_country)
    if traveling is False:
        return 0
    return None


# Below this, two stadium coordinates are treated as "the same place" --
# covers GPS/rounding noise and same-ground fixtures, not meant to
# distinguish genuinely close-but-different grounds (e.g. two clubs a
# few km apart in the same city still count as "traveling", correctly,
# since that's real distance a team has to cover).
_SAME_VENUE_THRESHOLD_KM = 2


def _team_travel(
    team_lat: float | None, team_lon: float | None, team_country: str | None,
    venue_lat: float | None, venue_lon: float | None, venue_country: str,
) -> tuple[bool | None, float | None]:
    """One side (home or away) of compute_travel_info's travel/distance
    determination, extracted to keep that function's own cognitive
    complexity down (python:S3776).

    Prefers exact venue-to-venue distance (this team's own home ground
    vs the match venue, both from Sofascore) when both coordinates are
    available; falls back to the country-level approximation otherwise.
    Confirmed live that the country-only approximation reports 0km/not-
    traveling for EVERY same-country match regardless of actual
    distance (Newcastle away at Coventry, ~250km, showed 0) -- exact
    coordinates fix this for same-country trips specifically, which is
    most of this project's own match volume (English football)."""
    if team_lat is not None and team_lon is not None and venue_lat is not None and venue_lon is not None:
        from .geo import Coord, haversine_km

        km = haversine_km(Coord(team_lat, team_lon), Coord(venue_lat, venue_lon))
        return km > _SAME_VENUE_THRESHOLD_KM, km
    if not team_country:
        return None, None
    traveling = team_country != venue_country
    return traveling, _travel_km(traveling, team_country, venue_country)


def compute_travel_info(merged: MatchDetails):
    """Sofascore-only fields (venue_country/home_team_country/
    away_team_country, and the exact venue coordinates _team_travel
    prefers when available) -- null from every other base source."""
    from .types import TravelInfo

    if not merged.venue_country or (not merged.home_team_country and not merged.away_team_country):
        return None
    home_traveling, home_km = _team_travel(
        merged.home_team_venue_lat, merged.home_team_venue_lon, merged.home_team_country,
        merged.venue_lat, merged.venue_lon, merged.venue_country,
    )
    away_traveling, away_km = _team_travel(
        merged.away_team_venue_lat, merged.away_team_venue_lon, merged.away_team_country,
        merged.venue_lat, merged.venue_lon, merged.venue_country,
    )
    return TravelInfo(
        venue_country=merged.venue_country,
        home_team_country=merged.home_team_country,
        away_team_country=merged.away_team_country,
        home_traveling=home_traveling,
        away_traveling=away_traveling,
        home_travel_distance_km=home_km,
        away_travel_distance_km=away_km,
        home_timezone_diff_hours=(country_timezone_diff_hours(merged.home_team_country, merged.venue_country) if merged.home_team_country else None),
        away_timezone_diff_hours=(country_timezone_diff_hours(merged.away_team_country, merged.venue_country) if merged.away_team_country else None),
        home_travel_time_hours=(travel_time_hours(home_km) if home_km is not None else None),
        away_travel_time_hours=(travel_time_hours(away_km) if away_km is not None else None),
    )


def compute_opponent_rank_record(results, competition: str | None, standings_table, own_position: int | None) -> OpponentRankRecord | None:
    """Only counts results in the SAME competition as the upcoming match,
    and only against opponents CURRENTLY ranked higher -- "currently," not
    at the time that result happened, since no source publishes
    point-in-time historical standings."""
    if not competition or not standings_table or own_position is None:
        return None
    wins = draws = losses = sample_size = 0
    for r in results:
        if r.competition != competition:
            continue
        row = next((s for s in standings_table if same_team(s.team_name, r.opponent)), None)
        if not row or row.position >= own_position:
            continue
        sample_size += 1
        if r.result == "W":
            wins += 1
        elif r.result == "D":
            draws += 1
        else:
            losses += 1
    return OpponentRankRecord(sample_size=sample_size, wins=wins, draws=draws, losses=losses) if sample_size else None


def _parse_xg_stat_value(raw: str | None) -> float | None:
    """A genuine 0.0 xG (a team with zero shots, or shots that all rounded
    to negligible value) is a real, different fact from "xG wasn't
    published for this match" -- kept as a small standalone helper
    specifically so that distinction is unit-testable without needing a
    live SCRAPERS fetch."""
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _h2h_meeting_venue(meeting_venue: str, details) -> str:
    """Neither team's own country matches the venue's -- a genuine
    neutral-site meeting (a cup final, etc.), not just "away" for
    whichever side happened to be listed as home. Same comparison
    form.py's own venue-classification enrichment uses for
    FormResult.neutral_venue, applied here since these are Sofascore-only
    fields (None from other sources, in which case this falls back to
    the plain home/away label meeting_venue already carries). Extracted
    from compute_recent_meetings to keep its own cognitive complexity
    down (python:S3776)."""
    if details.venue_country and details.home_team_country and details.away_team_country:
        if details.home_team_country != details.venue_country and details.away_team_country != details.venue_country:
            return "neutral"
    return meeting_venue


def _build_h2h_meeting(meeting, details) -> HeadToHeadMeeting:
    """Extracted from compute_recent_meetings to keep its own cognitive
    complexity down (python:S3776); behavior unchanged."""
    xg_stat = next((s for s in (details.match_stats or []) if "expected goals" in s.name.lower()), None)
    home_xg = _parse_xg_stat_value(xg_stat.home) if xg_stat else None
    away_xg = _parse_xg_stat_value(xg_stat.away) if xg_stat else None
    return HeadToHeadMeeting(
        date=meeting.date, competition=meeting.competition, scoreline=meeting.scoreline,
        venue=_h2h_meeting_venue(meeting.venue, details),
        home_formation=details.home_formation, away_formation=details.away_formation,
        home_xg=home_xg, away_xg=away_xg, home_lineup=details.home_lineup, away_lineup=details.away_lineup,
        home_team=details.home_team, away_team=details.away_team,
    )


async def compute_recent_meetings(
    raw_matches: list[MatchInfo], form_results, opponent_name: str, source: Source
) -> list[HeadToHeadMeeting] | None:
    """Sofascore's h2h endpoint only returns an aggregate tally, confirmed
    live -- no per-meeting match list exists there. This finds actual past
    meetings the honest way: scanning the already-fetched recent-form
    sample for results against this specific opponent, then
    cross-referencing the raw fixture list to fetch full details for just
    those matches. Capped at 3."""
    from .orchestrate import SCRAPERS

    meetings = [r for r in form_results if same_team(r.opponent, opponent_name)]
    if not meetings:
        return None

    out: list[HeadToHeadMeeting] = []
    for meeting in meetings[:3]:
        raw = next(
            (m for m in raw_matches if m.kickoff_utc == meeting.date and (same_team(m.home_team, opponent_name) or same_team(m.away_team, opponent_name))),
            None,
        )
        if raw is None:
            continue
        try:
            details = await SCRAPERS[source].details(raw)
            out.append(_build_h2h_meeting(meeting, details))
        except Exception as err:  # noqa: BLE001 - best-effort per past meeting
            record_step_failure("past meeting details", err)
    return out if out else None


def apply_usage_pattern(squad: list[SquadMember] | None, usage_by_player: dict[str, PlayerUsagePattern]) -> list[SquadMember] | None:
    if not squad or not usage_by_player:
        return squad
    from dataclasses import fields as _fields

    from .merge import find_by_name_containment

    result = []
    for m in squad:
        usage = usage_by_player.get(normalize_team_name(m.name)) or find_by_name_containment(m.name, usage_by_player)
        if usage:
            kwargs = {f.name: getattr(m, f.name) for f in _fields(m)}
            kwargs["recent_usage"] = usage
            result.append(SquadMember(**kwargs))
        else:
            result.append(m)
    return result


def compute_squad_strength(
    squad: list[SquadMember] | None,
    injuries: list[SquadMember] | None,
    suspended: list[str] | None,
    missing_players: list | None = None,
) -> SquadStrengthInfo | None:
    """missing_players: the match-level MissingPlayer list -- a player
    ruled out for a non-injury reason (e.g. "coach_decision") is on this
    list but not in `injuries`, and must still come off available_value
    (confirmed live: Richarlison was listed missing yet still counted)."""
    if not squad:
        return None

    def total(members: list[SquadMember]) -> float | None:
        values = [m.market_value for m in members if m.market_value is not None]
        return sum(values) if values else None

    unavailable = (
        {normalize_team_name(m.name) for m in (injuries or [])}
        | {normalize_team_name(n) for n in (suspended or [])}
        | {normalize_team_name(p.name) for p in (missing_players or [])}
    )
    available = [m for m in squad if normalize_team_name(m.name) not in unavailable]
    return SquadStrengthInfo(
        total_value=total(squad),
        attack_value=total([m for m in squad if is_attacker_role(m.role)]),
        midfield_value=total([m for m in squad if is_midfield_role(m.role)]),
        defense_value=total([m for m in squad if is_defender_role(m.role)]),
        goalkeeper_value=total([m for m in squad if is_goalkeeper_role(m.role)]),
        available_value=total(available),
    )


def compute_bench_info(bench: list[LineupPlayer] | None, lineup: list[LineupPlayer] | None, squad: list[SquadMember] | None):
    from .types import BenchInfo

    if not bench or not squad:
        return None
    value_by_name = {normalize_team_name(m.name): m.market_value for m in squad}

    def total(players: list[LineupPlayer]) -> float | None:
        values = [value_by_name.get(normalize_team_name(p.name)) for p in players]
        values = [v for v in values if v is not None]
        return sum(values) if values else None

    return BenchInfo(bench_size=len(bench), bench_total_market_value=total(bench), starting_total_market_value=(total(lineup) if lineup else None))


_INJURY_NOTE_KEYWORDS = ("injured", "injury", "out with", "ruled out", "sidelined", "hamstring", "knee", "ankle", "muscle", "knock")


def _injury_note_text(note_entry) -> str | None:
    """Extracted from _note_injury_reasons to keep its own cognitive
    complexity down (python:S3776); behavior unchanged.

    Returns the lowercased note text when note_entry is an
    injury-relevant AdditionalNote, else None."""
    from .merge import AdditionalNote

    if not isinstance(note_entry, AdditionalNote) or not note_entry.note:
        return None
    note_lower = note_entry.note.lower()
    if not any(kw in note_lower for kw in _INJURY_NOTE_KEYWORDS):
        return None
    return note_lower


def _note_injury_reasons(
    squad: list[SquadMember],
    additional_notes: list | None,
    already_known: set[str],
) -> dict[str, str]:
    """Extracted from compute_presence to keep its own cognitive
    complexity down (python:S3776); behavior unchanged.

    Cross-reference additional_notes for injury mentions not already in
    the profile's injuries list -- catches players whose injury was
    reported by a non-base source but didn't make it into the merged
    profile's injuries list (e.g. De Ligt/Heaton in notes but not in the
    injury merge)."""
    from .merge import normalize_team_name as _normalize

    result: dict[str, str] = {}
    for note_entry in (additional_notes or []):
        note_lower = _injury_note_text(note_entry)
        if note_lower is None:
            continue
        for m in squad:
            norm = _normalize(m.name)
            if m.name.lower() in note_lower and norm not in already_known:
                result[norm] = note_entry.note
    return result


def add_clean_sheets_recent_check(season_stats: TeamSeasonStats | None, results: list[FormResult] | None, source: str | None = None) -> None:
    """Counts clean sheets among the real competitive results in `results`
    (form.last20_overall) and RECONCILES season_stats.clean_sheets against
    that count: when the recent count exceeds the source's season aggregate
    (the lag case -- source still showing 0 after a 0-0 was played), raise
    clean_sheets to the recent count and preserve the original in
    clean_sheets_source_aggregate, so the report never shows two disagreeing
    numbers. `source` (the results' own form_source) is recorded alongside
    so a run-to-run swing can be attributed to a source change."""
    if not season_stats or not results:
        return
    check = sum(1 for r in results if not is_friendly_competition(r.competition) and result_goals(r)["against"] == 0)
    season_stats.clean_sheets_recent_check = check
    season_stats.clean_sheets_recent_check_source = source
    if check > season_stats.clean_sheets:
        season_stats.clean_sheets_source_aggregate = season_stats.clean_sheets
        season_stats.clean_sheets = check


def add_possession_venue_split_check(season_stats: TeamSeasonStats | None, venue_split, source: str | None = None) -> None:
    """Mutates season_stats in place with the n-weighted average of that
    team's detailed_venue_split possession buckets -- the same window form
    actually covers. When that figure diverges from the source's season-to-date
    average by more than 5pp, average_ball_possession is replaced with the
    form-window figure (more recent and match-relevant) and the original is
    kept in average_ball_possession_source_season, so consumers see one
    coherent number rather than two that look contradictory. No-op when
    either side is missing or no bucket has a possession figure."""
    if not season_stats or not venue_split:
        return
    total_n = 0
    weighted = 0.0
    for bucket in (venue_split.home, venue_split.away, venue_split.neutral):
        if bucket and bucket.possession_pct_avg is not None and bucket.sample_size:
            total_n += bucket.sample_size
            weighted += bucket.possession_pct_avg * bucket.sample_size
    if not total_n:
        return
    check = js_round_to(weighted / total_n, 1)
    season_stats.possession_venue_split_check = check
    season_stats.possession_venue_split_check_source = source
    season = season_stats.average_ball_possession
    if season is not None and abs(season - check) > 5.0:
        season_stats.average_ball_possession_source_season = season
        season_stats.average_ball_possession = check


def _same_competition(a: str | None, b: str | None) -> bool:
    """Exact match first, then base-name match so stage-suffixed labels
    ("UEFA Champions League, Knockout stage") still pair with the plain
    fixture competition ("UEFA Champions League") -- confirmed live: a
    strict == left standings form empty whenever the source tagged a
    recent result with a stage suffix the fixture didn't carry."""
    if not a or not b:
        return False
    if a == b:
        return True
    return a.split(",")[0].strip() == b.split(",")[0].strip()


def fill_standings_form(
    standings_table: list[StandingsTableRow] | None, position: int | None, results: list[FormResult] | None, competition: str | None
) -> None:
    """Sofascore's standings response has no `form` column, so it's null
    for every row. For the teams this report actually has results for, fill
    it from those real results: their last 5 matches in the fixture's own
    competition (stage suffixes ignored, see _same_competition), oldest
    first ("WWDLW"), matched to the row by table POSITION. Only the row(s)
    we have data for are filled -- the other teams' rows stay None rather
    than being guessed."""
    if not standings_table or position is None or not results or not competition:
        return
    row = next((r for r in standings_table if r.position == position), None)
    if row is None or row.form is not None:
        return
    league_results = [r for r in results if _same_competition(r.competition, competition)][:5]
    if league_results:
        row.form = "".join(r.result for r in reversed(league_results))


_PROJECTED_XI_SIZE = 11


def mark_projected_starters(presence: list[PresenceEntry] | None, squad: list[SquadMember] | None) -> list[PresenceEntry] | None:
    """Marks the likely XI on `presence` in place: one goalkeeper plus the
    ten outfield players with the most starts in the recent matches whose
    lineups we read (recent_usage), among players currently available.
    Returns the exact PresenceEntry objects marked (None when no
    projection was made) -- derive_lineup_and_formation takes this return
    value directly rather than re-scanning `presence` for
    `projected_starter == True` afterwards, so the two can never
    disagree, whatever squad/presence data produced them. Skipped when a
    real lineup is already marked, and when there's no usage history -- a
    projection needs evidence, not a guess. Position balance is NOT
    enforced beyond the keeper: it reflects who has actually been
    starting.

    Deduplicates by normalized name first (keeps the first occurrence) --
    a squad member appearing twice (a merge artifact) must count as one
    player toward the XI, not silently consume two of its eleven slots."""
    if not presence or not squad or any(p.starting for p in presence):
        return None
    from .merge import normalize_team_name as _normalize

    usage = {_normalize(m.name): m for m in squad if m.recent_usage and m.recent_usage.starts > 0}
    seen: set[str] = set()
    available = []
    for p in presence:
        norm = _normalize(p.name)
        if p.status == "P" and norm in usage and norm not in seen:
            seen.add(norm)
            available.append((p, usage[norm]))
    if not available:
        return None

    def strength(pair):
        u = pair[1].recent_usage
        return (u.starts, u.total_minutes)

    keepers = sorted((pair for pair in available if is_goalkeeper_role(pair[1].role)), key=strength, reverse=True)
    outfield = sorted((pair for pair in available if not is_goalkeeper_role(pair[1].role)), key=strength, reverse=True)
    chosen = keepers[:1] + outfield[: _PROJECTED_XI_SIZE - len(keepers[:1])]
    for entry, _ in chosen:
        entry.projected_starter = True
    return [entry for entry, _ in chosen]


def derive_lineup(selected: list[PresenceEntry] | None, squad: list[SquadMember] | None) -> list[LineupPlayer] | None:
    """Converts mark_projected_starters' own selection into LineupPlayer
    entries -- used only once no source has published a real lineup at
    all (Sofascore's own predicted lineup, when it exists, is used as-is
    and this is never reached; confirmed live Sofascore doesn't publish
    even a prediction until close to kickoff, real lineups only ~1 hour
    before).

    Deliberately does NOT derive a formation string ("4-3-3"): the
    selection is ranked purely by recent starts/minutes with no positional
    balancing, so the resulting D/M/F headcount is often not a real
    football shape (confirmed live: "6-2-2") -- home_formation/
    away_formation stay whatever a real source published, or null.

    age comes straight from the matching SquadMember (real data already
    on hand); shirt_number stays null -- no source publishes a team
    profile's per-player shirt number, only per-match lineups do, so
    there is nothing honest to put there for a derived entry. Every other
    field beyond name/position/substitute/age stays None -- exactly how
    a genuine unconfirmed prediction already looks pre-match (no minutes/
    stats exist yet either way)."""
    if not selected or not squad:
        return None
    by_name = {normalize_team_name(m.name): m for m in squad}
    return [
        LineupPlayer(
            name=p.name, position=(by_name[norm].role if norm in by_name else None), substitute=False,
            minutes_played=None, goals=None, assists=None, xg=None, xa=None, shots=None,
            shots_on_target=None, tackles=None, interceptions=None, fouls=None, rating=None, key_passes=None,
            age=(by_name[norm].age if norm in by_name else None),
        )
        for p in selected
        for norm in [normalize_team_name(p.name)]
    ]


def derive_projected_bench(lineup: list[LineupPlayer] | None, squad: list[SquadMember] | None) -> list[LineupPlayer] | None:
    """Projects a bench from squad members NOT in `lineup`, ranked by
    recent starts/minutes -- only when no source has published a real
    bench for this fixture (Sofascore is the only source that does, and
    only once lineups are close to confirmed). Mirrors derive_lineup's
    honesty rules: age from the squad, shirt_number left null (no source
    publishes a team profile's per-player shirt number), everything else
    None. Returns None when there's nothing meaningful to project (no
    lineup to subtract, or no squad / no unused players)."""
    if not lineup or not squad:
        return None
    if not all(getattr(p, "name", None) for p in lineup):
        return None
    starters = {normalize_team_name(p.name) for p in lineup}
    candidates = [
        m for m in squad
        if normalize_team_name(m.name) not in starters
        and m.recent_usage
        and (m.recent_usage.matches_in_squad or 0) > 0
    ]
    if not candidates:
        candidates = [m for m in squad if normalize_team_name(m.name) not in starters]
    if not candidates:
        return None
    candidates.sort(key=lambda m: (m.recent_usage.total_minutes if m.recent_usage else 0), reverse=True)
    return [
        LineupPlayer(
            name=m.name, position=m.role, substitute=True,
            minutes_played=None, goals=None, assists=None, xg=None, xa=None, shots=None,
            shots_on_target=None, tackles=None, interceptions=None, fouls=None, rating=None, key_passes=None,
            age=m.age,
        )
        for m in candidates[:9]
    ]


def _in_name_set(name: str, name_set: dict[str, bool] | None) -> bool | None:
    """Exact match first, then the same containment fallback used
    elsewhere for cross-source name spelling gaps (e.g. "Youri Tielemans"
    in the match-level lineup vs "Tielemans" in the squad profile, when
    the two came from different sources) -- confirmed live this
    previously made `starting` False for every real starter whenever the
    two sources spelled names differently, which let mark_projected_
    starters run anyway and compute its own, uncoordinated projection
    alongside a REAL published lineup. Extracted from compute_presence to
    keep its own cognitive complexity down (python:S3776). None when
    `name_set` itself is None (distinct from an empty dict, which means
    "checked, not present")."""
    if name_set is None:
        return None
    from .merge import find_by_name_containment
    from .merge import normalize_team_name as _normalize

    return _normalize(name) in name_set or find_by_name_containment(name, name_set) is not None


def compute_presence(
    squad: list[SquadMember] | None,
    lineup: list[LineupPlayer] | None,
    bench: list[LineupPlayer] | None,
    injuries: list[SquadMember] | None,
    suspended: list[str] | None,
    additional_notes: list | None = None,
    missing_players: list | None = None,
) -> list[PresenceEntry] | None:
    """Present = not on the injuries, suspensions, or match-level
    missing-players list; Absent = any of those. Doesn't distinguish
    "available but not selected" from "on the bench" -- none of our
    sources publish a separate bench list beyond Sofascore's own.

    additional_notes: list of AdditionalNote (from merge.py) -- cross-
    referenced for injury mentions not already in the injuries list.
    Player names found in note text mentioning 'injured'/'injury'/'out'
    are marked absent with the note as reason.

    missing_players: match-specific list (Sofascore's own
    lineups.missingPlayers, MissingPlayer objects) -- confirmed live a
    player ruled out for a non-injury reason (e.g. Richarlison,
    "coach_decision") showed status "P" here despite being listed
    unavailable in match.away_missing_players, since this function
    previously only looked at `injuries`. Checked last, after
    injury/note/suspension reasons, since those are more specific."""
    if not squad:
        return None
    from .merge import normalize_team_name as _normalize

    lineup_names = {_normalize(p.name): True for p in (lineup or [])}
    bench_names = {_normalize(p.name): True for p in bench} if bench is not None else None
    injury_by_name = {_normalize(p.name): p.injury for p in (injuries or [])}
    suspended_names = {_normalize(n) for n in (suspended or [])}
    note_injury_by_name = _note_injury_reasons(squad, additional_notes, set(injury_by_name))
    missing_reason_by_name = {_normalize(p.name): (p.description or "Not in squad") for p in (missing_players or [])}

    result = []
    for m in squad:
        norm = _normalize(m.name)
        reason = (
            injury_by_name.get(norm)
            or note_injury_by_name.get(norm)
            or ("Suspended" if norm in suspended_names else None)
            or missing_reason_by_name.get(norm)
        )
        result.append(
            PresenceEntry(
                name=m.name, status=("A" if reason else "P"), starting=bool(_in_name_set(m.name, lineup_names)),
                on_bench=_in_name_set(m.name, bench_names), reason=reason,
            )
        )
    return result


def _defender_count(f: str | None) -> int | None:
    if not f:
        return None
    return parse_leading_int(f.split("-")[0])


def _result_letter(team_score: int | None, opp_score: int | None) -> str | None:
    if team_score is None or opp_score is None:
        return None
    if team_score > opp_score:
        return "W"
    if team_score < opp_score:
        return "L"
    return "D"


def _build_rotation_info(
    team_name: str, last: MatchInfo, prev: MatchInfo, last_details, prev_details
) -> RotationInfo | None:
    """Extracted from compute_rotation_info to keep its own cognitive
    complexity down (python:S3776); behavior unchanged."""
    last_home = is_team_home(last, team_name)
    prev_home = is_team_home(prev, team_name)
    if last_home is None or prev_home is None:
        return None

    last_xi = (last_details.home_lineup if last_home else last_details.away_lineup) or []
    prev_xi = (prev_details.home_lineup if prev_home else prev_details.away_lineup) or []
    if not last_xi or not prev_xi:
        return None

    prev_names = {normalize_team_name(p.name) for p in prev_xi}
    changed_players = len([p for p in last_xi if normalize_team_name(p.name) not in prev_names])

    last_formation = (last_details.home_formation if last_home else last_details.away_formation)
    previous_formation = (prev_details.home_formation if prev_home else prev_details.away_formation)

    prev_team_score = prev.home_score if prev_home else prev.away_score
    prev_opp_score = prev.away_score if prev_home else prev.home_score
    preceding_result = _result_letter(prev_team_score, prev_opp_score)

    return RotationInfo(
        changed_players=changed_players, starting_xi_size=len(last_xi),
        last_match_date=last.kickoff_utc, previous_match_date=prev.kickoff_utc,
        last_formation=last_formation, previous_formation=previous_formation,
        formation_changed=(last_formation != previous_formation if last_formation and previous_formation else None),
        last_defender_count=_defender_count(last_formation), previous_defender_count=_defender_count(previous_formation),
        result_before_last=preceding_result,
        preceding_result=preceding_result,
    )


async def compute_rotation_info(team_name: str, source: Source, matches: list[MatchInfo]) -> RotationInfo | None:
    """Diffs the starting XI between the last TWO played matches (not the
    upcoming match's lineup, usually unpublished until close to kickoff)
    -- a general rotation-tendency signal."""
    from .orchestrate import SCRAPERS

    played = sorted(
        (m for m in matches if m.home_score is not None and m.away_score is not None and m.kickoff_utc),
        key=lambda m: m.kickoff_utc,
        reverse=True,
    )
    if len(played) < 2:
        return None
    last, prev = played[0], played[1]

    try:
        last_details = await SCRAPERS[source].details(last)
        prev_details = await SCRAPERS[source].details(prev)
        return _build_rotation_info(team_name, last, prev, last_details, prev_details)
    except Exception as err:  # noqa: BLE001 - mirrors TS's catch { return null }
        record_step_failure("rotation info", err)
        return None


def compute_resilience(results) -> ResilienceInfo | None:
    """Among results that WEREN'T wins, what share were draws -- "still
    earns a point when struggling" as an objective number."""
    non_wins = [r for r in results if r.result != "W"]
    if not non_wins:
        return None
    draws = len([r for r in non_wins if r.result == "D"])
    return ResilienceInfo(non_win_sample_size=len(non_wins), draw_share_pct=js_round(draws / len(non_wins) * 100))


def _points_for_match(m: MatchInfo, team_name: str) -> int | None:
    home = is_team_home(m, team_name)
    if home is None:
        return None
    team_score = m.home_score if home else m.away_score
    opp_score = m.away_score if home else m.home_score
    if team_score > opp_score:
        return 3
    if team_score == opp_score:
        return 1
    return 0


def _split_rest_performance(played: list[MatchInfo], team_name: str) -> tuple[int, int, int, int]:
    """Extracted from compute_rest_performance to keep its own cognitive
    complexity down (python:S3776); behavior unchanged."""
    short_pts = short_count = long_pts = long_count = 0
    for i in range(1, len(played)):
        pts = _points_for_match(played[i], team_name)
        if pts is None:
            continue
        rest_days = day_diff(played[i].kickoff_utc, played[i - 1].kickoff_utc)
        if rest_days <= 3:
            short_pts += pts
            short_count += 1
        else:
            long_pts += pts
            long_count += 1
    return short_pts, short_count, long_pts, long_count


def compute_rest_performance(team_name: str, matches: list[MatchInfo]) -> RestPerformanceInfo | None:
    """PPG split by rest before that match, across ALL played matches on
    record. <=3 days rest is "short"."""
    played = sorted(
        (m for m in matches if m.home_score is not None and m.away_score is not None and m.kickoff_utc),
        key=lambda m: m.kickoff_utc,
    )
    if len(played) < 2:
        return None

    short_pts, short_count, long_pts, long_count = _split_rest_performance(played, team_name)

    if not short_count and not long_count:
        return None
    return RestPerformanceInfo(
        short_rest_ppg=(js_round_to(short_pts / short_count, 2) if short_count else None), short_rest_sample_size=short_count,
        long_rest_ppg=(js_round_to(long_pts / long_count, 2) if long_count else None), long_rest_sample_size=long_count,
    )


def compute_experience_h2h(experience_comparison: ExperienceComparison | None, h2h: HeadToHeadSummary | None, own_is_home: bool | None) -> ExperienceH2HNote | None:
    """Correlation only, not causation -- reports whether the more
    experienced squad also happens to hold the head-to-head edge."""
    if not experience_comparison or not experience_comparison.more_experienced or not h2h or own_is_home is None:
        return None
    own_wins = h2h.home_wins if own_is_home else h2h.away_wins
    opp_wins = h2h.away_wins if own_is_home else h2h.home_wins
    if own_wins == opp_wins:
        h2h_leader = "even"
    elif own_wins > opp_wins:
        h2h_leader = "own"
    else:
        h2h_leader = "opponent"
    aligned = (
        None
        if experience_comparison.more_experienced == "even" or h2h_leader == "even"
        else experience_comparison.more_experienced == h2h_leader
    )
    return ExperienceH2HNote(more_experienced=experience_comparison.more_experienced, h2h_leader=h2h_leader, aligned=aligned)


def compute_fatigue_flag(recent_competitions: list[str], gaps_between_last_three: list[int]) -> FatigueFlag | None:
    """Flags multiple competitions AND a short average gap TOGETHER --
    either signal alone isn't flagged. <5 days average gap is the
    threshold."""
    if not gaps_between_last_three:
        return None
    avg_gap_days = js_round_to(sum(gaps_between_last_three) / len(gaps_between_last_three), 1)
    multi_competition = len(recent_competitions) > 1
    return FatigueFlag(multi_competition=multi_competition, competitions=recent_competitions, avg_gap_days=avg_gap_days, flagged=(multi_competition and avg_gap_days < 5))


def compute_home_advantage(form) -> HomeAdvantageInfo | None:
    """Gap between a team's own home and away win rates -- >=20pp
    "strong", 5-20pp "slight", -5..5pp "negligible", <=-5pp "reverse"."""
    if not form or form.home_win_rate_pct is None or form.away_win_rate_pct is None:
        return None
    gap_pct = form.home_win_rate_pct - form.away_win_rate_pct
    if gap_pct >= 20:
        strength = "strong"
    elif gap_pct >= 5:
        strength = "slight"
    elif gap_pct <= -5:
        strength = "reverse"
    else:
        strength = "negligible"
    return HomeAdvantageInfo(home_win_rate_pct=form.home_win_rate_pct, away_win_rate_pct=form.away_win_rate_pct, gap_pct=gap_pct, strength=strength)


def compute_streak_stability(streak: StreakInfo | None, rotation: RotationInfo | None) -> StreakStabilityInfo | None:
    """"Stable" requires a winning streak of >=2 AND <=2 XI changes
    between the last two matches -- both conditions."""
    if not streak:
        return None
    if streak.result == "W" and streak.count >= 2:
        stable = (rotation.changed_players <= 2) if rotation else None
    elif streak.result == "W":
        stable = None
    else:
        stable = False
    return StreakStabilityInfo(streak_result=streak.result, streak_count=streak.count, changed_players=(rotation.changed_players if rotation else None), stable=stable)


def compute_losing_streak_context(streak: StreakInfo | None, xg_estimate: SeasonXGEstimate | None) -> LosingStreakContextInfo | None:
    """"Potential turnaround" requires a losing streak of >=2 AND actual
    goals scored at least 1 below the season xG estimate.

    None only when there's no streak data at all (form missing / no
    results yet) -- a genuine completeness gap. When streak data exists
    but the team isn't on a 2+ losing streak (the common, healthy case),
    returns a checked-fine sentinel with streak_count=0 instead of None,
    so the field has a real value and compute_data_completeness can count
    it as populated. Previously both cases returned None and the field
    was excluded from completeness entirely, so a null in the JSON was
    unexplained (neither a value nor a listed gap)."""
    if not streak:
        return None
    if streak.result != "L" or streak.count < 2:
        return LosingStreakContextInfo(streak_count=0, xg_delta=None, potential_turnaround=None)
    xg_delta = js_round_to(xg_estimate.actual_goals_for - xg_estimate.xg_for, 2) if xg_estimate else None
    return LosingStreakContextInfo(streak_count=streak.count, xg_delta=xg_delta, potential_turnaround=(xg_delta <= -1 if xg_delta is not None else None))


def compute_card_risks(squad: list[SquadMember] | None, count: int = 5) -> list[PlayerCardRisk] | None:
    """Only returns players actually flagged (accumulation risk or a
    prior dismissal), sorted worst-first, not the full squad.
    None when there's no squad data to check at all -- distinct from a
    real, checked [] meaning "no player currently at risk" (confirmed
    live: e.g. a newly-promoted side with no red cards yet and everyone
    under the 4-yellow threshold). Both used to return the same []."""
    if not squad:
        return None
    risks = []
    for m in squad:
        if not m.season_stats:
            continue
        r = PlayerCardRisk(
            name=m.name, yellow_cards=m.season_stats.yellow_cards, red_cards=m.season_stats.red_cards,
            appearances=m.season_stats.appearances, accumulation_risk=(m.season_stats.yellow_cards >= 4),
            prior_dismissal=(m.season_stats.red_cards >= 1),
        )
        if r.accumulation_risk or r.prior_dismissal:
            risks.append(r)
    risks.sort(key=lambda r: r.yellow_cards + r.red_cards * 10, reverse=True)
    return risks[:count]


def compute_referee_card_risk_note(
    referee_name: str | None, referee_stats: RefereeStats | None, home_card_risks: list[PlayerCardRisk] | None, away_card_risks: list[PlayerCardRisk] | None
) -> RefereeCardRiskNote | None:
    """Pure synthesis of two things already computed separately -- no new
    requests. Returns a note whenever referee + stats exist, even with an
    empty flagged_players list ("checked, nobody currently flagged"), so
    the field is present for every fixture that has a known referee rather
    than disappearing whenever no player crosses the card-risk threshold."""
    from .types import FlaggedPlayer

    if not referee_name or not referee_stats:
        return None
    flagged_players = [
        *[FlaggedPlayer(name=r.name, side="home", prior_dismissal=r.prior_dismissal) for r in (home_card_risks or [])],
        *[FlaggedPlayer(name=r.name, side="away", prior_dismissal=r.prior_dismissal) for r in (away_card_risks or [])],
    ]
    yellow_cards_per_game = float(referee_stats.yellow_cards_per_game)
    return RefereeCardRiskNote(referee_name=referee_name, yellow_cards_per_game=yellow_cards_per_game, elevated_card_referee=(yellow_cards_per_game > 2.5), flagged_players=flagged_players)


def aerial_win_pct(aerial: SeasonAerialEstimate | None) -> float | None:
    if not aerial:
        return None
    total = aerial.aerial_duels_won_for + aerial.aerial_duels_won_against
    return js_round_to(aerial.aerial_duels_won_for / total * 100, 1) if total else None


def compute_set_piece_threat_flag(corners: SeasonCornersEstimate | None, opponent_aerial: SeasonAerialEstimate | None) -> SetPieceThreatFlag | None:
    if not corners:
        return None
    corners_per_game = js_round_to(corners.corners_for / corners.sample_size, 2)
    opponent_pct = aerial_win_pct(opponent_aerial)
    return SetPieceThreatFlag(corners_per_game=corners_per_game, opponent_aerial_win_pct=opponent_pct, elevated=(corners_per_game >= 5 and opponent_pct is not None and opponent_pct < 50))


def compute_direct_play_exposure_flag(passing_style: SeasonPassingStyleEstimate | None, opponent_aerial: SeasonAerialEstimate | None) -> DirectPlayExposureFlag | None:
    if not passing_style or passing_style.long_ball_share_pct is None:
        return None
    opponent_pct = aerial_win_pct(opponent_aerial)
    return DirectPlayExposureFlag(long_ball_share_pct=passing_style.long_ball_share_pct, opponent_aerial_win_pct=opponent_pct, elevated=(passing_style.long_ball_share_pct >= 15 and opponent_pct is not None and opponent_pct < 50))


def compute_duel_vulnerabilities(squad: list[SquadMember] | None, count: int = 5) -> list[DuelVulnerability] | None:
    """Squawka-only. Only returns defenders actually below the 50%
    threshold, not the full back line.
    None when there's no squad data to check at all -- distinct from a
    real, checked [] meaning "no defender currently below threshold".
    Both used to return the same []."""
    if not squad:
        return None
    candidates = [
        m for m in squad
        if is_defender_role(m.role) and m.defensive_stats and m.defensive_stats.ground_duel_success_pct is not None and m.defensive_stats.ground_duel_success_pct < 50
    ]
    candidates.sort(key=lambda m: m.defensive_stats.ground_duel_success_pct)
    return [DuelVulnerability(name=m.name, ground_duel_success_pct=m.defensive_stats.ground_duel_success_pct) for m in candidates[:count]]


def _median(values: list[float]) -> float:
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _is_mainly_central_back(member: SquadMember) -> bool:
    """True when the recent lineups show this defender starting more often
    in a central back-line slot than a wide one. No usage data (or none in
    a readable back line) leaves the player in, since nothing says
    otherwise."""
    usage = member.recent_usage
    return bool(usage and usage.central_back_starts > usage.wide_back_starts)


def compute_fullback_exposure(squad: list[SquadMember] | None, count: int = 3) -> list[FullbackExposureInfo] | None:
    """Above-own-team-median chances created AND below-55% ground duel
    success -- uses each team's own defenders as the baseline.
    None when there's no squad data (or too few defenders with the needed
    Squawka stats) to compute a baseline at all -- distinct from a real,
    checked [] meaning "no defender exposed". Both used to return the
    same [].

    Squad positions are only G/D/M/F, so fullbacks are told apart from
    centre-backs using where each defender actually lined up in recent
    matches (PlayerUsagePattern.wide_back_starts/central_back_starts, read
    from lineup order + formation): a defender who mostly starts in a
    central slot is excluded -- confirmed live a centre-back (Harry
    Maguire) used to appear here. Defenders with no readable lineup
    history stay in, as before. Named to match the Android app's existing
    "Fullback" section (ProfileTab.kt), not renamed -- that's a cross-repo
    JSON contract."""
    if not squad:
        return None
    defenders = [
        m for m in squad
        if is_defender_role(m.role) and not _is_mainly_central_back(m)
        and m.defensive_stats and m.defensive_stats.chances_created is not None and m.defensive_stats.ground_duel_success_pct is not None
    ]
    if len(defenders) < 2:
        return None
    median_chances = _median([d.defensive_stats.chances_created for d in defenders])
    candidates = [d for d in defenders if d.defensive_stats.chances_created > median_chances and d.defensive_stats.ground_duel_success_pct < 55]
    candidates.sort(key=lambda d: d.defensive_stats.chances_created, reverse=True)
    return [FullbackExposureInfo(name=d.name, chances_created=d.defensive_stats.chances_created, ground_duel_success_pct=d.defensive_stats.ground_duel_success_pct) for d in candidates[:count]]


def _simulated_points(r, own_current_position: int, opponent_current_position: int, new_own_points: int, new_opponent_points: int) -> int:
    if r.position == own_current_position:
        return new_own_points
    if r.position == opponent_current_position:
        return new_opponent_points
    return r.points


def _simulate_new_position(standings_table, own_current_position: int, opponent_current_position: int, new_own_points: int, new_opponent_points: int) -> int | None:
    """Re-ranks by matching standings-table rows by POSITION, not fuzzy
    team-name matching -- avoids an entire class of bug the name-matching
    approach elsewhere in this file is exposed to."""
    if not standings_table:
        return None
    from .types import StandingsTableRow

    simulated = [
        StandingsTableRow(
            team_name=r.team_name, position=r.position,
            points=_simulated_points(r, own_current_position, opponent_current_position, new_own_points, new_opponent_points),
        )
        for r in standings_table
    ]
    simulated.sort(key=lambda r: (-r.points, r.position))
    idx = next((i for i, r in enumerate(simulated) if r.position == own_current_position), -1)
    return idx + 1 if idx != -1 else None


def compute_standings_impact(standing: TeamStanding | None, opponent_standing: TeamStanding | None, standings_table) -> StandingsImpactInfo | None:
    if not standing or not opponent_standing or not standings_table:
        return None
    scenarios = []
    own_pts_by_outcome = {"win": 3, "draw": 1, "loss": 0}
    opp_pts_by_outcome = {"win": 0, "draw": 1, "loss": 3}
    for outcome in ("win", "draw", "loss"):
        own_pts = own_pts_by_outcome[outcome]
        opp_pts = opp_pts_by_outcome[outcome]
        new_points = standing.points + own_pts
        new_opponent_points = opponent_standing.points + opp_pts
        scenarios.append(
            StandingsScenario(
                outcome=outcome, new_points=new_points,
                new_position=_simulate_new_position(standings_table, standing.position, opponent_standing.position, new_points, new_opponent_points),
            )
        )
    return StandingsImpactInfo(current_position=standing.position, current_points=standing.points, scenarios=scenarios)


def is_recent_appointment(appointed_date: str | None) -> bool | None:
    if not appointed_date:
        return None
    dt = datetime.fromisoformat(appointed_date)
    return (datetime.now(tz=UTC) - dt).total_seconds() <= 90 * 86400


class OpponentContext:
    def __init__(self, rest_days, average_age, merged_profile, matches, error, matches_source=None):
        self.rest_days = rest_days
        self.average_age = average_age
        self.merged_profile = merged_profile
        self.matches = matches
        self.error = error
        # Which source actually supplied `matches` -- previously always
        # implicitly base_source (single point of failure: opponent form
        # went empty whenever base_source alone couldn't find the
        # opponent). Now the first source in SOURCE_ORDER that returns any
        # matches, same fallback pattern the searched team's own form
        # already uses. None only if every source failed.
        self.matches_source = matches_source


def _compute_rest_comparison(own_rest_days: int | None, opponent_rest_days: int | None) -> RestComparison | None:
    """Extracted from compute_insights to keep its own cognitive
    complexity down (python:S3776); behavior unchanged."""
    if own_rest_days is None and opponent_rest_days is None:
        return None
    more_rested = None
    if own_rest_days is not None and opponent_rest_days is not None:
        if own_rest_days == opponent_rest_days:
            more_rested = "even"
        elif own_rest_days > opponent_rest_days:
            more_rested = "own"
        else:
            more_rested = "opponent"
    return RestComparison(own_rest_days=own_rest_days, opponent_rest_days=opponent_rest_days, more_rested=more_rested)


def _compute_experience_comparison(own_average_age: float | None, opponent_average_age: float | None) -> ExperienceComparison | None:
    """Extracted from compute_insights to keep its own cognitive
    complexity down (python:S3776); behavior unchanged."""
    if own_average_age is None and opponent_average_age is None:
        return None
    more_experienced = None
    if own_average_age is not None and opponent_average_age is not None:
        diff = own_average_age - opponent_average_age
        if abs(diff) < 1.5:
            more_experienced = "even"
        elif diff > 0:
            more_experienced = "own"
        else:
            more_experienced = "opponent"
    return ExperienceComparison(own_average_age=own_average_age, opponent_average_age=opponent_average_age, more_experienced=more_experienced)


def compute_insights(merged: MatchDetails, own_average_age: float | None, own_rest_days: int | None, opponent: OpponentContext) -> MatchInsights:
    rest_comparison = _compute_rest_comparison(own_rest_days, opponent.rest_days)
    experience_comparison = _compute_experience_comparison(own_average_age, opponent.average_age)

    return MatchInsights(
        match_type=classify_match_type(merged.competition),
        rest_comparison=rest_comparison,
        experience_comparison=experience_comparison,
        home_standings_zone=classify_standings_zone(merged.home_team_standing, merged.competition, merged.standings_table),
        away_standings_zone=classify_standings_zone(merged.away_team_standing, merged.competition, merged.standings_table),
        home_card_discipline=classify_card_discipline(merged.home_team_season_stats, merged.home_team_standing),
        away_card_discipline=classify_card_discipline(merged.away_team_season_stats, merged.away_team_standing),
        home_card_discipline_venue_split=None,
        away_card_discipline_venue_split=None,
        home_xg_estimate=None, away_xg_estimate=None, home_shots_estimate=None, away_shots_estimate=None,
        home_aerial_estimate=None, away_aerial_estimate=None, home_big_chances_estimate=None, away_big_chances_estimate=None,
        home_passing_style=None, away_passing_style=None, home_fouls_estimate=None, away_fouls_estimate=None,
        home_goalkeeping_estimate=None, away_goalkeeping_estimate=None,
        home_set_piece_threat=None, away_set_piece_threat=None, home_direct_play_exposure=None, away_direct_play_exposure=None,
        travel_info=compute_travel_info(merged),
        home_opponent_rank_record=None, away_opponent_rank_record=None,
        home_presence=None, away_presence=None, home_rotation=None, away_rotation=None,
        home_resilience=None, away_resilience=None, home_rest_performance=None, away_rest_performance=None,
        experience_h2h=None, home_fatigue_flag=None, away_fatigue_flag=None,
        home_advantage=None, away_advantage=None, home_streak_stability=None, away_streak_stability=None,
        home_losing_streak_context=None, away_losing_streak_context=None,
        home_card_risks=None, away_card_risks=None, referee_card_risk_note=None,
        home_duel_vulnerabilities=None, away_duel_vulnerabilities=None,
        home_possession_matchup=None, away_possession_matchup=None,
        home_corners_estimate=None, away_corners_estimate=None,
        home_defensive_errors_estimate=None, away_defensive_errors_estimate=None,
        home_fullback_exposure=None, away_fullback_exposure=None,
        home_standings_impact=compute_standings_impact(merged.home_team_standing, merged.away_team_standing, merged.standings_table),
        away_standings_impact=compute_standings_impact(merged.away_team_standing, merged.home_team_standing, merged.standings_table),
        home_advanced_stats=None, away_advanced_stats=None,
        home_bench_info=None, away_bench_info=None,
        home_elo_rating=None, away_elo_rating=None,
        home_squad_strength=None, away_squad_strength=None,
        home_club_strength=None, away_club_strength=None,
        prediction=None,
        opponent_context_error=opponent.error,
    )


class SeasonMatchStatsEstimate:
    def __init__(self, xg, shots, card_split, aerial, big_chances, passing_style, fouls, goalkeeping):
        self.xg = xg
        self.shots = shots
        self.card_split = card_split
        self.aerial = aerial
        self.big_chances = big_chances
        self.passing_style = passing_style
        self.fouls = fouls
        self.goalkeeping = goalkeeping


def _find_stat(stats, name):
    return next((s for s in (stats or []) if s.name == name), None)


class _SeasonStatsAccumulator:
    """Internal accumulator for compute_season_match_stats_estimate's
    per-match totals -- bundled into one mutable object purely so the
    per-match processing loop can be extracted into its own function
    (python:S3776) without threading ~30 separate scalars through it.
    Behavior unchanged."""

    def __init__(self) -> None:
        self.xg_for = self.xg_against = self.goals_for = self.goals_against = 0.0
        self.xg_sample_size = 0
        self.shots_for = self.shots_against = self.sot_for = self.sot_against = 0
        self.shots_sample_size = 0
        self.saves_for = self.shots_on_target_faced = self.keeper_goals_conceded = self.keeper_sample_size = 0
        self.at_home_yellow = self.at_home_red = self.at_home_sample_size = 0
        self.away_yellow = self.away_red = self.away_sample_size = 0
        self.aerial_for = self.aerial_against = self.aerial_sample_size = 0
        self.chances_created_for = self.chances_created_against = 0
        self.chances_missed_for = self.chances_missed_against = self.big_chances_sample_size = 0
        self.total_passes_for = self.accurate_passes_for = self.accurate_long_balls_for = self.passing_sample_size = 0
        self.fouls_for = self.fouls_against = self.fouls_sample_size = 0


def _accumulate_xg(acc: _SeasonStatsAccumulator, stats, m: MatchInfo, home: bool) -> None:
    xg_stat = _find_stat(stats, "Expected goals (xG)")
    if not xg_stat:
        return
    acc.xg_for += float(xg_stat.home if home else xg_stat.away)
    acc.xg_against += float(xg_stat.away if home else xg_stat.home)
    acc.goals_for += m.home_score if home else m.away_score
    acc.goals_against += m.away_score if home else m.home_score
    acc.xg_sample_size += 1


def _accumulate_shots_and_keeper(acc: _SeasonStatsAccumulator, stats, m: MatchInfo, home: bool) -> None:
    shots_stat = _find_stat(stats, "Total shots")
    sot_stat = _find_stat(stats, "Shots on target")
    if not (shots_stat and sot_stat):
        return
    sot_against_this_match = int(float(sot_stat.away if home else sot_stat.home))
    acc.shots_for += int(float(shots_stat.home if home else shots_stat.away))
    acc.shots_against += int(float(shots_stat.away if home else shots_stat.home))
    acc.sot_for += int(float(sot_stat.home if home else sot_stat.away))
    acc.sot_against += sot_against_this_match
    acc.shots_sample_size += 1

    keeper_stat = _find_stat(stats, "Keeper saves")
    if keeper_stat:
        acc.saves_for += int(float(keeper_stat.home if home else keeper_stat.away))
        acc.shots_on_target_faced += sot_against_this_match
        acc.keeper_goals_conceded += m.away_score if home else m.home_score
        acc.keeper_sample_size += 1


def _accumulate_cards(acc: _SeasonStatsAccumulator, stats, home: bool) -> None:
    yellow_stat = _find_stat(stats, "Yellow cards")
    if not yellow_stat:
        return
    red_stat = _find_stat(stats, "Red cards")
    yellow = int(float(yellow_stat.home if home else yellow_stat.away))
    if red_stat:
        red = int(float(red_stat.home if home else red_stat.away))
    else:
        red = 0
    if home:
        acc.at_home_yellow += yellow
        acc.at_home_red += red
        acc.at_home_sample_size += 1
    else:
        acc.away_yellow += yellow
        acc.away_red += red
        acc.away_sample_size += 1


def _accumulate_aerial(acc: _SeasonStatsAccumulator, stats, home: bool) -> None:
    aerial_stat = _find_stat(stats, "Aerial duels won")
    if not aerial_stat:
        return
    for_val = parse_leading_int(aerial_stat.home if home else aerial_stat.away)
    against_val = parse_leading_int(aerial_stat.away if home else aerial_stat.home)
    if for_val is not None and against_val is not None:
        acc.aerial_for += for_val
        acc.aerial_against += against_val
        acc.aerial_sample_size += 1


def _accumulate_big_chances(acc: _SeasonStatsAccumulator, stats, home: bool) -> None:
    big_chances_stat = _find_stat(stats, "Big chances")
    big_chances_missed_stat = _find_stat(stats, "Big chances missed")
    if not (big_chances_stat and big_chances_missed_stat):
        return
    acc.chances_created_for += int(float(big_chances_stat.home if home else big_chances_stat.away))
    acc.chances_created_against += int(float(big_chances_stat.away if home else big_chances_stat.home))
    acc.chances_missed_for += int(float(big_chances_missed_stat.home if home else big_chances_missed_stat.away))
    acc.chances_missed_against += int(float(big_chances_missed_stat.away if home else big_chances_missed_stat.home))
    acc.big_chances_sample_size += 1


def _accumulate_passing(acc: _SeasonStatsAccumulator, stats, home: bool) -> None:
    # "Passes" appears TWICE in Fotmob's stats array -- the first
    # occurrence with empty home/away strings (a placeholder/header row)
    # and the second with the actual total -- explicitly skipping empty
    # values here (see the TS doc comment).
    passes_stat = next((s for s in (stats or []) if s.name == "Passes" and s.home != "" and s.away != ""), None)
    accurate_passes_stat = _find_stat(stats, "Accurate passes")
    long_balls_stat = _find_stat(stats, "Accurate long balls")
    if not (passes_stat and accurate_passes_stat and long_balls_stat):
        return
    total_own = parse_leading_int(passes_stat.home if home else passes_stat.away)
    accurate_own = parse_leading_int(accurate_passes_stat.home if home else accurate_passes_stat.away)
    long_balls_own = parse_leading_int(long_balls_stat.home if home else long_balls_stat.away)
    if total_own is not None and accurate_own is not None and long_balls_own is not None:
        acc.total_passes_for += total_own
        acc.accurate_passes_for += accurate_own
        acc.accurate_long_balls_for += long_balls_own
        acc.passing_sample_size += 1


def _accumulate_fouls(acc: _SeasonStatsAccumulator, stats, home: bool) -> None:
    fouls_stat = _find_stat(stats, "Fouls committed")
    if fouls_stat:
        acc.fouls_for += int(float(fouls_stat.home if home else fouls_stat.away))
        acc.fouls_against += int(float(fouls_stat.away if home else fouls_stat.home))
        acc.fouls_sample_size += 1


async def _accumulate_one_match_stats(acc: _SeasonStatsAccumulator, m: MatchInfo, team_name: str, get_fotmob_match_details) -> None:
    """One iteration of compute_season_match_stats_estimate's per-match
    loop -- mutates `acc` in place. Extracted purely to keep the caller's
    own cognitive complexity down (python:S3776); behavior unchanged,
    including silently skipping a match whose detail fetch fails."""
    home = is_team_home(m, team_name)
    if home is None:
        return
    try:
        details = await get_fotmob_match_details(m)
        stats = details.match_stats
        _accumulate_xg(acc, stats, m, home)
        _accumulate_shots_and_keeper(acc, stats, m, home)
        _accumulate_cards(acc, stats, home)
        _accumulate_aerial(acc, stats, home)
        _accumulate_big_chances(acc, stats, home)
        _accumulate_passing(acc, stats, home)
        _accumulate_fouls(acc, stats, home)
    except Exception as err:  # noqa: BLE001 - one match's detail fetch failing shouldn't drop the whole estimate
        record_step_failure("season match stats (Fotmob)", err)


def _build_xg_estimate(acc: _SeasonStatsAccumulator) -> SeasonXGEstimate | None:
    if not acc.xg_sample_size:
        return None
    return SeasonXGEstimate(
        sample_size=acc.xg_sample_size, xg_for=js_round_to(acc.xg_for, 2), xg_against=js_round_to(acc.xg_against, 2),
        actual_goals_for=int(acc.goals_for), actual_goals_against=int(acc.goals_against), source="fotmob",
    )


def _build_shots_estimate(acc: _SeasonStatsAccumulator) -> SeasonShotsEstimate | None:
    if not acc.shots_sample_size:
        return None
    return SeasonShotsEstimate(
        sample_size=acc.shots_sample_size, shots_for=acc.shots_for, shots_against=acc.shots_against,
        shots_on_target_for=acc.sot_for, shots_on_target_against=acc.sot_against, source="fotmob",
    )


def _build_card_split(acc: _SeasonStatsAccumulator) -> CardDisciplineVenueSplit | None:
    if not (acc.at_home_sample_size or acc.away_sample_size):
        return None
    return CardDisciplineVenueSplit(
        at_home_sample_size=acc.at_home_sample_size,
        at_home_yellow_per_game=(js_round_to(acc.at_home_yellow / acc.at_home_sample_size, 2) if acc.at_home_sample_size else None),
        at_home_red_per_game=(js_round_to(acc.at_home_red / acc.at_home_sample_size, 2) if acc.at_home_sample_size else None),
        away_sample_size=acc.away_sample_size,
        away_yellow_per_game=(js_round_to(acc.away_yellow / acc.away_sample_size, 2) if acc.away_sample_size else None),
        away_red_per_game=(js_round_to(acc.away_red / acc.away_sample_size, 2) if acc.away_sample_size else None),
        source="fotmob",
    )


def _build_passing_style(acc: _SeasonStatsAccumulator) -> SeasonPassingStyleEstimate | None:
    if not acc.passing_sample_size:
        return None
    return SeasonPassingStyleEstimate(
        sample_size=acc.passing_sample_size, total_passes_for=acc.total_passes_for, accurate_passes_for=acc.accurate_passes_for,
        pass_accuracy_pct=(js_round_to(acc.accurate_passes_for / acc.total_passes_for * 100, 1) if acc.total_passes_for else None),
        accurate_long_balls_for=acc.accurate_long_balls_for,
        long_ball_share_pct=(js_round_to(acc.accurate_long_balls_for / acc.accurate_passes_for * 100, 1) if acc.accurate_passes_for else None),
        source="fotmob",
    )


def _build_goalkeeping_estimate(acc: _SeasonStatsAccumulator) -> SeasonGoalkeepingEstimate | None:
    if not acc.keeper_sample_size:
        return None
    # Derive shots_on_target_faced from saves_for + goals_conceded so the
    # three figures always reconcile arithmetically (the identity every
    # reader adds up by hand: "25 saves on 41 shots faced, 16 conceded").
    # The provider's independent "Shots on target" sum can disagree with
    # saves + goals (own goals, provider quirks) -- confirmed live off by
    # 1 in both directions on the two sides of one fixture -- which made
    # the rendered line look wrong even though it was flagged. save_pct
    # uses the derived denominator too (standard saves / (saves + goals)).
    derived_sot = acc.saves_for + int(acc.keeper_goals_conceded)
    return SeasonGoalkeepingEstimate(
        sample_size=acc.keeper_sample_size, saves_for=acc.saves_for, shots_on_target_faced=derived_sot,
        save_pct=(js_round_to(acc.saves_for / derived_sot * 100, 1) if derived_sot else None),
        goals_conceded=int(acc.keeper_goals_conceded), source="fotmob",
    )


async def compute_season_match_stats_estimate(team_name: str, fotmob_matches: list[MatchInfo]) -> SeasonMatchStatsEstimate:
    """Fotmob's per-match stats include xG/shots/cards/aerial/big-chances/
    passing/fouls, but no season-aggregate endpoint exists for any of
    them on any of the 5 sources. This builds real aggregates from the
    last 10 *finished* Fotmob matches -- one fetch loop derives all
    eight, still just reusing get_fotmob_match_details."""
    from .sites.fotmob import get_fotmob_match_details

    finished = sorted(
        (m for m in fotmob_matches if m.status == "finished" and m.kickoff_utc), key=lambda m: m.kickoff_utc, reverse=True
    )[:10]
    if not finished:
        return SeasonMatchStatsEstimate(None, None, None, None, None, None, None, None)

    acc = _SeasonStatsAccumulator()
    for m in finished:
        await _accumulate_one_match_stats(acc, m, team_name, get_fotmob_match_details)

    aerial = SeasonAerialEstimate(sample_size=acc.aerial_sample_size, aerial_duels_won_for=acc.aerial_for, aerial_duels_won_against=acc.aerial_against, source="fotmob") if acc.aerial_sample_size else None
    big_chances = (
        SeasonBigChancesEstimate(sample_size=acc.big_chances_sample_size, big_chances_created_for=acc.chances_created_for, big_chances_created_against=acc.chances_created_against, big_chances_missed_for=acc.chances_missed_for, big_chances_missed_against=acc.chances_missed_against, source="fotmob")
        if acc.big_chances_sample_size
        else None
    )
    fouls = SeasonFoulsEstimate(sample_size=acc.fouls_sample_size, fouls_committed_for=acc.fouls_for, fouls_committed_against=acc.fouls_against, source="fotmob") if acc.fouls_sample_size else None

    return SeasonMatchStatsEstimate(
        _build_xg_estimate(acc), _build_shots_estimate(acc), _build_card_split(acc), aerial,
        big_chances, _build_passing_style(acc), fouls, _build_goalkeeping_estimate(acc),
    )


class PossessionAndCornersEstimate:
    def __init__(self, possession, corners, defensive_errors):
        self.possession = possession
        self.corners = corners
        self.defensive_errors = defensive_errors


class _PossessionAccumulator:
    """Internal accumulator for compute_possession_matchup's per-match
    totals -- bundled purely so the per-match processing can be extracted
    into its own function (python:S3776) without threading 9 separate
    scalars through it. Behavior unchanged."""

    def __init__(self) -> None:
        self.high_pts = self.high_count = self.other_pts = self.other_count = 0
        self.corners_for = self.corners_against = self.corners_sample_size = 0
        self.def_errors_for = self.def_errors_against = self.def_errors_sample_size = 0


def _accumulate_possession_stat(acc: _PossessionAccumulator, details, m: MatchInfo, home: bool) -> None:
    import re

    possession_stat = next((s for s in (details.match_stats or []) if re.search("possession", s.name, re.IGNORECASE)), None)
    if not possession_stat:
        return
    try:
        opponent_possession = float(possession_stat.away if home else possession_stat.home)
    except ValueError:
        opponent_possession = float("nan")
    if opponent_possession != opponent_possession:  # noqa: PLR0124  # NOSONAR(S1764) -- portable NaN check, not a typo
        return
    team_score = m.home_score if home else m.away_score
    opp_score = m.away_score if home else m.home_score
    if team_score > opp_score:
        pts = 3
    elif team_score == opp_score:
        pts = 1
    else:
        pts = 0
    if opponent_possession >= 55:
        acc.high_pts += pts
        acc.high_count += 1
    else:
        acc.other_pts += pts
        acc.other_count += 1


def _accumulate_corners_and_errors(acc: _PossessionAccumulator, details, home: bool) -> None:
    corners_stat = next((s for s in (details.match_stats or []) if s.name == "Corner total"), None)
    if corners_stat:
        acc.corners_for += int(float(corners_stat.home if home else corners_stat.away))
        acc.corners_against += int(float(corners_stat.away if home else corners_stat.home))
        acc.corners_sample_size += 1

    def_errors_stat = next((s for s in (details.match_stats or []) if s.name == "Defensive error"), None)
    if def_errors_stat:
        acc.def_errors_for += int(float(def_errors_stat.home if home else def_errors_stat.away))
        acc.def_errors_against += int(float(def_errors_stat.away if home else def_errors_stat.home))
        acc.def_errors_sample_size += 1


async def _accumulate_one_possession_match(
    acc: _PossessionAccumulator, m: MatchInfo, team_name: str, client, get_goal_match_details
) -> None:
    """One iteration of compute_possession_matchup's per-match loop --
    mutates `acc` in place. Extracted purely to keep the caller's own
    cognitive complexity down (python:S3776); behavior unchanged,
    including silently skipping a match whose detail fetch fails."""
    home = is_team_home(m, team_name)
    if home is None:
        return
    try:
        details = await get_goal_match_details(m, client)
        _accumulate_possession_stat(acc, details, m, home)
        _accumulate_corners_and_errors(acc, details, home)
    except Exception as err:  # noqa: BLE001 - one match's detail fetch failing shouldn't drop the whole estimate
        record_step_failure("possession and corners (Goal.com)", err)


async def compute_possession_matchup(team_name: str, goal_matches: list[MatchInfo]) -> PossessionAndCornersEstimate:
    """>=55% opponent possession is the "high" threshold. "Corner total"
    and "Defensive error" come free from the same Goal.com match-detail
    fetch already made for the possession stat."""
    from .http import new_client
    from .sites.goal import get_goal_match_details

    finished = sorted(
        (m for m in goal_matches if m.status == "finished" and m.kickoff_utc), key=lambda m: m.kickoff_utc, reverse=True
    )[:10]
    if not finished:
        return PossessionAndCornersEstimate(None, None, None)

    acc = _PossessionAccumulator()

    # One shared client for the whole loop (up to 10 sequential requests,
    # all to goal.com) instead of get_goal_match_details' default of a
    # fresh client per call -- confirmed live this is where most of this
    # function's wall-clock time was going on Android specifically (a
    # fresh client per call means a fresh DNS+TCP+TLS handshake per call;
    # see http.fetch_text's docstring for the measured ~6min-vs-~12s gap
    # this caused). Doesn't change what's requested or how often -- same
    # 10 URLs, same sequential order -- only reuses the underlying
    # connection, which is also lighter on goal.com's own server, not
    # heavier.
    async with new_client() as client:
        for m in finished:
            await _accumulate_one_possession_match(acc, m, team_name, client, get_goal_match_details)

    high_pts, high_count, other_pts, other_count = acc.high_pts, acc.high_count, acc.other_pts, acc.other_count
    corners_for, corners_against, corners_sample_size = acc.corners_for, acc.corners_against, acc.corners_sample_size
    def_errors_for, def_errors_against, def_errors_sample_size = acc.def_errors_for, acc.def_errors_against, acc.def_errors_sample_size

    high_ppg = js_round_to(high_pts / high_count, 2) if high_count else None
    other_ppg = js_round_to(other_pts / other_count, 2) if other_count else None
    possession = (
        PossessionMatchupInfo(
            high_opponent_possession_ppg=high_ppg, high_opponent_possession_sample_size=high_count,
            other_ppg=other_ppg, other_sample_size=other_count,
        )
        if (high_count or other_count)
        else None
    )
    corners = SeasonCornersEstimate(sample_size=corners_sample_size, corners_for=corners_for, corners_against=corners_against, source="goal") if corners_sample_size else None
    defensive_errors = (
        SeasonDefensiveErrorsEstimate(sample_size=def_errors_sample_size, defensive_errors_for=def_errors_for, defensive_errors_against=def_errors_against, source="goal") if def_errors_sample_size else None
    )
    return PossessionAndCornersEstimate(possession, corners, defensive_errors)


_COMPLETENESS_EXCLUDE = {
    "source", "source_url", "competition", "kickoff_utc", "status", "home_team", "away_team",
    "home_score", "away_score", "home_score_ht", "away_score_ht", "venue", "note",
    "base_source", "field_sources", "additional_notes", "opponent_context_error", "source_conflicts",
    # Null whenever home/away squad values came from the SAME source (the
    # common case) -- a real "nothing to flag" result, not an unknown gap;
    # see squad_value_basis_note's own doc comment on MatchInsights.
    "squad_value_basis_note",
    # Same reasoning -- null whenever a real lineup already exists (no
    # projection was needed), not a gap.
    "projected_xi_basis",
    # home/away_losing_streak_context used to live here: they returned
    # None both for "no streak data" and for "checked, team is fine", so
    # excluding them hid nulls the customer couldn't explain. Fixed at the
    # source instead -- compute_losing_streak_context now returns a
    # streak_count=0 sentinel when streak data exists but there's no 2+
    # losing streak (counted populated), and None only when there's no
    # streak data at all (counted missing, like any other gap).
}

# MatchDetails fields that can only be known during or after the match
# itself -- never a pre-match fixture property, not even a prediction.
# Excluded from compute_data_completeness's total (not just scored as
# "missing") when the match hasn't kicked off yet: counting them against
# an unplayed fixture's completeness penalizes the report for not having
# data that is structurally impossible to have yet, the same category of
# mistake already fixed once for home_score/away_score/*_ht above (in
# _COMPLETENESS_EXCLUDE, unconditionally). Unlike the unconditional score
# exclusion, these stay counted once a match is live or finished, where
# they're real data.
_MATCH_OUTCOME_ONLY_FIELDS = {
    "attendance", "match_stats", "event_timeline", "player_of_the_match",
    # Confirmed live: sofascore.py's _extract_set_piece_goals/
    # _extract_shotmap_stats deliberately return a zero-filled
    # SetPieceGoals/ShotmapStats -- never None -- for an unplayed match
    # ("empty (not null) for the not-yet-played upcoming match, same as
    # other match-in-progress fields", per that function's own
    # docstring). _is_populated treats any dataclass as populated
    # unconditionally, so without this exclusion these two fields
    # always counted as "populated" for every unplayed fixture
    # regardless of how far out kickoff was -- fake data indistinguishable
    # from a genuinely-played, zero-set-pieces match.
    "set_piece_goals", "shotmap_stats",
}

# Lineup/bench/formation are NOT outcome-only, despite feeling similar:
# Sofascore's own lineups payload goes absent -> predicted -> confirmed
# (see football/sites/sofascore.py's `lineup_confirmed` field and the
# comment above it) -- a "predicted" starting XI, built from recent
# matches and injury news, can legitimately exist hours or days before
# kickoff. So these belong with referee/odds (time-sensitive pre-match
# data that just may not be published yet for a fixture this far out),
# not with attendance/match_stats above (data that cannot exist by
# definition until the match happens) -- they're counted normally in
# compute_data_completeness at every status, not excluded. Kept as its
# own name (rather than folded into _MATCH_OUTCOME_ONLY_FIELDS) because
# report.py's JSON pruning still wants to drop these keys entirely when
# genuinely empty, the same cosmetic cleanup as the true outcome-only set.
_PREDICTABLE_PREMATCH_FIELDS = {"home_lineup", "away_lineup", "home_bench", "away_bench", "home_formation", "away_formation"}

# MatchInsights fields whose compute_* function explicitly distinguishes
# None ("no squad/stats data to check at all") from a real, checked []
# ("checked every candidate, genuinely none qualify") -- see the
# docstrings on compute_card_risks, compute_duel_vulnerabilities, and
# compute_fullback_exposure. For these six fields specifically, an empty
# list IS real, informative data (e.g. "no player currently at risk of
# a card"), not a gap -- the generic list-emptiness check in
# _is_populated would otherwise score a genuinely clean squad the same
# as a squad we never got data for at all, silently understating
# completeness for exactly the reports that turned out fine.
_CHECKED_EMPTY_LIST_FIELDS = {
    "home_card_risks", "away_card_risks",
    "home_duel_vulnerabilities", "away_duel_vulnerabilities",
    "home_fullback_exposure", "away_fullback_exposure",
}


def _is_populated(v) -> bool:
    if v is None:
        return False
    if isinstance(v, (list, dict)):
        return len(v) > 0
    if isinstance(v, str):
        return len(v) > 0
    from dataclasses import is_dataclass

    if is_dataclass(v):
        return True
    return True


def is_empty_value(value) -> bool:
    """None, an empty list, or an empty string -- report.py's own JSON
    pruning previously only checked the first two, silently missing
    string-typed outcome fields (home_formation/away_formation are
    Optional[str]): confirmed live, those came back as "" rather than
    None for an unplayed fixture, so the old check's `value == []` never
    matched and the fields survived pruning as pointless empty strings."""
    return value is None or value == [] or value == ""


def compute_data_completeness(merged: MatchDetails, insights: MatchInsights | None) -> dict[str, Any]:
    """How much of the *available* schema this particular run actually
    got real data for -- coverage varies a lot match-to-match, so this is
    a per-run signal, not a fixed target.

    Fields that can only exist once a match is live or finished
    (attendance, in-match stats, timeline, player of the match) are
    excluded from the total entirely for a not-yet-started fixture, not
    merely counted as "missing" -- an upcoming fixture's real analytical
    value is pre-match: difficulty/rest/form comparisons, not data that
    doesn't exist yet. Lineups/bench/formation are deliberately NOT in
    that excluded set even though they feel similar: sources publish a
    "predicted" lineup pre-match (built from recent matches + injuries)
    before it's confirmed near kickoff, so those fields count normally
    at every status -- absence there is real, informative "not published
    yet", the same as referee or odds, not a category error.

    card_risks/duel_vulnerabilities/fullback_exposure (home+away) count
    a real, checked [] as populated, not missing -- see
    _CHECKED_EMPTY_LIST_FIELDS: their compute_* functions only return
    None when there's no squad data to check at all, so an empty list
    means "checked, genuinely nothing flagged" (e.g. no player currently
    at card risk), which is real data, not a gap."""
    not_started = merged.status in _NOT_STARTED_STATUSES
    merged_total, merged_missing = _count_merged_completeness(merged, not_started)
    insights_total, insights_missing = _count_insights_completeness(insights)
    missing = merged_missing + insights_missing
    total = merged_total + insights_total
    # `missing` names every counted field that had no data this run, so a
    # consumer sees WHICH fields make up the gap, not just how many.
    # `denominator` documents what `total` is actually counting so a
    # consumer comparing 118 vs 116 across runs can see the schema itself
    # didn't silently change under them.
    return {
        "populated": total - len(missing),
        "total": total,
        "missing": missing,
        "denominator": (
            "MatchDetails + MatchInsights dataclass fields, excluding "
            "_COMPLETENESS_EXCLUDE (scores, provenance bookkeeping) and, "
            "pre-match only, _MATCH_OUTCOME_ONLY_FIELDS (attendance, "
            "in-match stats, timeline, player of the match, set pieces) "
            "which cannot exist until kickoff; lineup/bench/formation "
            "always count (predicted lineups are real pre-match data)"
        ),
        "outcome_fields_excluded_pre_match": sorted(_MATCH_OUTCOME_ONLY_FIELDS) if not_started else [],
    }


def _count_merged_completeness(merged: MatchDetails, not_started: bool) -> tuple[int, list[str]]:
    """total, names of fields with no data across MatchDetails' own fields -- extracted from
    compute_data_completeness (which had two similar loops, one over
    `merged`'s fields and one over `insights`'s, both accumulating
    branching complexity in a single function) purely to keep that
    function's cognitive complexity readable; behavior is unchanged."""
    from dataclasses import fields as _fields

    total = 0
    missing: list[str] = []
    for f in _fields(merged):
        if f.name in _COMPLETENESS_EXCLUDE:
            continue
        if not_started and f.name in _MATCH_OUTCOME_ONLY_FIELDS:
            continue
        total += 1
        value = getattr(merged, f.name)
        populated = value is not None if f.name in CONFIRMED_EMPTY_FIELDS else _is_populated(value)
        if not populated:
            missing.append(f.name)
    return total, missing


def _count_insights_completeness(insights: MatchInsights | None) -> tuple[int, list[str]]:
    """total, names of fields with no data across MatchInsights' own fields -- see
    _count_merged_completeness's doc comment for why this is split out."""
    from dataclasses import fields as _fields

    if not insights:
        return 0, []
    total = 0
    missing: list[str] = []
    for f in _fields(insights):
        if f.name in _COMPLETENESS_EXCLUDE:
            continue
        total += 1
        value = getattr(insights, f.name)
        populated = value is not None if f.name in _CHECKED_EMPTY_LIST_FIELDS else _is_populated(value)
        if not populated:
            missing.append(f.name)
    return total, missing
