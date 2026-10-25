#!/usr/bin/env python3
"""Runs the football collection on ONE report, saving every step to a markdown file so that a silent death or a timeout never loses work (Python standard library only).

    python3 run_collection.py report.json RUN_DIR [--model opencode/mimo-v2.6-flash-free] [--runner opencode] [--retries 2] [--timeout 1500] [--no-media] [--no-advocates] [--independent] [--review] [--dry-run]

Steps (with --review, two independent reviewers then check the answer and the decider fixes what is real; the council of seven advocates (home, away, draw, goals, underdog, state, chaos; no market advocate: the skill is market-independent) sits between the specialists and the decider; each one is skipped when its file already exists and passes its check, so re-running the same command RESUMES after a crash):
  1. prepare : RUN_DIR/evidence/<slice>.md written by facts.py (no model; the sheet is saved to disk, never pasted through a prompt)
  2. specialists : RUN_DIR/notes/<name>.md  (team-news, tactical-matchup, underlying-stats, context-motivation, media-scout) checked by note_check.py
  3. decider : RUN_DIR/decision.md (numbers and reasoning written FIRST) then RUN_DIR/answer.md, checked by check.py
Every step is logged in RUN_DIR/status.md. A step that ends without its file (a silent death) is retried up to --retries times, told which files already exist.
"""

from __future__ import annotations

import argparse
import re
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent.parent                               # .../skills
PROJECT = SKILLS.parent.parent                            # the folder holding .claude / .opencode: the models look their skills up from their working folder
LITE = SKILLS / "football-match-lite" / "scripts"
SPECIALISTS = [("team-news", "football-team-news", "team-news"), ("tactical-matchup", "football-tactical-matchup", "tactical"),
               ("underlying-stats", "football-underlying-stats", "stats"), ("context-motivation", "football-context-motivation", "context"),
               ("media-scout", "football-media-scout", None)]
EVIDENCE = ["team-news", "tactical", "stats", "context", "advocate", "home", "away", "draw", "goals", "underdog", "state", "chaos", "decider"]
ADVOCATES = [("home", "football-home-advocate"), ("away", "football-away-advocate"), ("draw", "football-draw-advocate"), ("goals", "football-goals-advocate"), ("underdog", "football-underdog-advocate"), ("state", "football-gamestate-advocate"), ("chaos", "football-chaos-advocate")]


def capture_on() -> bool:
    """The full stream of each claude step is kept by default so the run can be audited; FOOTBALL_CAPTURE=0 turns it off."""
    return os.environ.get("FOOTBALL_CAPTURE", "1") != "0"


def stamp_value(answer: Path, value_md: Path) -> None:
    """Add the market comparison to the end of the finished answer so a reader does not see 'Value: UNMEASURED / no odds' beside a value.md that found odds. The analysis above it is not touched."""
    try:
        lines = value_md.read_text(encoding="utf-8").strip().splitlines()
        keep = [ln for ln in lines if ln.startswith(("Final pick:", "Stake decision:"))] or lines[:1]
        board = [ln for ln in lines if ln.startswith("final pick:")]                   # the market scoreboard line for the final pick (reference only)
        first = " | ".join(keep + [f"scoreboard (reference only): {board[0]}"] if board else keep)
        text = answer.read_text(encoding="utf-8")
    except (OSError, IndexError):
        return
    if "Market comparison after the run" not in text:
        answer.write_text(text.rstrip("\n") + "\n\nMarket comparison after the run (value.py, replaces any 'no odds' / 'UNMEASURED' above; the analysis was written without odds): " + first + "\n", encoding="utf-8")


SOURCE_DENY = ("Read(**/scripts/*.py)", "Bash(cat *scripts/*.py*)", "Bash(python3 *open(*)", "Bash(python3 *sys.path*)", "Bash(python3 *importlib*)",
               *(f"Bash(python3 *import {m}*)" for m in ("calc", "facts", "check", "value", "score", "blind", "media", "advocate_check")),
               *(f"Bash(python3 *from {m} import*)" for m in ("calc", "facts", "check", "value", "score")))     # a hard block, not just an audit flag: no step may read a script's source or call its functions with its own numbers (the deciders of Villa r5/r6, Hull and Man Utd read check.py); tested 2026-10-25: Read, cat and python3 -c open/import are denied, `python3 -c "print(72 - 56.3)"` still runs. Patterns use "python3 *" (not "python3 -c *") so `python3 - <<EOF ... open(...) EOF` (stdin heredoc) and `python3 script.py ... open(...)` are covered too, not just -c (closed 2026-10-25, was an open gap in lessons.md)
MARKET_LEAK = re.compile(r"(?:_odds|odds_|fair_pct|implied_pct|market_implied)[\"']?\s*[:=]\s*\d|\b(?:odds|price|tip)\b[^\n]{0,25}?\b\d{1,2}/\d{1,2}\b|\b\d{1,2}/\d{1,2}\b[^\n]{0,25}?\b(?:odds|favourites?|to win|to edge)\b|\bcf\.?\s*\d\.\d|"
                         r"\bprediction:\s*\d{1,2}/\d{1,2}", re.I)    # a price in what an agent read (JSON odds fields, fractional or decimal odds in a headline): the blind run saw the market


def stream_audit(run: Path) -> list[str]:
    """Capture mode only: scan the saved stream of every step for rule breaks. Flags (1) reading a script's source (SKILL: never), (2) running calc.py from python with the agent's own numbers (a what-if probe), (3) a read or cat of another run's folder or of an earlier answer, (4) an advocate reading another advocate's brief, (5) odds-looking words in a read of the sheet, (6) market data (a price) in anything any step read -- unconditional, no exception (there is no market advocate any more). Returns the findings; also writes them to audit.md."""
    out: list[str] = []
    seen = re.findall(r"/output/([^/\s\"']+)/", " ".join(lp.read_text(encoding="utf-8", errors="replace") for lp in (run / "logs").glob("*.log")))
    own = max(set(seen), key=seen.count) if seen else run.name        # a run renamed after the fact still shows its old name in its own paths
    for lp in sorted((run / "logs").glob("*.log")):
        step = lp.stem
        for line in lp.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            msg = rec.get("message") if isinstance(rec, dict) else None
            if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
                continue
            for c in msg["content"]:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    body = c.get("content") if isinstance(c.get("content"), str) else json.dumps(c.get("content"))
                    hit = MARKET_LEAK.search(body or "")
                    if hit and f"{step}: saw market data" not in " ".join(out):
                        out.append(f"{step}: saw market data, the analysis is not market-independent ({hit.group(0)[:80]!r})")
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                inp = c.get("input") or {}
                text = inp.get("file_path") or inp.get("command") or ""
                if c.get("name") == "Read" and re.search(r"/scripts/[^/]+\.py$", text) or re.search(r"\b(cat|head|tail|sed|less)\b[^|;&]*/scripts/[^\s|;&]+\.py", text):
                    out.append(f"{step}: read a script's source ({text[:90]})")
                if re.search(r"import (calc|facts|check)\b|from (calc|facts|check) import", text):
                    out.append(f"{step}: ran a script's functions from python with its own numbers ({text[:70]!r})")
                if re.search(r"/output/(?!%s\b)[^/\s]+/(answer|decision)\.md" % re.escape(own), text) or "run.log" in text:
                    out.append(f"{step}: looked at another run or a log ({text[:90]})")
                if step.startswith("advocate-"):
                    me = step.split("-", 1)[1].split("-")[0]
                    for other in re.findall(r"advocates/(\w+)\.md", text):
                        if other != me and c.get("name") == "Read":
                            out.append(f"{step}: read the {other} advocate's brief")
    (run / "audit.md").write_text("# Stream audit\n" + ("\n".join("- " + o for o in out) if out else "no rule breaks found") + "\n", encoding="utf-8")
    return out


def log(run: Path, text: str) -> None:
    with open(run / "status.md", "a", encoding="utf-8") as fh:
        fh.write(f"- {datetime.datetime.now(datetime.timezone.utc):%H:%M:%S} {text}\n")


def prepare(report: Path, run: Path, py: str = sys.executable) -> list[str]:
    """Write the evidence slices to disk. Returns the slices written (skips the ones that exist)."""
    (run / "evidence").mkdir(parents=True, exist_ok=True)
    done = []
    for name in EVIDENCE:
        out = run / "evidence" / f"{name}.md"
        if out.exists() and out.stat().st_size > 200 and out.stat().st_mtime >= max(report.stat().st_mtime, (LITE / "facts.py").stat().st_mtime, ((run / "lineups.json").stat().st_mtime if (run / "lineups.json").exists() else 0)):
            continue                                       # fresh: newer than the report and than facts.py (a stale slice would feed the specialists old numbers)
        r = subprocess.run([py, str(LITE / "facts.py"), str(report), "--section", name], capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and r.stdout.strip():
            out.write_text(r.stdout, encoding="utf-8")
            done.append(name)
        else:
            log(run, f"prepare {name} FAILED: {r.stderr.strip()[:120]}")
    return done


def note_ok(note: Path, report: Path, py: str = sys.executable) -> bool:
    if not note.exists():
        return False
    return subprocess.run([py, str(LITE / "note_check.py"), str(note), str(report)], capture_output=True, text=True, timeout=60).returncode == 0


def advocate_ok(brief: Path, report: Path, side: str, py: str = sys.executable) -> bool:
    if not brief.exists():
        return False
    return subprocess.run([py, str(LITE / "advocate_check.py"), str(brief), str(report), side], capture_output=True, text=True, timeout=60).returncode == 0


def answer_ok(answer: Path, report: Path, py: str = sys.executable) -> bool:
    if not answer.exists():
        return False
    r = subprocess.run([py, str(LITE / "check.py"), str(answer), str(report)], capture_output=True, text=True, timeout=120)
    return r.returncode == 0


def decision_ok(decision: Path) -> bool:
    """decision.md counts as finished when it holds the calculator output (the line 'Expected goals (final): ...') and a bet."""
    try:
        t = decision.read_text(encoding="utf-8")
    except OSError:
        return False
    return len(t) > 300 and bool(re.search(r"Expected goals \(final\)", t)) and bool(re.search(r"\bbet\b", t, re.I))


STAMPED = ("facts.py", "calc.py", "check.py", "note_check.py", "advocate_check.py", "review.py", "blind.py", "value.py")


def code_stamp() -> str:
    """A short hash of the scripts that shape the evidence and the checks: it tells a resumed run whether its saved files were made under older rules."""
    import hashlib
    h = hashlib.sha1()
    for n in STAMPED:
        try:
            h.update((LITE / n).read_bytes())
        except OSError:
            h.update(b"missing:" + n.encode())
    for extra in [Path(__file__).resolve(), *sorted(SKILLS.glob("football-*/SKILL.md"))]:          # the runner and the skill wording shape the briefs too
        try:
            h.update(extra.read_bytes())
        except OSError:
            h.update(b"missing:" + extra.name.encode())
    return h.hexdigest()[:12]


def check_stamp(run: Path) -> str:
    """Compare with run/version.txt: 'new', 'same' or 'changed' (then the saved notes, decision and answer predate the current rules). Always writes the current stamp."""
    f, now = run / "version.txt", code_stamp()
    old = f.read_text(encoding="utf-8").strip() if f.exists() else ""
    f.write_text(now + "\n", encoding="utf-8")
    return "new" if not old else "same" if old == now else "changed"


def run_model(runner: str, model: str, prompt: str, timeout: int, done=None, grace: int = 20, poll: int = 10, log_path: Path | None = None, files: list | None = None) -> int:
    """Run one model step and keep its output in `log_path`. `done()` says whether the step's file already exists and passes its check: the runner then waits
    `grace` seconds and stops the process, because a finished model often lingers until the timeout (measured: 15+ minutes lost per match)."""
    import time
    sink = open(log_path, "ab") if log_path else subprocess.DEVNULL
    try:
        if Path(runner).name == "codex":                                           # codex has no -f: name the attached files in the message instead
            note = "".join(f"\nRead this file first: {f}" for f in (files or []))
            cmd = [runner, "exec", "--skip-git-repo-check", "--sandbox", "workspace-write"] + ([] if model.startswith("opencode/") else ["-m", model]) + [prompt + note]
        elif Path(runner).name == "claude":                                        # the Claude Code CLI (`--runner claude --model haiku`): one headless turn, files named in the message
            note = "".join(f"\nRead this file first: {f}" for f in (files or []))
            cmd = [runner, "-p", prompt + note, "--model", model, "--permission-mode", "acceptEdits", "--allowedTools", "Read", "Write", "Edit", "Bash(python3:*)", "Bash(ls:*)", "Bash(cat:*)",
                   "--disallowedTools", *SOURCE_DENY]
            if capture_on():                                                       # audit on by default for the claude runner (FOOTBALL_CAPTURE=0 turns it off): every message, tool call and thinking block of the step goes to the log as JSON lines
                cmd += ["--output-format", "stream-json", "--verbose"]
        else:
            cmd = [runner, "run", "-m", model, prompt] + [x for f in (files or []) for x in ("-f", str(f))]            # the message first, then the attached files
        proc = subprocess.Popen(cmd, stdout=sink, stderr=subprocess.STDOUT, cwd=PROJECT)       # a run started from another folder (e.g. output/) otherwise left codex unable to find the skills
    except FileNotFoundError:
        return 127
    start, finished_at = time.monotonic(), None
    try:
        while proc.poll() is None:
            time.sleep(poll if timeout > poll else 0.05)
            if done is not None and finished_at is None and done():
                finished_at = time.monotonic()
            if finished_at is not None and time.monotonic() - finished_at >= grace:
                _stop(proc)
                return 0
            if time.monotonic() - start >= timeout:
                _stop(proc)
                return 124
        return proc.returncode
    finally:
        if log_path:
            sink.close()


def _stop(proc) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


REVIEWERS = ["opencode/longcat-2.5-preview-free", "opencode/nemotron-3-ultra-free"]


def verdict_ok(path: Path) -> bool:
    """A reviewer's file counts only when its first non-empty line is VERDICT: PASS or VERDICT: FIX."""
    try:
        first = next((ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()), "")
    except OSError:
        return False
    return bool(re.match(r"VERDICT:\s*\**\s*(PASS|FIX)\b", first, re.I))


def verdict_of(path: Path) -> str:
    m = re.match(r"VERDICT:\s*\**\s*(PASS|FIX)\b", next((ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()), ""), re.I)
    return m.group(1).upper() if m else ""


def reviewer_prompt(run: Path, verdict: Path) -> str:
    return (f"The attached file is a review pack. Follow its instructions exactly: you are the reviewer and you did not write the answer. Write your verdict to {verdict}: the first line must be 'VERDICT: PASS' "
            f"or 'VERDICT: FIX', then numbered errors, each quoting the answer sentence and the sheet line that contradicts it. Write the file as soon as you have your findings. Read no other file.")


def fixer_prompt(report: Path, run: Path, existing: list[str]) -> str:
    resume = f" Files that already exist: {', '.join(existing)}." if existing else ""
    return (f"Use the football-match-lite skill in collection mode. Report: {report}. Run dir: {run}. Independent reviewers checked {run}/answer.md; their verdicts are in {run}/review/ (verdict-*.txt). "
            f"For EVERY numbered error in them: check it against {run}/evidence/ and {run}/notes/; if it is real, correct the sentence in {run}/answer.md (and recompute with calc.py if a number that drives the probabilities was wrong); "
            f"if it is wrong, leave the answer alone and write the reason in {run}/review/rejected.md. When done write {run}/review/fixed.md listing each error as FIXED or REJECTED with a one-line reason, then run check.py on the answer and fix every FAIL. "
            f"Do not read any file outside this project.{resume}")


def specialist_prompt(skill: str, name: str, report: Path, run: Path, evidence: str | None, existing: list[str]) -> str:
    src = f"The evidence is saved in {run}/evidence/{evidence}.md: READ THAT FILE (do not run facts.py again)." if evidence else "Run the media script as the skill says."
    resume = f" Files that already exist: {', '.join(existing)}; do only what is missing." if existing else ""
    return (f"Use the {skill} skill. Report: {report}. Run dir: {run}. {src} Write the note to {run}/notes/{name}.md FIRST (write the file as soon as you have your findings), "
            f"then check it with note_check.py as the skill says. Do not read any file outside this project and never read other notes or answers.{resume}")


def advocate_existing(run: Path, side: str) -> list[str]:
    """The files an advocate is told already exist: the notes and its OWN brief only (naming the other advocates' briefs invites reading them)."""
    return [f"notes/{p.name}" for p in (run / "notes").glob("*.md")] + [f"advocates/{p.name}" for p in (run / "advocates").glob("*.md") if p.stem == side]


def advocate_prompt(skill: str, side: str, report: Path, run: Path, existing: list[str]) -> str:
    resume = f" Files that already exist: {', '.join(existing)}; do only what is missing." if existing else ""
    return (f"Use the {skill} skill. Report: {report}. Run dir: {run}. Read every note in {run}/notes/, {run}/evidence/advocate.md and {run}/evidence/{side}.md (counts of how the games go, the weaknesses of the other side and the links between the sides, computed for your case). Write your brief to {run}/advocates/{side}.md as soon as you have the case, "
            f"then check it with advocate_check.py as the skill says. Do not read any file outside this project and never read the other advocate's brief or earlier answers.{resume}")


def decider_prompt(report: Path, run: Path, existing: list[str], step: str = "both", blind: bool = False) -> str:
    """step 'decision' = write decision.md only; 'answer' = write answer.md from an existing decision.md; 'both' = the old single pass."""
    resume = f" Files that already exist: {', '.join(existing)}; do only the missing step." if existing else ""
    head = (f"Use the football-match-lite skill in collection mode. Report: {report}. Run dir: {run}. Read {run}/evidence/decider.md, every note in {run}/notes/ and, if they exist, the advocate briefs in {run}/advocates/ (the council: weigh the home, away, draw, goals, underdog and state cases (the underdog advocate says whether the weaker side scores and whether the favourite then still wins, only draws or loses; the state advocate reads how the game swings: who leads first, whether the leader holds, whether the trailer comes back and how the defence and the shapes cope under pressure; the chaos advocate argues what the forecast cannot see (errors, keepers, set pieces and penalties, cards) and whether it widens the draw or the underdog: weigh it for the pick type and the Draw cover, never for expected goals), say which wins and why; the goals case argues over/under 2.5 or both teams to score and becomes the main bet only if its direction beats the best 1X2 or double-chance pick; it is always the separate Goals bet). ")
    s1 = (f"Step 1: " + ("you have NO bookmaker odds and must not look for any: you are an independent analyst like a real bettor who sets their own price from the match evidence, and a script compares your answer with the market only after you are done (write Value: UNMEASURED, the checker expects it). Start from the RATING ANCHOR line in decider.md when it has one (the two clubs' class plus the venue edge; it scored about like the bookmaker on held-out matches), otherwise from the xG anchor with the venue edge; the other anchor is the cross-check. " if blind else "") + f"If decider.md has bookmaker odds, START from the market-implied expected goals (calc.py --market H D A --over25 O) and move away only for named evidence (a move over 0.25 needs an 'Expected goals adjustment:' line; calc.py --market H D A --lam LH LA reports your move); otherwise start from the xG anchor (the SHRUNK xG block in decider.md has it, already pulled toward the mean for small samples). Re-add every note's arithmetic before accepting its delta. Weigh factors by size: venue/travel and the rating gap are large, recent form a quarter to a third of that, rest days, tenure and rotation about an eighth each. If the sheet shows STALE REPORT or LATE-NEWS WINDOW, confidence cannot be high. "
          f"Set your expected goals with calc.py and WRITE {run}/decision.md (anchor, each note's xG change accepted or rejected with a one-line reason, final expected goals, the calculator output verbatim, the pick (ALWAYS give one, never refuse), the edge and its Value label REAL/THIN/NONE/UNMEASURED, and 'Evidence the market lacks:' if REAL). ")
    s2 = (f"Step 2: write {run}/answer.md in the compact template from decision.md, run check.py on it and fix every FAIL. Always give the pick and a Value: line (never a PASS). When decider.md has odds it also has a CHALLENGE THE MARKET block: the odds anchor your expected goals, but you may challenge them, so write the `Market challenge:` line (the outcome where the data differs most, the gap, the strongest evidence, kept or moved and by how much). The pick is your most likely outcome or, only when a numbered fact backs it in a `Why a double chance:` line, a double chance covering it; a goals bet when its probability beats the best 1X2 or double-chance pick: never chase an edge with a weaker bet. Do NOT save or log any prediction (no --log). ")
    tail = f"Write the files yourself now: nobody will reply, so never ask for approval or confirmation. Do not read any file outside this project and never read earlier answers.{resume}"
    if step == "decision":
        return head + s1 + f"Then STOP: do not write answer.md in this step. " + tail
    if step == "answer":
        return head + f"{run}/decision.md is already written and final: do NOT redo the analysis, read it. " + s2 + tail
    return head + s1 + s2 + tail


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report")
    ap.add_argument("run_dir")
    ap.add_argument("--model", default="opencode/mimo-v2.6-flash-free")
    ap.add_argument("--runner", default="opencode")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=1500)
    ap.add_argument("--review", action="store_true", help="after the answer passes, have independent reviewers check it and the decider fix what is real")
    ap.add_argument("--reviewers", default=",".join(REVIEWERS), help="comma separated reviewer models (two different ones by default)")
    ap.add_argument("--no-advocates", action="store_true", help="skip the advocates (no council)")
    ap.add_argument("--no-media", action="store_true", help="skip the media scout (always use this for a match that is already played)")
    ap.add_argument("--independent", action="store_true", help="(always on; kept so old commands still work) every agent works from a copy with the bookmaker prices removed; value.py prints a market scoreboard afterwards, reference only")
    ap.add_argument("--market-anchor", action="store_true", help=argparse.SUPPRESS)          # removed 2026-10-25: the skill is market-independent; refused below
    ap.add_argument("--dry-run", action="store_true", help="prepare the evidence files and print the plan, run no model")
    a = ap.parse_args(argv)
    if a.market_anchor:
        print("--market-anchor was removed (2026-10-25): the skill is market-independent, no agent may see a price", file=sys.stderr)
        return 2
    a.independent = True                                   # always odds-free: no agent sees a price
    report, run = Path(a.report).resolve(), Path(a.run_dir).resolve()
    if not report.exists():
        print(f"no such report: {report}", file=sys.stderr)
        return 2
    (run / "notes").mkdir(parents=True, exist_ok=True)
    (run / "logs").mkdir(parents=True, exist_ok=True)
    odds_report = None                                     # the original report with its odds: only value.py reads it, after the answer is final
    if a.independent:
        odds_report = run.parent / f"{run.name}.odds.json"
        if report.parent != run:
            odds_report.write_bytes(report.read_bytes())   # keep the original OUTSIDE the run dir, where no agent looks
        elif not odds_report.exists():
            log(run, f"WARNING: --independent on a report inside the run folder and no {odds_report.name}: the odds copy is lost, so value.py is skipped")
            odds_report = None
        stale = run / "advocates" / "market.md"
        if stale.exists():                                  # a brief from an earlier odds run holds the price: move it out of the agents' reach
            stale.rename(run.parent / f"{run.name}.market-brief-with-odds.md")
            log(run, "moved advocates/market.md (written with odds) out of the run folder for the odds-free run")
        sys.path.insert(0, str(LITE))
        import blind as _blind
        cleaned, removed = _blind.blind(json.loads((odds_report or report).read_text(encoding="utf-8")))
        copy = run / "report.json"
        copy.write_text(json.dumps(cleaned, ensure_ascii=False), encoding="utf-8")
        report = copy
    elif report.parent != run:                             # check.py finds the notes next to the report, so the report must live in the run dir
        copy = run / "report.json"
        copy.write_bytes(report.read_bytes())
        report = copy
    log(run, f"start {report.name} ({a.runner}, model {a.model if a.model != ap.get_default('model') or Path(a.runner).name != 'codex' else 'its own default'})")
    stamp = check_stamp(run)
    if stamp == "changed":
        log(run, "WARNING: the skill scripts changed since this run started: saved notes, decision.md and answer.md were made under older rules (delete them to redo; the answer is re-checked below under the new rules)")
    written = prepare(report, run)
    log(run, f"prepare: wrote {', '.join(written) or 'nothing new (resuming)'}")
    plan = [(n, s, ev) for n, s, ev in SPECIALISTS if not (a.no_media and n == "media-scout")]
    if a.dry_run:
        council = [] if a.no_advocates else [side for side, _ in ADVOCATES]
        steps = [", ".join(n for n, _, _ in plan)] + (["council (" + ", ".join(council) + ")"] if council else []) + ["decider"] + (["review"] if a.review else [])
        print("plan:", " -> ".join(steps) + "; evidence in", run / "evidence")
        return 0
    for name, skill, ev in plan:
        note = run / "notes" / f"{name}.md"
        for attempt in range(1, a.retries + 2):
            if note_ok(note, report):
                log(run, f"{name}: note ok" + (f" (attempt {attempt - 1})" if attempt > 1 else " (already there)" if attempt == 1 and not written else ""))
                break
            existing = [p.name for p in (run / "notes").glob("*.md")] + [p.name for p in (run / "evidence").glob("*.md")]
            code = run_model(a.runner, a.model, specialist_prompt(skill, name, report, run, ev, existing), a.timeout, done=lambda note=note: note_ok(note, report), log_path=run / "logs" / f"{name}.log")
            log(run, f"{name}: attempt {attempt} ended (exit {code}); note {'ok' if note_ok(note, report) else 'MISSING or failing'}")
        else:
            log(run, f"{name}: gave up after {a.retries + 1} attempts")
    if not a.no_advocates:
        (run / "advocates").mkdir(parents=True, exist_ok=True)
        for side, skill in ADVOCATES:
            brief = run / "advocates" / f"{side}.md"
            for attempt in range(1, a.retries + 2):
                if advocate_ok(brief, report, side):
                    log(run, f"advocate {side}: brief ok" + (f" (attempt {attempt - 1})" if attempt > 1 else ""))
                    break
                existing = advocate_existing(run, side)
                code = run_model(a.runner, a.model, advocate_prompt(skill, side, report, run, existing), a.timeout, done=lambda brief=brief, side=side: advocate_ok(brief, report, side), log_path=run / "logs" / f"advocate-{side}.log")
                log(run, f"advocate {side}: attempt {attempt} ended (exit {code}); brief {'ok' if advocate_ok(brief, report, side) else 'MISSING or failing'}")
            else:
                log(run, f"advocate {side}: gave up after {a.retries + 1} attempts")
    answer = run / "answer.md"
    decision = run / "decision.md"
    for attempt in range(1, a.retries + 2):                # step 1: decision.md (the checkpoint), saved before the answer is attempted
        if answer_ok(answer, report) or decision_ok(decision):
            break
        existing = [p.name for p in run.glob("*.md") if p.name != "status.md"] + [f"notes/{p.name}" for p in (run / "notes").glob("*.md")]
        code = run_model(a.runner, a.model, decider_prompt(report, run, existing, "decision", a.independent), a.timeout, done=lambda: decision_ok(decision), log_path=run / "logs" / "decider-decision.log")
        log(run, f"decider step 1: attempt {attempt} ended (exit {code}); decision.md {'ok' if decision_ok(decision) else 'MISSING or incomplete'}")
    for attempt in range(1, a.retries + 2):                # step 2: answer.md from decision.md
        if answer_ok(answer, report):
            log(run, "decider: answer.md passes the checker")
            break
        existing = [p.name for p in run.glob("*.md") if p.name != "status.md"] + [f"notes/{p.name}" for p in (run / "notes").glob("*.md")]
        step = "answer" if decision_ok(decision) else "both"
        code = run_model(a.runner, a.model, decider_prompt(report, run, existing, step, a.independent), a.timeout, done=lambda: answer_ok(answer, report), log_path=run / "logs" / "decider.log")
        log(run, f"decider step 2: attempt {attempt} ended (exit {code}); decision.md {'there' if decision.exists() else 'MISSING'}, answer {'passes' if answer_ok(answer, report) else 'MISSING or failing'}")
    if not answer_ok(answer, report):
        log(run, "decider: gave up (the files written so far are kept)")
    if a.review and answer_ok(answer, report):
        rdir = run / "review"
        rdir.mkdir(parents=True, exist_ok=True)
        if not (rdir / "pack.txt").exists() or (rdir / "pack.txt").stat().st_mtime < answer.stat().st_mtime:
            pk = subprocess.run([sys.executable, str(LITE / "review.py"), str(answer), str(report)], capture_output=True, text=True, timeout=180)
            (rdir / "pack.txt").write_text(pk.stdout, encoding="utf-8")
            for old_v in rdir.glob("verdict-*.txt"):
                old_v.unlink()                                  # a verdict on an older answer is stale
            for stale in ("fixed.md", "rejected.md"):
                if (rdir / stale).exists():
                    (rdir / stale).unlink()
        for k, model in enumerate([x.strip() for x in a.reviewers.split(",") if x.strip()], 1):
            vfile = rdir / f"verdict-{k}.txt"
            for attempt in range(1, a.retries + 2):
                if verdict_ok(vfile):
                    log(run, f"review {k} ({model}): {verdict_of(vfile)}" + (f" (attempt {attempt - 1})" if attempt > 1 else ""))
                    break
                code = run_model(a.runner, model, reviewer_prompt(run, vfile), a.timeout, done=lambda vfile=vfile: verdict_ok(vfile), log_path=run / "logs" / f"review-{k}.log", files=[rdir / "pack.txt"])
                log(run, f"review {k} ({model}): attempt {attempt} ended (exit {code}); verdict {'ok' if verdict_ok(vfile) else 'MISSING (provider error or silent end)'}")
            else:
                log(run, f"review {k} ({model}): gave up after {a.retries + 1} attempts")
        verdicts = [v for v in sorted(rdir.glob("verdict-*.txt")) if verdict_ok(v)]
        errors = [v for v in verdicts if verdict_of(v) == "FIX"]
        if errors and not (rdir / "fixed.md").exists():
            for attempt in range(1, a.retries + 2):
                existing = [f"review/{q.name}" for q in rdir.glob("*") if q.is_file()]
                code = run_model(a.runner, a.model, fixer_prompt(report, run, existing), a.timeout, done=lambda: (rdir / "fixed.md").exists() and answer_ok(answer, report), log_path=run / "logs" / "fix.log")
                log(run, f"fix: attempt {attempt} ended (exit {code}); fixed.md {'there' if (rdir / 'fixed.md').exists() else 'MISSING'}, answer {'passes' if answer_ok(answer, report) else 'FAILING'}")
                if (rdir / "fixed.md").exists() and answer_ok(answer, report):
                    break
        log(run, f"review done: {len(verdicts)} verdict(s), {len(errors)} asked for a fix")
    if a.runner == "claude" and capture_on():
        found = stream_audit(run)
        log(run, f"stream audit: {len(found)} finding(s), see audit.md" if found else "stream audit: no rule breaks found")
    if odds_report is not None and answer_ok(answer, report):
        vr = subprocess.run([sys.executable, str(LITE / "value.py"), str(answer), str(odds_report), str(run / "value.md")], capture_output=True, text=True, timeout=60)
        log(run, vr.stdout.strip() or "value.py: no output")
        stamp_value(answer, run / "value.md")
    print((run / "status.md").read_text(encoding="utf-8"))
    return 0 if answer_ok(answer, report) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
