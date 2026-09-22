"""How good have this app's own past predictions actually been?

There is no server-side archive, so the caller (the Android app's History)
hands over the predictions it already saved as compact records; each is
checked against the finished results this run has fetched anyway. Only
predictions made BEFORE kickoff count, and only those whose match result is
found -- the rest are reported as pending, never guessed.

Scores (all lower-is-better except accuracy):
- Brier score: sum over the 3 outcomes of (p - actual)^2, 0 = perfect,
  2 = worst; always guessing 1/3 each scores 2/3 (~0.667).
- Log loss: -ln(probability given to what actually happened).
"""

from __future__ import annotations

import math
from typing import Any

from .team_aliases import same_team
from .types import CalibrationSummary, MatchInfo, MethodCalibration

_METHODS = ("blended", "market_implied", "heuristic_blend", "xg_model")
_UNIFORM_BRIER = 2 / 3
_MIN_PROBABILITY = 1e-9


def _probabilities(method_probs: dict[str, Any] | None) -> tuple[float, float, float] | None:
    """(home, draw, away) as fractions summing to 1, from a report's
    percent-based OutcomeProbabilities dict; None if absent/degenerate."""
    if not method_probs:
        return None
    try:
        home, draw, away = (float(method_probs[k]) for k in ("home_win_pct", "draw_pct", "away_win_pct"))
    except (KeyError, TypeError, ValueError):
        return None
    total = home + draw + away
    return (home / total, draw / total, away / total) if total > 0 else None


def _outcome_index(match: MatchInfo) -> int:
    """0 = home win, 1 = draw, 2 = away win."""
    if match.home_score > match.away_score:
        return 0
    return 1 if match.home_score == match.away_score else 2


def brier_score(probs: tuple[float, float, float], outcome: int) -> float:
    return sum((p - (1.0 if i == outcome else 0.0)) ** 2 for i, p in enumerate(probs))


def log_loss(probs: tuple[float, float, float], outcome: int) -> float:
    return -math.log(max(probs[outcome], _MIN_PROBABILITY))


def _latest_pre_kickoff(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One record per match: the newest prediction generated before that
    match's kickoff (a re-run after kickoff would leak the answer)."""
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in records:
        home, away, kickoff = r.get("home_team"), r.get("away_team"), r.get("kickoff_utc")
        generated = r.get("generated_at")
        if not (home and away and kickoff and generated) or generated >= kickoff:
            continue
        key = (home.lower(), away.lower(), kickoff[:10])
        if key not in best or generated > best[key]["generated_at"]:
            best[key] = r
    return list(best.values())


def _find_result(record: dict[str, Any], matches: list[MatchInfo]) -> MatchInfo | None:
    day = record["kickoff_utc"][:10]
    return next(
        (
            m for m in matches
            if m.home_score is not None and m.away_score is not None and (m.kickoff_utc or "")[:10] == day
            and same_team(m.home_team, record["home_team"]) and same_team(m.away_team, record["away_team"])
        ),
        None,
    )


def _method_summary(method: str, scored: list[tuple[tuple[float, float, float], int]]) -> MethodCalibration:
    n = len(scored)
    return MethodCalibration(
        method=method, sample_size=n,
        brier_score=round(sum(brier_score(p, o) for p, o in scored) / n, 4),
        log_loss=round(sum(log_loss(p, o) for p, o in scored) / n, 4),
        accuracy_pct=round(100 * sum(1 for p, o in scored if p.index(max(p)) == o) / n, 1),
    )


def _score_one_record(record: dict[str, Any], outcome: int, per_method: dict[str, list]) -> bool:
    """Adds `record`'s per-method probabilities (that parse) to
    `per_method`; returns whether the blended method itself was usable, the
    signal `evaluated` counts on."""
    got_blended = False
    for method in _METHODS:
        probs = _probabilities((record.get("prediction") or {}).get(method))
        if probs is not None:
            per_method[method].append((probs, outcome))
            got_blended = got_blended or method == "blended"
    return got_blended


def compute_calibration(past_predictions: list[dict[str, Any]], matches: list[MatchInfo]) -> CalibrationSummary:
    """`past_predictions`: dicts with home_team, away_team, kickoff_utc,
    generated_at and prediction (the report's own prediction block).
    `matches`: every played/upcoming MatchInfo this run has for the teams
    involved; a prediction is evaluated only when its finished match is in
    there."""
    per_method: dict[str, list[tuple[tuple[float, float, float], int]]] = {m: [] for m in _METHODS}
    evaluated = pending = 0
    for record in _latest_pre_kickoff(past_predictions):
        played = _find_result(record, matches)
        if played is None:
            pending += 1
            continue
        evaluated += _score_one_record(record, _outcome_index(played), per_method)
    by_method = [_method_summary(m, scored) for m, scored in per_method.items() if scored]
    headline = next((m for m in by_method if m.method == "blended"), None)
    return CalibrationSummary(
        evaluated=evaluated, pending=pending,
        brier_score=headline.brier_score if headline else None,
        brier_skill_vs_uniform_pct=round(100 * (1 - headline.brier_score / _UNIFORM_BRIER), 1) if headline else None,
        log_loss=headline.log_loss if headline else None,
        accuracy_pct=headline.accuracy_pct if headline else None,
        by_method=by_method,
        note=(
            "Scores this app's own earlier predictions (blended = the headline) against finished results found in this run; "
            "'pending' predictions have no known result yet. Brier: 0 perfect, 0.667 = always guessing 1/3 each."
            if evaluated else
            "No earlier prediction has a known result yet -- calibration needs saved predictions whose matches have since been played."
        ),
    )
