#!/usr/bin/env python3
"""Builds a review pack for a SEPARATE reviewer (Python standard library only): the facts sheet, your answer, a checklist and a sentence table that pairs each sentence of
your answer with the lines of the sheet that share its numbers and names. A reviewer who did not write the answer ticks every row.

    python3 review.py answer.md report.json > pack.txt     (a forecasts.jsonl as a third argument is optional)
"""

from __future__ import annotations

import io
import re
import sys
import contextlib
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("facts", HERE / "facts.py")
facts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(facts)

CHECKLIST = """You are the REVIEWER, not the author. You did not write this answer. Read the ANSWER against the SHEET (the report's facts) and report every error. Do not rewrite the answer and do not run other tools.

Rules to apply:
- Facts from the report must be exact: numbers, counts, names, dates, scorelines, who played at home or away in a past match, which side a statistic belongs to. A less negative xG or goal difference is BETTER. Expected goals are not "an edge".
- The CALCULATOR OUTPUT block is the author's own calc.py run: the answer's probabilities, scorelines and own odds must equal it; the expected goals themselves and any estimate such as 'this player is worth 0.2 xG' are judgements and must be labelled as estimates, never called 'confirmed' or 'the report shows'.\n- Opinion and own knowledge must be kept apart from facts and labelled; never accept an invented competition fact (a round, other teams' points, a result the sheet does not show).
- A claim about what the bookmaker or the market "has not adjusted for", "ignores" or "underweights" is a claim about the market, not about the match: it needs evidence the market lacks, or it is an error.
- A number called lucky or unsustainable for one side must be treated the same for the other side. Per-game figures, not totals, when sample sizes differ.
- Check the internal consistency: the same fact must not appear twice with different values; a result must not be called a win and a draw; the best bet, its probability and its confidence must agree with the rest of the answer (HIGH confidence needs about 70% and a named edge); both cases must be argued fairly.
- Check venues and orientation of past matches against the sheet's result rows ("home"/"away" there is that team's venue) and the recent meetings (home team first).
- Analyst judgement is allowed and wanted (who looks stronger, how a side is likely to play, what a matchup implies) as long as it reads as the analyst's own judgement or is tied to a number; flag only claims presented as REPORT facts that the sheet does not show, invented specifics (named tactics, players' roles or injuries, results, competition facts) and judgements that contradict the sheet.

Method (do not skip): go through the SENTENCE TABLE row by row, S1, S2, ... and for each row compare the sentence with its EVIDENCE lines; if the sheet has no support for a factual claim, mark it. Only after the last row, write the reply.

Reply in exactly this form:
VERDICT: PASS   (only if you found nothing)
or
VERDICT: FIX
1. "<exact quote>" -> problem -> the correct fact from the sheet (quote the line)
2. ...
Keep it under 300 words and list only wrong rows."""


def sheet_of(report_path: str, deep: bool = True) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        facts.main(report_path, deep=deep)
    return buf.getvalue()


def tokens(sentence: str) -> tuple[set[str], set[str]]:
    nums = {n for n in re.findall(r"(?<![\w.])\d+(?:\.\d+)?", sentence) if len(n.replace(".", "")) >= 2}
    names = {w for w in re.findall(r"\b[A-ZÀ-Ý][\wÀ-ÿ'’-]{3,}\b", sentence)}
    return nums, names


def sentence_table(sheet: str, answer: str, limit: int = 120) -> str:
    lines = [ln.strip() for ln in sheet.splitlines() if ln.strip()]
    rows, n = [], 0
    for para in answer.splitlines():
        if not para.strip() or set(para.strip()) <= set("|-: "):
            continue
        for sent in re.split(r"(?<=[\w\]%)])\.\s+(?=[A-Z\[(])|;\s+", para):
            sent = sent.strip(" |*#-")
            if len(sent) < 25:
                continue
            nums, names = tokens(sent)
            ev = []
            for ln in lines:
                score = sum(1 for x in nums if re.search(rf"(?<![\w.]){re.escape(x)}(?![\w.]*\d)", ln)) * 2 + sum(1 for w in names if w in ln)
                if score >= 2 and len(ev) < 300:
                    ev.append((score, ln[:170]))
            ev = [e for _, e in sorted(ev, key=lambda t: -t[0])[:2]]
            n += 1
            rows.append(f"S{n}. \"{sent[:280]}\"\n    EVIDENCE: " + (" || ".join(ev) if ev else "NO MATCHING SHEET LINE (check that this is opinion or derived, and labelled)"))
            if n >= limit:
                return "\n".join(rows)
    return "\n".join(rows)


def calculator_block(report_path: str, log_path: str | None, answer: str = "") -> str:
    """The author's own calc.py output for the logged forecast, so the reviewer can verify probabilities, scorelines and odds that are not in the sheet."""
    import json
    spec2 = importlib.util.spec_from_file_location("calc", HERE / "calc.py")
    calc = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(calc)
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        m = report.get("match") if isinstance(report.get("match"), dict) else {}
        norm = lambda x: re.sub(r"\W", "", str(x or "").lower())
        entries = [json.loads(x) for x in Path(log_path).read_text(encoding="utf-8").splitlines() if x.strip()] if log_path else []
        mine = [e for e in entries if norm(e.get("home")) == norm(m.get("home_team")) and norm(e.get("away")) == norm(m.get("away_team"))]
        if mine:
            e = mine[-1]
        else:                                    # no saved forecast: rebuild the calculator numbers from the answer's own headline
            xg = re.search(r"expected goals (\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", answer, re.I)
            e = {"home": m.get("home_team"), "away": m.get("away_team"), "lam_home": float(xg.group(1)), "lam_away": float(xg.group(2)), "bet": "(read from the answer)"}
    except (OSError, ValueError, IndexError, AttributeError):
        return "(no calculator output: the answer has no 'expected goals X-Y' in its headline and no log was given)"
    a = calc.analyse(e["lam_home"], e["lam_away"])
    rec = calc.recommend(a, e.get("home") or "Home", e.get("away") or "Away")
    pct = lambda x: f"{100 * x:.1f}"
    return "\n".join([f"The author's chosen expected goals: {e['lam_home']} - {e['lam_away']} (a judgement, not a sheet figure).",
                      f"calc.py results for them: home {pct(a['home'])}% / draw {pct(a['draw'])}% / away {pct(a['away'])}%; over 2.5 {pct(a['over_2_5'])}%; both teams to score {pct(a['btts'])}%.",
                      "likeliest scores: " + ", ".join(f"{sc} ({pct(p)}%)" for sc, p in a["top_scores"]) + "; drawn scores: " + ", ".join(f"{k} {pct(v)}%" for k, v in a["draw_scores"].items()),
                      f"own fair odds: home {1 / a['home']:.2f}, draw {1 / a['draw']:.2f}, away {1 / a['away']:.2f}; logged bet: {e.get('bet')}; calc.py's suggestion: {rec['selection']} ({rec['pct']}%).",
                      "These come from the author's own calc.py run: they are not report facts, but the percentages, scorelines and odds in the answer must equal them. Expected goals and any estimate of a player's value to the team are judgements and must be labelled as such, never called 'confirmed'."])


def main(answer_path: str, report_path: str, log_path: str | None = None, short: bool = False) -> int:
    try:
        answer = Path(answer_path).read_text(encoding="utf-8")
        sheet = sheet_of(report_path, deep=not short)
    except (OSError, ValueError) as e:
        print(f"cannot build the pack: {e}", file=sys.stderr)
        return 2
    parts = [CHECKLIST] + (["=== SHEET OMITTED (short pack): judge each sentence by its EVIDENCE lines in the table below; a sentence with NO evidence line carrying its numbers is an unsupported claim ==="] if short else ["=== SHEET ===", sheet])
    calc_text = calculator_block(report_path, log_path, answer)
    if calc_text:
        parts += ["=== CALCULATOR OUTPUT (the author's own calc.py run) ===", calc_text]
    parts += ["=== ANSWER ===", answer.strip(), "=== SENTENCE TABLE (tick every row) ===", sentence_table(sheet + "\n" + calc_text, answer)]
    print("\n\n".join(parts))
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--short"]
    if len(args) not in (2, 3):
        print("usage: python3 review.py answer.md report.json [forecasts.jsonl] [--short] > pack.txt   (--short leaves out the whole sheet and keeps only the evidence lines in the sentence table: a smaller pack for models that give up on long ones)", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(*args, short="--short" in sys.argv))
