#!/usr/bin/env python3
"""Save the market's price just before kickoff, so score.py can measure closing line value.

    python3 closing_odds.py RUN_DIR      one fetch of football-data.co.uk's upcoming-fixtures file -> RUN_DIR/closing_odds.json

Closing line value (did the market move towards our view after we logged it?) shows an edge in far fewer matches than
results do. Run it within CLOSE_HOURS of kickoff. It refuses after kickoff (the file drops played matches, and a later
price is not a closing price) and never retries: no row means the match is not in a tracked league or not yet listed.
The run folder's report.json gives the teams and kickoff; nothing in the run is changed except closing_odds.json.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PKG = Path(__file__).resolve().parent                       # holds football/ (the ported scraping layer)
CLOSE_HOURS = 3.0


def minutes_to_kickoff(kickoff: str, now: datetime) -> float:
    return (datetime.fromisoformat(kickoff.replace("Z", "+00:00")) - now).total_seconds() / 60


def fair_pct(odds) -> list[float] | None:
    fair = [getattr(odds, k, None) for k in ("home_win_fair_pct", "draw_fair_pct", "away_win_fair_pct")]
    if not all(isinstance(v, (int, float)) for v in fair):
        raw = [getattr(odds, k, None) for k in ("home_win_odds", "draw_odds", "away_win_odds")]
        if not all(isinstance(v, (int, float)) and v > 1 for v in raw):
            return None
        fair = [100 / v for v in raw]
    t = sum(fair)
    return [round(100 * v / t, 2) for v in fair]


def main(run_dir: str) -> int:
    run = Path(run_dir)
    try:
        m = json.loads((run / "report.json").read_text(encoding="utf-8"))["match"]
        home, away, kickoff = m["home_team"], m["away_team"], m["kickoff_utc"]
    except (OSError, ValueError, KeyError, TypeError) as err:
        print(f"cannot read {run / 'report.json'}: {err}", file=sys.stderr)
        return 2
    now = datetime.now(UTC)
    left = minutes_to_kickoff(kickoff, now)
    if left <= 0:
        print(f"kickoff {kickoff} has passed: a price taken now is not a closing price", file=sys.stderr)
        return 2
    if left > CLOSE_HOURS * 60:
        print(f"kickoff is {left / 60:.1f} h away: run this within {CLOSE_HOURS:g} h of kickoff", file=sys.stderr)
        return 2
    sys.path.insert(0, str(PKG))
    from football.sites import footballdata
    odds, _ = asyncio.run(footballdata.get_upcoming_fixture(home, away))
    fair = fair_pct(odds) if odds else None
    if not fair:
        print(f"no 1X2 price for {home} v {away} in the upcoming-fixtures file (league not tracked or not listed)", file=sys.stderr)
        return 1
    out = {"fair_pct": fair, "fetched_at": now.isoformat(timespec="seconds"), "kickoff_utc": kickoff,
           "minutes_before_kickoff": round(left), "source": "football-data.co.uk fixtures.csv (Avg columns, de-vigged)"}
    (run / "closing_odds.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{home} v {away}: closing fair {fair[0]:.1f} / {fair[1]:.1f} / {fair[2]:.1f} ({round(left)} min before kickoff) -> {run / 'closing_odds.json'}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
