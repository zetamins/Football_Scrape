"""Match analyst: a scraped report JSON in -> data audit + independent calculations + prediction out.

    python -m football.analyze report.json [more.json | folder/] [--deep] [--json] [--llm [model]] [--fast]

Uses ONLY the JSON (no results archive, no seed files, no network, no training), so it works for any
match -- international or club league. Steps, all visible in the output:

1. AUDIT   what is missing / stale / conflicting / thinly sampled, with a data-quality score.
2. CALCULATE  independent estimates from the JSON's own fields: bookmaker odds (de-vigged), xG-based and
   results-based Poisson goal models (with shrinkage toward the pooled mean for short samples), Elo gap
   (rest/absence/travel adjusted), squad-value gap. Each gives win/draw/loss probabilities and a reason.
3. COMBINE weighted by how reliable each source is (odds highest), shrunk toward base rates when the data
   is poor, then mapped to a calibrated "chance the pick is right" (prediction._CONFIDENCE_KNOTS).
4. UNCERTAINTY  Monte Carlo over method weights, per-method noise and goal rates (--deep: 10x more
   draws) -> 10-90% ranges and how often each outcome is the favourite.

It audits the pipeline's own blended prediction as a cross-check but never copies it.
"""

from __future__ import annotations

import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .history_model import score_grid
from .prediction import _CONFIDENCE_KNOTS, _calibrated_confidence

BASE_RATES = (0.47, 0.25, 0.28)      # home / draw / away across international matches (2018-26 archive)
DRAW_NU = 0.75                        # Davidson draw parameter used for rating-gap methods
HOME_ADV_ELO = 100.0
HOME_LOG_ADV = 0.20                   # +-: home scores e^{+0.20}, away e^{-0.20} when not neutral (validated on 8,041 historical matches: Brier 0.5711 -> 0.5675)
SHRINK_GAMES = 4.0                    # prior strength (games) for short form windows
RECENCY_DECAY = 0.9
DC_RHO = -0.05
OUTCOMES = ("home", "draw", "away")


# ----------------------------------------------------------------------------- helpers
def _get(d: Any, *path: str, default=None):
    for key in path:
        if not isinstance(d, dict):
            return default
        d = d.get(key)
    return default if d is None else d


def _norm(s: str | None) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


def _normalize3(p) -> tuple[float, float, float]:
    t = sum(p)
    return (p[0] / t, p[1] / t, p[2] / t)


def _davidson(rating_gap: float) -> tuple[float, float, float]:
    """Home-perspective rating gap (Elo points, home advantage already included) -> H/D/A."""
    ph, pa = 10 ** (rating_gap / 800), 10 ** (-rating_gap / 800)
    draw = DRAW_NU
    return _normalize3((ph, draw, pa))


def _own_is_home(report: dict) -> bool:
    team, home = _norm(report.get("team")), _norm(_get(report, "match", "home_team"))
    away = _norm(_get(report, "match", "away_team"))
    if team and team == home:
        return True
    if team and team == away:
        return False
    return bool(team and home and (team in home or home in team))


def _parse_score(entry: dict) -> tuple[int, int] | None:
    """(goals for, goals against) from a form row. `scoreline` is home-away in the fixture frame; resolve
    orientation by venue, then verify against the W/D/L letter (swap if they disagree)."""
    try:
        h, a = (int(x) for x in str(entry["scoreline"]).split("-"))
    except (KeyError, ValueError):
        return None
    gf, ga = (a, h) if entry.get("venue") == "away" else (h, a)
    result = entry.get("result")
    if result == "W" and gf < ga or result == "L" and gf > ga:
        gf, ga = ga, gf
    return gf, ga


def _form_rows(form: dict | None) -> list[dict]:
    for key in ("last10_overall", "last5_overall", "last20_overall"):
        rows = _get(form, key)
        if rows:
            return rows[:10]
    return []


def _weighted_rates(rows: list[dict], use_xg: bool = False) -> tuple[float, float, float] | None:
    """(goals-for per game, goals-against per game, effective games), newest rows weigh most; friendlies 0.7."""
    sf = sa = sw = 0.0
    for idx, row in enumerate(rows):
        if use_xg:
            gf, ga = row.get("xg_for"), row.get("xg_against")
            if gf is None or ga is None:
                continue
        else:
            parsed = _parse_score(row)
            if parsed is None:
                continue
            gf, ga = parsed
        w = RECENCY_DECAY ** idx * (0.7 if "friendl" in (row.get("competition") or "").lower() else 1.0)
        sf += w * gf
        sa += w * ga
        sw += w
    return (sf / sw, sa / sw, sw) if sw > 0 else None


def _shrunk(value: float, n_eff: float, prior: float) -> float:
    return (n_eff * value + SHRINK_GAMES * prior) / (n_eff + SHRINK_GAMES)


def _grid_probs(grid) -> tuple[float, float, float]:
    return (
        sum(p for (i, j), p in grid.items() if i > j),
        sum(p for (i, j), p in grid.items() if i == j),
        sum(p for (i, j), p in grid.items() if i < j),
    )


# ----------------------------------------------------------------------------- methods
def _method(name: str, probs, weight: float, why: str, rates: tuple[float, float] | None = None, n: float | None = None) -> dict:
    return {"name": name, "probs": _normalize3(probs), "weight": weight, "why": why, "rates": rates, "n": n}


def _market(report: dict) -> dict | None:
    odds = _get(report, "match", "betting_odds") or _get(report, "match", "sofascore_betting_odds")
    if not odds:
        return None
    fair = [odds.get(k) for k in ("home_win_fair_pct", "draw_fair_pct", "away_win_fair_pct")]
    if all(isinstance(v, (int, float)) for v in fair) and sum(fair) > 0:
        probs, how = fair, "de-vigged bookmaker odds"
    else:
        raw = [odds.get(k) for k in ("home_win_odds", "draw_odds", "away_win_odds")]
        if not all(isinstance(v, (int, float)) and v > 1 for v in raw):
            return None
        probs, how = [1 / v for v in raw], "bookmaker odds, proportional de-vig"
    p = _normalize3(probs)
    return _method("market", p, 4.0, f"{how}: {p[0]:.0%}/{p[1]:.0%}/{p[2]:.0%}")


def _poisson_method(name: str, home: tuple, away: tuple, neutral: bool, weight: float, source: str) -> dict | None:
    """home/away = (goals-for/game, goals-against/game, n_eff). Multiplicative attack x opposing defence."""
    if home is None or away is None:
        return None
    base = max(0.8, (home[0] + home[1] + away[0] + away[1]) / 4)
    att_h, def_h = _shrunk(home[0], home[2], base), _shrunk(home[1], home[2], base)
    att_a, def_a = _shrunk(away[0], away[2], base), _shrunk(away[1], away[2], base)
    adv = 0.0 if neutral else HOME_LOG_ADV
    lam_h = min(4.0, max(0.2, att_h * def_a / base * math.exp(adv)))
    lam_a = min(4.0, max(0.2, att_a * def_h / base * math.exp(-adv)))
    probs = _grid_probs(score_grid(lam_h, lam_a, DC_RHO))
    n = min(home[2], away[2])
    return _method(name, probs, weight, f"{source}: expected goals {lam_h:.2f}-{lam_a:.2f} from {n:.1f} effective games per side", (lam_h, lam_a), n)


def _context_shift(report: dict) -> tuple[float, list[str]]:
    """Elo-point adjustment (home perspective) for rest, absences and travel."""
    shift, notes = 0.0, []
    own_home = _own_is_home(report)
    rest = _get(report, "insights", "rest_comparison") or {}
    own_r, opp_r = rest.get("own_rest_days"), rest.get("opponent_rest_days")
    if own_r is not None and opp_r is not None:
        diff = max(-5, min(5, own_r - opp_r)) * 5.0
        diff = diff if own_home else -diff
        if diff:
            shift += diff
            notes.append(f"rest {diff:+.0f}")
    for side, sign in (("home", 1), ("away", -1)):
        s = _get(report, "insights", f"{side}_squad_strength") or {}
        total, avail = s.get("total_value"), s.get("available_value")
        if total and avail is not None and total > 0:
            missing = max(0.0, 1 - avail / total)
            pen = min(60.0, 200.0 * missing)
            if pen >= 5:
                shift -= sign * pen
                notes.append(f"{side} absences {-sign * pen:+.0f}")
    travel = _get(report, "insights", "travel_info") or {}
    if travel.get("away_traveling") and (travel.get("away_travel_distance_km") or 0) > 3000:
        shift += 10
        notes.append("away long travel +10")
    return shift, notes


def _elo_method(report: dict, neutral: bool) -> dict | None:
    h, a = _get(report, "insights", "home_elo_rating"), _get(report, "insights", "away_elo_rating")
    if not (h and a and h.get("elo") and a.get("elo")):
        return None
    shift, notes = _context_shift(report)
    gap = h["elo"] + (0.0 if neutral else HOME_ADV_ELO) - a["elo"] + shift
    national = h.get("sample_source") == "eloratings.net" and a.get("sample_source") == "eloratings.net"
    weight = 2.0 if national else 0.5
    kind = "opponent-adjusted national Elo" if national else "form-only Elo (assumes average opponents)"
    extra = f"; context {', '.join(notes)}" if notes else ""
    return _method("elo", _davidson(gap), weight, f"{kind}: {h['elo']:.0f} vs {a['elo']:.0f}, gap {gap:+.0f}{extra}")


def _squad_method(report: dict, neutral: bool) -> dict | None:
    h, a = _get(report, "insights", "home_squad_strength"), _get(report, "insights", "away_squad_strength")
    hv = (h or {}).get("available_value") or (h or {}).get("total_value")
    av = (a or {}).get("available_value") or (a or {}).get("total_value")
    if not (hv and av and hv > 0 and av > 0):
        return None
    gap = max(-400.0, min(400.0, 100.0 * math.log(hv / av))) + (0.0 if neutral else HOME_ADV_ELO)
    return _method("squad_value", _davidson(gap), 0.75, f"available squad value {hv / 1e6:.0f}M vs {av / 1e6:.0f}M (ratio {hv / av:.2f})")


def calculate(report: dict) -> list[dict]:
    neutral = bool(_get(report, "match", "neutral"))
    own_home = _own_is_home(report)
    own_rows, opp_rows = _form_rows(report.get("form")), _form_rows(report.get("opponentForm"))
    home_rows, away_rows = (own_rows, opp_rows) if own_home else (opp_rows, own_rows)
    methods = [
        _market(report),
        _poisson_method("results_poisson", _weighted_rates(home_rows), _weighted_rates(away_rows), neutral, 1.0, "recent results"),
    ]
    xg_h, xg_a = (_get(report, "insights", "home_xg_estimate"), _get(report, "insights", "away_xg_estimate"))
    if xg_h and xg_a and xg_h.get("sample_size") and xg_a.get("sample_size"):
        xh = (xg_h["xg_for"] / xg_h["sample_size"], xg_h["xg_against"] / xg_h["sample_size"], float(xg_h["sample_size"]))
        xa = (xg_a["xg_for"] / xg_a["sample_size"], xg_a["xg_against"] / xg_a["sample_size"], float(xg_a["sample_size"]))
        methods.append(_poisson_method("xg_poisson", xh, xa, neutral, 1.5, "expected goals (xG)"))
    methods += [_elo_method(report, neutral), _squad_method(report, neutral)]
    return [m for m in methods if m]


# ----------------------------------------------------------------------------- audit
def audit(report: dict, methods: list[dict], now: datetime | None = None) -> dict:
    findings: list[dict] = []
    penalty = 0.0

    def add(severity: str, code: str, message: str, cost: float = 0.0):
        nonlocal penalty
        findings.append({"severity": severity, "code": code, "message": message})
        penalty += cost

    m = report.get("match") or {}
    if not (m.get("home_team") and m.get("away_team")):
        add("error", "no_fixture", "report has no upcoming fixture", 1.0)
    names = {x["name"] for x in methods}
    now = now or datetime.now(timezone.utc)
    kickoff = m.get("kickoff_utc")
    if m.get("status") not in (None, "notstarted"):
        add("error", "not_pre_match", f"match status is '{m.get('status')}': facts may include the result, so this is not a clean pre-match prediction", 0.5)
    elif kickoff:
        try:
            if datetime.fromisoformat(kickoff.replace("Z", "+00:00")) < now and report.get("generatedAt", "") >= kickoff:
                add("error", "after_kickoff", "report was generated after kickoff", 0.5)
        except ValueError:
            add("warn", "bad_kickoff", f"unparseable kickoff time {kickoff!r}")
    if "market" not in names:
        add("warn", "no_odds", "no bookmaker odds: the strongest single signal is missing, so the prediction leans on models only", 0.15)
    if "xg_poisson" not in names:
        add("info", "no_xg", "no xG data: goal model uses actual goals only", 0.04)
    if "elo" not in names:
        add("warn", "no_elo", "no Elo ratings in the report", 0.05)
    elif not any(x["name"] == "elo" and x["weight"] >= 2 for x in methods):
        add("info", "form_elo", "Elo is form-only (no opponent adjustment), so it carries little weight", 0.03)
    if "squad_value" not in names:
        add("info", "no_squad_value", "no squad market values", 0.02)
    if not m.get("lineup_confirmed"):
        add("info", "lineup_unconfirmed", "lineups are predicted, not confirmed", 0.05)
    for label, key in (("team", "form"), ("opponent", "opponentForm")):
        n = len(_form_rows(report.get(key)))
        if n == 0:
            add("error", "no_form", f"no recent results for the {label}", 0.3)
        elif n < 5:
            add("warn", "short_form", f"only {n} recent results for the {label}", 0.08)
    for side in ("home", "away"):
        missing = m.get(f"{side}_missing_players") or []
        if len(missing) >= 3:
            add("info", "many_absences", f"{len(missing)} {side} players missing (injured/suspended)")
        stand = m.get(f"{side}_team_standing") or {}
        if stand.get("played") is not None and stand["played"] <= 2:
            add("info", "early_season", f"{side} table position rests on {stand['played']} game(s)")
    conflicts = m.get("source_conflicts") or []
    if conflicts:
        fields = ", ".join(sorted({c.get('field', '?') for c in conflicts})[:6])
        add("info", "source_conflicts", f"{len(conflicts)} field(s) disagree between sources ({fields}); the pipeline kept one", 0.0)
    comp = report.get("dataCompleteness") or {}
    if comp.get("total"):
        ratio = comp["populated"] / comp["total"]
        if ratio < 0.7:
            add("warn", "low_completeness", f"only {ratio:.0%} of expected fields populated", 0.1)
    # internal consistency: independent methods should not wildly disagree
    probs = [x["probs"] for x in methods]
    if len(probs) >= 2:
        spread = max(max(p[k] for p in probs) - min(p[k] for p in probs) for k in range(3))
        if spread > 0.25:
            who = ", ".join(f"{x['name']} {x['probs'][0]:.0%}/{x['probs'][1]:.0%}/{x['probs'][2]:.0%}" for x in methods)
            add("warn", "methods_disagree", f"methods differ by up to {spread:.0%} on one outcome ({who})", 0.0)
    if "market" in names:
        mk = next(x for x in methods if x["name"] == "market")["probs"]
        rest = [x for x in methods if x["name"] != "market"]
        if rest:
            avg = [sum(x["probs"][k] * x["weight"] for x in rest) / sum(x["weight"] for x in rest) for k in range(3)]
            gap = max(abs(mk[k] - avg[k]) for k in range(3))
            if gap > 0.15:
                add("warn", "market_vs_models", f"bookmakers and the models differ by {gap:.0%} on an outcome; the market is weighted most, check for news (injuries, lineups) not in the data", 0.0)
    own = _get(report, "insights", "prediction", "blended")
    score = max(0.0, min(1.0, 1.0 - penalty))
    return {"findings": findings, "quality": round(score, 2), "pipeline_blend": own}


# ----------------------------------------------------------------------------- combine
def combine(methods: list[dict], quality: float) -> dict:
    tw = sum(x["weight"] for x in methods)
    ens = tuple(sum(x["probs"][k] * x["weight"] for x in methods) / tw for k in range(3))
    shrink = 0.3 * (1 - quality)
    final = tuple((1 - shrink) * ens[k] + shrink * BASE_RATES[k] for k in range(3))
    pick = max(range(3), key=lambda k: final[k])
    rates = [x["rates"] for x in methods if x["rates"]]
    lam = None
    if rates:
        wsum = sum(x["weight"] for x in methods if x["rates"])
        lam = (sum(x["rates"][0] * x["weight"] for x in methods if x["rates"]) / wsum, sum(x["rates"][1] * x["weight"] for x in methods if x["rates"]) / wsum)
    return {"ensemble": ens, "final": final, "shrink": shrink, "pick": pick, "pick_probability_pct": round(100 * final[pick], 1),
            "confidence_pct": _calibrated_confidence(100 * final[pick]), "lambda": lam}


def goals_summary(lam: tuple[float, float] | None) -> dict | None:
    if not lam:
        return None
    grid = score_grid(lam[0], lam[1], DC_RHO)
    best: dict[str, tuple[tuple[int, int], float]] = {}
    for (i, j), p in grid.items():
        k = "home win" if i > j else ("draw" if i == j else "away win")
        if k not in best or p > best[k][1]:
            best[k] = ((i, j), p)
    return {
        "expected_goals": (round(lam[0], 2), round(lam[1], 2)),
        "likely_scorelines": [{"result": k, "score": f"{s[0]}-{s[1]}", "pct": round(100 * p, 1)} for k, (s, p) in sorted(best.items(), key=lambda kv: -kv[1][1])],
        "over_2_5_pct": round(100 * sum(p for (i, j), p in grid.items() if i + j > 2), 1),
        "btts_pct": round(100 * sum(p for (i, j), p in grid.items() if i >= 1 and j >= 1), 1),
    }


# ----------------------------------------------------------------------------- uncertainty
def monte_carlo(methods: list[dict], quality: float, draws: int, seed: int = 0) -> dict:
    """Resample method weights (Dirichlet around the nominal weights), per-method logit noise (market
    small, models larger and shrinking with sample size) and the final shrink; report 10-90% ranges and
    how often each outcome is the favourite."""
    rng = random.Random(seed)
    sds = []
    for x in methods:
        if x["name"] == "market":
            sds.append(0.05)
        elif x["n"]:
            sds.append(0.30 / math.sqrt(max(1.0, x["n"] / 4)))
        else:
            sds.append(0.25)
    samples: list[tuple[float, float, float]] = []
    wins = [0, 0, 0]
    for _ in range(draws):
        ws = [rng.gammavariate(max(0.2, x["weight"] * 4), 1.0) for x in methods]
        tw = sum(ws)
        acc = [0.0, 0.0, 0.0]
        for x, w, sd in zip(methods, ws, sds):
            logits = [math.log(max(p, 1e-6)) + rng.gauss(0, sd) for p in x["probs"]]
            top = max(logits)
            ex = [math.exp(v - top) for v in logits]
            s = sum(ex)
            for k in range(3):
                acc[k] += w / tw * ex[k] / s
        shrink = 0.3 * (1 - quality)
        p = tuple((1 - shrink) * acc[k] + shrink * BASE_RATES[k] for k in range(3))
        samples.append(p)
        wins[max(range(3), key=lambda k: p[k])] += 1
    out = {"draws": draws, "favourite_share_pct": {o: round(100 * w / draws, 1) for o, w in zip(OUTCOMES, wins)}, "ranges_pct": {}}
    for k, o in enumerate(OUTCOMES):
        vals = sorted(s[k] for s in samples)
        out["ranges_pct"][o] = (round(100 * vals[int(0.1 * draws)], 1), round(100 * vals[int(0.9 * draws)], 1))
    return out


# ----------------------------------------------------------------------------- entry points
def analyze_report(report: dict, deep: bool = False, draws: int | None = None, now: datetime | None = None) -> dict:
    methods = calculate(report)
    aud = audit(report, methods, now)
    if not methods:
        return {"home": _get(report, "match", "home_team"), "away": _get(report, "match", "away_team"), "audit": aud, "methods": [], "prediction": None}
    comb = combine(methods, aud["quality"])
    mc = monte_carlo(methods, aud["quality"], draws or (100_000 if deep else 10_000))
    pipe = aud["pipeline_blend"]
    if pipe:
        pf = (pipe["home_win_pct"] / 100, pipe["draw_pct"] / 100, pipe["away_win_pct"] / 100)
        diff = max(abs(pf[k] - comb["final"][k]) for k in range(3))
        if diff > 0.10:
            aud["findings"].append({"severity": "info", "code": "pipeline_differs", "message": f"this analysis differs from the pipeline's own blend by up to {diff:.0%} on an outcome"})
    return {
        "home": _get(report, "match", "home_team"), "away": _get(report, "match", "away_team"), "own_is_home": _own_is_home(report),
        "competition": _get(report, "match", "competition"), "kickoff_utc": _get(report, "match", "kickoff_utc"),
        "audit": aud, "methods": methods,
        "prediction": {
            "home_win_pct": round(100 * comb["final"][0], 1), "draw_pct": round(100 * comb["final"][1], 1), "away_win_pct": round(100 * comb["final"][2], 1),
            "pick": OUTCOMES[comb["pick"]], "pick_probability_pct": comb["pick_probability_pct"], "confidence_pct": comb["confidence_pct"],
            "shrink_toward_base_rates": round(comb["shrink"], 3), "goals": goals_summary(comb["lambda"]), "uncertainty": mc,
        },
    }


def format_markdown(a: dict) -> str:
    p, aud = a["prediction"], a["audit"]
    lines = [f"# {a['home']} vs {a['away']}" + (f" -- {a['competition']}" if a.get("competition") else ""), ""]
    lines.append(f"## Data audit (quality {aud['quality']:.0%})")
    order = {"error": 0, "warn": 1, "info": 2}
    for f in sorted(aud["findings"], key=lambda f: order[f["severity"]]):
        lines.append(f"- **{f['severity']}** ({f['code']}): {f['message']}")
    if not aud["findings"]:
        lines.append("- no issues found")
    lines += ["", "## Calculations", "| method | home | draw | away | weight | basis |", "|---|---|---|---|---|---|"]
    for m in a["methods"]:
        lines.append(f"| {m['name']} | {m['probs'][0]:.1%} | {m['probs'][1]:.1%} | {m['probs'][2]:.1%} | {m['weight']} | {m['why']} |")
    if not p:
        return "\n".join(lines + ["", "No method could run on this report: no prediction."])
    who = {"home": f"{a['home']} win", "draw": "Draw", "away": f"{a['away']} win"}[p["pick"]]
    lines += ["", "## Prediction",
              f"- **{a['home']} {p['home_win_pct']}% / Draw {p['draw_pct']}% / {a['away']} {p['away_win_pct']}%**",
              f"- Most likely: **{who}** ({p['pick_probability_pct']}%) -- calibrated chance the pick is right: **{p['confidence_pct']}%** (what such picks achieved in 8,054 held-out matches; not a guarantee)"]
    if p["shrink_toward_base_rates"]:
        lines.append(f"- Pulled {p['shrink_toward_base_rates']:.0%} toward base rates because the data is incomplete (quality {aud['quality']:.0%})")
    u = p["uncertainty"]
    lines.append(f"- 10-90% range from {u['draws']:,} simulations: " + ", ".join(f"{o} {lo}-{hi}%" for o, (lo, hi) in u["ranges_pct"].items()))
    lines.append("- Favourite in simulations: " + ", ".join(f"{o} {v}%" for o, v in u["favourite_share_pct"].items()))
    g = p["goals"]
    if g:
        lines.append(f"- Expected goals {g['expected_goals'][0]}-{g['expected_goals'][1]}; over 2.5: {g['over_2_5_pct']}%; both score: {g['btts_pct']}%; likeliest scorelines: " + ", ".join(f"{s['score']} ({s['result']}, {s['pct']}%)" for s in g["likely_scorelines"]))
    pipe = aud.get("pipeline_blend")
    if pipe:
        lines.append(f"- Cross-check, pipeline blend in the report: {pipe['home_win_pct']}/{pipe['draw_pct']}/{pipe['away_win_pct']}")
    return "\n".join(lines)


def _collect(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        out += sorted(p.glob("*.json")) if p.is_dir() else [p]
    return out


def _llm_args(argv: list[str]) -> tuple[bool, str | None, list[str]]:
    """--llm [model] : the optional model name is consumed only when it doesn't look like a path."""
    if "--llm" not in argv:
        return False, None, argv
    i = argv.index("--llm")
    model = None
    rest = argv[:i] + argv[i + 1:]
    if i + 1 < len(argv) and ":" in argv[i + 1] and not Path(argv[i + 1]).exists() and not argv[i + 1].startswith("--"):
        model = argv[i + 1]
        rest = argv[:i] + argv[i + 2:]
    return True, model, rest


def main(argv: list[str]) -> int:
    use_llm, llm_model, argv = _llm_args(argv)
    think = "--fast" not in argv   # thinking mode unless --fast
    deep = "--deep" in argv
    as_json = "--json" in argv
    files = _collect([a for a in argv[1:] if not a.startswith("--")])
    if not files:
        print("usage: python -m football.analyze report.json [more.json | folder/] [--deep] [--json]", file=sys.stderr)
        return 2
    results = []
    for f in files:
        try:
            report = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"skipping {f}: {e}", file=sys.stderr)
            continue
        analysis = analyze_report(report, deep=deep)
        if use_llm and analysis["prediction"]:
            from . import llm_audit  # noqa: PLC0415 -- optional; talks to a local Ollama only when asked
            analysis["llm"] = llm_audit.audit_with_llm(llm_audit.build_brief(report, analysis), llm_model, think=think)
        results.append(analysis)
    if as_json:
        print(json.dumps(results, indent=1, default=str))
    else:
        from . import llm_audit  # noqa: PLC0415
        print("\n\n---\n\n".join(format_markdown(r) + (("\n\n" + llm_audit.format_llm_section(r["llm"])) if r.get("llm") else "") for r in results))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
