"""Token-free scorecard: run the engine over a folder of reports, match the real results, and show how the recommended bets did, what failed and why.

    python -m football.oracle score <reports folder | report.json ...> --results results.csv      (csv: date,home_team,away_team,home_score,away_score)
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from . import oracle
from .facts import extract_facts
from ..national_elo import canonical_name
from ..prediction_log import parse_results_csv


def bet_hit(selection: str, home: str, away: str, hg: int, ag: int) -> bool:
    """Did the recommended selection win? `selection` is exactly the text oracle.recommend() produces."""
    total, both = hg + ag, hg > 0 and ag > 0
    fixed = {"Over 2.5 goals": total > 2, "Under 2.5 goals": total <= 2, "Both teams to score: Yes": both, "Both teams to score: No": not both, "Draw": hg == ag}
    if selection in fixed:
        return fixed[selection]
    if selection == f"{home} or draw":
        return hg >= ag
    if selection == f"draw or {away}":
        return ag >= hg
    if selection == "Either side to win (no draw)":
        return hg != ag
    return hg > ag if selection == f"{home} to win" else ag > hg


def why_missed(rec: dict, home: str, away: str, hg: int, ag: int) -> str:
    market = rec["market"]
    if market == "Double chance":
        return "draw" if hg == ag else f"{home if hg > ag else away} won"
    if market == "1X2":
        return "draw" if hg == ag else f"upset: {home if hg > ag else away} won"
    if market == "Under 2.5":
        return f"{hg + ag} goals"
    if market == "Over 2.5":
        return f"only {hg + ag} goal{'s' if hg + ag != 1 else ''}"
    if market == "BTTS Yes":
        return "nobody scored" if hg + ag == 0 else f"{home if hg == 0 else away} did not score"
    return "both teams scored"


def _reports(paths: list[str]) -> list[dict]:
    files: list[Path] = []
    for a in paths:
        p = Path(a)
        files += sorted(p.glob("*.json")) if p.is_dir() else [p]
    out = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):        # a folder may also hold opinion files or lists: only report objects count
            out.append(data)
    return out


def score_reports(reports: list[dict], results: list[dict]) -> dict:
    index: dict[tuple[str, str], list[dict]] = {}
    for r in results:
        index.setdefault((r["home"], r["away"]), []).append(r)
    rows = []
    for rep in reports:
        m = rep.get("match") or {}
        if not (m.get("home_team") and m.get("away_team") and m.get("kickoff_utc")):
            continue
        kick = date.fromisoformat(m["kickoff_utc"][:10])
        res = next((r for r in index.get((canonical_name(m["home_team"]), canonical_name(m["away_team"])), []) if abs((r["day"] - kick).days) <= 1), None)
        pred = oracle.predict(rep, panel="none").get("prediction")
        if not res or not pred:
            continue
        h, a, hg, ag = m["home_team"], m["away_team"], res["hg"], res["ag"]
        odds = extract_facts(rep)["odds"]
        o = 0 if hg > ag else 1 if hg == ag else 2
        probs = [pred["home_win_pct"] / 100, pred["draw_pct"] / 100, pred["away_win_pct"] / 100]
        onehot = [1.0 if k == o else 0.0 for k in range(3)]
        rec = pred["recommendation"]
        rows.append({"match": f"{h} v {a}", "score": f"{hg}-{ag}", "hg": hg, "ag": ag, "outcome": o, "rec": rec, "hit": bet_hit(rec["selection"], h, a, hg, ag),
                     "pick_right": ["home", "draw", "away"][o] == pred["pick"], "p_actual": 100 * probs[o], "brier": sum((p - y) ** 2 for p, y in zip(probs, onehot)),
                     "odds_brier": (sum((x - y) ** 2 for x, y in zip((odds["home"], odds["draw"], odds["away"]), onehot)) if odds else None),
                     "odds_p_actual": (100 * (odds["home"], odds["draw"], odds["away"])[o] if odds else None), "draw_pct": pred["draw_pct"], "alert": pred["draw"]["alert"],
                     "goals": hg + ag, "expected_goals": pred["lam_home"] + pred["lam_away"], "draw_expected": probs[1]})
    return {"rows": rows}


def format_scorecard(sc: dict) -> str:
    rows = sc["rows"]
    n = len(rows)
    if not n:
        return "No settled matches: check the results file (date,home_team,away_team,home_score,away_score) and the report kickoff dates."
    hits = sum(r["hit"] for r in rows)
    quoted = sum(r["rec"]["probability_pct"] for r in rows) / n
    withodds = [r for r in rows if r["odds_brier"] is not None]
    draws = [r for r in rows if r["outcome"] == 1]
    flagged = [r for r in rows if r["alert"] != "none"]
    lines = [f"# Scorecard: {n} settled matches", "", "| Measure | Value |", "|---|---|",
             f"| Recommended bets that hit | {hits} of {n} ({100*hits/n:.0f}%); the engine quoted {quoted:.0f}% on average |",
             f"| 1X2 top pick right | {sum(r['pick_right'] for r in rows)} of {n} ({100*sum(r['pick_right'] for r in rows)/n:.0f}%) |",
             f"| Brier (lower is better) | engine {sum(r['brier'] for r in rows)/n:.3f}" + (f"; on the {len(withodds)} with odds: engine {sum(r['brier'] for r in withodds)/len(withodds):.3f} vs odds {sum(r['odds_brier'] for r in withodds)/len(withodds):.3f}" if withodds else "") + "; guessing 0.667 |",
             f"| Draws | {len(draws)} actual vs {sum(r['draw_expected'] for r in rows):.1f} expected; flagged WATCH/ALERT {len(flagged)}, of which {sum(1 for r in flagged if r['outcome'] == 1)} were draws; draws picked as the 1X2 bet {sum(1 for r in rows if r['rec']['selection'] == 'Draw')} |",
             f"| Goals per match | actual {sum(r['goals'] for r in rows)/n:.2f} vs engine {sum(r['expected_goals'] for r in rows)/n:.2f} |"]
    by = defaultdict(list)
    for r in rows:
        by[r["rec"]["market"]].append(r)
    lines += ["", "## By market", "| Market | Bets | Hits | Hit rate | Quoted |", "|---|---|---|---|---|"]
    lines += [f"| {m} | {len(v)} | {sum(x['hit'] for x in v)} | {100*sum(x['hit'] for x in v)/len(v):.0f}% | {sum(x['rec']['probability_pct'] for x in v)/len(v):.0f}% |" for m, v in sorted(by.items(), key=lambda kv: -len(kv[1]))]
    chk = defaultdict(list)
    for r in rows:
        g = r["rec"]["odds_gap"]
        chk["no odds" if not g else "under 5 points" if abs(g["gap_pct"]) < 5 else "5-10 points" if abs(g["gap_pct"]) < 10 else "10+ points"].append(r["hit"])
    lines += ["", "## Gap to the odds (a benchmark only: the bets never use the odds)", "| Largest gap, engine vs odds | Bets | Hits |", "|---|---|---|"]
    lines += [f"| {k} | {len(chk[k])} | {sum(chk[k])} |" for k in ("under 5 points", "5-10 points", "10+ points", "no odds") if chk[k]]
    misses = [r for r in rows if not r["hit"]]
    lines += ["", f"## Misses ({len(misses)})", "| Match | Score | Bet (prob %) | What happened | Engine gave the real result | Odds gave it |", "|---|---|---|---|---|---|"]
    for r in sorted(misses, key=lambda r: -r["rec"]["probability_pct"]):
        h, a = r["match"].split(" v ", 1)
        lines.append(f"| {r['match']} | {r['score']} | {r['rec']['selection']} ({r['rec']['probability_pct']}) | {why_missed(r['rec'], h, a, r['hg'], r['ag'])} | {r['p_actual']:.0f}% | {('%.0f%%' % r['odds_p_actual']) if r['odds_p_actual'] is not None else 'n/a'} |")
    causes = defaultdict(int)
    for r in misses:
        h, a = r["match"].split(" v ", 1)
        w = why_missed(r["rec"], h, a, r["hg"], r["ag"])
        causes["draw" if w == "draw" else "upset" if w.startswith("upset") else "goals" if ("goals" in w) else "BTTS"] += 1
    lines += ["", "Miss causes: " + ", ".join(f"{k} {v}" for k, v in sorted(causes.items(), key=lambda kv: -kv[1])) + f". Small samples: {n} matches cannot justify retuning; judge against the held-out 68% only once you have hundreds."]
    return "\n".join(lines)


def main(args: list[str]) -> int:
    results_path = None
    if "--results" in args:
        i = args.index("--results")
        results_path = args[i + 1] if i + 1 < len(args) else None
        args = args[:i] + args[i + 2:]
    paths = [a for a in args if not a.startswith("--")]
    if not paths or not results_path:
        print("usage: python -m football.oracle score <reports folder | report.json ...> --results results.csv", file=__import__("sys").stderr)
        return 2
    try:
        results = parse_results_csv(Path(results_path).read_text(encoding="utf-8"))
    except OSError as e:
        print(f"cannot read the results file: {e}", file=__import__("sys").stderr)
        return 2
    print(format_scorecard(score_reports(_reports(paths), results)))
    return 0
