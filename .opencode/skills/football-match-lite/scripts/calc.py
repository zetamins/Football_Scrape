#!/usr/bin/env python3
"""The one calculator of the football-match-lite skill (Python standard library only, no data files, no network).

It holds no knowledge about any team and takes no decisions. It does four things with the numbers YOU give it:
  1. combines expected-goals estimates (weighted geometric mean), if you give several,
  2. turns your FINAL expected goals into one coherent set of probabilities for every market (Poisson with the Dixon-Coles low-score correction, exact),
  3. prints your own fair odds next to the bookmaker odds you pass in, and a rule-of-thumb bet suggestion (you may choose differently),
  4. appends your forecast to a log file so that scripts/score.py can later measure your judgement against the results and the bookmakers.

    python3 calc.py --lam 1.45 1.10 --home Cyprus --away Latvia --odds 54.3 26.9 18.8
    python3 calc.py --src xg 1.45 1.10 1.5 --src results 1.60 1.20 1.0       # combine anchors first
    python3 calc.py --lam 1.45 1.10 --home Cyprus --away Latvia --odds 54 27 19
    (--log FILE exists for the maintainer's own experiments; the skill never saves its predictions)
    add --json for machine-readable output.
"""

from __future__ import annotations

import argparse
import json
import math
import sys

MAX_GOALS = 10
DC_RHO = -0.05               # Dixon & Coles low-score dependence
TOTAL_SHRINK = 0.2           # goal markets only: the total is pulled 20% of the way to the mean total
MEAN_TOTAL_GOALS = 2.676
GOALS_BET_MIN_PCT = 0.0      # no bar: over/under 2.5 or both teams to score is the pick whenever it beats the best 1X2 or double-chance pick (user's rule, 2026-10-25). On the 28 scored matches of Oct 2026: 23 right and +5.93 units at fair prices v 23 and +5.69 with the old 60% bar (2 goals picks); the oracle engine keeps its own 60%
DOUBLE_CHANCE_BELOW_PCT = 45.0   # the best double chance is suggested only when no single outcome reaches this (an open game): double chances are the exception, not the default
DOUBLE_CHANCE_DRAWISH_BELOW_PCT, DOUBLE_CHANCE_DRAWISH_MIN_PCT = 50.0, 24.0   # ...or when the top outcome is under 50% and the draw is 24%+ (a level finish is then a real way to lose the single bet)
ALERT_PCT, WATCH_PCT = 29.0, 27.0
TOSS_UP_GAP_PCT, TOSS_UP_MIN_DRAW_PCT = 5.0, 28.0


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def poisson(k: int, rate: float) -> float:
    return math.exp(-rate) * rate**k / math.factorial(k)


def tau(i: int, j: int, lam: float, mu: float, rho: float) -> float:
    if i == 0 and j == 0:
        return 1 - lam * mu * rho
    if i == 0 and j == 1:
        return 1 + lam * rho
    if i == 1 and j == 0:
        return 1 + mu * rho
    if i == 1 and j == 1:
        return 1 - rho
    return 1.0


def grid(lam_h: float, lam_a: float) -> dict[tuple[int, int], float]:
    lam_h, lam_a = clamp(lam_h, 0.05, 6.0), clamp(lam_a, 0.05, 6.0)
    g = {(i, j): max(0.0, poisson(i, lam_h) * poisson(j, lam_a) * tau(i, j, lam_h, lam_a, DC_RHO)) for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1)}
    total = sum(g.values())
    return {k: v / total for k, v in g.items()}


def combine(sources: list[tuple[str, float, float, float]]) -> tuple[float, float]:
    """Weighted geometric mean of (name, lam_home, lam_away, weight)."""
    tw = sum(w for _, _, _, w in sources)
    return (math.exp(sum(w * math.log(h) for _, h, _, w in sources) / tw), math.exp(sum(w * math.log(a) for _, _, a, w in sources) / tw))


def shrink_total(lam_h: float, lam_a: float) -> tuple[float, float]:
    t = lam_h + lam_a
    f = (t + TOTAL_SHRINK * (MEAN_TOTAL_GOALS - t)) / t
    return lam_h * f, lam_a * f


def analyse(lam_h: float, lam_a: float) -> dict:
    g = grid(lam_h, lam_a)
    home = sum(p for (i, j), p in g.items() if i > j)
    draw = sum(p for (i, j), p in g.items() if i == j)
    away = sum(p for (i, j), p in g.items() if i < j)
    sh, sa = shrink_total(clamp(lam_h, 0.05, 6.0), clamp(lam_a, 0.05, 6.0))
    gg = grid(sh, sa)                                         # goal markets use the shrunk total
    over = sum(p for (i, j), p in gg.items() if i + j > 2)
    btts = sum(p for (i, j), p in gg.items() if i > 0 and j > 0)
    top = sorted(g.items(), key=lambda kv: -kv[1])[:4]
    return {"lam_home": round(lam_h, 3), "lam_away": round(lam_a, 3), "home": home, "draw": draw, "away": away, "over_2_5": over, "btts": btts,
            "top_scores": [(f"{i}-{j}", p) for (i, j), p in top], "draw_scores": {f"{k}-{k}": g.get((k, k), 0.0) for k in range(4)}}


def underdog_first(lam_h: float, lam_a: float, steps: int = 400) -> dict:
    """The route 'the underdog scores first' under independent goals spread evenly over the match: the chance it happens and, if it does, how the match ends.
    The first goal comes at time t (0..1) with density L e^(-L t), L = both rates; after it each side scores Poisson(rate x (1 - t)) more. The favourite
    is the side with the higher rate. Draws in the model are only as common as the rates allow; the sheet's record after conceding is the team's real version."""
    lam_h, lam_a = clamp(lam_h, 0.05, 6.0), clamp(lam_a, 0.05, 6.0)
    fav_home = lam_h >= lam_a
    lf, lu = (lam_h, lam_a) if fav_home else (lam_a, lam_h)
    tot = lf + lu
    win = draw = loss = 0.0                                   # the favourite's result, given the underdog scored first
    for s in range(steps):
        t = (s + 0.5) / steps
        w = tot * math.exp(-tot * t) / steps                  # the first goal falls in this slice
        rf, ru = lf * (1 - t), lu * (1 - t)
        pf = [poisson(k, rf) for k in range(MAX_GOALS + 1)]
        pu = [poisson(k, ru) for k in range(MAX_GOALS + 1)]
        for i, a in enumerate(pf):
            for j, b in enumerate(pu):
                d = i - j - 1                                 # favourite's margin at full time, from 0-1 down
                if d > 0:
                    win += w * a * b
                elif d == 0:
                    draw += w * a * b
                else:
                    loss += w * a * b
    first = (lu / tot) * (1 - math.exp(-tot))
    cond = win + draw + loss
    return {"favourite": "home" if fav_home else "away", "underdog_first": first,
            "fav_win": win / cond, "draw": draw / cond, "fav_loss": loss / cond}


def flags(a: dict) -> dict:
    home, draw, away = 100 * a["home"], 100 * a["draw"], 100 * a["away"]
    level = "ALERT" if draw >= ALERT_PCT else "WATCH" if draw >= WATCH_PCT else "none"
    notes = []
    if abs(home - away) < TOSS_UP_GAP_PCT and draw >= TOSS_UP_MIN_DRAW_PCT:
        notes.append("toss-up: the sides are level and a draw is about as likely as either win")
    if a["lam_home"] + a["lam_away"] < 2.2:
        notes.append("low-scoring game expected: more 0-0 and 1-1")
    if max(home, away) >= 70:
        notes.append("heavy favourite: draws are rare, the usual way the favourite fails to win is a 0-0 or 1-1")
    return {"draw_level": level, "notes": notes}


def recommend(a: dict, home_name: str = "Home", away_name: str = "Away") -> dict:
    final = [a["home"], a["draw"], a["away"]]
    one = max(range(3), key=lambda k: final[k])
    names = {0: f"{home_name} to win", 1: "Draw", 2: f"{away_name} to win"}
    top = ("1X2", names[one], final[one])
    goals = [("Over/Under 2.5", "Over 2.5 goals", a["over_2_5"]), ("Over/Under 2.5", "Under 2.5 goals", 1 - a["over_2_5"]),
             ("BTTS", "Both teams to score: Yes", a["btts"]), ("BTTS", "Both teams to score: No", 1 - a["btts"])]
    dcs = [("Double chance", f"{home_name} or draw", final[0] + final[1]), ("Double chance", f"draw or {away_name}", final[1] + final[2]),
           ]                                                   # 'either side to win' is never suggested: it loses on the draw
    best_dc = max(dcs, key=lambda c: c[2])
    eligible = [top] + [g for g in goals if 100 * g[2] >= GOALS_BET_MIN_PCT] + ([best_dc] if 100 * top[2] < DOUBLE_CHANCE_BELOW_PCT or (100 * top[2] < DOUBLE_CHANCE_DRAWISH_BELOW_PCT and 100 * a["draw"] >= DOUBLE_CHANCE_DRAWISH_MIN_PCT) else [])
    market, selection, p = max(eligible, key=lambda c: c[2])
    p1x2 = max((c for c in eligible if c[0] in ("1X2", "Double chance")), key=lambda c: c[2])
    pct = 100 * p
    strength = "very strong" if pct >= 80 else "strong" if pct >= 70 else "moderate" if pct >= 60 else "lean"
    skipped = [{"selection": s, "pct": round(100 * q, 1)} for _, s, q in sorted(goals, key=lambda c: -c[2]) if 100 * q < GOALS_BET_MIN_PCT and q > top[2]][:1]
    gsel, gp = goals_bet(a)
    return {"market": market, "selection": selection, "pct": round(pct, 1), "strength": strength, "single_outcome": names[one], "single_pct": round(100 * final[one], 1),
            "not_recommended": skipped, "goals_bet": gsel, "goals_pct": gp, "pick_1x2": p1x2[1], "pick_1x2_pct": round(100 * p1x2[2], 1)}


def goals_bet(a: dict) -> tuple[str, float]:
    """The likeliest of the four goals selections (over or under 2.5, both teams to score yes or no): the answer's separate 'Goals bet', given every match.
    On the 28 scored matches of Oct 2026 this pick won 16 (57%) at an average 58%; our over 2.5 scored Brier 0.233 v the market's 0.212 and rated goals
    high (56% predicted over 2.5 v 46% seen), so it is a forecast, not an edge, until score.py says otherwise."""
    four = [("Over 2.5 goals", a["over_2_5"]), ("Under 2.5 goals", 1 - a["over_2_5"]), ("Both teams to score: Yes", a["btts"]), ("Both teams to score: No", 1 - a["btts"])]
    sel, p = max(four, key=lambda c: c[1])
    return sel, round(100 * p, 1)


FLB_A, FLB_B = 0.0508, 1.0777        # favourite-longshot correction: logit(p') = A + B x logit(p), fitted on 21,502 matches (2019-22), tested on 17,793 (2022-25)


def flb_adjust(probs: list[float]) -> list[float]:
    """The market's fair 1X2 probabilities with the favourite-longshot bias removed (heavy favourites are under-priced, longshots over-priced). A reference only: the gain out of sample is tiny."""
    t = sum(probs)
    if t <= 0:
        return list(probs)
    q = []
    for x in probs:
        x = min(max(x / t, 1e-4), 1 - 1e-4)
        q.append(1 / (1 + math.exp(-(FLB_A + FLB_B * math.log(x / (1 - x))))))
    s = sum(q)
    return [v / s for v in q]


def implied_lams(p_home: float, p_draw: float, p_away: float, over25: float | None = None) -> tuple[float, float, float]:
    """The expected goals (lam_home, lam_away) whose 1X2 probabilities best reproduce a market's fair prices (and its over 2.5 when given). Returns (lam_home, lam_away, worst error in points).
    A coarse grid, then two refinements: no libraries, the same grid model as analyse()."""
    t = sum((p_home, p_draw, p_away))
    tgt = (p_home / t, p_draw / t, p_away / t)

    def loss(lh: float, la: float) -> float:
        a = analyse(lh, la)
        e = (a["home"] - tgt[0]) ** 2 + (a["draw"] - tgt[1]) ** 2 + (a["away"] - tgt[2]) ** 2
        if over25 is not None:
            e += (a["over_2_5"] - over25) ** 2
        return e
    best = (9.0, 0.3, 0.3)
    for i in range(3, 36):
        for j in range(3, 36):
            e = loss(i / 10, j / 10)
            if e < best[0]:
                best = (e, i / 10, j / 10)
    for step in (0.02, 0.005):
        e0, lh, la = best
        for i in range(-10, 11):
            for j in range(-10, 11):
                h, a_ = lh + i * step, la + j * step
                if 0.2 <= h <= 4 and 0.2 <= a_ <= 4:
                    e = loss(h, a_)
                    if e < best[0]:
                        best = (e, h, a_)
    a = analyse(best[1], best[2])
    err = max(abs(a["home"] - tgt[0]), abs(a["draw"] - tgt[1]), abs(a["away"] - tgt[2]))
    return round(best[1], 2), round(best[2], 2), round(100 * err, 1)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", nargs=4, action="append", metavar=("NAME", "LAM_HOME", "LAM_AWAY", "WEIGHT"), help="one expected-goals estimate and its weight")
    ap.add_argument("--lam", nargs=2, type=float, metavar=("LAM_HOME", "LAM_AWAY"), help="a final expected-goals pair (skips combining)")
    ap.add_argument("--home", default="Home")
    ap.add_argument("--away", default="Away")
    ap.add_argument("--odds", nargs=3, type=float, metavar=("HOME_PCT", "DRAW_PCT", "AWAY_PCT"), help="the bookmaker's fair percentages from the report, for comparison only")
    ap.add_argument("--log", metavar="FILE", help="MAINTAINER ONLY: append this forecast to a JSON-lines file (the skill itself never saves predictions)")
    ap.add_argument("--match", default="", help="match name for the log")
    ap.add_argument("--kickoff", default="", help="kickoff date (YYYY-MM-DD) for the log")
    ap.add_argument("--bet", default="", help="the bet YOU chose, for the log (default: the suggestion)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.src:
            sources = [(n, float(h), float(a), float(w)) for n, h, a, w in args.src]
            if any(h <= 0 or a <= 0 or w <= 0 for _, h, a, w in sources):
                raise ValueError("every estimate and weight must be positive")
            lam_h, lam_a = combine(sources)
        elif args.lam:
            lam_h, lam_a = args.lam
            if lam_h <= 0 or lam_a <= 0:
                raise ValueError("expected goals must be positive")
        else:
            ap.error("give --src (one or more) or --lam")
            return 2
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    a = analyse(lam_h, lam_a)
    fl, rec = flags(a), recommend(a, args.home, args.away)
    if args.log:
        write_log(args, a, rec)
    if args.json:
        print(json.dumps({"analysis": a, "flags": fl, "recommendation": rec}, indent=1))
        return 0
    pct = lambda x: f"{100 * x:.1f}"
    print(f"Expected goals (final): {a['lam_home']} - {a['lam_away']}")
    print(f"Home {pct(a['home'])}% / Draw {pct(a['draw'])}% / Away {pct(a['away'])}%")
    print(f"Double chance: home or draw {pct(a['home'] + a['draw'])}% / draw or away {pct(a['draw'] + a['away'])}% / either side to win {pct(a['home'] + a['away'])}%")
    print(f"Over 2.5 goals {pct(a['over_2_5'])}% / Under 2.5 {pct(1 - a['over_2_5'])}%; both teams to score {pct(a['btts'])}%")
    print(f"Goals markets (own fair odds): over 2.5 {pct(a['over_2_5'])}% ({1 / max(a['over_2_5'], 1e-9):.2f}), under 2.5 {pct(1 - a['over_2_5'])}% ({1 / max(1 - a['over_2_5'], 1e-9):.2f}), "
          f"both score yes {pct(a['btts'])}% ({1 / max(a['btts'], 1e-9):.2f}), no {pct(1 - a['btts'])}% ({1 / max(1 - a['btts'], 1e-9):.2f}); goals bet: {rec['goals_bet']} {rec['goals_pct']}%")
    print("Likeliest scores: " + ", ".join(f"{s} ({pct(p)}%)" for s, p in a["top_scores"]))
    print("Drawn scores: " + ", ".join(f"{s} {pct(p)}%" for s, p in a["draw_scores"].items()))
    print(f"Draw flag: {fl['draw_level']}" + ("; " + "; ".join(fl["notes"]) if fl["notes"] else ""))
    uf = underdog_first(lam_h, lam_a)
    fav, und = (args.home, args.away) if uf["favourite"] == "home" else (args.away, args.home)
    print(f"If the underdog scores first: {und} scores first in {pct(uf['underdog_first'])}% of matches; then {fav} still wins {pct(uf['fav_win'])}%, draw {pct(uf['draw'])}%, {und} wins {pct(uf['fav_loss'])}% "
          f"(independent-goals model; set it against the sheet's IF THE UNDERDOG SCORES record, the team's real version)")
    own =[("home", a["home"]), ("draw", a["draw"]), ("away", a["away"])]
    print("Your own fair odds (decimal): " + ", ".join(f"{n} {1 / p:.2f}" for n, p in own))
    if args.odds:
        t = sum(args.odds)
        bk = [x / t for x in args.odds]
        print("Bookmaker fair odds (decimal): " + ", ".join(f"{n} {100 / x:.2f}" for (n, _), x in zip(own, args.odds)) + "; your probability minus theirs (points): "
              + ", ".join(f"{n} {100 * (p - b):+.1f}" for (n, p), b in zip(own, bk)))
    print(f"Rule-of-thumb suggestion (you decide; choose another bet if you can justify it): {rec['selection']} - {rec['pct']}% ({rec['market']}); strength {rec['strength']}; best single outcome: {rec['single_outcome']} {rec['single_pct']}%"
          + (f"; not recommended: {rec['not_recommended'][0]['selection']} {rec['not_recommended'][0]['pct']}% (goals bets need {GOALS_BET_MIN_PCT:.0f}%)" if rec["not_recommended"] else ""))
    return 0


def write_log(args, a: dict, rec: dict) -> None:
    import datetime
    entry = {"logged_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "match": args.match or f"{args.home} v {args.away}", "home": args.home, "away": args.away, "kickoff": args.kickoff,
             "lam_home": a["lam_home"], "lam_away": a["lam_away"], "p": [round(a["home"], 4), round(a["draw"], 4), round(a["away"], 4)], "over_2_5": round(a["over_2_5"], 4), "btts": round(a["btts"], 4),
             "bet": args.bet or rec["selection"], "suggested": rec["selection"], "odds_fair_pct": list(args.odds) if args.odds else None}
    with open(args.log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
