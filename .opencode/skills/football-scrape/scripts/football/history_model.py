"""Trained national-team goal model (time-decayed, ridge-regularised
Poisson regression with a Dixon-Coles low-score correction), fitted offline
on the public international-results archive
(github.com/martj42/international_results, ~49k matches since 1872).

log(home_goals) = mu + home_adv*[not neutral] + attack[home] - defence[away]
log(away_goals) = mu                           + attack[away] - defence[home]

Pure Python on purpose (no numpy/scipy): the project targets Android
(Chaquopy) and keeps its dependency list to httpx. Fitting takes seconds on
~10k recent matches; inference is a dictionary lookup plus a score grid.

Fitted parameters live in data/history-model.json (committed seed, like the
other caches); refit with `python -m football.history_train`. Team names
resolve through national_elo's exact-name + alias matching, so clubs and
women's sides never get a rating.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .data_dir import data_dir, seed_path
from .national_elo import _normalize, _NAME_ALIASES

MAX_GOALS = 10


@dataclass
class PiModel:
    """Multinomial logistic regression on pi-ratings + Elo gap (+ neutral flag), with the per-team rating
    state frozen at fit time. Blended with the Poisson model (see PI_BLEND_WEIGHT)."""

    pi_home: dict[str, float]
    pi_away: dict[str, float]
    elo: dict[str, float]
    mean: list[float]
    std: list[float]
    weights: list[list[float]]  # 3 classes (home, draw, away) x (bias + features)


@dataclass
class FittedModel:
    mu: float
    home_adv: float
    rho: float
    attack: dict[str, float]
    defence: dict[str, float]
    as_of: str
    matches_used: int
    pi: PiModel | None = None
    # Extra log-goals for the side LISTED as home at a neutral venue (organiser / seeded team): 0.14 in the data, ~58% of the full home edge.
    neutral_adv: float = 0.0
    # Venue model (history_train.fit venue='split' / 'confed'): away-side drag at genuine home matches, per-host-confederation deviations of the home boost and away
    # drag, and each team's confederation. All empty/zero = the original single home-advantage model.
    away_adv: float = 0.0
    home_dev: dict | None = None
    away_dev: dict | None = None
    confed: dict | None = None


# Weight of the pi-ratings logistic model in the history blend (70/30 beat Poisson alone on three separate
# windows: 2018-21, 2022-23, 2024-26 -- see research/README.md).
PI_BLEND_WEIGHT = 0.3
ELO_HOME_ADV = 100.0


def _model_path() -> Path:
    return seed_path("history-model.json")


def _key(name: str) -> str:
    k = _normalize(name)
    return _NAME_ALIASES.get(k, k)


def _pi_from_json(raw: dict | None) -> PiModel | None:
    if not raw:
        return None
    return PiModel(
        pi_home={_key(k): v for k, v in raw["pi_home"].items()}, pi_away={_key(k): v for k, v in raw["pi_away"].items()},
        elo={_key(k): v for k, v in raw["elo"].items()}, mean=raw["mean"], std=raw["std"], weights=raw["weights"],
    )


def _from_json(raw: dict) -> FittedModel:
    return FittedModel(
        pi=_pi_from_json(raw.get("pi")),
        mu=raw["mu"], home_adv=raw["home_adv"], rho=raw["rho"], neutral_adv=raw.get("neutral_adv", 0.0), away_adv=raw.get("away_adv", 0.0), home_dev=raw.get("home_dev") or {}, away_dev=raw.get("away_dev") or {}, confed={_key(k): v for k, v in (raw.get("confed") or {}).items()},
        attack={_key(k): v for k, v in raw["attack"].items()},
        defence={_key(k): v for k, v in raw["defence"].items()},
        as_of=raw["as_of"], matches_used=raw.get("matches_used", 0),
    )


@lru_cache(maxsize=1)
def load_model() -> FittedModel | None:
    try:
        return _from_json(json.loads(_model_path().read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        return None


def _poisson(k: int, rate: float) -> float:
    return math.exp(-rate) * rate**k / math.factorial(k)


def _dc_tau(i: int, j: int, lam: float, mu: float, rho: float) -> float:
    """Dixon & Coles (1997) low-score dependence correction."""
    if i == 0 and j == 0:
        return 1 - lam * mu * rho
    if i == 0 and j == 1:
        return 1 + lam * rho
    if i == 1 and j == 0:
        return 1 + mu * rho
    if i == 1 and j == 1:
        return 1 - rho
    return 1.0


def score_grid(home_rate: float, away_rate: float, rho: float) -> dict[tuple[int, int], float]:
    grid = {}
    for i in range(MAX_GOALS + 1):
        pi = _poisson(i, home_rate)
        for j in range(MAX_GOALS + 1):
            grid[(i, j)] = max(0.0, pi * _poisson(j, away_rate) * _dc_tau(i, j, home_rate, away_rate, rho))
    total = sum(grid.values())
    return {k: v / total for k, v in grid.items()}


_MIN_RATE, _MAX_RATE = 0.1, 6.0


def _clamp_rate(rate: float) -> float:
    """Keeps a poorly-determined extreme team pair (sparse history, tiny
    ridge) from producing a degenerate score grid."""
    return max(_MIN_RATE, min(_MAX_RATE, rate))


def expected_goals(model: FittedModel, home: str, away: str, neutral: bool = False) -> tuple[float, float] | None:
    h, a = _key(home), _key(away)
    if h not in model.attack or a not in model.attack:
        return None
    if neutral:
        home_boost, away_boost = model.neutral_adv, 0.0
    else:
        c = (model.confed or {}).get(h)
        home_boost = model.home_adv + (model.home_dev or {}).get(c, 0.0)
        away_boost = model.away_adv + (model.away_dev or {}).get(c, 0.0)
    home_log = model.mu + home_boost + model.attack[h] - model.defence[a]
    away_log = model.mu + away_boost + model.attack[a] - model.defence[h]
    return _clamp_rate(math.exp(home_log)), _clamp_rate(math.exp(away_log))


def pi_features(pi_home: dict, pi_away: dict, elo: dict, home: str, away: str, neutral: bool) -> list[float] | None:
    """[home's home rating, home's away rating, away's home rating, away's away rating, expected goal
    difference, Elo gap/400, neutral] -- None when either team has no rating."""
    import math as _m

    if home not in elo or away not in elo:
        return None
    hh, ha = pi_home.get(home, 0.0), pi_away.get(home, 0.0)
    ah, aa = pi_home.get(away, 0.0), pi_away.get(away, 0.0)

    def g(r: float) -> float:
        return _m.copysign(10 ** (abs(r) / 3.0) - 1.0, r)

    expected = g((hh + ha) / 2) - g((ah + aa) / 2) if neutral else g(hh) - g(aa)
    gap = elo[home] + (0.0 if neutral else ELO_HOME_ADV) - elo[away]
    return [hh, ha, ah, aa, expected, gap / 400.0, 1.0 if neutral else 0.0]


def pi_probabilities(model: FittedModel, home: str, away: str, neutral: bool = False) -> tuple[float, float, float] | None:
    pm = model.pi
    if pm is None:
        return None
    x = pi_features(pm.pi_home, pm.pi_away, pm.elo, _key(home), _key(away), neutral)
    if x is None:
        return None
    z = [(v - m) / sd for v, m, sd in zip(x, pm.mean, pm.std)]
    logits = [w[0] + sum(wi * zi for wi, zi in zip(w[1:], z)) for w in pm.weights]
    top = max(logits)
    ex = [math.exp(v - top) for v in logits]
    total = sum(ex)
    return ex[0] / total, ex[1] / total, ex[2] / total


def blended_outcome(model: FittedModel, home: str, away: str, neutral: bool, poisson_probs: tuple[float, float, float]):
    """(1 - PI_BLEND_WEIGHT) * Poisson + PI_BLEND_WEIGHT * pi-ratings logit; Poisson alone when the
    pi model is missing or doesn't know a team."""
    pi = pi_probabilities(model, home, away, neutral)
    if pi is None:
        return poisson_probs
    w = PI_BLEND_WEIGHT
    return tuple((1 - w) * a + w * b for a, b in zip(poisson_probs, pi))


def predict_grid(home: str, away: str, neutral: bool = False, model: FittedModel | None = None):
    """(grid, home_rate, away_rate) or None when either team is unknown."""
    model = model or load_model()
    if model is None:
        return None
    rates = expected_goals(model, home, away, neutral)
    if rates is None:
        return None
    return score_grid(rates[0], rates[1], model.rho), rates[0], rates[1]


def predict_outcome(home: str, away: str, neutral: bool = False, model: FittedModel | None = None):
    """Blended (Poisson + pi-ratings logit) win/draw/loss probabilities as fractions, or None."""
    model = model or load_model()
    predicted = predict_grid(home, away, neutral, model) if model else None
    if predicted is None:
        return None
    grid = predicted[0]
    poisson_probs = (
        sum(p for (i, j), p in grid.items() if i > j),
        sum(p for (i, j), p in grid.items() if i == j),
        sum(p for (i, j), p in grid.items() if i < j),
    )
    return blended_outcome(model, home, away, neutral, poisson_probs)
