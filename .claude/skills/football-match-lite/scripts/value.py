#!/usr/bin/env python3
"""After the analysis: the final pick, the stake and a market scoreboard (Python standard library only).

    python3 value.py answer.md original_report.json [value.md]

INDEPENDENT block (our numbers only, no market): the final pick (the answer's Best bet, or "Draw or <underdog>" when the upset rule fires on our own
underdog at UPSET_MIN%+), the goals bet, the independent data model (rating anchor through calc.py) and the stake (a flat 1 unit on the final pick).
MARKET SCOREBOARD (reference only, printed last): the market's fair 1X2 and our final pick and goals bet against it. Nothing in the scoreboard changes a
pick or a stake, and nothing this script prints goes back into the answer. The JSON line keeps the pick's market label (REAL, THIN, NONE, UNMEASURED)
for score.py's scoreboard."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPSET_MIN = 22.0         # upset rule: our underdog at this % or more, and at or above the market's fair price, switches the final pick to "Draw or <underdog>"


def _check():
    spec = importlib.util.spec_from_file_location("check_for_value", HERE / "check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def value(answer: str, report: dict) -> dict:
    ck = _check()
    m = report.get("match") if isinstance(report.get("match"), dict) else {}
    home, away = str(m.get("home_team") or "Home"), str(m.get("away_team") or "Away")
    lines = [ln for ln in answer.splitlines() if re.match(r"[*#\s|]*best bet", ln, re.I) and re.search(r"\d\s*%", ln)]
    if not lines:
        return {"label": "UNMEASURED", "why": "no Best bet line with a probability"}
    line = re.sub(r"^[*#\s|]*best bet:?[*\s]*", "", lines[0], flags=re.I)
    bm = re.search(r"^\**\s*(.+?)\s*\(\s*(\d+(?:\.\d+)?)\s*%(?:[,;][^)]*)?\)", line)
    if not bm:
        return {"label": "UNMEASURED", "why": "cannot read the bet and its probability"}
    bet, own = re.sub(r"\s*\([^)]*\)", "", bm.group(1)).strip(" *:-"), float(bm.group(2))
    bk, ov = ck.bookmaker(report), ck.over25_fair(report)
    if not bk:
        return {"bet": bet, "own": own, "label": "UNMEASURED", "why": "the report has no 1X2 odds"}
    a_m = {"home": bk[0] / 100, "draw": bk[1] / 100, "away": bk[2] / 100, "over_2_5": ov if ov is not None else 0.0, "btts": 0.0}   # goals/BTTS are read only when priced (below)
    nb = ck.norm(bet)
    goals = "over25" in nb or "under25" in nb
    if "bothteams" in nb or (goals and ov is None):
        return {"bet": bet, "own": own, "label": "UNMEASURED", "why": "no market price for this bet"}
    mk = ck.bet_probability(bet, home, away, a_m)
    if mk is None:
        return {"bet": bet, "own": own, "label": "UNMEASURED", "why": "no market price for this bet"}
    edge = own - mk
    need = 7.0 if mk >= 70 else 5.0
    label = ck.value_label(edge, need)
    out = {"bet": bet, "own": own, "market": round(mk, 1), "edge": round(edge, 1), "label": label, "bar": need, "home": home, "away": away}
    if edge < 0 and re.search(r"\bor\b|\b(?:1x|x2|12)\b|double chance", bet, re.I):
        out["weak_cover"] = True                              # a cover the market prices safer than you do: a short price with negative value
    other = _larger_gap(answer, bk, home, away, edge, ck)
    if other:
        out["elsewhere"] = other
    g = _goals(answer, ov, ck, home, away)
    if g:
        out["goals"] = g
    return out


def _goals(answer: str, ov, ck, home: str, away: str) -> dict | None:
    """The answer's separate 'Goals bet' against the market's fair over/under 2.5 price (both teams to score has no price in the reports: UNMEASURED).
    Never staked: on the 28 scored matches of Oct 2026, betting the biggest goals-market edge lost at every bar (-4.70 units at edge 0+, -5.77 at 5+) and our
    over 2.5 scored Brier 0.233 v the market's 0.212."""
    gm = re.search(r"^[*#\s|]*goals bet:?[*\s]*(.+?)\s*\(\s*(\d+(?:\.\d+)?)\s*%", answer, re.I | re.M)
    if not gm:
        return None
    bet, own = gm.group(1).strip(" *:-"), float(gm.group(2))
    nb = ck.norm(bet)
    if ("over25" not in nb and "under25" not in nb) or ov is None:
        return {"bet": bet, "own": own, "label": "UNMEASURED", "why": "no market price for this goals bet"}
    mk = 100 * (ov if "over25" in nb else 1 - ov)
    need = 7.0 if mk >= 70 else 5.0
    return {"bet": bet, "own": own, "market": round(mk, 1), "edge": round(own - mk, 1), "label": ck.value_label(own - mk, need), "bar": need}


def _upset(answer: str, home: str, away: str) -> dict | None:
    """The upset rule, from our own numbers only (market-independent since 2026-10-25): when our underdog (the side we rate lower) is at UPSET_MIN% or more,
    the final pick is "Draw or <underdog>". On the 28 scored matches this blind version made 22 picks right and +5.85 units at fair prices, against 23 and
    +5.69 for the plain pick (the earlier market-gated version was worse in leave-one-out); score.py judges it on new matches."""
    head = next((ln for ln in answer.splitlines() if re.search(r"\d\s*%\s*/", ln)), "")
    parts = re.findall(r"([^/%*]+?)\s+(\d+(?:\.\d+)?)\s*%", head)
    if len(parts) != 3:
        return None
    ph, pd, pa = (float(p) for _, p in parts)
    dog, dp = (home, ph) if ph < pa else (away, pa)
    if dp < UPSET_MIN:
        return None
    return {"bet": f"Draw or {dog}", "dog": dog, "dog_own": dp, "own": round(pd + dp, 1)}


def independent(answer: str, report: dict) -> dict:
    """Everything the decision needs, from our own numbers only: the answer's pick, the upset rule, the final pick, the goals bet and the stake.
    The stake is a flat 1 unit on the final pick: on the 28 scored matches no rule on our own probabilities beat staking every pick (60%+ only: +5.20,
    65%+: +3.36, 70%+: +2.81 units v +5.69 for all)."""
    m = report.get("match") if isinstance(report.get("match"), dict) else {}
    home, away = str(m.get("home_team") or "Home"), str(m.get("away_team") or "Away")
    out: dict = {}
    lines = [ln for ln in answer.splitlines() if re.match(r"[*#\s|]*best bet", ln, re.I) and re.search(r"\d\s*%", ln)]
    bm = re.search(r"^\**\s*(.+?)\s*\(\s*(\d+(?:\.\d+)?)\s*%(?:[,;][^)]*)?\)", re.sub(r"^[*#\s|]*best bet:?[*\s]*", "", lines[0], flags=re.I)) if lines else None
    if bm:
        out["pick"], out["pick_own"] = re.sub(r"\s*\([^)]*\)", "", bm.group(1)).strip(" *:-"), float(bm.group(2))
    gm = re.search(r"^[*#\s|]*goals bet:?[*\s]*(.+?)\s*\(\s*(\d+(?:\.\d+)?)\s*%", answer, re.I | re.M)
    if gm:
        out["goals_bet"], out["goals_own"] = gm.group(1).strip(" *:-"), float(gm.group(2))
    up = _upset(answer, home, away)
    if up and not (bm and _backs(out["pick"], up["dog"], home, away)):
        out["upset"] = up
    if "upset" in out:
        out["final_pick"], out["final_own"] = out["upset"]["bet"], out["upset"]["own"]
    elif bm:
        out["final_pick"], out["final_own"] = out["pick"], out["pick_own"]
    out["stake"], out["stake_why"] = ("BET", f"a flat 1 unit on the final pick, {out['final_pick']} (our own numbers only)") if "final_pick" in out else ("PASS", "no Best bet line")
    return out


def decide(v: dict) -> tuple[str, str]:
    """The stake, from our own numbers only (see independent())."""
    return v.get("stake", "PASS"), v.get("stake_why", "no Best bet line")


def _backs(bet: str, outcome: str, home: str, away: str) -> bool:
    """Does the bet include the outcome (a team to win, the draw, or a double chance that contains it)?"""
    nb = _check().norm(bet)
    if outcome == "Draw":
        return "draw" in nb or "x" in nb.split("or")
    return _check().norm(outcome) in nb


def _larger_gap(answer: str, bk: list[float], home: str, away: str, pick_edge: float, ck) -> dict | None:
    """The 1X2 outcome (from the answer's headline probabilities) whose edge over the market's fair price is larger than the pick's, or None."""
    head = next((ln for ln in answer.splitlines() if re.search(r"\d\s*%\s*/", ln)), "")
    parts = re.findall(r"([^/%*]+?)\s+(\d+(?:\.\d+)?)\s*%", head)
    if len(parts) != 3:
        return None
    best = None
    for (name, p), m, label in zip(parts, bk, (home, "Draw", away)):
        e = float(p) - m
        if e > pick_edge + 0.05 and e > 0 and (best is None or e > best["edge"]):
            need = 7.0 if m >= 70 else 5.0
            best = {"outcome": label, "own": float(p), "market": round(m, 1), "edge": round(e, 1), "label": ck.value_label(e, need), "bar": need}
    return best


def model_view(report: dict) -> dict | None:
    """The market-independent DATA MODEL: the rating anchor (ClubElo or national Elo, the league's goal level and the venue edge) through calc.py, with no analyst
    and no odds. On the 28 scored matches of Oct 2026 it scored Brier 0.442 against the finished answers' 0.466 and the market's 0.475, so it is printed beside
    every answer and compared with the market only here, after the run."""
    ck = _check()
    facts, calc = ck.facts, ck.calc
    facts.set_venue(report)
    ins = report.get("insights") if isinstance(report.get("insights"), dict) else {}
    ra = facts.rating_anchor(ins, report.get("match"))
    if not ra:
        return None
    a = calc.analyse(ra[0], ra[1])
    mm = report.get("match") if isinstance(report.get("match"), dict) else {}
    rec = calc.recommend(a, str(mm.get("home_team") or "Home"), str(mm.get("away_team") or "Away"))
    return {"lam_home": round(ra[0], 2), "lam_away": round(ra[1], 2), "source": ra[4], "home": round(100 * a["home"], 1), "draw": round(100 * a["draw"], 1),
            "away": round(100 * a["away"], 1), "over_2_5": round(100 * a["over_2_5"], 1), "btts": round(100 * a["btts"], 1), "score": a["top_scores"][0][0],
            "pick": rec["selection"], "pick_pct": rec["pct"], "goals_bet": rec["goals_bet"], "goals_pct": rec["goals_pct"]}


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 4):
        print(__doc__)
        return 2
    answer = Path(argv[1]).read_text(encoding="utf-8")
    report = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    ck = _check()
    ind = independent(answer, report)
    mm = report.get("match") if isinstance(report.get("match"), dict) else {}
    h, w = str(mm.get("home_team") or "Home"), str(mm.get("away_team") or "Away")
    text = "INDEPENDENT (our numbers only; no market used)"
    if "final_pick" in ind:
        text += f"\nFinal pick: {ind['final_pick']} ({ind['final_own']:.1f}%)" + (f", from the upset rule instead of {ind['pick']}" if "upset" in ind else "")
    if "upset" in ind:
        u = ind["upset"]
        text += f"\nUpset rule: our underdog {u['dog']} is {u['dog_own']:.1f}% ({UPSET_MIN:.0f}%+), so the final pick is {u['bet']} ({u['own']:.1f}%); unproven, judged by score.py."
    if "goals_bet" in ind:
        text += f"\nGoals bet: {ind['goals_bet']} ({ind['goals_own']:.1f}%), a forecast, not staked."
    mv = model_view(report)
    if mv:
        text += (f"\nIndependent data model (ratings and venue only, {mv['source']}; no analyst, no odds): {h} {mv['home']:.1f}% / Draw {mv['draw']:.1f}% / {w} {mv['away']:.1f}%, "
                 f"expected goals {mv['lam_home']:.2f}-{mv['lam_away']:.2f}, likeliest score {mv['score']}, over 2.5 {mv['over_2_5']:.1f}%, both score {mv['btts']:.1f}%; its pick {mv['pick']} {mv['pick_pct']:.1f}%, "
                 f"goals bet {mv['goals_bet']} {mv['goals_pct']:.1f}%.")
    text += f"\nStake decision: {ind['stake']} - {ind['stake_why']}."
    v = value(answer, report)
    bk, ov = ck.bookmaker(report), ck.over25_fair(report)
    text += "\n\nMARKET SCOREBOARD (reference only, after the run: nothing here changes a pick or a stake)"
    if not bk:
        text += "\nno market prices in the report"
    else:
        a_m = {"home": bk[0] / 100, "draw": bk[1] / 100, "away": bk[2] / 100, "over_2_5": ov if ov is not None else 0.0, "btts": 0.0}
        text += f"\nThe market's fair 1X2: {h} {bk[0]:.1f} / Draw {bk[1]:.1f} / {w} {bk[2]:.1f}."
        for label, bet, own in (("final pick", ind.get("final_pick"), ind.get("final_own")), ("goals bet", ind.get("goals_bet"), ind.get("goals_own"))):
            nb = ck.norm(bet or "")
            mk = None if not bet or "bothteams" in nb or (("over25" in nb or "under25" in nb) and ov is None) else ck.bet_probability(bet, h, w, a_m)
            if mk is not None:
                text += f"\n{label}: {bet} ours {own:.1f}% v the market's {mk:.1f}% ({own - mk:+.1f} points)."
            elif bet:
                text += f"\n{label}: {bet} - no market price."
    v.update(ind)
    if mv:
        v["model"] = mv
    print(text)
    if len(argv) == 4:
        Path(argv[3]).write_text(text + "\n" + json.dumps(v) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
