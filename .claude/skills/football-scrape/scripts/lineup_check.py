#!/usr/bin/env python3
"""Fetch the confirmed lineups once, close to kickoff, so the analysis can drop absences that are not real.

    python3 lineup_check.py RUN_DIR             within LINEUP_HOURS of kickoff: ONE Sofascore lineups fetch -> RUN_DIR/lineups.json
    python3 lineup_check.py RUN_DIR --review    after kickoff (a post-match look): -> RUN_DIR/lineups-review.json, never read as pre-match evidence

Lineups are published about 60-75 minutes before kickoff. The report is scraped earlier, so its missing list can hold a
player who starts (Manzambi: "Physical Discomfort (dayToDay)", back 1 Nov in another source, started Villa 2-1 City on
2026-10-24). facts.py prints a CONFIRMED LINEUPS section from lineups.json when it sits beside the report (run_collection
copies the report into RUN_DIR, so put this file there BEFORE the run, or re-run run_collection: it refreshes the evidence).
One browser session, one API call, no retry; it honours the scraper's block marker and lock. Nothing in the run is changed
except the file it writes.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

PKG = Path(__file__).resolve().parent                       # holds football/ (the ported scraping layer)
LINEUP_HOURS = 2.0
WORK = Path(os.environ.get("FOOTBALL_WORK") or Path.cwd())
LOCK, BLOCK = WORK / "output" / ".scrape.lock", WORK / "output" / ".scrape_blocked"


def key(name) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFKD", str(name or "")) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", plain.lower())


def same(a, b) -> bool:
    """One player under two spellings: equal keys, or the same last word and first initial."""
    if key(a) == key(b):
        return True
    pa, pb = str(a or "").split(), str(b or "").split()
    return bool(pa and pb) and key(pa[-1]) == key(pb[-1]) and key(pa[0])[:1] == key(pb[0])[:1]


def event_id(m: dict) -> str | None:
    url = str(m.get("source_url") or "")
    if "sofascore" in url:
        return [p for p in url.split("/") if p][-1].split("#id:")[-1] or None
    return str(m["match_id"]) if str(m.get("match_id") or "").isdigit() else None


def checks(report: dict, sides: dict) -> list[str]:
    """What the confirmed lineups change: listed absentees who start or sit on the bench, regulars left out."""
    m = report.get("match") or {}
    own_home = str((report.get("teamProfile") or {}).get("team_name") or report.get("team") or "").lower() in str(m.get("home_team") or "").lower()
    profiles = {"home": report.get("teamProfile") if own_home else report.get("opponentProfile"),
                "away": report.get("opponentProfile") if own_home else report.get("teamProfile")}
    out = []
    for side in ("home", "away"):
        team, xi, bench = m.get(f"{side}_team"), sides[side]["xi"], sides[side]["bench"]
        if not xi:
            continue
        for x in m.get(f"{side}_missing_players") or []:
            n = (x or {}).get("name")
            if any(same(n, p) for p in xi):
                out.append(f"{team}: {n} was listed missing ({(x or {}).get('description')}) but STARTS: drop that absence")
            elif any(same(n, p) for p in bench):
                out.append(f"{team}: {n} was listed missing ({(x or {}).get('description')}) but is on the BENCH: a part absence at most")
        squad = [p for p in ((profiles[side] or {}).get("squad") or []) if isinstance(p, dict)]
        regulars = sorted(squad, key=lambda p: -(((p.get("recent_usage") or {}).get("total_minutes")) or 0))[:11]
        left = [p["name"] for p in regulars if p.get("name") and ((p.get("recent_usage") or {}).get("total_minutes") or 0) > 0
                and not any(same(p["name"], q) for q in xi)]
        if left:
            out.append(f"{team}: regulars (most minutes lately) NOT in the XI: {', '.join(left)}" + ("; on the bench: " + ", ".join(n for n in left if any(same(n, q) for q in bench)) if any(any(same(n, q) for q in bench) for n in left) else ""))
    return out


def main(argv: list[str]) -> int:
    review = "--review" in argv
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    run = Path(args[0])
    try:
        report = json.loads((run / "report.json").read_text(encoding="utf-8"))
        m = report["match"]
        kickoff = m["kickoff_utc"]
    except (OSError, ValueError, KeyError, TypeError) as err:
        print(f"cannot read {run / 'report.json'}: {err}", file=sys.stderr)
        return 2
    now = datetime.now(UTC)
    left = (datetime.fromisoformat(kickoff.replace("Z", "+00:00")) - now).total_seconds() / 60
    if not review and left <= 0:
        print(f"kickoff {kickoff} has passed: lineups now are not pre-match evidence (use --review for a post-match look)", file=sys.stderr)
        return 2
    if not review and left > LINEUP_HOURS * 60:
        print(f"kickoff is {left / 60:.1f} h away: lineups come out about 60-75 min before kickoff; run this within {LINEUP_HOURS:g} h", file=sys.stderr)
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

    async def fetch():
        async with ss._session_page() as page:
            return await ss._fetch_json_optional(page, f"https://www.sofascore.com/api/v1/event/{eid}/lineups")
    try:
        raw = asyncio.run(fetch())
    except Exception as err:                                    # one try only: a block or a hang is never retried
        print(f"lineups fetch failed ({type(err).__name__}: {err}); do not retry", file=sys.stderr)
        return 1
    if not raw or not (raw.get("home") or {}).get("players"):
        print(f"no lineups published yet for {m.get('home_team')} v {m.get('away_team')} ({round(left)} min before kickoff)", file=sys.stderr)
        return 1
    sides = {}
    for side in ("home", "away"):
        s = raw.get(side) or {}
        sides[side] = {"formation": s.get("formation"),
                       "xi": [p["player"]["name"] for p in s.get("players") or [] if p.get("substitute") is False],
                       "bench": [p["player"]["name"] for p in s.get("players") or [] if p.get("substitute") is True]}
    out = {"confirmed": bool(raw.get("confirmed")), "fetched_at": now.isoformat(timespec="seconds"), "kickoff_utc": kickoff,
           "minutes_before_kickoff": round(left), "home_team": m.get("home_team"), "away_team": m.get("away_team"),
           "home": sides["home"], "away": sides["away"], "checks": checks(report, sides), "source": "Sofascore event lineups"}
    dest = run / ("lineups-review.json" if review else "lineups.json")
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{m.get('home_team')} {sides['home']['formation']} v {m.get('away_team')} {sides['away']['formation']} "
          f"({'confirmed' if out['confirmed'] else 'NOT confirmed'}, {round(left)} min before kickoff) -> {dest}")
    for c in out["checks"]:
        print("  " + c)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
