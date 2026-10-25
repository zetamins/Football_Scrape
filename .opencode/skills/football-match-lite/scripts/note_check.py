#!/usr/bin/env python3
"""Mechanical checker for a specialist note (Python standard library only).

    python3 note_check.py notes/team-news.md report.json

A specialist writes ONE short note in a fixed format. This checks the format and the hard rules; it does not judge the football.
Rules: every field present; favours home|away|neutral; strength 0-3; confidence low|medium|high; xG deltas between -0.60 and +0.60 with arithmetic shown;
a finding for BOTH sides (length is free: as thorough as the evidence needs); the match line equals the report's teams; no bookmaker odds, probabilities or bets (that is the decider's job).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

FIELDS = ("specialist", "match", "favours", "strength", "confidence", "xg_delta_home", "xg_delta_away", "arithmetic", "home", "away", "uncertain")
FORBIDDEN = re.compile(r"\b(bookmakers?|odds|probabilit\w+|best bet|value bet)\b|\bstak(?:e|es|ing)\s+(?:\d|on\b|of \d|size|plan)|\b(?:your|the|a) stake (?:should|would)\b|\b\d+(?:\.\d+)?\s*%\s*(?:chance|probability|to win)", re.I)      # a stat like '18% win rate' is fine


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


REPLACEMENT_LINE = re.compile(r"^\s*[^:\n]+: ([^(\n]+?) \([^\n]*?=> (WEAK replacement|comparable replacement|uncertain replacement)", re.M)
CLAIMS_NONE = re.compile(r"unreplaced|no replacement|no cover\b|nobody (?:to )?(?:replace|cover)|weak (?:replacement|cover|stand-in)|irreplaceable|no natural replacement|no like-for-like", re.I)
CLAIMS_COVERED = re.compile(r"comparable (?:replacement|cover)|like-for-like|well covered|ample cover|equal replacement|covered comparably", re.I)


def replacement_contradictions(text: str, sheet_text: str) -> list[str]:
    """Sentences that call a replacement weak or missing when the sheet's ABSENCES line says it is comparable, or the reverse. Matches on the player's surname."""
    verdicts = {}
    for name, verdict in REPLACEMENT_LINE.findall(sheet_text or ""):
        words = [w for w in re.findall(r"[^\W\d_]{4,}", name)]
        if words:
            verdicts[words[-1].lower()] = (name.strip(), verdict)
    out = []
    for sentence in re.split(r"(?<=[.;])\s+|\n", text or ""):
        low = sentence.lower()
        for sur, (name, verdict) in verdicts.items():
            if sur in low:
                if verdict == "comparable replacement" and CLAIMS_NONE.search(sentence):
                    out.append(f"{name}: the sheet says a comparable replacement exists, but: '{sentence.strip()[:110]}'")
                elif verdict == "WEAK replacement" and CLAIMS_COVERED.search(sentence):
                    out.append(f"{name}: the sheet says the replacement is WEAK, but: '{sentence.strip()[:110]}'")
    return out


def _sheet_text(report_path: str) -> str:
    import contextlib
    import importlib.util
    import io
    try:
        spec = importlib.util.spec_from_file_location("facts_for_checks2", Path(__file__).with_name("facts.py"))
        facts = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(facts)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            facts.main(report_path, deep=True)
        return buf.getvalue()
    except Exception:                                                          # noqa: BLE001
        return ""


ARITH = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:[x×*/÷+]|\s-\s|−)\s*(\d+(?:\.\d+)?)(?![\w.]*\s*(?:%|ppg|km))")


def unknown_operands(text: str, known: set[str]) -> list[str]:
    """Operands of a visible calculation (a x b, a / b, a + b) that are not in the sheet, a note or a brief, and not a result shown earlier ('= n'). The results after '=' are free."""
    if not known:
        return []
    results = set(re.findall(r"=\s*(\d+(?:\.\d+)?)", text))
    bad = []
    for a, b in ARITH.findall(text):
        for n in (a, b):
            if len(n.replace(".", "")) >= 2 and n not in known and n.lstrip("0") not in known and n not in results and n.rstrip("0").rstrip(".") not in known:
                bad.append(n)
    return sorted(set(bad))


SUM_LINE = re.compile(r"(?<![\w.])([+\-−]?\d+(?:\.\d+)?(?:\s+[+\-−]\s+\d+(?:\.\d+)?)+)\s*=\s*([+\-−]?\d+(?:\.\d+)?)(?![\d.]*\s*%)")


def broken_sums(text: str) -> list[tuple[str, float, float]]:
    """Visible sums 'a + b - c = d' whose total is wrong by more than 0.015 (the decider re-adds every note; a sum that does not add up is a reason to reject its delta)."""
    out = []
    for expr, res in SUM_LINE.findall(text or ""):
        parts = re.findall(r"([+\-−]?)\s*(\d+(?:\.\d+)?)", expr.replace("−", "-"))
        total = 0.0
        for i, (sign, num) in enumerate(parts):
            total += -float(num) if sign == "-" else float(num)
        got = float(res.replace("−", "-"))
        if abs(total - got) > 0.015:
            out.append((expr.strip() + " = " + res, round(total, 3), got))
    return out


def norm(x) -> str:
    return re.sub(r"\W", "", str(x or "").lower())


def parse(text: str) -> dict:
    """Read 'field: value' lines, tolerating the markdown models like to add (bold, backticks, bullets, quotes) and Windows line endings."""
    out: dict = {}
    for ln in text.replace("\r", "").splitlines():
        ln = re.sub(r"^[\s>*_`'\"-]+", "", ln)                                  # leading bullets, quotes, bold markers
        m = re.match(r"^([A-Za-z_]+)[*_`'\"]*\s*:\s*[*_`'\"]*\s*(.*)$", ln)
        key = m.group(1).lower() if m else ""
        if m and key in FIELDS and key not in out:
            out[key] = re.sub(r"[*_`]+$", "", m.group(2).strip()).strip()
    return out


def check(note_text: str, report_path: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    add = lambda s, n, d="": rows.append((s, n, d))
    f = parse(note_text)
    missing = [k for k in FIELDS if not f.get(k)]
    add("FAIL" if missing else "ok", "every field is present", ", ".join(missing))
    if missing:
        return rows
    try:
        rep = json.loads(Path(report_path).read_text(encoding="utf-8"))
        m = rep.get("match") if isinstance(rep.get("match"), dict) else {}
        home, away = str(m.get("home_team") or ""), str(m.get("away_team") or "")
    except (OSError, ValueError):
        home = away = ""
    ok_match = bool(home) and norm(home) in norm(f["match"]) and norm(away) in norm(f["match"])
    add("ok" if ok_match else "FAIL", "the match line names both teams of the report", f"'{f['match']}' v {home} / {away}")
    f["favours"] = f["favours"].strip(" .,;").lower()
    add("ok" if f["favours"] in ("home", "away", "neutral") else "FAIL", "favours is home, away or neutral", f["favours"])
    f["strength"] = f["strength"].strip(" .,;")
    st = re.fullmatch(r"[0-3]", f["strength"])
    add("ok" if st else "FAIL", "strength is a whole number 0 to 3", f["strength"])
    f["confidence"] = f["confidence"].strip(" .,;").lower()
    add("ok" if f["confidence"] in ("low", "medium", "high") else "FAIL", "confidence is low, medium or high", f["confidence"])
    deltas = []
    for k in ("xg_delta_home", "xg_delta_away"):
        try:
            v = float(f[k].replace("+", "").replace(",", ".").strip(" .;"))
        except ValueError:
            add("FAIL", f"{k} is a number", f[k])
            continue
        deltas.append(v)
        add("ok" if abs(v) <= 0.6 else "FAIL", f"{k} stays within +-0.60", f"{v:+.2f}")
        if "context" in f["specialist"].lower():
            add("ok" if abs(v) <= 0.2 else "FAIL", f"{k} stays within +-0.20 (context moves expected goals by at most 0.20 a side)", f"{v:+.2f}")
    _anc = re.search(r"(?:[^.\n]|\.(?=\d))*(?<!sheet's )(?<!sheet's venue-)\b(?:(?:adjusted|new|my|revised) anchors?\s*(?:[:=]|are|become|now)\s*(?:home\s*)?\d|adjusted (?:home|away)\s+(?:about\s+|to\s+)?\d|result\s+\d\.\d+\s*(?:v|vs|-|/)\s*\d\.\d+)(?:[^.\n]|\.(?=\d))*", note_text, re.I)
    add("FAIL" if _anc else "ok", "the note gives deltas, not its own anchors (the decider owns the numbers)", f"'{_anc.group(0).strip()[:100]}'" if _anc else "")
    if any(abs(v) > 0 for v in deltas):
        add("ok" if re.search(r"\d", f["arithmetic"]) and len(f["arithmetic"].split()) >= 4 else "FAIL", "a non-zero xG change shows its arithmetic", f["arithmetic"][:80])
    for side, team in (("home", home), ("away", away)):
        n = len(f[side].split())
        add("ok" if n >= 8 else "FAIL", f"the {side} finding says something concrete (8 words or more)", f"{n} words")
    bad_ops = unknown_operands(" ".join(f.get(k, "") for k in ("home", "away", "uncertain", "arithmetic")), _sheet_numbers(report_path))
    add("FAIL" if len(bad_ops) > 3 else "WARN" if bad_ops else "ok", "the operands of every calculation are in the sheet", f"not found: {', '.join(bad_ops)} (a calculation built on a number the sheet does not hold)" if bad_ops else "")
    contra = replacement_contradictions(" ".join(f.get(k, "") for k in ("home", "away")), _sheet_text(report_path))
    add("WARN" if contra else "ok", "replacement claims agree with the sheet", "; ".join(contra[:2]))
    bad_nums = unsupported_numbers(" ".join(f.get(k, "") for k in ("home", "away", "uncertain")), f.get("arithmetic", ""), _sheet_numbers(report_path))
    add("FAIL" if len(bad_nums) > 3 else "WARN" if bad_nums else "ok", "every number in the findings is in the sheet or shown in the arithmetic", f"not found: {', '.join(bad_nums)} (quote the sheet's figures; an invented or mis-copied number reaches the decider)" if bad_nums else "")
    sums = broken_sums(" ".join(f.get(k, "") for k in ("arithmetic", "home", "away", "uncertain")))
    add("FAIL" if sums else "ok", "every sum in the note adds up", "; ".join(f"{e} (really {t:+.2f})" for e, t, _ in sums[:3]) + ": re-add it, the decider will not trust the delta" if sums else "")
    inv = re.search(r"[^.\n]*\bassum(?:ed|ing|e)\b[^.\n]{0,40}?\d+\.\d+[^.\n]*", note_text, re.I) or re.search(r"[^.\n]*\b(?:is|are|was) (?:a|just a) guess\b[^.\n]*", note_text, re.I)
    add("WARN" if inv else "ok", "no move is priced on an assumed or guessed number", f"use the sheet or 0.00 ('{inv.group(0).strip()[:100]}')" if inv else "")
    bad = FORBIDDEN.search(note_text)
    add("FAIL" if bad else "ok", "no bookmaker odds, probabilities or bets (the decider's job)", bad.group(0) if bad else "")
    return rows


def main(note_path: str, report_path: str) -> int:
    try:
        text = Path(note_path).read_text(encoding="utf-8")
    except OSError as e:
        print(f"cannot read the note: {e}", file=sys.stderr)
        return 2
    rows = check(text, report_path)
    print("| Status | Check | Detail |\n|---|---|---|")
    for s, n, d in rows:
        if s != "ok":
            print(f"| {s} | {n} | {d} |")
    fails = sum(1 for r in rows if r[0] == "FAIL")
    print(f"\nResult: {'clean' if not fails else 'fix the FAIL rows and run again'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python3 note_check.py note.md report.json", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:]))
