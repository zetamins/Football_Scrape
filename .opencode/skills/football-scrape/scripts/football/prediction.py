"""Combines already-computed signals into a match outcome prediction.
Three independent methods, shown side by side rather than merged into one
opaque number -- see MatchPrediction's own doc comment in types.py for the
full reasoning behind each and their real citations.

None of the three methods here fetch anything new: market_implied reads
whichever already-fetched 1X2 odds orchestrate passed in
(football-data.co.uk average, or Sofascore single-book when that feed
lags), heuristic_blend reads the already-computed home/away EloRating
(elo.py) plus rest_days/squad_strength (both already computed by
insights.py for the report's own Context/Squad tabs), and xg_model reads
the already-computed rolling xG estimates (insights.py's
SeasonXGEstimate). Zero extra requests for any of the three.

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

from .history_model import predict_grid, predict_outcome
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
_DAVIDSON_NU = 0.75

# Draw uplift applied to the final blend, in percentage points. DISABLED
# (0): it was added after a 38-match sample where 34% were draws, but the
# 2,678-match out-of-sample backtest of history_model (2024-2026) shows the
# true international draw rate is 23.5% and an unadjusted model is already
# calibrated to it (23.1% predicted). The 38-match excess was variance.
_DRAW_UPLIFT_PCT = 0.0

# Blend weights. Market odds are the strongest predictor; the Elo heuristic
# backtested worse than guessing 1/3 each (Brier 0.680 vs 0.667) and pulled
# the blend below the market alone, so it only gets a token weight when a
# market exists and its old weight otherwise (it is then the only extra
# signal besides xg).
_W_MARKET = 3.0
_W_XG = 1.5
_W_HEURISTIC_WITH_MARKET = 0.5
_W_HEURISTIC_ALONE = 1.0
# With opponent-adjusted eloratings.net ratings (national_elo.py) the Elo
# method backtested at market level (Brier 0.574 vs 0.680 for the form-only
# rating), so it earns real weight.
_W_HEURISTIC_NATIONAL_ELO = 2.0
_W_SQUAD_VALUE = 0.75
# Trained history model: beat a sequential Elo baseline on 2,678 out-of-sample
# internationals (Brier 0.496 vs 0.511, draw rate calibrated). No historical
# odds exist to compare it with the market, and on the 38 live fixtures the
# market alone was best, so it ranks second.
_W_HISTORY = 2.0
_W_XG_WITH_HISTORY = 1.0
_NATIONAL_ELO_SOURCE = "eloratings.net"

# Squad-market-value model: Elo-point gap per unit of ln(value ratio). Chosen
# by grid search on 38 national-team fixtures (Brier minimum at 100 over
# 60-300; 0.609 alone vs 0.667 for guessing). Small sample; a weak signal,
# hence its small blend weight.
_SQUAD_VALUE_ELO_PER_LN = 100.0
_SQUAD_VALUE_MAX_ELO_GAP = 400.0
_METHOD_COUNT = 5

# Calibration of the pick probability -> how often such a pick is actually right: binned reliability, made monotone, measured on 8,054 held-out international
# matches 2018-2026 with rolling two-monthly refits of the venue-aware Poisson + Dixon-Coles model (the engine's own probabilities; pairs of pick probability %,
# observed accuracy %). Re-fitted after the venue and simulation fixes; the previous knots came from the old model. Caveat: fitted on the history model alone, so it
# is an approximation for blends that include the odds or the JSON-only sources.
_CONFIDENCE_KNOTS = (
    (33.3, 33.3), (37.3, 36.1), (44.9, 46.4), (52.4, 50.7), (57.5, 61.3),
    (64.9, 67.1), (74.8, 78.0), (84.7, 86.8), (95.0, 94.6), (100.0, 97.0),
)

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


def _poisson_likely_scorelines(grid: dict[tuple[int, int], float]) -> list[ScorelineProbability]:
    """Most likely scoreline within each result class (home win / draw /
    away win), ranked by probability. The plain overall top-3 was almost
    always 1-1/1-0/0-1 whenever both rates sit near 1.3 goals (the modal
    cell of a Poisson grid), which carried no information: 2 of 31 hits
    in the backtest. Per-class best scorelines say what a win would most
    likely look like on each side."""
    best: dict[str, tuple[tuple[int, int], float]] = {}
    for (i, j), p in grid.items():
        outcome = "home_win" if i > j else ("draw" if i == j else "away_win")
        if outcome not in best or p > best[outcome][1]:
            best[outcome] = ((i, j), p)
    ranked = sorted(best.items(), key=lambda kv: kv[1][1], reverse=True)
    return [
        ScorelineProbability(home_goals=i, away_goals=j, probability_pct=round(100 * p, 1), outcome=outcome)
        for outcome, ((i, j), p) in ranked
    ]


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


def _history_model_result(home_team: str | None, away_team: str | None, neutral: bool | None) -> _XgModelResult | None:
    """Trained Dixon-Coles-style model (history_model.py). Same grid-derived
    outputs as the xG model, from fitted attack/defence strengths instead of
    the last ten matches."""
    if not home_team or not away_team:
        return None
    predicted = predict_grid(home_team, away_team, bool(neutral))
    if predicted is None:
        return None
    grid, home_rate, away_rate = predicted
    outcome = _poisson_outcome_probabilities(grid)
    blended = predict_outcome(home_team, away_team, bool(neutral))
    if blended is not None:
        # Poisson + pi-ratings logit (history_model.PI_BLEND_WEIGHT); goals/scorelines stay Poisson.
        outcome = OutcomeProbabilities(
            home_win_pct=round(100 * blended[0], 1), draw_pct=round(100 * blended[1], 1), away_win_pct=round(100 * blended[2], 1),
        )
    return _XgModelResult(
        outcome=outcome,
        home_expected_goals=round(home_rate, 2),
        away_expected_goals=round(away_rate, 2),
        likely_scorelines=_poisson_likely_scorelines(grid),
        goal_markets=_poisson_goal_markets(grid),
    )


def _squad_value_model(home: SquadStrengthInfo | None, away: SquadStrengthInfo | None) -> OutcomeProbabilities | None:
    """Independent strength read from total squad market value (Transfermarkt-
    style values already on each profile): ln(value ratio) -> Elo-point gap ->
    the same Davidson three-outcome formula (home advantage included)."""
    if not (home and away and home.total_value and away.total_value):
        return None
    gap = _SQUAD_VALUE_ELO_PER_LN * math.log(home.total_value / away.total_value)
    gap = max(-_SQUAD_VALUE_MAX_ELO_GAP, min(_SQUAD_VALUE_MAX_ELO_GAP, gap))
    return _davidson_probabilities(1500.0 + gap / 2, 1500.0 - gap / 2)


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


def _apply_draw_uplift(home_pct: float, draw_pct: float, away_pct: float) -> tuple[float, float, float]:
    """Move _DRAW_UPLIFT_PCT points into the draw share, taken from home and
    away in proportion to their size, so the three still sum to 100."""
    decisive = home_pct + away_pct
    if decisive <= 0:
        return home_pct, draw_pct, away_pct
    take = min(_DRAW_UPLIFT_PCT, decisive)
    return (
        home_pct - take * home_pct / decisive,
        draw_pct + take,
        away_pct - take * away_pct / decisive,
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
    home_pct, draw_pct, away_pct = _apply_draw_uplift(home_pct, draw_pct, away_pct)
    blended = OutcomeProbabilities(
        home_win_pct=round(home_pct, 1),
        draw_pct=round(draw_pct, 1),
        away_win_pct=round(away_pct, 1),
    )
    # Confidence: 100 minus the max spread across the three outcomes
    # between any two methods, then scaled by how many of the three
    # methods actually ran. Two in-house models agreeing closely is not
    # the same as three (especially when the market check is missing) --
    # without the scale, heuristic+xg alone could read 96 while market
    # disagreed, which overstated how settled the estimate was.
    max_spreads = []
    for attr in ("home_win_pct", "draw_pct", "away_win_pct"):
        vals = [getattr(a, attr) for a in available]
        max_spreads.append(max(vals) - min(vals))
    max_disagreement = max(max_spreads)
    agreement = max(0, 100 - max_disagreement)
    confidence = round(agreement * (len(available) / _METHOD_COUNT), 1)
    return blended, confidence


_CONFIDENCE_BASIS = (
    "Calibrated: how often a pick made at this probability was right in 8,054 held-out international matches "
    "(2018-2026, history model, refit monthly); an average over matches like this one, not a guarantee"
)


def _calibrated_confidence(pick_probability_pct: float) -> float:
    """Linear interpolation through _CONFIDENCE_KNOTS: the observed hit rate of a pick made at this
    probability in the held-out backtest."""
    knots = _CONFIDENCE_KNOTS
    if pick_probability_pct <= knots[0][0]:
        return knots[0][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if pick_probability_pct <= x1:
            return round(y0 + (y1 - y0) * (pick_probability_pct - x0) / (x1 - x0), 1)
    return knots[-1][1]


def _pick(blended: OutcomeProbabilities | None) -> tuple[str | None, float | None]:
    """Most likely outcome of the blend and its probability -- the number a
    reader should act on. `confidence` is this probability mapped to the observed
    hit rate of such picks (_calibrated_confidence); `method_agreement` is only how
    closely the methods agree with each other (96 on a fixture whose pick was wrong)."""
    if blended is None:
        return None, None
    options = {"home_win": blended.home_win_pct, "draw": blended.draw_pct, "away_win": blended.away_win_pct}
    name = max(options, key=options.get)
    return name, options[name]


def _prediction_model_name(market_implied, heuristic_blend, xg_result, squad_value=None, history_model=None) -> str | None:
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
    if squad_value is not None:
        names.append("squadvalue")
    if history_model is not None:
        names.append("history")
    return "+".join(names) if names else None


def _confidence_basis(method_names: list[str], confidence: float | None, market_available: bool) -> str | None:
    if confidence is None:
        return None
    basis = (
        f"Agreement between {len(method_names)} of {_METHOD_COUNT} methods ({', '.join(method_names)}), "
        "scaled by methods that ran, not real-world accuracy"
    )
    if not market_available:
        basis += "; no market odds available, so no independent check on the model-based methods"
    return basis


def _heuristic_weight(market_present: bool, home_elo: EloRating | None, away_elo: EloRating | None) -> float:
    if home_elo and away_elo and home_elo.sample_source == _NATIONAL_ELO_SOURCE and away_elo.sample_source == _NATIONAL_ELO_SOURCE:
        return _W_HEURISTIC_NATIONAL_ELO
    return _W_HEURISTIC_WITH_MARKET if market_present else _W_HEURISTIC_ALONE


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
    home_team: str | None = None,
    away_team: str | None = None,
    neutral: bool | None = None,
) -> MatchPrediction | None:
    market_implied = _market_implied_from_odds(betting_odds)
    heuristic_blend = _heuristic_blend_from_elo(
        home_elo, away_elo, home_rest_days, away_rest_days, home_squad_strength, away_squad_strength
    )
    xg_result = _xg_model_from_estimates(home_xg, away_xg)
    squad_value = _squad_value_model(home_squad_strength, away_squad_strength)
    xg_model = xg_result.outcome if xg_result else None
    history_result = _history_model_result(home_team, away_team, neutral)
    history_model = history_result.outcome if history_result else None
    # Expected goals / scorelines / goal markets: the trained model's grid
    # when it knows both teams, else the recent-xG grid.
    grid_result = history_result or xg_result

    if market_implied is None and heuristic_blend is None and xg_model is None and squad_value is None and history_model is None:
        return None

    # Market-implied gets highest weight (strongest standalone predictor
    # per research), xg_model second, heuristic_blend third.
    available = []
    weights = []
    if market_implied is not None:
        available.append(market_implied)
        weights.append(_W_MARKET)
    if xg_model is not None:
        available.append(xg_model)
        weights.append(_W_XG_WITH_HISTORY if history_model is not None else _W_XG)
    if history_model is not None:
        available.append(history_model)
        weights.append(_W_HISTORY)
    if heuristic_blend is not None:
        available.append(heuristic_blend)
        weights.append(_heuristic_weight(market_implied is not None, home_elo, away_elo))
    if squad_value is not None:
        available.append(squad_value)
        weights.append(_W_SQUAD_VALUE)
    blended, method_agreement = _blend_predictions(available, weights)
    pick, pick_probability = _pick(blended)
    confidence = _calibrated_confidence(pick_probability) if pick_probability is not None else None

    return MatchPrediction(
        market_implied=market_implied, heuristic_blend=heuristic_blend,
        xg_model=xg_model, squad_value_model=squad_value, history_model=history_model, blended=blended, confidence=confidence, method_agreement=method_agreement,
        pick=pick, pick_probability_pct=pick_probability,
        model=_prediction_model_name(market_implied, heuristic_blend, xg_result, squad_value, history_model),
        confidence_basis=_CONFIDENCE_BASIS if confidence is not None else None,
        method_agreement_basis=_confidence_basis(
            (_prediction_model_name(market_implied, heuristic_blend, xg_result, squad_value, history_model) or "").split("+"), method_agreement, market_implied is not None
        ),
        home_expected_goals=(grid_result.home_expected_goals if grid_result else None),
        away_expected_goals=(grid_result.away_expected_goals if grid_result else None),
        likely_scorelines=(grid_result.likely_scorelines if grid_result else None),
        goal_markets=(grid_result.goal_markets if grid_result else None),
    )
