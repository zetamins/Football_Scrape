---
name: football-scrape
description: Run the football scraping layer for ONE team and get its match report JSON (fixtures, lineups, injuries, referee, odds, standings, form, xG, H2H) from up to 13 public sources, or reuse a saved report. Self-contained port of backend/football with a guarded runner (one live run, no retry after a hang or 403). Use it before the football-match-lite / football-match-collection analysis when no fresh report exists.
---

# Football scrape

The scraping layer is ported into this skill: `scripts/football/` is a copy of `backend/football` (the package the Android app embeds), `data/` holds the seed caches and trained seed files, `scripts/scrape.py` is the safe runner. Install with `pip install -r requirements.txt` (Python 3.11+, `httpx[http2]`, and `playwright` plus `playwright install chromium`). Without playwright the run still works but Sofascore (the base source: lineups, referee, odds, standings), Squawka and worldfootball are skipped, so the report is thinner. The folder is portable: copy it anywhere; only `sync_from_backend.py` needs the original repo.

## Run it
```
python3 scripts/scrape.py "Greece"             # reuse a report younger than 6 h (no network), else ONE live run
python3 scripts/scrape.py --list [Team]        # saved reports, newest first
python3 scripts/scrape.py --status report.json # which sources worked, what is missing
python3 scripts/closing_odds.py RUN_DIR        # within 3 h of kickoff: ONE fetch of the market price -> RUN_DIR/closing_odds.json (score.py's closing line value)
python3 scripts/lineup_check.py RUN_DIR    # within 2 h of kickoff (lineups come out ~60-75 min before): ONE Sofascore lineups fetch -> RUN_DIR/lineups.json; facts.py then prints CONFIRMED LINEUPS (listed absentees who start, regulars left out). Re-run run_collection afterwards: it refreshes the evidence. --review after kickoff writes lineups-review.json (never used as pre-match evidence)
python3 scripts/event_raw.py RUN_DIR [OUT_DIR] # AFTER the match only: Sofascore's raw post-match data (event, statistics, incidents, lineups with player stats, shotmap, best players, both teams' season statistics) -> RUN_DIR/review-raw/; a review aid, never pre-match evidence (set FOOTBALL_RAW_DIR on a scrape to keep its raw responses too)
```
Flags: `--max-age-hours N`, `--timeout S` (default 900), `--force` (ignore the age and the block marker). Run from the folder where `output/` should live (or set `FOOTBALL_WORK`); set `FOOTBALL_PYTHON` to an interpreter that has httpx. It prints `report: <path>` and a source table; pass that path on as the report for the analysis skills.

## Rules (they protect the sources; the runner enforces most of them)
1. One team per run, one live run at a time (lock file). Sources are sequential and block-sensitive.
2. Check `--list` first: reuse a saved report whenever it is recent enough. Ask the user before a live run unless they already asked for one.
3. Never retry after a hang, timeout or 403/429. The runner writes `output/.scrape_blocked` and refuses another live run for 1 h; tell the user, reuse a saved report, wait.
4. A match already played needs a report saved before kickoff; a fresh scrape returns the finished match.
5. The CLI also appends to `output/prediction-log.jsonl` (the engine's own log, not an analysis answer). No keys or cookies are read or printed.

## Keeping the port in step
The copy is generated, not edited: change `backend/football`, then run `python3 scripts/sync_from_backend.py` (`--check` lists any difference; the test suite runs it). Left out on purpose: `android_*.py` (Android only) and `oracle/` (the engine, not scraping).

## Exact comparison: record and replay
`FOOTBALL_RECORD=cassette.json` on a live run saves every HTTP response and browser call; `FOOTBALL_REPLAY=cassette.json` re-runs offline from it (no network, politeness pauses skipped, a call that was never recorded fails). Run the same cassette through two copies of the code and diff the JSON: the only difference should be `generatedAt`. Use a scratch working folder (`FOOTBALL_WORK`) so the test adds nothing to `output/` or the prediction log. A cassette is large (about 80 MB for one match): keep it out of git.
