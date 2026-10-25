"""Shared betting-odds math: de-vig calculation and fractional-odds
conversion. Used by both footballdata.py (decimal odds, already in the
right format) and sofascore.py (fractional odds, needs conversion first)
so the two sources compute implied/fair/overround identically."""

from __future__ import annotations

from ._jsmath import js_round_to


def fractional_to_decimal(fractional: str) -> float:
    """"8/11" -> 1.73 (decimal odds = 1 + numerator/denominator)."""
    num, den = fractional.split("/")
    return 1 + int(num) / int(den)


def _devig(odds: list[float]) -> tuple[list[float], float, list[float]]:
    """Shared core for any N-outcome market: given N decimal odds,
    returns (raw_implied_pcts, overround_pct, fair_pcts)."""
    invs = [1 / o for o in odds]
    total = sum(invs)
    overround = js_round_to(total * 100, 1)
    raw = [js_round_to(100 * inv, 1) for inv in invs]
    fair = [js_round_to(100 * inv / total, 1) for inv in invs]
    return raw, overround, fair


def implied_and_fair_percentages(
    home_odds: float | None, draw_odds: float | None, away_odds: float | None
) -> tuple[float | None, float | None, float | None, float | None, float | None, float | None, float | None]:
    """Raw implied probabilities (100/odds, one per outcome -- these sum
    to the overround, not to 100%) plus the standard de-vig calculation
    (each outcome's 1/odds share renormalized to sum to exactly 100%) for
    the fair probabilities. Returns (home_pct, draw_pct, away_pct,
    overround_pct, home_fair, draw_fair, away_fair) -- all None unless
    every odd is present."""
    if not (home_odds and draw_odds and away_odds):
        return None, None, None, None, None, None, None
    raw, overround, fair = _devig([home_odds, draw_odds, away_odds])
    return raw[0], raw[1], raw[2], overround, fair[0], fair[1], fair[2]


def implied_and_fair_percentages_2way(
    a_odds: float | None, b_odds: float | None
) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    """Same de-vig math as implied_and_fair_percentages, for a 2-outcome
    market (e.g. Over/Under N.5 goals, or any other yes/no line). Returns
    (a_pct, b_pct, overround_pct, a_fair, b_fair) -- all None unless both
    odds are present."""
    if not (a_odds and b_odds):
        return None, None, None, None, None
    raw, overround, fair = _devig([a_odds, b_odds])
    return raw[0], raw[1], overround, fair[0], fair[1]
