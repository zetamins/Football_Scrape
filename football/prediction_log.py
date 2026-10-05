"""Local, append-only log of every prediction this app makes, plus scoring
of the log against real results -- so model changes can be judged on a
growing out-of-sample record instead of a handful of hand-checked matches.

    python -m football.prediction_log import <dir-of-report-jsons>
    python -m football.prediction_log score [--results results.csv]

The CLI appends a record after every report (cli.py) and feeds the log back
into run_search, so each report's own `calibration` section works with no
Android history. `score` settles records against finished results (the
public international-results archive by default, or a CSV in the same
format) and prints per-method Brier / log loss / accuracy, each compared
with the bookmaker odds on the *same* matches.

Only predictions generated before kickoff are scored (calibration.py's
rule), one per match (the latest pre-kickoff one).
"""

from __future__ import annotations

import csv
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .calibration import _latest_pre_kickoff, _probabilities, brier_score, log_loss
from .national_elo import canonical_name

LOG_NAME = "prediction-log.jsonl"
METHODS = ("blended", "market_implied", "heuristic_blend", "xg_model", "squad_value_model", "history_model")
_REFERENCE = "market_implied"


def default_path() -> Path:
    return Path.cwd() / "output" / LOG_NAME


def record_from_report(report: dict[str, Any]) -> dict[str, Any] | None:
    """Compact log record from a build_report_json() dict; None when the
    report has no upcoming fixture or no prediction to log."""
    match = report.get("match") or {}
    prediction = (report.get("insights") or {}).get("prediction")
    home, away, kickoff, generated = match.get("home_team"), match.get("away_team"), match.get("kickoff_utc"), report.get("generatedAt")
    if not (prediction and home and away and kickoff and generated):
        return None
    return {
        "home_team": home, "away_team": away, "kickoff_utc": kickoff, "generated_at": generated,
        "competition": match.get("competition"), "model": prediction.get("model"), "prediction": prediction,
    }


def _identity(record: dict[str, Any]) -> tuple:
    return (record.get("home_team"), record.get("away_team"), (record.get("kickoff_utc") or "")[:10], record.get("generated_at"))


def load(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or default_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except ValueError:
            continue  # a torn/garbled line must not take the whole log down
    return records


def append(record: dict[str, Any], path: Path | None = None) -> bool:
    """Append unless this exact prediction (teams, kickoff day, generated_at)
    is already logged. Returns whether it was written."""
    path = path or default_path()
    if _identity(record) in {_identity(r) for r in load(path)}:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return True


def append_report(report: dict[str, Any], path: Path | None = None) -> bool:
    record = record_from_report(report)
    return append(record, path) if record else False


def import_reports(directory: Path, path: Path | None = None) -> tuple[int, int]:
    """(written, skipped) for every *.json report in `directory`."""
    written = skipped = 0
    for f in sorted(directory.glob("*.json")):
        try:
            report = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            skipped += 1
            continue
        if isinstance(report, dict) and append_report(report, path):
            written += 1
        else:
            skipped += 1
    return written, skipped


def parse_results_csv(text: str) -> list[dict[str, Any]]:
    """Rows of `date,home_team,away_team,home_score,away_score[,...]` (the
    martj42 archive layout). Unplayed rows (blank scores) are skipped."""
    out = []
    for row in csv.DictReader(text.splitlines()):
        try:
            out.append({
                "day": date.fromisoformat(row["date"]), "home": canonical_name(row["home_team"]),
                "away": canonical_name(row["away_team"]), "hg": int(row["home_score"]), "ag": int(row["away_score"]),
            })
        except (KeyError, ValueError):
            continue
    return out


def settle(records: list[dict[str, Any]], results: list[dict[str, Any]]) -> list[tuple[dict[str, Any], int, int, int]]:
    """(record, outcome 0/1/2 = home/draw/away, home_goals, away_goals) for
    each latest-pre-kickoff record with a finished result. A result matches on
    canonical team names and a kickoff date within +-1 day (UTC vs local)."""
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in results:
        index.setdefault((r["home"], r["away"]), []).append(r)
    settled = []
    for record in _latest_pre_kickoff(records):
        kickoff = date.fromisoformat(record["kickoff_utc"][:10])
        for r in index.get((canonical_name(record["home_team"]), canonical_name(record["away_team"])), []):
            if abs((r["day"] - kickoff).days) <= 1:
                outcome = 0 if r["hg"] > r["ag"] else (1 if r["hg"] == r["ag"] else 2)
                settled.append((record, outcome, r["hg"], r["ag"]))
                break
    return settled


def summarize(settled: list[tuple[dict[str, Any], int, int, int]]) -> list[dict[str, Any]]:
    """Per method: n, Brier, log loss, accuracy, and (for non-reference
    methods) the Brier difference vs market odds on the matches both
    cover -- positive = worse than the market."""
    rows = []
    market = {}
    for i, (record, outcome, _, _) in enumerate(settled):
        probs = _probabilities((record.get("prediction") or {}).get(_REFERENCE))
        if probs is not None:
            market[i] = brier_score(probs, outcome)
    for method in METHODS:
        scored = []
        for i, (record, outcome, _, _) in enumerate(settled):
            probs = _probabilities((record.get("prediction") or {}).get(method))
            if probs is not None:
                scored.append((i, probs, outcome))
        if not scored:
            continue
        n = len(scored)
        paired = [brier_score(p, o) - market[i] for i, p, o in scored if i in market]
        rows.append({
            "method": method, "n": n,
            "brier": sum(brier_score(p, o) for _, p, o in scored) / n,
            "log_loss": sum(log_loss(p, o) for _, p, o in scored) / n,
            "accuracy": sum(1 for _, p, o in scored if p.index(max(p)) == o) / n,
            "vs_market": (sum(paired) / len(paired)) if method != _REFERENCE and paired else None,
            "vs_market_n": len(paired) if method != _REFERENCE else None,
        })
    return rows


def format_summary(rows: list[dict[str, Any]], settled_count: int, pending: int) -> str:
    if not rows:
        return f"No scored predictions yet ({pending} logged, none with a known result)."
    lines = [f"{settled_count} settled, {pending} pending. Brier: 0 perfect, 0.667 = guessing 1/3 each.", "",
             f"{'method':18} {'n':>4} {'brier':>7} {'logloss':>8} {'acc':>6} {'vs market (same matches)':>26}"]
    for r in rows:
        vs = "-" if r["vs_market"] is None else f"{r['vs_market']:+.4f} (n={r['vs_market_n']})"
        lines.append(f"{r['method']:18} {r['n']:>4} {r['brier']:>7.4f} {r['log_loss']:>8.4f} {100 * r['accuracy']:>5.1f}% {vs:>26}")
    return "\n".join(lines)


def _flag(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "score"
    if cmd == "import":
        if len(argv) < 3:
            print("usage: import <dir-of-report-jsons>", file=sys.stderr)
            return 2
        written, skipped = import_reports(Path(argv[2]))
        print(f"imported {written} predictions ({skipped} skipped) into {default_path()}")
        return 0
    if cmd == "score":
        records = load()
        results_file = _flag(argv, "--results")
        if results_file:
            results = parse_results_csv(Path(results_file).read_text(encoding="utf-8"))
        else:
            from .history_train import ARCHIVE_URL, _get_text  # noqa: PLC0415 -- network only when scoring
            results = parse_results_csv(_get_text(ARCHIVE_URL))
        settled = settle(records, results)
        pending = len(_latest_pre_kickoff(records)) - len(settled)
        print(format_summary(summarize(settled), len(settled), pending))
        return 0
    print("usage: python -m football.prediction_log import <dir> | score [--results file.csv]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
