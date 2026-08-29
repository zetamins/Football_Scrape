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
from .insights import compute_data_completeness
from .orchestrate import RunSearchResult

# Statuses that unambiguously mean "hasn't kicked off yet" across every
# source's own vocabulary (Sofascore: notstarted, Fotmob/Goal/SoccerDesk/
# 365Scores: scheduled). Deliberately narrow -- "live"/"inprogress",
# "postponed", "cancelled", "unknown", etc. are excluded because those
# matches can genuinely have partial real data (a live score, published
# lineups, an abandoned match's final stats), so only the two clearly
# pre-kickoff values are treated as "definitely no match-outcome data yet".
_NOT_STARTED_STATUSES = {"notstarted", "scheduled"}

# Fields on MatchDetails that can only be known during or after the match
# itself (never a pre-match fixture property) -- omitted from the JSON
# entirely, rather than serialized as null, when the match hasn't kicked
# off yet AND the field actually came back empty. Never removed if a field
# happens to be populated (e.g. an early-confirmed lineup published close
# to kickoff) -- this only prunes genuinely-nonexistent-yet data, it never
# discards real data based on status alone.
_MATCH_OUTCOME_ONLY_FIELDS = [
    "home_score", "away_score", "home_score_ht", "away_score_ht",
    "attendance", "home_lineup", "away_lineup", "home_bench", "away_bench",
    "home_formation", "away_formation", "match_stats", "event_timeline",
    "player_of_the_match",
]

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


def _is_empty_value(value: Any) -> bool:
    return value is None or value == []


def _prune_unplayed_match_fields(match_dict: dict[str, Any]) -> dict[str, Any]:
    if match_dict.get("status") not in _NOT_STARTED_STATUSES:
        return match_dict
    for list_field in _LINEUP_LIST_FIELDS:
        for player in match_dict.get(list_field) or []:
            for field in _LINEUP_PLAYER_OUTCOME_FIELDS:
                player.pop(field, None)
    for field in _MATCH_OUTCOME_ONLY_FIELDS:
        if field in match_dict and _is_empty_value(match_dict[field]):
            del match_dict[field]
    return match_dict


# Every key name, anywhere in the output, that classifies a piece of data
# by which of the 5 scraped sites it came from. The underlying merge/
# fallback logic (merge.py) still needs these internally to route deep
# per-source enrichment correctly -- this only controls what a consumer
# of the JSON/markdown sees, not how the data was actually assembled.
_SOURCE_LABEL_KEYS = {"source", "base_source", "field_sources", "season_stats_source"}


def _strip_source_labels(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_source_labels(v) for k, v in obj.items() if k not in _SOURCE_LABEL_KEYS}
    if isinstance(obj, list):
        return [_strip_source_labels(v) for v in obj]
    return obj


def build_report_json(result: RunSearchResult) -> dict[str, Any]:
    match_dict = asdict(result.merged) if result.merged else None
    if match_dict is not None:
        match_dict = _strip_source_labels(_prune_unplayed_match_fields(match_dict))
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
        "teamProfile": (_strip_source_labels(asdict(result.merged_profile)) if result.merged_profile else None),
        "opponentProfile": (_strip_source_labels(asdict(result.opponent_profile)) if result.opponent_profile else None),
        "insights": (_strip_source_labels(asdict(result.insights)) if result.insights else None),
    }


def build_report_markdown(result: RunSearchResult) -> str:
    lines: list[str] = [f"# {result.team} — full match report", "", f"_Generated {result.generated_at}_", "", "## Sources", ""]
    for s in result.statuses:
        issues = [i for i in (s.matches_error, s.details_error, s.profile_error) if i]
        lines.append(f"- {s.source}: {s.fixtures_scraped} fixtures" + (f" -- {'; '.join(issues)}" if issues else ""))
    lines.append("")

    if result.merged:
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
    else:
        lines.append("No upcoming match found from any source.")

    return "\n".join(lines) + "\n"
