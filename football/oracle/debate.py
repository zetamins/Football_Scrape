"""Odds challenge + advocate dossier: the structured adversarial round before the final opinion.

* challenge(): what the models say WITHOUT the odds (xG, results, strength, with absences applied) next to the de-vigged odds, the
  gap per outcome, who the models lean to, and the total-goals disagreement. The base rate is stated: on 36 labelled fixtures the odds
  beat the models in 21 of the 30 matches where they disagreed by >= 10 points (the result went the odds' way 17 times, the models' 3).
  The burden of proof is on the challenger.
* dossier(): deterministic evidence points from the JSON for each side, each marked `priced` (already inside the engine's numbers) or
  unpriced, with a strength. A HOME advocate and an AWAY advocate (the agent / an LLM) argue from these tags; they may not cite anything else.
* check_advocates(): validates the advocates' tags and keeps their text for the report. They never move a probability by themselves:
  only the bounded, evidence-tagged adjustments in the opinion do.
"""

from __future__ import annotations

import re
from typing import Any

from . import quant

MAX_ABSENTEES = 30                       # every listed absentee gets a tag (the old cap of 8 left the rest invisible)
TAG_RE = re.compile(r"\[[^\]]+\]")
VERDICTS = ("odds_right", "odds_overrate_home", "odds_overrate_away", "unclear")
HISTORY_NOTE = ("on 36 labelled fixtures the odds were closer than the models in 21 of the 30 matches where they differed by >= 10 points "
                "(16 of 21 at >= 15 points); the result went the odds' way 17 times and the models' 3: challenge only with specific, unpriced evidence")


def _ppg(rows: list[dict], n: int = 6) -> float | None:
    rs = [r for r in rows[:n] if r.get("result") in ("W", "D", "L")]
    return sum({"W": 3, "D": 1, "L": 0}[r["result"]] for r in rs) / len(rs) if rs else None


def _gd(rows: list[dict], n: int = 6) -> float | None:
    rs = [r for r in rows[:n] if not r.get("shootout")]            # penalty goals are not goals scored in play
    return sum(min(r["gf"], quant.GOAL_CAP) - min(r["ga"], quant.GOAL_CAP) for r in rs) / len(rs) if rs else None


def _strength(diff: float, slight: float, moderate: float, strong: float) -> str | None:
    d = abs(diff)
    return "strong" if d >= strong else "moderate" if d >= moderate else "slight" if d >= slight else None


def dossier(facts: dict) -> dict:
    """{'home': [points favouring home], 'away': [...], 'both': [...]}; each point {tag, strength, priced, text}."""
    h, a = facts["sides"]["home"], facts["sides"]["away"]
    pts: list[tuple[str, dict]] = []

    def add(side: str, tag: str, strength: str | None, priced: bool, text: str):
        if strength:
            pts.append((side, {"tag": tag, "strength": strength, "priced": priced, "text": text}))

    ph, pa = _ppg(h["form"]), _ppg(a["form"])
    if ph is not None and pa is not None:
        side = "home" if ph > pa else "away"
        add(side, f"[{'H' if side == 'home' else 'A'}.form]", _strength(ph - pa, 0.4, 0.8, 1.4), True, f"recent form: {h['name']} {ph:.1f} pts/game vs {a['name']} {pa:.1f} over the last 6")
    gh, ga = _gd(h["form"]), _gd(a["form"])
    if gh is not None and ga is not None:
        side = "home" if gh > ga else "away"
        add(side, f"[{'H' if side == 'home' else 'A'}.form]", _strength(gh - ga, 0.5, 1.0, 1.7), True, f"goal difference per game: {h['name']} {gh:+.1f} vs {a['name']} {ga:+.1f}")
    if h["xg"] and a["xg"]:
        xh, xa = h["xg"]["for_pg"] - h["xg"]["against_pg"], a["xg"]["for_pg"] - a["xg"]["against_pg"]
        side = "home" if xh > xa else "away"
        add(side, "[BASELINE]", _strength(xh - xa, 0.3, 0.7, 1.2), True, f"xG difference per game: {h['name']} {xh:+.2f} vs {a['name']} {xa:+.2f}")
    if h["squad_value"] and a["squad_value"]:
        ratio = h["squad_value"] / a["squad_value"]
        side = "home" if ratio >= 1 else "away"
        big = max(ratio, 1 / ratio)
        add(side, "[BASELINE]", "strong" if big >= 3 else "moderate" if big >= 1.8 else "slight" if big >= 1.25 else None, True, f"squad market value x{big:.1f} in favour of {h['name'] if side == 'home' else a['name']}")
    if h["elo"] and a["elo"] and h["elo"]["national"] and a["elo"]["national"]:
        g = h["elo"]["rating"] - a["elo"]["rating"]
        side = "home" if g > 0 else "away"
        add(side, "[BASELINE]", _strength(g, 40, 100, 200), True, f"opponent-adjusted Elo gap {abs(g):.0f} to {h['name'] if side == 'home' else a['name']}")
    if facts["edge"]:
        side = "home" if facts["edge"] > 0 else "away"
        add(side, "[FIXTURE]", "slight", True, f"home edge: {facts['edge_reason']}")
    st_h, st_a = h["standing"] or {}, a["standing"] or {}
    if st_h.get("played") and st_a.get("played") and min(st_h["played"], st_a["played"]) >= 4:
        dppg = st_h["points"] / st_h["played"] - st_a["points"] / st_a["played"]
        side = "home" if dppg > 0 else "away"
        add(side, f"[{'H' if side == 'home' else 'A'}.table]", _strength(dppg, 0.3, 0.7, 1.2), True, f"league points per game: {st_h['points'] / st_h['played']:.2f} vs {st_a['points'] / st_a['played']:.2f}")
    if facts["h2h"] and (facts["h2h"].get("n") or 0) >= 4:
        hw, aw, n = facts["h2h"]["home_wins"] or 0, facts["h2h"]["away_wins"] or 0, facts["h2h"]["n"]
        side = "home" if hw > aw else "away"
        add(side, "[H2H]", _strength((hw - aw) / n, 0.25, 0.5, 0.75), False, f"head to head: home {hw}, draws {facts['h2h'].get('draws')}, away {aw} (n={n}); weak evidence once current strength is known")
    rh, ra = h["rest_days"], a["rest_days"]
    if rh is not None and ra is not None and rh != ra:
        side = "home" if rh > ra else "away"
        add(side, f"[{'H' if side == 'home' else 'A'}.fatigue]", "slight" if abs(rh - ra) <= 2 else "moderate", False, f"rest: {h['name']} {rh} days vs {a['name']} {ra} days")
    tr = facts.get("travel") or {}
    dist = (tr.get("away_travel_distance_km") or 0) - (tr.get("home_travel_distance_km") or 0)
    if abs(dist) >= 1500 and facts["edge"] == 1:
        add("home" if dist > 0 else "away", "[TRAVEL]", "slight", False, f"travel: away side travels {tr.get('away_travel_distance_km')} km, home {tr.get('home_travel_distance_km')} km")
    for side, s in (("home", h), ("away", a)):
        other = "away" if side == "home" else "home"
        tag = "H" if side == "home" else "A"
        modelled = [x for x in s["absentees"][:MAX_ABSENTEES] if x["in_squad_list"] and x["impact"] >= 0.03]
        if modelled:
            names = ", ".join(f"{x['name']} ({x['role']})" for x in modelled[:3])
            add(other, f"[{tag}.absent.{modelled[0]['name']}]", "moderate" if sum(x["impact"] for x in modelled) >= 0.1 else "slight", True,
                f"{s['name']} are without {names}: modelled in the non-odds sources, and already priced by the odds")
        unknown = [x for x in s["absentees"][:MAX_ABSENTEES] if not x["in_squad_list"]]
        if unknown:
            add(other, f"[{tag}.absent.{unknown[0]['name']}]", "slight", False, f"{s['name']} also miss {', '.join(x['name'] for x in unknown[:3])} (not in the squad list: unmodelled by the engine, impact unknown)")
        res = [r.get("result") for r in s["form"][:6]]
        run = next((i for i, x in enumerate(res) if x != "L"), len(res))
        if run >= 2 or (len(res) >= 4 and "W" not in res[:4]):
            what = f"lost the last {run} matches" if run >= 2 else "have not won in the last 4"
            pts.append(("both", {"tag": f"[{tag}.form]", "strength": "slight", "priced": True,
                                 "text": f"{s['name']} {what}: tested on 8,054 internationals, sides on losing form do NOT bounce back (-0.06 points/game vs the model, not significant): context only, never an upside"}))
        rot = s["rotation"] or {}
        if rot.get("changed_players") is not None and rot.get("starting_xi_size") and 5 <= rot["changed_players"] < rot["starting_xi_size"]:
            pts.append(("both", {"tag": f"[{tag}.rotation]", "strength": "slight", "priced": False, "text": f"{s['name']} changed {rot['changed_players']} of {rot['starting_xi_size']} starters last match (describes the previous match; direction for this one is ambiguous)"}))
        stakes = s["zone"] or {}
        if stakes.get("zone") in ("top-of-table", "relegation", "promotion"):
            pts.append(("both", {"tag": f"[{tag}.stakes]", "strength": "slight", "priced": False, "text": f"{s['name']} are {stakes['zone']} ({stakes.get('points_from_boundary')} pts from a boundary)"}))
    order = {"strong": 0, "moderate": 1, "slight": 2}
    out: dict[str, list[dict]] = {"home": [], "away": [], "both": []}
    for side, p in pts:
        out[side].append(p)
    for k in out:
        out[k].sort(key=lambda p: (order[p["strength"]], p["priced"]))
    return out


def challenge(facts: dict, eng: dict) -> dict | None:
    """Odds vs the models without the odds. None when there are no odds or no non-odds source."""
    odds = facts["odds"]
    non = [s for s in eng["sources"] if s["name"] != "market"]
    if not odds or not non:
        return None
    mh, ma, _ = quant.absence_multipliers(facts)
    lh, la, _ = quant.combine_rates(quant.apply_absences(non, mh, ma))
    model = quant.outcome_probs(lh, la)
    mk = (odds["home"], odds["draw"], odds["away"])
    gap = {k: round(100 * (m - o), 1) for k, m, o in zip(("home", "draw", "away"), model, mk)}
    largest = max(abs(v) for v in gap.values())
    lean_pts = 100 * ((model[0] - model[2]) - (mk[0] - mk[2]))
    lean = "home" if lean_pts > 4 else "away" if lean_pts < -4 else "none"
    market_lam = quant.market_rates(odds)           # rates implied by the odds (only used here, as a check on tempo)
    notes = []
    if market_lam:
        mt, tt = sum(market_lam), lh + la
        if abs(mt - tt) >= 0.5:
            notes.append(f"total goals: the odds imply {mt:.2f}, the models {tt:.2f}: {'the market expects a more open game' if mt > tt else 'the market expects a tighter game'}")
    if odds.get("overround_pct"):
        notes.append(f"bookmaker margin {odds['overround_pct'] - 100:.1f}% (already removed)")
    if not facts["lineup_confirmed"]:
        notes.append("lineups unconfirmed: the odds may still move on team news")
    stance = "challenge-strong" if largest >= 15 else "challenge-light" if largest >= 8 else "agree"
    return {"market": [round(100 * x, 1) for x in mk], "model_only": [round(100 * x, 1) for x in model], "gap_pp": gap, "largest_gap_pp": round(largest, 1),
            "models_lean": lean, "stance": stance, "notes": notes, "history": HISTORY_NOTE}


def check_advocates(adv: Any, valid_tags: set[str]) -> dict | None:
    """Keeps the advocates' text for the report and verifies every tag they cite exists in the brief."""
    if not isinstance(adv, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("home", "away", "odds_challenge"):
        text = str(adv.get(key) or "").strip()
        if not text:
            continue
        tags = TAG_RE.findall(text)
        out[key] = {"text": text[:900], "tags": tags, "unknown_tags": [t for t in tags if t not in valid_tags], "uncited": not tags}
    if not out:                       # no advocate text at all: nothing to show
        return None
    verdict = adv.get("verdict")
    out["verdict"] = verdict if verdict in VERDICTS else "unclear"
    return out


def _weak_point(p: dict) -> bool:
    return p["tag"] == "[H2H]" or "not in the squad list" in p["text"]


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "..."


def advocate_kit(d: dict, home: str, away: str) -> list[str]:
    """How each advocate builds a strong case from the dossier: lead with the two strongest points, rebut the opponent's best, concede the honest weak spot."""
    lines = ["**How to argue (each advocate, <= 90 words, every claim tagged)**"]
    for side, name, other, other_name in (("home", home, "away", away), ("away", away, "home", home)):
        mine, theirs = d[side], d[other]
        tag = "H" if side == "home" else "A"
        solid = [p for p in mine if not _weak_point(p)] or mine          # head-to-head and unknown-role absentees are thin evidence: lead with substance
        lead_tags = list(dict.fromkeys(p["tag"] for p in solid))[:2]
        if len(lead_tags) < 2:        # a thin side argues from the OPPONENT's weak spots (rotation, losing run, unknown absentees) and from the engine's own numbers
            opp_tag = "A" if side == "home" else "H"
            lead_tags += [p["tag"] for p in d["both"] if p["tag"].startswith(f"[{opp_tag}.")][:2 - len(lead_tags)]
        lead = ", ".join(lead_tags) or "no tagged points: say the case is thin and argue from the engine's likeliest scorelines for this side"
        best = next((p for p in theirs if not _weak_point(p)), theirs[0] if theirs else None)
        rebut = f"{best['tag']} ({_clip(best['text'], 70)})" if best else "no tagged point to rebut: say what the opponent lacks"
        weak = [p for p in d["both"] if p["tag"].startswith(f"[{tag}.")]
        concede = ", ".join(p["tag"] for p in weak[:2]) or "state the main unmodelled risk (unconfirmed lineups, unknown absentees)"
        lines.append(f"- {name}: LEAD with {lead}; SCENARIO: one sentence on how {name} gets the result; REBUT {other_name}'s best point: {rebut}; CONCEDE {concede}.")
    return lines


def format_dossier(d: dict, home: str, away: str) -> str:
    def block(title: str, pts: list[dict]) -> list[str]:
        lines = [f"**{title}**"]
        lines += [f"- {p['tag']} ({p['strength']}, {'already priced' if p['priced'] else 'NOT priced'}): {p['text']}" for p in pts] or ["- nothing notable in the data"]
        return lines
    return "\n".join(block(f"Evidence for {home} (home)", d["home"]) + [""] + block(f"Evidence for {away} (away)", d["away"]) + [""] + block("Context that cuts both ways", d["both"]) + [""] + advocate_kit(d, home, away))


def format_challenge(ch: dict | None) -> str:
    if not ch:
        return "No odds challenge possible (no odds, or no non-odds source)."
    g = ch["gap_pp"]
    lines = [f"- Odds (de-vigged) {ch['market'][0]}/{ch['market'][1]}/{ch['market'][2]} vs models without the odds {ch['model_only'][0]}/{ch['model_only'][1]}/{ch['model_only'][2]}: "
             f"gap home {g['home']:+.1f}, draw {g['draw']:+.1f}, away {g['away']:+.1f} points -> **{ch['stance']}**"
             + (f"; the models lean to the {ch['models_lean']} side more than the odds" if ch["models_lean"] != "none" else "; no side leaning")]
    lines += [f"- {n}" for n in ch["notes"]]
    return "\n".join(lines)
