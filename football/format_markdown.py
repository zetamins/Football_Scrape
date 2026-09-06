"""Human-readable markdown rendering for a merged match/profile/insights
result. Ported from src/search.ts's `*Markdown` functions.

The TS original also had a parallel `print*` family (identical logic,
`console.log` instead of `lines.push`) for the CLI's terminal output. That
duplication added no information -- consolidated here to one markdown-line
builder; the CLI (cli.py) prints these same lines directly.
"""

from __future__ import annotations

from ._jsmath import js_number_to_string
from .form import format_when
from .merge import (
    RecentFormLeader,
    RoleFormEntry,
    compute_bench_regulars,
    compute_recent_form_leaders,
    compute_role_form_breakdown,
    compute_top_defenders,
    compute_top_performers,
    is_defender_role,
    is_midfield_role,
)
from .team_name_match import (
    slugify_for_match as slugify,  # noqa: F401  # re-exported for cli.py's `from .format_markdown import slugify`
)
from .types import (
    CardDisciplineInfo,
    CardDisciplineVenueSplit,
    ClubStrengthRating,
    CompetitionFormRecord,
    DetailedVenueSplitForm,
    DirectPlayExposureFlag,
    DuelVulnerability,
    EloRating,
    ExperienceH2HNote,
    FatigueFlag,
    FormResult,
    FormSummary,
    FullbackExposureInfo,
    HalfSplitStats,
    HeadToHeadMeeting,
    HomeAdvantageInfo,
    LosingStreakContextInfo,
    ManagerInfo,
    MatchInsights,
    OpponentRankRecord,
    PlayerCardRisk,
    PossessionMatchupInfo,
    PresenceEntry,
    RefereeCardRiskNote,
    RefereeStats,
    ResilienceInfo,
    RestPerformanceInfo,
    RotationInfo,
    SeasonAdvancedStatsEstimate,
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
    StandingsImpactInfo,
    StandingsZoneInfo,
    StreakStabilityInfo,
    TransferRecord,
    TravelInfo,
    VenueDetails,
    VenueSplitForm,
    VenueSplitStats,
)


def transfer_str(t: TransferRecord) -> str:
    """Sofascore's transfers endpoint spans multiple transfer windows (not
    just "recent"), pre-sorted most-recent-first -- the date is included
    here specifically so two entries for the same player read as distinct
    dated events, not duplicates."""
    date = f" on {t.date[:10]}" if t.date else ""
    club = f", {t.from_club} -> {t.to_club}" if (t.from_club and t.to_club) else ""
    return f"{t.player_name} ({t.direction}{club}{date})"


def form_result_str(r: FormResult) -> str:
    ht = f" (HT {r.ht_scoreline})" if r.ht_scoreline else ""
    xg = f" (xG {js_number_to_string(r.xg_for)}-{js_number_to_string(r.xg_against)})" if r.xg_for is not None and r.xg_against is not None else ""
    narrow = " (narrow)" if r.margin == 1 else ""
    return f"{r.result} {r.scoreline}{ht}{xg} vs {r.opponent}{narrow}"


def meeting_str(m: HeadToHeadMeeting) -> str:
    xg = f", xG {js_number_to_string(m.home_xg)}-{js_number_to_string(m.away_xg)}" if m.home_xg is not None and m.away_xg is not None else ""
    formations = f" ({m.home_formation} v {m.away_formation})" if m.home_formation and m.away_formation else ""
    date = m.date[:10] if m.date else "?"
    return f"{date} {m.scoreline}{formations}{xg}"


def half_split_str(h: HalfSplitStats) -> str:
    return f"1H {h.first_half_goals_for}-{h.first_half_goals_against}, 2H {h.second_half_goals_for}-{h.second_half_goals_against} (n={h.sample_size})"


def competition_form_str(c: CompetitionFormRecord) -> str:
    return f"{c.competition} {c.wins}W-{c.draws}D-{c.losses}L, {c.goals_for}-{c.goals_against} goals"


def venue_split_form_str(v: VenueSplitForm) -> str:
    return (
        f"home {v.home_wins}W-{v.home_draws}D-{v.home_losses}L, {v.home_goals_for}-{v.home_goals_against} goals (n={v.home_sample_size}) / "
        f"away {v.away_wins}W-{v.away_draws}D-{v.away_losses}L, {v.away_goals_for}-{v.away_goals_against} goals (n={v.away_sample_size}) / "
        f"neutral {v.neutral_wins}W-{v.neutral_draws}D-{v.neutral_losses}L, {v.neutral_goals_for}-{v.neutral_goals_against} goals (n={v.neutral_sample_size})"
    )


def venue_bucket_str(b: VenueSplitStats) -> str:
    """"/g" (per-game) suffix throughout -- these are team box-score sums
    over N matches, not per-player minutes, so "per game" and "per 90" are
    the same number for a normal 90-minute match."""
    if not b.sample_size:
        return "n=0"

    def per(n: float) -> str:
        return f"{n / b.sample_size:.1f}"

    poss = b.possession_pct_avg if b.possession_pct_avg is not None else "n/a"
    return (
        f"xG {per(b.xg_for)}-{per(b.xg_against)}/g, shots {per(b.shots_for)}-{per(b.shots_against)}/g "
        f"({per(b.shots_on_target_for)}-{per(b.shots_on_target_against)} on target), poss {poss}%, "
        f"corners {per(b.corners_for)}-{per(b.corners_against)}/g, fouls {per(b.fouls_for)}-{per(b.fouls_against)}/g, "
        f"cards {per(b.yellow_cards_for)}Y/{per(b.red_cards_for)}R-{per(b.yellow_cards_against)}Y/{per(b.red_cards_against)}R, "
        f"big chances {per(b.big_chances_created_for)}-{per(b.big_chances_created_against)}/g (n={b.sample_size})"
    )


def detailed_venue_split_str(d: DetailedVenueSplitForm) -> str:
    return f"home: {venue_bucket_str(d.home)} | away: {venue_bucket_str(d.away)} | neutral: {venue_bucket_str(d.neutral)}"


def _append_form_recent_results(f: FormSummary, lines: list[str]) -> None:
    """First third of form_summary_markdown -- extracted purely to keep
    that function's own cognitive complexity down (python:S3776); each
    block is independent (its own `if`, appending to the same shared
    `lines`), so splitting doesn't change what's appended or in what
    order. Behavior unchanged."""
    if f.last5_overall:
        lines.append(f"- Last 5 (all): {', '.join(form_result_str(r) for r in f.last5_overall)}")
    with_ht = [r for r in f.last20_overall if r.ht_scoreline]
    if with_ht:
        lines.append(f"- With HT score: {', '.join(form_result_str(r) for r in with_ht)}")
    if f.last5_home:
        lines.append(f"- Last 5 (home): {', '.join(form_result_str(r) for r in f.last5_home)}")
    if f.last5_away:
        lines.append(f"- Last 5 (away): {', '.join(form_result_str(r) for r in f.last5_away)}")
    if f.next5_with_gaps:
        parts = [f"{format_when(g.date)} vs {g.opponent}" + (f" (+{g.days_since_previous}d rest)" if g.days_since_previous is not None else "") for g in f.next5_with_gaps]
        lines.append(f"- Next 5: {' | '.join(parts)}")
    if f.gaps_between_last_three:
        lines.append(f"- Gaps between last 3 matches: {', '.join(str(g) for g in f.gaps_between_last_three)} days")
    if f.half_split:
        lines.append(f"- Half split: {half_split_str(f.half_split)}")
    if len(f.recent_competitions) > 1:
        lines.append(f"- Competitions played recently: {' | '.join(f.recent_competitions)} ({len(f.recent_competitions)})")
    if f.current_streak:
        if f.current_streak.result == "W":
            word = "winning"
        elif f.current_streak.result == "L":
            word = "losing"
        else:
            word = "drawing"
        lines.append(f"- Streak: {f.current_streak.count}-game {word} streak")


def _append_form_rates(f: FormSummary, lines: list[str]) -> None:
    """Second third of form_summary_markdown, itself split in two --
    see _append_form_recent_results' docstring for why this split is
    safe, and _append_form_rates_streaks_and_splits below for the rest."""
    if f.home_win_rate_pct is not None or f.away_win_rate_pct is not None:
        lines.append(f"- Win rate: Home {f.home_win_rate_pct if f.home_win_rate_pct is not None else 'n/a'}% / Away {f.away_win_rate_pct if f.away_win_rate_pct is not None else 'n/a'}%")
    if f.momentum:
        lines.append(f"- Momentum: {js_number_to_string(f.momentum.recent_ppg)} ppg (last 3) vs {js_number_to_string(f.momentum.prior_ppg)} ppg (prior 3) -- {f.momentum.trend}")
    if f.narrow_win_share_pct is not None:
        lines.append(f"- Narrow wins: {f.narrow_win_share_pct}% of last 10 wins were tight and low-scoring (1-0, 2-1 style)")
    if f.scoring_draw_share_pct is not None:
        lines.append(f"- Scoring draws: {f.scoring_draw_share_pct}% of last 10 draws weren't 0-0")
    if f.btts_share_pct is not None:
        lines.append(f"- BTTS: {f.btts_share_pct}% of last 10 played matches had both teams scoring")
    _append_form_rates_streaks_and_splits(f, lines)


def _append_form_rates_streaks_and_splits(f: FormSummary, lines: list[str]) -> None:
    """Second half of _append_form_rates -- see its own docstring."""
    if f.clean_sheet_streak is not None and f.clean_sheet_streak >= 2:
        lines.append(f"- Clean sheets: {f.clean_sheet_streak}-game clean sheet streak")
    if f.scoreless_streak is not None and f.scoreless_streak >= 2:
        lines.append(f"- Scoreless: {f.scoreless_streak}-game scoreless streak")
    if f.over25_share_pct is not None:
        lines.append(f"- Over/Under (last 10): O1.5 {f.over15_share_pct}% / O2.5 {f.over25_share_pct}% / O3.5 {f.over35_share_pct}%")
    if f.clean_sheet_share_pct is not None:
        lines.append(f"- Clean sheet / failed-to-score rate (last 10): {f.clean_sheet_share_pct}% / {f.failed_to_score_share_pct}%")
    if len(f.form_by_competition) > 1:
        lines.append(f"- Form by competition: {' | '.join(competition_form_str(c) for c in f.form_by_competition)}")


def _append_form_venue_splits(f: FormSummary, lines: list[str]) -> None:
    """Final third of form_summary_markdown -- see
    _append_form_recent_results' docstring for why this split is safe."""
    lines.append(f"- Fixture congestion: {f.matches_last7_days} matches in last 7 days, {f.matches_last14_days} in last 14 days")
    if f.win_rate_pct is not None:
        lines.append(f"- Rates (last 10): W{f.win_rate_pct}%/D{f.draw_rate_pct}%/L{f.loss_rate_pct}%, {f.points_per_game} ppg, {f.goals_for_per_game}-{f.goals_against_per_game} goals/game")
    if f.venue_split_form:
        lines.append(f"- Venue split (true venue not fixture label): {venue_split_form_str(f.venue_split_form)}")
    if f.detailed_venue_split:
        lines.append(f"- Detailed venue split: {detailed_venue_split_str(f.detailed_venue_split)}")


def form_summary_markdown(f: FormSummary, lines: list[str]) -> None:
    _append_form_recent_results(f, lines)
    _append_form_rates(f, lines)
    _append_form_venue_splits(f, lines)


def referee_stats_str(rs: RefereeStats) -> str:
    penalties = f", {rs.penalties_awarded} penalties this season" if rs.penalties_awarded is not None else ""
    second_yellow = f", {rs.second_yellow_cards} second-yellow dismissals this season" if rs.second_yellow_cards is not None else ""
    bias = f", home {rs.home_away_bias.home_cards_per_game} vs away {rs.home_away_bias.away_cards_per_game} cards/game (n={rs.home_away_bias.sample_size})" if rs.home_away_bias else ""
    fouls = f", {rs.fouls_per_game} fouls/game" if rs.fouls_per_game is not None else ""
    pens = f", {rs.penalties_per_game} penalties/game" if rs.penalties_per_game is not None else ""
    cards_foul = f", {rs.cards_per_foul} cards/foul" if rs.cards_per_foul is not None else ""
    avg_cards = f", {rs.avg_total_cards} avg total cards/game" if rs.avg_total_cards is not None else ""
    return f"{rs.games} games, {rs.yellow_cards} yellow / {rs.red_cards} red, {rs.yellow_cards_per_game} yellow/game{penalties}{second_yellow}{bias}{fouls}{pens}{cards_foul}{avg_cards}"


def manager_str(m: ManagerInfo | None) -> str:
    if not m:
        return "unknown"
    tenure = f", appointed {m.appointed_date[:10]}" if m.appointed_date else ""
    recent = " -- recent managerial change" if m.recent_appointment else ""
    previous = f", previously {m.previous_manager}" if m.previous_manager else ""
    return f"{m.name}{f' ({m.country})' if m.country else ''}{tenure}{recent}{previous}"


def performer_str(t) -> str:
    if t.goals and t.assists:
        stat = f"{t.goals}g/{t.assists}a"
    elif t.goals:
        stat = f"{t.goals}g"
    else:
        stat = f"{t.assists}a"
    # appearances is None for sources that don't publish it (confirmed:
    # Fotmob's squad page has real per-player stats but no appearances
    # count anywhere on it) -- omit the "in N apps" clause entirely rather
    # than print a misleading "in None apps".
    apps = f" in {t.appearances} apps" if t.appearances is not None else ""
    rating = f", {t.rating:.2f} avg rating" if t.rating else ""
    return f"{t.name} ({stat}{apps}{rating})"


def defender_str(d) -> str:
    return f"{d.name} ({d.tackles_made} tackles, {d.interceptions} interceptions)"


def bench_regular_str(b) -> str:
    return f"{b.name} ({b.starts} starts, {b.sub_appearances} sub apps, {b.unused_bench} unused, of {b.matches_in_squad})"


def recent_form_leader_str(r: RecentFormLeader) -> str:
    per90 = f", {js_number_to_string(r.goals_per90)}g/{js_number_to_string(r.assists_per90)}a per 90" if r.goals_per90 is not None else ""
    key_passes = f", {r.key_passes} key passes" if r.key_passes > 0 else ""
    rating = f", {js_number_to_string(r.avg_rating)} avg rating" if r.avg_rating is not None else ""
    return f"{r.name} ({r.goals}g/{r.assists}a, {js_number_to_string(r.xg)}xG/{js_number_to_string(r.xa)}xA{key_passes}{per90}{rating}, n={r.sample_size})"


def role_form_entry_str(r: RoleFormEntry) -> str:
    key_passes = f", {r.key_passes} key passes" if r.key_passes > 0 else ""
    rating = f", {js_number_to_string(r.avg_rating)} avg rating" if r.avg_rating is not None else ""
    return f"{r.name} ({r.total_minutes}min in {r.matches_in_squad} ({r.starts} starts), {r.goals}g/{r.assists}a, {js_number_to_string(r.xg)}xG/{js_number_to_string(r.xa)}xA{key_passes}{rating})"


def _weather_detail_extra(w) -> str:
    """The 4 optional trailing weather-detail clauses, extracted from
    _append_match_header to remove their nested-if contribution to its
    cognitive complexity (python:S3776); behavior unchanged."""
    extra = ""
    if w.chance_of_rain_pct is not None:
        extra += f", {w.chance_of_rain_pct:g}% chance of rain"
    if w.wind_gust_kmph is not None:
        extra += f", gusts {w.wind_gust_kmph:g} km/h"
    if w.cloud_cover_pct is not None:
        extra += f", {w.cloud_cover_pct:g}% cloud cover"
    if w.feels_like_c is not None:
        extra += f", feels like {w.feels_like_c:g}°C"
    return extra


def _weather_detail_line(w) -> str:
    """The full "- Weather detail: ..." line, extracted from
    _append_match_header -- see _weather_detail_extra's own doc comment
    for why. Behavior unchanged."""
    humidity = w.humidity_pct if w.humidity_pct is not None else "n/a"
    wind = w.wind_speed_kmph if w.wind_speed_kmph is not None else "n/a"
    precip = w.precip_mm if w.precip_mm is not None else "n/a"
    extra = _weather_detail_extra(w)
    return f"- Weather detail: humidity {humidity}%, wind {wind} km/h, precip {precip} mm{extra}"


def _competition_line(d) -> str:
    """The "- Competition: ..." line, extracted from _append_match_header
    -- see _weather_detail_extra's own doc comment for why. Behavior
    unchanged."""
    season = f" ({d.season})" if d.season else ""
    round_str = f", round {d.round}" if d.round is not None else ""
    return f"- Competition: {d.competition or 'unknown'}{season}{round_str}"


def _venue_line(d) -> str | None:
    """The "- Venue: ..." line, extracted from _append_match_header -- see
    _weather_detail_extra's own doc comment for why. Behavior unchanged."""
    if not d.venue_name:
        return None
    city = f", {d.venue_city}" if d.venue_city else ""
    country = f", {d.venue_country}" if d.venue_country else ""
    return f"- Venue: {d.venue_name}{city}{country}"


def _append_match_header(d, lines: list[str]) -> None:
    """First part of merged_match_markdown -- extracted purely to keep
    that function's own cognitive complexity down (python:S3776); each
    block is independent (its own `if`, appending to the same shared
    `lines`), so splitting doesn't change what's appended or in what
    order. Behavior unchanged."""
    lines.append(f"**{d.home_team} vs {d.away_team}**")
    lines.append("")
    lines.append(f"- Kickoff: {format_when(d.kickoff_utc)}")
    lines.append(_competition_line(d))
    lines.append(f"- Status: {d.status}")
    venue_line = _venue_line(d)
    if venue_line:
        lines.append(venue_line)
    if d.referee:
        rs = f" ({referee_stats_str(d.referee_stats)})" if d.referee_stats else ""
        lines.append(f"- Referee: {d.referee}{rs}")
    if d.attendance:
        lines.append(f"- Attendance: {d.attendance}")
    if d.weather:
        lines.append(f"- Weather: {d.weather}")
    if d.weather_detail:
        lines.append(_weather_detail_line(d.weather_detail))


def _append_match_odds_and_standings(d, lines: list[str]) -> None:
    """Second part of merged_match_markdown, itself split in two -- see
    _append_match_header's docstring for why this split is safe, and
    _append_match_season_stats below for the rest."""
    if d.betting_odds:
        o = d.betting_odds
        pct = f" ({o.home_win_implied_pct}%/{o.draw_implied_pct}%/{o.away_win_implied_pct}% implied)" if o.home_win_implied_pct is not None else ""
        ou = f", O/U 2.5: {o.over_2_5_odds}/{o.under_2_5_odds}" if o.over_2_5_odds is not None else ""
        lines.append(f"- Odds: {d.home_team} {o.home_win_odds} / Draw {o.draw_odds} / {d.away_team} {o.away_win_odds}{pct}{ou}")
    if d.head_to_head_summary:
        h = d.head_to_head_summary
        lines.append(f"- H2H: {d.home_team} {h.home_wins}W - {h.draws}D - {h.away_wins}W {d.away_team}")
    if d.head_to_head_streaks:
        lines.append(f"- H2H streaks: {'; '.join(d.head_to_head_streaks)}")
    if d.recent_meetings:
        lines.append(f"- Recent meetings: {' | '.join(meeting_str(m) for m in d.recent_meetings)}")
    if d.home_team_standing:
        s = d.home_team_standing
        lines.append(f"- {d.home_team} rank: #{s.position} ({s.points} pts, {s.wins}W-{s.draws}D-{s.losses}L, {s.goal_diff})")
    if d.away_team_standing:
        s = d.away_team_standing
        lines.append(f"- {d.away_team} rank: #{s.position} ({s.points} pts, {s.wins}W-{s.draws}D-{s.losses}L, {s.goal_diff})")
    _append_match_season_stats(d, lines)


def _append_match_season_stats(d, lines: list[str]) -> None:
    """Second half of _append_match_odds_and_standings -- see its own
    docstring."""
    if d.home_team_season_stats:
        s = d.home_team_season_stats
        poss = f", {s.average_ball_possession}% avg possession" if s.average_ball_possession else ""
        lines.append(f"- {d.home_team} season: {s.goals_scored} scored, {s.goals_conceded} conceded, {s.clean_sheets} clean sheets, {s.yellow_cards} yellow / {s.red_cards} red{poss}")
    if d.away_team_season_stats:
        s = d.away_team_season_stats
        poss = f", {s.average_ball_possession}% avg possession" if s.average_ball_possession else ""
        lines.append(f"- {d.away_team} season: {s.goals_scored} scored, {s.goals_conceded} conceded, {s.clean_sheets} clean sheets, {s.yellow_cards} yellow / {s.red_cards} red{poss}")


def _lineup_label(lineup_confirmed: bool | None) -> str:
    if lineup_confirmed is True:
        return "lineup (confirmed)"
    if lineup_confirmed is False:
        return "expected lineup (predicted, not confirmed)"
    return "lineup"


def _append_match_lineups_and_notes(d, lines: list[str]) -> None:
    """Final part of merged_match_markdown, itself split in two -- see
    _append_match_header's docstring for why this split is safe, and
    _append_match_managers_and_notes below for the rest."""
    if d.match_stats:
        lines.append(f"- Match stats: {', '.join(f'{s.name} {s.home}-{s.away}' for s in d.match_stats)}")
    if d.event_timeline:
        timeline_parts = [f"{e.minute}' {e.type}" + (f" ({e.player})" if e.player else "") for e in d.event_timeline]
        lines.append(f"- Timeline: {', '.join(timeline_parts)}")
    if d.player_of_the_match:
        rating = f" ({d.player_of_the_match.rating})" if d.player_of_the_match.rating else ""
        lines.append(f"- Player of the match: {d.player_of_the_match.name}{rating}")
    lineup_label = _lineup_label(d.lineup_confirmed)
    if d.home_formation:
        lines.append(f"- {d.home_team} formation: {d.home_formation}")
    if d.home_lineup:
        lines.append(f"- {d.home_team} {lineup_label}: {', '.join(p.name for p in d.home_lineup)}")
    if d.away_formation:
        lines.append(f"- {d.away_team} formation: {d.away_formation}")
    if d.away_lineup:
        lines.append(f"- {d.away_team} {lineup_label}: {', '.join(p.name for p in d.away_lineup)}")
    _append_match_managers_and_notes(d, lines)


def _append_match_managers_and_notes(d, lines: list[str]) -> None:
    """Second half of _append_match_lineups_and_notes -- see its own
    docstring."""
    if d.home_manager or d.away_manager:
        lines.append(f"- Managers: {d.home_team}: {manager_str(d.home_manager)} | {d.away_team}: {manager_str(d.away_manager)}")
    if d.home_manager_vs_away_club and d.home_manager_vs_away_club.sample_size:
        r = d.home_manager_vs_away_club
        lines.append(f"- {r.manager_name} vs {r.opponent_club} (his last {r.sample_size} meetings, any club he's managed): {r.wins}W-{r.draws}D-{r.losses}L")
    if d.away_manager_vs_home_club and d.away_manager_vs_home_club.sample_size:
        r = d.away_manager_vs_home_club
        lines.append(f"- {r.manager_name} vs {r.opponent_club} (his last {r.sample_size} meetings, any club he's managed): {r.wins}W-{r.draws}D-{r.losses}L")
    if d.note:
        lines.append(f"- Note: {d.note}")
    for n in d.additional_notes:
        lines.append(f"- Note: {n.note}")


def merged_match_markdown(d, lines: list[str]) -> None:
    _append_match_header(d, lines)
    _append_match_odds_and_standings(d, lines)
    _append_match_lineups_and_notes(d, lines)


def venue_details_markdown(v: VenueDetails, lines: list[str]) -> None:
    capacity = f", capacity {v.capacity:,}" if v.capacity else ""
    opened = f", opened {v.opened}" if v.opened else ""
    renovated = f", renovated {v.renovated}" if v.renovated else ""
    city = f", {v.city}" if v.city else ""
    lines.append(f"- Stadium: {v.stadium_name}{city}{capacity}{opened}{renovated}")
    if v.address:
        lines.append(f"  - Address: {v.address}")
    if v.architect:
        lines.append(f"  - Design: {v.architect}")
    if v.record_attendance:
        lines.append(f"  - Record attendance: {v.record_attendance}")


def _append_profile_squad_and_injuries(p, lines: list[str]) -> None:
    """First half of merged_profile_markdown -- extracted purely to keep
    that function's own cognitive complexity down (python:S3776); each
    block is independent (its own `if`, appending to the same shared
    `lines`), so splitting doesn't change what's appended or in what
    order. Behavior unchanged."""
    if p.squad:
        avg_age = f", avg age {js_number_to_string(p.average_age)}" if p.average_age else ""
        lines.append(f"- Squad ({len(p.squad)}{avg_age}): {', '.join(m.name for m in p.squad)}")
    injuries_str = "; ".join(f"{m.name} - {m.injury}" for m in p.injuries) if p.injuries else "none reported"
    lines.append(f"- Injuries: {injuries_str}")
    if p.key_injuries:
        lines.append(f"- Key injuries (by squad value): {', '.join(m.name for m in p.key_injuries)}")
    if p.missing_midfielders:
        lines.append(f"- Missing midfielders: {', '.join(p.missing_midfielders)}")
    if p.missing_attackers:
        lines.append(f"- Missing attackers: {', '.join(p.missing_attackers)}")
    if p.missing_defenders:
        lines.append(f"- Missing defenders: {', '.join(p.missing_defenders)}")
    if p.missing_goalkeepers:
        lines.append(f"- Missing goalkeepers: {', '.join(p.missing_goalkeepers)}")
    if p.recent_transfers:
        lines.append(f"- Recent transfers: {'; '.join(transfer_str(t) for t in p.recent_transfers)}")


def _append_profile_performers(p, lines: list[str]) -> None:
    """Second half of merged_profile_markdown -- see
    _append_profile_squad_and_injuries' docstring for why this split is
    safe."""
    top_scorers = compute_top_performers(p.squad, "goals")
    top_assists = compute_top_performers(p.squad, "assists")
    if top_scorers:
        lines.append(f"- Top scorers: {', '.join(performer_str(t) for t in top_scorers)}")
    if top_assists:
        lines.append(f"- Top assists: {', '.join(performer_str(t) for t in top_assists)}")
    top_defenders = compute_top_defenders(p.squad)
    if top_defenders:
        lines.append(f"- Top defenders: {', '.join(defender_str(d) for d in top_defenders)}")
    bench_regulars = compute_bench_regulars(p.squad)
    if bench_regulars:
        lines.append(f"- Bench regulars (last 20): {', '.join(bench_regular_str(b) for b in bench_regulars)}")
    recent_form_leaders = compute_recent_form_leaders(p.squad)
    if recent_form_leaders:
        lines.append(f"- Recent form (last 20): {', '.join(recent_form_leader_str(r) for r in recent_form_leaders)}")
    midfielders_form = compute_role_form_breakdown(p.squad, is_midfield_role)
    if midfielders_form:
        lines.append(f"- Midfielders (last 20, by minutes): {', '.join(role_form_entry_str(r) for r in midfielders_form)}")
    defenders_form = compute_role_form_breakdown(p.squad, is_defender_role)
    if defenders_form:
        lines.append(f"- Defenders (last 20, by minutes): {', '.join(role_form_entry_str(r) for r in defenders_form)}")


def merged_profile_markdown(p, lines: list[str]) -> None:
    lines.append("")
    lines.append(f"**Team profile ({p.team_name})**")
    lines.append("")
    _append_profile_squad_and_injuries(p, lines)
    _append_profile_performers(p, lines)


def elo_str(e: EloRating, label: str) -> str:
    return f"{label} Elo: {e.elo} (computed from recent form, as of {e.as_of})"


def club_strength_str(s: ClubStrengthRating, label: str) -> str:
    rank = f", global rank #{s.rank}" if s.rank is not None else ""
    if s.strength_change is not None:
        sign = "+" if s.strength_change >= 0 else ""
        change = f", {sign}{js_number_to_string(s.strength_change)} vs last check"
    else:
        change = ""
    return (
        f"{label} strength: {js_number_to_string(s.overall)} overall (attack {js_number_to_string(s.attack)}, "
        f"defense {js_number_to_string(s.defense)}{rank}{change})"
    )


def zone_str(z: StandingsZoneInfo, label: str) -> str:
    if z.points_from_boundary is not None:
        in_mix = " -- in the mix" if z.in_the_mix else ""
        stakes = f", {z.points_from_boundary}pts from nearest zone boundary{in_mix}"
    else:
        stakes = ""
    return f"{label}: #{z.position}/{z.total_teams} ({z.zone}{stakes})"


def card_str(c: CardDisciplineInfo, label: str) -> str:
    return f"{label}: {js_number_to_string(c.yellow_per_game)} yellow/game, {js_number_to_string(c.red_per_game)} red/game" + (" (elevated risk)" if c.elevated_risk else "")


def card_discipline_venue_split_str(s: CardDisciplineVenueSplit, label: str) -> str:
    home = f"{js_number_to_string(s.at_home_yellow_per_game)}Y/{js_number_to_string(s.at_home_red_per_game)}R (n={s.at_home_sample_size})" if s.at_home_sample_size else "n/a"
    away = f"{js_number_to_string(s.away_yellow_per_game)}Y/{js_number_to_string(s.away_red_per_game)}R (n={s.away_sample_size})" if s.away_sample_size else "n/a"
    return f"{label} card discipline by venue (last 5): at home {home} / away {away}"


def travel_str(t: TravelInfo, home_team: str, away_team: str) -> str:
    def side(traveling: bool | None, team: str, country: str | None, km: float | None, tz_diff: float | None, hours: float | None) -> str:
        if traveling is None:
            return f"{team}: unknown"
        if not traveling:
            return f"{team} at home turf ({country})"
        km_str = f", ~{km:,.0f}km" if km is not None else ""
        hours_str = f", ~{js_number_to_string(hours)}h travel" if hours is not None else ""
        tz_str = f", {js_number_to_string(tz_diff)}h tz diff" if tz_diff is not None and tz_diff > 0 else ""
        return f"{team} traveling ({country} -> {t.venue_country}{km_str}{hours_str}{tz_str})"

    return f"Travel: {side(t.home_traveling, home_team, t.home_team_country, t.home_travel_distance_km, t.home_timezone_diff_hours, t.home_travel_time_hours)}; {side(t.away_traveling, away_team, t.away_team_country, t.away_travel_distance_km, t.away_timezone_diff_hours, t.away_travel_time_hours)}"


def rank_record_str(r: OpponentRankRecord, label: str) -> str:
    return f"{label} vs currently-higher-ranked opponents (same competition): {r.wins}W-{r.draws}D-{r.losses}L (n={r.sample_size})"


def presence_str(p: list[PresenceEntry], label: str) -> str:
    present = [e for e in p if e.status == "P"]
    absent = [e for e in p if e.status == "A"]
    starting = len([e for e in present if e.starting])
    on_bench = len([e for e in present if e.on_bench])
    bench_part = f", {on_bench} on bench" if any(e.on_bench is not None for e in present) else ""
    absent_list = f": {', '.join(f'{e.name} ({e.reason})' for e in absent)}" if absent else ""
    return f"{label} availability: {len(present)} present ({starting} starting{bench_part}), {len(absent)} absent{absent_list}"


def _eur(v: float | None) -> str:
    return f"€{v / 1_000_000:.0f}m" if v is not None else "n/a"


def bench_info_str(b, label: str) -> str:
    return f"{label} bench: {b.bench_size} named, {_eur(b.bench_total_market_value)} combined value vs starting XI's {_eur(b.starting_total_market_value)}"


def squad_strength_str(s, label: str) -> str:
    return f"{label} squad value: {_eur(s.total_value)} total ({_eur(s.available_value)} available) -- attack {_eur(s.attack_value)}, midfield {_eur(s.midfield_value)}, defense {_eur(s.defense_value)}, GK {_eur(s.goalkeeper_value)}"


_RESULT_WORD = {"W": "a win", "D": "a draw", "L": "a loss"}


def rotation_str(r: RotationInfo, label: str) -> str:
    trigger = f" after {_RESULT_WORD[r.preceding_result]}" if r.preceding_result else ""
    prev_date = r.previous_match_date[:10] if r.previous_match_date else "?"
    last_date = r.last_match_date[:10] if r.last_match_date else "?"
    base = f"{label} rotation{trigger}: {r.changed_players}/{r.starting_xi_size} starting XI changed from the previous match ({prev_date} -> {last_date})"
    if not r.previous_formation or not r.last_formation:
        return base
    if r.formation_changed:
        defenders = (
            f" ({r.previous_defender_count} -> {r.last_defender_count} defenders)"
            if r.last_defender_count is not None and r.previous_defender_count is not None and r.last_defender_count != r.previous_defender_count
            else ""
        )
        shape = f"shape changed {r.previous_formation} -> {r.last_formation}{defenders}"
    else:
        shape = f"shape unchanged ({r.last_formation})"
    return f"{base}, {shape}"


def resilience_str(r: ResilienceInfo, label: str) -> str:
    return f"{label} resilience: {r.draw_share_pct}% of non-win results (n={r.non_win_sample_size}) were draws rather than losses"


def rest_performance_str(r: RestPerformanceInfo, label: str) -> str:
    short = f"{js_number_to_string(r.short_rest_ppg)} ppg (n={r.short_rest_sample_size})" if r.short_rest_ppg is not None else "n/a"
    long_ = f"{js_number_to_string(r.long_rest_ppg)} ppg (n={r.long_rest_sample_size})" if r.long_rest_ppg is not None else "n/a"
    return f"{label} performance by rest: <=3 days rest {short} vs longer rest {long_}"


def experience_h2h_str(e: ExperienceH2HNote) -> str:
    if e.aligned is None:
        return f'Experience/H2H: more experienced squad is "{e.more_experienced}", h2h leader is "{e.h2h_leader}" -- not directly comparable (one side is even)'
    return f"Experience/H2H: more experienced squad ({e.more_experienced}) {'also holds' if e.aligned else 'does not hold'} the head-to-head edge"


def fatigue_flag_str(f: FatigueFlag, label: str) -> str:
    avg_gap = js_number_to_string(f.avg_gap_days) if f.avg_gap_days is not None else "n/a"
    return f"{label} fatigue risk: {'elevated' if f.flagged else 'normal'} ({len(f.competitions)} competitions recently, {avg_gap}d avg gap between last 3)"


def home_advantage_str(h: HomeAdvantageInfo, label: str) -> str:
    sign = "+" if h.gap_pct is not None and h.gap_pct >= 0 else ""
    return f"{label} home advantage: {h.strength} (home {h.home_win_rate_pct}% / away {h.away_win_rate_pct}% win rate, {sign}{h.gap_pct}pp)"


def streak_stability_str(s: StreakStabilityInfo, label: str) -> str:
    if s.streak_result != "W" or s.streak_count < 2:
        if s.streak_result == "W":
            word = "winning"
        elif s.streak_result == "L":
            word = "losing"
        else:
            word = "drawing"
        return f"{label} streak: {s.streak_count}-game {word} run"
    if s.stable is None:
        stability = "unknown (no rotation data)"
    elif s.stable:
        stability = "stable XI"
    else:
        stability = "rotated XI"
    changes = f" ({s.changed_players} changes since previous match)" if s.changed_players is not None else ""
    return f"{label} streak: {s.streak_count}-game winning run, {stability}{changes}"


def losing_streak_context_str(losing: LosingStreakContextInfo, team_name: str) -> str:
    if losing.xg_delta is not None:
        sign = "+" if losing.xg_delta >= 0 else ""
        xg = f"{sign}{js_number_to_string(losing.xg_delta)} actual-vs-xG"
    else:
        xg = "xG data unavailable"
    turnaround = " -- underperforming their chances, potential turnaround" if losing.potential_turnaround else ""
    return f"{team_name} losing streak context: {losing.streak_count} games, {xg}{turnaround}"


def xg_estimate_str(x: SeasonXGEstimate, label: str) -> str:
    return f"{label} xG estimate (last {x.sample_size} finished): {js_number_to_string(x.xg_for)} xGF / {js_number_to_string(x.xg_against)} xGA vs actual {x.actual_goals_for}-{x.actual_goals_against}"


def shots_estimate_str(x: SeasonShotsEstimate, label: str) -> str:
    return f"{label} shots estimate (last {x.sample_size} finished): {x.shots_for} shots for ({x.shots_on_target_for} on target) / {x.shots_against} against ({x.shots_on_target_against} on target)"


def aerial_estimate_str(x: SeasonAerialEstimate, label: str) -> str:
    return f"{label} aerial duels (last {x.sample_size} finished): {x.aerial_duels_won_for} won / {x.aerial_duels_won_against} lost"


def big_chances_estimate_str(x: SeasonBigChancesEstimate, label: str) -> str:
    return f"{label} big chances (last {x.sample_size} finished): {x.big_chances_created_for} created ({x.big_chances_missed_for} missed) / {x.big_chances_created_against} conceded ({x.big_chances_missed_against} missed by opponent)"


def advanced_stats_str(x: SeasonAdvancedStatsEstimate, label: str) -> str:
    poss = js_number_to_string(x.possession_pct_avg) if x.possession_pct_avg is not None else "n/a"
    tilt = js_number_to_string(x.field_tilt_pct) if x.field_tilt_pct is not None else "n/a"
    parts = [
        f"touches in box {x.touches_in_box_for}-{x.touches_in_box_against}",
        f"shots in/out box {x.shots_inside_box_for}/{x.shots_outside_box_for}-{x.shots_inside_box_against}/{x.shots_outside_box_against}",
        f"shots off target {x.shots_off_target_for}-{x.shots_off_target_against}",
        f"blocked {x.blocked_shots_for}-{x.blocked_shots_against}",
        f"big chances scored {x.big_chances_scored_for}-{x.big_chances_scored_against}",
        f"crosses {x.crosses_for}-{x.crosses_against}",
        f"dribbles {x.dribbles_for}-{x.dribbles_against}",
        f"through balls {x.through_balls_for}-{x.through_balls_against}",
        f"final third entries {x.final_third_entries_for}-{x.final_third_entries_against}",
        f"offsides {x.offsides_for}-{x.offsides_against}",
        f"dispossessed {x.dispossessed_for}-{x.dispossessed_against}",
        f"tackles {x.team_tackles_for}-{x.team_tackles_against}",
        f"interceptions {x.team_interceptions_for}-{x.team_interceptions_against}",
        f"clearances {x.team_clearances_for}-{x.team_clearances_against}",
        f"free kicks {x.free_kicks_for}-{x.free_kicks_against}",
        f"xA {js_number_to_string(x.xa_for)}-{js_number_to_string(x.xa_against)}",
        f"corner goals {x.corner_goals_for}-{x.corner_goals_against}",
        f"penalty goals {x.penalty_goals_for}-{x.penalty_goals_against}",
        f"free-kick goals {x.free_kick_goals_for}-{x.free_kick_goals_against}",
        f"recoveries {x.recoveries_for}-{x.recoveries_against}",
        f"errors->shot {x.errors_lead_to_shot_for}-{x.errors_lead_to_shot_against}",
        f"errors->goal {x.errors_lead_to_goal_for}-{x.errors_lead_to_goal_against}",
        f"goals prevented {js_number_to_string(x.goals_prevented_for)}-{js_number_to_string(x.goals_prevented_against)}",
        f"big saves {x.big_saves_for}-{x.big_saves_against}",
        f"high claims {x.high_claims_for}-{x.high_claims_against}",
        f"distance {js_number_to_string(x.distance_covered_km_for)}km-{js_number_to_string(x.distance_covered_km_against)}km",
        f"sprints {x.sprints_for}-{x.sprints_against}",
        f"total shots {x.total_shots_for}-{x.total_shots_against} ({x.shots_on_target_for}-{x.shots_on_target_against} on target)",
        f"corners {x.corners_for}-{x.corners_against}",
        f"fouls {x.fouls_for}-{x.fouls_against}",
        f"cards {x.yellow_cards_for}Y/{x.red_cards_for}R-{x.yellow_cards_against}Y/{x.red_cards_against}R",
        f"possession {poss}%",
        f"big chances created {x.big_chances_created_for}-{x.big_chances_created_against}",
        f"non-penalty xG {js_number_to_string(x.non_penalty_xg_for)}-{js_number_to_string(x.non_penalty_xg_against)}",
        f"set-piece xG {js_number_to_string(x.set_piece_xg_for)}-{js_number_to_string(x.set_piece_xg_against)}",
        f"penalties awarded {x.penalties_awarded_for}-{x.penalties_awarded_against}",
        f"field tilt {tilt}%",
    ]
    return f"{label} advanced stats (last {x.sample_size} matched): {', '.join(parts)}"


def passing_style_str(x: SeasonPassingStyleEstimate, label: str) -> str:
    pass_acc = js_number_to_string(x.pass_accuracy_pct) if x.pass_accuracy_pct is not None else "n/a"
    long_ball = js_number_to_string(x.long_ball_share_pct) if x.long_ball_share_pct is not None else "n/a"
    return f"{label} passing style (last {x.sample_size} finished): {pass_acc}% pass accuracy, {long_ball}% of accurate passes were long balls"


def fouls_estimate_str(x: SeasonFoulsEstimate, label: str) -> str:
    return f"{label} fouls estimate (last {x.sample_size} finished): {x.fouls_committed_for} committed / {x.fouls_committed_against} suffered"


def goalkeeping_estimate_str(x: SeasonGoalkeepingEstimate, label: str) -> str:
    save_pct = js_number_to_string(x.save_pct) if x.save_pct is not None else "n/a"
    return f"{label} goalkeeping estimate (last {x.sample_size} finished): {x.saves_for} saves on {x.shots_on_target_faced} shots faced ({save_pct}% save rate), {x.goals_conceded} conceded"


def set_piece_threat_str(f: SetPieceThreatFlag, label: str) -> str:
    corners = js_number_to_string(f.corners_per_game) if f.corners_per_game is not None else "n/a"
    aerial = js_number_to_string(f.opponent_aerial_win_pct) if f.opponent_aerial_win_pct is not None else "n/a"
    return f"{label} set-piece threat: {corners} corners/game vs opponent's {aerial}% aerial win rate" + (" -- elevated" if f.elevated else "")


def direct_play_exposure_str(f: DirectPlayExposureFlag, label: str) -> str:
    long_ball = js_number_to_string(f.long_ball_share_pct) if f.long_ball_share_pct is not None else "n/a"
    aerial = js_number_to_string(f.opponent_aerial_win_pct) if f.opponent_aerial_win_pct is not None else "n/a"
    return f"{label} direct-play exposure: {long_ball}% long-ball share vs opponent's {aerial}% aerial win rate" + (" -- elevated" if f.elevated else "")


def card_risks_str(risks: list[PlayerCardRisk], label: str) -> str:
    parts = [f"{r.name} ({r.yellow_cards}Y" + (f"/{r.red_cards}R" if r.red_cards else "") + (", prior dismissal" if r.prior_dismissal else "") + ")" for r in risks]
    return f"{label} card risk: {', '.join(parts)}"


def referee_card_risk_note_str(n: RefereeCardRiskNote, home_team: str, away_team: str) -> str:
    parts = [f"{p.name} ({home_team if p.side == 'home' else away_team}" + (", prior dismissal" if p.prior_dismissal else "") + ")" for p in n.flagged_players]
    elevated = " (elevated)" if n.elevated_card_referee else ""
    return f"Referee {n.referee_name} books {js_number_to_string(n.yellow_cards_per_game)} yellow/game{elevated} -- already-flagged players: {', '.join(parts)}"


def duel_vulnerabilities_str(vulns: list[DuelVulnerability], label: str) -> str:
    parts = [f"{v.name} ({v.ground_duel_success_pct:.1f}% ground duels won)" for v in vulns]
    return f"{label} defensive duel risk: {', '.join(parts)}"


def fullback_exposure_str(exposure: list[FullbackExposureInfo], label: str) -> str:
    parts = [f"{e.name} ({e.chances_created} chances created, {e.ground_duel_success_pct:.1f}% ground duels won)" for e in exposure]
    return f"{label} attacking-defender exposure: {', '.join(parts)}"


def standings_impact_str(s: StandingsImpactInfo, label: str) -> str:
    parts = []
    for sc in s.scenarios:
        delta = sc.new_position - s.current_position if sc.new_position is not None else None
        if delta is None:
            arrow = ""
        elif delta < 0:
            arrow = f" (up {-delta})"
        elif delta > 0:
            arrow = f" (down {delta})"
        else:
            arrow = " (no change)"
        parts.append(f"{sc.outcome}: #{sc.new_position if sc.new_position is not None else '?'}{arrow}")
    return f"{label} new standing if: {', '.join(parts)} (currently #{s.current_position}, {s.current_points}pts)"


def possession_matchup_str(p: PossessionMatchupInfo, team_name: str) -> str:
    high = f"{js_number_to_string(p.high_opponent_possession_ppg)} ppg (n={p.high_opponent_possession_sample_size})" if p.high_opponent_possession_ppg is not None else "n/a"
    other = f"{js_number_to_string(p.other_ppg)} ppg (n={p.other_sample_size})" if p.other_ppg is not None else "n/a"
    return f"{team_name} vs high-possession opponents (>=55%): {high} vs other opponents: {other}"


def corners_estimate_str(x: SeasonCornersEstimate, label: str) -> str:
    return f"{label} corners estimate (last {x.sample_size} finished): {x.corners_for} for / {x.corners_against} against"


def defensive_errors_estimate_str(x: SeasonDefensiveErrorsEstimate, label: str) -> str:
    return f"{label} defensive errors (last {x.sample_size} published): {x.defensive_errors_for} for / {x.defensive_errors_against} against"


def rest_label(days: int | None) -> str:
    """Same <=3 day threshold used for RestPerformanceInfo's "short rest"
    bucket and FatigueFlag's "tight schedule"."""
    return " (short rest)" if days is not None and days <= 3 else ""


def prediction_str(p, home_team: str, away_team: str) -> list[str]:
    """Market-implied is the primary signal when available (real money,
    reflects squad quality/injuries/form the heuristic has no way to
    see) -- the heuristic is a supplementary, lower-confidence estimate
    from recent-match results alone. Both are always shown, but not with
    equal weight: when they land on different favourites, or more than
    15 points apart on the same side, that's flagged explicitly rather
    than left for the reader to notice a silent disagreement between two
    numbers presented as if they were equally authoritative."""
    out = []
    m = p.market_implied
    b = p.heuristic_blend
    if m:
        out.append(f"- Prediction (market-implied, primary): {home_team} {m.home_win_pct}% / Draw {m.draw_pct}% / {away_team} {m.away_win_pct}%")
    if b:
        label = "Elo heuristic, not a trained model" + ("" if m else " -- no market odds available, this is the only estimate")
        out.append(f"- Prediction ({label}): {home_team} {b.home_win_pct}% / Draw {b.draw_pct}% / {away_team} {b.away_win_pct}%")
    if m and b:
        home_gap = abs(m.home_win_pct - b.home_win_pct)
        away_gap = abs(m.away_win_pct - b.away_win_pct)
        m_favors_home = m.home_win_pct > m.away_win_pct
        b_favors_home = b.home_win_pct > b.away_win_pct
        if m_favors_home != b_favors_home or max(home_gap, away_gap) > 15:
            out.append(
                "  - These disagree: the heuristic only sees each team's own recent match results in isolation, "
                "not squad quality, injuries, or how tough their opponents were -- treat the market-implied figure "
                "as the more reliable one when they diverge."
            )
    return out


def _more_rested_suffix(more_rested: str | None) -> str:
    """Extracted from _append_insights_summary to remove its nested-if
    contribution to that function's cognitive complexity (python:S3776);
    behavior unchanged."""
    if not more_rested:
        return ""
    if more_rested == "even":
        return " -- even"
    return f" -- {more_rested} team more rested"


def _more_experienced_suffix(more_experienced: str | None) -> str:
    """Extracted from _append_insights_summary -- see
    _more_rested_suffix's own doc comment for why."""
    if not more_experienced:
        return ""
    if more_experienced == "even":
        return " -- even"
    return f" -- {more_experienced} squad older"


def _append_insights_summary(insights: MatchInsights, home_team: str, away_team: str, lines: list[str]) -> None:
    """First fifth of insights_markdown -- extracted purely to keep that
    function's own cognitive complexity down (python:S3776); each block
    is independent (its own `if`, appending to the same shared `lines`),
    so splitting doesn't change what's appended or in what order.
    Behavior unchanged."""
    if insights.prediction:
        lines.extend(prediction_str(insights.prediction, home_team, away_team))
    if insights.match_type:
        lines.append(f"- Match type: {insights.match_type}")
    if insights.rest_comparison:
        r = insights.rest_comparison
        rested = _more_rested_suffix(r.more_rested)
        lines.append(f"- Rest: own {r.own_rest_days if r.own_rest_days is not None else 'n/a'}d{rest_label(r.own_rest_days)} / opponent {r.opponent_rest_days if r.opponent_rest_days is not None else 'n/a'}d{rest_label(r.opponent_rest_days)}{rested}")
    if insights.experience_comparison:
        e = insights.experience_comparison
        exp = _more_experienced_suffix(e.more_experienced)
        own_age = js_number_to_string(e.own_average_age) if e.own_average_age is not None else "n/a"
        opp_age = js_number_to_string(e.opponent_average_age) if e.opponent_average_age is not None else "n/a"
        lines.append(f"- Experience: own avg age {own_age} / opponent {opp_age}{exp}")


def _append_insights_ratings_and_estimates(insights: MatchInsights, home_team: str, away_team: str, lines: list[str]) -> None:
    """Second fifth of insights_markdown, itself split into 3 roughly-even
    parts (each independently under kotlin:S3776's threshold) -- see
    _append_insights_summary's docstring for why this split is safe."""
    _append_insights_ratings_part1(insights, home_team, away_team, lines)
    _append_insights_ratings_part2(insights, home_team, away_team, lines)
    _append_insights_ratings_part3(insights, home_team, away_team, lines)


def _append_insights_ratings_part1(insights: MatchInsights, home_team: str, away_team: str, lines: list[str]) -> None:
    """First third of _append_insights_ratings_and_estimates -- see its
    own docstring."""
    if insights.home_elo_rating:
        lines.append(f"- {elo_str(insights.home_elo_rating, home_team)}")
    if insights.away_elo_rating:
        lines.append(f"- {elo_str(insights.away_elo_rating, away_team)}")
    if insights.home_club_strength:
        lines.append(f"- {club_strength_str(insights.home_club_strength, home_team)}")
    if insights.away_club_strength:
        lines.append(f"- {club_strength_str(insights.away_club_strength, away_team)}")
    if insights.home_standings_zone:
        lines.append(f"- {zone_str(insights.home_standings_zone, home_team)}")
    if insights.away_standings_zone:
        lines.append(f"- {zone_str(insights.away_standings_zone, away_team)}")
    if insights.home_card_discipline:
        lines.append(f"- {card_str(insights.home_card_discipline, home_team)}")
    if insights.away_card_discipline:
        lines.append(f"- {card_str(insights.away_card_discipline, away_team)}")
    if insights.home_card_discipline_venue_split:
        lines.append(f"- {card_discipline_venue_split_str(insights.home_card_discipline_venue_split, home_team)}")
    if insights.away_card_discipline_venue_split:
        lines.append(f"- {card_discipline_venue_split_str(insights.away_card_discipline_venue_split, away_team)}")


def _append_insights_ratings_part2(insights: MatchInsights, home_team: str, away_team: str, lines: list[str]) -> None:
    """Second third of _append_insights_ratings_and_estimates -- see its
    own docstring."""
    if insights.home_xg_estimate:
        lines.append(f"- {xg_estimate_str(insights.home_xg_estimate, home_team)}")
    if insights.away_xg_estimate:
        lines.append(f"- {xg_estimate_str(insights.away_xg_estimate, away_team)}")
    if insights.home_shots_estimate:
        lines.append(f"- {shots_estimate_str(insights.home_shots_estimate, home_team)}")
    if insights.away_shots_estimate:
        lines.append(f"- {shots_estimate_str(insights.away_shots_estimate, away_team)}")
    if insights.home_aerial_estimate:
        lines.append(f"- {aerial_estimate_str(insights.home_aerial_estimate, home_team)}")
    if insights.away_aerial_estimate:
        lines.append(f"- {aerial_estimate_str(insights.away_aerial_estimate, away_team)}")
    if insights.home_advanced_stats:
        lines.append(f"- {advanced_stats_str(insights.home_advanced_stats, home_team)}")
    if insights.away_advanced_stats:
        lines.append(f"- {advanced_stats_str(insights.away_advanced_stats, away_team)}")
    if insights.home_big_chances_estimate:
        lines.append(f"- {big_chances_estimate_str(insights.home_big_chances_estimate, home_team)}")
    if insights.away_big_chances_estimate:
        lines.append(f"- {big_chances_estimate_str(insights.away_big_chances_estimate, away_team)}")


def _append_insights_ratings_part3(insights: MatchInsights, home_team: str, away_team: str, lines: list[str]) -> None:
    """Third third of _append_insights_ratings_and_estimates -- see its
    own docstring."""
    if insights.home_passing_style:
        lines.append(f"- {passing_style_str(insights.home_passing_style, home_team)}")
    if insights.away_passing_style:
        lines.append(f"- {passing_style_str(insights.away_passing_style, away_team)}")
    if insights.home_fouls_estimate:
        lines.append(f"- {fouls_estimate_str(insights.home_fouls_estimate, home_team)}")
    if insights.away_fouls_estimate:
        lines.append(f"- {fouls_estimate_str(insights.away_fouls_estimate, away_team)}")
    if insights.home_goalkeeping_estimate:
        lines.append(f"- {goalkeeping_estimate_str(insights.home_goalkeeping_estimate, home_team)}")
    if insights.away_goalkeeping_estimate:
        lines.append(f"- {goalkeeping_estimate_str(insights.away_goalkeeping_estimate, away_team)}")
    if insights.home_set_piece_threat:
        lines.append(f"- {set_piece_threat_str(insights.home_set_piece_threat, home_team)}")
    if insights.away_set_piece_threat:
        lines.append(f"- {set_piece_threat_str(insights.away_set_piece_threat, away_team)}")
    if insights.home_direct_play_exposure:
        lines.append(f"- {direct_play_exposure_str(insights.home_direct_play_exposure, home_team)}")
    if insights.away_direct_play_exposure:
        lines.append(f"- {direct_play_exposure_str(insights.away_direct_play_exposure, away_team)}")


def _append_insights_context(insights: MatchInsights, home_team: str, away_team: str, lines: list[str]) -> None:
    """Third fifth of insights_markdown, itself split in two -- see
    _append_insights_summary's docstring for why this split is safe,
    and _append_insights_context_squad below for the rest."""
    if insights.travel_info:
        lines.append(f"- {travel_str(insights.travel_info, home_team, away_team)}")
    if insights.home_opponent_rank_record:
        lines.append(f"- {rank_record_str(insights.home_opponent_rank_record, home_team)}")
    if insights.away_opponent_rank_record:
        lines.append(f"- {rank_record_str(insights.away_opponent_rank_record, away_team)}")
    if insights.home_rotation:
        lines.append(f"- {rotation_str(insights.home_rotation, home_team)}")
    if insights.away_rotation:
        lines.append(f"- {rotation_str(insights.away_rotation, away_team)}")
    if insights.home_presence:
        lines.append(f"- {presence_str(insights.home_presence, home_team)}")
    if insights.away_presence:
        lines.append(f"- {presence_str(insights.away_presence, away_team)}")
    _append_insights_context_squad(insights, home_team, away_team, lines)


def _append_insights_context_squad(insights: MatchInsights, home_team: str, away_team: str, lines: list[str]) -> None:
    """Second half of _append_insights_context -- see its own
    docstring."""
    if insights.home_bench_info:
        lines.append(f"- {bench_info_str(insights.home_bench_info, home_team)}")
    if insights.away_bench_info:
        lines.append(f"- {bench_info_str(insights.away_bench_info, away_team)}")
    if insights.home_squad_strength:
        lines.append(f"- {squad_strength_str(insights.home_squad_strength, home_team)}")
    if insights.away_squad_strength:
        lines.append(f"- {squad_strength_str(insights.away_squad_strength, away_team)}")
    if insights.home_resilience:
        lines.append(f"- {resilience_str(insights.home_resilience, home_team)}")
    if insights.away_resilience:
        lines.append(f"- {resilience_str(insights.away_resilience, away_team)}")
    if insights.home_rest_performance:
        lines.append(f"- {rest_performance_str(insights.home_rest_performance, home_team)}")
    if insights.away_rest_performance:
        lines.append(f"- {rest_performance_str(insights.away_rest_performance, away_team)}")


def _append_insights_risk_flags(insights: MatchInsights, home_team: str, away_team: str, lines: list[str]) -> None:
    """Fourth fifth of insights_markdown -- see _append_insights_summary's
    docstring for why this split is safe."""
    if insights.experience_h2h:
        lines.append(f"- {experience_h2h_str(insights.experience_h2h)}")
    if insights.home_fatigue_flag:
        lines.append(f"- {fatigue_flag_str(insights.home_fatigue_flag, home_team)}")
    if insights.away_fatigue_flag:
        lines.append(f"- {fatigue_flag_str(insights.away_fatigue_flag, away_team)}")
    if insights.home_advantage:
        lines.append(f"- {home_advantage_str(insights.home_advantage, home_team)}")
    if insights.away_advantage:
        lines.append(f"- {home_advantage_str(insights.away_advantage, away_team)}")
    if insights.home_streak_stability:
        lines.append(f"- {streak_stability_str(insights.home_streak_stability, home_team)}")
    if insights.away_streak_stability:
        lines.append(f"- {streak_stability_str(insights.away_streak_stability, away_team)}")
    if insights.home_losing_streak_context:
        lines.append(f"- {losing_streak_context_str(insights.home_losing_streak_context, home_team)}")
    if insights.away_losing_streak_context:
        lines.append(f"- {losing_streak_context_str(insights.away_losing_streak_context, away_team)}")


def _append_insights_impact(insights: MatchInsights, home_team: str, away_team: str, lines: list[str]) -> None:
    """Final fifth of insights_markdown, itself split in two -- see
    _append_insights_summary's docstring for why this split is safe,
    and _append_insights_impact_estimates below for the rest."""
    if insights.home_card_risks:
        lines.append(f"- {card_risks_str(insights.home_card_risks, home_team)}")
    if insights.away_card_risks:
        lines.append(f"- {card_risks_str(insights.away_card_risks, away_team)}")
    if insights.referee_card_risk_note:
        lines.append(f"- {referee_card_risk_note_str(insights.referee_card_risk_note, home_team, away_team)}")
    if insights.home_duel_vulnerabilities:
        lines.append(f"- {duel_vulnerabilities_str(insights.home_duel_vulnerabilities, home_team)}")
    if insights.away_duel_vulnerabilities:
        lines.append(f"- {duel_vulnerabilities_str(insights.away_duel_vulnerabilities, away_team)}")
    if insights.home_possession_matchup:
        lines.append(f"- {possession_matchup_str(insights.home_possession_matchup, home_team)}")
    if insights.away_possession_matchup:
        lines.append(f"- {possession_matchup_str(insights.away_possession_matchup, away_team)}")
    _append_insights_impact_estimates(insights, home_team, away_team, lines)


def _append_insights_impact_estimates(insights: MatchInsights, home_team: str, away_team: str, lines: list[str]) -> None:
    """Second half of _append_insights_impact -- see its own docstring."""
    if insights.home_corners_estimate:
        lines.append(f"- {corners_estimate_str(insights.home_corners_estimate, home_team)}")
    if insights.away_corners_estimate:
        lines.append(f"- {corners_estimate_str(insights.away_corners_estimate, away_team)}")
    if insights.home_defensive_errors_estimate:
        lines.append(f"- {defensive_errors_estimate_str(insights.home_defensive_errors_estimate, home_team)}")
    if insights.away_defensive_errors_estimate:
        lines.append(f"- {defensive_errors_estimate_str(insights.away_defensive_errors_estimate, away_team)}")
    if insights.home_fullback_exposure:
        lines.append(f"- {fullback_exposure_str(insights.home_fullback_exposure, home_team)}")
    if insights.away_fullback_exposure:
        lines.append(f"- {fullback_exposure_str(insights.away_fullback_exposure, away_team)}")
    if insights.home_standings_impact:
        lines.append(f"- {standings_impact_str(insights.home_standings_impact, home_team)}")
    if insights.away_standings_impact:
        lines.append(f"- {standings_impact_str(insights.away_standings_impact, away_team)}")
    if insights.opponent_context_error:
        lines.append(f"- (opponent lookup issue: {insights.opponent_context_error})")


def insights_markdown(insights: MatchInsights, home_team: str, away_team: str, lines: list[str]) -> None:
    lines.append("")
    lines.append("**Insights** _(rule-based, see README for thresholds)_")
    lines.append("")
    _append_insights_summary(insights, home_team, away_team, lines)
    _append_insights_ratings_and_estimates(insights, home_team, away_team, lines)
    _append_insights_context(insights, home_team, away_team, lines)
    _append_insights_risk_flags(insights, home_team, away_team, lines)
    _append_insights_impact(insights, home_team, away_team, lines)
