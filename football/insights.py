"""Per-match insight computations: standings zones, card discipline, travel,
rotation, fatigue, card risk, standings-impact simulation, and the two
season-estimate fetch loops (Fotmob match-stats, Goal.com possession).
Ported from src/search.ts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ._jsmath import js_round, js_round_to
from .form import day_diff, is_team_home, normalize_team_name, parse_leading_int
from .geo import country_distance_km, country_timezone_diff_hours, travel_time_hours
from .merge import is_attacker_role, is_defender_role, is_goalkeeper_role, is_midfield_role
from .types import (
    CardDisciplineInfo,
    CardDisciplineVenueSplit,
    DirectPlayExposureFlag,
    DuelVulnerability,
    ExperienceComparison,
    ExperienceH2HNote,
    FatigueFlag,
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
    MomentumInfo,
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
    standing: Optional[TeamStanding], competition: Optional[str], standings_table
) -> Optional[StandingsZoneInfo]:
    if not standing or not standing.total_teams:
        return None
    stakes = LEAGUE_STAKES.get(competition) if competition else None
    continental_spots = stakes["continental_spots"] if stakes else 4
    relegation_spots = stakes["relegation_spots"] if stakes else 3
    zone = (
        "top-of-table"
        if standing.position <= continental_spots
        else "relegation-zone"
        if standing.position > standing.total_teams - relegation_spots
        else "midtable"
    )

    points_from_boundary: Optional[int] = None
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


def classify_match_type(competition: Optional[str]) -> Optional[MatchType]:
    """See MatchType's doc comment -- text classification, not a distinct
    field any source publishes as a boolean."""
    if not competition:
        return None
    c = competition.lower()
    return "friendly" if ("friendly" in c or "pre-season" in c or "preseason" in c) else "competitive"


def classify_card_discipline(stats, standing: Optional[TeamStanding]) -> Optional[CardDisciplineInfo]:
    played = standing.played if standing else None
    if not stats or not played:
        return None
    yellow_per_game = js_round_to(stats.yellow_cards / played, 2)
    red_per_game = js_round_to(stats.red_cards / played, 2)
    return CardDisciplineInfo(yellow_per_game=yellow_per_game, red_per_game=red_per_game, elevated_risk=(yellow_per_game > 2.5 or red_per_game > 0.2))


def compute_travel_info(merged: MatchDetails):
    """Sofascore-only fields (venue_country/home_team_country/
    away_team_country) -- null from every other base source."""
    from .types import TravelInfo

    if not merged.venue_country or (not merged.home_team_country and not merged.away_team_country):
        return None
    home_traveling = (merged.home_team_country != merged.venue_country) if merged.home_team_country else None
    away_traveling = (merged.away_team_country != merged.venue_country) if merged.away_team_country else None
    home_km = (
        country_distance_km(merged.home_team_country, merged.venue_country)
        if (home_traveling and merged.home_team_country)
        else 0
        if home_traveling is False
        else None
    )
    away_km = (
        country_distance_km(merged.away_team_country, merged.venue_country)
        if (away_traveling and merged.away_team_country)
        else 0
        if away_traveling is False
        else None
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


def compute_opponent_rank_record(results, competition: Optional[str], standings_table, own_position: Optional[int]) -> Optional[OpponentRankRecord]:
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
        target = normalize_team_name(r.opponent)
        row = next(
            (s for s in standings_table if normalize_team_name(s.team_name) == target or target in normalize_team_name(s.team_name) or normalize_team_name(s.team_name) in target),
            None,
        )
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


def _parse_xg_stat_value(raw: Optional[str]) -> Optional[float]:
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


async def compute_recent_meetings(
    raw_matches: list[MatchInfo], form_results, opponent_name: str, source: Source
) -> Optional[list[HeadToHeadMeeting]]:
    """Sofascore's h2h endpoint only returns an aggregate tally, confirmed
    live -- no per-meeting match list exists there. This finds actual past
    meetings the honest way: scanning the already-fetched recent-form
    sample for results against this specific opponent, then
    cross-referencing the raw fixture list to fetch full details for just
    those matches. Capped at 3."""
    from .orchestrate import SCRAPERS

    target = normalize_team_name(opponent_name)
    meetings = [r for r in form_results if (lambda opp: opp == target or target in opp or opp in target)(normalize_team_name(r.opponent))]
    if not meetings:
        return None

    out: list[HeadToHeadMeeting] = []
    for meeting in meetings[:3]:
        raw = next(
            (m for m in raw_matches if m.kickoff_utc == meeting.date and (normalize_team_name(m.home_team) == target or normalize_team_name(m.away_team) == target)),
            None,
        )
        if raw is None:
            continue
        try:
            details = await SCRAPERS[source].details(raw)
            xg_stat = next((s for s in (details.match_stats or []) if "expected goals" in s.name.lower()), None)
            home_xg = _parse_xg_stat_value(xg_stat.home) if xg_stat else None
            away_xg = _parse_xg_stat_value(xg_stat.away) if xg_stat else None
            out.append(
                HeadToHeadMeeting(
                    date=meeting.date, competition=meeting.competition, scoreline=meeting.scoreline, venue=meeting.venue,
                    home_formation=details.home_formation, away_formation=details.away_formation,
                    home_xg=home_xg, away_xg=away_xg, home_lineup=details.home_lineup, away_lineup=details.away_lineup,
                )
            )
        except Exception:  # noqa: BLE001 - best-effort per past meeting
            pass
    return out if out else None


def apply_usage_pattern(squad: Optional[list[SquadMember]], usage_by_player: dict[str, PlayerUsagePattern]) -> Optional[list[SquadMember]]:
    if not squad or not usage_by_player:
        return squad
    from dataclasses import fields as _fields

    result = []
    for m in squad:
        usage = usage_by_player.get(normalize_team_name(m.name))
        if usage:
            kwargs = {f.name: getattr(m, f.name) for f in _fields(m)}
            kwargs["recent_usage"] = usage
            result.append(SquadMember(**kwargs))
        else:
            result.append(m)
    return result


def compute_squad_strength(squad: Optional[list[SquadMember]], injuries: Optional[list[SquadMember]], suspended: Optional[list[str]]) -> Optional[SquadStrengthInfo]:
    if not squad:
        return None

    def total(members: list[SquadMember]) -> Optional[float]:
        values = [m.market_value for m in members if m.market_value is not None]
        return sum(values) if values else None

    unavailable = {normalize_team_name(m.name) for m in (injuries or [])} | {normalize_team_name(n) for n in (suspended or [])}
    available = [m for m in squad if normalize_team_name(m.name) not in unavailable]
    return SquadStrengthInfo(
        total_value=total(squad),
        attack_value=total([m for m in squad if is_attacker_role(m.role)]),
        midfield_value=total([m for m in squad if is_midfield_role(m.role)]),
        defense_value=total([m for m in squad if is_defender_role(m.role)]),
        goalkeeper_value=total([m for m in squad if is_goalkeeper_role(m.role)]),
        available_value=total(available),
    )


def compute_bench_info(bench: Optional[list[LineupPlayer]], lineup: Optional[list[LineupPlayer]], squad: Optional[list[SquadMember]]):
    from .types import BenchInfo

    if not bench or not squad:
        return None
    value_by_name = {normalize_team_name(m.name): m.market_value for m in squad}

    def total(players: list[LineupPlayer]) -> Optional[float]:
        values = [value_by_name.get(normalize_team_name(p.name)) for p in players]
        values = [v for v in values if v is not None]
        return sum(values) if values else None

    return BenchInfo(bench_size=len(bench), bench_total_market_value=total(bench), starting_total_market_value=(total(lineup) if lineup else None))


def compute_presence(
    squad: Optional[list[SquadMember]],
    lineup: Optional[list[LineupPlayer]],
    bench: Optional[list[LineupPlayer]],
    injuries: Optional[list[SquadMember]],
    suspended: Optional[list[str]],
) -> Optional[list[PresenceEntry]]:
    """Present = not on the injuries or suspensions list; Absent = either
    one. Doesn't distinguish "available but not selected" from "on the
    bench" -- none of our sources publish a separate bench list beyond
    Sofascore's own."""
    if not squad:
        return None
    lineup_names = {normalize_team_name(p.name) for p in (lineup or [])}
    bench_names = {normalize_team_name(p.name) for p in bench} if bench is not None else None
    injury_by_name = {normalize_team_name(p.name): p.injury for p in (injuries or [])}
    suspended_names = {normalize_team_name(n) for n in (suspended or [])}
    result = []
    for m in squad:
        norm = normalize_team_name(m.name)
        reason = injury_by_name.get(norm) or ("Suspended" if norm in suspended_names else None)
        result.append(
            PresenceEntry(
                name=m.name, status=("A" if reason else "P"), starting=(norm in lineup_names),
                on_bench=(norm in bench_names if bench_names is not None else None), reason=reason,
            )
        )
    return result


async def compute_rotation_info(team_name: str, source: Source, matches: list[MatchInfo]) -> Optional[RotationInfo]:
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

        def defender_count(f: Optional[str]) -> Optional[int]:
            if not f:
                return None
            n = parse_leading_int(f.split("-")[0])
            return n

        prev_team_score = prev.home_score if prev_home else prev.away_score
        prev_opp_score = prev.away_score if prev_home else prev.home_score
        preceding_result = None
        if prev_team_score is not None and prev_opp_score is not None:
            preceding_result = "W" if prev_team_score > prev_opp_score else "L" if prev_team_score < prev_opp_score else "D"

        return RotationInfo(
            changed_players=changed_players, starting_xi_size=len(last_xi),
            last_match_date=last.kickoff_utc, previous_match_date=prev.kickoff_utc,
            last_formation=last_formation, previous_formation=previous_formation,
            formation_changed=(last_formation != previous_formation if last_formation and previous_formation else None),
            last_defender_count=defender_count(last_formation), previous_defender_count=defender_count(previous_formation),
            preceding_result=preceding_result,
        )
    except Exception:  # noqa: BLE001 - mirrors TS's catch { return null }
        return None


def compute_resilience(results) -> Optional[ResilienceInfo]:
    """Among results that WEREN'T wins, what share were draws -- "still
    earns a point when struggling" as an objective number."""
    non_wins = [r for r in results if r.result != "W"]
    if not non_wins:
        return None
    draws = len([r for r in non_wins if r.result == "D"])
    return ResilienceInfo(non_win_sample_size=len(non_wins), draw_share_pct=js_round(draws / len(non_wins) * 100))


def compute_rest_performance(team_name: str, matches: list[MatchInfo]) -> Optional[RestPerformanceInfo]:
    """PPG split by rest before that match, across ALL played matches on
    record. <=3 days rest is "short"."""
    played = sorted(
        (m for m in matches if m.home_score is not None and m.away_score is not None and m.kickoff_utc),
        key=lambda m: m.kickoff_utc,
    )
    if len(played) < 2:
        return None

    def points(m: MatchInfo) -> Optional[int]:
        home = is_team_home(m, team_name)
        if home is None:
            return None
        team_score = m.home_score if home else m.away_score
        opp_score = m.away_score if home else m.home_score
        return 3 if team_score > opp_score else 1 if team_score == opp_score else 0

    short_pts = short_count = long_pts = long_count = 0
    for i in range(1, len(played)):
        pts = points(played[i])
        if pts is None:
            continue
        rest_days = day_diff(played[i].kickoff_utc, played[i - 1].kickoff_utc)
        if rest_days <= 3:
            short_pts += pts
            short_count += 1
        else:
            long_pts += pts
            long_count += 1

    if not short_count and not long_count:
        return None
    return RestPerformanceInfo(
        short_rest_ppg=(js_round_to(short_pts / short_count, 2) if short_count else None), short_rest_sample_size=short_count,
        long_rest_ppg=(js_round_to(long_pts / long_count, 2) if long_count else None), long_rest_sample_size=long_count,
    )


def compute_experience_h2h(experience_comparison: Optional[ExperienceComparison], h2h: Optional[HeadToHeadSummary], own_is_home: Optional[bool]) -> Optional[ExperienceH2HNote]:
    """Correlation only, not causation -- reports whether the more
    experienced squad also happens to hold the head-to-head edge."""
    if not experience_comparison or not experience_comparison.more_experienced or not h2h or own_is_home is None:
        return None
    own_wins = h2h.home_wins if own_is_home else h2h.away_wins
    opp_wins = h2h.away_wins if own_is_home else h2h.home_wins
    h2h_leader = "even" if own_wins == opp_wins else "own" if own_wins > opp_wins else "opponent"
    aligned = (
        None
        if experience_comparison.more_experienced == "even" or h2h_leader == "even"
        else experience_comparison.more_experienced == h2h_leader
    )
    return ExperienceH2HNote(more_experienced=experience_comparison.more_experienced, h2h_leader=h2h_leader, aligned=aligned)


def compute_fatigue_flag(recent_competitions: list[str], gaps_between_last_three: list[int]) -> Optional[FatigueFlag]:
    """Flags multiple competitions AND a short average gap TOGETHER --
    either signal alone isn't flagged. <5 days average gap is the
    threshold."""
    if not gaps_between_last_three:
        return None
    avg_gap_days = js_round_to(sum(gaps_between_last_three) / len(gaps_between_last_three), 1)
    multi_competition = len(recent_competitions) > 1
    return FatigueFlag(multi_competition=multi_competition, competitions=recent_competitions, avg_gap_days=avg_gap_days, flagged=(multi_competition and avg_gap_days < 5))


def compute_home_advantage(form) -> Optional[HomeAdvantageInfo]:
    """Gap between a team's own home and away win rates -- >=20pp
    "strong", 5-20pp "slight", -5..5pp "negligible", <=-5pp "reverse"."""
    if not form or form.home_win_rate_pct is None or form.away_win_rate_pct is None:
        return None
    gap_pct = form.home_win_rate_pct - form.away_win_rate_pct
    strength = "strong" if gap_pct >= 20 else "slight" if gap_pct >= 5 else "reverse" if gap_pct <= -5 else "negligible"
    return HomeAdvantageInfo(home_win_rate_pct=form.home_win_rate_pct, away_win_rate_pct=form.away_win_rate_pct, gap_pct=gap_pct, strength=strength)


def compute_streak_stability(streak: Optional[StreakInfo], rotation: Optional[RotationInfo]) -> Optional[StreakStabilityInfo]:
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


def compute_losing_streak_context(streak: Optional[StreakInfo], xg_estimate: Optional[SeasonXGEstimate]) -> Optional[LosingStreakContextInfo]:
    """"Potential turnaround" requires a losing streak of >=2 AND actual
    goals scored at least 1 below the season xG estimate."""
    if not streak or streak.result != "L" or streak.count < 2:
        return None
    xg_delta = js_round_to(xg_estimate.actual_goals_for - xg_estimate.xg_for, 2) if xg_estimate else None
    return LosingStreakContextInfo(streak_count=streak.count, xg_delta=xg_delta, potential_turnaround=(xg_delta <= -1 if xg_delta is not None else None))


def compute_card_risks(squad: Optional[list[SquadMember]], count: int = 5) -> Optional[list[PlayerCardRisk]]:
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
    referee_name: Optional[str], referee_stats: Optional[RefereeStats], home_card_risks: Optional[list[PlayerCardRisk]], away_card_risks: Optional[list[PlayerCardRisk]]
) -> Optional[RefereeCardRiskNote]:
    """Pure synthesis of two things already computed separately -- no new
    requests."""
    from .types import FlaggedPlayer

    if not referee_name or not referee_stats:
        return None
    flagged_players = [
        *[FlaggedPlayer(name=r.name, side="home", prior_dismissal=r.prior_dismissal) for r in (home_card_risks or [])],
        *[FlaggedPlayer(name=r.name, side="away", prior_dismissal=r.prior_dismissal) for r in (away_card_risks or [])],
    ]
    if not flagged_players:
        return None
    yellow_cards_per_game = float(referee_stats.yellow_cards_per_game)
    return RefereeCardRiskNote(referee_name=referee_name, yellow_cards_per_game=yellow_cards_per_game, elevated_card_referee=(yellow_cards_per_game > 2.5), flagged_players=flagged_players)


def aerial_win_pct(aerial: Optional[SeasonAerialEstimate]) -> Optional[float]:
    if not aerial:
        return None
    total = aerial.aerial_duels_won_for + aerial.aerial_duels_won_against
    return js_round_to(aerial.aerial_duels_won_for / total * 100, 1) if total else None


def compute_set_piece_threat_flag(corners: Optional[SeasonCornersEstimate], opponent_aerial: Optional[SeasonAerialEstimate]) -> Optional[SetPieceThreatFlag]:
    if not corners:
        return None
    corners_per_game = js_round_to(corners.corners_for / corners.sample_size, 2)
    opponent_pct = aerial_win_pct(opponent_aerial)
    return SetPieceThreatFlag(corners_per_game=corners_per_game, opponent_aerial_win_pct=opponent_pct, elevated=(corners_per_game >= 5 and opponent_pct is not None and opponent_pct < 50))


def compute_direct_play_exposure_flag(passing_style: Optional[SeasonPassingStyleEstimate], opponent_aerial: Optional[SeasonAerialEstimate]) -> Optional[DirectPlayExposureFlag]:
    if not passing_style or passing_style.long_ball_share_pct is None:
        return None
    opponent_pct = aerial_win_pct(opponent_aerial)
    return DirectPlayExposureFlag(long_ball_share_pct=passing_style.long_ball_share_pct, opponent_aerial_win_pct=opponent_pct, elevated=(passing_style.long_ball_share_pct >= 15 and opponent_pct is not None and opponent_pct < 50))


def compute_duel_vulnerabilities(squad: Optional[list[SquadMember]], count: int = 5) -> Optional[list[DuelVulnerability]]:
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


def compute_fullback_exposure(squad: Optional[list[SquadMember]], count: int = 3) -> Optional[list[FullbackExposureInfo]]:
    """Above-own-team-median chances created AND below-55% ground duel
    success -- uses each team's own defenders as the baseline.
    None when there's no squad data (or too few defenders with the needed
    Squawka stats) to compute a baseline at all -- distinct from a real,
    checked [] meaning "no defender exposed". Both used to return the
    same []."""
    if not squad:
        return None
    defenders = [m for m in squad if is_defender_role(m.role) and m.defensive_stats and m.defensive_stats.chances_created is not None and m.defensive_stats.ground_duel_success_pct is not None]
    if len(defenders) < 2:
        return None
    median_chances = _median([d.defensive_stats.chances_created for d in defenders])
    candidates = [d for d in defenders if d.defensive_stats.chances_created > median_chances and d.defensive_stats.ground_duel_success_pct < 55]
    candidates.sort(key=lambda d: d.defensive_stats.chances_created, reverse=True)
    return [FullbackExposureInfo(name=d.name, chances_created=d.defensive_stats.chances_created, ground_duel_success_pct=d.defensive_stats.ground_duel_success_pct) for d in candidates[:count]]


def _simulate_new_position(standings_table, own_current_position: int, opponent_current_position: int, new_own_points: int, new_opponent_points: int) -> Optional[int]:
    """Re-ranks by matching standings-table rows by POSITION, not fuzzy
    team-name matching -- avoids an entire class of bug the name-matching
    approach elsewhere in this file is exposed to."""
    if not standings_table:
        return None
    from .types import StandingsTableRow

    simulated = [
        StandingsTableRow(team_name=r.team_name, position=r.position, points=(new_own_points if r.position == own_current_position else new_opponent_points if r.position == opponent_current_position else r.points))
        for r in standings_table
    ]
    simulated.sort(key=lambda r: (-r.points, r.position))
    idx = next((i for i, r in enumerate(simulated) if r.position == own_current_position), -1)
    return idx + 1 if idx != -1 else None


def compute_standings_impact(standing: Optional[TeamStanding], opponent_standing: Optional[TeamStanding], standings_table) -> Optional[StandingsImpactInfo]:
    if not standing or not opponent_standing or not standings_table:
        return None
    scenarios = []
    for outcome in ("win", "draw", "loss"):
        own_pts = 3 if outcome == "win" else 1 if outcome == "draw" else 0
        opp_pts = 0 if outcome == "win" else 1 if outcome == "draw" else 3
        new_points = standing.points + own_pts
        new_opponent_points = opponent_standing.points + opp_pts
        scenarios.append(
            StandingsScenario(
                outcome=outcome, new_points=new_points,
                new_position=_simulate_new_position(standings_table, standing.position, opponent_standing.position, new_points, new_opponent_points),
            )
        )
    return StandingsImpactInfo(current_position=standing.position, current_points=standing.points, scenarios=scenarios)


def is_recent_appointment(appointed_date: Optional[str]) -> Optional[bool]:
    if not appointed_date:
        return None
    dt = datetime.fromisoformat(appointed_date.replace("Z", "+00:00"))
    return (datetime.now(tz=timezone.utc) - dt).total_seconds() <= 90 * 86400


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


def compute_insights(merged: MatchDetails, own_average_age: Optional[float], own_rest_days: Optional[int], opponent: OpponentContext) -> MatchInsights:
    rest_comparison: Optional[RestComparison] = None
    if own_rest_days is not None or opponent.rest_days is not None:
        more_rested = None
        if own_rest_days is not None and opponent.rest_days is not None:
            more_rested = "even" if own_rest_days == opponent.rest_days else "own" if own_rest_days > opponent.rest_days else "opponent"
        rest_comparison = RestComparison(own_rest_days=own_rest_days, opponent_rest_days=opponent.rest_days, more_rested=more_rested)

    experience_comparison: Optional[ExperienceComparison] = None
    if own_average_age is not None or opponent.average_age is not None:
        more_experienced = None
        if own_average_age is not None and opponent.average_age is not None:
            diff = own_average_age - opponent.average_age
            more_experienced = "even" if abs(diff) < 1.5 else "own" if diff > 0 else "opponent"
        experience_comparison = ExperienceComparison(own_average_age=own_average_age, opponent_average_age=opponent.average_age, more_experienced=more_experienced)

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

    xg_for = xg_against = goals_for = goals_against = 0.0
    xg_sample_size = 0
    shots_for = shots_against = sot_for = sot_against = 0
    shots_sample_size = 0
    saves_for = shots_on_target_faced = keeper_goals_conceded = keeper_sample_size = 0
    at_home_yellow = at_home_red = at_home_sample_size = 0
    away_yellow = away_red = away_sample_size = 0
    aerial_for = aerial_against = aerial_sample_size = 0
    chances_created_for = chances_created_against = chances_missed_for = chances_missed_against = big_chances_sample_size = 0
    total_passes_for = accurate_passes_for = accurate_long_balls_for = passing_sample_size = 0
    fouls_for = fouls_against = fouls_sample_size = 0

    def find(stats, name):
        return next((s for s in (stats or []) if s.name == name), None)

    for m in finished:
        home = is_team_home(m, team_name)
        if home is None:
            continue
        try:
            details = await get_fotmob_match_details(m)
            stats = details.match_stats

            xg_stat = find(stats, "Expected goals (xG)")
            if xg_stat:
                xg_for += float(xg_stat.home if home else xg_stat.away)
                xg_against += float(xg_stat.away if home else xg_stat.home)
                goals_for += m.home_score if home else m.away_score
                goals_against += m.away_score if home else m.home_score
                xg_sample_size += 1

            shots_stat = find(stats, "Total shots")
            sot_stat = find(stats, "Shots on target")
            if shots_stat and sot_stat:
                sot_against_this_match = int(float(sot_stat.away if home else sot_stat.home))
                shots_for += int(float(shots_stat.home if home else shots_stat.away))
                shots_against += int(float(shots_stat.away if home else shots_stat.home))
                sot_for += int(float(sot_stat.home if home else sot_stat.away))
                sot_against += sot_against_this_match
                shots_sample_size += 1

                keeper_stat = find(stats, "Keeper saves")
                if keeper_stat:
                    saves_for += int(float(keeper_stat.home if home else keeper_stat.away))
                    shots_on_target_faced += sot_against_this_match
                    keeper_goals_conceded += m.away_score if home else m.home_score
                    keeper_sample_size += 1

            yellow_stat = find(stats, "Yellow cards")
            if yellow_stat:
                red_stat = find(stats, "Red cards")
                yellow = int(float(yellow_stat.home if home else yellow_stat.away))
                red = int(float(red_stat.home if home else red_stat.away)) if red_stat else 0
                if home:
                    at_home_yellow += yellow
                    at_home_red += red
                    at_home_sample_size += 1
                else:
                    away_yellow += yellow
                    away_red += red
                    away_sample_size += 1

            aerial_stat = find(stats, "Aerial duels won")
            if aerial_stat:
                for_val = parse_leading_int(aerial_stat.home if home else aerial_stat.away)
                against_val = parse_leading_int(aerial_stat.away if home else aerial_stat.home)
                if for_val is not None and against_val is not None:
                    aerial_for += for_val
                    aerial_against += against_val
                    aerial_sample_size += 1

            big_chances_stat = find(stats, "Big chances")
            big_chances_missed_stat = find(stats, "Big chances missed")
            if big_chances_stat and big_chances_missed_stat:
                chances_created_for += int(float(big_chances_stat.home if home else big_chances_stat.away))
                chances_created_against += int(float(big_chances_stat.away if home else big_chances_stat.home))
                chances_missed_for += int(float(big_chances_missed_stat.home if home else big_chances_missed_stat.away))
                chances_missed_against += int(float(big_chances_missed_stat.away if home else big_chances_missed_stat.home))
                big_chances_sample_size += 1

            # "Passes" appears TWICE in Fotmob's stats array -- the first
            # occurrence with empty home/away strings (a placeholder/header
            # row) and the second with the actual total -- explicitly
            # skipping empty values here (see the TS doc comment).
            passes_stat = next((s for s in (stats or []) if s.name == "Passes" and s.home != "" and s.away != ""), None)
            accurate_passes_stat = find(stats, "Accurate passes")
            long_balls_stat = find(stats, "Accurate long balls")
            if passes_stat and accurate_passes_stat and long_balls_stat:
                total_own = parse_leading_int(passes_stat.home if home else passes_stat.away)
                accurate_own = parse_leading_int(accurate_passes_stat.home if home else accurate_passes_stat.away)
                long_balls_own = parse_leading_int(long_balls_stat.home if home else long_balls_stat.away)
                if total_own is not None and accurate_own is not None and long_balls_own is not None:
                    total_passes_for += total_own
                    accurate_passes_for += accurate_own
                    accurate_long_balls_for += long_balls_own
                    passing_sample_size += 1

            fouls_stat = find(stats, "Fouls committed")
            if fouls_stat:
                fouls_for += int(float(fouls_stat.home if home else fouls_stat.away))
                fouls_against += int(float(fouls_stat.away if home else fouls_stat.home))
                fouls_sample_size += 1
        except Exception:  # noqa: BLE001 - one match's detail fetch failing shouldn't drop the whole estimate
            pass

    xg = (
        SeasonXGEstimate(sample_size=xg_sample_size, xg_for=js_round_to(xg_for, 2), xg_against=js_round_to(xg_against, 2), actual_goals_for=int(goals_for), actual_goals_against=int(goals_against), source="fotmob")
        if xg_sample_size
        else None
    )
    shots = (
        SeasonShotsEstimate(sample_size=shots_sample_size, shots_for=shots_for, shots_against=shots_against, shots_on_target_for=sot_for, shots_on_target_against=sot_against, source="fotmob")
        if shots_sample_size
        else None
    )
    card_split = (
        CardDisciplineVenueSplit(
            at_home_sample_size=at_home_sample_size,
            at_home_yellow_per_game=(js_round_to(at_home_yellow / at_home_sample_size, 2) if at_home_sample_size else None),
            at_home_red_per_game=(js_round_to(at_home_red / at_home_sample_size, 2) if at_home_sample_size else None),
            away_sample_size=away_sample_size,
            away_yellow_per_game=(js_round_to(away_yellow / away_sample_size, 2) if away_sample_size else None),
            away_red_per_game=(js_round_to(away_red / away_sample_size, 2) if away_sample_size else None),
            source="fotmob",
        )
        if (at_home_sample_size or away_sample_size)
        else None
    )
    aerial = SeasonAerialEstimate(sample_size=aerial_sample_size, aerial_duels_won_for=aerial_for, aerial_duels_won_against=aerial_against, source="fotmob") if aerial_sample_size else None
    big_chances = (
        SeasonBigChancesEstimate(sample_size=big_chances_sample_size, big_chances_created_for=chances_created_for, big_chances_created_against=chances_created_against, big_chances_missed_for=chances_missed_for, big_chances_missed_against=chances_missed_against, source="fotmob")
        if big_chances_sample_size
        else None
    )
    passing_style = (
        SeasonPassingStyleEstimate(
            sample_size=passing_sample_size, total_passes_for=total_passes_for, accurate_passes_for=accurate_passes_for,
            pass_accuracy_pct=(js_round_to(accurate_passes_for / total_passes_for * 100, 1) if total_passes_for else None),
            accurate_long_balls_for=accurate_long_balls_for,
            long_ball_share_pct=(js_round_to(accurate_long_balls_for / accurate_passes_for * 100, 1) if accurate_passes_for else None),
            source="fotmob",
        )
        if passing_sample_size
        else None
    )
    fouls = SeasonFoulsEstimate(sample_size=fouls_sample_size, fouls_committed_for=fouls_for, fouls_committed_against=fouls_against, source="fotmob") if fouls_sample_size else None
    goalkeeping = (
        SeasonGoalkeepingEstimate(
            sample_size=keeper_sample_size, saves_for=saves_for, shots_on_target_faced=shots_on_target_faced,
            save_pct=(js_round_to(saves_for / shots_on_target_faced * 100, 1) if shots_on_target_faced else None),
            goals_conceded=int(keeper_goals_conceded), source="fotmob",
        )
        if keeper_sample_size
        else None
    )
    return SeasonMatchStatsEstimate(xg, shots, card_split, aerial, big_chances, passing_style, fouls, goalkeeping)


class PossessionAndCornersEstimate:
    def __init__(self, possession, corners, defensive_errors):
        self.possession = possession
        self.corners = corners
        self.defensive_errors = defensive_errors


async def compute_possession_matchup(team_name: str, goal_matches: list[MatchInfo]) -> PossessionAndCornersEstimate:
    """>=55% opponent possession is the "high" threshold. "Corner total"
    and "Defensive error" come free from the same Goal.com match-detail
    fetch already made for the possession stat."""
    import re

    from .sites.goal import get_goal_match_details

    finished = sorted(
        (m for m in goal_matches if m.status == "finished" and m.kickoff_utc), key=lambda m: m.kickoff_utc, reverse=True
    )[:10]
    if not finished:
        return PossessionAndCornersEstimate(None, None, None)

    high_pts = high_count = other_pts = other_count = 0
    corners_for = corners_against = corners_sample_size = 0
    def_errors_for = def_errors_against = def_errors_sample_size = 0

    for m in finished:
        home = is_team_home(m, team_name)
        if home is None:
            continue
        try:
            details = await get_goal_match_details(m)
            possession_stat = next((s for s in (details.match_stats or []) if re.search("possession", s.name, re.IGNORECASE)), None)
            if possession_stat:
                try:
                    opponent_possession = float(possession_stat.away if home else possession_stat.home)
                except ValueError:
                    opponent_possession = float("nan")
                if opponent_possession == opponent_possession:  # not NaN
                    team_score = m.home_score if home else m.away_score
                    opp_score = m.away_score if home else m.home_score
                    pts = 3 if team_score > opp_score else 1 if team_score == opp_score else 0
                    if opponent_possession >= 55:
                        high_pts += pts
                        high_count += 1
                    else:
                        other_pts += pts
                        other_count += 1

            corners_stat = next((s for s in (details.match_stats or []) if s.name == "Corner total"), None)
            if corners_stat:
                corners_for += int(float(corners_stat.home if home else corners_stat.away))
                corners_against += int(float(corners_stat.away if home else corners_stat.home))
                corners_sample_size += 1

            def_errors_stat = next((s for s in (details.match_stats or []) if s.name == "Defensive error"), None)
            if def_errors_stat:
                def_errors_for += int(float(def_errors_stat.home if home else def_errors_stat.away))
                def_errors_against += int(float(def_errors_stat.away if home else def_errors_stat.home))
                def_errors_sample_size += 1
        except Exception:  # noqa: BLE001 - one match's detail fetch failing shouldn't drop the whole estimate
            pass

    possession = (
        PossessionMatchupInfo(
            high_opponent_possession_ppg=(js_round_to(high_pts / high_count, 2) if high_count else None), high_opponent_possession_sample_size=high_count,
            other_ppg=(js_round_to(other_pts / other_count, 2) if other_count else None), other_sample_size=other_count,
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
    "base_source", "field_sources", "additional_notes", "opponent_context_error",
}

# Statuses that unambiguously mean "hasn't kicked off yet" across every
# source's own vocabulary (Sofascore: notstarted, Fotmob/Goal/SoccerDesk/
# 365Scores: scheduled). Deliberately narrow -- "live"/"inprogress",
# "postponed", "cancelled", "unknown", etc. are excluded because those
# matches can genuinely have partial real data (a live score, published
# lineups, an abandoned match's final stats), so only the two clearly
# pre-kickoff values are treated as "definitely no match-outcome data
# yet". Shared with report.py's own pruning of the same fields from the
# JSON output -- defined here (not there) since report.py already
# imports from this module, not the reverse.
_NOT_STARTED_STATUSES = {"notstarted", "scheduled"}

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


def compute_data_completeness(merged: MatchDetails, insights: Optional[MatchInsights]) -> dict[str, int]:
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
    from dataclasses import fields as _fields

    not_started = merged.status in _NOT_STARTED_STATUSES

    populated = 0
    total = 0
    for f in _fields(merged):
        if f.name in _COMPLETENESS_EXCLUDE:
            continue
        if not_started and f.name in _MATCH_OUTCOME_ONLY_FIELDS:
            continue
        total += 1
        if _is_populated(getattr(merged, f.name)):
            populated += 1
    if insights:
        for f in _fields(insights):
            if f.name in _COMPLETENESS_EXCLUDE:
                continue
            total += 1
            value = getattr(insights, f.name)
            if f.name in _CHECKED_EMPTY_LIST_FIELDS:
                if value is not None:
                    populated += 1
            elif _is_populated(value):
                populated += 1
    return {"populated": populated, "total": total}
