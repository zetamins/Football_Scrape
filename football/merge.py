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
from .fetch_log import record_step_failure
from .team_name_match import normalize_for_match as normalize_team_name
from .types import (
    DefensiveStats,
    MatchDetails,
    MissingPlayer,
    Source,
    SquadMember,
    TeamProfile,
)

# Sofascore is the base/primary source for the merged report -- every other
# source only supplements fields Sofascore doesn't have. This order is both
# "who's the base" (first entry) and "fill-gap priority" (fallback order)
# for everything downstream.
SOURCE_ORDER: tuple[Source, ...] = ("sofascore", "fotmob", "soccerdesk", "goal", "365scores")

# Reliability weights used ONLY to settle a genuine disagreement between
# sources on a hard number (see detect_source_conflicts). They restate
# SOURCE_ORDER's trust ranking as votes: Sofascore (the base) outweighs any
# single other source, but two mid-tier sources that agree with each other
# (2 + 2 = 4) outvote it -- one dissenting source never overrides the
# base, a small consensus can. Not used to pick between spellings.
SOURCE_WEIGHTS: dict[str, int] = {"sofascore": 3, "fotmob": 2, "goal": 2, "soccerdesk": 1, "365scores": 1}

# Fields whose values are hard numbers: a disagreement is a real conflict
# and is settled by weighted vote.
_NUMERIC_CONFLICT_FIELDS = ("venue_capacity", "attendance", "home_score", "away_score", "home_score_ht", "away_score_ht")
# Fields whose values are names/labels, where sources legitimately spell
# things differently ("Old Trafford" / "Old Trafford Stadium"): a
# disagreement is only REPORTED, and the base source's value is kept.
_TEXT_CONFLICT_FIELDS = ("venue_name", "venue_city", "venue_country", "referee", "home_formation", "away_formation")


# wttr.in isn't a per-team Source (it has no fixtures/lineups/squad to
# search) -- it only ever fills the single `weather` field, as a post-merge
# supplemental fetch, so field_sources needs to name it too.
# "derived" (not a real site) marks a field this project computed itself
# from other data rather than any source actually publishing it -- e.g.
# orchestrate.derive_lineup_and_formation's projected pre-match lineup.
# "mixed" means the final value is a splice of rows from more than one
# source (recent_meetings deep+leftover is the only current case) --
# neither a single site nor a pure derivation. "football-data" is the
# football-data.co.uk fixtures CSV (odds/referee), distinct from its
# per-season results CSV used for referee bias stats.
FieldSource = Literal[
    "sofascore", "fotmob", "soccerdesk", "goal", "365scores", "wttr.in",
    "derived", "mixed", "football-data",
]


def is_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


# Fields where a source's explicit [] means "checked -- none" (e.g. nobody
# suspended), a real answer distinct from None ("no source told us"). The
# generic is_empty() would treat that [] as missing and keep hunting for a
# non-empty value, discarding the confirmation.
CONFIRMED_EMPTY_FIELDS = frozenset({"home_suspended_players", "away_suspended_players", "home_missing_players", "away_missing_players"})


def _is_unfilled(field_name: str, value: Any) -> bool:
    return value is None if field_name in CONFIRMED_EMPTY_FIELDS else is_empty(value)


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


def is_match_details_complete(details: MatchDetails) -> bool:
    """True when the base source's own MatchDetails already has every
    field a fallback source could otherwise fill in (_MATCH_MERGE_FIELDS)
    -- lets a caller skip fetching another source's match details entirely
    once there is genuinely nothing left for it to contribute, instead of
    always scraping every source and discarding most of what comes back.
    A pre-match fixture will rarely satisfy this (referee/odds/lineups
    aren't published yet) -- that's correct, not a bug: those fields are
    still worth trying other sources for until kickoff nears."""
    return all(not _is_unfilled(name, getattr(details, name, None)) for name in _MATCH_MERGE_FIELDS)


def is_profile_complete(profile: TeamProfile) -> bool:
    """Same idea as is_match_details_complete, for a team profile
    (_PROFILE_MERGE_FIELDS) -- squad/injuries are usually always available
    from an established team's base-source profile, so this one triggers
    far more often in practice."""
    return all(not _is_unfilled(name, getattr(profile, name, None)) for name in _PROFILE_MERGE_FIELDS)


def _deduplicate_transfers(transfers: list | None) -> list | None:
    """De-duplicate transfer records that appear in multiple sources.
    Matches by (player_name, direction, date) -- same player, same
    direction, same date is a duplicate. Also handles reversals (same
    player appearing as both 'in' and 'out' from different sources)
    by keeping the more recent entry."""
    if not transfers:
        return transfers
    from .types import TransferRecord

    seen: dict[tuple, TransferRecord] = {}
    for t in transfers:
        if not isinstance(t, TransferRecord):
            continue
        key = (normalize_team_name(t.player_name), t.direction, t.date)
        if key not in seen:
            seen[key] = t
    return list(seen.values()) if seen else transfers


@dataclass
class AdditionalNote:
    source: Source
    note: str


@dataclass
class SourceValue:
    # `from_source`, not `source`: report.py strips every "source" key from
    # the JSON output as a per-item label.
    from_source: str
    value: str | int | float


@dataclass
class SourceConflict:
    """Sources disagreed on `field`. `kept` is the value the report uses
    (from `kept_source`); `alternatives` are the other values and who gave
    them; `resolution` says how `kept` was chosen."""

    field: str
    kept: str | int | float
    kept_source: str
    alternatives: list[SourceValue]
    resolution: str


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
    source_conflicts: list[SourceConflict] = field(default_factory=list)


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
        if not _is_unfilled(field_name, merged.get(field_name)):
            continue
        for src in SOURCE_ORDER:
            if src == base_source:
                continue
            candidate = by_source.get(src)
            if candidate is not None:
                candidate_val = getattr(candidate, field_name)
                if not _is_unfilled(field_name, candidate_val):
                    merged[field_name] = candidate_val
                    field_sources[field_name] = src
                    break
    return field_sources


def _same_text(a: str, b: str) -> bool:
    na, nb = normalize_team_name(a), normalize_team_name(b)
    return na == nb or (bool(na) and bool(nb) and (na in nb or nb in na))


def _group_by_agreement(present: dict[str, Any], numeric: bool) -> list[list[str]]:
    """Sources whose values agree, as lists ordered by SOURCE_ORDER; text
    agrees loosely (_same_text), numbers exactly."""
    groups: list[list[str]] = []
    for src in SOURCE_ORDER:
        if src not in present:
            continue
        for group in groups:
            other = present[group[0]]
            if present[src] == other if numeric else _same_text(str(present[src]), str(other)):
                group.append(src)
                break
        else:
            groups.append([src])
    return groups


def _settle_numeric_conflict(
    groups: list[list[str]], current_source: str, base_source: Source, merged: dict, field_sources: dict, field_name: str, present: dict
) -> tuple[str, str]:
    """The weighted-vote branch of detect_source_conflicts, extracted to
    keep that function's own cognitive complexity down (python:S3776).
    Mutates `merged`/`field_sources` when the consensus beats the current
    source. Returns (new current_source, resolution)."""
    winner = max(groups, key=lambda g: (sum(SOURCE_WEIGHTS.get(s, 1) for s in g), -SOURCE_ORDER.index(g[0])))
    if current_source in winner:
        return current_source, f"{current_source} kept"
    winning_source = winner[0]
    merged[field_name] = present[winning_source]
    if winning_source == base_source:
        field_sources.pop(field_name, None)
    else:
        field_sources[field_name] = winning_source
    return winning_source, f"weighted vote: {len(winner)} sources agree"


def _looks_like_wrong_fixture(field_name: str, kept_value, alternatives: list[SourceValue]) -> bool:
    """True when a text conflict is not a spelling/punctuation difference
    ("Old Trafford" vs "Old Trafford Stadium") but a source that resolved
    to an entirely different place -- confirmed live on the Germany
    report: Sofascore said venue_city=Amsterdam while Fotmob's
    venueDetails said Karlsruhe (StadiumDB resolved the club-name query
    to a different ground entirely). Shared tokens of length >2 are what
    makes two strings "about the same place"; zero overlap means they
    almost certainly are not."""
    if field_name not in ("venue_name", "venue_city", "venue_country"):
        return False

    def _tokens(v) -> set[str]:
        return {w for w in str(v or "").lower().split() if len(w) > 2}

    kept_tokens = _tokens(kept_value)
    if not kept_tokens:
        return False
    return any(not (kept_tokens & _tokens(a.value)) for a in alternatives)


def _text_conflict_resolution(field_name: str, current_source: str, present: dict, kept_value) -> str:
    """Resolution string for the text-conflict (report-only) branch of
    detect_source_conflicts. Defaults to the honest "disagreements are
    reported, not overridden" note, but upgrades to an explicit
    wrong-fixture flag when the values are not near-spelling variants of
    each other but entirely different places (see
    _looks_like_wrong_fixture) -- otherwise a reader has no way to tell
    "two spellings of one stadium" from "one source matched the wrong
    match entirely"."""
    alternatives = [SourceValue(from_source=src, value=v) for src, v in present.items() if v != kept_value]
    if _looks_like_wrong_fixture(field_name, kept_value, alternatives):
        return (
            f"{current_source} kept; at least one alternative appears to be a different fixture "
            f"(resolved to an unrelated place) -- reported, not overridden"
        )
    return f"{current_source} kept (text disagreements are reported, not overridden)"


def detect_source_conflicts(
    by_source: dict[Source, MatchDetails], base_source: Source, merged: dict, field_sources: dict[str, Source]
) -> list[SourceConflict]:
    """Finds fields where two or more sources gave DIFFERENT non-empty
    values. Numeric fields are settled by SOURCE_WEIGHTS vote (mutating
    `merged`/`field_sources` when the consensus beats the base source);
    text fields are only reported. A source that simply lacks a value is
    not a conflict (that's what the fill-from-fallback merge is for)."""
    conflicts: list[SourceConflict] = []
    for field_name in (*_NUMERIC_CONFLICT_FIELDS, *_TEXT_CONFLICT_FIELDS):
        present = {src: v for src, d in by_source.items() if (v := getattr(d, field_name, None)) not in (None, "")}
        if len(present) < 2:
            continue
        numeric = field_name in _NUMERIC_CONFLICT_FIELDS
        groups = _group_by_agreement(present, numeric)
        if len(groups) < 2:
            continue
        current_source = field_sources.get(field_name, base_source)
        if numeric:
            current_source, resolution = _settle_numeric_conflict(groups, current_source, base_source, merged, field_sources, field_name, present)
        else:
            resolution = _text_conflict_resolution(field_name, current_source, present, merged.get(field_name))
        kept_value = merged.get(field_name)
        conflicts.append(SourceConflict(
            field=field_name, kept=kept_value, kept_source=current_source,
            alternatives=[SourceValue(from_source=src, value=present[src]) for g in groups for src in g if present[src] != kept_value],
            resolution=resolution,
        ))
    return conflicts


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

    # Validate lineup positions against formation to catch scraping
    # bugs where position tags don't match the stated formation.
    merged["home_lineup"] = _validate_lineup_positions(merged.get("home_lineup"), merged.get("home_formation"))
    merged["away_lineup"] = _validate_lineup_positions(merged.get("away_lineup"), merged.get("away_formation"))

    source_conflicts = detect_source_conflicts(by_source, base_source, merged, field_sources)

    return MergedMatch(
        **merged,
        base_source=base_source,
        field_sources=field_sources,
        additional_notes=additional_notes,
        source_conflicts=source_conflicts,
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
    # Set when no squad member received Squawka defensive stats, so an
    # empty top_defenders reads as "source unavailable", not "no defenders".
    defensive_stats_note: str | None = None
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


def canonical_role(role: str | None) -> str | None:
    """G/D/M/F for any source's spelling ("Keeper", "DEFENDER", "Attacker",
    "Midfielder"...), so both teams' squads use one role vocabulary in the
    output -- confirmed live: the own team came back as G/D/M/F while the
    opponent (a different source) came back as Keeper/Defender/
    Midfielder/Attacker. Unrecognized values pass through unchanged."""
    if is_goalkeeper_role(role):
        return "G"
    if is_defender_role(role):
        return "D"
    if is_midfield_role(role):
        return "M"
    if is_attacker_role(role):
        return "F"
    return role


def _with_canonical_roles(members: list[SquadMember] | None) -> list[SquadMember] | None:
    if not members:
        return members
    from dataclasses import replace as _replace

    return [_replace(m, role=canonical_role(m.role)) for m in members]


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


def reconcile_missing_by_role(
    squad: list[SquadMember] | None,
    injuries: list[SquadMember] | None,
    missing_players: list[MissingPlayer] | None,
    matches: Callable[[str | None], bool],
) -> list[str] | None:
    """Same shape as compute_missing_by_role, but also includes players
    from the match-level missing_players list (reconcile_missing_players'
    output) who aren't in `injuries` at all -- e.g. ruled out for a
    non-injury reason. MissingPlayer has no role field of its own, so
    it's looked up from `squad` by name.

    Confirmed live: Richarlison correctly appeared in
    match.away_missing_players (reason "coach_decision") but was absent
    from teamProfile.missing_attackers despite being a forward, since
    that field was computed from `injuries` alone, before
    reconcile_missing_players even runs in the pipeline. Returns None
    under the same condition compute_missing_by_role does (injuries is
    None -- no profile injury tracking available at all for this team),
    even if missing_players has entries, since squad/role data usually
    comes from the same unavailable profile fetch."""
    if injuries is None:
        return None
    result = [p.name for p in injuries if matches(p.role)]
    known = {normalize_team_name(n) for n in result}
    role_by_name = {normalize_team_name(m.name): m.role for m in (squad or [])}
    for p in (missing_players or []):
        norm = normalize_team_name(p.name)
        if norm in known:
            continue
        role = role_by_name.get(norm)
        if role and matches(role):
            result.append(p.name)
            known.add(norm)
    return result


def compute_non_injury_absences(profile) -> list[str] | None:
    """Names on the profile's missing_*_role lists that are NOT in
    teamProfile.injuries -- e.g. Richarlison (coach_decision, a forward,
    correctly in missing_attackers after reconcile_missing_by_role but
    absent from injuries). Explicit field so a JSON consumer sees the set
    difference without re-deriving it; None when there are none or when
    the role lists themselves are unavailable (no injury tracking)."""
    if profile is None:
        return None
    injury_names = {m.name for m in (profile.injuries or [])}
    missing = [
        *(profile.missing_midfielders or []),
        *(profile.missing_attackers or []),
        *(profile.missing_defenders or []),
        *(profile.missing_goalkeepers or []),
    ]
    if not missing and not injury_names:
        return None
    seen: set[str] = set()
    out: list[str] = []
    for name in missing:
        if name not in injury_names and name not in seen:
            seen.add(name)
            out.append(name)
    return out or None


def annotate_stat_window_notes(squad: list[SquadMember] | None) -> None:
    """Mutates each squad member in place: when season_stats.goals and
    recent_usage.total_goals disagree, store an explicit note naming both
    windows and both values (Gallagher 1 season vs 2 recent). Cleared when
    the numbers match or either side is missing, so a stale note never
    survives a re-enrichment that brought the figures into agreement."""
    for m in (squad or []):
        if m.season_stats and m.recent_usage:
            season_g = m.season_stats.goals
            recent_g = m.recent_usage.total_goals
            if season_g != recent_g:
                m.stat_window_note = (
                    f"season_stats.goals={season_g} (season to date) vs "
                    f"recent_usage.total_goals={recent_g} (last 20)"
                )
            else:
                m.stat_window_note = None
        else:
            m.stat_window_note = None


_MIN_CONTAINMENT_NAME_LEN = 3


def find_by_name_containment(name: str, candidates: dict[str, Any]) -> Any | None:
    """Fallback for two sources spelling the same player's name to
    different lengths -- confirmed live: Sofascore's "Chido Obi-Martin"
    vs Fotmob's "Chido Obi" for the same Man Utd player. Neither an exact
    normalized match nor surname() (which would compare "obi-martin" to
    "obi", still unequal) catches this; a normalized-substring check in
    either direction does: "chido obi" in "chido obi-martin".

    Same safety rule as enrich_squad_with_season_stats' surname fallback:
    only returned when exactly one candidate key overlaps, so a short or
    common fragment ("obi" alone would risk matching an unrelated
    "Obiora") doesn't silently attach the wrong player's data -- ambiguous
    or too-short names return None rather than guessing."""
    normalized = normalize_team_name(name)
    if len(normalized) < _MIN_CONTAINMENT_NAME_LEN:
        return None
    hits = [
        value for key, value in candidates.items()
        if len(key) >= _MIN_CONTAINMENT_NAME_LEN and (key in normalized or normalized in key)
    ]
    return hits[0] if len(hits) == 1 else None


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


def _season_stats_by_full_name(by_source: dict[Source, TeamProfile]) -> dict[str, tuple[Any, Source]]:
    """Same priority-fallback shape as _season_stats_by_surname, keyed by
    full normalized name instead. Tried first in
    enrich_squad_with_season_stats since it can't collide the way bare-
    surname matching can (see surname()'s own docstring)."""
    stats_by_name: dict[str, tuple[Any, Source]] = {}
    for src in SOURCE_ORDER:
        profile = by_source.get(src)
        for member in (profile.squad if profile and profile.squad else []):
            if member.season_stats:
                key = normalize_team_name(member.name)
                if key not in stats_by_name:
                    stats_by_name[key] = (member.season_stats, src)
    return stats_by_name


def enrich_squad_with_season_stats(squad: list[SquadMember], by_source: dict[Source, TeamProfile]) -> list[SquadMember]:
    """Inherited bug, found and fixed here (confirmed it also exists in
    the original TS -- Map.set() there has the identical unconditional-
    overwrite behavior): iterating SOURCE_ORDER and unconditionally
    setting stats_by_surname[surname] on every match meant the LAST
    source in SOURCE_ORDER with data for a player silently won, not the
    first/highest-priority one -- the opposite of the priority-fallback
    convention every other merge function in this file follows (see
    merge_match_details/merge_team_profile's own "first match wins,
    then break" loops). Fixed by only setting a surname's entry once.

    Full-name match is tried first; bare-surname match (surname()'s own
    documented approximation, needed for Goal.com's abbreviated first
    names) is used only as a fallback, and only when that surname is
    unambiguous within THIS squad -- confirmed live: two same-surname
    players in one squad (Everton's real starter "Jordan Pickford" and a
    fringe/youth "George Pickford") previously collided under bare-
    surname matching, silently attributing Jordan's real season stats to
    George despite George showing 0 minutes/0 starts in recent_usage."""
    stats_by_name = _season_stats_by_full_name(by_source)
    stats_by_surname = _season_stats_by_surname(by_source)
    if not stats_by_name and not stats_by_surname:
        return squad

    surname_counts: dict[str, int] = {}
    for m in squad:
        key = surname(m.name)
        surname_counts[key] = surname_counts.get(key, 0) + 1

    result = []
    for m in squad:
        if m.season_stats:
            result.append(m)
            continue
        found = stats_by_name.get(normalize_team_name(m.name))
        if not found and surname_counts[surname(m.name)] == 1:
            found = stats_by_surname.get(surname(m.name))
        if not found:
            found = find_by_name_containment(m.name, stats_by_name)
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
    except Exception as err:  # noqa: BLE001 - mirrors TS's .catch(() => new Map())
        record_step_failure("defensive stats (Squawka)", err)
        stats_by_name: dict[str, DefensiveStats] = {}
    if not stats_by_name:
        return squad
    result = []
    for m in squad:
        stats = stats_by_name.get(normalize_team_name(m.name)) or find_by_name_containment(m.name, stats_by_name)
        result.append(_replace(m, defensive_stats=stats) if stats else m)
    return result


@dataclass
class TopPerformer:
    name: str
    goals: int
    assists: int
    appearances: int | None
    rating: float | None
    source: Source | None
    # Which window these numbers cover ("season_to_date"). Row-level so a
    # JSON consumer never has to rely on a section header alone to know
    # these goals are season-wide, not last-20.
    window: str | None = "season_to_date"


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
            window="season_to_date",
        )
        for m in candidates[:count]
    ]


@dataclass
class TopDefender:
    name: str
    tackles_made: int
    interceptions: int
    source: Source | None = None


def compute_top_defenders(squad: list[SquadMember] | None, count: int = 3) -> list[TopDefender]:
    """Ranked by tackles+interceptions combined -- both are real
    defensive-activity counts (see DefensiveStats), not the literal
    pressing/defensive-line metrics the original checklist asked for.

    Restricted to is_defender_role(m.role) -- confirmed live this was
    previously missing entirely, letting high-tackle midfielders (e.g.
    Kobbie Mainoo, Youri Tielemans) outrank a team's real defenders and
    show up in a list named "top defenders". A team with no defender
    recording any Squawka tackles/interceptions now correctly returns
    [] instead of being backfilled with midfielders."""
    if not squad:
        return []
    candidates = [
        m
        for m in squad
        if is_defender_role(m.role)
        and m.defensive_stats
        and ((m.defensive_stats.tackles_made or 0) > 0 or (m.defensive_stats.interceptions or 0) > 0)
    ]

    def score(m: SquadMember) -> int:
        return (m.defensive_stats.tackles_made or 0) + (m.defensive_stats.interceptions or 0)

    candidates.sort(key=score, reverse=True)
    return [
        TopDefender(
            name=m.name,
            tackles_made=m.defensive_stats.tackles_made or 0,
            interceptions=m.defensive_stats.interceptions or 0,
            source="squawka",
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
    reading as a pattern. Excludes anyone currently injured (m.injury
    set) -- confirmed live: a trailing-stat-only filter surfaced a player
    with a Cruciate Ligament Injury as a "bench regular" purely from
    matches before the injury, with nothing about their current
    availability."""
    if not squad:
        return []
    candidates = [
        m
        for m in squad
        if m.recent_usage
        and not m.injury
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
    # Which window these numbers cover ("last_20"). Row-level counterpart
    # to TopPerformer.window -- same player can legitimately appear in both
    # leaderboards with different goal totals (Gallagher 1 vs 2).
    window: str | None = "last_20"


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
    recent form. Uses recent_usage data (from the venue-enrichment
    per-match fetch loop), not season_stats from any source.

    Excludes a currently-injured squad member (m.injury) -- confirmed
    live: a player out for months (a cruciate ligament injury, in one
    case) still topped this list on the strength of matches played before
    getting hurt, presenting someone who literally cannot play the
    upcoming fixture as the team's most in-form asset for it. Does not
    check suspension or the match-specific missing_players list (neither
    is available on SquadMember itself) -- a suspended-but-fit player
    genuinely was in recent form, so that omission is a narrower,
    deliberate scope, not an oversight."""
    if not squad:
        return []
    candidates = [m for m in squad if m.recent_usage and not m.injury and (m.recent_usage.total_goals + m.recent_usage.total_assists) > 0]
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
            window="last_20",
        )
        for m in candidates[:count]
    ]


def merge_team_profile(by_source: dict[Source, TeamProfile]) -> MergedProfile:
    base_source = next((s for s in SOURCE_ORDER if s in by_source), next(iter(by_source)))
    base = by_source[base_source]
    merged = {f.name: getattr(base, f.name) for f in fields(base)}
    field_sources = _fill_missing_fields(merged, by_source, base_source, _PROFILE_MERGE_FIELDS)
    for key in ("squad", "injuries", "key_injuries"):
        merged[key] = _with_canonical_roles(merged.get(key))

    merged["missing_midfielders"] = compute_missing_midfielders(merged.get("injuries"))
    merged["missing_attackers"] = compute_missing_by_role(merged.get("injuries"), is_attacker_role)
    merged["missing_defenders"] = compute_missing_by_role(merged.get("injuries"), is_defender_role)
    merged["missing_goalkeepers"] = compute_missing_by_role(merged.get("injuries"), is_goalkeeper_role)
    if merged.get("squad"):
        merged["squad"] = enrich_squad_with_season_stats(merged["squad"], by_source)
    if merged.get("recent_transfers"):
        merged["recent_transfers"] = _deduplicate_transfers(merged["recent_transfers"])

    return MergedProfile(**merged, base_source=base_source, field_sources=field_sources)


def _fix_missing_or_duplicate_gk(result: list, formation: str | None) -> None:
    """Extracted from _validate_lineup_positions to keep its own
    cognitive complexity down (python:S3776); behavior unchanged.

    A valid XI must have exactly one GK. Mutates result in place."""
    from dataclasses import replace as _replace

    gk_indices = [i for i, p in enumerate(result) if p.position and p.position.upper() == "G"]
    if len(gk_indices) == 0 and formation:
        # No GK found -- reclassify the first player without a position
        # (or the last outfield player if all have positions) as GK.
        no_pos = [i for i, p in enumerate(result) if not p.position]
        if no_pos:
            result[no_pos[0]] = _replace(result[no_pos[0]], position="G")
        elif len(result) >= 11:
            # All players have positions but none is GK -- reclassify
            # the first non-D non-M non-F player, or the last player.
            outfield = [i for i, p in enumerate(result) if p.position and p.position.upper() not in ("D", "M", "F")]
            if outfield:
                result[outfield[0]] = _replace(result[outfield[0]], position="G")
            else:
                result[-1] = _replace(result[-1], position="G")
    elif len(gk_indices) > 1:
        # Multiple GKs -- keep the first, reclassify the rest as M.
        for idx in gk_indices[1:]:
            result[idx] = _replace(result[idx], position="M")


def _fix_defender_count(result: list, expected_def: int) -> None:
    """Extracted from _validate_lineup_positions to keep its own
    cognitive complexity down (python:S3776); behavior unchanged.

    Mutates result in place."""
    from dataclasses import replace as _replace

    current_def = sum(1 for p in result if p.position and p.position.upper() == "D")
    if current_def == expected_def:
        return

    if current_def > expected_def:
        # Too many defenders -- reclassify the last excess defender as
        # midfielder (the most common misclassification).
        def_indices = [i for i, p in enumerate(result) if p.position and p.position.upper() == "D"]
        for idx in def_indices[expected_def:]:
            result[idx] = _replace(result[idx], position="M")
    elif current_def < expected_def:
        # Too few defenders -- reclassify the midfielder(s) closest to the
        # goalkeeper in list order as defender. Lineups are consistently
        # listed GK -> defenders -> midfielders -> forwards, so an
        # M-tagged player appearing right after the real defenders (i.e.
        # earliest in the M-tagged group) is a much stronger signal of a
        # mistagged defender than one deep in the attacking midfield --
        # confirmed live (Everton vs Man Utd, 2026-09-06): a genuine
        # fullback tagged "M" sat immediately after the goalkeeper while
        # three real attacking midfielders followed later; picking from
        # the end of the M list reclassified one of THOSE instead, the
        # opposite of the intended fix.
        mid_indices = [i for i, p in enumerate(result) if p.position and p.position.upper() == "M"]
        needed = expected_def - current_def
        for idx in mid_indices[:needed]:
            result[idx] = _replace(result[idx], position="D")


def _validate_lineup_positions(lineup: list | None, formation: str | None) -> list | None:
    """Validate that the lineup has a goalkeeper and that the number of
    outfield players marked as 'D' matches the formation's defender count.
    When the formation is known but the lineup's position assignments
    disagree (e.g. 4-2-3-1 formation but only 3 players marked 'D'), or
    the lineup is missing a goalkeeper, reclassify the excess/deficit by
    reassigning the most plausible player. This catches real scraping
    bugs where sofascore's position tags don't match the formation."""
    if not lineup:
        return lineup

    result = list(lineup)
    _fix_missing_or_duplicate_gk(result, formation)

    # --- Defender count check (requires formation) ---
    if not formation:
        return result
    parts = formation.split("-")
    if len(parts) < 2:
        return result
    try:
        expected_def = int(parts[0])
    except (ValueError, IndexError):
        return result

    _fix_defender_count(result, expected_def)
    return result


def reconcile_missing_players(
    missing_players: list[MissingPlayer] | None, profile_injuries: list[SquadMember] | None
) -> list[MissingPlayer] | None:
    """Merges a team-profile's injuries into the match-level missing-
    players list. These are two independently-sourced facts about the
    same team -- match.home/away_missing_players comes from Sofascore's
    match-specific lineups.missingPlayers, while teamProfile.injuries is
    a separate squad-level scrape -- and confirmed live (repeatedly,
    across several reports) that they disagree: Pedro Porro correctly
    flagged in teamProfile.injuries/missing_defenders but silently
    absent from match.away_missing_players, alongside several other
    players in the same situation. Injuries not already present (by
    normalized name) are added using the profile's own injury text as
    the description; expected_return stays None since profile-level
    injuries don't carry that field. Order: existing entries first, then
    newly-added ones, so a consumer already reading the match-level list
    sees no change in what was already there."""
    result = list(missing_players or [])
    known = {normalize_team_name(p.name) for p in result}
    for m in (profile_injuries or []):
        norm = normalize_team_name(m.name)
        if norm not in known:
            result.append(MissingPlayer(name=m.name, description=m.injury, expected_return=None))
            known.add(norm)
    # Preserve confirmed-empty [] (checked, none missing) -- only collapse
    # to None when there was never any list to begin with.
    return result if result else ([] if missing_players is not None else None)


def merge_absences_into_profile_injuries(profile, missing_players: list[MissingPlayer] | None) -> None:
    """One-way mirror of reconcile_missing_players: add match-level
    injury/suspension absences that are missing from teamProfile.injuries
    so the profile's Injuries line and key_injuries list reflect the
    full set. Confirmed live (Germany): match.missing_players had five
    entries (de Jong, Wieffer, Simons, Malen, Timber) while profile
    .injuries only listed two (Malen, Timber) because the two lists are
    independently sourced. Non-injury absences (coach_decision / other)
    are deliberately NOT folded into `injuries` -- they belong on
    non_injury_absences instead. Mutates `profile` in place; no-op when
    either side is empty."""
    if not profile or not missing_players:
        return
    known = {normalize_team_name(m.name) for m in (profile.injuries or [])}
    additions: list[SquadMember] = []
    for p in missing_players:
        if p.absence_type not in ("injury", "suspension"):
            continue
        norm = normalize_team_name(p.name)
        if norm in known:
            continue
        known.add(norm)
        additions.append(
            SquadMember(
                name=p.name, role=None, injury=p.description, age=None, market_value=None,
                season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None,
            )
        )
    if not additions:
        return
    profile.injuries = [*(profile.injuries or []), *additions]
    # Re-rank key_injuries (by market value) over the expanded list so
    # the top-3 line stays honest; non-squad additions have no market
    # value and sort last, which is correct -- we know less about them.
    with_value = [m for m in profile.injuries if m.market_value is not None]
    with_value.sort(key=lambda m: m.market_value or 0.0, reverse=True)
    profile.key_injuries = with_value[:3] if with_value else profile.key_injuries


def absent_name_set(
    missing_players: list[MissingPlayer] | None,
    suspended: list[str] | None,
    injuries: list[SquadMember] | None = None,
) -> set[str]:
    """Normalized names of every player ruled out for THIS fixture:
    match-level missing_players, suspensions, and profile injuries.
    Callers that already ran reconcile_missing_players can omit
    `injuries` (those names are already on missing_players)."""
    names = {normalize_team_name(p.name) for p in (missing_players or [])}
    names.update(normalize_team_name(n) for n in (suspended or []))
    names.update(normalize_team_name(m.name) for m in (injuries or []))
    return names


def filter_absent_players(players: list | None, absent: set[str]) -> list | None:
    """Removes players in `absent` from a published lineup or bench.

    Confirmed live: Sofascore lists injured/missing players on the bench
    AND on match.missingPlayers (and presence marks them "A") -- the two
    contradicted each other in the report. Runs after
    reconcile_missing_players so profile injuries are included.

    Matching is exact-normalized, plus one-directional containment: an
    absent entry that is a substring of the player's normalized name
    (e.g. absent "chido obi" vs player "chido obi-martin"). The reverse
    (player name inside a longer absent entry) is deliberately NOT used
    -- that would drop "Starter" whenever anyone else on the list is
    "Injured Starter". Returns None only when the input was None; an
    all-filtered non-empty list becomes [] (we checked, nobody remains)
    rather than being confused with "never published"."""
    if players is None or not absent:
        return players
    kept = []
    for p in players:
        norm = normalize_team_name(getattr(p, "name", "") or "")
        if not norm or norm in absent:
            if norm:
                continue  # exact match -> absent
            kept.append(p)
            continue
        if any(len(a) >= _MIN_CONTAINMENT_NAME_LEN and a in norm for a in absent):
            continue
        kept.append(p)
    return kept


def apply_deep_recent_meetings(merged: MergedMatch, deep_meetings: list, source: Source, opponent_name: str | None = None) -> None:
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
    rather than being cleared).

    Meetings the deep computation could not detail (older than the raw
    fixtures it can look up) are KEPT from the earlier merge rather than
    dropped -- replacing the whole list previously turned a 3-meeting
    fallback into a single detailed meeting. Same-date entries are taken
    from the deep result; the list is newest-first. When any fallback
    entry survives alongside deep rows, provenance is labelled "mixed" --
    claiming either single source would misattribute the other half of
    the list (confirmed live: newest meeting detailed by Sofascore while
    two older rows still came from Fotmob, labelled wholly "fotmob").

    `opponent_name`, when given, filters leftovers to true H2H rows
    against that opponent and caps the final list at 3 -- the generic
    field-merge can leave non-H2H leftovers (confirmed live: Germany's
    recent_meetings contained Germany vs Australia rows that were never
    against the Netherlands), and deep_meetings + leftovers could
    previously exceed the documented cap of 3."""
    from .team_aliases import same_team

    if not deep_meetings:
        # Deep computation failed or came back empty: leave the earlier
        # merge's fallback (or None) exactly as it was -- filtering here
        # would clobber a fallback list we have no better replacement for
        # (confirmed by test_apply_own_recent_meetings_and_form_tolerates_failures).
        return
    # HeadToHeadMeeting.date is str | None (soccerdesk/fotmob/form-only
    # can omit it); slicing None TypeError-kills the whole team run.
    deep_days = {m.date[:10] for m in deep_meetings if m.date}
    leftovers = [m for m in (merged.recent_meetings or []) if not m.date or m.date[:10] not in deep_days]
    if opponent_name:
        # Keep only true H2H leftovers against this opponent. Rows with
        # neither home_team nor away_team populated (form-only fallbacks
        # that predate the frame fix) can't be judged either way -- keep
        # them rather than silently dropping real history. Confirmed
        # live (Germany): non-H2H leftovers like Germany vs Australia
        # were sitting in recent_meetings for a Germany vs Netherlands
        # fixture because the generic field-merge doesn't know the
        # opponent. Also cap the final list at 3 to match the documented
        # window -- deep_meetings (already [:3]) plus leftovers could
        # previously grow past it.
        filtered = []
        for m in leftovers:
            if not m.home_team and not m.away_team:
                filtered.append(m)
                continue
            if same_team(m.home_team or "", opponent_name) or same_team(m.away_team or "", opponent_name):
                filtered.append(m)
        leftovers = filtered
    merged.recent_meetings = sorted(deep_meetings + leftovers, key=lambda m: m.date or "", reverse=True)[:3]
    if leftovers:
        merged.field_sources["recent_meetings"] = "mixed"
        return
    if source == merged.base_source:
        merged.field_sources.pop("recent_meetings", None)
    else:
        merged.field_sources["recent_meetings"] = source
