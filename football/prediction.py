"""Combines already-computed signals into a match outcome prediction.
Two independent methods, shown side by side rather than merged into one
opaque number -- see MatchPrediction's own doc comment in types.py for the
full reasoning behind each and their real citations.

Neither method here fetches anything new: market_implied reads the
already-fetched football-data.co.uk betting_odds, and heuristic_blend
reads the already-computed home/away EloRating (elo.py). Zero extra
requests either way.
"""

from __future__ import annotations

from typing import Optional

from .types import BettingOdds, EloRating, MatchPrediction, OutcomeProbabilities

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


def compute_match_prediction(
    betting_odds: Optional[BettingOdds], home_elo: Optional[EloRating], away_elo: Optional[EloRating]
) -> Optional[MatchPrediction]:
    market_implied: Optional[OutcomeProbabilities] = None
    if betting_odds and betting_odds.home_win_implied_pct is not None:
        market_implied = OutcomeProbabilities(
            home_win_pct=betting_odds.home_win_implied_pct,
            draw_pct=betting_odds.draw_implied_pct,
            away_win_pct=betting_odds.away_win_implied_pct,
        )

    heuristic_blend: Optional[OutcomeProbabilities] = None
    if home_elo and away_elo:
        heuristic_blend = _davidson_probabilities(home_elo.elo, away_elo.elo)

    if market_implied is None and heuristic_blend is None:
        return None
    return MatchPrediction(market_implied=market_implied, heuristic_blend=heuristic_blend)
