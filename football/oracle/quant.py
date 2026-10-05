"""Quantitative engine: goal-rate estimates from several independent sources, player-level absence adjustment, analytic
outcome probabilities with parameter uncertainty, and an exact score distribution (Poisson goals with a Dixon-Coles correction).

Everything is expressed as expected goals (lambda) per side; probabilities come from the Dixon-Coles score grid, computed exactly
(no sampling), never from averaging probabilities. An earlier Poisson-Gamma Monte Carlo was validated and rejected: see exact_distribution.
Sources (each returns lambda_home, lambda_away, weight, why):
  market      the pair of rates whose score grid best reproduces the de-vigged H/D/A odds (and over/under 2.5 when present)
  xg          shrunk xG for / against per game, attack x opposing defence
  results     the same from actual goals in the last 10 games, recency weighted
  strength    rating gap (Elo + squad value) -> expected goal difference around the pooled total
"""

from __future__ import annotations

import math
import random
from typing import Any

from ..history_model import expected_goals as _history_goals
from ..history_model import load_model as _history_model
from ..history_model import score_grid

BASE_GOALS = 1.30          # per team per game, international/club typical
HOME_LOG_ADV = 0.20        # +-0.20 on log rates when not neutral (validated on 8,041 matches, see analyze.py)
SHRINK_GAMES = 4.0
RECENCY_DECAY = 0.9
DC_RHO = -0.05
GOAL_CAP = 6               # per side per match in rate estimates: a 10-9 'result' is a shootout or a data error
GOALS_PER_ELO_GAP = 0.0022      # expected goal-difference per rating point (about 0.88 goals per 400 Elo)
MAX_ABSENCE_EFFECT = 0.15       # a side's rate never moves more than 15% from player absences
ATTACK_ABSENCE_SENSITIVITY = 0.8
DEFENCE_ABSENCE_SENSITIVITY = 0.7
# The odds dominate when present (share = 20 / (20 + 3.5) = 85%). On 36 labelled fixtures the quant Brier falls monotonically as the
# market weight rises (0 -> 0.6725, 4 -> 0.5990, 8 -> 0.5892, 20 -> 0.5828, odds alone 0.5739; research/market_weight_curve.py) and
# published benchmarks agree that bookmaker consensus is the bar models rarely beat. One parameter, chosen on that curve, so treat the
# exact value as soft. The other sources, absences and the LLM panel stay as corrections on top, and carry the whole prediction when
# there are no odds.
# Independent mode (default, odds are NOT an input): our trained national-team model carries the blend. On 36 labelled fixtures the odds-free Brier
# falls as its weight rises (JSON sources only 0.6576; history share 63% -> 0.6023, 77% -> 0.5985, 88% -> 0.5966, history alone 0.5954; odds alone 0.5739),
# so it gets 25 against ~3.5 for the others (88%). Without the model (clubs, unknown teams) only the weak JSON sources remain: see weak_model in the audit.
SOURCE_WEIGHTS = {"market": 20.0, "history": 25.0, "xg": 1.5, "results": 1.0, "strength": 1.0}
# The player-level absence adjustment was never validated and makes the odds-free prediction WORSE as its strength rises (38 fixtures: Brier 0.6176 with none,
# 0.6207 at 0.25x, 0.6237 at 0.5x, 0.6278 at 1x; difference vs none +0.0102, 95% CI -0.003..+0.025). It is therefore computed and reported but applied at scale 0
# until evidence says otherwise (set ABSENCE_APPLY_SCALE to enable).
# With odds in the blend (--with-odds) the history model adds little: market 20 + history 0 / 6 / 25 -> Brier 0.5747 / 0.5763 / 0.5800 on 36 fixtures; keep a small share.
HISTORY_WEIGHT_WITH_ODDS = 6.0
ABSENCE_APPLY_SCALE = 0.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _grid_outcomes(grid) -> tuple[float, float, float]:
    return (sum(p for (i, j), p in grid.items() if i > j), sum(p for (i, j), p in grid.items() if i == j), sum(p for (i, j), p in grid.items() if i < j))


def outcome_probs(lam_h: float, lam_a: float, rho: float = DC_RHO) -> tuple[float, float, float]:
    return _grid_outcomes(score_grid(_clamp(lam_h, 0.05, 6.0), _clamp(lam_a, 0.05, 6.0), rho))


def over_prob(lam_h: float, lam_a: float, line: float = 2.5) -> float:
    grid = score_grid(_clamp(lam_h, 0.05, 6.0), _clamp(lam_a, 0.05, 6.0), DC_RHO)
    return sum(p for (i, j), p in grid.items() if i + j > line)


# ---------------------------------------------------------------- rate sources
def _weighted(rows: list[dict], gf_key: str, ga_key: str) -> tuple[float, float, float] | None:
    sf = sa = sw = 0.0
    for idx, r in enumerate(rows):
        gf, ga = r.get(gf_key), r.get(ga_key)
        if gf is None or ga is None or (gf_key == "gf" and r.get("shootout")):
            continue
        if gf_key == "gf":                      # actual goals only (xG values are already continuous and sane)
            gf, ga = min(gf, GOAL_CAP), min(ga, GOAL_CAP)
        w = RECENCY_DECAY ** idx * (0.7 if "friendl" in (r.get("competition") or "").lower() else 1.0)
        sf, sa, sw = sf + w * gf, sa + w * ga, sw + w
    return (sf / sw, sa / sw, sw) if sw > 0 else None


def _shrunk(value: float, n: float, prior: float) -> float:
    return (n * value + SHRINK_GAMES * prior) / (n + SHRINK_GAMES)


def _poisson_rates(home: tuple | None, away: tuple | None, edge: int) -> tuple[float, float, float] | None:
    if home is None or away is None:
        return None
    base = max(0.8, (home[0] + home[1] + away[0] + away[1]) / 4)
    att_h, def_h = _shrunk(home[0], home[2], base), _shrunk(home[1], home[2], base)
    att_a, def_a = _shrunk(away[0], away[2], base), _shrunk(away[1], away[2], base)
    adv = HOME_LOG_ADV * edge          # +1 home side has the edge, -1 the away side, 0 neutral
    return (_clamp(att_h * def_a / base * math.exp(adv), 0.2, 4.0), _clamp(att_a * def_h / base * math.exp(-adv), 0.2, 4.0), min(home[2], away[2]))


def _xg_source(facts: dict) -> dict | None:
    h, a = facts["sides"]["home"]["xg"], facts["sides"]["away"]["xg"]
    if not (h and a):
        return None
    r = _poisson_rates((h["for_pg"], h["against_pg"], float(h["n"])), (a["for_pg"], a["against_pg"], float(a["n"])), facts["edge"])
    return {"name": "xg", "lam": (r[0], r[1]), "weight": SOURCE_WEIGHTS["xg"], "n": r[2], "why": f"shrunk xG per game, {r[2]:.0f} games per side"}


def _results_source(facts: dict) -> dict | None:
    hr, ar = _weighted(facts["sides"]["home"]["form"], "gf", "ga"), _weighted(facts["sides"]["away"]["form"], "gf", "ga")
    r = _poisson_rates(hr, ar, facts["edge"])
    if r is None:
        return None
    return {"name": "results", "lam": (r[0], r[1]), "weight": SOURCE_WEIGHTS["results"], "n": r[2], "why": f"recent goals, {r[2]:.1f} effective games per side"}


def _strength_source(facts: dict) -> dict | None:
    h, a = facts["sides"]["home"], facts["sides"]["away"]
    gap, parts = 0.0, []
    if h["elo"] and a["elo"]:
        g = h["elo"]["rating"] - a["elo"]["rating"]
        gap += g * (1.0 if (h["elo"]["national"] and a["elo"]["national"]) else 0.5)   # form-only Elo assumes average opponents: half weight
        parts.append(f"Elo gap {g:+.0f}")
    if h["squad_value"] and a["squad_value"]:
        v = _clamp(100.0 * math.log(h["squad_value"] / a["squad_value"]), -400, 400)
        gap += v
        parts.append(f"squad value x{h['squad_value'] / a['squad_value']:.2f}")
    if not parts:
        return None
    diff = _clamp(gap * GOALS_PER_ELO_GAP, -2.5, 2.5)
    diff += facts["edge"] * 2 * BASE_GOALS * (math.exp(HOME_LOG_ADV) - math.exp(-HOME_LOG_ADV)) / 2 * 0.5
    total = 2 * BASE_GOALS
    lam_h, lam_a = _clamp((total + diff) / 2, 0.2, 4.0), _clamp((total - diff) / 2, 0.2, 4.0)
    return {"name": "strength", "lam": (lam_h, lam_a), "weight": SOURCE_WEIGHTS["strength"], "n": None, "why": ", ".join(parts)}


def market_rates(odds: dict) -> tuple[float, float] | None:
    """Rates whose score grid best matches the fair H/D/A (and O/U 2.5) probabilities: coarse-to-fine grid search."""
    target = (odds["home"], odds["draw"], odds["away"])

    def loss(lh: float, la: float) -> float:
        grid = score_grid(lh, la, DC_RHO)
        h, d, a = _grid_outcomes(grid)
        err = (h - target[0]) ** 2 + (d - target[1]) ** 2 + (a - target[2]) ** 2
        if odds.get("over_2_5") is not None:
            err += (sum(p for (i, j), p in grid.items() if i + j > 2) - odds["over_2_5"]) ** 2
        return err

    best, best_loss = (1.3, 1.3), 9.0
    for step, span, center in ((0.25, 3.0, (1.5, 1.5)), (0.05, 0.3, None), (0.01, 0.06, None)):
        c = center or best
        lo_h, lo_a = max(0.1, c[0] - span), max(0.1, c[1] - span)
        n = int(2 * span / step) + 1
        for i in range(n):
            for j in range(n):
                lh, la = lo_h + i * step, lo_a + j * step
                if lh > 5.5 or la > 5.5:
                    continue
                v = loss(lh, la)
                if v < best_loss:
                    best, best_loss = (lh, la), v
    return best


def _market_source(facts: dict) -> dict | None:
    if not facts["odds"]:
        return None
    lam = market_rates(facts["odds"])
    return {"name": "market", "lam": lam, "weight": SOURCE_WEIGHTS["market"], "n": None,
            "why": f"rates reproducing the de-vigged odds{' and over/under 2.5' if facts['odds'].get('over_2_5') is not None else ''}"}


def _history_source(facts: dict) -> dict | None:
    """Our own trained national-team model (Dixon-Coles-style goals model fitted on ~17,500 international results, data/history-model.json;
    opponent-adjusted, odds-free). Only for national teams it knows. Home edge follows the venue like every other source."""
    model = _history_model()
    if model is None:
        return None
    edge = facts["edge"]
    rates = _history_goals(model, facts["home"], facts["away"], neutral=(edge == 0)) if edge >= 0 else None
    if edge < 0:
        swapped = _history_goals(model, facts["away"], facts["home"], neutral=False)      # the away side hosts: compute with roles swapped
        rates = (swapped[1], swapped[0]) if swapped else None
    if rates is None:
        return None
    return {"name": "history", "lam": rates, "weight": SOURCE_WEIGHTS["history"], "n": None, "why": f"trained national-team goals model (fitted {model.as_of}, {model.matches_used} matches)"}


def rate_sources(facts: dict, use_market: bool = True) -> list[dict]:
    """use_market=False gives the independent view: bookmaker odds are not an input (they are only used by the odds challenge)."""
    sources = [s for s in ((_market_source(facts) if use_market else None), _history_source(facts), _xg_source(facts), _results_source(facts), _strength_source(facts)) if s]
    if use_market and any(s["name"] == "market" for s in sources):
        sources = [{**s, "weight": HISTORY_WEIGHT_WITH_ODDS} if s["name"] == "history" else s for s in sources]
    return sources


def combine_rates(sources: list[dict]) -> tuple[float, float, float]:
    """Weighted geometric mean of the sources' rates, plus their relative spread (a disagreement measure used for uncertainty)."""
    tw = sum(s["weight"] for s in sources)
    lh = math.exp(sum(s["weight"] * math.log(s["lam"][0]) for s in sources) / tw)
    la = math.exp(sum(s["weight"] * math.log(s["lam"][1]) for s in sources) / tw)
    if len(sources) > 1:
        var = sum(s["weight"] * ((math.log(s["lam"][0]) - math.log(lh)) ** 2 + (math.log(s["lam"][1]) - math.log(la)) ** 2) / 2 for s in sources) / tw
        spread = math.sqrt(var)
    else:
        spread = 0.25
    return lh, la, spread


def apply_absences(sources: list[dict], mh: float, ma: float) -> list[dict]:
    """Absence multipliers go on the NON-odds sources only. Bookmaker odds already price known injuries and suspensions; applying
    the player-level model to them (or to a blend that is 85% odds) counted every absence twice. With no odds the multipliers
    apply to everything, because then the absences are not priced anywhere else."""
    return [s if s["name"] == "market" else {**s, "lam": (s["lam"][0] * mh, s["lam"][1] * ma)} for s in sources]


def absence_multipliers(facts: dict, scale: float | None = None) -> tuple[float, float, list[str]]:
    """Player-level absences -> multipliers on (home rate, away rate). Home attackers missing lowers the home rate; home
    defenders/keeper missing raises the away rate (and vice versa). Capped so one report can never move a rate >15%."""
    h, a = facts["sides"]["home"]["absence_loss"], facts["sides"]["away"]["absence_loss"]
    notes = []

    k = ABSENCE_APPLY_SCALE if scale is None else scale

    def eff(att_loss: float, opp_def_loss: float, factor: float) -> float:
        up = factor * DEFENCE_ABSENCE_SENSITIVITY * opp_def_loss
        down = factor * ATTACK_ABSENCE_SENSITIVITY * att_loss
        return _clamp((1 - down) * (1 + up), 1 - MAX_ABSENCE_EFFECT, 1 + MAX_ABSENCE_EFFECT)

    full_h, full_a = eff(h["attack_loss"], a["defence_loss"], 1.0), eff(a["attack_loss"], h["defence_loss"], 1.0)
    state = "applied" if k else "NOT applied: unvalidated, it did not help on 38 fixtures"
    if abs(full_h - 1) > 0.005:
        notes.append(f"home rate would be x{full_h:.3f} (home attack loss {h['attack_loss']:.3f}, away defence loss {a['defence_loss']:.3f}) -- {state}")
    if abs(full_a - 1) > 0.005:
        notes.append(f"away rate would be x{full_a:.3f} (away attack loss {a['attack_loss']:.3f}, home defence loss {h['defence_loss']:.3f}) -- {state}")
    return eff(h["attack_loss"], a["defence_loss"], k), eff(a["attack_loss"], h["defence_loss"], k), notes


def probability_spread(lam_h: float, lam_a: float, log_sd: float, draws: int = 600, seed: int = 1) -> dict:
    """10-90% ranges of H/D/A when the rates themselves are uncertain (lognormal noise, sd = source disagreement)."""
    rng = random.Random(seed)
    sd = _clamp(log_sd, 0.04, 0.5)
    rows = [outcome_probs(lam_h * math.exp(rng.gauss(0, sd)), lam_a * math.exp(rng.gauss(0, sd))) for _ in range(draws)]
    out = {}
    for k, name in enumerate(("home", "draw", "away")):
        vals = sorted(r[k] for r in rows)
        out[name] = (round(100 * vals[int(0.1 * draws)], 1), round(100 * vals[int(0.9 * draws)], 1))
    return out


# ---------------------------------------------------------------- goal-market shrink
# The goal markets (Over/Under, both teams to score, clean sheets) are too extreme when the predicted total is low: matches predicted under 2.0 goals
# scored 2.10, and Under 2.5 quoted at 70%+ happened 64% of the time (8,054 held-out internationals, research/under_check.py). Pulling the total goal rate 20%
# of the way to the training mean (both sides scaled by the same factor, so 1X2 and the draw lens are untouched) improves Over/Under log-loss by 0.0025
# (z = -3.6) and BTTS by 0.0026 (z = -5.5), 1X2 unchanged (z = +0.5), with the same sign in 2018-21, 2022-23 and 2024-26 (research/total_shrink*.py).
TOTAL_SHRINK, MEAN_TOTAL_GOALS = 0.2, 2.676


def shrink_total_goals(lam_h: float, lam_a: float) -> tuple[float, float]:
    """Both rates scaled by one factor so that the total moves TOTAL_SHRINK of the way to the mean total; the home/away split is unchanged."""
    t = lam_h + lam_a
    if t <= 0:
        return lam_h, lam_a
    f = (t + TOTAL_SHRINK * (MEAN_TOTAL_GOALS - t)) / t
    return lam_h * f, lam_a * f


# ---------------------------------------------------------------- exact score distribution
def exact_distribution(lam_h: float, lam_a: float) -> dict:
    """The full score distribution (Poisson goals with the Dixon-Coles low-score correction), computed exactly, no sampling. The earlier version simulated
    Poisson-Gamma goals with a shared tempo factor; validated on 4,027 held-out matches (research/sim_validation.py) that was WORSE than plain Poisson
    (Brier 0.4955 vs 0.4943, log-loss 0.8464 vs 0.8442), over-predicted draws (23.5% vs 22.6% actual) and 0-0 (10.0% vs 8.8%), and the tempo factor did nothing.
    Plain Poisson + Dixon-Coles is calibrated on the markets: over 1.5 72.4/71.6, over 2.5 48.1/47.9, both-score 42.2/41.2, 0-0 8.9/8.8 (predicted/actual %)."""
    grid = score_grid(_clamp(lam_h, 0.05, 6.0), _clamp(lam_a, 0.05, 6.0), DC_RHO)
    home, draw, away = _grid_outcomes(grid)
    cell = lambda f: sum(p for (i, j), p in grid.items() if f(i, j))
    margins: dict[int, float] = {}
    for (i, j), p in grid.items():
        margins[i - j] = margins.get(i - j, 0.0) + p
    top = sorted(grid.items(), key=lambda kv: -kv[1])[:6]
    return {
        "home": home, "draw": draw, "away": away,
        "expected_goals": (sum(i * p for (i, j), p in grid.items()), sum(j * p for (i, j), p in grid.items())),
        "markets": {"over_1_5": cell(lambda i, j: i + j > 1), "over_2_5": cell(lambda i, j: i + j > 2), "over_3_5": cell(lambda i, j: i + j > 3),
                    "btts": cell(lambda i, j: i > 0 and j > 0), "home_cs": cell(lambda i, j: j == 0), "away_cs": cell(lambda i, j: i == 0)},
        "top_scores": [{"score": f"{i}-{j}", "pct": round(100 * p, 1)} for (i, j), p in top],
        "margin_pct": {str(k): round(100 * v, 1) for k, v in sorted(margins.items()) if v >= 0.01},
        "draw_scores_pct": {f"{k}-{k}": round(100 * grid.get((k, k), 0.0), 1) for k in range(4)},
    }
