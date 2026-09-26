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
    source_conflicts_markdown,
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
# says so explicitly instead of leaving consumers to guess. Field-level
# entries name individual JSON keys that sit inside a section whose own
# description is too coarse to cover them (e.g. possession cross-check
# lives beside season goals under match.*_team_season_stats).
_DATA_WINDOWS = {
    "team_season_stats": "current season to date (goals, cards, average possession)",
    "team_season_stats.average_ball_possession": (
        "season to date from the source; when possession_venue_split_check diverges by >5pp this becomes the "
        "last-20 venue-split figure and the original is kept in average_ball_possession_source_season"
    ),
    "team_season_stats.possession_venue_split_check": "last 20 competitive matches, n-weighted venue-split possession",
    "team_season_stats.possession_window_note": (
        "explains which window average_ball_possession currently represents (season-to-date vs last-20 "
        "venue-split) and why the swap did or did not happen"
    ),
    "team_season_stats.clean_sheets_recent_check": (
        "last 20 competitive matches (friendlies excluded); clean_sheets_recent_check_sample_size is how many "
        "competitive results in that window fed the count"
    ),
    "top_scorers_and_assists": "current season to date (top_scorers/top_assists rows also carry window=\"season_to_date\")",
    "recent_form_leaders": "last 20 matches (rows also carry window=\"last_20\")",
    "squad_season_stats": (
        "current season to date (squad[].season_stats -- goals/assists/cards/rating); individual rows are null "
        "for players the source publishes no season line for (no appearances this season, not in the "
        "source's stat coverage) -- a null row inside an otherwise populated list is normal, not a partial fetch"
    ),
    "squad_recent_usage": (
        "last 20 matches with lineup/stats detail (squad[].recent_usage -- totals and per-90); individual rows "
        "are null for players with no read appearances in that window (new signing, unused keeper) -- a null "
        "row inside an otherwise populated list is normal, not a partial fetch"
    ),
    "squad.stat_window_note": (
        "set when season_stats.goals and recent_usage.total_goals disagree for a player "
        "(e.g. Gallagher 1 season vs 2 recent) -- names both windows and both values"
    ),
    "squad[].shirt_number": (
        "as listed by Sofascore's season roster endpoint; national-team lists can carry the same number on "
        "different players (observed live: #1 on 4 players, #7 and #10 on 5 each) -- treat it as informational, "
        "not a unique matchday kit number; the same player can legitimately show a different number in "
        "home_lineup/away_lineup (matchday kit published on the fixture) than here (season roster) -- the two "
        "are NOT reconciled against each other, never corrected from either side"
    ),
    "form_by_competition": "last 20 competitive matches (friendlies excluded)",
    "form_by_competition_half_split_venue_split_last20": "last 20 competitive matches (friendlies excluded)",
    "win_rate_points_goals_per_game_over_btts": "last 10 competitive matches",
    "recent_competitions": "last 10 competitive matches plus upcoming fixtures",
    "head_to_head_summary": (
        "all meetings the source records (aggregate sample_size); recent_meetings lists only the "
        "up-to-3 H2H meetings found in either team's recent match history -- the two counts differ by design; "
        "home_wins/away_wins/draws count from the SOURCE'S bracket for the fixture (its duel frame, with the "
        "searched team typically listed first), NOT from a verified stadium home/away -- a neutral-venue "
        "meeting still lands in one of the two win buckets"
    ),
    "recent_meetings": (
        "capped at 3 most recent H2H fixtures found in either team's form window; non-H2H leftovers "
        "from earlier merges are filtered out when the opponent is known; "
        "not the full head_to_head_summary.sample_size; venue is the searched-team form frame "
        "(home/away relative to the requested team's perspective as the source recorded it) and is NOT "
        "verified against the stadium -- 'neutral' appears only when the source publishes the venue country "
        "AND both team countries (Sofascore-only fields), so meetings fetched from other sources can show "
        "'home'/'away' for a genuinely neutral match; per-meeting detail (lineups, formations, xG) exists only "
        "for meetings whose own event page was fetched -- typically the most recent one -- so a meeting with "
        "null lineups is expected, not a broken record"
    ),
    "insights.home_corners_estimate": (
        "Goal.com Corner total summed over that team's own last finished matches with the stat present "
        "(independent per side; equal home/away totals are coincidence, not a shared total)"
    ),
    "insights.away_corners_estimate": (
        "Goal.com Corner total summed over that team's own last finished matches with the stat present "
        "(independent per side; equal home/away totals are coincidence, not a shared total)"
    ),
    "insights.home_advanced_stats": (
        "form-source detail window (typically last N matched fixtures); its corners_for is a DIFFERENT "
        "series from insights.*_corners_estimate (Goal.com Corner total) -- they can legitimately disagree; "
        "partial_stats (when present) maps each stat summed over FEWER than sample_size matches to its own n "
        "-- those totals understate the full window (unavailable_stats covers stats absent from every match); "
        "AFTER reading the two rules above: a stat published in SOME window matches stays POPULATED as a "
        "partial total (its n in partial_stats), while a stat absent from EVERY match is null + listed in "
        "unavailable_stats -- so the same stat can be populated on one side and null on the other, and any "
        "partial total must be read as 'n of sample_size', never as a full-window total"
    ),
    "insights.away_advanced_stats": (
        "form-source detail window (typically last N matched fixtures); its corners_for is a DIFFERENT "
        "series from insights.*_corners_estimate (Goal.com Corner total) -- they can legitimately disagree; "
        "partial_stats (when present) maps each stat summed over FEWER than sample_size matches to its own n "
        "-- those totals understate the full window (unavailable_stats covers stats absent from every match); "
        "AFTER reading the two rules above: a stat published in SOME window matches stays POPULATED as a "
        "partial total (its n in partial_stats), while a stat absent from EVERY match is null + listed in "
        "unavailable_stats -- so the same stat can be populated on one side and null on the other, and any "
        "partial total must be read as 'n of sample_size', never as a full-window total"
    ),
    "insights.sample_size_windows": (
        "the several independent 'last N' windows behind the home/away estimates are NOT shared -- a side can "
        "legitimately show different n on adjacent rows: advanced_stats = form-source detail window (often the "
        "side's last 5 matched fixtures), xg/shots estimates = that side's own last finished fotmob matches "
        "counting only where the stat published (can be 6 of 10), corners_estimate = that side's own last "
        "finished goal.com matches with a Corner total (can be 10). Compare sample sizes WITHIN one estimate "
        "family, not across families; each object's own sample_size (or partial_stats per-stat n) is authoritative"
    ),
    "insights.home_defensive_errors_estimate": (
        "Goal.com Defensive error stat summed over that side's own last finished matches with the stat "
        "present; null means no match in that window published the stat (not zero errors)"
    ),
    "insights.away_defensive_errors_estimate": (
        "Goal.com Defensive error stat summed over that side's own last finished matches with the stat "
        "present; null means no match in that window published the stat (not zero errors)"
    ),
    "insights.corners_cross_source_note": (
        "set only when a side's corners_for disagrees between insights.*_advanced_stats and "
        "insights.*_corners_estimate -- names both values and windows; null when they agree"
    ),
    "insights.home/away_*_estimate": (
        "estimate/flag family (xg, shots, aerial, big_chances, passing_style, fouls, goalkeeping, "
        "possession_matchup, card_discipline_venue_split, set_piece_threat, direct_play_exposure): each side is "
        "computed INDEPENDENTLY from its own recent-match stat windows (the opponent's fixtures are fetched "
        "separately); null for one side means those opponent windows carried no usable per-match stats -- common "
        "for national-team fixtures -- NOT 'zero', and the other side can be fully populated at the same time"
    ),
    "insights.home_advantage": (
        "strength label withheld when either side's win-rate sample is <3 matches (rates and gap still reported; "
        "home_sample_size/away_sample_size show why the label is absent) -- sample floor added after an n=1 "
        "'strong' label shipped"
    ),
    "insights.away_advantage": (
        "strength label withheld when either side's win-rate sample is <3 matches (rates and gap still reported; "
        "home_sample_size/away_sample_size show why the label is absent) -- sample floor added after an n=1 "
        "'strong' label shipped"
    ),
    "insights.home/away_standings_zone": (
        "position within the standings table classified against spot counts clamped to that table's size "
        "(top spot = min(league continental spots, (total_teams-1)//2), same for relegation) -- so a 4-team "
        "group table yields 1 spot per side (1st top-of-table, 2nd-3rd midtable, last relegation-zone) instead "
        "of labelling every position <=4 top-of-table; points_from_boundary is the closest gap to either "
        "clamped boundary"
    ),
    "teamProfile.missing_attackers": (
        "teamProfile.injuries by role PLUS match-level missing_players not in injuries "
        "(e.g. coach_decision) -- non-injury absences can appear here without appearing under injuries"
    ),
    "teamProfile.non_injury_absences": (
        "names on missing_*_role that are NOT in teamProfile.injuries -- explicit set-difference so "
        "a coach_decision player doesn't have to be re-derived from two lists"
    ),
    "match.away_missing_players.absence_type": (
        "injury / suspension / coach_decision / other -- coach_decision is a non-injury absence "
        "(not in teamProfile.injuries; expected_return forced null)"
    ),
    "match.home_missing_players": (
        "Sofascore match-specific missingPlayers reconciled both ways with teamProfile.injuries: "
        "profile injuries are folded into the match list, and match injury/suspension absences are "
        "folded back into teamProfile.injuries so both lists see the same set"
    ),
    "match.source_conflicts": (
        "cross-source disagreements reported (not overridden) -- always rendered in markdown even "
        "when venueDetails is null (StadiumDB cannot resolve national-team venues)"
    ),
    "teamProfile.injuries": (
        "union of teamProfile scrape injuries and match-level missingPlayers with absence_type "
        "in injury/suspension (non-injury absences like coach_decision stay on non_injury_absences only)"
    ),
    "match.*_team_standing.goal_diff": (
        "canonical display form, signed iff nonzero ('+8'/'-9'/'0'), derived once from whichever source filled "
        "the standing -- Sofascore already publishes it this way, other sources vary (goal.com unsigned '15', "
        "soccerdesk signed '+8'); the string is never rendered '+' before 0, and goal_difference is its int twin"
    ),
    "match.head_to_head_streaks": (
        "Sofascore event team-streaks endpoint, head2head items only ('No losses (home): 7'); the source "
        "publishes no streak set for some fixtures -- even the same fixture across runs -- so null/missing "
        "means 'source published none this run', not 'no streaks exist'"
    ),
    "match.manager_duel": (
        "Sofascore h2h managerDuel: W/D/L the two managers' sides have against each other, published by the "
        "source only when both managers carry such history -- null is a source gap; distinct from "
        "match.home/away_manager_vs_*_club, which WE compute ourselves"
    ),
    "match.home/away_manager_vs_*_club": (
        "WE scan that manager's own sofascore event history for finished matches against the named opponent; "
        "sample_size 0 means scanned and zero prior meetings found (an honest value -- 'never looked' would be "
        "null); markdown hides zero-sample records, JSON keeps them; the two directions are independent"
    ),
    "match.betting_odds": (
        "football-data.co.uk upcoming-fixtures CSV cross-bookmaker Avg prices, tracked club leagues only -- a "
        "national-team fixture isn't in that file, so null here; sofascore's own single-book prices are always "
        "carried separately in sofascore_betting_odds and feed the prediction either way; BOTH sources are "
        "routinely absent this far from kickoff (the CSV only lists fixtures it has published, sofascore odds "
        "appear closer to the match), so a pre-match report weeks ahead commonly has no market odds at all -- "
        "prediction.market_implied is then null and confidence falls back to model methods only"
    ),
    "match.sofascore_betting_odds": (
        "sofascore's own single-book 1X2/OU prices for this fixture (deliberately kept separate from betting_odds' "
        "cross-bookmaker Avg so a single book is never mistaken for a market average); published only close to "
        "kickoff -- null weeks ahead is normal availability, not a fetch failure"
    ),
    "match.referee": (
        "appointed referee for THIS fixture: filled from football-data.co.uk's upcoming-fixture row (its "
        "Referee column) or the sofascore event page -- both lag far-from-kickoff fixtures, so null here means "
        "neither has published the appointment yet, not that the match has no referee"
    ),
    "match.referee_stats": (
        "aggregate of that referee's recent matches -- computed only when match.referee is named, so it is null "
        "whenever referee is null (one root cause, two null fields)"
    ),
    "match.referee_card_risk_note": (
        "needs match.referee PLUS card-risk data to say anything about this referee's card habits -- null "
        "whenever referee is null"
    ),
    "match.weather_detail": (
        "structured wttr.in forecast (temp/humidity/wind/gust/cloud/precip) is fetched ONLY within 2 days of "
        "kickoff -- wttr.in's forecast horizon; further out weather_detail is null while the plain source "
        "weather string (fotmob/sofascore) remains, which is why a report can show weather='Few Showers, 15C' "
        "with no detail block beside it; inside the window the detail is kickoff-hour matched and its "
        "description overwrites the source string (field_source becomes wttr.in)"
    ),
    "match.home_formation": (
        "formation beside a lineup only when a lineup can carry it: absent from the JSON entirely (not null) "
        "when empty on an unplayed match -- same cosmetic prune as lineups/bench -- and cleared when the XI "
        "is OUR derived projection (a formation orphaned from the real XI is untrustworthy); still counted in "
        "dataCompleteness.missing while absent"
    ),
    "match.away_formation": (
        "formation beside a lineup only when a lineup can carry it: absent from the JSON entirely (not null) "
        "when empty on an unplayed match -- same cosmetic prune as lineups/bench -- and cleared when the XI "
        "is OUR derived projection (a formation orphaned from the real XI is untrustworthy); still counted in "
        "dataCompleteness.missing while absent"
    ),
    "match.lineup_confirmed": (
        "false = a source published an XI but hasn't confirmed it; null = NO source lineup exists to confirm "
        "(a derived XI has nothing to confirm) -- present-with-null while the formation keys above are "
        "pruned-when-empty, an intentional asymmetry between an outcome flag and a display field"
    ),
    "match.*_team_venue_lat/lon": (
        "each side's OWN published home-venue coordinates (club sides carry one; national teams have no club "
        "venue) -- distinct from match.venue_lat/lon, which is the fixture's venue"
    ),
    "insights.*_opponent_rank_record": (
        "same-competition results against opponents ranked ABOVE this side in the CURRENT standings (no source "
        "publishes point-in-time tables) -- null when zero results qualify, e.g. early in a group before any "
        "match vs a higher-ranked opponent; that is a checked zero, not a lookup failure"
    ),
    "insights.*_club_strength": (
        "statsultra 480-club strength table matched by team name -- national teams can't match a club row, so "
        "both sides are null together; per-side best-effort even for clubs (uncovered league -> null)"
    ),
    "insights.*_fullback_exposure": (
        "from that side's squad per-player defensive stats (chances created vs own-team median, ground-duel "
        "rate); null = no squad or fewer than 2 defenders with the needed stats (baseline not computable), "
        "while a real empty list = checked, nobody exposed and counts as populated"
    ),
    "teamProfile.recent_transfers": (
        "source transfer lists unioned across profiles (club sides populate them); national-team call-ups are "
        "not transfer records, so both profiles are null together -- not a lookup failure"
    ),
    "home/away_manager": (
        "name/country from the match source; appointed_date, previous_manager, recent_appointment, "
        "record_at_club and age are filled only when a Wikipedia tenure row resolves for THAT manager -- one "
        "side populated and the other null is coverage asymmetry, both sides run the same enrichment"
    ),
    "venueDetails": (
        "StadiumDB venue details (stadium, capacity, coordinates context); it cannot resolve national-team "
        "venues, so null for national-team fixtures -- see also match.source_conflicts; record_attendance is "
        "the stadium's documented record crowd and is null whenever StadiumDB doesn't publish one; "
        "venueDetails fields are NOT part of the dataCompleteness denominator (which scores MatchDetails + "
        "MatchInsights only), so a null here never appears in dataCompleteness.missing"
    ),
    "insights.*_presence": (
        "availability rows computed from SOURCE-published lineups/bench/injuries at step 1-2 time: starting = "
        "a source named him in its XI, on_bench = a source published him on its bench. When the final "
        "match.home_lineup/home_bench are OUR derived lists (field_sources='derived'), starting stays false "
        "and on_bench null on purpose -- projected_starter is the flag that marks our own XI, so the two "
        "objects never disagree about WHO said what: presence reports source knowledge, projected_starter "
        "reports our projection"
    ),
    "insights.* reference frames (own vs home/away)": (
        "two conventions coexist: keys using own_/opponent_ (rest_comparison.own_rest_days, "
        "experience_comparison, fatigue_flag) are REPORT-TEAM-relative (own = the searched team, here "
        "Tottenham, wherever the fixture lists them), while keys using home_/away_ (home_advantage, "
        "rest/experience fields named home_* or away_*) are FIXTURE-relative (home = match.home_team, the "
        "side listed first -- the OPPONENT when the searched team plays away); each key follows its own "
        "name consistently, but the file never mixes them inside one object"
    ),
    "insights.projected_xi_basis": (
        "the exact selection rule behind a derived XI: one goalkeeper plus the ten AVAILABLE outfield players "
        "with the most starts in recent matches whose lineups were read, ties broken by total minutes played "
        "in those matches (so a 4-way tie at 2 starts is decided by minutes: 193>192>181>173 picks the top "
        "two); no position balance is enforced -- it reflects who has actually been starting"
    ),
    "lineups": (
        "home_lineup/away_lineup come from a named source when field_sources says so (Sofascore publishes an "
        "unconfirmed XI days ahead; lineup_confirmed stays false until a source confirms it -- or null when NO "
        "source lineup exists to confirm at all, see match.lineup_confirmed) or 'derived' when no "
        "source published one; a source-published XI is shown exactly AS PUBLISHED -- players with few or zero "
        "starts appear because the SOURCE named them, never from starts-based ranking (that ranking exists only "
        "in projected_xi_basis); home_bench/away_bench='derived' means no source publishes a bench (projected from "
        "the published XI minus absences, with shirt numbers that collide with another XI+bench member blanked -- "
        "stale squad numbering); duplicate shirt numbers across the full squad list are expected for national teams "
        "(players keep club numbers between camps) and are not matchday numbers; lineup shirt_number is the "
        "matchday kit published on the fixture and can differ from the same player's squad[].shirt_number (season "
        "roster) -- a known, documented source-window mismatch, neither side corrected from the other; "
        "projected_xi_basis is set only "
        "when WE project the XI from starts data and is intentionally absent -- and not counted missing -- "
        "whenever a real source lineup exists"
    ),
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
        venue_details_markdown(result.venue_details, lines, result.merged.source_conflicts if result.merged else None)
    # Always render source_conflicts when present, even if venueDetails
    # failed to resolve (StadiumDB looks up by club name and cannot find
    # national teams) -- otherwise a wrong-fixture venue_city/country
    # conflict is silently invisible in the markdown.
    if result.merged and result.merged.source_conflicts:
        source_conflicts_markdown(result.merged.source_conflicts, lines)
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
    lines.append(f"_Denominator basis:_ {completeness['denominator']}")
    if completeness.get("outcome_fields_excluded_pre_match"):
        lines.append(
            f"_Excluded from this total (cannot exist before kickoff):_ "
            f"{', '.join(completeness['outcome_fields_excluded_pre_match'])}"
        )
    if result.calibration:
        lines.append("")
        lines.append(f"**Calibration:** {result.calibration.evaluated} evaluated, {result.calibration.pending} pending -- {result.calibration.note}")


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
