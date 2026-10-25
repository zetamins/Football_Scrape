"""Offline fitting + honest backtest for history_model.

    python -m football.history_train fit      # download archive, fit, write data/history-model.json
    python -m football.history_train backtest # train < cutoff, score on later matches vs baselines

Fitting: weighted Poisson regression, coordinate-wise Newton sweeps, L2 ridge
on attack/defence, exponential time decay, tournament weights (friendlies
count less), Dixon-Coles rho by 1-D likelihood grid.
"""

from __future__ import annotations

import csv
import io
import json
import math
import sys
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime

from . import history_model as _hm
from .pi_ratings import PiRatings
from .history_model import FittedModel, MAX_GOALS, PiModel, _key, load_model, pi_features, score_grid
from .national_elo import _normalize  # noqa: F401  (name normaliser shared with inference)

ARCHIVE_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"

# Defaults chosen on the 2022-23 validation window (rolling refit), then
# scored untouched on 2024-01..2026-08 (2,678 matches): see `backtest`.
# RIDGE 0.5 (was 1.0) came from the overnight technique search: best on the
# 2022-23 validation window, then confirmed once on 2024-26 (paired Brier
# -0.0008, 95% CI [-0.0013, -0.0003]). See backend/research/README.md.
HALF_LIFE_YEARS = 4.0
RIDGE = 0.5
START_YEAR = 2008
SWEEPS = 40


@dataclass
class Match:
    day: date
    home: str
    away: str
    hg: int
    ag: int
    tournament: str
    neutral: bool


def parse_archive(text: str) -> list[Match]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            out.append(Match(
                date.fromisoformat(row["date"]), _key(row["home_team"]), _key(row["away_team"]),
                int(row["home_score"]), int(row["away_score"]), row["tournament"], row["neutral"].upper() == "TRUE",
            ))
        except (ValueError, KeyError):
            continue  # unplayed fixtures have empty scores
    return out


def _get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 -- fixed https URL
        return resp.read().decode("utf-8")


def download() -> list[Match]:
    return parse_archive(_get_text(ARCHIVE_URL))


_NON_FIFA = ("conifa", "island games", "muhammad ali", "viva world cup", "inter games")
_MAJOR = ("fifa world cup", "uefa euro", "copa am", "african cup of nations", "afc asian cup", "gold cup", "confederations", "oceania nations cup", "arab cup", "gulf cup")
CATEGORIES = ("friendly", "qualifier", "nations_league", "major", "other")


def tournament_category(name: str) -> str:
    """friendly / qualifier / nations_league / major (finals tournaments) /
    other; non-FIFA events (CONIFA, Island Games ...) -> "nonfifa", which is
    always excluded."""
    lowered = name.lower()
    if any(k in lowered for k in _NON_FIFA):
        return "nonfifa"
    if lowered == "friendly":
        return "friendly"
    if "qualification" in lowered:
        return "qualifier"
    if "nations league" in lowered:
        return "nations_league"
    if any(k in lowered for k in _MAJOR):
        return "major"
    return "other"


# Per-category weights, tuned by coordinate search on the 2022-23 validation
# window (see `tune_weights`); every category is 1.0 until tuned.
TOURNAMENT_WEIGHTS = {c: 1.0 for c in CATEGORIES}


_MAX_LOG_RATE = 4.0   # exp(4) ~ 55 goals: far beyond any real rate, only stops divergence
_MAX_STEP = 1.0       # per-sweep Newton step cap for each team parameter
_MAX_PARAM = 3.0


def _exp(x: float) -> float:
    return math.exp(min(x, _MAX_LOG_RATE))


def _damped(value: float, step: float) -> float:
    step = max(-_MAX_STEP, min(_MAX_STEP, step))
    return max(-_MAX_PARAM, min(_MAX_PARAM, value + step))


def _weight(m: Match, as_of: date, half_life_years: float, tournament_weights: dict[str, float]) -> float:
    category = tournament_category(m.tournament)
    if category == "nonfifa":
        return 0.0
    age_years = (as_of - m.day).days / 365.25
    return (0.5 ** (age_years / half_life_years)) * tournament_weights[category]


_CONFED_KEYS = {
    "CAF": ("african cup of nations", "cosafa", "cecafa", "african nations championship", "waff", "unaf", "uniffac", "amilcar"),
    "UEFA": ("uefa", "euro", "baltic cup", "balkan cup", "nordic"),
    "AFC": ("afc", "asian", "aff ", "aff championship", "gulf cup", "eaff", "saff", "asean", "waff", "arab cup", "merdeka", "king's cup"),
    "CONCACAF": ("concacaf", "gold cup", "caribbean", "ccccf", "uncaf", "cfu"),
    "CONMEBOL": ("copa am", "conmebol", "south american"),
    "OFC": ("oceania", "ofc", "pacific games", "polynesia", "melanesian"),
}
VENUE_MODES = ("basic", "split", "confed")
VENUE_DEV_RIDGE = 40.0     # weighted matches of shrinkage pulling a confederation's venue effect toward the global one


def infer_confederations(matches: list[Match]) -> dict[str, str]:
    """Team -> confederation from the tournaments it has played in (regional tournaments / qualifiers; friendlies and World Cups say nothing)."""
    votes: dict[str, dict[str, int]] = {}
    for m in matches:
        t = m.tournament.lower()
        if t == "friendly" or ("world cup" in t and "qualification" not in t):
            continue
        for conf, keys in _CONFED_KEYS.items():
            if any(k in t for k in keys):
                if "concacaf nations" in t:
                    conf = "CONCACAF"
                for team in (m.home, m.away):
                    votes.setdefault(team, {}).setdefault(conf, 0)
                    votes[team][conf] += 1
                break
    return {team: max(v, key=v.get) for team, v in votes.items()}


def fit(matches: list[Match], as_of: date, half_life_years=HALF_LIFE_YEARS, ridge=RIDGE,
        tournament_weights=None, start_year=START_YEAR, sweeps=SWEEPS, venue: str = "confed") -> FittedModel:
    """venue: how the venue effect is modelled.
      basic  one home boost for non-neutral matches (the original model);
      split  + an away-side drag at genuine home matches and a boost for the side LISTED as home at neutral venues;
      confed split, with each host confederation's home boost / away drag allowed to differ (shrunk toward the global value).
    Default confed: pooled over 8,053 held-out matches 2018-26 it beat basic by -0.00142 Brier [-0.00256, -0.00038] and -0.00244 log-loss [-0.00422, -0.00081], better in
    every one of the three periods (split alone: -0.00067 [-0.00150, +0.00020], not significant). It removes the away-goals over-prediction at genuine home matches
    (CAF -14%, AFC -16%, CONMEBOL -29% in the old model) -- research/bias_scan.py, venue_test.py."""
    if venue not in VENUE_MODES:
        raise ValueError(f"venue must be one of {VENUE_MODES}")
    weights_by_category = {**TOURNAMENT_WEIGHTS, **(tournament_weights or {})}
    use = [m for m in matches if start_year <= m.day.year and m.day < as_of and tournament_category(m.tournament) != "nonfifa"]
    w = [_weight(m, as_of, half_life_years, weights_by_category) for m in use]
    if not use or sum(w) <= 0:
        raise ValueError("no matches with positive weight to fit on")
    teams = sorted({m.home for m in use} | {m.away for m in use})
    idx = {t: i for i, t in enumerate(teams)}
    n, K = len(teams), len(use)
    hi = [idx[m.home] for m in use]
    ai = [idx[m.away] for m in use]
    hg = [m.hg for m in use]
    ag = [m.ag for m in use]
    non = [not m.neutral for m in use]
    confed = infer_confederations(use) if venue == "confed" else {}
    confs = sorted(set(confed.values()) | {"?"})
    cidx = {c: i for i, c in enumerate(confs)}
    ck = [cidx[confed.get(m.home, "?")] if (venue == "confed" and not m.neutral) else -1 for m in use]
    att = [0.0] * n
    dfn = [0.0] * n
    mu = math.log(sum(wi * (a + b) for wi, a, b in zip(w, hg, ag)) / (2 * sum(w)))
    hadv, nadv, aadv = 0.2, 0.0, 0.0
    dh = [0.0] * len(confs)       # confederation deviations of the home boost / away drag
    da = [0.0] * len(confs)

    def rates():
        lam_h = [_exp(mu + (hadv + (dh[ck[k]] if ck[k] >= 0 else 0.0) if non[k] else nadv) + att[hi[k]] - dfn[ai[k]]) for k in range(K)]
        lam_a = [_exp(mu + ((aadv + (da[ck[k]] if ck[k] >= 0 else 0.0)) if non[k] else 0.0) + att[ai[k]] - dfn[hi[k]]) for k in range(K)]
        return lam_h, lam_a

    for _ in range(sweeps):
        lam_h, lam_a = rates()
        g = sum(w[k] * ((hg[k] - lam_h[k]) + (ag[k] - lam_a[k])) for k in range(K))
        h = sum(w[k] * (lam_h[k] + lam_a[k]) for k in range(K))
        mu += g / h
        lam_h, lam_a = rates()
        gh = sum(w[k] * (hg[k] - lam_h[k]) for k in range(K) if non[k]); hh = sum(w[k] * lam_h[k] for k in range(K) if non[k])
        hadv += gh / hh if hh else 0.0
        if venue != "basic":
            lam_h, lam_a = rates()
            gn = sum(w[k] * (hg[k] - lam_h[k]) for k in range(K) if not non[k]); hn = sum(w[k] * lam_h[k] for k in range(K) if not non[k])
            nadv += gn / hn if hn else 0.0
            ga_ = sum(w[k] * (ag[k] - lam_a[k]) for k in range(K) if non[k]); ha_ = sum(w[k] * lam_a[k] for k in range(K) if non[k])
            aadv += ga_ / ha_ if ha_ else 0.0
        if venue == "confed":
            lam_h, lam_a = rates()
            for c in range(len(confs)):
                gH = sum(w[k] * (hg[k] - lam_h[k]) for k in range(K) if ck[k] == c); hH = sum(w[k] * lam_h[k] for k in range(K) if ck[k] == c)
                gA = sum(w[k] * (ag[k] - lam_a[k]) for k in range(K) if ck[k] == c); hA = sum(w[k] * lam_a[k] for k in range(K) if ck[k] == c)
                dh[c] += (gH - VENUE_DEV_RIDGE * dh[c]) / (hH + VENUE_DEV_RIDGE)
                da[c] += (gA - VENUE_DEV_RIDGE * da[c]) / (hA + VENUE_DEV_RIDGE)
        lam_h, lam_a = rates()
        ga = [0.0] * n; ha = [0.0] * n; gd = [0.0] * n; hd = [0.0] * n
        for k in range(K):
            ga[hi[k]] += w[k] * (hg[k] - lam_h[k]); ha[hi[k]] += w[k] * lam_h[k]
            ga[ai[k]] += w[k] * (ag[k] - lam_a[k]); ha[ai[k]] += w[k] * lam_a[k]
            gd[ai[k]] -= w[k] * (hg[k] - lam_h[k]); hd[ai[k]] += w[k] * lam_h[k]
            gd[hi[k]] -= w[k] * (ag[k] - lam_a[k]); hd[hi[k]] += w[k] * lam_a[k]
        for t in range(n):
            att[t] = _damped(att[t], (ga[t] - ridge * att[t]) / (ha[t] + ridge))
            dfn[t] = _damped(dfn[t], (gd[t] - ridge * dfn[t]) / (hd[t] + ridge))
        # keep the attack scale anchored (defence absorbs the rest into mu)
        mean_a = sum(att) / n
        att = [a - mean_a for a in att]
        mean_d = sum(dfn) / n
        dfn = [d - mean_d for d in dfn]
    lam_h, lam_a = rates()
    rho = _fit_rho(w, hg, ag, lam_h, lam_a)
    return FittedModel(
        mu=mu, home_adv=hadv, neutral_adv=nadv, away_adv=aadv, rho=rho,
        home_dev={c: dh[i] for c, i in cidx.items()} if venue == "confed" else {}, away_dev={c: da[i] for c, i in cidx.items()} if venue == "confed" else {},
        confed={t: confed.get(t, "?") for t in idx} if venue == "confed" else {},
        attack={t: att[i] for t, i in idx.items()}, defence={t: dfn[i] for t, i in idx.items()},
        as_of=as_of.isoformat(), matches_used=len(use),
    )


def _fit_rho(w, hg, ag, lam_h, lam_a) -> float:
    from .history_model import _dc_tau
    best, best_ll = 0.0, -1e18
    low = [k for k in range(len(w)) if hg[k] <= 1 and ag[k] <= 1]
    for step in range(-20, 21):
        rho = step / 100
        ll = 0.0
        for k in low:
            tau = _dc_tau(hg[k], ag[k], lam_h[k], lam_a[k], rho)
            if tau <= 0:
                ll = -1e18
                break
            ll += w[k] * math.log(tau)
        if ll > best_ll:
            best, best_ll = rho, ll
    return best


PI_FIRST_TRAIN_YEAR = 2010
PI_L2_PER_SAMPLE_FACTOR = 2.0   # sklearn-equivalent C=0.5: l2 = 1 / (C * n)
PI_ITERS = 150
PI_LR = 0.8


def _softmax3(z):
    top = max(z)
    ex = [math.exp(v - top) for v in z]
    s = sum(ex)
    return [v / s for v in ex]


def fit_pi(matches: list[Match], as_of: date, keep_teams: set[str] | None = None) -> PiModel | None:
    """Pi-ratings + Elo gap -> multinomial logit. Ratings run over ALL matches before `as_of` (warm-up),
    the logistic regression trains on rows from PI_FIRST_TRAIN_YEAR on, using features computed strictly
    BEFORE each match."""
    pi = PiRatings()
    elo = _SeqElo()
    X: list[list[float]] = []
    y: list[int] = []
    for m in sorted((m for m in matches if m.day < as_of and tournament_category(m.tournament) != "nonfifa"), key=lambda m: m.day):
        if m.day.year >= PI_FIRST_TRAIN_YEAR:
            x = pi_features(pi.home, pi.away, elo.r, m.home, m.away, m.neutral)
            if x is not None:
                X.append(x)
                y.append(_outcome(m))
        pi.update(m.home, m.away, m.hg, m.ag, m.neutral)
        elo.update(m)
    if len(X) < 200:
        return None
    k = len(X[0])
    n = len(X)
    mean = [sum(r[j] for r in X) / n for j in range(k)]
    std = [max(1e-6, math.sqrt(sum((r[j] - mean[j]) ** 2 for r in X) / n)) for j in range(k)]
    Z = [[1.0] + [(r[j] - mean[j]) / std[j] for j in range(k)] for r in X]
    W = [[0.0] * (k + 1) for _ in range(3)]
    l2 = PI_L2_PER_SAMPLE_FACTOR / n
    for _ in range(PI_ITERS):
        grad = [[0.0] * (k + 1) for _ in range(3)]
        for zi, yi in zip(Z, y):
            p = _softmax3([sum(w * v for w, v in zip(W[c], zi)) for c in range(3)])
            for c in range(3):
                err = p[c] - (1.0 if c == yi else 0.0)
                gc = grad[c]
                for j in range(k + 1):
                    gc[j] += err * zi[j]
        for c in range(3):
            for j in range(k + 1):
                W[c][j] -= PI_LR * (grad[c][j] / n + (l2 * W[c][j] if j else 0.0))
    teams = keep_teams if keep_teams is not None else set(elo.r)
    return PiModel(
        pi_home={t: round(v, 5) for t, v in pi.home.items() if t in teams}, pi_away={t: round(v, 5) for t, v in pi.away.items() if t in teams},
        elo={t: round(v, 2) for t, v in elo.r.items() if t in teams}, mean=mean, std=std, weights=W,
    )


def fit_full(matches: list[Match], as_of: date, **params) -> FittedModel:
    """Poisson model + the pi-ratings logit, ready for history_model.predict_outcome."""
    model = fit(matches, as_of, **params)
    model.pi = fit_pi(matches, as_of, keep_teams=set(model.attack))
    return model


def outcome_probs_blended(model: FittedModel, home: str, away: str, neutral: bool):
    from .history_model import blended_outcome
    base = outcome_probs(model, home, away, neutral)
    return None if base is None else blended_outcome(model, home, away, neutral, base)


def outcome_probs(model: FittedModel, home: str, away: str, neutral: bool):
    from .history_model import expected_goals
    rates = expected_goals(model, home, away, neutral)
    if rates is None:
        return None
    grid = score_grid(rates[0], rates[1], model.rho)
    return (
        sum(p for (i, j), p in grid.items() if i > j),
        sum(p for (i, j), p in grid.items() if i == j),
        sum(p for (i, j), p in grid.items() if i < j),
    )


def _outcome(m: Match) -> int:
    return 0 if m.hg > m.ag else (1 if m.hg == m.ag else 2)


def _brier(p, o) -> float:
    return sum((p[j] - (1 if j == o else 0)) ** 2 for j in range(3))


class _SeqElo:
    """Baseline: opponent-adjusted Elo updated match by match from the same
    archive (eloratings-style K, goal-margin multiplier, +100 home), mapped to
    probabilities with Davidson's draw model."""

    def __init__(self):
        self.r: dict[str, float] = {}

    def update_all(self, matches):
        for m in matches:
            self.update(m)

    def update(self, m: Match):
        rh, ra = self.r.get(m.home, 1500.0), self.r.get(m.away, 1500.0)
        dr = rh + (0 if m.neutral else 100) - ra
        e = 1 / (1 + 10 ** (-dr / 400))
        s = 1.0 if m.hg > m.ag else (0.5 if m.hg == m.ag else 0.0)
        k = 20 if m.tournament == "Friendly" else 40
        diff = abs(m.hg - m.ag)
        g = 1 if diff <= 1 else (1.5 if diff == 2 else (11 + diff) / 8)
        delta = k * g * (s - e)
        self.r[m.home] = rh + delta
        self.r[m.away] = ra - delta

    def probs(self, m: Match):
        if m.home not in self.r or m.away not in self.r:
            return None
        ph = 10 ** ((self.r[m.home] + (0 if m.neutral else 100)) / 400)
        pa = 10 ** (self.r[m.away] / 400)
        d = 0.75 * math.sqrt(ph * pa)
        z = ph + pa + d
        return ph / z, d / z, pa / z


def backtest(matches: list[Match], cutoff: date, end: date | None = None, refit_months: int = 6, blended: bool = False, **params):
    """Rolling-origin: refit every `refit_months` on data strictly before the
    block, score the block. No match is ever predicted by a model that saw it."""
    test = sorted((m for m in matches if m.day >= cutoff and (end is None or m.day < end)), key=lambda m: m.day)
    base_rates = [0.0, 0.0, 0.0]
    for m in matches:
        if m.day < cutoff and m.day.year >= 2008:
            base_rates[_outcome(m)] += 1
    s = sum(base_rates)
    base = [x / s for x in base_rates]
    results = {"model": [], "elo": [], "base": [], "uniform": []}
    elo = _SeqElo()
    elo.update_all(m for m in sorted(matches, key=lambda m: m.day) if m.day < cutoff)
    pos = 0
    block_start = cutoff
    while pos < len(test):
        month = block_start.month - 1 + refit_months
        block_end = date(block_start.year + month // 12, month % 12 + 1, 1)
        block = [m for m in test[pos:] if m.day < block_end]
        if block:
            model = fit_full(matches, block_start, **params) if blended else fit(matches, block_start, **params)
            for m in block:
                p = (outcome_probs_blended if blended else outcome_probs)(model, m.home, m.away, m.neutral)
                pe = elo.probs(m)
                if p is not None and pe is not None:
                    o = _outcome(m)
                    results["model"].append(_brier(p, o) if True else 0)
                    results["elo"].append(_brier(pe, o))
                    results["base"].append(_brier(base, o))
                    results["uniform"].append(_brier([1 / 3] * 3, o))
                    results.setdefault("acc_model", []).append(1 if max(range(3), key=lambda j: p[j]) == o else 0)
                    results.setdefault("acc_elo", []).append(1 if max(range(3), key=lambda j: pe[j]) == o else 0)
                    results.setdefault("draw_p", []).append(p[1])
                    results.setdefault("draw_actual", []).append(1 if o == 1 else 0)
                # the sequential Elo must learn the block only after predicting it
            for m in block:
                elo.update(m)
            pos += len(block)
        block_start = block_end
    return {k: sum(v) / len(v) for k, v in results.items() if v} | {"n": len(results["model"])}


def write_model(model: FittedModel) -> None:
    pi = None
    if model.pi is not None:
        pi = {"pi_home": model.pi.pi_home, "pi_away": model.pi.pi_away, "elo": model.pi.elo,
              "mean": [round(v, 6) for v in model.pi.mean], "std": [round(v, 6) for v in model.pi.std],
              "weights": [[round(v, 6) for v in row] for row in model.pi.weights]}
    payload = {
        "source": "martj42/international_results", "as_of": model.as_of, "matches_used": model.matches_used,
        "mu": round(model.mu, 5), "home_adv": round(model.home_adv, 5), "neutral_adv": round(model.neutral_adv, 5), "away_adv": round(model.away_adv, 5), "rho": model.rho,
        "home_dev": {k: round(v, 5) for k, v in model.home_dev.items()}, "away_dev": {k: round(v, 5) for k, v in model.away_dev.items()}, "confed": model.confed,
        "attack": {k: round(v, 4) for k, v in sorted(model.attack.items())},
        "defence": {k: round(v, 4) for k, v in sorted(model.defence.items())},
        "pi": pi,
    }
    _hm._model_path().write_text(json.dumps(payload, indent=0) + "\n", encoding="utf-8")
    load_model.cache_clear()


def main(argv: list[str]) -> None:
    cmd = argv[1] if len(argv) > 1 else "fit"
    matches = download()
    if cmd == "fit":
        as_of = datetime.now(UTC).date()
        model = fit_full(matches, as_of)
        write_model(model)
        print(f"fitted {len(model.attack)} teams on {model.matches_used} matches, rho={model.rho}, home_adv={model.home_adv:.3f}")
    elif cmd == "backtest":
        print(backtest(matches, date(2024, 1, 1)))


if __name__ == "__main__":
    main(sys.argv)
