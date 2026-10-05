"""Forward test for the player-absence adjustment.

No historical lineups exist, so the adjustment cannot be back-tested. Instead every logged live prediction stores the engine's
probabilities twice: absences OFF (what the engine uses) and absences ON (full scale), from the same sources. Once results
arrive, `score` compares the two on the matches where they differ and applies the promotion gate from
research/LINEUP_NEWS_PLAN.md. Nothing here changes any prediction.

    python -m football.oracle.forward_log score results.csv      # martj42 layout: date,home_team,away_team,home_score,away_score
"""

from __future__ import annotations

import json
import math
import random
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import quant
from .lineup import lineup_picture
from ..national_elo import canonical_name
from ..prediction_log import parse_results_csv

LOG_NAME = "oracle-forward-log.jsonl"
REQUIRED_KEYS = ("home_team", "away_team", "kickoff_utc", "generated_at", "off", "on")
MIN_MATCHES = 300          # settled matches where the two versions differ by at least MIN_GAP before the gate can pass
MIN_GAP = 0.005            # largest probability difference (any outcome) for a match to count as "differs"
BOOTSTRAPS = 2000


def default_path() -> Path:
    return Path.cwd() / "output" / LOG_NAME


def make_record(facts: dict, sources: list[dict]) -> dict | None:
    """The engine probabilities with absences off and on, plus who was missing. None without an upcoming fixture."""
    if not (facts["home"] and facts["away"] and facts["kickoff"] and facts["generated_at"]):
        return None
    lh0, la0, _ = quant.combine_rates(sources)
    mh, ma, _ = quant.absence_multipliers(facts, scale=1.0)
    lh1, la1, _ = quant.combine_rates(quant.apply_absences(sources, mh, ma))
    pic = lineup_picture(facts)
    return {
        "home_team": facts["home"], "away_team": facts["away"], "kickoff_utc": facts["kickoff"], "generated_at": facts["generated_at"],
        "off": [round(p, 5) for p in quant.outcome_probs(lh0, la0)], "on": [round(p, 5) for p in quant.outcome_probs(lh1, la1)],
        "lineup_confirmed": pic["confirmed"], "starters_out": {s: pic[s]["starters_out"] for s in ("home", "away")},
        "n_absent": {s: len(pic[s]["absentees"]) for s in ("home", "away")},
    }


def _identity(r: dict) -> tuple:
    return (canonical_name(r["home_team"]), canonical_name(r["away_team"]), r["kickoff_utc"][:10], r["generated_at"])


def load(path: Path | None = None) -> list[dict]:
    path = path or default_path()
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and all(k in rec for k in REQUIRED_KEYS):      # skip junk or truncated lines instead of crashing the score
            out.append(rec)
    return out


def append(record: dict, path: Path | None = None) -> bool:
    path = path or default_path()
    if _identity(record) in {_identity(r) for r in load(path)}:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return True


def _ts(value: str) -> datetime | None:
    """An ISO-8601 time as an aware UTC datetime (a trailing Z or +02:00 offset both work); None when it cannot be read. Text comparison breaks with mixed formats."""
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _before(generated: str, kickoff: str) -> bool:
    g, k = _ts(generated), _ts(kickoff)
    return (g < k) if g and k else generated < kickoff


def _latest_pre_kickoff(records: list[dict]) -> list[dict]:
    """One record per fixture: the latest generated before kickoff (a report made after kickoff may contain the result)."""
    best: dict[tuple, dict] = {}
    for r in records:
        if not _before(r["generated_at"], r["kickoff_utc"]):
            continue
        key = (canonical_name(r["home_team"]), canonical_name(r["away_team"]), r["kickoff_utc"][:10])
        if key not in best or (_ts(r["generated_at"]) or datetime.min.replace(tzinfo=timezone.utc)) > (_ts(best[key]["generated_at"]) or datetime.min.replace(tzinfo=timezone.utc)):
            best[key] = r
    return list(best.values())


def settle(records: list[dict], results: list[dict]) -> list[tuple[dict, int]]:
    index: dict[tuple[str, str], list[dict]] = {}
    for r in results:
        index.setdefault((r["home"], r["away"]), []).append(r)
    out = []
    for rec in _latest_pre_kickoff(records):
        kickoff = date.fromisoformat(rec["kickoff_utc"][:10])
        h, a = canonical_name(rec["home_team"]), canonical_name(rec["away_team"])
        for key, flip in (((h, a), False), ((a, h), True)):          # a source may list a neutral-venue fixture the other way round: then home and away swap
            hit = next((r for r in index.get(key, []) if abs((r["day"] - kickoff).days) <= 1), None)
            if hit:
                hg, ag = (hit["ag"], hit["hg"]) if flip else (hit["hg"], hit["ag"])
                out.append((rec, 0 if hg > ag else 1 if hg == ag else 2))
                break
    return out


def _brier(p: list[float], o: int) -> float:
    return sum((p[k] - (1.0 if k == o else 0.0)) ** 2 for k in range(3))


def _logloss(p: list[float], o: int) -> float:
    return -math.log(max(p[o], 1e-9))


def evaluate(settled: list[tuple[dict, int]], seed: int = 1) -> dict:
    """Paired comparison on matches where absences change the probabilities. Negative `diff` = absences ON is better."""
    differ = [(r, o) for r, o in settled if max(abs(a - b) for a, b in zip(r["on"], r["off"])) >= MIN_GAP]
    out: dict[str, Any] = {"settled": len(settled), "differ": len(differ), "needed": MIN_MATCHES}
    if len(differ) < 2:
        return {**out, "verdict": "not enough data", "metrics": {}}
    rng = random.Random(seed)
    metrics = {}
    for name, fn in (("brier", _brier), ("logloss", _logloss)):
        d = [fn(r["on"], o) - fn(r["off"], o) for r, o in differ]
        mean = sum(d) / len(d)
        boots = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(BOOTSTRAPS))
        metrics[name] = {"diff": round(mean, 5), "ci95": (round(boots[int(0.025 * BOOTSTRAPS)], 5), round(boots[int(0.975 * BOOTSTRAPS)], 5)),
                         "off": round(sum(fn(r["off"], o) for r, o in differ) / len(differ), 4), "on": round(sum(fn(r["on"], o) for r, o in differ) / len(differ), 4)}
    better = all(m["ci95"][1] < 0 for m in metrics.values())
    worse = any(m["ci95"][0] > 0 for m in metrics.values())
    if len(differ) < MIN_MATCHES:
        verdict = f"keep OFF: only {len(differ)} of the {MIN_MATCHES} matches needed"
    elif better:
        verdict = "gate passed on live data: absences ON beats OFF on Brier and log-loss (interval excludes zero); then confirm on a fresh batch before switching on"
    elif worse:
        verdict = "keep OFF: absences ON is worse"
    else:
        verdict = "keep OFF: no proven difference"
    return {**out, "verdict": verdict, "metrics": metrics, "strata": strata(settled)}


STRATA = (("confirmed lineup", lambda r: bool(r.get("lineup_confirmed"))), ("predicted lineup", lambda r: not r.get("lineup_confirmed")),
          ("a starter is out", lambda r: sum((r.get("starters_out") or {}).values()) > 0), ("no starter out", lambda r: sum((r.get("starters_out") or {}).values()) == 0))


def strata(settled: list[tuple[dict, int]]) -> list[dict]:
    """Descriptive only: where does absences ON beat OFF (negative Brier difference)? Practitioners find the effect varies by tier; no verdict is drawn from a tier."""
    out = []
    for name, pick in STRATA:
        rows = [(r, o) for r, o in settled if pick(r) and max(abs(a - b) for a, b in zip(r["on"], r["off"])) >= MIN_GAP]
        if rows:
            d = [_brier(r["on"], o) - _brier(r["off"], o) for r, o in rows]
            out.append({"stratum": name, "n": len(rows), "brier_diff": round(sum(d) / len(d), 5)})
    return out


def accuracy(settled: list[tuple[dict, int]]) -> dict:
    """How the engine (absences off, the version in use) did on all settled matches."""
    n = len(settled)
    if not n:
        return {"n": 0}
    picks = [max(range(3), key=lambda k: r["off"][k]) for r, _ in settled]
    return {"n": n, "pick_right": sum(p == o for p, (_, o) in zip(picks, settled)) / n,
            "brier": sum(_brier(r["off"], o) for r, o in settled) / n, "logloss": sum(_logloss(r["off"], o) for r, o in settled) / n,
            "draws_actual": sum(o == 1 for _, o in settled), "draws_expected": sum(r["off"][1] for r, _ in settled), "draw_picks": sum(p == 1 for p in picks),
            "guess_brier": 0.667}


def format_accuracy(a: dict) -> str:
    if not a["n"]:
        return "Accuracy: no settled matches yet"
    return (f"Accuracy on {a['n']} settled matches: pick right {a['pick_right']:.0%}, Brier {a['brier']:.3f} (guessing 0.667), log-loss {a['logloss']:.3f}; "
            f"draws {a['draws_actual']} actual vs {a['draws_expected']:.1f} expected, draws picked {a['draw_picks']}")


def format_evaluation(e: dict) -> str:
    lines = [f"Settled matches: {e['settled']}; absences change the probabilities in {e['differ']} (needed {e['needed']})", f"Verdict: {e['verdict']}"]
    for name, m in e["metrics"].items():
        lines.append(f"- {name}: OFF {m['off']} vs ON {m['on']}; difference ON-OFF {m['diff']:+} (95% interval {m['ci95'][0]:+} to {m['ci95'][1]:+}; negative favours ON)")
    lines += [f"- tier {t['stratum']}: {t['n']} matches, Brier ON-OFF {t['brier_diff']:+} (descriptive, no verdict from a tier)" for t in e.get("strata", [])]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = argv[1:]
    if len(args) != 2 or args[0] != "score":
        print("usage: python -m football.oracle.forward_log score results.csv", file=sys.stderr)
        return 2
    try:
        results = parse_results_csv(Path(args[1]).read_text(encoding="utf-8"))
    except OSError as e:
        print(f"cannot read the results file: {e}", file=sys.stderr)
        return 2
    records = load()
    settled = settle(records, results)
    print(f"{len(records)} logged, {len(_latest_pre_kickoff(records))} usable pre-kickoff")
    print(format_accuracy(accuracy(settled)))
    print(format_evaluation(evaluate(settled)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
