#!/usr/bin/env python3
"""Scores the forecasts you logged with calc.py --log against real results (Python standard library only).

    python3 score.py forecasts.jsonl results.csv
    python3 score.py --answers DIR [DIR ...] results.csv     (each DIR holds answer.md and report.json: nothing is saved by the skill, the forecast is read from the finished answer)
results.csv columns: date,home_team,away_team,home_score,away_score   (the date is the match day; a one-day difference is tolerated)
             optional: home_xg,away_xg (the match's own expected goals after full time): scores how well the forecast read the match, which is far less noisy than the result

It reports, per match, your 1X2 probabilities, the result, whether your bet hit, and how you did against the bookmaker's fair odds when you logged them
(Brier score: lower is better; guessing equal chances scores 0.667). Small samples are noise: only judge the analyst after dozens of matches.
"""

from __future__ import annotations

import csv
import datetime
import json
import sys
import unicodedata


def norm(s) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(c))
    return "".join(c for c in s.lower() if c.isalnum())


def hit(bet: str, home: str, away: str, hg: int, ag: int) -> bool | None:
    """Whether a bet won. Understands 1X2, double chance, over/under 2.5 and both-teams-to-score; None when the text is not recognised."""
    b, h, a = norm(bet), norm(home), norm(away)
    res = "h" if hg > ag else "d" if hg == ag else "a"
    both = hg > 0 and ag > 0
    if "over25" in b:
        return hg + ag > 2
    if "under25" in b:
        return hg + ag <= 2
    if "bothteamstoscore" in b or b.startswith("btts"):
        return (not both) if b.endswith("no") else both
    if "eithersidetowin" in b or "homeoraway" in b or "noDraw".lower() in b and "win" in b:
        return res != "d"
    if b == f"{h}ordraw" or b == f"drawor{h}" or b in ("homeordraw", "draworhome", "1x"):
        return res in ("h", "d")
    if b == f"drawor{a}" or b == f"{a}ordraw" or b in ("draworaway", "awayordraw", "x2"):
        return res in ("d", "a")
    if b == "draw":
        return res == "d"
    if b in (f"{h}towin", f"{h}win", h, "homewin"):
        return res == "h"
    if b in (f"{a}towin", f"{a}win", a, "awaywin"):
        return res == "a"
    return None


def entries_from_answers(dirs: list[str]) -> list[dict]:
    """Read finished answers instead of a saved log: headline probabilities, the Best bet line and the bookmaker figures in the report."""
    import re
    from pathlib import Path
    out = []
    for d in dirs:
        try:
            ans = Path(d, "answer.md").read_text(encoding="utf-8")
            rep = json.loads(Path(d, "report.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(rep, dict):
            continue                                                   # a corrupt report.json (a list, a number): skip that run instead of crashing
        m = rep.get("match") if isinstance(rep.get("match"), dict) else {}
        head = re.search(r"(\d+(?:\.\d+)?)%\s*/\s*Draw\s*(\d+(?:\.\d+)?)%\s*/\s*[^\n]*?(\d+(?:\.\d+)?)%", ans)
        bl = [ln for ln in ans.splitlines() if re.match(r"[*#\s|]*best bet", ln, re.I) and re.search(r"\d\s*%", ln)]
        bm = re.search(r"^\**\s*(.+?)\s*\(\s*\d+(?:\.\d+)?\s*%(?:[,;][^)]*)?\)", re.sub(r"^[*#\s|]*best bet:?[*\s]*", "", bl[0], flags=re.I)) if bl else None
        if not (head and m.get("home_team") and m.get("away_team")):
            continue
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("check_for_score", Path(__file__).with_name("check.py"))
            chk = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(chk)
            fair = chk.bookmaker(rep)
            side = Path(str(d).rstrip("/") + ".odds.json")             # the runner blinds report.json and keeps the original (with odds) beside the run folder
            if not fair and side.exists():
                fair = chk.bookmaker(json.loads(side.read_text(encoding="utf-8")))
        except Exception:
            fair = None
        anchor = None
        try:
            ev = Path(d, "evidence", "decider.md").read_text(encoding="utf-8")
            am = (re.search(r"RATING ANCHOR \(.*?\):\s*.*?\s(\d+\.\d+),\s*.*?\s(\d+\.\d+)\.", ev)
                  or re.search(r"With the venue edge[^:]*:\s*.*?\s(\d+\.\d+),\s*.*?\s(\d+\.\d+)\b", ev))
            anchor = [float(am.group(1)), float(am.group(2))] if am else None
        except OSError:
            pass
        lm = re.search(r"expected goals[^0-9\n]{0,20}(\d+(?:\.\d+)?)\s*[-\u2013]\s*(\d+(?:\.\d+)?)", ans, re.I)
        lams = [float(lm.group(1)), float(lm.group(2))] if lm else None
        label = ""
        try:                                                           # the label value.py measured after the run; an independent answer itself always says UNMEASURED
            label = str(json.loads(Path(d, "value.md").read_text(encoding="utf-8").strip().splitlines()[-1]).get("label") or "").upper()
        except (OSError, ValueError, IndexError, AttributeError):
            pass
        stamp = ans.split("Market comparison after the run", 1)
        dm = re.search(r"value\s*\(checked after the analysis\)\s*:\s*(real|thin|none|unmeasured)\b", stamp[1], re.I) if len(stamp) == 2 else None
        dm = dm or re.search(r"value\s*:\**\s*\**(real|thin|none|unmeasured)\b", ans, re.I)
        stake, closing = "", None
        try:
            sm = re.search(r"^Stake decision:\s*(BET|PASS)\b", Path(d, "value.md").read_text(encoding="utf-8"), re.M)
            stake = sm.group(1) if sm else ""
        except OSError:
            pass
        try:
            closing = [float(x) for x in json.loads(Path(d, "closing_odds.json").read_text(encoding="utf-8"))["fair_pct"]]      # optional: the market's fair 1X2 % just before kickoff
        except (OSError, ValueError, KeyError, TypeError):
            pass
        out.append({"stake": stake, "closing_fair_pct": closing, "decision": label or (dm.group(1).upper() if dm else ""), "home": m["home_team"], "away": m["away_team"], "kickoff": str(m.get("kickoff_utc") or "")[:10], "p": [float(head.group(i)) / 100 for i in (1, 2, 3)],
                    "bet": re.split(r",\s|\.\s", re.sub(r"\s*\([^)]*\)", "", bm.group(1)).strip(" *:-"))[0].strip() if bm else "", "odds_fair_pct": list(fair) if fair else None, "anchor_lams": anchor, "lams": lams})
    return out


def rps(p: list, res: int) -> float:
    """Ranked probability score for the ordered outcomes home, draw, away (lower is better): a miss by one step costs less than a miss by two, so a forecast that favours the right side but over-rates the draw is punished less than one on the wrong side."""
    o = [1.0 if i == res else 0.0 for i in range(3)]
    return 0.5 * ((p[0] - o[0]) ** 2 + ((p[0] + p[1]) - (o[0] + o[1])) ** 2)


PRICE_BANDS = ((0, 35, "long shot (market under 35%)"), (35, 50, "even-ish (35-50%)"), (50, 65, "favourite (50-65%)"), (65, 101, "heavy favourite (65%+)"))


_CHECK = None


def _check_module():
    """check.py loaded once (the band table asks for two probabilities per pick)."""
    global _CHECK
    if _CHECK is None:
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location("check_for_bands", Path(__file__).with_name("check.py"))
        _CHECK = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_CHECK)
    return _CHECK


def _pick_prob(e: dict, vec) -> float | None:
    """Percentage a [home, draw, away] vector gives to the logged pick (1X2 and double chance only; None for goals bets)."""
    if not vec or not e.get("bet"):
        return None
    chk = _check_module()
    t = sum(vec)
    if t <= 0:
        return None
    a = {"home": vec[0] / t, "draw": vec[1] / t, "away": vec[2] / t, "over_2_5": 0.5, "btts": 0.5}
    b = chk.norm(e["bet"])
    if "over25" in b or "under25" in b or "bothteams" in b or b.startswith("btts"):
        return None
    return chk.bet_probability(e["bet"], e["home"], e["away"], a)


def market_prob_of_pick(e: dict) -> float | None:
    """The market's fair percentage for the logged pick, or None when the pick is a goals bet or no odds were logged."""
    return _pick_prob(e, e.get("odds_fair_pct"))


def poisson_1x2(lh: float, la: float) -> list:
    """Home, draw, away probabilities (0 to 1) from two expected-goals figures."""
    import math
    ph = pd = pa = 0.0
    for i in range(11):
        for j in range(11):
            p = math.exp(-lh) * lh ** i / math.factorial(i) * math.exp(-la) * la ** j / math.factorial(j)
            ph, pd, pa = (ph + p, pd, pa) if i > j else (ph, pd + p, pa) if i == j else (ph, pd, pa + p)
    t = ph + pd + pa
    return [ph / t, pd / t, pa / t]


def context_lift(rows: list) -> str:
    """rows = [(entry, home goals, away goals)]. Brier of the sheet's anchor (before any judgment) minus Brier of the final answer, per match: positive means the specialists' and advocates' changes moved the forecast toward the result."""
    items = []
    for e, hg, ag in rows:
        lam = e.get("anchor_lams")
        if not lam or not e.get("p"):
            continue
        res = 0 if hg > ag else 1 if hg == ag else 2
        pa = poisson_1x2(lam[0], lam[1])
        b = lambda v: sum((v[i] - (1.0 if i == res else 0.0)) ** 2 for i in range(3))
        bm = None
        if e.get("odds_fair_pct"):
            t = sum(e["odds_fair_pct"])
            bm = b([x / t for x in e["odds_fair_pct"]])
        items.append((e, b(pa), b(e["p"]), bm))
    if not items:
        return "no anchor found in the run folders (needs evidence/decider.md)."
    n = len(items)
    lift = [a - f for _, a, f, _ in items]
    helped = sum(1 for x in lift if x > 0.005)
    hurt = sum(1 for x in lift if x < -0.005)
    withm = [(a, f, m) for _, a, f, m in items if m is not None]
    text = (f"{n} matches: anchor-only Brier {sum(a for _, a, _, _ in items) / n:.3f}, full skill {sum(f for _, _, f, _ in items) / n:.3f}; lift {sum(lift) / n:+.3f} per match "
            f"(judgment helped {helped}, hurt {hurt}, within 0.005 on {n - helped - hurt})")
    if withm:
        text += f"; on the {len(withm)} with odds: anchor {sum(a for a, _, _ in withm) / len(withm):.3f}, full {sum(f for _, f, _ in withm) / len(withm):.3f}, market {sum(m for _, _, m in withm) / len(withm):.3f}"
    return text + ("" if n >= 30 else f". Only {n} matches: noise until about 30.")


def context_lift_lines(rows: list) -> str:
    """One line per match: anchor Brier, final Brier, the change (negative is a better forecast), so each error can be traced to the judgment step."""
    out = []
    for e, hg, ag in rows:
        lam = e.get("anchor_lams")
        if not lam or not e.get("p"):
            continue
        res = 0 if hg > ag else 1 if hg == ag else 2
        pa = poisson_1x2(lam[0], lam[1])
        b = lambda v: sum((v[i] - (1.0 if i == res else 0.0)) ** 2 for i in range(3))
        out.append(f"- {e['home']} v {e['away']} {hg}-{ag}: anchor xG {lam[0]:.2f}-{lam[1]:.2f} ({100 * pa[0]:.0f}/{100 * pa[1]:.0f}/{100 * pa[2]:.0f}) Brier {b(pa):.3f}; final {100 * e['p'][0]:.0f}/{100 * e['p'][1]:.0f}/{100 * e['p'][2]:.0f} Brier {b(e['p']):.3f}; "
                   f"{'judgment helped' if b(pa) - b(e['p']) > 0.005 else 'judgment hurt' if b(pa) - b(e['p']) < -0.005 else 'no real change'}")
    return "\n".join(out)


def xg_read(rows: list, xg: dict) -> str:
    """How well the forecast read the match, against the match's own xG after full time (results.csv home_xg/away_xg). A result is one noisy draw
    from the chances; the xG is close to the chances themselves, so far fewer matches are needed. Per match: our expected goals against the real xG,
    the same for the anchor and the market-implied expected goals, and whether the side we favoured won the chances."""
    items, lines = [], []
    chk = _check_module()
    for e, hg, ag in rows:
        x = xg.get(id(e))
        if not x or not e.get("p"):
            continue
        q = poisson_1x2(x[0], x[1])                                   # the 1X2 the chances deserved
        soft = lambda v: sum((v[i] - q[i]) ** 2 for i in range(3))
        err = lambda lam: (abs(lam[0] - x[0]) + abs(lam[1] - x[1])) / 2 if lam else None
        mk = None
        if e.get("odds_fair_pct"):
            f = e["odds_fair_pct"]
            mk = list(chk.calc.implied_lams(f[0], f[1], f[2])[:2])
        fav = 0 if e["p"][0] > e["p"][2] else 2
        chances = 0 if x[0] - x[1] >= 0.3 else 2 if x[1] - x[0] >= 0.3 else 1
        items.append((soft(e["p"]), err(e.get("lams")), err(e.get("anchor_lams")), err(mk), fav == chances, chances == 1,
                      soft([v / sum(e["odds_fair_pct"]) for v in e["odds_fair_pct"]]) if e.get("odds_fair_pct") else None))
        lines.append(f"- {e['home']} v {e['away']} {hg}-{ag}, xG {x[0]:.2f}-{x[1]:.2f}: ours {('%.2f-%.2f' % tuple(e['lams'])) if e.get('lams') else 'n/a'}"
                     + (f", anchor {e['anchor_lams'][0]:.2f}-{e['anchor_lams'][1]:.2f}" if e.get("anchor_lams") else "") + (f", market-implied {mk[0]:.2f}-{mk[1]:.2f}" if mk else "")
                     + f"; the side we favoured {'won the chances' if fav == chances else 'did not win the chances (level on xG)' if chances == 1 else 'LOST the chances'}")
    if not items:
        return ""
    n = len(items)
    avg = lambda k: [v[k] for v in items if v[k] is not None]
    fmt = lambda vals: f"{sum(vals) / len(vals):.2f} (n={len(vals)})" if vals else "n/a"
    text = (f"{n} matches with match xG: the side we favoured won the chances (0.3+ xG) in {sum(1 for v in items if v[4])}, level in {sum(1 for v in items if v[5])}; "
            f"average miss of the expected goals per side: ours {fmt(avg(1))}, anchor {fmt(avg(2))}, market-implied {fmt(avg(3))}; "
            f"Brier against the 1X2 the chances deserved: ours {sum(v[0] for v in items) / n:.3f}" + (f", market {sum(avg(6)) / len(avg(6)):.3f} (n={len(avg(6))})" if avg(6) else "")
            + ("" if n >= 15 else f". Only {n}: still noise, but xG settles faster than results (about 15 matches, not 30)."))
    return text + "\n" + "\n".join(lines)


def goals_markets(rows: list) -> str:
    """Over/under 2.5 and both teams to score, from each answer's own expected goals, against the result: Brier and how often the lean was right."""
    chk = _check_module()
    over, btts = [], []
    for e, hg, ag in rows:
        if not e.get("lams"):
            continue
        a = chk.calc.analyse(*e["lams"])
        over.append((a["over_2_5"], hg + ag > 2))
        btts.append((a["btts"], hg > 0 and ag > 0))
    if not over:
        return "no expected goals found in the answers."
    def part(name, xs):
        b = sum((p - (1.0 if y else 0.0)) ** 2 for p, y in xs) / len(xs)
        right = sum(1 for p, y in xs if (p >= 0.5) == y)
        return f"{name}: lean right {right} of {len(xs)}, Brier {b:.3f} (0.25 is a coin toss)"
    return part("over 2.5", over) + "; " + part("both teams to score", btts) + ("" if len(over) >= 30 else f"; only {len(over)}: noise until about 30")


DISAGREE_POINTS = 5.0


def disagreement_call(e: dict) -> tuple[int, float, float] | None:
    """The 1X2 outcome where our probability beats the market's fair price by the most (at least DISAGREE_POINTS), as (outcome index, ours, market's), or None."""
    q = e.get("odds_fair_pct")
    if not q or not e.get("p") or sum(q) <= 0:
        return None
    t = sum(q)
    best = None
    for i in range(3):
        mk, own = 100 * q[i] / t, 100 * e["p"][i]
        if own - mk >= DISAGREE_POINTS and (best is None or own - mk > best[1] - best[2]):
            best = (i, own, mk)
    return best


def disagreement_profit(rows: list) -> str:
    """Flat 1-unit stakes on each disagreement call at the market's fair price (before the bookmaker's margin): does following the view pay, where the pick may have ignored it?"""
    units, n, k = 0.0, 0, 0
    for e, hg, ag in rows:
        c = disagreement_call(e)
        if not c:
            continue
        res = 0 if hg > ag else 1 if hg == ag else 2
        n += 1
        if c[0] == res:
            k += 1
            units += 100 / c[2] - 1
        else:
            units -= 1
    if not n:
        return ""
    return (f"Backing every disagreement call at the market's fair price (flat 1 unit, before the bookmaker's margin): {n} bets, {k} won, {units:+.2f} units"
            + ("" if n >= 30 else f"; only {n} bets, noise until about 30") + ".")


def disagreement_summary(rows: list) -> str:
    """rows = [(entry, home goals, away goals)]. Does the outcome we rate 5+ points above the market happen more often than the market says? Compared with what the market's own price for it would have scored."""
    calls = []
    for e, hg, ag in rows:
        c = disagreement_call(e)
        if c:
            res = 0 if hg > ag else 1 if hg == ag else 2
            calls.append((c[0] == res, c[1], c[2]))
    if not calls:
        return "no match had an outcome 5+ points above the market (or no odds were logged)."
    n, k = len(calls), sum(1 for c in calls if c[0])
    return (f"{n} calls; the outcome happened {k} times ({100 * k / n:.0f}%); we said {sum(c[1] for c in calls) / n:.0f}% on average, the market {sum(c[2] for c in calls) / n:.0f}%. "
            f"Our side is right when the actual rate is above the market's figure" + ("" if n >= 30 else f"; only {n} calls, so this is noise until about 30") + ".")


def blend_fit(rows: list) -> str:
    """The share w of our own probabilities in w * ours + (1 - w) * market that scores best on the matches with odds. w near 0: our view adds nothing to the market; near 1: it beats it."""
    items = []
    for e, hg, ag in rows:
        q = e.get("odds_fair_pct")
        if q and e.get("p") and sum(q) > 0:
            t = sum(q)
            items.append(([x / t for x in q], e["p"], 0 if hg > ag else 1 if hg == ag else 2))
    if not items:
        return "no matches with odds."
    def brier(w):
        return sum(sum((w * p[i] + (1 - w) * m[i] - (1.0 if i == res else 0.0)) ** 2 for i in range(3)) for m, p, res in items) / len(items)
    best = min((k / 20 for k in range(21)), key=brier)
    return (f"{len(items)} matches: market alone {brier(0):.3f}, ours alone {brier(1):.3f}, best blend {brier(best):.3f} at {best:.0%} ours / {1 - best:.0%} market"
            + ("" if len(items) >= 30 else f". Only {len(items)} matches: noise until about 30, keep the prior weight") + ".")


def stake_summary(rows: list) -> str:
    """Flat 1-unit stakes on the answers whose Stake decision was BET, at the market's fair price for the pick (before the margin); the PASS answers are counted only."""
    bet = [(e, hg, ag) for e, hg, ag in rows if e.get("stake") == "BET"]
    passed = sum(1 for e, _, _ in rows if e.get("stake") == "PASS")
    units, k, n = 0.0, 0, 0
    for e, hg, ag in bet:
        mp, ok = market_prob_of_pick(e), hit(e.get("bet", ""), e["home"], e["away"], hg, ag)
        if mp is None or ok is None:
            continue
        n += 1
        k += bool(ok)
        units += (100 / mp - 1) if ok else -1
    return f"{n} BET (won {k}, {units:+.2f} units at fair prices), {passed} PASS" + ("" if n >= 30 else f"; only {n} bets, noise until about 30") + "."


def clv_summary(rows: list) -> str:
    """Closing line value: for each disagreement call with a closing price (closing_odds.json in the run folder), the closing fair % for that outcome minus the % at logging. Positive means the market moved our way, a faster sign of an edge than results."""
    d = []
    for e, _, _ in rows:
        c, close = disagreement_call(e), e.get("closing_fair_pct")
        if c and close and sum(close) > 0:
            d.append(100 * close[c[0]] / sum(close) - c[2])
    if not d:
        return "no closing prices (put closing_odds.json {\"fair_pct\": [h, d, a]} in a run folder to measure it)."
    return f"{len(d)} calls: the market moved {sum(d) / len(d):+.1f} points toward our side on average ({sum(1 for x in d if x > 0)} toward, {sum(1 for x in d if x < 0)} away)" + ("" if len(d) >= 30 else f"; only {len(d)}, noise until about 30") + "."


def band_table(items: list) -> str:
    """items = [(market % for the pick, my % for the pick or None, hit bool)]. One line per price band: where do the picks win and lose?"""
    lines = []
    for lo, hi, label in PRICE_BANDS:
        sel = [x for x in items if lo <= x[0] < hi]
        if sel:
            mine = [x[1] for x in sel if x[1] is not None]
            lines.append(f"| {label} | {len(sel)} | {sum(1 for x in sel if x[2])} ({100 * sum(1 for x in sel if x[2]) / len(sel):.0f}%) | {sum(x[0] for x in sel) / len(sel):.0f}% | {(sum(mine) / len(mine)) if mine else float('nan'):.0f}% |")
    return "| Market price of the pick | Picks | Hit | Market says | You said |\n|---|---|---|---|---|\n" + "\n".join(lines) if lines else "n/a"


def longshot_calibration(rows: list) -> str:
    """KellyBench: LLM agents systematically over-rated draws and longshots. Every outcome we gave under 20%: how often did it happen, against what we said?"""
    sel = [(e["p"][i], int((0 if h > a else 1 if h == a else 2) == i)) for e, h, a in rows for i in range(3) if e["p"][i] < 0.20]
    if not sel:
        return "n/a"
    pred, act = sum(x for x, _ in sel) / len(sel), sum(y for _, y in sel) / len(sel)
    verdict = "longshots OVER-rated: shorten them" if pred - act > 0.05 else "longshots UNDER-rated" if act - pred > 0.05 else "longshots about right"
    return f"{len(sel)} outcomes under 20%: you said {100 * pred:.0f}%, happened {100 * act:.0f}% ({verdict})" + ("; under 30 matches is noise" if len(rows) < 30 else "")


def draw_calibration(rows: list) -> str:
    """Draws are the outcome the analyst missed most: your average draw probability v how often it happened, split by whether you rated the match close (draw 27%+) or not, with the market's draw average where logged."""
    n = len(rows)
    if not n:
        return "n/a"
    drew = [int(h == a) for _, h, a in rows]
    mine = [e["p"][1] for e, _, _ in rows]
    out = [f"all {n}: you average {100 * sum(mine) / n:.0f}% draw, drawn {100 * sum(drew) / n:.0f}%"]
    mk = [(sum(e["odds_fair_pct"][1:2]) / sum(e["odds_fair_pct"]), d) for (e, _, _), d in zip(rows, drew) if e.get("odds_fair_pct")]
    if mk:
        out.append(f"market average {100 * sum(m for m, _ in mk) / len(mk):.0f}% on its {len(mk)}")
    for name, sel in (("rated close (draw 27%+)", [d for m, d in zip(mine, drew) if m >= 0.27]), ("rated open (draw under 27%)", [d for m, d in zip(mine, drew) if m < 0.27])):
        if sel:
            out.append(f"{name}: drawn {100 * sum(sel) / len(sel):.0f}% (n={len(sel)})")
    gap = sum(drew) / n - sum(mine) / n
    out.append("draws UNDER-rated by " + f"{100 * gap:.0f} points: raise the draw base rate" if gap > 0.05 else "draws OVER-rated by " + f"{-100 * gap:.0f} points" if gap < -0.05 else "draw level is about right")
    if n < 30:
        out.append("under 30 matches: noise, do not retune on this")
    return "; ".join(out)


def main(log_path: str, results_path: str, answers: list[str] | None = None) -> int:
    try:
        logs = entries_from_answers(answers) if answers is not None else [json.loads(x) for x in open(log_path, encoding="utf-8") if x.strip()]
        results = list(csv.DictReader(open(results_path, encoding="utf-8")))
    except (OSError, ValueError) as e:
        print(f"cannot read the files: {e}", file=sys.stderr)
        return 2
    latest: dict[tuple, dict] = {}
    for e in logs:                                          # the latest forecast of a fixture counts
        if isinstance(e, dict) and "p" in e:
            latest[(norm(e.get("home")), norm(e.get("away")), str(e.get("kickoff"))[:10])] = e
    rows = []
    xg: dict = {}
    for (h, a, k), e in latest.items():
        for r in results:
            try:
                day, kick = datetime.date.fromisoformat(r["date"][:10]), datetime.date.fromisoformat(k)
            except (ValueError, KeyError):
                continue
            if norm(r.get("home_team")) == h and norm(r.get("away_team")) == a and abs((day - kick).days) <= 1:
                rows.append((e, int(r["home_score"]), int(r["away_score"])))
                try:
                    xg[id(e)] = (float(r["home_xg"]), float(r["away_xg"]))
                except (KeyError, TypeError, ValueError):
                    pass
                break
    if not rows:
        print("No logged forecast matches a result yet (check team names, kickoff dates and the results file).")
        return 0
    print("| Match | Your 1X2 % | Result | Your bet | Bet |\n|---|---|---|---|---|")
    hits = n_bets = n_pass = 0
    by_value: dict = {}
    b_me = b_bk = n_bk = 0.0
    r_me = r_bk = 0.0
    bands: list = []
    for e, hg, ag in rows:
        res = 0 if hg > ag else 1 if hg == ag else 2
        ok = hit(e.get("bet", ""), e["home"], e["away"], hg, ag)
        n_bets += ok is not None                          # every pick counts: the skill always gives its best bet (older PASS answers are scored as picks too)
        hits += bool(ok)
        mp = market_prob_of_pick(e)
        if mp is not None and ok is not None:
            bands.append((mp, _pick_prob(e, e.get("p")), bool(ok)))
        lvl = e.get("decision") or "?"
        by_value.setdefault(lvl, [0, 0])
        by_value[lvl][0] += ok is not None
        by_value[lvl][1] += bool(ok)
        p = e["p"]
        b_me += sum((p[i] - (1.0 if i == res else 0.0)) ** 2 for i in range(3))
        r_me += rps(p, res)
        if e.get("odds_fair_pct"):
            t = sum(e["odds_fair_pct"])
            q = [x / t for x in e["odds_fair_pct"]]
            b_bk += sum((q[i] - (1.0 if i == res else 0.0)) ** 2 for i in range(3))
            r_bk += rps(q, res)
            n_bk += 1
        print(f"| {e['home']} v {e['away']} | {100 * p[0]:.0f}/{100 * p[1]:.0f}/{100 * p[2]:.0f} | {hg}-{ag} | {e.get('bet')} | {'HIT' if ok else 'miss' if ok is not None else '?'} ({e.get('decision') or 'no value label'}) |")
    n = len(rows)
    print(f"\nSettled {n}; picks {n_bets}; picks hit {hits} of {n_bets} ({100 * hits / max(n_bets, 1):.0f}%).")
    print("Hit rate by the Value label (does REAL value beat THIN/NONE?): " + "; ".join(f"{k} {v[1]} of {v[0]}" for k, v in sorted(by_value.items())))
    print("Disagreement calls (our outcome 5+ points above the market's fair price; the pick is scored above, this is the view): " + disagreement_summary(rows))
    dp = disagreement_profit(rows)
    if dp:
        print(dp)
    print("Best share of our own view against the market (Brier): " + blend_fit(rows))
    print("Stake decision (BET only on REAL value, else PASS): " + stake_summary(rows))
    print("Closing line value: " + clv_summary(rows))
    print("Context lift (anchor alone against the finished answer; does the judgment add anything?): " + context_lift(rows))
    cl = context_lift_lines(rows)
    if cl:
        print(cl)
    xr = xg_read(rows, xg)
    if xr:
        print("Read of the match (against its own xG; did we see the chances right, whatever the finishing?): " + xr)
    print("Goals markets (from your expected goals): " + goals_markets(rows))
    print(f"Brier (lower is better): you {b_me / n:.3f}" + (f"; bookmaker fair odds {b_bk / n_bk:.3f} on the {int(n_bk)} where you logged them" if n_bk else "") + "; guessing equal chances 0.667.")
    print(f"Ranked probability score, the field's standard (lower is better; it respects the home-draw-away order): you {r_me / n:.4f}" + (f"; bookmaker fair odds {r_bk / n_bk:.4f}" if n_bk else "") + "; guessing equal chances 0.2222.")
    import math
    ll = sum(-math.log(max(1e-9, e["p"][0 if h > a else 1 if h == a else 2])) for e, h, a in rows) / n
    print(f"Log loss (lower is better): you {ll:.3f}; guessing equal chances {math.log(3):.3f}.")
    tops = [(max(e["p"]), int(max(range(3), key=lambda i: e["p"][i]) == (0 if h > a else 1 if h == a else 2))) for e, h, a in rows]
    bins = [(0, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 1.01)]
    cal = []
    for lo, hi in bins:
        sel = [hit_ for p_, hit_ in tops if lo <= p_ < hi]
        if sel:
            cal.append(f"{int(lo * 100)}-{min(int(hi * 100), 100)}%: predicted {100 * sum(p_ for p_, _ in tops if lo <= p_ < hi) / len(sel):.0f}% -> happened {100 * sum(sel) / len(sel):.0f}% (n={len(sel)})")
    print("Calibration of the most likely outcome: " + ("; ".join(cal) or "n/a"))
    print("Hit rate by the market's price for the pick (1X2 and double chance; where do we lose?):\n" + band_table(bands))
    print("Longshot calibration (KellyBench: models over-rate draws and longshots): " + longshot_calibration(rows))
    print("Draw calibration: " + draw_calibration(rows))
    print("Small samples are noise: judge the analyst only after dozens of matches; a calibration bin with fewer than 20 matches says almost nothing.")
    return 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    if len(argv) >= 3 and argv[0] == "--answers":
        sys.exit(main("", argv[-1], answers=argv[1:-1]))
    if len(argv) != 2:
        print("usage: python3 score.py forecasts.jsonl results.csv   or   python3 score.py --answers DIR [DIR ...] results.csv", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(argv[0], argv[1]))
