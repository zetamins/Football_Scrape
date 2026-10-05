"""Oracle pipeline: facts -> audit -> quant baseline -> LLM context panel -> adjusted exact score distribution -> calibrated prediction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..prediction import _calibrated_confidence
from . import context, debate, llm, quant
from .facts import audit_facts, extract_facts

OUTCOMES = ("home", "draw", "away")

# Draw lens. Observed draw frequency by the model's draw probability, measured on 8,054 held-out international matches 2018-2026
# (history model; the same table the confidence map uses). (upper bound of the draw probability in %, tier, observed draw rate in %).
# The probability itself was already calibrated (mean 23.2% vs 23.2% actual) and ranks draws with AUC 0.645; team draw tendency and
# low-scoring form added nothing beyond it (weights ~0), so this is a presentation of risk, not a new predictor.
# Home / draw / away share of the 8,054 held-out international matches (2018-26): the prior the final probabilities shrink toward when the data quality is below 100%.
# (The older analyze pipeline uses 47/25/28, which overstates draws by 1.8 points.)
BASE_RATES = (0.476, 0.232, 0.292)
DRAW_TIERS = ((15, "very low", 7.8), (19, "low", 14.2), (22, "moderate", 20.2), (25, "moderate", 23.7), (28, "elevated", 28.6), (31, "elevated", 31.8), (101, "high", 31.0))
TOSS_UP_GAP_PCT, TOSS_UP_MIN_DRAW_PCT = 5.0, 28.0
# Draw alert levels, measured on the 8,054 held-out matches and stable across 2018-21 / 2022-23 / 2024-26 (precision = share of flagged
# matches that ended level, base rate 23.2%; recall = share of ALL draws that were flagged; fires = share of matches flagged):
#   watch  draw >= 27%: fires 38.5%, precision 31.2%, recall 51.9%      alert  draw >= 29%: fires 23.7%, precision 31.8%, recall 32.6%
# (re-measured on the exact venue-aware Poisson + Dixon-Coles model the engine now uses, rolling out-of-sample, 8,054 matches)
# These are risk flags, not picks: even the alert level is wrong about two times in three.
DRAW_ALERTS = ((29.0, "alert", {"fires_pct": 23.7, "precision_pct": 31.8, "recall_pct": 32.6}), (27.0, "watch", {"fires_pct": 38.5, "precision_pct": 31.2, "recall_pct": 51.9}))
# A "call a draw in toss-ups" pick rule was tested (|home-away| < 5 pts and draw >= 28%): +3.6 points on the ~5% of matches where it fires
# (36.3% vs 32.7%), but +3.1 / -5.8 / +11.8 in three periods and a 95% interval of [-4.3, +10.9], so it is shown as a label, not used as the pick.


def draw_lens(final: list[float], sim: dict, lam_h: float, lam_a: float) -> dict:
    """Draw risk with its observed hit rate, a toss-up label, double chances and the likeliest drawn scorelines."""
    home, draw, away = (100 * x for x in final)
    tier, observed = next((t, o) for ub, t, o in DRAW_TIERS if draw < ub)
    toss_up = abs(home - away) < TOSS_UP_GAP_PCT and draw >= TOSS_UP_MIN_DRAW_PCT
    flags = []
    if toss_up:
        flags.append("toss-up: the sides are level and a draw is about as likely as either win")
    if lam_h + lam_a < 2.2:
        flags.append(f"low-scoring game expected ({lam_h + lam_a:.2f} goals), which raises the share of 0-0 and 1-1 results")
    if max(home, away) >= 70:
        flags.append("heavy favourite: draws are rare here (about 11% historically), but a scoreless or 1-1 upset is the main way the favourite fails to win")
    level, stats = next(((name, st) for floor, name, st in DRAW_ALERTS if draw >= floor), ("none", None))
    return {"draw_pct": round(draw, 1), "tier": tier, "observed_draw_rate_pct": observed, "toss_up": toss_up, "alert": level, "alert_stats": stats,
            "double_chance_pct": {"home_or_draw": round(home + draw, 1), "draw_or_away": round(draw + away, 1), "home_or_away": round(home + away, 1)},
            "draw_scores_pct": sim["draw_scores_pct"], "flags": flags}


# Observed hit rate of the recommended selection by market, on the 8,054 held-out internationals (research/recommend_eval.py): the most likely
# of {1X2 top outcome, Over/Under 2.5, Both teams to score Yes/No} hit 68.2% overall (the model quoted 67.3% after the goal-market shrink); always taking the 1X2 pick hit 61.0%.
# Over/under and BTTS probabilities run a little too extreme, so each market's own observed rate is quoted next to the model probability.
OBSERVED_HIT_PCT = {"1X2": 76.8, "Over 2.5": 68.8, "Under 2.5": 61.2, "BTTS Yes": 53.2, "BTTS No": 62.3, "Double chance": 73.8}
# What a recommended bet of a GIVEN probability can expect, by KIND (research/reco_bands_by_kind.py, 8,054 held-out matches):
# - a 1X2 bet is the 1X2 top pick, so it quotes the same calibrated chance as the headline ("calibrated chance the pick is right"), which tracks reality (65-70% -> 70.1% actual);
# - a goal-market bet (Over/Under 2.5, BTTS) is flatter: above ~62% the model is overconfident (quoted 70-75% hit 67.6%, 75-80% hit 72.5%, 80%+ hit 77.8%).
GOAL_BET_HIT_BY_BAND = ((60, 56.7), (65, 59.8), (70, 65.0), (75, 65.9), (80, 76.2), (101, 81.2))
# Double chance (recommended only when no single outcome reaches 50%): hit rate by band (research/reco_dc_bands.py); below 65% it was never the pick, so the 65-70% rate is the floor.
DOUBLE_CHANCE_HIT_BY_BAND = ((70, 64.8), (75, 73.2), (80, 78.7), (101, 86.5))
# RULE (user request, measured in research/reco_min_goals.py): a goal-market bet (Over/Under 2.5, BTTS) is only recommended from 60%; below that it is a coin flip (the 50-60% goals bets hit 56.7%).
# When the best single 1X2 outcome is under 50%, the better double chance competes instead. Held-out: hit 72.8% (quoted 71.7%) against 68.2% for "most likely of everything".
GOALS_BET_MIN_PCT, DOUBLE_CHANCE_BELOW_PCT = 60.0, 60.0


def observed_hit_for(probability_pct: float, market: str = "1X2") -> float:
    """Held-out hit rate of recommended bets of this kind at about this probability. For 1X2 it is exactly the headline's calibrated confidence."""
    if market == "1X2":
        return _calibrated_confidence(probability_pct)
    table = DOUBLE_CHANCE_HIT_BY_BAND if market == "Double chance" else GOAL_BET_HIT_BY_BAND
    return next(rate for edge, rate in table if probability_pct < edge)


BENCHMARK_NOTE_PCT = 10.0
# INDEPENDENCE: the bookmaker odds are never an input to a forecast, a recommended bet, its strength or its cautions. They are only a benchmark: the largest gap between the engine
# and the odds is reported next to the bet (odds_gap) so a reader can see it, nothing more. (On 36 live fixtures the odds beat the models in 17 of the 20 big disagreements; the skill
# still does not copy them.)


def recommend(home: str, away: str, final: list[float], markets: dict, weak_model: bool = False, odds: dict | None = None, cautions: list[str] | None = None) -> dict:
    """The recommended bet for EVERY match. Eligible: the 1X2 top outcome (always); Over/Under 2.5 and Both teams to score only from GOALS_BET_MIN_PCT (below that they are coin flips);
    the better double chance only when no single outcome reaches DOUBLE_CHANCE_BELOW_PCT. The most likely eligible selection wins. `strength` says how much to trust it."""
    one = max(range(3), key=lambda k: final[k])
    over, btts = markets["over_2_5"], markets["btts"]
    names = {0: f"{home} to win", 1: "Draw", 2: f"{away} to win"}
    top = ("1X2", names[one], final[one])
    goals = [("Over 2.5", "Over 2.5 goals", over), ("Under 2.5", "Under 2.5 goals", 1 - over), ("BTTS Yes", "Both teams to score: Yes", btts), ("BTTS No", "Both teams to score: No", 1 - btts)]
    dcs = [("Double chance", f"{home} or draw", final[0] + final[1]), ("Double chance", f"draw or {away}", final[1] + final[2]), ("Double chance", "Either side to win (no draw)", final[0] + final[2])]
    best_dc = max(dcs, key=lambda c: c[2])
    eligible = [top] + [g for g in goals if 100 * g[2] >= GOALS_BET_MIN_PCT] + ([best_dc] if 100 * top[2] < DOUBLE_CHANCE_BELOW_PCT else [])
    market, selection, p = max(eligible, key=lambda c: c[2])
    pct = 100 * p
    strength = "very strong" if pct >= 80 else "strong" if pct >= 70 else "moderate" if pct >= 60 else "lean"
    if weak_model:
        strength = "lean"
    odds_gap = None
    if odds:         # benchmark only: reported, never used to change the bet, its strength or its cautions
        onames = (f"{home} win", "draw", f"{away} win")
        gaps = [100 * (final[k] - odds[("home", "draw", "away")[k]]) for k in range(3)]
        k = max(range(3), key=lambda i: abs(gaps[i]))
        odds_gap = {"outcome": onames[k], "engine_pct": round(100 * final[k], 1), "odds_pct": round(100 * odds[("home", "draw", "away")[k]], 1), "gap_pct": round(gaps[k], 1)}
    cautions = list(cautions or [])
    chosen = (market, selection, p)
    others = sorted([c for c in [top] + goals + [best_dc] if c != chosen and (c in eligible or c[0] == "Double chance")], key=lambda c: -c[2])
    not_recommended = [{"selection": s_, "probability_pct": round(100 * q, 1)} for m_, s_, q in sorted(goals, key=lambda c: -c[2]) if 100 * q < GOALS_BET_MIN_PCT and q > top[2]][:1]      # the goals bet the old rule would have picked over the 1X2 outcome
    reason = (f"no single outcome reaches {DOUBLE_CHANCE_BELOW_PCT:.0f}% (best: {names[one]} {100 * final[one]:.0f}%), so the double chance is recommended" if market == "Double chance" else "")
    return {"market": market, "selection": selection, "probability_pct": round(pct, 1), "observed_hit_pct": observed_hit_for(pct, market), "market_hit_pct": OBSERVED_HIT_PCT[market], "strength": strength,
            "weak_model": weak_model, "odds_gap": odds_gap, "cautions": cautions, "reason": reason, "not_recommended": not_recommended,
            "alternatives": [{"market": m, "selection": s_, "probability_pct": round(100 * q, 1)} for m, s_, q in others]}


def _cautions(facts: dict, audit: dict, spread: float) -> list[str]:
    """Reasons to hold a recommended bet more loosely. Shown next to the bet; they do not change its probability."""
    from .lineup import lineup_picture
    out = []
    if not facts["lineup_confirmed"]:
        out.append("lineups unconfirmed: re-run once they are")
    pic = lineup_picture(facts)
    unknown = sum(1 for s in ("home", "away") for a in pic[s]["absentees"] if a["status"] == "unknown")
    if unknown >= 2:
        out.append(f"{unknown} absentees are not in the squad list (impact unknown)")
    for s in ("home", "away"):
        if pic[s]["heavy_rotation"]:
            out.append(f"{facts['sides'][s]['name']} changed {facts['sides'][s]['rotation']['changed_players']} starters last match")
    if spread > 0.2:
        out.append(f"the rate sources disagree widely (spread {spread:.2f})")
    if audit["quality"] < 0.9:
        out.append(f"data quality {audit['quality']:.0%}")
    return out


def _parse_panel(spec: str | None) -> list[tuple[str, str]] | None:
    """None/'auto' -> default panel; 'none' -> no LLM; 'nvidia' -> default-panel members of that provider;
    'provider:model,provider:model' -> explicit panel."""
    if spec in (None, "auto"):
        return llm.default_panel()
    if spec == "none":
        return []
    if spec in llm.PROVIDERS and ":" not in spec:
        members = [(p, m) for p, m in llm.DEFAULT_PANEL if p == spec]
        return members or [(spec, llm.PROVIDERS[spec]["model"])]
    out = []
    for item in spec.split(","):
        provider, _, model = item.partition(":")
        out.append((provider, model or llm.PROVIDERS[provider]["model"]))
    return out


def _engine(facts: dict, use_odds: bool = False) -> dict | None:
    """Quant baseline shared by predict() and brief(): sources, combined rates, absences, probabilities. use_odds=False (default) is the
    independent view: bookmaker odds are not an input and only feed the odds challenge."""
    if not (facts["home"] and facts["away"]):
        return None                                           # no fixture in the report: the audit says so, there is nothing to forecast
    sources = quant.rate_sources(facts, use_market=use_odds)
    if not sources:
        return None
    lam_h0, lam_a0, spread = quant.combine_rates(sources)
    mh, ma, absence_notes = quant.absence_multipliers(facts)
    lam_h1, lam_a1, _ = quant.combine_rates(quant.apply_absences(sources, mh, ma))      # odds are not adjusted: they already price absences
    if any(s["name"] == "market" for s in sources) and absence_notes:
        absence_notes = [n + " -- applied to the non-odds sources only (odds already price known absences)" for n in absence_notes]
    return {"sources": sources, "lam_h0": lam_h0, "lam_a0": lam_a0, "spread": spread, "absence_notes": absence_notes, "lam_h1": lam_h1, "lam_a1": lam_a1,
            "probs": quant.outcome_probs(lam_h1, lam_a1)}


def _brief_impl(report: dict, use_odds: bool = False) -> dict:
    """What a reviewer (an LLM agent or a person) needs to give context adjustments: the tagged brief, the evidence tags, the
    baseline, the audit, and the exact opinion format."""
    facts = extract_facts(report)
    eng = _engine(facts, use_odds)
    has_model = bool(eng) and any(s["name"] == "history" for s in eng["sources"])
    out = {"home": facts["home"], "away": facts["away"], "mode": "market-informed" if use_odds else "independent", "audit": audit_facts(facts, independent=not use_odds, has_trained_model=has_model), "opinion_format": OPINION_FORMAT, "bounds": {"rate_pct": context.MAX_RATE_PCT, "draw_pp": context.MAX_DRAW_PCT}}
    if eng is None:
        return {**out, "brief": None, "tags": [], "baseline": None}
    baseline = {"lam_home": eng["lam_h1"], "lam_away": eng["lam_a1"], "home": eng["probs"][0], "draw": eng["probs"][1], "away": eng["probs"][2]}
    text, tags = context.build_brief(facts, baseline, out["mode"])
    return {**out, "opinion_example": context.EXAMPLE_OPINION, "brief": text, "tags": sorted(tags), "baseline": {k: round(v, 4) for k, v in baseline.items()},
            "challenge": debate.challenge(facts, eng), "dossier": debate.dossier(facts)}


OPINION_FORMAT = {
    "home_rate_pct": "-12..12, change to the home side's expected goals (0 if no justified change)",
    "away_rate_pct": "-12..12, change to the away side's expected goals",
    "draw_bias_pct": "-3..3, percentage points moved toward (+) or away from (-) a draw",
    "confidence": "0..1 (below 0.2 and every adjustment is ignored)",
    "factors": [{"effect": "home_rate_pct|away_rate_pct|draw_bias_pct", "evidence": "[TAG] exactly as printed in the brief (not [BASELINE]/[FIXTURE], not an absentee marked fringe/unknown); every non-zero number above needs a factor with the SAME effect", "note": "max 25 words"}],
    "data_gaps": ["what is missing that would matter"],
    "advocates": {"home": "<=90 words: the strongest honest case for the HOME side, citing [TAGS] from the dossier/brief",
                  "away": "<=90 words: the strongest honest case for the AWAY side, citing [TAGS]",
                  "odds_challenge": "<=90 words: why the odds might be wrong, and why they are probably right; cite [TAGS]",
                  "verdict": "odds_right | odds_overrate_home | odds_overrate_away | unclear"},
}


def _predict_impl(report: dict, panel: str | list | None = "auto", sims: int | None = None, seed: int = 0, use_cache: bool = True,
            opinions: list[dict] | None = None, opinion_trust: float | None = None, use_odds: bool = False) -> dict:
    facts = extract_facts(report)
    result: dict = {"home": facts["home"], "away": facts["away"], "competition": facts["competition"], "kickoff": facts["kickoff"]}
    eng = _engine(facts, use_odds)
    audit = audit_facts(facts, independent=not use_odds, has_trained_model=bool(eng) and any(s["name"] == "history" for s in eng["sources"]))
    result["audit"] = audit
    result["mode"] = "market-informed" if use_odds else "independent"
    if eng is None:
        return {**result, "prediction": None, "reason": "no rate source could be computed from this report"}
    result["challenge"] = debate.challenge(facts, eng)
    result["dossier"] = debate.dossier(facts)
    result["advocates"] = None
    sources, lam_h0, lam_a0, spread, absence_notes = eng["sources"], eng["lam_h0"], eng["lam_a0"], eng["spread"], eng["absence_notes"]
    lam_h1, lam_a1, base_probs = eng["lam_h1"], eng["lam_a1"], eng["probs"]
    result["engine"] = {
        "sources": [{"name": s["name"], "lam_home": round(s["lam"][0], 3), "lam_away": round(s["lam"][1], 3), "weight": s["weight"], "why": s["why"],
                     "probs": [round(p, 4) for p in quant.outcome_probs(*s["lam"])]} for s in sources],
        "combined": {"lam_home": round(lam_h0, 3), "lam_away": round(lam_a0, 3), "source_spread": round(spread, 3)},
        "absences": absence_notes, "after_absences": {"lam_home": round(lam_h1, 3), "lam_away": round(lam_a1, 3), "probs": [round(p, 4) for p in base_probs]},
    }
    members = _parse_panel(panel) if not isinstance(panel, list) else panel
    adjust = {e: 0.0 for e in context.EFFECTS}
    if opinions:        # externally supplied reviewer opinion(s), e.g. from a Claude Code / OpenCode agent skill
        opinions = [o if isinstance(o, dict) else {} for o in opinions]      # a non-object opinion counts as an empty one
        baseline = {"lam_home": lam_h1, "lam_away": lam_a1, "home": base_probs[0], "draw": base_probs[1], "away": base_probs[2]}
        _, tags = context.build_brief(facts, baseline, result["mode"])
        weak = context.weak_absence_tags(facts)
        validated = [context.validate_opinion(o, tags, weak) for o in opinions]
        agg = context.aggregate(validated, trust_override=opinion_trust)
        adjust = agg["adjust"]
        factors = [{**f, "by": "reviewer"} for v in validated for f in v["factors"]]
        result["panel"] = {**{k: agg[k] for k in ("adjust", "n", "trust", "agreement")}, "factors": factors,
                           "members": [{"provider": "reviewer", "model": "agent", "ok": True, **v} for v in validated],
                           "data_gaps": sorted({g for v in validated for g in v["data_gaps"]})}
    elif members:
        baseline = {"lam_home": lam_h1, "lam_away": lam_a1, "home": base_probs[0], "draw": base_probs[1], "away": base_probs[2]}
        pr = context.run_panel(facts, baseline, members, use_cache=use_cache, mode=result["mode"])
        adjust = pr["adjust"]
        result["panel"] = {k: pr[k] for k in ("adjust", "n", "trust", "agreement", "members", "factors", "data_gaps")}
    else:
        result["panel"] = None
    lam_h2 = lam_h1 * (1 + adjust["home_rate_pct"] / 100)
    lam_a2 = lam_a1 * (1 + adjust["away_rate_pct"] / 100)
    sim = quant.exact_distribution(lam_h2, lam_a2)
    gmarkets = quant.exact_distribution(*quant.shrink_total_goals(lam_h2, lam_a2))["markets"]     # goal markets only: see quant.shrink_total_goals
    probs = [sim["home"], sim["draw"], sim["away"]]
    pp = adjust["draw_bias_pct"] / 100
    if pp:                                  # move probability mass to/from the draw, taking it proportionally from the two sides
        decisive = probs[0] + probs[2]
        take = max(-probs[1], min(pp, decisive)) if pp > 0 else max(pp, -probs[1])
        probs = [probs[0] - take * probs[0] / decisive, probs[1] + take, probs[2] - take * probs[2] / decisive]
    shrink = 0.3 * (1 - audit["quality"])
    final = [(1 - shrink) * probs[k] + shrink * BASE_RATES[k] for k in range(3)]
    pick = max(range(3), key=lambda k: final[k])
    spread_eff = (spread ** 2 + (0.02 * (1 - (result["panel"] or {}).get("agreement", 1) if result["panel"] and result["panel"].get("agreement") else 0)) ** 2) ** 0.5
    result["prediction"] = {
        "home_win_pct": round(100 * final[0], 1), "draw_pct": round(100 * final[1], 1), "away_win_pct": round(100 * final[2], 1),
        "pick": OUTCOMES[pick], "pick_probability_pct": round(100 * final[pick], 1), "confidence_pct": _calibrated_confidence(100 * final[pick]),
        "lam_home": round(lam_h2, 3), "lam_away": round(lam_a2, 3), "shrink_toward_base_rates": round(shrink, 3),
        "ranges_pct": quant.probability_spread(lam_h2, lam_a2, spread_eff),
        "draw": draw_lens(final, sim, lam_h2, lam_a2),
        "recommendation": recommend(facts["home"], facts["away"], final, gmarkets, weak_model=not (any(s["name"] == "history" for s in sources)), odds=facts["odds"],
                                    cautions=_cautions(facts, audit, spread)),
        "simulation": {"exact": True, "expected_goals": [round(x, 2) for x in sim["expected_goals"]], "top_scores": sim["top_scores"],
                       "markets_pct": {k: round(100 * v, 1) for k, v in gmarkets.items()}, "margin_pct": sim["margin_pct"]},
    }
    # the advocates are written by the engine from the tagged dossier (an agent's free text caused new errors in every test round); only an enumerated verdict from the opinion is read
    from . import draft as _draft
    base = {"lam_home": lam_h1, "lam_away": lam_a1, "home": base_probs[0], "draw": base_probs[1], "away": base_probs[2]}
    _, adv_tags = context.build_brief(facts, base, result["mode"])
    aj = _draft.auto_judgement(result, facts, opinions[0] if opinions else None, adv_tags)
    result["advocates"] = debate.check_advocates({"home": aj["case_home"], "away": aj["case_away"], "odds_challenge": aj["odds_challenge"], "verdict": aj["odds_challenge"].split(" - ")[0]}, adv_tags)
    return result


UNREADABLE = (TypeError, KeyError, AttributeError, ValueError, IndexError, ZeroDivisionError)


def _unreadable(report, err: Exception) -> dict:
    m = report.get("match") if isinstance(report, dict) and isinstance(report.get("match"), dict) else {}
    msg = f"the report could not be analysed ({type(err).__name__}: {err}); a field has an unexpected type or shape"
    return {"home": m.get("home_team") if isinstance(m.get("home_team"), str) else None, "away": m.get("away_team") if isinstance(m.get("away_team"), str) else None,
            "competition": None, "kickoff": None, "mode": "independent", "prediction": None, "reason": msg, "brief": None, "challenge": None, "dossier": {"home": [], "away": [], "both": []},
            "advocates": None, "audit": {"quality": 0.0, "findings": [{"severity": "error", "code": "unreadable_report", "message": msg}]}}


def brief(report: dict, use_odds: bool = False) -> dict:
    try:
        return _brief_impl(report, use_odds)
    except UNREADABLE as e:
        return _unreadable(report, e)


def predict(report: dict, *args, **kwargs) -> dict:
    try:
        return _predict_impl(report, *args, **kwargs)
    except UNREADABLE as e:
        return _unreadable(report, e)


def format_report(r: dict) -> str:
    p, aud = r.get("prediction"), r["audit"]
    lines = [f"# {r['home']} vs {r['away']}" + (f" -- {r['competition']}" if r.get("competition") else ""), "", f"## 1. Data audit (quality {aud['quality']:.0%})"]
    order = {"error": 0, "warn": 1, "info": 2}
    lines += [f"- **{f['severity']}** ({f['code']}): {f['message']}" for f in sorted(aud["findings"], key=lambda f: order[f["severity"]])] or ["- no issues found"]
    if not p:
        return "\n".join(lines + ["", f"No prediction: {r.get('reason')}"])
    e = r["engine"]
    lines += ["", "## 2. Quantitative engine (expected goals per side)", "| source | home xG | away xG | win/draw/loss | weight | basis |", "|---|---|---|---|---|---|"]
    for s in e["sources"]:
        lines.append(f"| {s['name']} | {s['lam_home']} | {s['lam_away']} | {s['probs'][0]:.0%}/{s['probs'][1]:.0%}/{s['probs'][2]:.0%} | {s['weight']} | {s['why']} |")
    c = e["combined"]
    lines.append(f"\nCombined (weighted geometric mean): {c['lam_home']}-{c['lam_away']}, sources disagree by {c['source_spread']:.2f} (log scale).")
    for n in e["absences"]:
        lines.append(f"- Player-level absences: {n}")
    a = e["after_absences"]
    lines.append(f"After absences: {a['lam_home']}-{a['lam_away']} -> {a['probs'][0]:.1%}/{a['probs'][1]:.1%}/{a['probs'][2]:.1%}")
    lines += ["", "## 3. Context review (LLM panel or reviewer)"]
    pn = r["panel"]
    if not pn:
        lines.append("- disabled (--llm none): the prediction is purely quantitative")
    else:
        for m in pn["members"]:
            if m["ok"]:
                lines.append(f"- {m['model']} ({m['provider']}): home {m['adjust']['home_rate_pct']:+.1f}%, away {m['adjust']['away_rate_pct']:+.1f}%, draw {m['adjust']['draw_bias_pct']:+.1f}pp, confidence {m['confidence']:.2f}; "
                             f"{len(m['factors'])} evidenced factor(s), {len(m['rejected'])} rejected" + (" [cached]" if m.get("cached") else ""))
            else:
                lines.append(f"- {m['model']} ({m['provider']}): unavailable ({m['error']})")
        ad = pn["adjust"]
        lines.append(f"- **Panel result** ({pn['n']} voice(s), trust x{pn['trust']}, direction agreement {pn['agreement']}): home rate {ad['home_rate_pct']:+.2f}%, away rate {ad['away_rate_pct']:+.2f}%, draw {ad['draw_bias_pct']:+.2f}pp")
        for f in pn["factors"][:8]:
            lines.append(f"  - {f['evidence']} -> {f['effect']}: {f.get('note')} (by {f['by']})")
        if pn["data_gaps"]:
            lines.append("- Data gaps raised: " + "; ".join(pn["data_gaps"][:5]))
    lines += ["", "## 3b. Odds challenge and advocates", debate.format_challenge(r.get("challenge")), "", debate.format_dossier(r["dossier"], r["home"], r["away"])]
    adv = r.get("advocates")
    if adv:
        lines += ["", "**Advocates (reviewer)**"]
        for key, title in (("home", f"Home advocate ({r['home']})"), ("away", f"Away advocate ({r['away']})"), ("odds_challenge", "Odds challenger")):
            if key in adv:
                a = adv[key]
                flag = " [UNCITED]" if a["uncited"] else (f" [unknown tags ignored: {', '.join(a['unknown_tags'])}]" if a["unknown_tags"] else "")
                lines.append(f"- {title}{flag}: {a['text']}")
        lines.append(f"- **Verdict on the odds: {adv['verdict']}** (advocates never move a probability; only the bounded, evidenced adjustments above do)")
    who = {"home": f"{r['home']} win", "draw": "Draw", "away": f"{r['away']} win"}[p["pick"]]
    sim = p["simulation"]
    rec = p["recommendation"]
    lines += ["", "## 4. Score distribution (exact Poisson + Dixon-Coles grid) and prediction",
              f"- **{r['home']} {p['home_win_pct']}% / Draw {p['draw_pct']}% / {r['away']} {p['away_win_pct']}%**",
              f"- Most likely: **{who}** ({p['pick_probability_pct']}%); calibrated chance the pick is right: **{p['confidence_pct']}%** (observed hit rate of such picks in 8,054 held-out matches; not a guarantee)",
              f"- **Recommended bet: {rec['selection']}** ({rec['market']}) {rec['probability_pct']}%; bets of this kind at this probability hit {rec['observed_hit_pct']}% in 8,054 held-out matches; strength: {rec['strength']}"
              + (" (weak model: treat as a lean)" if rec["weak_model"] else "") + "; next best: " + ", ".join(f"{a['selection']} {a['probability_pct']}%" for a in rec["alternatives"][:2])
              + (f". Why this market: {rec['reason']}" if rec["reason"] else "") + (f". Not recommended: {rec['not_recommended'][0]['selection']} {rec['not_recommended'][0]['probability_pct']}% (goals bets need {GOALS_BET_MIN_PCT:.0f}%, below that they are coin flips)" if rec["not_recommended"] else ""),
              *(["- Cautions on the recommended bet: " + "; ".join(rec["cautions"])] if rec["cautions"] else []),
              *([f"- Benchmark only (odds are not an input; the bet and its strength do not use them): the odds differ from the engine by {abs(rec['odds_gap']['gap_pct']):.1f} points on {rec['odds_gap']['outcome']} (engine {rec['odds_gap']['engine_pct']}%, odds {rec['odds_gap']['odds_pct']}%)"]
                if rec["odds_gap"] and abs(rec["odds_gap"]["gap_pct"]) >= BENCHMARK_NOTE_PCT else []),
              "- Plausible range if the goal rates are off by the sources' disagreement: " + ", ".join(f"{k} {lo}-{hi}%" for k, (lo, hi) in p["ranges_pct"].items()),
              f"- Expected goals {sim['expected_goals'][0]}-{sim['expected_goals'][1]}; likeliest scores " + ", ".join(f"{s['score']} ({s['pct']}%)" for s in sim["top_scores"][:4]),
              f"- Over 1.5 / 2.5 / 3.5: {sim['markets_pct']['over_1_5']}% / {sim['markets_pct']['over_2_5']}% / {sim['markets_pct']['over_3_5']}%; both score {sim['markets_pct']['btts']}%; clean sheet home {sim['markets_pct']['home_cs']}% / away {sim['markets_pct']['away_cs']}%"]
    d = p["draw"]
    dc = d["double_chance_pct"]
    best_dc = ("home or draw", dc["home_or_draw"]) if dc["home_or_draw"] >= dc["draw_or_away"] else ("draw or away", dc["draw_or_away"])
    lines += ["", "### Draw lens",
              f"- Draw probability {d['draw_pct']}% -> **{d['tier']} draw risk**: matches at this level ended level about {d['observed_draw_rate_pct']}% of the time in 8,054 held-out internationals (a draw is rarely the single most likely result; even the top tier is about 3 in 10).",
              (f"- **Draw {d['alert'].upper()}**: matches flagged at this level ended level {d['alert_stats']['precision_pct']}% of the time (base rate 23%); flagging at this level catches about {d['alert_stats']['recall_pct']}% of all draws while flagging {d['alert_stats']['fires_pct']}% of matches. A risk flag, not a pick: it is wrong about two times in three."
               if d["alert"] != "none" else f"- No draw alert (draw probability below 27%): about {d['observed_draw_rate_pct']}% of such matches still end level, and the flag misses roughly half of all draws, which is why a draw can never be the headline call."),
              f"- Double chance: {r['home']} or draw {dc['home_or_draw']}%, draw or {r['away']} {dc['draw_or_away']}%, either side wins {dc['home_or_away']}% (best cover: {best_dc[0]} {best_dc[1]}%).",
              "- Drawn scorelines: " + ", ".join(f"{k} {v}%" for k, v in d["draw_scores_pct"].items() if v >= 0.5)]
    lines += [f"- Flag: {x}" for x in d["flags"]]
    if p["shrink_toward_base_rates"]:
        lines.append(f"- Pulled {p['shrink_toward_base_rates']:.0%} toward base rates because the data is incomplete")
    return "\n".join(lines)


def _main(argv: list[str]) -> int:
    args = argv[1:]
    def flag(name: str, default=None):
        if name in args:
            i = args.index(name)
            val = args[i + 1] if i + 1 < len(args) else default
            del args[i:i + 2]
            return val
        return default
    panel = flag("--llm", "auto")
    sims = int(flag("--sims", 200_000))
    as_json = "--json" in args
    use_cache = "--no-cache" not in args
    use_odds = "--with-odds" in args
    do_log = "--log" in args
    as_table = "--table" in args
    opinion_arg, opinion_file, trust_arg = flag("--opinion"), flag("--opinion-file"), flag("--trust")
    if args and args[0] == "lint":
        return _lint_cli(args[1:], use_odds)
    if args and args[0] == "audit":
        return _audit_cli(args[1:], use_odds, opinion_file)
    if args and args[0] == "roles":
        return _roles_cli(args[1:])
    if args and args[0] == "review":
        return _review_cli(args[1:], use_odds)
    if args and args[0] == "draft":
        return _draft_cli(args[1:], use_odds, opinion_file)
    if args and args[0] == "compose":
        return _compose_cli(args[1:], use_odds, opinion_file)
    if args and args[0] == "score":
        from . import scorecard
        return scorecard.main(args[1:])
    do_brief = bool(args) and args[0] == "brief"
    if do_brief:
        args = args[1:]
    files: list[Path] = []
    for a in args:
        if a.startswith("--"):
            continue
        p = Path(a)
        files += sorted(p.glob("*.json")) if p.is_dir() else [p]
    if not files:
        print("usage: python -m football.oracle [brief] report.json [more.json | folder/] [--llm auto|none|nvidia|openrouter|ollama|provider:model,...] [--opinion JSON | --opinion-file F [--trust X]] [--with-odds] [--json] [--no-cache] [--log] [--table]   |   lint report.json opinion.json   |   audit report.json answer.md   |   draft report.json   |   compose report.json judgement.json   |   score <folder> --results results.csv   (--sims is accepted and ignored: the score distribution is exact)", file=sys.stderr)
        return 2
    opinions = None
    try:
        if opinion_file:
            opinions = [json.loads(Path(opinion_file).read_text(encoding="utf-8"))]
        elif opinion_arg:
            opinions = [json.loads(opinion_arg)]
        if opinions and not isinstance(opinions[0], dict):
            print("the opinion must be a JSON object (see the example in the brief)", file=sys.stderr)
            return 2
    except (OSError, ValueError) as e:
        print(f"cannot read the opinion JSON: {e}", file=sys.stderr)
        return 2
    out = []
    for f in files:
        try:
            report = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"skipping {f}: {e}", file=sys.stderr)
            continue
        if do_brief:
            out.append(brief(report, use_odds=use_odds))
        else:
            if do_log:
                _log_forward(report, use_odds)
            out.append(predict(report, panel="none" if opinions else panel, sims=sims, use_cache=use_cache, opinions=opinions,
                               opinion_trust=float(trust_arg) if trust_arg is not None else None, use_odds=use_odds))
    if do_brief:
        print(json.dumps(out, indent=1, default=str) if as_json else "\n\n---\n\n".join(format_brief(b) for b in out))
    else:
        print(json.dumps(out, indent=1, default=str) if as_json else format_table(out) if as_table else "\n\n---\n\n".join(format_report(r) for r in out))
    return 0


def main(argv: list[str]) -> int:
    try:
        return _main(argv)
    except UNREADABLE as e:                 # a scraped field with an unexpected type or shape: say so plainly instead of printing a traceback
        print(f"cannot analyse the input: {type(e).__name__}: {e} (a field in the report has an unexpected type or shape)", file=sys.stderr)
        return 2


def _lint_cli(args: list[str], use_odds: bool) -> int:
    from . import lint
    paths = [a for a in args if not a.startswith("--")]
    if len(paths) != 2:
        print("usage: python -m football.oracle lint report.json opinion.json [--with-odds]", file=sys.stderr)
        return 2
    try:
        report, opinion = (json.loads(Path(p).read_text(encoding="utf-8")) for p in paths)
    except (OSError, ValueError) as e:
        print(f"cannot read the files: {e}", file=sys.stderr)
        return 2
    if not isinstance(report, dict):
        print("cannot lint: the report file does not hold a JSON object", file=sys.stderr)
        return 2
    try:
        print(lint.format_lint(lint.lint_opinion(report, opinion, use_odds=use_odds)))
    except UNREADABLE as e:
        print(f"cannot lint: the report could not be analysed ({type(e).__name__}: {e})", file=sys.stderr)
        return 2
    return 0


def _draft_cli(args: list[str], use_odds: bool, opinion_file: str | None) -> int:
    from . import draft
    paths = [a for a in args if not a.startswith("--")]
    if len(paths) != 1:
        print("usage: python -m football.oracle draft report.json [--opinion-file opinion.json] [--with-odds]", file=sys.stderr)
        return 2
    try:
        report = json.loads(Path(paths[0]).read_text(encoding="utf-8"))
        opinion = json.loads(Path(opinion_file).read_text(encoding="utf-8")) if opinion_file else None
    except (OSError, ValueError) as e:
        print(f"cannot read the files: {e}", file=sys.stderr)
        return 2
    print(draft.draft_answer(report, opinion, use_odds))
    return 0


def _compose_cli(args: list[str], use_odds: bool, opinion_file: str | None) -> int:
    from . import draft
    paths = [a for a in args if not a.startswith("--")]
    if len(paths) != 2:
        print("usage: python -m football.oracle compose report.json judgement.json [--opinion-file opinion.json] [--with-odds] [--free-text]   (default: only analyst_note is read, every other line is the engine's; judgement.json keys: " + ", ".join(draft.JUDGEMENT) + ")", file=sys.stderr)
        return 2
    try:
        report = json.loads(Path(paths[0]).read_text(encoding="utf-8"))
        judgement = json.loads(Path(paths[1]).read_text(encoding="utf-8"))
        opinion = json.loads(Path(opinion_file).read_text(encoding="utf-8")) if opinion_file else None
    except (OSError, ValueError) as e:
        print(f"cannot read the files: {e}", file=sys.stderr)
        return 2
    print(draft.compose_answer(report, judgement, opinion, use_odds, free_text="--free-text" in args))
    return 0


def _audit_cli(args: list[str], use_odds: bool, opinion_file: str | None) -> int:
    from . import audit_answer
    paths = [a for a in args if not a.startswith("--")]
    if len(paths) != 2:
        print("usage: python -m football.oracle audit report.json answer.md [--opinion-file opinion.json] [--with-odds]", file=sys.stderr)
        return 2
    try:
        report = json.loads(Path(paths[0]).read_text(encoding="utf-8"))
        answer = Path(paths[1]).read_text(encoding="utf-8")
        opinion = json.loads(Path(opinion_file).read_text(encoding="utf-8")) if opinion_file else None
    except (OSError, ValueError) as e:
        print(f"cannot read the files: {e}", file=sys.stderr)
        return 2
    print(audit_answer.format_audit(audit_answer.audit_answer(report, answer, opinion, use_odds)))
    return 0


def _roles_cli(args: list[str]) -> int:
    paths = [a for a in args if not a.startswith("--")]
    files: list[Path] = []
    for a in paths:
        pth = Path(a)
        files += sorted(pth.glob("*.json")) if pth.is_dir() else [pth]
    if not files:
        print("usage: python -m football.oracle roles report.json|folder   (lists absentees whose position is unknown, to look up and add to football/oracle/player_roles.json)", file=sys.stderr)
        return 2
    need: dict[str, str] = {}
    for f in files:
        try:
            facts = extract_facts(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError, AttributeError, TypeError):
            continue
        for side in ("home", "away"):
            for a in facts["sides"][side]["absentees"]:
                if not a["in_squad_list"] and not a["role"]:
                    need[a["name"]] = facts["sides"][side]["name"]
    print(f"{len(need)} absentee(s) need a position (G/D/M/F); add them as \"Name\": \"D\" under \"players\" in football/oracle/player_roles.json")
    for n, t in sorted(need.items()):
        print(f"- {n} ({t})")
    return 0


def _review_cli(args: list[str], use_odds: bool) -> int:
    from . import review_pack
    paths = [a for a in args if not a.startswith("--")]
    if len(paths) != 2:
        print("usage: python -m football.oracle review report.json answer.md   (prints the pack for a separate reviewer agent)", file=sys.stderr)
        return 2
    try:
        report = json.loads(Path(paths[0]).read_text(encoding="utf-8"))
        answer = Path(paths[1]).read_text(encoding="utf-8")
    except (OSError, ValueError) as e:
        print(f"cannot read the files: {e}", file=sys.stderr)
        return 2
    print(review_pack.review_pack(report, answer, use_odds))
    return 0


def format_table(results: list[dict]) -> str:
    """One row per match: the numbers, the pick, the draw flag and the audit findings that matter. Several reports of the same fixture (a re-run for lineups) show once: the latest."""
    latest: dict[tuple, int] = {}
    for idx, r in enumerate(results):
        latest[(r.get("home"), r.get("away"), str(r.get("kickoff") or "")[:10]) if r.get("home") and r.get("away") else ("row", idx)] = idx
    hidden = len(results) - len(latest)
    results = [results[i] for i in sorted(latest.values())]
    lines = ["| # | Match | Competition | Home % | Draw % | Away % | Pick | Recommended bet | Draw flag | Data quality | Main audit findings |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        p, aud = r.get("prediction"), r["audit"]
        names = f"{r['home']} v {r['away']}"
        comp = (r.get("competition") or "").replace("UEFA Nations League", "UEFA NL")
        notable = [f["code"] for f in aud["findings"] if f["severity"] in ("error", "warn")] or [f["code"] for f in aud["findings"] if f["code"] in ("lineup_unconfirmed", "heavy_rotation", "empty_absentee_list")]
        findings = ", ".join(dict.fromkeys(notable)) or "-"
        if not p:
            lines.append(f"| {i} | {names} | {comp} | - | - | - | no prediction | - | - | {aud['quality']:.0%} | {findings} |")
            continue
        d = p["draw"]
        lines.append(f"| {i} | {names} | {comp} | {p['home_win_pct']:.1f} | {p['draw_pct']:.1f} | {p['away_win_pct']:.1f} | {p['pick']} ({p['pick_probability_pct']:.0f}%) | {p['recommendation']['selection']} {p['recommendation']['probability_pct']:.0f}% ({p['recommendation']['strength']}) | {d['alert'].upper() if d['alert'] != 'none' else '-'} | {aud['quality']:.0%} | {findings} |")
    if hidden:
        lines.append(f"\n({hidden} older report(s) of the same fixture hidden; the latest is shown.)")
    return "\n".join(lines)


def _log_forward(report: dict, use_odds: bool) -> None:
    """Append the absences-off / absences-on engine probabilities for the forward test (football/oracle/forward_log.py)."""
    from . import forward_log
    facts = extract_facts(report)
    sources = quant.rate_sources(facts, use_market=use_odds)
    rec = forward_log.make_record(facts, sources) if sources else None
    if rec:
        forward_log.append(rec)


def format_brief(b: dict) -> str:
    lines = [f"# BRIEF: {b['home']} vs {b['away']}", "", f"Data quality {b['audit']['quality']:.0%}"]
    lines += [f"- [{f['severity']}] {f['message']}" for f in b["audit"]["findings"]]
    if not b["brief"]:
        return "\n".join(lines + ["", "No quantitative baseline could be computed from this report."])
    lines += ["", "## Odds challenge", debate.format_challenge(b.get("challenge")), "", "## Advocate dossier (argue each side ONLY from these tags and the facts below)",
              debate.format_dossier(b["dossier"], b["home"], b["away"]), "", "## Facts (cite the [TAG] of the line you rely on)", b["brief"], "",
              "## Opinion file (--opinion-file). Bounds: rates +-%s%%, draw +-%spp; ONE [TAG] per factor, exactly as printed above; zero is the expected answer" % (b["bounds"]["rate_pct"], b["bounds"]["draw_pp"]),
              "Example (tags illustrative):", json.dumps(b["opinion_example"], indent=1), "", "Field guide:", json.dumps(b["opinion_format"], indent=1)]
    return "\n".join(lines)
