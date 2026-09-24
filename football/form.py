"""Recent-form computation: W/D/L history, streaks, momentum, venue-split
enrichment, and the shared match-stat parsing helpers. Ported from
src/search.ts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NamedTuple

from ._jsmath import js_round, js_round_to
from .elo import is_friendly_competition
from .fetch_log import record_step_failure
from .merge import normalize_team_name
from .team_aliases import canonical_for
from .types import (
    CompetitionFormRecord,
    DetailedVenueSplitForm,
    FixtureGap,
    FormResult,
    FormSummary,
    HalfSplitStats,
    LineupPlayer,
    MatchDetails,
    MatchInfo,
    MatchStatItem,
    MomentumInfo,
    PlayerUsagePattern,
    SeasonAdvancedStatsEstimate,
    Source,
    StreakInfo,
    VenueSplitForm,
    VenueSplitStats,
)

# How many of form.last20_overall get a full details() fetch when the
# source is Sofascore (see enrich_form_with_venue_classification). Each
# details() call is ~15 paced browser API requests; 20 x 2 teams was
# enough volume to get the client blocked mid-run.
FORM_ENRICH_DETAIL_LIMIT = 5

# Per-run cache of MatchDetails, filled as form enrichment / H2H detail
# fetches already pay for a full details() call. compute_rotation_info
# reuses these instead of re-opening two browser sessions after the rest
# of the pipeline may have tripped the Sofascore circuit breaker
# (confirmed live: both rotations null while the same matches' lineups
# had already been read for form enrichment).
# Keyed by kickoff + both team names, not kickoff alone: synchronized
# league rounds give both sides the same kickoff_utc, and own-team then
# opponent enrichment share this dict -- kickoff-only let the later write
# overwrite the earlier team's MatchDetails (rotation then diffed the
# wrong XI). Team names make the key collision-free within one run.
_details_by_kickoff: dict[tuple[str, str, str], MatchDetails] = {}


def _details_cache_key(match: MatchInfo) -> tuple[str, str, str] | None:
    if not match.kickoff_utc:
        return None
    return (match.kickoff_utc, normalize_team_name(match.home_team or ""), normalize_team_name(match.away_team or ""))


def cache_match_details(match: MatchInfo, details: MatchDetails) -> None:
    key = _details_cache_key(match)
    if key:
        _details_by_kickoff[key] = details


def get_cached_match_details(match: MatchInfo) -> MatchDetails | None:
    key = _details_cache_key(match)
    if not key:
        return None
    return _details_by_kickoff.get(key)


def clear_details_cache() -> None:
    _details_by_kickoff.clear()

# Statuses that unambiguously mean "hasn't kicked off yet" across every
# source's own vocabulary (Sofascore: notstarted, Fotmob/Goal/SoccerDesk/
# 365Scores: scheduled). Deliberately narrow -- "live"/"inprogress",
# "postponed", "cancelled", "interrupted", "unknown", etc. are excluded.
# Shared with insights.py's own completeness scoring (imported from
# there as NOT_STARTED_STATUSES, not redefined) -- defined here since
# next_match() below needs it and form.py has no dependency on
# insights.py, only the reverse.
NOT_STARTED_STATUSES = {"notstarted", "scheduled"}


_FORM_WINDOW = 20


def _parse_dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def next_match(matches: list[MatchInfo]) -> MatchInfo | None:
    """The soonest fixture that hasn't kicked off yet.

    Filters on BOTH a future kickoff_utc AND status in
    NOT_STARTED_STATUSES -- a future kickoff_utc alone isn't a reliable
    enough signal on its own. Confirmed live: a postponed/interrupted/
    live match can still carry a kickoff_utc value in the future (the
    original scheduled time, simply never updated once the match was
    postponed/interrupted), which let it silently outrank the genuinely
    next scheduled fixture under a pure-timestamp sort -- e.g. a
    postponed Everton vs Man Utd fixture outranking the real next
    Tottenham vs Everton match. status is the correct signal for "has
    this actually not started yet", independent of what its stored
    kickoff_utc happens to say."""
    now = datetime.now(tz=UTC)
    upcoming = sorted(
        (m for m in matches if m.kickoff_utc and m.status in NOT_STARTED_STATUSES and _parse_dt(m.kickoff_utc) > now),
        key=lambda m: _parse_dt(m.kickoff_utc),
    )
    return upcoming[0] if upcoming else None


def format_when(kickoff_utc: str | None) -> str:
    if not kickoff_utc:
        return "TBD"
    dt = _parse_dt(kickoff_utc)
    return dt.strftime("%Y-%m-%d %H:%M") + " UTC"


def is_team_home(m: MatchInfo, team_name: str) -> bool | None:
    target = normalize_team_name(team_name)
    home = normalize_team_name(m.home_team)
    away = normalize_team_name(m.away_team)
    if target in home or home in target:
        return True
    if target in away or away in target:
        return False
    # Substring matching alone misses source-specific short names that
    # share no substring with the searched name at all (e.g. Fotmob's own
    # literal "Nottm Forest" vs "Nottingham Forest") -- fall back to the
    # shared alias table (team_aliases.py) before giving up. Comparing
    # canonical forms unconditionally is safe: for any name absent from
    # the table, canonical_for() is the identity normalize(), so this
    # degrades to a plain equality check, not a replacement for the
    # substring checks already tried above.
    target_alias = canonical_for(team_name)
    if target_alias == canonical_for(m.home_team):
        return True
    if target_alias == canonical_for(m.away_team):
        return False
    return None


def day_diff(a: str, b: str) -> int:
    return round((_parse_dt(a) - _parse_dt(b)).total_seconds() / 86400)


def _to_form_result(m: MatchInfo, team_name: str) -> FormResult | None:
    home = is_team_home(m, team_name)
    if home is None:
        return None
    team_score = m.home_score if home else m.away_score
    opp_score = m.away_score if home else m.home_score
    if team_score > opp_score:
        result = "W"
    elif team_score < opp_score:
        result = "L"
    else:
        result = "D"
    return FormResult(
        opponent=(m.away_team if home else m.home_team),
        competition=m.competition,
        date=m.kickoff_utc,
        result=result,
        scoreline=f"{m.home_score}-{m.away_score}",
        venue=("home" if home else "away"),
        margin=abs(team_score - opp_score),
        neutral_venue=None,
        ht_scoreline=None,
        xg_for=None,
        xg_against=None,
    )


def _team_goals(r: FormResult) -> dict[str, int]:
    h, a = (int(n) for n in r.scoreline.split("-"))
    return {"for": h, "against": a} if r.venue == "home" else {"for": a, "against": h}


def _total_goals(r: FormResult) -> int:
    return sum(int(n) for n in r.scoreline.split("-"))


def _both_scored(r: FormResult) -> bool:
    h, a = (int(n) for n in r.scoreline.split("-"))
    return h > 0 and a > 0


_RESULT_POINTS = {"W": 3, "D": 1, "L": 0}


def _points_for_result(r: FormResult) -> int:
    return _RESULT_POINTS.get(r.result, 0)


def _win_rate(results: list[FormResult]) -> float | None:
    return js_round(len([r for r in results if r.result == "W"]) / len(results) * 100) if results else None


def _compute_next5_with_gaps(matches: list[MatchInfo], now: datetime, team_name: str) -> list[FixtureGap]:
    """Extracted from compute_form_summary to keep its own cognitive
    complexity down (python:S3776); behavior unchanged."""
    chronological = sorted((m for m in matches if m.kickoff_utc), key=lambda m: _parse_dt(m.kickoff_utc))
    # Same status filter as next_match: a postponed fixture keeps a future
    # kickoff_utc (the original time, never updated) and would otherwise
    # sit at [0] as phantom "next" -- corrupting own rest days against a
    # match that isn't scheduled (confirmed live for next_match itself).
    upcoming = [
        m for m in chronological
        if m.status in NOT_STARTED_STATUSES and _parse_dt(m.kickoff_utc) > now
    ][:5]
    next5_with_gaps: list[FixtureGap] = []
    for m in upcoming:
        idx = chronological.index(m)
        prev = chronological[idx - 1] if idx > 0 else None
        home = is_team_home(m, team_name)
        next5_with_gaps.append(
            FixtureGap(
                opponent=(m.home_team if home is False else m.away_team),
                date=m.kickoff_utc,
                days_since_previous=(day_diff(m.kickoff_utc, prev.kickoff_utc) if prev and prev.kickoff_utc else None),
            )
        )
    return next5_with_gaps


def _compute_half_split(played: list[MatchInfo], team_name: str) -> HalfSplitStats | None:
    """Only Sofascore's fixture list carries home_score_ht/away_score_ht
    (from the same events/next|last response already fetched -- no extra
    request). Silently empty for every other source, which is a real
    source limitation, not a bug in this computation. Extracted from
    compute_form_summary to keep its own cognitive complexity down
    (python:S3776); behavior unchanged."""
    with_half_time = [m for m in played if m.home_score_ht is not None and m.away_score_ht is not None]
    if not with_half_time:
        return None
    fh_for = fh_against = sh_for = sh_against = 0
    sample_size = 0
    for m in with_half_time:
        home = is_team_home(m, team_name)
        if home is None:
            continue
        sample_size += 1
        ht_for = m.home_score_ht if home else m.away_score_ht
        ht_against = m.away_score_ht if home else m.home_score_ht
        ft_for = m.home_score if home else m.away_score
        ft_against = m.away_score if home else m.home_score
        fh_for += ht_for
        fh_against += ht_against
        sh_for += ft_for - ht_for
        sh_against += ft_against - ht_against
    return HalfSplitStats(
        sample_size=sample_size,
        first_half_goals_for=fh_for,
        first_half_goals_against=fh_against,
        second_half_goals_for=sh_for,
        second_half_goals_against=sh_against,
    )


def _compute_current_streak(all_results: list[FormResult]) -> StreakInfo | None:
    """Longest run of the same result starting from the most recent match.
    Extracted from compute_form_summary to keep its own cognitive
    complexity down (python:S3776); behavior unchanged."""
    if not all_results:
        return None
    first = all_results[0].result
    count = 1
    while count < len(all_results) and all_results[count].result == first:
        count += 1
    return StreakInfo(result=first, count=count)


def _compute_momentum(all_results: list[FormResult]) -> MomentumInfo | None:
    """Extracted from compute_form_summary to keep its own cognitive
    complexity down (python:S3776); behavior unchanged."""
    if len(all_results) < 6:
        return None
    recent = all_results[:3]
    prior = all_results[3:6]
    recent_ppg = js_round_to(sum(_points_for_result(r) for r in recent) / len(recent), 2)
    prior_ppg = js_round_to(sum(_points_for_result(r) for r in prior) / len(prior), 2)
    diff = recent_ppg - prior_ppg
    if diff >= 0.3:
        trend = "improving"
    elif diff <= -0.3:
        trend = "declining"
    else:
        trend = "stable"
    return MomentumInfo(recent_ppg=recent_ppg, prior_ppg=prior_ppg, trend=trend)


def _compute_clean_sheet_and_scoreless_streaks(all_results: list[FormResult]) -> tuple[int | None, int | None]:
    """Extracted from compute_form_summary to keep its own cognitive
    complexity down (python:S3776); behavior unchanged."""
    if not all_results:
        return None, None
    cs = 0
    while cs < len(all_results) and _team_goals(all_results[cs])["against"] == 0:
        cs += 1
    ss = 0
    while ss < len(all_results) and _team_goals(all_results[ss])["for"] == 0:
        ss += 1
    return cs, ss


def _compute_form_by_competition(all_results: list[FormResult]) -> list[CompetitionFormRecord]:
    """W/D/L split per competition, from the same played-match sample (not
    a fresh fetch) -- competitions the team hasn't played in this sample
    simply don't appear, rather than showing a zeroed row. Stage suffixes
    (", Knockout stage") are folded into the base competition name so the
    list stays one row per competition and aligns with recent_competitions.
    Extracted from compute_form_summary to keep its own cognitive
    complexity down (python:S3776); behavior otherwise unchanged."""
    form_by_competition_map: dict[str, dict[str, int]] = {}
    for r in all_results:
        if not r.competition:
            continue
        comp = r.competition.split(",")[0].strip() or r.competition
        entry = form_by_competition_map.setdefault(
            comp, {"played": 0, "wins": 0, "draws": 0, "losses": 0, "goals_for": 0, "goals_against": 0}
        )
        entry["played"] += 1
        if r.result == "W":
            entry["wins"] += 1
        elif r.result == "D":
            entry["draws"] += 1
        else:
            entry["losses"] += 1
        g = _team_goals(r)
        entry["goals_for"] += g["for"]
        entry["goals_against"] += g["against"]
    return [CompetitionFormRecord(competition=comp, **v) for comp, v in form_by_competition_map.items()]


class _Last10Stats(NamedTuple):
    narrow_win_share_pct: float | None
    scoring_draw_share_pct: float | None
    btts_share_pct: float | None
    over15_share_pct: float | None
    over25_share_pct: float | None
    over35_share_pct: float | None
    clean_sheet_share_pct: float | None
    failed_to_score_share_pct: float | None
    win_rate_pct: float | None
    draw_rate_pct: float | None
    loss_rate_pct: float | None
    points_per_game: float | None
    goals_for_per_game: float | None
    goals_against_per_game: float | None


def _outcome_rates(results: list[FormResult]) -> tuple[float | None, float | None, float | None]:
    """Win/draw/loss percentages that add up to exactly 100. Rounding each
    independently gave 101 (or 99) for sample sizes that don't divide
    evenly, e.g. 3W/2D/2L of 7 -> 43+29+29; the largest-remainder method
    hands the leftover points to the biggest fractional parts instead."""
    if not results:
        return None, None, None
    counts = [len([r for r in results if r.result == outcome]) for outcome in ("W", "D", "L")]
    exact = [c * 100 / len(results) for c in counts]
    floors = [int(e) for e in exact]
    leftover = 100 - sum(floors)
    by_remainder = sorted(range(3), key=lambda i: (exact[i] - floors[i], -i), reverse=True)
    for i in by_remainder[:leftover]:
        floors[i] += 1
    return floors[0], floors[1], floors[2]


def _compute_last10_stats(all_results: list[FormResult]) -> _Last10Stats:
    """Every share/rate/per-game stat derived from the last 10 played
    results. Extracted from compute_form_summary to keep its own
    cognitive complexity down (python:S3776); behavior unchanged."""
    # "Narrow win" means genuinely tight and low-scoring (1-0, 2-1) -- a
    # 1-goal margin alone would also catch high-scoring shootouts like 4-3.
    last10_wins = [r for r in all_results[:10] if r.result == "W"]
    narrow_win_share_pct = (
        js_round(len([r for r in last10_wins if r.margin == 1 and _total_goals(r) <= 3]) / len(last10_wins) * 100)
        if last10_wins
        else None
    )

    last10_draws = [r for r in all_results[:10] if r.result == "D"]
    scoring_draw_share_pct = (
        js_round(len([r for r in last10_draws if _total_goals(r) > 0]) / len(last10_draws) * 100) if last10_draws else None
    )

    last10_played = all_results[:10]

    btts_share_pct = js_round(len([r for r in last10_played if _both_scored(r)]) / len(last10_played) * 100) if last10_played else None

    def over_share(line: float) -> float | None:
        return js_round(len([r for r in last10_played if _total_goals(r) > line]) / len(last10_played) * 100) if last10_played else None

    over15_share_pct = over_share(1.5)
    over25_share_pct = over_share(2.5)
    over35_share_pct = over_share(3.5)

    clean_sheet_share_pct = (
        js_round(len([r for r in last10_played if _team_goals(r)["against"] == 0]) / len(last10_played) * 100)
        if last10_played
        else None
    )
    failed_to_score_share_pct = (
        js_round(len([r for r in last10_played if _team_goals(r)["for"] == 0]) / len(last10_played) * 100)
        if last10_played
        else None
    )

    win_rate_pct, draw_rate_pct, loss_rate_pct = _outcome_rates(last10_played)
    points_per_game = js_round_to(sum(_points_for_result(r) for r in last10_played) / len(last10_played), 2) if last10_played else None
    goals_for_per_game = (
        js_round_to(sum(_team_goals(r)["for"] for r in last10_played) / len(last10_played), 2) if last10_played else None
    )
    goals_against_per_game = (
        js_round_to(sum(_team_goals(r)["against"] for r in last10_played) / len(last10_played), 2) if last10_played else None
    )

    return _Last10Stats(
        narrow_win_share_pct=narrow_win_share_pct,
        scoring_draw_share_pct=scoring_draw_share_pct,
        btts_share_pct=btts_share_pct,
        over15_share_pct=over15_share_pct,
        over25_share_pct=over25_share_pct,
        over35_share_pct=over35_share_pct,
        clean_sheet_share_pct=clean_sheet_share_pct,
        failed_to_score_share_pct=failed_to_score_share_pct,
        win_rate_pct=win_rate_pct,
        draw_rate_pct=draw_rate_pct,
        loss_rate_pct=loss_rate_pct,
        points_per_game=points_per_game,
        goals_for_per_game=goals_for_per_game,
        goals_against_per_game=goals_against_per_game,
    )


def all_form_results(team_name: str, matches: list[MatchInfo]) -> list[FormResult]:
    """Every played match converted to a FormResult, most recent first --
    the full history available from `matches`, not sliced to last5/10/20
    or friendly-filtered like compute_form_summary's own internal
    all_results is. Used by compute_recent_meetings (insights.py) to
    search for historical head-to-head meetings against a specific
    opponent: two teams often haven't played each other within the
    smaller last-20-overall window at all (confirmed live -- a
    Tottenham/Man Utd Europa League meeting over a year old was
    unreachable from that window), so H2H search needs the wider net.
    Friendlies deliberately included here (unlike compute_form_summary's
    all_results) -- a friendly meeting is still real head-to-head
    history worth surfacing, even though it's excluded from form/goals
    stats."""
    played = sorted(
        (m for m in matches if m.home_score is not None and m.away_score is not None and m.kickoff_utc),
        key=lambda m: _parse_dt(m.kickoff_utc),
        reverse=True,
    )
    return [r for r in (_to_form_result(m, team_name) for m in played) if r is not None]


def compute_form_summary(team_name: str, matches: list[MatchInfo]) -> FormSummary:
    now = datetime.now(tz=UTC)

    played = sorted(
        (m for m in matches if m.home_score is not None and m.away_score is not None and m.kickoff_utc),
        key=lambda m: _parse_dt(m.kickoff_utc),
        reverse=True,
    )

    # Friendlies/preseason excluded from every form/goals/streak/rate
    # computation below (same rationale as elo.py's own exclusion --
    # weakened lineups and no real stakes make them a poor signal of true
    # form) -- but NOT from next5_with_gaps, matches_last7/14_days, or
    # gaps_between_last_three, which are genuine scheduling/fitness
    # signals a friendly still counts toward. Falls back to the
    # unfiltered list only if every result is a friendly (better than an
    # empty form summary).
    all_results = [r for r in (_to_form_result(m, team_name) for m in played) if r is not None]
    competitive_results = [r for r in all_results if not is_friendly_competition(r.competition)]
    if competitive_results:
        all_results = competitive_results
    competitive_played = [m for m in played if not is_friendly_competition(m.competition)]
    if not competitive_played:
        competitive_played = played

    next5_with_gaps = _compute_next5_with_gaps(matches, now, team_name)

    last_three_played = played[:3]
    gaps_between_last_three = [
        day_diff(last_three_played[i].kickoff_utc, last_three_played[i + 1].kickoff_utc)
        for i in range(len(last_three_played) - 1)
    ]

    # Every windowed breakdown below uses the same last-20 competitive
    # matches as last20_overall/venue_split_form, so their sample sizes
    # reconcile instead of differing by however much history was fetched.
    half_split = _compute_half_split(competitive_played[:_FORM_WINDOW], team_name)

    # From `competitive_played` (raw MatchInfo, sorted desc, NOT `all_results`) --
    # `all_results` can be shorter than `played` when isTeamHome() returns
    # None for some entries (ambiguous team-name match), so the two aren't
    # interchangeable here even though they're both "recent matches".
    # Same _FORM_WINDOW as form_by_competition/half_split/venue_split_form
    # (see above) -- confirmed live a 10-match window here disagreed with
    # form_by_competition's 20 whenever a competition (a Champions League
    # tie, say) fell between the two: recent_competitions silently omitted
    # it while form_by_competition listed it. dict.fromkeys preserves
    # first-seen order the same way JS's Set does. Stage suffixes
    # (", Knockout stage") are stripped to the base competition name so
    # this list stays one label per competition and aligns with
    # form_by_competition below -- confirmed live, a bare "Premier League"
    # here next to "UEFA Champions League, Knockout stage" there read as
    # two different competitions covering different windows.
    def _base_comp(name: str | None) -> str | None:
        if not name:
            return None
        return name.split(",")[0].strip()

    recent_competitions = list(
        dict.fromkeys(
            base for m in competitive_played[:_FORM_WINDOW] if (base := _base_comp(m.competition))
        )
    )
    # Also include competitions from upcoming fixtures so consumers know
    # what's coming (e.g. a cup match in next5 that isn't in recent
    # played results yet).
    upcoming_competitions = [
        base
        for m in matches
        if m.kickoff_utc and m.status in NOT_STARTED_STATUSES and m.competition
        for base in [_base_comp(m.competition)]
    ]
    for comp in upcoming_competitions:
        if comp and comp not in recent_competitions:
            recent_competitions.append(comp)

    current_streak = _compute_current_streak(all_results)

    home_results = [r for r in all_results if r.venue == "home"]
    away_results = [r for r in all_results if r.venue == "away"]

    momentum = _compute_momentum(all_results)
    clean_sheet_streak, scoreless_streak = _compute_clean_sheet_and_scoreless_streaks(all_results)
    form_by_competition = _compute_form_by_competition(all_results[:_FORM_WINDOW])

    matches_last7_days = len([m for m in played if (now - _parse_dt(m.kickoff_utc)).total_seconds() <= 7 * 86400])
    matches_last14_days = len([m for m in played if (now - _parse_dt(m.kickoff_utc)).total_seconds() <= 14 * 86400])

    last10 = _compute_last10_stats(all_results)

    return FormSummary(
        last5_overall=all_results[:5],
        last10_overall=all_results[:10],
        last20_overall=all_results[:20],
        last5_home=home_results[:5],
        last5_away=away_results[:5],
        next5_with_gaps=next5_with_gaps,
        gaps_between_last_three=gaps_between_last_three,
        half_split=half_split,
        recent_competitions=recent_competitions,
        current_streak=current_streak,
        home_win_rate_pct=_win_rate(home_results),
        away_win_rate_pct=_win_rate(away_results),
        momentum=momentum,
        narrow_win_share_pct=last10.narrow_win_share_pct,
        scoring_draw_share_pct=last10.scoring_draw_share_pct,
        btts_share_pct=last10.btts_share_pct,
        clean_sheet_streak=clean_sheet_streak,
        scoreless_streak=scoreless_streak,
        over15_share_pct=last10.over15_share_pct,
        over25_share_pct=last10.over25_share_pct,
        over35_share_pct=last10.over35_share_pct,
        clean_sheet_share_pct=last10.clean_sheet_share_pct,
        failed_to_score_share_pct=last10.failed_to_score_share_pct,
        form_by_competition=form_by_competition,
        matches_last7_days=matches_last7_days,
        matches_last14_days=matches_last14_days,
        venue_split_form=None,
        detailed_venue_split=None,
        win_rate_pct=last10.win_rate_pct,
        draw_rate_pct=last10.draw_rate_pct,
        loss_rate_pct=last10.loss_rate_pct,
        points_per_game=last10.points_per_game,
        goals_for_per_game=last10.goals_for_per_game,
        goals_against_per_game=last10.goals_against_per_game,
        home_win_rate_sample_size=len(home_results),
        away_win_rate_sample_size=len(away_results),
        win_rate_sample_size=min(len(all_results), 10),
        points_per_game_sample_size=min(len(all_results), 10),
        goals_for_per_game_sample_size=min(len(all_results), 10),
        goals_against_per_game_sample_size=min(len(all_results), 10),
    )


# Sofascore's own per-match statistics endpoint's stat names, mapped to our
# field-name suffixes -- see SeasonAdvancedStatsEstimate's doc comment.
# Each key maps to every real stat-category title seen to carry that
# quantity -- Sofascore's own label first (unchanged from before), then
# any other source's synonym confirmed live to report the same thing
# under a different title (Fotmob: "Tackles" not "Total tackles",
# "Touches in opposition box" not "Touches in penalty area", "Corners"
# not "Corner kicks", "Fouls committed" not "Fouls", "Successful
# dribbles"/"Accurate crosses" -- the leading count before Fotmob's own
# "(NN%)" suffix, not the same denominator as Sofascore's plain count, but
# real data rather than a silent 0). Stats with NO confirmed synonym
# (through_balls, final_third_entries, recoveries, errors_lead_to_shot/
# goal, dispossessed, free_kicks, goals_prevented, big_saves, high_claims)
# genuinely aren't in Fotmob's own stat set -- see _unavailable_stat_keys.
_BIG_CHANCES_STAT_NAME = "Big chances"
_BIG_CHANCES_MISSED_STAT_NAME = "Big chances missed"


ADVANCED_STAT_NAMES: dict[str, tuple[str, ...]] = {
    "touches_in_box": ("Touches in penalty area", "Touches in opposition box"),
    "crosses": ("Crosses", "Accurate crosses"),
    "dribbles": ("Dribbles", "Successful dribbles"),
    "through_balls": ("Through balls",),
    "final_third_entries": ("Final third entries",),
    "recoveries": ("Recoveries",),
    "errors_lead_to_shot": ("Errors lead to a shot",),
    "errors_lead_to_goal": ("Errors lead to a goal",),
    "shots_inside_box": ("Shots inside box",),
    "shots_outside_box": ("Shots outside box",),
    "shots_off_target": ("Shots off target",),
    "blocked_shots": ("Blocked shots",),
    "offsides": ("Offsides",),
    "big_chances_scored": ("Big chances scored",),  # derived from "Big chances"/"Big chances missed" when absent -- see _big_chances_scored
    "dispossessed": ("Dispossessed",),
    "team_tackles": ("Total tackles", "Tackles"),
    "team_interceptions": ("Interceptions",),
    "goals_prevented": ("Goals prevented",),
    "big_saves": ("Big saves",),
    "high_claims": ("High claims",),
    "distance_covered_km": ("Distance covered",),  # unit varies by source -- see _km_from_distance_stat
    "sprints": ("Number of sprints",),
    "team_clearances": ("Clearances",),
    "free_kicks": ("Free kicks",),
    "total_shots": ("Total shots",),
    "shots_on_target": ("Shots on target",),
    "corner_kicks": ("Corner kicks", "Corners"),
    "fouls": ("Fouls", "Fouls committed"),
    "yellow_cards": ("Yellow cards",),
    "red_cards": ("Red cards",),
    "big_chances": (_BIG_CHANCES_STAT_NAME,),
    "ball_possession": ("Ball possession",),
}


def result_goals(r: FormResult) -> dict[str, int]:
    """Standalone (not the same-named local in compute_form_summary) --
    reads goals-for/against straight off a FormResult's own
    scoreline+venue, no extra data needed."""
    h, a = (int(n) for n in r.scoreline.split("-"))
    return {"for": h, "against": a} if r.venue == "home" else {"for": a, "against": h}


def parse_leading_int(s: str | None) -> int | None:
    """Fotmob stat values are sometimes plain integers ("3") and sometimes
    "count (%)" strings ("21 (58%)") -- this stops at the first
    non-digit character either way, so it handles both without needing to
    know which shape a given stat name uses."""
    if not s:
        return None
    import re

    m = re.match(r"\s*([+-]?\d+)", s)
    return int(m.group(1)) if m else None


def parse_leading_float(s: str | None) -> float | None:
    """parse_leading_int truncates decimals (parseInt("1.19") === 1), wrong
    for Sofascore's own "Expected goals" match stat which is a real
    decimal ("1.19", never a "count (%)" shape) -- this is the
    float-preserving equivalent, used only for that one stat."""
    if not s:
        return None
    import re

    m = re.match(r"\s*([+-]?\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


def stat_for(match_stats: list[MatchStatItem] | None, name: str, own_venue: str) -> int | None:
    item = next((s for s in (match_stats or []) if s.name == name), None)
    if not item:
        return None
    return parse_leading_int(item.home if own_venue == "home" else item.away)


def _stat_for_any(match_stats: list[MatchStatItem] | None, names: tuple[str, ...], own_venue: str) -> int | None:
    """First of `names` (see ADVANCED_STAT_NAMES) actually present in
    `match_stats`, from whichever source provided it."""
    for name in names:
        value = stat_for(match_stats, name, own_venue)
        if value is not None:
            return value
    return None


# A per-match team total covering ~90 minutes at match pace is always in
# roughly this range regardless of source -- Sofascore's own "Distance
# covered" is already km ("108.5"), confirmed live Fotmob's is meters as a
# plain integer ("118485"); nothing this large is a real km figure.
_PLAUSIBLE_MAX_KM_PER_MATCH = 200


def _km_from_distance_stat(raw_value: int | None) -> int | None:
    if raw_value is None or raw_value <= _PLAUSIBLE_MAX_KM_PER_MATCH:
        return raw_value
    return round(raw_value / 1000)


def _big_chances_scored(match_stats: list[MatchStatItem] | None, own_venue: str) -> int | None:
    """Fotmob has no direct "Big chances scored" stat, but "Big chances"
    minus "Big chances missed" is exactly that (every big chance is either
    scored or missed) -- confirmed both are present together whenever
    Fotmob's stats appear at all."""
    total = stat_for(match_stats, _BIG_CHANCES_STAT_NAME, own_venue)
    missed = stat_for(match_stats, _BIG_CHANCES_MISSED_STAT_NAME, own_venue)
    return None if total is None or missed is None else total - missed


def stat_for_float(match_stats: list[MatchStatItem] | None, name: str, own_venue: str) -> float | None:
    item = next((s for s in (match_stats or []) if s.name == name), None)
    if not item:
        return None
    return parse_leading_float(item.home if own_venue == "home" else item.away)


class _UsageAccumulator:
    """Internal accumulator, not the public PlayerUsagePattern shape --
    carries a rating_sum that's stripped off (into avg_rating) once
    tallying is done for the whole sample."""

    def __init__(self) -> None:
        self.matches_in_squad = 0
        self.starts = 0
        self.sub_appearances = 0
        self.unused_bench = 0
        self.total_minutes = 0
        self.total_goals = 0
        self.total_assists = 0
        self.total_xg = 0.0
        self.total_xa = 0.0
        self.total_shots = 0
        self.total_shots_on_target = 0
        self.total_tackles = 0
        self.total_interceptions = 0
        self.total_fouls = 0
        self.total_key_passes = 0
        self.appearances_with_stats = 0
        self.rating_sum = 0.0
        self.wide_back_starts = 0
        self.central_back_starts = 0


def _tally_player_stats(entry: _UsageAccumulator, p: LineupPlayer) -> None:
    entry.total_goals += p.goals or 0
    entry.total_assists += p.assists or 0
    entry.total_xg += p.xg or 0
    entry.total_xa += p.xa or 0
    entry.total_shots += p.shots or 0
    entry.total_shots_on_target += p.shots_on_target or 0
    entry.total_tackles += p.tackles or 0
    entry.total_interceptions += p.interceptions or 0
    entry.total_fouls += p.fouls or 0
    entry.total_key_passes += p.key_passes or 0
    if p.rating is not None:
        entry.rating_sum += p.rating
        entry.appearances_with_stats += 1


_BACK_LINE_SIZES_WITH_WIDE_SLOTS = (4, 5)


def _back_line_slots(lineup: list[LineupPlayer] | None, formation: str | None) -> list[tuple[LineupPlayer, bool]]:
    """(player, is_wide) for each member of the back line, from lineup
    order + formation: index 0 is the goalkeeper, the next N (the
    formation's first number) are the back line right-to-left, so the
    first and last of a 4- or 5-man line are the full-/wing-backs and the
    rest are central. Empty when the shape can't be trusted (no lineup or
    formation, first player not a keeper, unparsable formation); a
    3-man line is all central."""
    if not lineup or not formation or lineup[0].position != "G":
        return []
    head = formation.split("-", 1)[0]
    if not head.isdigit():
        return []
    size = int(head)
    line = lineup[1 : 1 + size]
    if len(line) != size:
        return []
    wide_ends = size in _BACK_LINE_SIZES_WITH_WIDE_SLOTS
    return [(p, wide_ends and i in (0, size - 1)) for i, p in enumerate(line)]


def _tally_usage(
    usage_by_player: dict[str, _UsageAccumulator],
    lineup: list[LineupPlayer] | None,
    bench: list[LineupPlayer] | None,
    formation: str | None = None,
) -> None:
    def get(name: str) -> _UsageAccumulator:
        return usage_by_player.setdefault(name, _UsageAccumulator())

    for p in lineup or []:
        entry = get(normalize_team_name(p.name))
        entry.matches_in_squad += 1
        entry.starts += 1
        entry.total_minutes += p.minutes_played or 0
        _tally_player_stats(entry, p)
    for p, is_wide in _back_line_slots(lineup, formation):
        entry = get(normalize_team_name(p.name))
        if is_wide:
            entry.wide_back_starts += 1
        else:
            entry.central_back_starts += 1
    for p in bench or []:
        entry = get(normalize_team_name(p.name))
        entry.matches_in_squad += 1
        if p.minutes_played is not None:
            entry.sub_appearances += 1
            _tally_player_stats(entry, p)
            entry.total_minutes += p.minutes_played
        else:
            entry.unused_bench += 1


class VenueEnrichmentResult:
    def __init__(
        self,
        form: FormSummary,
        advanced_stats: SeasonAdvancedStatsEstimate | None,
        usage_by_player: dict[str, PlayerUsagePattern],
    ) -> None:
        self.form = form
        self.advanced_stats = advanced_stats
        self.usage_by_player = usage_by_player


class _SetPieceAccumulator:
    """Internal accumulator for the scalar totals
    enrich_form_with_venue_classification used to carry as bare local
    variables -- bundled into one mutable object purely so the per-match
    processing loop can be extracted into its own function (python:S3776)
    without threading a dozen separate `nonlocal`-style scalars through
    it. Behavior unchanged."""

    def __init__(self) -> None:
        self.corner_goals_for = 0
        self.corner_goals_against = 0
        self.penalty_goals_for = 0
        self.penalty_goals_against = 0
        self.free_kick_goals_for = 0
        self.free_kick_goals_against = 0
        self.non_penalty_xg_for = 0.0
        self.non_penalty_xg_against = 0.0
        self.set_piece_xg_for = 0.0
        self.set_piece_xg_against = 0.0
        self.penalties_awarded_for = 0
        self.penalties_awarded_against = 0
        self.xa_for = 0.0
        self.xa_against = 0.0


def _empty_venue_bucket() -> dict[str, float]:
    return {
        "sample_size": 0, "xg_for": 0, "xg_against": 0, "shots_for": 0, "shots_against": 0,
        "shots_on_target_for": 0, "shots_on_target_against": 0, "possession_sum": 0, "possession_n": 0,
        "corners_for": 0, "corners_against": 0, "fouls_for": 0, "fouls_against": 0,
        "yellow_cards_for": 0, "yellow_cards_against": 0, "red_cards_for": 0, "red_cards_against": 0,
        "big_chances_created_for": 0, "big_chances_created_against": 0,
    }


def _sum_xa(lineup: list[LineupPlayer] | None, bench: list[LineupPlayer] | None) -> float:
    return sum((p.xa or 0) for p in [*(lineup or []), *(bench or [])])


def _find_raw_match(raw_matches: list[MatchInfo], result: FormResult) -> MatchInfo | None:
    return next(
        (
            m
            for m in raw_matches
            if m.kickoff_utc == result.date
            and (
                normalize_team_name(m.home_team) == normalize_team_name(result.opponent)
                or normalize_team_name(m.away_team) == normalize_team_name(result.opponent)
            )
        ),
        None,
    )


def _build_enriched_result(result: FormResult, details: MatchDetails) -> tuple[FormResult, bool | None, float | None, float | None]:
    """The FormResult itself plus the 3 derived values later steps also
    need (neutral_venue/xg_for/xg_against), extracted from
    _process_one_result to keep its own cognitive complexity down
    (python:S3776); behavior unchanged."""
    own_country = details.home_team_country if result.venue == "home" else details.away_team_country
    neutral_venue = (own_country != details.venue_country) if (own_country and details.venue_country) else None
    if details.home_score_ht is not None and details.away_score_ht is not None:
        ht_scoreline = (
            f"{details.home_score_ht}-{details.away_score_ht}"
            if result.venue == "home"
            else f"{details.away_score_ht}-{details.home_score_ht}"
        )
    else:
        ht_scoreline = None
    opp_venue = "away" if result.venue == "home" else "home"
    xg_for = stat_for_float(details.match_stats, "Expected goals", result.venue)
    xg_against = stat_for_float(details.match_stats, "Expected goals", opp_venue)
    enriched_result = FormResult(
        opponent=result.opponent, competition=result.competition, date=result.date, result=result.result,
        scoreline=result.scoreline, venue=result.venue, margin=result.margin,
        neutral_venue=neutral_venue, ht_scoreline=ht_scoreline, xg_for=xg_for, xg_against=xg_against,
    )
    return enriched_result, neutral_venue, xg_for, xg_against


def _accumulate_stat_totals(
    stat_totals: dict[str, dict[str, float]],
    details: MatchDetails,
    result: FormResult,
    opp_venue: str,
) -> None:
    """Extracted from _process_one_result -- see _build_enriched_result's
    own doc comment for why."""
    for key, stat_names in ADVANCED_STAT_NAMES.items():
        for_val = _stat_for_any(details.match_stats, stat_names, result.venue)
        against_val = _stat_for_any(details.match_stats, stat_names, opp_venue)
        if key == "big_chances_scored" and for_val is None and against_val is None:
            for_val = _big_chances_scored(details.match_stats, result.venue)
            against_val = _big_chances_scored(details.match_stats, opp_venue)
        if key == "distance_covered_km":
            for_val, against_val = _km_from_distance_stat(for_val), _km_from_distance_stat(against_val)
        if for_val is not None and against_val is not None:
            stat_totals[key]["for"] += for_val
            stat_totals[key]["against"] += against_val
            stat_totals[key]["n"] += 1


def _accumulate_venue_bucket(
    venue_buckets: dict[str, dict[str, float]],
    details: MatchDetails,
    result: FormResult,
    opp_venue: str,
    xg_for: float | None,
    xg_against: float | None,
) -> None:
    """Extracted from _process_one_result -- see _build_enriched_result's
    own doc comment for why. Caller already checked neutral_venue is not
    None before calling this."""
    bucket = venue_buckets["neutral"] if result.neutral_venue else venue_buckets[result.venue]

    def both_sides(name: str) -> tuple[float, float]:
        return (
            stat_for(details.match_stats, name, result.venue) or 0,
            stat_for(details.match_stats, name, opp_venue) or 0,
        )

    bucket["sample_size"] += 1
    bucket["xg_for"] += xg_for or 0
    bucket["xg_against"] += xg_against or 0
    shots_f, shots_a = both_sides("Total shots")
    bucket["shots_for"] += shots_f
    bucket["shots_against"] += shots_a
    sot_f, sot_a = both_sides("Shots on target")
    bucket["shots_on_target_for"] += sot_f
    bucket["shots_on_target_against"] += sot_a
    possession = stat_for(details.match_stats, "Ball possession", result.venue)
    if possession is not None:
        bucket["possession_sum"] += possession
        bucket["possession_n"] += 1
    corners_f, corners_a = both_sides("Corner kicks")
    bucket["corners_for"] += corners_f
    bucket["corners_against"] += corners_a
    fouls_f, fouls_a = both_sides("Fouls")
    bucket["fouls_for"] += fouls_f
    bucket["fouls_against"] += fouls_a
    yellow_f, yellow_a = both_sides("Yellow cards")
    bucket["yellow_cards_for"] += yellow_f
    bucket["yellow_cards_against"] += yellow_a
    red_f, red_a = both_sides("Red cards")
    bucket["red_cards_for"] += red_f
    bucket["red_cards_against"] += red_a
    big_f, big_a = both_sides(_BIG_CHANCES_STAT_NAME)
    bucket["big_chances_created_for"] += big_f
    bucket["big_chances_created_against"] += big_a


def _accumulate_usage_and_xa(
    usage_by_player: dict[str, _UsageAccumulator],
    acc: _SetPieceAccumulator,
    details: MatchDetails,
    result: FormResult,
) -> None:
    """Extracted from _process_one_result -- see _build_enriched_result's
    own doc comment for why."""
    own_lineup = details.home_lineup if result.venue == "home" else details.away_lineup
    own_bench = details.home_bench if result.venue == "home" else details.away_bench
    opp_lineup = details.away_lineup if result.venue == "home" else details.home_lineup
    opp_bench = details.away_bench if result.venue == "home" else details.home_bench
    own_formation = details.home_formation if result.venue == "home" else details.away_formation
    _tally_usage(usage_by_player, own_lineup, own_bench, own_formation)
    acc.xa_for += _sum_xa(own_lineup, own_bench)
    acc.xa_against += _sum_xa(opp_lineup, opp_bench)


def _accumulate_set_piece_and_shotmap(acc: _SetPieceAccumulator, details: MatchDetails, result: FormResult) -> None:
    """Extracted from _process_one_result -- see _build_enriched_result's
    own doc comment for why."""
    if details.set_piece_goals:
        own = details.set_piece_goals.home if result.venue == "home" else details.set_piece_goals.away
        opp = details.set_piece_goals.away if result.venue == "home" else details.set_piece_goals.home
        acc.corner_goals_for += own.corner
        acc.corner_goals_against += opp.corner
        acc.penalty_goals_for += own.penalty
        acc.penalty_goals_against += opp.penalty
        acc.free_kick_goals_for += own.free_kick
        acc.free_kick_goals_against += opp.free_kick

    if details.shotmap_stats:
        own = details.shotmap_stats.home if result.venue == "home" else details.shotmap_stats.away
        opp = details.shotmap_stats.away if result.venue == "home" else details.shotmap_stats.home
        acc.non_penalty_xg_for += own.non_penalty_xg
        acc.non_penalty_xg_against += opp.non_penalty_xg
        acc.set_piece_xg_for += own.set_piece_xg
        acc.set_piece_xg_against += opp.set_piece_xg
        acc.penalties_awarded_for += own.penalties_awarded
        acc.penalties_awarded_against += opp.penalties_awarded


async def _process_one_result(
    result: FormResult,
    raw_matches: list[MatchInfo],
    source: Source,
    stat_totals: dict[str, dict[str, float]],
    venue_buckets: dict[str, dict[str, float]],
    usage_by_player: dict[str, _UsageAccumulator],
    acc: _SetPieceAccumulator,
) -> FormResult:
    """One iteration of enrich_form_with_venue_classification's per-result
    loop -- mutates stat_totals/venue_buckets/usage_by_player/acc in place
    (all mutable containers/objects, so updates are visible to the
    caller) and returns the FormResult to append. Its own body is now
    just a sequence of calls to the accumulator helpers above (each
    extracted for the same cognitive-complexity reason, python:S3776);
    behavior unchanged, including falling back to the original `result`
    unenriched on any exception (mirrors TS's catch { enriched.push(result) })."""
    from .orchestrate import (
        SCRAPERS,  # local import: orchestrate imports form, avoid a cycle
    )
    from .sites.sofascore import SofascoreBlockedError

    raw = _find_raw_match(raw_matches, result)
    if raw is None:
        return result
    try:
        details: MatchDetails = await SCRAPERS[source].details(raw)
        cache_match_details(raw, details)
        enriched_result, neutral_venue, xg_for, xg_against = _build_enriched_result(result, details)
        opp_venue = "away" if result.venue == "home" else "home"

        _accumulate_stat_totals(stat_totals, details, result, opp_venue)
        if neutral_venue is not None:
            _accumulate_venue_bucket(venue_buckets, details, enriched_result, opp_venue, xg_for, xg_against)
        _accumulate_usage_and_xa(usage_by_player, acc, details, result)
        _accumulate_set_piece_and_shotmap(acc, details, result)
        return enriched_result
    except SofascoreBlockedError:
        # Re-raise so enrich_form_with_venue_classification can stop the
        # rest of the last-20 window without one browser launch per match.
        raise
    except Exception as err:  # noqa: BLE001  # mirrors TS's catch { enriched.push(result) }
        record_step_failure("form enrichment: past-match details", err)
        return result


def _compute_venue_split_form(enriched: list[FormResult]) -> VenueSplitForm | None:
    """Extracted from enrich_form_with_venue_classification to keep its
    own cognitive complexity down (python:S3776); behavior unchanged."""
    home_ss = home_w = home_d = home_l = home_gf = home_ga = 0
    away_ss = away_w = away_d = away_l = away_gf = away_ga = 0
    neutral_ss = neutral_w = neutral_d = neutral_l = neutral_gf = neutral_ga = 0
    for r in enriched:
        if r.neutral_venue is None:
            continue
        bucket_name = "neutral" if r.neutral_venue else r.venue
        g = result_goals(r)
        if bucket_name == "neutral":
            neutral_ss += 1
            neutral_gf += g["for"]
            neutral_ga += g["against"]
            neutral_w += r.result == "W"
            neutral_d += r.result == "D"
            neutral_l += r.result == "L"
        elif bucket_name == "home":
            home_ss += 1
            home_gf += g["for"]
            home_ga += g["against"]
            home_w += r.result == "W"
            home_d += r.result == "D"
            home_l += r.result == "L"
        else:
            away_ss += 1
            away_gf += g["for"]
            away_ga += g["against"]
            away_w += r.result == "W"
            away_d += r.result == "D"
            away_l += r.result == "L"

    if not any(r.neutral_venue is not None for r in enriched):
        return None
    return VenueSplitForm(
        home_sample_size=home_ss, home_wins=home_w, home_draws=home_d, home_losses=home_l,
        home_goals_for=home_gf, home_goals_against=home_ga,
        away_sample_size=away_ss, away_wins=away_w, away_draws=away_d, away_losses=away_l,
        away_goals_for=away_gf, away_goals_against=away_ga,
        neutral_sample_size=neutral_ss, neutral_wins=neutral_w, neutral_draws=neutral_d, neutral_losses=neutral_l,
        neutral_goals_for=neutral_gf, neutral_goals_against=neutral_ga,
    )


def _finalize_venue_bucket(b: dict[str, float]) -> VenueSplitStats:
    return VenueSplitStats(
        sample_size=int(b["sample_size"]),
        xg_for=js_round_to(b["xg_for"], 2), xg_against=js_round_to(b["xg_against"], 2),
        shots_for=int(b["shots_for"]), shots_against=int(b["shots_against"]),
        shots_on_target_for=int(b["shots_on_target_for"]), shots_on_target_against=int(b["shots_on_target_against"]),
        possession_pct_avg=(js_round_to(b["possession_sum"] / b["possession_n"], 1) if b["possession_n"] else None),
        corners_for=int(b["corners_for"]), corners_against=int(b["corners_against"]),
        fouls_for=int(b["fouls_for"]), fouls_against=int(b["fouls_against"]),
        yellow_cards_for=int(b["yellow_cards_for"]), yellow_cards_against=int(b["yellow_cards_against"]),
        red_cards_for=int(b["red_cards_for"]), red_cards_against=int(b["red_cards_against"]),
        big_chances_created_for=int(b["big_chances_created_for"]), big_chances_created_against=int(b["big_chances_created_against"]),
    )


def _compute_detailed_venue_split(venue_buckets: dict[str, dict[str, float]]) -> DetailedVenueSplitForm | None:
    """Extracted from enrich_form_with_venue_classification to keep its
    own cognitive complexity down (python:S3776); behavior unchanged."""
    total_sample = venue_buckets["home"]["sample_size"] + venue_buckets["away"]["sample_size"] + venue_buckets["neutral"]["sample_size"]
    if total_sample <= 0:
        return None
    return DetailedVenueSplitForm(
        home=_finalize_venue_bucket(venue_buckets["home"]),
        away=_finalize_venue_bucket(venue_buckets["away"]),
        neutral=_finalize_venue_bucket(venue_buckets["neutral"]),
    )


def _compute_advanced_stats(
    stat_totals: dict[str, dict[str, float]], acc: _SetPieceAccumulator, source: Source
) -> SeasonAdvancedStatsEstimate | None:
    """Extracted from enrich_form_with_venue_classification to keep its
    own cognitive complexity down (python:S3776); behavior unchanged."""
    max_n = max((t["n"] for t in stat_totals.values()), default=0)
    if not max_n:
        return None
    st = stat_totals
    # A key whose own n stayed 0 across a sample where OTHER keys did find
    # data means this specific stat is absent from the source used this
    # run (e.g. Fotmob has no "Through balls") -- its for/against below are
    # a structural 0, not "zero events happened". Named here so a consumer
    # doesn't read that 0 as real.
    unavailable_stats = sorted(key for key, totals in st.items() if totals["n"] == 0) or None
    final_third_total = st["final_third_entries"]["for"] + st["final_third_entries"]["against"]
    return SeasonAdvancedStatsEstimate(
        sample_size=int(max_n),
        unavailable_stats=unavailable_stats,
        touches_in_box_for=int(st["touches_in_box"]["for"]), touches_in_box_against=int(st["touches_in_box"]["against"]),
        crosses_for=int(st["crosses"]["for"]), crosses_against=int(st["crosses"]["against"]),
        dribbles_for=int(st["dribbles"]["for"]), dribbles_against=int(st["dribbles"]["against"]),
        through_balls_for=int(st["through_balls"]["for"]), through_balls_against=int(st["through_balls"]["against"]),
        final_third_entries_for=int(st["final_third_entries"]["for"]), final_third_entries_against=int(st["final_third_entries"]["against"]),
        recoveries_for=int(st["recoveries"]["for"]), recoveries_against=int(st["recoveries"]["against"]),
        errors_lead_to_shot_for=int(st["errors_lead_to_shot"]["for"]), errors_lead_to_shot_against=int(st["errors_lead_to_shot"]["against"]),
        errors_lead_to_goal_for=int(st["errors_lead_to_goal"]["for"]), errors_lead_to_goal_against=int(st["errors_lead_to_goal"]["against"]),
        shots_inside_box_for=int(st["shots_inside_box"]["for"]), shots_inside_box_against=int(st["shots_inside_box"]["against"]),
        shots_outside_box_for=int(st["shots_outside_box"]["for"]), shots_outside_box_against=int(st["shots_outside_box"]["against"]),
        shots_off_target_for=int(st["shots_off_target"]["for"]), shots_off_target_against=int(st["shots_off_target"]["against"]),
        blocked_shots_for=int(st["blocked_shots"]["for"]), blocked_shots_against=int(st["blocked_shots"]["against"]),
        offsides_for=int(st["offsides"]["for"]), offsides_against=int(st["offsides"]["against"]),
        big_chances_scored_for=int(st["big_chances_scored"]["for"]), big_chances_scored_against=int(st["big_chances_scored"]["against"]),
        dispossessed_for=int(st["dispossessed"]["for"]), dispossessed_against=int(st["dispossessed"]["against"]),
        team_tackles_for=int(st["team_tackles"]["for"]), team_tackles_against=int(st["team_tackles"]["against"]),
        team_interceptions_for=int(st["team_interceptions"]["for"]), team_interceptions_against=int(st["team_interceptions"]["against"]),
        goals_prevented_for=st["goals_prevented"]["for"], goals_prevented_against=st["goals_prevented"]["against"],
        big_saves_for=int(st["big_saves"]["for"]), big_saves_against=int(st["big_saves"]["against"]),
        high_claims_for=int(st["high_claims"]["for"]), high_claims_against=int(st["high_claims"]["against"]),
        distance_covered_km_for=st["distance_covered_km"]["for"], distance_covered_km_against=st["distance_covered_km"]["against"],
        sprints_for=int(st["sprints"]["for"]), sprints_against=int(st["sprints"]["against"]),
        team_clearances_for=int(st["team_clearances"]["for"]), team_clearances_against=int(st["team_clearances"]["against"]),
        free_kicks_for=int(st["free_kicks"]["for"]), free_kicks_against=int(st["free_kicks"]["against"]),
        xa_for=js_round_to(acc.xa_for, 2), xa_against=js_round_to(acc.xa_against, 2),
        corner_goals_for=acc.corner_goals_for, corner_goals_against=acc.corner_goals_against,
        penalty_goals_for=acc.penalty_goals_for, penalty_goals_against=acc.penalty_goals_against,
        free_kick_goals_for=acc.free_kick_goals_for, free_kick_goals_against=acc.free_kick_goals_against,
        total_shots_for=int(st["total_shots"]["for"]), total_shots_against=int(st["total_shots"]["against"]),
        shots_on_target_for=int(st["shots_on_target"]["for"]), shots_on_target_against=int(st["shots_on_target"]["against"]),
        corners_for=int(st["corner_kicks"]["for"]), corners_against=int(st["corner_kicks"]["against"]),
        fouls_for=int(st["fouls"]["for"]), fouls_against=int(st["fouls"]["against"]),
        yellow_cards_for=int(st["yellow_cards"]["for"]), yellow_cards_against=int(st["yellow_cards"]["against"]),
        red_cards_for=int(st["red_cards"]["for"]), red_cards_against=int(st["red_cards"]["against"]),
        possession_pct_avg=(js_round_to(st["ball_possession"]["for"] / st["ball_possession"]["n"], 1) if st["ball_possession"]["n"] else None),
        big_chances_created_for=int(st["big_chances"]["for"]), big_chances_created_against=int(st["big_chances"]["against"]),
        non_penalty_xg_for=js_round_to(acc.non_penalty_xg_for, 2), non_penalty_xg_against=js_round_to(acc.non_penalty_xg_against, 2),
        set_piece_xg_for=js_round_to(acc.set_piece_xg_for, 2), set_piece_xg_against=js_round_to(acc.set_piece_xg_against, 2),
        penalties_awarded_for=acc.penalties_awarded_for, penalties_awarded_against=acc.penalties_awarded_against,
        field_tilt_pct=(js_round_to(st["final_third_entries"]["for"] / final_third_total * 100, 1) if final_third_total > 0 else None),
        source=source,
    )


def _per90(total: float, total_minutes: int) -> float | None:
    return js_round_to(total / total_minutes * 90, 2) if total_minutes else None


def _finalize_usage(usage_by_player: dict[str, _UsageAccumulator]) -> dict[str, PlayerUsagePattern]:
    """Extracted from enrich_form_with_venue_classification to keep its
    own cognitive complexity down (python:S3776); behavior unchanged."""
    finalized_usage: dict[str, PlayerUsagePattern] = {}
    for name, entry in usage_by_player.items():
        finalized_usage[name] = PlayerUsagePattern(
            matches_in_squad=entry.matches_in_squad, starts=entry.starts, sub_appearances=entry.sub_appearances,
            unused_bench=entry.unused_bench, total_minutes=entry.total_minutes,
            total_goals=entry.total_goals, total_assists=entry.total_assists, total_xg=entry.total_xg, total_xa=entry.total_xa,
            total_shots=entry.total_shots, total_shots_on_target=entry.total_shots_on_target,
            total_tackles=entry.total_tackles, total_interceptions=entry.total_interceptions,
            total_fouls=entry.total_fouls, total_key_passes=entry.total_key_passes,
            appearances_with_stats=entry.appearances_with_stats,
            avg_rating=(js_round_to(entry.rating_sum / entry.appearances_with_stats, 2) if entry.appearances_with_stats else None),
            goals_per_90=_per90(entry.total_goals, entry.total_minutes), assists_per_90=_per90(entry.total_assists, entry.total_minutes),
            xg_per_90=_per90(entry.total_xg, entry.total_minutes), xa_per_90=_per90(entry.total_xa, entry.total_minutes),
            key_passes_per_90=_per90(entry.total_key_passes, entry.total_minutes),
            wide_back_starts=entry.wide_back_starts, central_back_starts=entry.central_back_starts,
        )
    return finalized_usage


async def enrich_form_with_venue_classification(
    raw_matches: list[MatchInfo], form: FormSummary, source: Source
) -> VenueEnrichmentResult:
    """Fetches full match details for each of the last20Overall results
    (bounded window, not the entire played history) to find out where
    each match was ACTUALLY played, not just which side of the fixture
    data the team was listed on. A match counts as neutral when the
    venue's country doesn't match the team's own country on that specific
    match's own record. The same per-match fetch also carries matchStats
    and lineup/bench statistics, so advanced-stats aggregation and
    per-player usage ride along at zero extra requests. Best-effort per
    match throughout: a handful of failed fetches just leave those
    entries/stats undetermined rather than failing the whole enrichment.

    Sofascore-specific request budget: each details() call is a full
    browser session + ~15 paced API endpoints, so a naïve 20-match loop
    for BOTH teams was ~600 Sofascore requests in one run and reliably
    tripped Cloudflare. For the Sofascore source only, enrich the most
    recent FORM_ENRICH_DETAIL_LIMIT matches and leave the rest of the
    last-20 window unenriched (same honest fallback a failed fetch
    already produces). Plain-HTTP sources keep the full 20 -- their
    details() is one small request, not a browser session."""
    from .sites.sofascore import SofascoreBlockedError, is_blocked

    stat_totals: dict[str, dict[str, float]] = {k: {"for": 0, "against": 0, "n": 0} for k in ADVANCED_STAT_NAMES}
    usage_by_player: dict[str, _UsageAccumulator] = {}
    acc = _SetPieceAccumulator()
    venue_buckets = {"home": _empty_venue_bucket(), "away": _empty_venue_bucket(), "neutral": _empty_venue_bucket()}

    enriched: list[FormResult] = []
    for index, result in enumerate(form.last20_overall):
        # After the first CDN block, stop opening new Sofascore sessions
        # for the remaining window -- is_blocked() short-circuits before
        # launch_browser, but skipping here also avoids the per-call
        # exception path 19 more times.
        if source == "sofascore" and is_blocked():
            enriched.append(result)
            continue
        if source == "sofascore" and index >= FORM_ENRICH_DETAIL_LIMIT:
            enriched.append(result)
            continue
        try:
            enriched.append(await _process_one_result(result, raw_matches, source, stat_totals, venue_buckets, usage_by_player, acc))
        except SofascoreBlockedError:
            enriched.append(result)

    venue_split_form = _compute_venue_split_form(enriched)
    detailed_venue_split = _compute_detailed_venue_split(venue_buckets)
    advanced_stats = _compute_advanced_stats(stat_totals, acc, source)
    finalized_usage = _finalize_usage(usage_by_player)

    # last5/10_overall and last5_home/away are separate list slices taken
    # from all_results in compute_form_summary, BEFORE this enrichment
    # runs -- replacing last20_overall alone left every other window
    # holding the original bare FormResult objects (ht_scoreline/xg_for/
    # xg_against always None), even for entries that fall inside the very
    # same last-20 window that was just enriched. Confirmed live: every
    # entry across last5/10/20_overall came back null for these three
    # fields. Re-pointing each window at its enriched counterpart (keyed
    # by date+opponent, since that's what identifies the same match)
    # fixes all of them; a window entry outside the bounded 20-match
    # enrichment scan (possible for last5_home/away on a team with a long
    # run of one-sided fixtures) falls back to its original, unenriched
    # object rather than being dropped.
    enriched_by_key = {(r.date, r.opponent): r for r in enriched}

    def _reenrich(results: list[FormResult]) -> list[FormResult]:
        return [enriched_by_key.get((r.date, r.opponent), r) for r in results]

    # Recompute home/away win rates from the enriched venue_split_form
    # to ensure consistency -- previously these were computed from the
    # unenriched home_results/away_results which didn't account for
    # neutral-venue reclassification, causing contradictions with
    # venue_split_form's own win counts. Sample sizes must move with the
    # rates: leaving the full-history n beside an enriched-window rate
    # (Sofascore only classifies FORM_ENRICH_DETAIL_LIMIT matches) made
    # JSON pair e.g. 60% with n=34.
    home_win_rate_pct = form.home_win_rate_pct
    away_win_rate_pct = form.away_win_rate_pct
    home_win_rate_sample_size = form.home_win_rate_sample_size
    away_win_rate_sample_size = form.away_win_rate_sample_size
    if venue_split_form:
        if venue_split_form.home_sample_size:
            home_win_rate_pct = js_round(venue_split_form.home_wins / venue_split_form.home_sample_size * 100)
            home_win_rate_sample_size = venue_split_form.home_sample_size
        if venue_split_form.away_sample_size:
            away_win_rate_pct = js_round(venue_split_form.away_wins / venue_split_form.away_sample_size * 100)
            away_win_rate_sample_size = venue_split_form.away_sample_size

    new_form = FormSummary(
        **{
            **form.__dict__,
            "last5_overall": _reenrich(form.last5_overall),
            "last10_overall": _reenrich(form.last10_overall),
            "last20_overall": enriched,
            "last5_home": _reenrich(form.last5_home),
            "last5_away": _reenrich(form.last5_away),
            "venue_split_form": venue_split_form,
            "detailed_venue_split": detailed_venue_split,
            "home_win_rate_pct": home_win_rate_pct,
            "away_win_rate_pct": away_win_rate_pct,
            "home_win_rate_sample_size": home_win_rate_sample_size,
            "away_win_rate_sample_size": away_win_rate_sample_size,
        }
    )
    return VenueEnrichmentResult(form=new_form, advanced_stats=advanced_stats, usage_by_player=finalized_usage)
