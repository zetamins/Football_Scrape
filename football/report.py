"""Builds the two report shapes (JSON and Markdown) from a RunSearchResult
-- both the CLI and any other caller (e.g. a future Android UI) consume the
same shape, computed by the same single code path, so there's no risk of
the two drifting apart. Ported from src/search.ts's buildReportJson/
buildReportMarkdown.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .format_markdown import (
    form_summary_markdown,
    insights_markdown,
    merged_match_markdown,
    merged_profile_markdown,
    venue_details_markdown,
)
from .insights import (
    _MATCH_OUTCOME_ONLY_FIELDS,
    _NOT_STARTED_STATUSES,
    _PREDICTABLE_PREMATCH_FIELDS,
    compute_data_completeness,
    is_empty_value,
)
from .orchestrate import RunSearchResult

# home_score/away_score/*_ht are also outcome-only but are handled
# separately (unconditionally excluded, not status-gated) by
# insights.py's own _COMPLETENESS_EXCLUDE -- not repeated here since this
# set is now shared with compute_data_completeness rather than a local
# copy. JSON pruning is deliberately broader than the completeness
# denominator: it also strips home_lineup/away_lineup/home_bench/
# away_bench/home_formation/away_formation when they're genuinely empty
# (_PREDICTABLE_PREMATCH_FIELDS) -- those fields DO count toward
# completeness (a "predicted" lineup can exist pre-match), but an empty
# `""`/`[]` value still isn't worth showing a consumer of the JSON, same
# cosmetic cleanup as the true outcome-only set.
_JSON_ONLY_OUTCOME_FIELDS = _MATCH_OUTCOME_ONLY_FIELDS | _PREDICTABLE_PREMATCH_FIELDS | {
    "home_score", "away_score", "home_score_ht", "away_score_ht",
}

# Within a LineupPlayer entry, name/position/substitute are pre-match
# identity fields (known once a lineup is announced); everything else is a
# real in-match statistic that cannot exist before kickoff. Only pruned
# when the surrounding match itself is pre-kickoff -- a null here for a
# finished match legitimately means something else (e.g. minutes_played
# stays null, not 0, for an unused substitute).
_LINEUP_PLAYER_OUTCOME_FIELDS = [
    "minutes_played", "goals", "assists", "xg", "xa", "shots",
    "shots_on_target", "tackles", "interceptions", "fouls", "rating", "key_passes",
]
_LINEUP_LIST_FIELDS = ["home_lineup", "away_lineup", "home_bench", "away_bench"]

# set_piece_goals/shotmap_stats are the one pair in _MATCH_OUTCOME_ONLY_
# FIELDS that is_empty_value can never catch: sofascore.py's extraction
# functions deliberately return a zero-filled dataclass, not None, for
# an unplayed match (confirmed live -- {'home': {'corner': 0, ...}, ...}
# survives the generic None/[]/"" check untouched). They need an
# unconditional drop when the match hasn't kicked off, not an emptiness
# check -- the "empty" shape here IS the populated shape.
_ALWAYS_PRUNE_WHEN_UNPLAYED = {"set_piece_goals", "shotmap_stats"}


def _prune_unplayed_match_fields(match_dict: dict[str, Any]) -> dict[str, Any]:
    if match_dict.get("status") not in _NOT_STARTED_STATUSES:
        return match_dict
    for list_field in _LINEUP_LIST_FIELDS:
        for player in match_dict.get(list_field) or []:
            for field in _LINEUP_PLAYER_OUTCOME_FIELDS:
                player.pop(field, None)
    for field in _JSON_ONLY_OUTCOME_FIELDS:
        if field in match_dict and is_empty_value(match_dict[field]):
            del match_dict[field]
    for field in _ALWAYS_PRUNE_WHEN_UNPLAYED:
        match_dict.pop(field, None)
    return match_dict


# Per-item source labels (which single site a specific squad member's
# season stats came from, etc.) -- these still get stripped since they're
# a finer-grained, more invasive level of labeling than what was actually
# requested (per-field provenance for the match/profile merge itself,
# answered by base_source/field_sources below).
_SOURCE_LABEL_KEYS = {"source", "season_stats_source"}


def _strip_source_labels(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_source_labels(v) for k, v in obj.items() if k not in _SOURCE_LABEL_KEYS}
    if isinstance(obj, list):
        return [_strip_source_labels(v) for v in obj]
    return obj


# Which slice of history each family of numbers covers. These genuinely
# differ (season stats and top scorers are current-season-to-date; form
# blocks are trailing match windows), so the same team can legitimately
# show e.g. 60% season possession beside 52% last-20 possession -- this
# says so explicitly instead of leaving consumers to guess.
_DATA_WINDOWS = {
    "team_season_stats": "current season to date (goals, cards, average possession)",
    "top_scorers_and_assists": "current season to date",
    "recent_form_leaders": "last 20 matches",
    "form_by_competition_half_split_venue_split_last20": "last 20 competitive matches (friendlies excluded)",
    "win_rate_points_goals_per_game_over_btts": "last 10 competitive matches",
    "recent_competitions": "last 10 competitive matches plus upcoming fixtures",
    "head_to_head_summary": "all meetings the source records; recent_meetings lists only those found in either team's match history",
}


_PROVENANCE_META_KEYS = {"source", "source_url", "base_source", "field_sources", "team_name", "additional_notes"}


def _with_explicit_provenance(section: dict[str, Any] | None) -> dict[str, Any] | None:
    """Merge bookkeeping only records fields a NON-base source filled in;
    every other populated field silently means "the base source". Spell
    that out so field_sources covers every populated field -- an empty
    field_sources otherwise reads as "no provenance tracked at all"."""
    if not section or not section.get("base_source"):
        return section
    explicit = dict(section.get("field_sources") or {})
    for key, value in section.items():
        if key not in _PROVENANCE_META_KEYS and key not in explicit and not is_empty_value(value):
            explicit[key] = section["base_source"]
    section["field_sources"] = explicit
    return section


def build_report_json(result: RunSearchResult) -> dict[str, Any]:
    match_dict = asdict(result.merged) if result.merged else None
    if match_dict is not None:
        match_dict = _strip_source_labels(_with_explicit_provenance(_prune_unplayed_match_fields(match_dict)))
    return {
        "team": result.team,
        "generatedAt": result.generated_at,
        # Fetch-status per site (fixtures scraped, errors) -- kept as
        # operational health information, distinct from data provenance:
        # this says whether a source responded at all, not which source
        # filled which field in the data below.
        "sources": [asdict(s) for s in result.statuses],
        "match": match_dict,
        "venueDetails": (_strip_source_labels(asdict(result.venue_details)) if result.venue_details else None),
        "form": (_strip_source_labels(asdict(result.form)) if result.form else None),
        "opponentForm": (_strip_source_labels(asdict(result.opponent_form)) if result.opponent_form else None),
        "teamProfile": (_strip_source_labels(_with_explicit_provenance(asdict(result.merged_profile))) if result.merged_profile else None),
        "opponentProfile": (_strip_source_labels(_with_explicit_provenance(asdict(result.opponent_profile))) if result.opponent_profile else None),
        "insights": (_strip_source_labels(asdict(result.insights)) if result.insights else None),
        # Same computation the Markdown report's trailing "X/Y fields
        # populated" line already used -- previously computed for
        # Markdown only and never included in the JSON output at all.
        # None when there's no upcoming match at all (compute_data_
        # completeness needs a real MatchDetails to score against).
        "dataCompleteness": (compute_data_completeness(result.merged, result.insights) if result.merged else None),
        "dataWindows": _DATA_WINDOWS,
        "calibration": (asdict(result.calibration) if result.calibration else None),
    }


def _append_match_sections(result: RunSearchResult, lines: list[str]) -> None:
    """Everything build_report_markdown appends once an upcoming match is
    known -- extracted purely to keep that function's own cognitive
    complexity down (python:S3776); behavior unchanged."""
    lines.append("## Next match")
    lines.append("")
    merged_match_markdown(result.merged, lines)
    if result.venue_details:
        venue_details_markdown(result.venue_details, lines)
    if result.form and result.form_source:
        lines.append("")
        lines.append("## Form")
        lines.append("")
        form_summary_markdown(result.form, lines)
    if result.opponent_form and result.opponent_name:
        lines.append("")
        lines.append(f"## {result.opponent_name} form")
        lines.append("")
        form_summary_markdown(result.opponent_form, lines)
    if result.merged_profile:
        merged_profile_markdown(result.merged_profile, lines)
    if result.opponent_profile:
        merged_profile_markdown(result.opponent_profile, lines)
    if result.insights:
        insights_markdown(result.insights, result.merged.home_team, result.merged.away_team, lines)
    completeness = compute_data_completeness(result.merged, result.insights)
    lines.append("")
    lines.append(f"**Data completeness:** {completeness['populated']}/{completeness['total']} fields populated this run")


def build_report_markdown(result: RunSearchResult) -> str:
    lines: list[str] = [f"# {result.team} — full match report", "", f"_Generated {result.generated_at}_", "", "## Sources", ""]
    for s in result.statuses:
        issues = [i for i in (s.matches_error, s.details_error, s.profile_error) if i]
        lines.append(f"- {s.source}: {s.fixtures_scraped} fixtures" + (f" -- {'; '.join(issues)}" if issues else ""))
    lines.append("")

    if result.merged:
        _append_match_sections(result, lines)
    else:
        lines.append("No upcoming match found from any source.")

    return "\n".join(lines) + "\n"
