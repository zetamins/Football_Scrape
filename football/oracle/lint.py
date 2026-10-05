"""Pre-flight check of an opinion file: shows, before the numbers are applied, which factors the engine will accept, which numbers
survive validation (and why not), and whether the advocates cite real tags. Changes nothing.

    python -m football.oracle lint <report.json> <opinion.json> [--with-odds]
"""

from __future__ import annotations

import re
from typing import Any

from . import context, debate
from .facts import extract_facts

LARGE_SINGLE_FACTOR = 3.0
ADVOCATE_MAX_WORDS = 90
ABSENTEE_MAX_POINTS = 3.0
WEAK_MODEL_MAX_POINTS, WEAK_MODEL_MAX_CONFIDENCE = 2.0, 0.4


def _reason(tag_list: list[str], valid: set[str], weak: set[str], effect: Any, with_odds: bool) -> str | None:
    if effect not in context.EFFECTS:
        return f"unknown effect '{effect}' (use {', '.join(context.EFFECTS)})"
    for t in tag_list:
        if t not in valid:
            return f"tag {t} does not exist in the brief"
        if t in context.PRICED_TAGS:
            return f"{t} is already priced by the engine"
        if t in weak:
            return f"{t} is a fringe or unknown-role absentee (worth 0)"
        if with_odds and ".absent." in t:
            return f"{t}: the odds already price known absences"
    return None


def lint_opinion(report: dict, op: dict, use_odds: bool = False) -> dict:
    if not isinstance(op, dict):
        op = {}
    facts = extract_facts(report)
    from . import oracle  # local import: oracle imports this module for the CLI
    b = oracle.brief(report, use_odds=use_odds)
    valid = set(b["tags"])
    weak = context.weak_absence_tags(facts)
    v = context.validate_opinion(op, valid, weak)
    factors = []
    for f in (op.get("factors") or []):
        if not isinstance(f, dict):
            factors.append({"effect": "?", "evidence": "?", "status": "ignored: not an object"})
            continue
        raw = str(f.get("evidence", "")).strip()
        tags = re.findall(r"\[[^\]]+\]", raw) or [f"[{raw}]"]
        why = _reason(tags, valid, weak, f.get("effect"), use_odds)
        factors.append({"effect": f.get("effect"), "evidence": ", ".join(tags), "status": "accepted" if why is None else f"REJECTED: {why}"})
    numbers = []
    for e in context.EFFECTS:
        try:
            stated = float(op.get(e, 0) or 0)
        except (TypeError, ValueError):
            stated = 0.0
        applied = v["adjust"][e]
        bound = context.MAX_DRAW_PCT if e == "draw_bias_pct" else context.MAX_RATE_PCT
        clamped = max(-bound, min(stated, bound))
        n_same = [f for f in factors if f["effect"] == e]
        if not stated:
            note = "hint: a factor cites evidence but this number is 0, so it changes nothing" if any(f["status"] == "accepted" for f in n_same) else "-"
        elif v["confidence"] < context.MIN_CONFIDENCE:
            note = f"ignored: confidence {v['confidence']:.2f} is below {context.MIN_CONFIDENCE:g}"
        elif not any(f["status"] == "accepted" for f in n_same):
            note = f"ignored: no accepted factor with the SAME effect ({e})"
        elif applied != clamped:
            note = "scaled by the share of supported factors"
        elif stated != clamped:
            note = f"clamped to +-{bound:g}"
        elif abs(stated) > LARGE_SINGLE_FACTOR and len(n_same) < 2:
            note = "large for a single factor (typical 1-3)"
        else:
            note = "-"
        numbers.append({"effect": e, "stated": stated, "after_validation": round(applied, 3), "note": note})
    def _num(key):
        try:
            return float(op.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0
    rules: list[str] = []          # skill rules that the engine itself would not reject
    for f in factors:
        if len(re.findall(r"\[[^\]]+\]", f["evidence"])) > 1:
            rules.append(f"factor evidence {f['evidence']} has several tags: ONE tag per factor")
        if ".absent." in f["evidence"] and abs(_num(f["effect"])) > ABSENTEE_MAX_POINTS:
            rules.append(f"{f['evidence']}: an absentee is worth at most +-{ABSENTEE_MAX_POINTS:g} points (you wrote {_num(f['effect']):g})")
    from .lineup import lineup_picture
    pic = lineup_picture(facts)
    for f in factors:
        for tag, side in (("[H.rotation]", "home"), ("[A.rotation]", "away")):
            if tag in f["evidence"] and pic[side]["heavy_rotation"]:
                rules.append(f"{tag}: {facts['sides'][side]['rotation']['changed_players']} starters changed is heavy rotation: mention it, never adjust for it")
    weak = any(x["code"] == "weak_model" for x in b["audit"]["findings"])
    if weak:
        if v["confidence"] > WEAK_MODEL_MAX_CONFIDENCE:
            rules.append(f"weak_model: confidence must be <= {WEAK_MODEL_MAX_CONFIDENCE:g} (you wrote {v['confidence']:g})")
        if any(abs(_num(e)) > WEAK_MODEL_MAX_POINTS for e in context.EFFECTS):
            rules.append(f"weak_model: every adjustment must be within +-{WEAK_MODEL_MAX_POINTS:g}")
    draw_tags = [f["evidence"] for f in factors if f["effect"] == "draw_bias_pct" and f["status"] == "accepted"]
    adv = debate.check_advocates(op.get("advocates"), valid)
    problems: list[str] = []
    if adv is None:
        pass                                          # the engine writes the advocates itself; an opinion may carry only a verdict
    else:
        for k in ("home", "away", "odds_challenge"):
            if k not in adv:
                problems.append(f"advocate '{k}' is missing")
            elif adv[k]["uncited"]:
                problems.append(f"advocate '{k}' cites no [TAG]")
            elif adv[k]["unknown_tags"]:
                problems.append(f"advocate '{k}' cites unknown tags: {', '.join(adv[k]['unknown_tags'])}")
        from . import audit_answer as AA
        for k in ("home", "away", "odds_challenge"):
            if k in adv:
                bad = sorted({m.group(0) for m in AA.SPECULATION.finditer(adv[k]["text"])} | {m.group(0) for m in AA.CHARACTER_WORDS.finditer(adv[k]["text"])})
                if bad:
                    problems.append(f"advocate '{k}' contains guesses or characterising words ({', '.join(repr(b) for b in bad)}): state the tagged number or tag line instead")
        for k in ("home", "away"):
            if k in adv and not adv[k]["uncited"]:
                have = {p["tag"] for p in b["dossier"][k]}
                used = set(adv[k]["tags"])
                if len(have) >= 2 and len(used & have) < 2:
                    problems.append(f"advocate '{k}' uses fewer than two of its side's dossier points ({', '.join(sorted(have)[:3])}): a strong case leads with its two best")
                if len(adv[k]["text"].split()) < 15:
                    problems.append(f"advocate '{k}' is too short to be a case (15+ words: lead, scenario, rebuttal, concession)")
        if not facts["odds"] and adv["verdict"] != "unclear":
            problems.append("no odds in the report: the verdict should be `unclear`")
        if (op.get("advocates") or {}).get("verdict") not in debate.VERDICTS:
            problems.append("verdict is not one of " + " | ".join(debate.VERDICTS) + " (it will be read as `unclear`)")
    if not op.get("data_gaps") and not facts["lineup_confirmed"]:
        problems.append("lineups are unconfirmed but data_gaps does not say so")
    for k in ("home", "away", "odds_challenge"):
        text = (op.get("advocates") or {}).get(k) if isinstance(op.get("advocates"), dict) else None
        if isinstance(text, str) and len(text.split()) > ADVOCATE_MAX_WORDS:
            problems.append(f"advocate '{k}' has {len(text.split())} words (the limit is {ADVOCATE_MAX_WORDS})")
    problems += rules
    for ev in draw_tags:
        if not re.search(r"\.stakes\]|\.table\]|\[VENUE\]|\[REFEREE\]|\.manager\]", ev):
            problems.append(f"draw adjustment cites {ev}: the skill allows draw bias only for a table scenario where a draw suits both, a dead rubber or a clearly defensive matchup")
    ok = not problems and all(f["status"] == "accepted" for f in factors) and all(n["note"] == "-" or n["note"].startswith("hint:") for n in numbers)
    return {"home": facts["home"], "away": facts["away"], "factors": factors, "numbers": numbers, "advocate_problems": problems, "confidence": v["confidence"], "clean": ok}


def format_lint(r: dict) -> str:
    lines = [f"# Opinion lint: {r['home']} v {r['away']} (confidence {r['confidence']:.2f})", "", "## Factors", "| Effect | Evidence | Status |", "|---|---|---|"]
    lines += [f"| {f['effect']} | {f['evidence']} | {f['status']} |" for f in r["factors"]] or ["| - | - | no factors (valid: zero is the expected answer) |"]
    lines += ["", "## Numbers", "| Effect | Stated | After validation | Note |", "|---|---|---|---|"]
    lines += [f"| {n['effect']} | {n['stated']:g} | {n['after_validation']:g} | {n['note']} |" for n in r["numbers"]]
    lines += ["", "## Advocates"] + ([f"- {p}" for p in r["advocate_problems"]] or ["- ok"])
    lines += ["", "Result: " + ("clean, ready to apply" if r["clean"] else "fix the items above, then apply (a lone reviewer's adjustment is halved by the engine)")]
    return "\n".join(lines)
