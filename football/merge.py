"""Cross-source merging: combines each source's MatchDetails/TeamProfile
into one MergedMatch/MergedProfile, filling gaps field-by-field in
SOURCE_ORDER priority, plus the squad-analysis computations (top
performers/defenders, bench regulars, role-based form breakdowns) that
operate on a merged squad. Ported from src/search.ts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, fields
from typing import Any, Literal

from ._jsmath import js_round_to
from .team_name_match import normalize_for_match as normalize_team_name
from .types import (
    DefensiveStats,
    MatchDetails,
    Source,
    SquadMember,
    TeamProfile,
)

# Sofascore is the base/primary source for the merged report -- every other
# source only supplements fields Sofascore doesn't have. This order is both
# "who's the base" (first entry) and "fill-gap priority" (fallback order)
# for everything downstream.
SOURCE_ORDER: tuple[Source, ...] = ("sofascore", "fotmob", "soccerdesk", "goal", "365scores")

# wttr.in isn't a per-team Source (it has no fixtures/lineups/squad to
# search) -- it only ever fills the single `weather` field, as a post-merge
# supplemental fetch, so field_sources needs to name it too.
FieldSource = Literal["sofascore", "fotmob", "soccerdesk", "goal", "365scores", "wttr.in"]


def is_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


# Fields Sofascore might not have, that another source can fill in.
_MATCH_MERGE_FIELDS = [
    "venue_name", "venue_city", "venue_country", "referee", "referee_stats", "attendance", "weather",
    "head_to_head_summary", "head_to_head_streaks", "home_lineup", "away_lineup", "home_formation", "away_formation",
    "home_team_standing", "away_team_standing", "home_team_season_stats", "away_team_season_stats", "match_stats",
    "event_timeline", "player_of_the_match", "home_suspended_players", "away_suspended_players",
    # Added alongside the maximum-information audit: venue_lat/lon are
    # independently fallback-able even when venue_name itself already came
    # from the base source (same physical stadium regardless of which
    # source's own numbers we use, so mixing sources here is safe).
    # home_manager/away_manager previously came from Sofascore only; Fotmob
    # and SoccerDesk now populate them too. home_missing_players/
    # away_missing_players and manager_duel are Sofascore/Fotmob-only today
    # but listed here so any future source that starts populating them
    # participates in the same fallback automatically.
    "venue_lat", "venue_lon", "home_manager", "away_manager",
    "home_missing_players", "away_missing_players", "manager_duel",
    # recent_meetings: the generic merge fallback fills this from whichever
    # source has it (today: SoccerDesk); orchestrate.py's deeper
    # Sofascore-based computation (recentMeetings with formations/xG) then
    # overwrites it when THAT succeeds, but no longer clobbers this
    # fallback with None when it doesn't -- see run_search.
    "recent_meetings",
]

_PROFILE_MERGE_FIELDS = ["squad", "average_age", "injuries", "key_injuries", "recent_transfers"]


@dataclass
class AdditionalNote:
    source: Source
    note: str


@dataclass
class MergedMatch(MatchDetails):
    """MatchDetails plus provenance metadata -- a flat subclass (not a
    wrapper) so downstream code reads `merged.home_team`,
    `merged.venue_name`, etc. directly, exactly like the rest of
    MatchDetails' fields, matching the TS `interface MergedMatch extends
    MatchDetails` shape. All three fields below are always passed
    explicitly at construction (never relied on as defaults) -- the
    defaults exist only because MatchDetails' own last field (`note`) has
    one, and Python dataclass inheritance requires every field after the
    first defaulted one to have a default too."""

    base_source: Source | None = None
    field_sources: dict[str, FieldSource] = field(default_factory=dict)
    additional_notes: list[AdditionalNote] = field(default_factory=list)


def _fill_missing_fields(merged: dict, by_source: dict, base_source: Source, field_names: list[str]) -> dict[str, Source]:
    """Mutates `merged` in place, filling any of `field_names` still empty
    after the base source with the first other source (in SOURCE_ORDER)
    that has a non-empty value for it. Shared by merge_match_details and
    merge_team_profile -- both had this identical loop, just over a
    different field list; extracted to keep both functions' own cognitive
    complexity down (python:S3776) rather than duplicating it twice.
    Behavior unchanged for either call site."""
    field_sources: dict[str, Source] = {}
    for field_name in field_names:
        if not is_empty(merged.get(field_name)):
            continue
        for src in SOURCE_ORDER:
            if src == base_source:
                continue
            candidate = by_source.get(src)
            if candidate is not None:
                candidate_val = getattr(candidate, field_name)
                if not is_empty(candidate_val):
                    merged[field_name] = candidate_val
                    field_sources[field_name] = src
                    break
    return field_sources


def merge_match_details(by_source: dict[Source, MatchDetails]) -> MergedMatch:
    base_source = next((s for s in SOURCE_ORDER if s in by_source), next(iter(by_source)))
    base = by_source[base_source]
    merged = {f.name: getattr(base, f.name) for f in fields(base)}
    field_sources = _fill_missing_fields(merged, by_source, base_source, _MATCH_MERGE_FIELDS)

    additional_notes = [
        AdditionalNote(source=src, note=d.note)
        for src, d in by_source.items()
        if src != base_source and d.note
    ]

    return MergedMatch(
        **merged,
        base_source=base_source,
        field_sources=field_sources,
        additional_notes=additional_notes,
    )


@dataclass
class MergedProfile(TeamProfile):
    """Flat subclass of TeamProfile, same reasoning as MergedMatch above."""

    base_source: Source | None = None
    field_sources: dict[str, Source] = field(default_factory=dict)
    # All five computed purely from this profile's own (already fully
    # enriched) squad -- zero extra requests. Previously computed only
    # inside format_markdown.py and never stored anywhere, so a JSON
    # consumer had no way to see them even though the underlying data and
    # computation already existed. Populated by run_search once squad
    # enrichment (season stats, defensive stats, recent usage) finishes
    # for both sides -- see orchestrate.py.
    top_scorers: list[TopPerformer] = field(default_factory=list)
    top_assists: list[TopPerformer] = field(default_factory=list)
    top_defenders: list[TopDefender] = field(default_factory=list)
    bench_regulars: list[BenchRegular] = field(default_factory=list)
    midfielders_form: list[RoleFormEntry] = field(default_factory=list)
    defenders_form: list[RoleFormEntry] = field(default_factory=list)
    recent_form_leaders: list[RecentFormLeader] = field(default_factory=list)


# Matches Fotmob/365scores' full word ("Midfielder"), Goal's uppercase enum
# ("MIDFIELDER"), and Sofascore's single-letter code ("M"). SoccerDesk never
# sets role at all, so its injuries (never populated anyway) are unaffected.
def is_midfield_role(role: str | None) -> bool:
    if not role:
        return False
    return role.upper() == "M" or "mid" in role.lower()


# Same tolerance-for-format-differences approach as is_midfield_role --
# Sofascore's single-letter code ("D"), Goal's uppercase enum
# ("DEFENDER"), and full words all match.
def is_defender_role(role: str | None) -> bool:
    if not role:
        return False
    lowered = role.lower()
    return role.upper() == "D" or "defen" in lowered or "back" in lowered


def is_attacker_role(role: str | None) -> bool:
    if not role:
        return False
    r = role.upper()
    lowered = role.lower()
    return r in ("F", "A") or "forward" in lowered or "attack" in lowered or "striker" in lowered


def is_goalkeeper_role(role: str | None) -> bool:
    if not role:
        return False
    r = role.upper()
    lowered = role.lower()
    return r in ("G", "GK") or "goalkeeper" in lowered or "keeper" in lowered


def compute_missing_midfielders(injuries: list[SquadMember] | None) -> list[str] | None:
    if injuries is None:
        return None
    return [p.name for p in injuries if is_midfield_role(p.role)]


def compute_missing_by_role(
    injuries: list[SquadMember] | None, matches: Callable[[str | None], bool]
) -> list[str] | None:
    if injuries is None:
        return None
    return [p.name for p in injuries if matches(p.role)]


def surname(name: str) -> str:
    """Only Goal.com's squad carries per-player season stats, and it
    abbreviates first names ("A. Becker"), so it can't be matched against
    another source's squad by exact name -- last-name-only match is the
    best available common ground. This is approximate: two same-surname
    players in one squad (rare but real) would collide, and the stats
    attach to whichever matches first."""
    parts = [p for p in normalize_team_name(name).split(" ") if p]
    return parts[-1] if parts else ""


def _season_stats_by_surname(by_source: dict[Source, TeamProfile]) -> dict[str, tuple[Any, Source]]:
    """First (highest-priority, per SOURCE_ORDER) source with season_stats
    for a given surname wins. Extracted from enrich_squad_with_season_stats
    to keep its own cognitive complexity down (python:S3776); behavior
    unchanged."""
    stats_by_surname: dict[str, tuple[Any, Source]] = {}
    for src in SOURCE_ORDER:
        profile = by_source.get(src)
        for member in (profile.squad if profile and profile.squad else []):
            if member.season_stats:
                key = surname(member.name)
                if key not in stats_by_surname:
                    stats_by_surname[key] = (member.season_stats, src)
    return stats_by_surname


def enrich_squad_with_season_stats(squad: list[SquadMember], by_source: dict[Source, TeamProfile]) -> list[SquadMember]:
    """Inherited bug, found and fixed here (confirmed it also exists in
    the original TS -- Map.set() there has the identical unconditional-
    overwrite behavior): iterating SOURCE_ORDER and unconditionally
    setting stats_by_surname[surname] on every match meant the LAST
    source in SOURCE_ORDER with data for a player silently won, not the
    first/highest-priority one -- the opposite of the priority-fallback
    convention every other merge function in this file follows (see
    merge_match_details/merge_team_profile's own "first match wins,
    then break" loops). Fixed by only setting a surname's entry once."""
    stats_by_surname = _season_stats_by_surname(by_source)
    if not stats_by_surname:
        return squad

    result = []
    for m in squad:
        if m.season_stats:
            result.append(m)
            continue
        found = stats_by_surname.get(surname(m.name))
        if found:
            stats, src = found
            result.append(_replace(m, season_stats=stats, season_stats_source=src))
        else:
            result.append(m)
    return result


def _replace(m: SquadMember, **changes: Any) -> SquadMember:
    kwargs = {f.name: getattr(m, f.name) for f in fields(m)}
    kwargs.update(changes)
    return SquadMember(**kwargs)


async def enrich_squad_with_defensive_stats(
    squad: list[SquadMember], team_name: str, competition_candidates: list[str]
) -> list[SquadMember]:
    """Squawka isn't a MatchInfo source, so this is a separate enrichment
    step (async, needs a live fetch) rather than folding into the
    SOURCE_ORDER merge loop -- same pattern as StadiumDB/wttr.in. Matches
    by exact normalized name (Squawka publishes full names, same as
    Sofascore)."""
    from .sites.squawka import get_squawka_defensive_stats

    try:
        stats_by_name = await get_squawka_defensive_stats(team_name, competition_candidates)
    except Exception:  # noqa: BLE001 - mirrors TS's .catch(() => new Map())
        stats_by_name: dict[str, DefensiveStats] = {}
    if not stats_by_name:
        return squad
    return [
        (_replace(m, defensive_stats=stats_by_name[normalize_team_name(m.name)]) if normalize_team_name(m.name) in stats_by_name else m)
        for m in squad
    ]


@dataclass
class TopPerformer:
    name: str
    goals: int
    assists: int
    appearances: int | None
    rating: float | None
    source: Source | None


def compute_top_performers(squad: list[SquadMember] | None, by: Literal["goals", "assists"], count: int = 3) -> list[TopPerformer]:
    if not squad:
        return []
    candidates = [m for m in squad if m.season_stats and getattr(m.season_stats, by) > 0]
    candidates.sort(key=lambda m: getattr(m.season_stats, by), reverse=True)
    return [
        TopPerformer(
            name=m.name,
            goals=m.season_stats.goals,
            assists=m.season_stats.assists,
            appearances=m.season_stats.appearances,
            rating=m.season_stats.rating,
            source=m.season_stats_source,
        )
        for m in candidates[:count]
    ]


@dataclass
class TopDefender:
    name: str
    tackles_made: int
    interceptions: int


def compute_top_defenders(squad: list[SquadMember] | None, count: int = 3) -> list[TopDefender]:
    """Ranked by tackles+interceptions combined -- both are real
    defensive-activity counts (see DefensiveStats), not the literal
    pressing/defensive-line metrics the original checklist asked for."""
    if not squad:
        return []
    candidates = [
        m
        for m in squad
        if m.defensive_stats and ((m.defensive_stats.tackles_made or 0) > 0 or (m.defensive_stats.interceptions or 0) > 0)
    ]

    def score(m: SquadMember) -> int:
        return (m.defensive_stats.tackles_made or 0) + (m.defensive_stats.interceptions or 0)

    candidates.sort(key=score, reverse=True)
    return [
        TopDefender(
            name=m.name,
            tackles_made=m.defensive_stats.tackles_made or 0,
            interceptions=m.defensive_stats.interceptions or 0,
        )
        for m in candidates[:count]
    ]


@dataclass
class BenchRegular:
    name: str
    matches_in_squad: int
    starts: int
    sub_appearances: int
    unused_bench: int


def compute_bench_regulars(squad: list[SquadMember] | None, count: int = 5) -> list[BenchRegular]:
    """Players named in the matchday squad (last20Overall sample) more
    often than they actually started -- i.e. genuinely bench-regular, not
    just "happened to miss one game." Requires at least 2 non-start
    appearances (sub-on or unused) to filter out a single one-off absence
    reading as a pattern."""
    if not squad:
        return []
    candidates = [
        m
        for m in squad
        if m.recent_usage
        and (m.recent_usage.sub_appearances + m.recent_usage.unused_bench) >= 2
        and (m.recent_usage.sub_appearances + m.recent_usage.unused_bench) > m.recent_usage.starts
    ]
    candidates.sort(key=lambda m: m.recent_usage.matches_in_squad or 0, reverse=True)
    return [
        BenchRegular(
            name=m.name,
            matches_in_squad=m.recent_usage.matches_in_squad,
            starts=m.recent_usage.starts,
            sub_appearances=m.recent_usage.sub_appearances,
            unused_bench=m.recent_usage.unused_bench,
        )
        for m in candidates[:count]
    ]


@dataclass
class RecentFormLeader:
    name: str
    goals: int
    assists: int
    xg: float
    xa: float
    avg_rating: float | None
    goals_per90: float | None
    assists_per90: float | None
    key_passes: int
    sample_size: int


@dataclass
class RoleFormEntry:
    name: str
    matches_in_squad: int
    starts: int
    total_minutes: int
    goals: int
    assists: int
    xg: float
    xa: float
    key_passes: int
    avg_rating: float | None


def compute_role_form_breakdown(
    squad: list[SquadMember] | None, role_check: Callable[[str | None], bool], count: int = 5
) -> list[RoleFormEntry]:
    """compute_recent_form_leaders ranks by goals+assists, which
    structurally excludes most midfielders/defenders -- they rarely lead a
    squad in G+A even when heavily used. This ranks by playing time
    instead (most-used first) within a single role group, surfacing the
    same already-fetched recent_usage numbers for the players that ranking
    skips over. Zero extra requests."""
    if not squad:
        return []
    candidates = [m for m in squad if role_check(m.role) and m.recent_usage and m.recent_usage.matches_in_squad > 0]
    candidates.sort(key=lambda m: m.recent_usage.total_minutes, reverse=True)
    return [
        RoleFormEntry(
            name=m.name,
            matches_in_squad=m.recent_usage.matches_in_squad,
            starts=m.recent_usage.starts,
            total_minutes=m.recent_usage.total_minutes,
            goals=m.recent_usage.total_goals,
            assists=m.recent_usage.total_assists,
            xg=js_round_to(m.recent_usage.total_xg, 2),
            xa=js_round_to(m.recent_usage.total_xa, 2),
            key_passes=m.recent_usage.total_key_passes,
            avg_rating=m.recent_usage.avg_rating,
        )
        for m in candidates[:count]
    ]


def compute_recent_form_leaders(squad: list[SquadMember] | None, count: int = 3) -> list[RecentFormLeader]:
    """Same "last 10 played, real per-match data" scope as everything else
    the venue-classification enrichment produces -- distinct from the
    season-wide totals top_performers already show, this is specifically
    recent form."""
    if not squad:
        return []
    candidates = [m for m in squad if m.recent_usage and (m.recent_usage.total_goals + m.recent_usage.total_assists) > 0]
    candidates.sort(key=lambda m: m.recent_usage.total_goals + m.recent_usage.total_assists, reverse=True)
    return [
        RecentFormLeader(
            name=m.name,
            goals=m.recent_usage.total_goals,
            assists=m.recent_usage.total_assists,
            xg=js_round_to(m.recent_usage.total_xg, 2),
            xa=js_round_to(m.recent_usage.total_xa, 2),
            avg_rating=m.recent_usage.avg_rating,
            goals_per90=m.recent_usage.goals_per_90,
            assists_per90=m.recent_usage.assists_per_90,
            key_passes=m.recent_usage.total_key_passes,
            sample_size=m.recent_usage.matches_in_squad,
        )
        for m in candidates[:count]
    ]


def merge_team_profile(by_source: dict[Source, TeamProfile]) -> MergedProfile:
    base_source = next((s for s in SOURCE_ORDER if s in by_source), next(iter(by_source)))
    base = by_source[base_source]
    merged = {f.name: getattr(base, f.name) for f in fields(base)}
    field_sources = _fill_missing_fields(merged, by_source, base_source, _PROFILE_MERGE_FIELDS)

    merged["missing_midfielders"] = compute_missing_midfielders(merged.get("injuries"))
    merged["missing_attackers"] = compute_missing_by_role(merged.get("injuries"), is_attacker_role)
    merged["missing_defenders"] = compute_missing_by_role(merged.get("injuries"), is_defender_role)
    merged["missing_goalkeepers"] = compute_missing_by_role(merged.get("injuries"), is_goalkeeper_role)
    if merged.get("squad"):
        merged["squad"] = enrich_squad_with_season_stats(merged["squad"], by_source)

    return MergedProfile(**merged, base_source=base_source, field_sources=field_sources)


def apply_deep_recent_meetings(merged: MergedMatch, deep_meetings: list, source: Source) -> None:
    """Overwrites merged.recent_meetings with a richer, deeper computation
    (formations/xG/lineups per meeting) that only one specific `source`
    can produce, and keeps merged.field_sources' provenance label honest
    when doing so.

    The generic field-merge (merge_match_details, run earlier) may have
    already tagged "recent_meetings" as coming from a fallback source
    (e.g. SoccerDesk) because the base source's own field was empty at
    that point. This deeper computation can succeed afterwards using
    `source`'s raw data even when base_source lacked match details -- so
    the label needs to reflect whichever source actually produced the
    final value, not what was true at merge time. No-op if deep_meetings
    is empty (a decent fallback from the earlier merge is left in place
    rather than being cleared)."""
    if not deep_meetings:
        return
    merged.recent_meetings = deep_meetings
    if source == merged.base_source:
        merged.field_sources.pop("recent_meetings", None)
    else:
        merged.field_sources["recent_meetings"] = source
