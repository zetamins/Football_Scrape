#!/usr/bin/env python3
"""Mechanical checker for an advocate brief (Python standard library only).

    python3 advocate_check.py advocates/home.md report.json home      (side: home, away, draw, goals, underdog, state or chaos)

An advocate argues the strongest honest case for ONE side, from the specialist notes and the sheet slice. The brief has a fixed format. This checks the format and the
hard rules; it does not judge the football. Rules: every field present; the side and team match the report; the case says something concrete (25 words or more); 3 to 8 evidence items, each
with a number (4 or more for the draw, goals, underdog, state and chaos advocates, whose brief must link signals); a rebuttal to the other side's best argument; one thing to verify; no
bookmaker odds, probabilities or bets (there is no market advocate any more: every side is price-free).
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

FIELDS = ("advocate", "team", "case", "evidence", "must_overcome", "rebuttal", "verify")
FORBIDDEN = re.compile(r"\b(bookmakers?|odds|probabilit\w+|best bet|value bet)\b|\bstak(?:e|es|ing)\s+(?:\d|on\b|of \d|size|plan)|\b(?:your|the|a) stake (?:should|would)\b|\b\d+(?:\.\d+)?\s*%\s*(?:chance|probability|to win)", re.I)


def _sheet_numbers(report_path: str) -> set[str]:
    """Every number the facts sheet and the report hold (plus the same values in millions or thousands): what a specialist may quote."""
    import contextlib
    import importlib.util
    import io
    out: set[str] = set()
    try:
        spec = importlib.util.spec_from_file_location("facts_for_checks", Path(__file__).with_name("facts.py"))
        facts = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(facts)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            facts.main(report_path, deep=True)
        text = buf.getvalue() + " " + Path(report_path).read_text(encoding="utf-8")
    except Exception:                                                          # noqa: BLE001 - no sheet, no number check
        return out
    out = set(re.findall(r"(?<![\w.])\d+(?:\.\d+)?", text))
    for n in list(out):
        try:
            v = float(n)
        except ValueError:
            continue
        out |= {n.lstrip("0") or "0", n.rstrip("0").rstrip(".") if "." in n else n}
        if v >= 1e5:
            for div in (1e6, 1e3):
                out |= {f"{v / div:.{k}f}".rstrip("0").rstrip(".") if k else f"{v / div:.0f}" for k in (0, 1, 2, 3)}
    return out


def unsupported_numbers(claims: str, shown: str, known: set[str]) -> list[str]:
    """Numbers (2+ digits) in `claims` that are neither in the sheet nor in the `shown` arithmetic text. Empty when no sheet could be built."""
    if not known:
        return []
    allowed = known | set(re.findall(r"(?<![\w.])\d+(?:\.\d+)?", shown))
    bad = []
    for n in re.findall(r"(?<![\w.])\d+(?:\.\d+)?", claims):
        if len(n.replace(".", "")) >= 2 and n not in allowed and n.lstrip("0") not in allowed and n.rstrip("0").rstrip(".") not in allowed and not re.fullmatch(r"20\d\d", n):
            bad.append(n)
    return sorted(set(bad))


def norm(x) -> str:
    return re.sub(r"\W", "", str(x or "").lower())


def parse(text: str) -> dict:
    """Read 'field: value' lines (a value may continue on following lines until the next field), tolerating markdown."""
    out: dict = {}
    cur = None
    for ln in text.replace("\r", "").splitlines():
        clean = re.sub(r"^[\s>*_`'\"-]+", "", ln)
        m = re.match(r"^([A-Za-z_]+)[*_`'\"]*\s*:\s*[*_`'\"]*\s*(.*)$", clean)
        if m and m.group(1).lower() in FIELDS and m.group(1).lower() not in out:
            cur = m.group(1).lower()
            out[cur] = re.sub(r"[*_`]+$", "", m.group(2).strip()).strip()
        elif cur and ln.strip():
            out[cur] = (out[cur] + " " + ln.strip(" -*")).strip()
    return out


def check(text: str, report_path: str, side: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    add = lambda s, n, d="": rows.append((s, n, d))
    f = parse(text)
    missing = [k for k in FIELDS if not f.get(k)]
    add("FAIL" if missing else "ok", "every field is present", ", ".join(missing))
    if missing:
        return rows
    try:
        m = json.loads(Path(report_path).read_text(encoding="utf-8")).get("match") or {}
        h, a = str(m.get("home_team") or ""), str(m.get("away_team") or "")
    except (OSError, ValueError, AttributeError):
        h = a = ""
    add("ok" if f["advocate"].strip(" .").lower() == side else "FAIL", f"the advocate field says {side}", f["advocate"])
    if side in ("draw", "goals", "underdog", "state", "chaos"):
        add("ok" if h and a and norm(h) in norm(f["team"]) and norm(a) in norm(f["team"]) else "FAIL", "the match line names both teams of the report", f"'{f['team']}' v {h} / {a}")
    else:
        team = h if side == "home" else a
        add("ok" if team and norm(team) in norm(f["team"]) else "FAIL", "the team is the report's side", f"'{f['team']}' v {team}")
    n = len(f["case"].split())
    add("ok" if n >= 25 else "FAIL", "the case says something concrete (25 words or more)", f"{n} words")
    items = [x.strip() for x in re.split(r"\s*(?:;|\|\||\n|\b\d\)|(?<=\.)\s+(?=[A-Z]))\s*", f["evidence"]) if x.strip()]
    withnum = [x for x in items if re.search(r"\d", x)]
    need = 4 if side in ("draw", "goals", "underdog", "state", "chaos") else 3
    add("ok" if need <= len(withnum) <= 8 else "FAIL", f"{need} or more evidence items, each with a number", f"{len(withnum)} items with a number")
    for k in ("must_overcome", "rebuttal", "verify"):
        add("ok" if len(f[k].split()) >= 4 else "FAIL", f"{k} says something concrete", f"{len(f[k].split())} words")
    notes_dir = Path(report_path).parent / "notes"
    from_notes = " ".join(n.read_text(encoding="utf-8") for n in sorted(notes_dir.glob("*.md"))) if notes_dir.exists() else ""
    bad_nums = unsupported_numbers(" ".join(f.get(k, "") for k in ("case", "evidence", "must_overcome", "rebuttal")), from_notes, _sheet_numbers(report_path))
    add("FAIL" if len(bad_nums) > 3 else "WARN" if bad_nums else "ok", "every number is in the sheet or in a specialist note", f"not found: {', '.join(bad_nums)}" if bad_nums else "")
    if side == "underdog":
        routes = ("underdog blanked", "underdog scores, favourite wins", "underdog scores, draw", "underdog wins")
        got = [x for x in routes if x in re.sub(r"\s+", " ", f["case"].lower())]
        add("ok" if got else "FAIL", "the case starts with one route: " + " / ".join(x.upper() for x in routes), got[0].upper() if got else "none of the four routes named")
        add("ok" if re.search(r"error", f["case"] + " " + f["evidence"], re.I) else "FAIL", "the defensive errors are part of the case", "" if re.search(r"error", f["case"] + " " + f["evidence"], re.I) else "no mention of the favourite's defensive errors")
    if side == "state":
        routes = ("first goal decides", "comeback", "swing", "stalemate")
        got = [x for x in routes if x in re.sub(r"\s+", " ", f["case"].lower())]
        add("ok" if got else "FAIL", "the case starts with one route: " + " / ".join(x.upper() for x in routes), got[0].upper() if got else "none of the four routes named")
        ok_und = re.search(r"underdog", f["case"], re.I)
        add("ok" if ok_und else "FAIL", "the case names the underdog's path to the lead", "" if ok_und else "the word underdog is not in the case")
        ok_def = re.search(r"defen[cs]", f["case"] + " " + f["evidence"], re.I)
        add("ok" if ok_def else "FAIL", "the defence under pressure is part of the case (errors, shape or back line)", "" if ok_def else "no mention of the defence")
    if side == "chaos":
        routes = ("error swing", "keeper swing", "set-piece swing", "discipline swing", "low chaos")
        got = [x for x in routes if x in re.sub(r"\s+", " ", f["case"].lower())]
        add("ok" if got else "FAIL", "the case starts with one route: " + " / ".join(x.upper() for x in routes), got[0].upper() if got else "none of the five routes named")
        near_exposed = lambda team: bool(team) and bool(re.search(rf"{re.escape(team)}[^.\n]{{0,60}}\bexpos|\bexpos[^.\n]{{0,60}}{re.escape(team)}", f["case"], re.I))
        ok_side = near_exposed(h) or near_exposed(a)
        add("ok" if ok_side else "FAIL", "the case names the side more exposed to chaos", "" if ok_side else "no team name appears near 'exposed' in the case (a name mentioned only in a rebuttal or comparison clause does not count)")
        ok_eff = re.search(r"\b(draw|underdog|favourite|favorite)\b", f["case"], re.I)
        add("ok" if ok_eff else "FAIL", "the case says whether chaos widens the draw, the underdog or the favourite", "" if ok_eff else "no draw / underdog / favourite effect named")
        moves = re.search(r"expected goals?\s+(?:up|down|by|to|from|\+|-)|\bxg\s*[+-]\s*\d|\b[+-]\d\.\d+\s*(?:goals|xg)\b"
                          r"|\b(?:price[sd]?|rate[sd]?|value[sd]?|push(?:es|ed)?|moves?|moved|shifts?|shifted|cuts?|raises?|lowers?|sets?)\b[^.\n]{0,50}\b(?:attack|defen[cs]e|total)\b[^.\n]{0,20}\b(?:at|to|up to|down to)\s+\d+\.\d{1,2}\b",
                          text, re.I)
        add("FAIL" if moves else "ok", "no expected-goals move (chaos argues a route only)", moves.group(0) if moves else "")
    bad = FORBIDDEN.search(text)
    add("FAIL" if bad else "ok", "no bookmaker odds, probabilities or bets (the decider's job)", bad.group(0) if bad else "")
    return rows


def main(path: str, report_path: str, side: str) -> int:
    if side not in ("home", "away", "draw", "goals", "underdog", "state", "chaos"):
        print("side must be home, away, draw, goals, underdog, state or chaos", file=sys.stderr)
        return 2
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        print(f"cannot read the brief: {e}", file=sys.stderr)
        return 2
    rows = check(text, report_path, side)
    print("| Status | Check | Detail |\n|---|---|---|")
    for s, n, d in rows:
        if s != "ok":
            print(f"| {s} | {n} | {d} |")
    fails = sum(1 for r in rows if r[0] == "FAIL")
    print(f"\nResult: {'clean' if not fails else 'fix the FAIL rows and run again'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("usage: python3 advocate_check.py brief.md report.json home|away|draw|goals|underdog|state|chaos", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:]))
