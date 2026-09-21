"""Combines already-computed signals into a match outcome prediction.
Three independent methods, shown side by side rather than merged into one
opaque number -- see MatchPrediction's own doc comment in types.py for the
full reasoning behind each and their real citations.

None of the three methods here fetch anything new: market_implied reads
the already-fetched football-data.co.uk betting_odds, heuristic_blend
reads the already-computed home/away EloRating (elo.py) plus rest_days/
squad_strength (both already computed by insights.py for the report's own
Context/Squad tabs), and xg_model reads the already-computed rolling xG
estimates (insights.py's SeasonXGEstimate). Zero extra requests for any
of the three.

Why rest-days and available-squad-value, and not the other signals this
project already computes (head-to-head, card discipline, weather,
manager tenure, set-piece threat)? Researched, not guessed, before
adding this:

- Rest/fixture-congestion: real, if not precisely quantified, evidence
  that less-rested teams underperform (e.g. teams on 2-3 days' rest show
  a measurable physical/tactical deficit vs. teams on 6+ days' rest in
  published sports-science reviews of fixture congestion). No study
  found gives a clean "N Elo points per rest-day" coefficient, so the
  magnitude below is a modest, capped heuristic, not a fitted one --
  same honesty standard elo.py's own goal-margin scaling already holds
  itself to (that one's own comment: "not tuned").
- Key-player availability: real evidence that injuries measurably move
  bookmaker odds and player market value (published research: a 1%
  higher probability of a serious injury is associated with a ~2.3%
  market-value drop). No clean "N Elo points per €M of missing value"
  coefficient exists either, so this is likewise a modest, capped
  heuristic using the already-computed available_value/total_value
  ratio (insights.py's SquadStrengthInfo) as the input.
- Explicitly NOT folded into the outcome math: head-to-head record
  (published research is consistent that standalone H2H is a weak
  predictor once current team strength is already accounted for --
  exactly what Elo and xG already are); card discipline, weather,
  set-piece threat, and manager tenure (no research found quantifying
  any of these as outcome-probability predictors specifically, as
  opposed to their own narrower things -- discipline predicts cards,
  not who wins). All four stay in the report as genuinely useful
  context, just not as invented prediction-math inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .types import (
    BettingOdds,
    EloRating,
    GoalMarketProbabilities,
    MatchPrediction,
    OutcomeProbabilities,
    ScorelineProbability,
    SeasonXGEstimate,
    SquadStrengthInfo,
)

# World Football Elo Ratings' (eloratings.net) publicly documented home-
# advantage constant -- a widely-cited approximation (other sources cite
# 68-100 Elo points; 100 is the most commonly referenced figure), not
# tuned to any specific league or competition.
_HOME_ADVANTAGE_ELO_POINTS = 100.0

# Davidson (1970)'s draw parameter for the three-outcome extension of the
# Elo win-probability formula -- calibrated here to football's commonly-
# cited ~25% average draw rate across Europe's top leagues (solving
# d = nu / (2 + nu) = 0.25 for two exactly-equal-strength teams), not a
# league-specific or empirically-fitted value.
_DAVIDSON_NU = 0.6667

# Rest-day adjustment: direction supported by published fixture-congestion
# research (see module docstring), magnitude is a modest, capped heuristic
# -- 5 Elo points per day of rest advantage, capped at 5 days' worth so a
# large rest gap (e.g. after an international break) can't dominate the
# whole prediction on its own.
_REST_DAY_ELO_POINTS = 5.0
_REST_DAY_ELO_CAP = 25.0

# Availability adjustment: direction supported by published injury/market-
# value research (see module docstring), magnitude is a modest, capped
# heuristic -- up to 60 Elo points off (roughly the same order of
# magnitude as the home-advantage constant above, deliberately not
# larger) for a team missing a large share of its squad's transfer value,
# scaling linearly with the missing fraction below that cap.
_AVAILABILITY_ELO_SCALE = 200.0
_AVAILABILITY_ELO_CAP = 60.0

# Poisson model: goal counts beyond this per side contribute negligible
# probability mass for realistic football xG rates (a rate of 4.0, on the
# high end of anything real, still has <0.1% mass beyond 10) -- capping
# the summation here rather than an unbounded/analytic approach keeps the
# implementation simple and dependency-free (no scipy).
_POISSON_MAX_GOALS = 10

# Home-advantage goal adjustment: the xG rates that feed this model
# (insights.py's SeasonXGEstimate) are blended across a team's last 10
# finished matches regardless of venue, so without this the Poisson model
# would have no home advantage in it at all. A precise, per-league-fitted
# home-goals bump (the standard way real Dixon-Coles implementations do
# this) needs a historical result archive this project doesn't have --
# same limitation elo.py's own docstring already states for its rating.
# Deliberately kept small and explicit rather than fitted: multiple
# practitioner sources describe home teams outscoring away teams by
# roughly a few tenths of a goal per match on average across Europe's top
# leagues; +/-0.15 sits within that commonly-cited range without claiming
# more precision than a web-search-level source actually supports.
_HOME_ADVANTAGE_GOALS = 0.15


def _davidson_probabilities(home_elo: float, away_elo: float) -> OutcomeProbabilities:
    """Davidson, R.R. (1970), "On Extending the Bradley-Terry Model to
    Accommodate Ties in Paired Comparison Experiments" -- the standard
    academic extension of a pairwise-strength model (which the Elo
    win-probability formula already is) to three outcomes. pi_i =
    10^(R_i/400) is the standard Elo strength value; the draw probability
    is proportional to nu * sqrt(pi_home * pi_away), reducing to the
    ordinary two-outcome Elo formula when nu = 0."""
    adjusted_home_elo = home_elo + _HOME_ADVANTAGE_ELO_POINTS
    pi_home = 10 ** (adjusted_home_elo / 400)
    pi_away = 10 ** (away_elo / 400)
    draw_term = _DAVIDSON_NU * (pi_home * pi_away) ** 0.5
    denom = pi_home + pi_away + draw_term
    return OutcomeProbabilities(
        home_win_pct=round(100 * pi_home / denom, 1),
        draw_pct=round(100 * draw_term / denom, 1),
        away_win_pct=round(100 * pi_away / denom, 1),
    )


def _rest_elo_adjustment(own_rest_days: int | None, opponent_rest_days: int | None) -> float:
    """Positive means this side has the rest advantage, negative means
    the opponent does. Zero (no adjustment) whenever either side's
    rest-days figure is unknown -- an absent signal should never
    silently become "even", which would be a fabricated data point, not
    a documented default."""
    if own_rest_days is None or opponent_rest_days is None:
        return 0.0
    diff_days = own_rest_days - opponent_rest_days
    points = diff_days * _REST_DAY_ELO_POINTS
    return max(-_REST_DAY_ELO_CAP, min(_REST_DAY_ELO_CAP, points))


def _availability_elo_penalty(strength: SquadStrengthInfo | None) -> float:
    """Always <= 0 -- a penalty for the team's own missing squad value,
    never a bonus. Zero whenever total/available value isn't known
    (can't compute a missing fraction without both)."""
    if strength is None or not strength.total_value or strength.total_value <= 0:
        return 0.0
    if strength.available_value is None:
        return 0.0
    missing_fraction = max(0.0, 1.0 - (strength.available_value / strength.total_value))
    penalty = missing_fraction * _AVAILABILITY_ELO_SCALE
    return -min(_AVAILABILITY_ELO_CAP, penalty)


def _poisson_pmf(k: int, rate: float) -> float:
    return math.exp(-rate) * (rate**k) / math.factorial(k)


def _poisson_score_grid(home_rate: float, away_rate: float) -> dict[tuple[int, int], float]:
    """Maher (1982)'s independent-Poisson goal model -- the foundational
    version of the approach Dixon & Coles (1997) later refined with a
    low-score dependence correction. That correction's own dependence
    parameter (rho) is normally fit from a large historical result
    archive this project doesn't have (see elo.py's own docstring on the
    same limitation for its rating), so this implementation is the plain
    independent-Poisson version, not the full Dixon-Coles correction --
    stated plainly rather than silently claiming more sophistication
    than what's actually implemented.

    Returns P(home_goals=i, away_goals=j) for every (i, j) up to
    _POISSON_MAX_GOALS each, renormalized to sum to 1.0 (the tiny
    excluded tail beyond that cap is folded back in here). Computed once
    and shared by outcome probabilities, likely scorelines, and the
    O/U 2.5 + BTTS goal markets -- all four are different summaries of
    this same grid, not four separate models."""
    home_probs = [_poisson_pmf(i, home_rate) for i in range(_POISSON_MAX_GOALS + 1)]
    away_probs = [_poisson_pmf(j, away_rate) for j in range(_POISSON_MAX_GOALS + 1)]
    grid = {(i, j): p_i * p_j for i, p_i in enumerate(home_probs) for j, p_j in enumerate(away_probs)}
    total = sum(grid.values())
    if total <= 0:
        return grid
    return {k: v / total for k, v in grid.items()}


def _poisson_outcome_probabilities(grid: dict[tuple[int, int], float]) -> OutcomeProbabilities:
    home_win = sum(p for (i, j), p in grid.items() if i > j)
    draw = sum(p for (i, j), p in grid.items() if i == j)
    away_win = sum(p for (i, j), p in grid.items() if i < j)
    return OutcomeProbabilities(
        home_win_pct=round(100 * home_win, 1),
        draw_pct=round(100 * draw, 1),
        away_win_pct=round(100 * away_win, 1),
    )


def _poisson_likely_scorelines(grid: dict[tuple[int, int], float], count: int = 3) -> list[ScorelineProbability]:
    ranked = sorted(grid.items(), key=lambda kv: kv[1], reverse=True)
    return [ScorelineProbability(home_goals=i, away_goals=j, probability_pct=round(100 * p, 1)) for (i, j), p in ranked[:count]]


def _poisson_goal_markets(grid: dict[tuple[int, int], float]) -> GoalMarketProbabilities:
    over_2_5 = sum(p for (i, j), p in grid.items() if i + j > 2.5)
    btts_yes = sum(p for (i, j), p in grid.items() if i >= 1 and j >= 1)
    return GoalMarketProbabilities(
        over_2_5_pct=round(100 * over_2_5, 1),
        under_2_5_pct=round(100 * (1 - over_2_5), 1),
        btts_yes_pct=round(100 * btts_yes, 1),
        btts_no_pct=round(100 * (1 - btts_yes), 1),
    )


def _expected_goal_rates(home_xg: SeasonXGEstimate, away_xg: SeasonXGEstimate) -> tuple[float, float] | None:
    """Standard simple attack/defense blend (average "how many I usually
    score" with "how many this opponent usually concedes") used across
    most practical from-scratch Poisson-football implementations --
    xg_for/xg_against are sums over sample_size matches (insights.py),
    divided here to get each team's own per-game rate first. Then
    _HOME_ADVANTAGE_GOALS is applied (see that constant's own comment) --
    the only adjustment this model gets; unlike heuristic_blend it does
    not receive the rest/availability adjustments, so it stays a clean
    independent read."""
    if home_xg.sample_size <= 0 or away_xg.sample_size <= 0:
        return None
    home_attack = home_xg.xg_for / home_xg.sample_size
    home_defense = home_xg.xg_against / home_xg.sample_size
    away_attack = away_xg.xg_for / away_xg.sample_size
    away_defense = away_xg.xg_against / away_xg.sample_size
    home_rate = max(0.05, (home_attack + away_defense) / 2 + _HOME_ADVANTAGE_GOALS)
    away_rate = max(0.05, (away_attack + home_defense) / 2 - _HOME_ADVANTAGE_GOALS)
    return home_rate, away_rate


def _market_implied_from_odds(betting_odds: BettingOdds | None) -> OutcomeProbabilities | None:
    """Extracted from compute_match_prediction to keep its own cognitive
    complexity down (python:S3776).

    Uses the de-vigged fair_pct fields, not the raw implied_pct fields --
    implied_pct sums to the overround (>100%), which would bias every
    blended outcome upward if fed directly into a weighted average
    alongside xg_model/heuristic_blend (which do sum to 100%)."""
    if not (betting_odds and betting_odds.home_win_fair_pct is not None):
        return None
    return OutcomeProbabilities(
        home_win_pct=betting_odds.home_win_fair_pct,
        draw_pct=betting_odds.draw_fair_pct,
        away_win_pct=betting_odds.away_win_fair_pct,
    )


def _heuristic_blend_from_elo(
    home_elo: EloRating | None,
    away_elo: EloRating | None,
    home_rest_days: int | None,
    away_rest_days: int | None,
    home_squad_strength: SquadStrengthInfo | None,
    away_squad_strength: SquadStrengthInfo | None,
) -> OutcomeProbabilities | None:
    """Extracted from compute_match_prediction to keep its own cognitive
    complexity down (python:S3776); behavior unchanged."""
    if not (home_elo and away_elo):
        return None
    adjusted_home = (
        home_elo.elo
        + _rest_elo_adjustment(home_rest_days, away_rest_days)
        + _availability_elo_penalty(home_squad_strength)
    )
    adjusted_away = (
        away_elo.elo
        + _rest_elo_adjustment(away_rest_days, home_rest_days)
        + _availability_elo_penalty(away_squad_strength)
    )
    return _davidson_probabilities(adjusted_home, adjusted_away)


@dataclass
class _XgModelResult:
    """Everything derived from the same Poisson grid the xG model
    computes -- bundled so compute_match_prediction can take it as one
    value instead of unpacking a 5-tuple. Not part of the public types
    module: purely internal plumbing between _xg_model_from_estimates
    and compute_match_prediction."""

    outcome: OutcomeProbabilities
    home_expected_goals: float
    away_expected_goals: float
    likely_scorelines: list[ScorelineProbability]
    goal_markets: GoalMarketProbabilities


def _xg_model_from_estimates(home_xg: SeasonXGEstimate | None, away_xg: SeasonXGEstimate | None) -> _XgModelResult | None:
    """Extracted from compute_match_prediction to keep its own cognitive
    complexity down (python:S3776)."""
    if not (home_xg and away_xg):
        return None
    rates = _expected_goal_rates(home_xg, away_xg)
    if rates is None:
        return None
    home_rate, away_rate = rates
    grid = _poisson_score_grid(home_rate, away_rate)
    return _XgModelResult(
        outcome=_poisson_outcome_probabilities(grid),
        home_expected_goals=round(home_rate, 2),
        away_expected_goals=round(away_rate, 2),
        likely_scorelines=_poisson_likely_scorelines(grid),
        goal_markets=_poisson_goal_markets(grid),
    )


def _blend_predictions(available: list[OutcomeProbabilities], weights: list[float]) -> tuple[OutcomeProbabilities | None, float | None]:
    """Extracted from compute_match_prediction to keep its own cognitive
    complexity down (python:S3776); behavior unchanged.

    Weighted average of available methods (market-implied gets highest
    weight -- strongest standalone predictor per research -- xg_model
    second, heuristic_blend third). Confidence is 100 minus the max
    disagreement across outcomes."""
    if len(available) < 2:
        return None, None
    total_weight = sum(weights)
    home_pct = sum(a.home_win_pct * w for a, w in zip(available, weights)) / total_weight
    draw_pct = sum(a.draw_pct * w for a, w in zip(available, weights)) / total_weight
    away_pct = sum(a.away_win_pct * w for a, w in zip(available, weights)) / total_weight
    blended = OutcomeProbabilities(
        home_win_pct=round(home_pct, 1),
        draw_pct=round(draw_pct, 1),
        away_win_pct=round(away_pct, 1),
    )
    # Confidence: 100 minus the max spread across the three outcomes
    # between any two methods. Lower disagreement = higher confidence.
    max_spreads = []
    for attr in ("home_win_pct", "draw_pct", "away_win_pct"):
        vals = [getattr(a, attr) for a in available]
        max_spreads.append(max(vals) - min(vals))
    max_disagreement = max(max_spreads)
    confidence = round(max(0, 100 - max_disagreement), 1)
    return blended, confidence


def _prediction_model_name(market_implied, heuristic_blend, xg_result) -> str | None:
    """"+"-joined names of whichever methods actually ran for this match
    -- see MatchPrediction.model's own doc comment. Extracted from
    compute_match_prediction to keep its own cognitive complexity down
    (python:S3776)."""
    names = []
    if market_implied is not None:
        names.append("market")
    if heuristic_blend is not None:
        names.append("heuristic")
    if xg_result is not None:
        names.append("xg")
    return "+".join(names) if names else None


def compute_match_prediction(
    betting_odds: BettingOdds | None,
    home_elo: EloRating | None,
    away_elo: EloRating | None,
    home_rest_days: int | None = None,
    away_rest_days: int | None = None,
    home_squad_strength: SquadStrengthInfo | None = None,
    away_squad_strength: SquadStrengthInfo | None = None,
    home_xg: SeasonXGEstimate | None = None,
    away_xg: SeasonXGEstimate | None = None,
) -> MatchPrediction | None:
    market_implied = _market_implied_from_odds(betting_odds)
    heuristic_blend = _heuristic_blend_from_elo(
        home_elo, away_elo, home_rest_days, away_rest_days, home_squad_strength, away_squad_strength
    )
    xg_result = _xg_model_from_estimates(home_xg, away_xg)
    xg_model = xg_result.outcome if xg_result else None

    if market_implied is None and heuristic_blend is None and xg_model is None:
        return None

    # Market-implied gets highest weight (strongest standalone predictor
    # per research), xg_model second, heuristic_blend third.
    available = []
    weights = []
    if market_implied is not None:
        available.append(market_implied)
        weights.append(3.0)
    if xg_model is not None:
        available.append(xg_model)
        weights.append(2.0)
    if heuristic_blend is not None:
        available.append(heuristic_blend)
        weights.append(1.0)
    blended, confidence = _blend_predictions(available, weights)

    return MatchPrediction(
        market_implied=market_implied, heuristic_blend=heuristic_blend,
        xg_model=xg_model, blended=blended, confidence=confidence,
        model=_prediction_model_name(market_implied, heuristic_blend, xg_result),
        home_expected_goals=(xg_result.home_expected_goals if xg_result else None),
        away_expected_goals=(xg_result.away_expected_goals if xg_result else None),
        likely_scorelines=(xg_result.likely_scorelines if xg_result else None),
        goal_markets=(xg_result.goal_markets if xg_result else None),
    )
