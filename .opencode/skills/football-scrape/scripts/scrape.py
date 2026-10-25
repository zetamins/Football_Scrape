#!/usr/bin/env python3
"""Run the football scraping layer once, safely, and hand back the report path.

    python3 scrape.py "Greece"                 reuse a saved report younger than --max-age-hours, else ONE live run
    python3 scrape.py "Greece" --force         ignore the age and the block marker (one live run)
    python3 scrape.py --list [Team]            saved reports, newest first (no network)
    python3 scrape.py --status report.json     which sources worked, what is missing (no network)

The live run is `football.cli` (a ported copy of backend/football, the package the Android app embeds) started
from the current folder (or $FOOTBALL_WORK) with the ported copy in ./football on PYTHONPATH, so it writes output/<team>-<time>.json and .md. Rules this wrapper enforces:
one live run at a time (lock file), never a retry after a hang or a 403 (a block marker stops the next run for
BLOCK_HOURS unless --force), a hard timeout, and no key or cookie is read or printed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

PKG = Path(__file__).resolve().parent                       # holds football/ (the ported scraping layer); seeds sit in ../data
WORK = Path(os.environ.get("FOOTBALL_WORK") or Path.cwd())  # the CLI writes WORK/output/<team>-<time>.json
OUT = WORK / "output"
LOCK, BLOCK = OUT / ".scrape.lock", OUT / ".scrape_blocked"
BLOCK_HOURS = 1.0
BLOCK_WORDS = re.compile(r"\b403\b|forbidden|cloudflare|captcha|too many requests|\b429\b", re.I)


def slug(name: str) -> str:
    try:
        sys.path.insert(0, str(PKG))
        from football.format_markdown import slugify
        return slugify(name)
    except Exception:                                       # noqa: BLE001 - fall back to a plain slug
        return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def reports(team: str | None = None) -> list[Path]:
    pat = f"{slug(team)}-*.json" if team else "*-*T*.json"
    return sorted((p for p in OUT.glob(pat) if re.search(r"\d{4}-\d\d-\d\dT", p.name)), key=lambda p: p.stat().st_mtime, reverse=True)


def reusable(path: Path, max_age_hours: float) -> bool:
    """A saved report is reused only when it was GENERATED within the age limit (its own generatedAt, not the file time: a copied
    or edited file looks new) and its match has not kicked off yet (a report of a match already started cannot predict it)."""
    import datetime
    try:
        r = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    def when(x):
        try:
            v = datetime.datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        except ValueError:
            return None
        return v if v.tzinfo else v.replace(tzinfo=datetime.timezone.utc)
    made = when(r.get("generatedAt")) if isinstance(r, dict) else None
    age = (now - made).total_seconds() / 3600 if made else (time.time() - path.stat().st_mtime) / 3600
    kick = when(((r.get("match") or {}) if isinstance(r, dict) else {}).get("kickoff_utc"))
    return age <= max_age_hours and (kick is None or kick > now)


def status(path: Path) -> int:
    r = json.loads(path.read_text(encoding="utf-8"))
    m = r.get("match") or {}
    print(f"{path.name}: {m.get('home_team')} v {m.get('away_team')}, {m.get('competition')}, kickoff {m.get('kickoff_utc')}, status {m.get('status')}")
    print("| source | fixtures | error | skipped |\n|---|---|---|---|")
    for s in r.get("sources") or []:
        err = s.get("matches_error") or s.get("details_error") or s.get("profile_error") or ""
        print(f"| {s.get('source')} | {s.get('fixtures_scraped')} | {str(err)[:60]} | {s.get('skipped')} |")
    comp = r.get("dataCompleteness")
    if comp:
        print("completeness:", json.dumps(comp, default=str)[:400])
    return 0


def live(team: str, timeout: int) -> int:
    OUT.mkdir(exist_ok=True)
    if LOCK.exists():
        try:
            os.kill(int(LOCK.read_text().strip()), 0)
            print(f"a scrape is already running (pid {LOCK.read_text().strip()}): wait for it, do not start another", file=sys.stderr)
            return 3
        except (OSError, ValueError):
            LOCK.unlink(missing_ok=True)                    # stale lock from a dead process
    py = os.environ.get("FOOTBALL_PYTHON") or sys.executable            # an interpreter that has httpx[http2]
    if subprocess.run([py, "-c", "import httpx, h2"], capture_output=True).returncode != 0:
        print(f'{py} lacks httpx: run  pip install "httpx[http2]"  or set FOOTBALL_PYTHON to an interpreter that has it (playwright is optional, for the real-browser sources)', file=sys.stderr)
        return 5
    cmd = [py, "-m", "football.cli", team]
    env = {**os.environ, "PYTHONPATH": str(PKG) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    log = OUT / f".scrape-{slug(team)}.log"
    before = {p for p in OUT.glob("*.json")}
    with open(log, "wb") as sink:
        proc = subprocess.Popen(cmd, cwd=WORK, env=env, stdout=sink, stderr=subprocess.STDOUT)
        LOCK.write_text(str(proc.pid))
        start, why = time.monotonic(), ""
        try:
            while proc.poll() is None:
                time.sleep(5)
                if time.monotonic() - start > timeout:
                    why = f"timeout after {timeout}s"
                    proc.send_signal(signal.SIGTERM)
                    try:
                        proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    break
        finally:
            LOCK.unlink(missing_ok=True)
    tail = log.read_text(encoding="utf-8", errors="replace")[-4000:]
    new = sorted((p for p in OUT.glob("*.json") if p not in before and re.search(r"\d{4}-\d\d-\d\dT", p.name)), key=lambda p: p.stat().st_mtime, reverse=True)
    if not why and proc.returncode != 0:
        why = f"exit {proc.returncode}"
    if not why and BLOCK_WORDS.search(tail) and not new:
        why = "the site answered 403/blocked"
    if why or not new:
        BLOCK.write_text(f"{time.time():.0f} {why or 'no report written'}\n")
        print(f"scrape FAILED ({why or 'no report written'}); log {log}. Do NOT retry: wait at least {BLOCK_HOURS:g} h, or reuse a saved report (--list).", file=sys.stderr)
        return 1
    BLOCK.unlink(missing_ok=True)
    print(f"report: {new[0]}")
    return status(new[0])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("team", nargs="?", help="one team name (one team per run)")
    ap.add_argument("--max-age-hours", type=float, default=6.0)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--status", metavar="REPORT")
    a = ap.parse_args(argv)
    if a.status:
        return status(Path(a.status))
    if a.list:
        for p in reports(a.team)[:20]:
            print(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))}  {p}")
        return 0
    if not a.team or "," in a.team:
        print('give exactly one team: scrape.py "Greece" (batches would send many requests at once)', file=sys.stderr)
        return 2
    have = reports(a.team)
    if have and not a.force and reusable(have[0], a.max_age_hours):
        print(f"reusing saved report (no network): {have[0]}")
        return status(have[0])
    if BLOCK.exists() and not a.force:
        stamp, _, why = BLOCK.read_text().partition(" ")
        left = BLOCK_HOURS - (time.time() - float(stamp)) / 3600
        if left > 0:
            print(f"last live run failed ({why.strip()}); not retrying for {left:.1f} h. Reuse a saved report (--list) or pass --force.", file=sys.stderr)
            return 4
    return live(a.team, a.timeout)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
