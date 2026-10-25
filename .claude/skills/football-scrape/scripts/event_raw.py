#!/usr/bin/env python3
"""Save Sofascore's RAW post-match data for one played match, to find out why it went the way it did.
    python3 event_raw.py RUN_DIR [OUT_DIR]      after kickoff only: -> OUT_DIR (default RUN_DIR/review-raw/) one .json per endpoint

The scraper keeps only the fields it parses; this keeps everything Sofascore sends for the match itself (event, statistics,
incidents, lineups with every player's statistics, shotmap, best players) and both teams' season statistics, so a review
can read fields the report never carries (errors leading to a goal, big chances, saves, duels). The files contain the
result: they are a post-match review, never pre-match evidence, and nothing reads them into a forecast.
One browser session, the scraper's own pacing, no retry; it honours the scraper's block marker and lock.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

PKG = Path(__file__).resolve().parent                       # holds football/ (the ported scraping layer)
WORK = Path(os.environ.get("FOOTBALL_WORK") or Path.cwd())
LOCK, BLOCK = WORK / "output" / ".scrape.lock", WORK / "output" / ".scrape_blocked"
EVENT_PARTS = ("", "/statistics", "/incidents", "/lineups", "/shotmap", "/best-players")


def event_id(m: dict) -> str | None:
    url = str(m.get("source_url") or "")
    if "sofascore" in url:
        return [p for p in url.split("/") if p][-1].split("#id:")[-1] or None
    return str(m["match_id"]) if str(m.get("match_id") or "").isdigit() else None


def season_urls(event: dict) -> list[tuple[str, str]]:
    """(file name, url) for both teams' season statistics in the event's own competition and season."""
    e = (event or {}).get("event") or {}
    ut = ((e.get("tournament") or {}).get("uniqueTournament") or {}).get("id")
    season = (e.get("season") or {}).get("id")
    if not (ut and season):
        return []
    out = []
    for side in ("homeTeam", "awayTeam"):
        tid = (e.get(side) or {}).get("id")
        if tid:
            out.append((f"season-statistics-{side[:4]}", f"https://www.sofascore.com/api/v1/team/{tid}/unique-tournament/{ut}/season/{season}/statistics/overall"))
    return out


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2):
        print(__doc__, file=sys.stderr)
        return 2
    run = Path(argv[0])
    out = Path(argv[1]) if len(argv) == 2 else run / "review-raw"
    try:
        m = json.loads((run / "report.json").read_text(encoding="utf-8"))["match"]
        kickoff = datetime.fromisoformat(str(m["kickoff_utc"]).replace("Z", "+00:00"))
    except (OSError, ValueError, KeyError, TypeError) as err:
        print(f"cannot read {run / 'report.json'}: {err}", file=sys.stderr)
        return 2
    if kickoff > datetime.now(UTC):
        print(f"kickoff {m['kickoff_utc']} is still ahead: this is a post-match review tool (its data holds the result)", file=sys.stderr)
        return 2
    if BLOCK.exists():
        print(f"the scraper is blocked ({BLOCK}): do not fetch, wait", file=sys.stderr)
        return 2
    if LOCK.exists():
        print(f"a scrape is running ({LOCK}): wait for it", file=sys.stderr)
        return 2
    eid = event_id(m)
    if not eid:
        print("the report has no Sofascore event id (source_url / match_id)", file=sys.stderr)
        return 2
    sys.path.insert(0, str(PKG))
    from football.sites import sofascore as ss

    async def fetch() -> dict[str, object]:
        got: dict[str, object] = {}
        async with ss._session_page() as page:
            for part in EVENT_PARTS:
                got[f"event{part.replace('/', '-')}" or "event"] = await ss._fetch_json_optional(page, f"https://www.sofascore.com/api/v1/event/{eid}{part}")
            for name, url in season_urls(got.get("event")):
                got[name] = await ss._fetch_json_optional(page, url)
        return got

    try:
        got = asyncio.run(fetch())
    except Exception as err:                                    # one try only: a block or a hang is never retried
        print(f"fetch failed ({type(err).__name__}: {err}); do not retry", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    saved = []
    for name, data in got.items():
        if data is not None:
            (out / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            saved.append(name)
    print(f"{m.get('home_team')} v {m.get('away_team')}: saved {len(saved)} of {len(got)} ({', '.join(saved)}) -> {out}")
    return 0 if saved else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
