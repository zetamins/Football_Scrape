#!/usr/bin/env python3
"""Makes an odds-free copy of a match report, so the analysis can never lean on the bookmaker (Python standard library only).

    python3 blind.py report.json blind_report.json

Removes every bookmaker price (match.betting_odds, match.sofascore_betting_odds, the past meetings' historical_odds, their entries in field_sources and
dataWindows) and the scraper's own blended prediction (insights.prediction, which holds the market-implied probabilities). Everything else stays.
Prints what was removed. value.py later compares the finished answer with the market, after the analysis is done."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ODDS_WORDS = ("odds", "implied")


def _is_odds_key(key: str) -> bool:
    k = str(key).lower()
    return any(w in k for w in ODDS_WORDS) or k.endswith("fair_pct")


def blind(report: dict) -> tuple[dict, list[str]]:
    removed: list[str] = []

    def walk(o, path: str):
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                p = f"{path}/{k}"
                if _is_odds_key(k):
                    if v not in (None, {}, [], ""):
                        removed.append(p)
                    continue
                if path == "/insights" and k == "prediction":
                    removed.append(p)
                    continue
                out[k] = walk(v, p)
            return out
        if isinstance(o, list):
            return [walk(v, f"{path}[{i}]") for i, v in enumerate(o)]
        return o

    return walk(report, ""), removed


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    if src.resolve() == dst.resolve():
        print("blind.py: the output must be a different file (the original keeps the odds for value.py)", file=sys.stderr)
        return 2
    cleaned, removed = blind(json.loads(src.read_text(encoding="utf-8")))
    dst.write_text(json.dumps(cleaned, ensure_ascii=False), encoding="utf-8")
    print(f"removed {len(removed)} odds/prediction field(s): " + ", ".join(removed[:12]) + (" ..." if len(removed) > 12 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
