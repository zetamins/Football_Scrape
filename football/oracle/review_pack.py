"""Second-reader pack: the brief, the finished answer and a checklist, for a separate reviewer agent.

The audit checks numbers and known wording errors. A second agent that did not write the answer reads it against the brief and
catches what no pattern knows about (a number read backwards, a claim the tags do not show). Nothing here changes a forecast.
"""

from __future__ import annotations

import re

from .oracle import brief, format_brief

CHECKLIST = """You are the REVIEWER, not the author. You did not write this answer. Read the ANSWER against the BRIEF and report every error. Do not rewrite the answer and do not run other tools.

Definitions you must apply:
- A less negative number is BETTER (xG difference -0.48 beats -0.81); goal difference +0.5 beats -0.7.
- Heavy rotation means 8 or more changed starters. 5 changes is "5 of 11", never "heavy".
- The forecast comes from the engine only: a trained national-team goals model (weight 25), xG (1.5), recent results (1), strength (1). Form, stakes, rotation, fatigue and travel are context, never "the primary driver". Travel, rotation, stakes and fatigue are NOT inputs to the engine's numbers at all (the inputs are those four sources plus the home edge), so a dossier point marked 'NOT priced' really is outside the engine: do not flag a sentence that says so.
- Direction of the odds: if the odds give a side MORE than the engine does, the odds are more bullish on that side and the engine is the sceptical one; never the reverse. An absentee must appear under its own [H.absent.Name]/[A.absent.Name] tag, never under a rotation or form tag.
- Bookmaker odds are a benchmark, never an argument for the forecast, the bet or a verdict.
- Verdicts: odds_right = the odds' view is supported; odds_overrate_home/away = the odds are too high on that side; unclear = mixed or not settled by the tags. Either `odds_right` or `unclear` is acceptable when the brief says the models and odds agree; flag only a verdict that contradicts its OWN sentence.
- Listing a losing run under Weak points is fine (it is context). Flag only a claim that it will help or hurt next match.
- A side on a losing run does not bounce back (tested): context only. No "desperate", "hungry", "will respond".
- A player who is not in the squad list has an UNKNOWN role: never "key". An absentee must be cited with its [H.absent.Name]/[A.absent.Name] tag.

Method (do not skip): go through the author's own sentences ONE BY ONE (Own model vs odds after the numbers, both Case lines, Weak points, Odds challenge, Why, Risks, Data audit notes). For each sentence find the brief line that backs every claim in it before moving on: every number must appear in the line of the tag cited next to it (a goal difference is not a table figure); every tag must describe what the sentence says; anything about tactics, shape, physicality, counter-attacks, set pieces, stress, fragility, being 'routed', or what 'may/could' happen is invented unless a brief line says it. Use the SENTENCE TABLE at the end: go through every row S1, S2, ... in order, and only after the last row write the reply (list only the rows that are wrong).

Check, quoting the exact words of each problem:
1. Every number, direction (better/worse, higher/lower), count and score claim against the tag lines in the brief. For EVERY sentence that compares two numbers (xG, goal difference, points, rest days, squad value), write which side the numbers favour (the less negative / larger is better), then check the sentence says the same. Also check every derived figure (a difference or gap) by subtracting yourself (a gap to the FINAL forecast and a gap to the no-odds baseline differ slightly and both are valid if the subtraction is right), and that a model 'expected goals' figure is not called 'xG'.
2. The odds-challenge verdict against its own sentence (no overrate wording under odds_right, no "supports the odds" under overrate).
3. Claims the brief does not show: invented causes, invented tactics, "controls possession", "lacks quality", unexplained "because".
4. Characterising words without a number behind them (significant, notable, resilient, dangerous, drag, drain).
5. Each Case line defends its side with tagged points (two when the side has them), rebuts the opponent's best point and concedes a weak spot; a thin side argues from the opponent's tagged weak spots, not from invented strengths. The likeliest scorelines live in the engine's Goals line, so a Case line needs no scenario sentence.
6. Tags: each cited tag exists, matches its sentence, and one tag per bracket.
7. The recommended bet, probabilities and draw line are the engine's, unchanged. Engine lines (headline, In plain words, Recommended bet, Draw, Goals, Lineups) are verbatim by design, and so are the calibration percentages inside them (such as '~31.8% of such matches end level'): never flag their rounding, wording or source, only the author's own sentences.

Reply in exactly this form:
VERDICT: PASS   (only if you found nothing)
or
VERDICT: FIX
1. "<exact quote>" -> problem -> correct fact from the brief (quote the tag line).
2. ...
Keep it under 250 words."""


AUTHOR_LINES = ("Case for ", "Weak points:", "Odds challenge:", "Why:", "Risks and data gaps:", "Analyst note")


def sentence_table(brief_text: str, answer: str) -> str:
    """One row per author sentence with the brief lines of the tags it cites: the reviewer ticks rows instead of searching, which is what lifts recall."""
    lines_by_tag: dict[str, list[str]] = {}
    for ln in brief_text.splitlines():
        for t in dict.fromkeys(re.findall(r"\[[^\]]+\]", ln[:60])):
            lines_by_tag.setdefault(t, []).append(re.sub(r"\s+", " ", ln.strip())[:170])
    rows, n = [], 0
    for ln in answer.splitlines():
        if not ln.startswith(AUTHOR_LINES):
            continue
        for sent in re.split(r"(?<=[\w\]%)])\.\s+(?=[A-Z\[])|;\s+|\s{4,}", ln):
            if not sent.strip():
                continue
            n += 1
            tags = list(dict.fromkeys(re.findall(r"\[[^\]]+\]", sent)))
            ev = " || ".join(f"{t} -> {' / '.join(lines_by_tag.get(t, ['NO SUCH TAG'])[:2])}" for t in tags) or "NO TAG CITED"
            rows.append(f"S{n}. \"{sent.strip()[:260]}\"\n    EVIDENCE: {ev}")
    return "\n".join(rows[:60])


def review_pack(report: dict, answer: str, use_odds: bool = False) -> str:
    b = brief(report, use_odds)
    text = format_brief(b)
    table = ("=== SENTENCE TABLE (tick every row: OK, or the problem) ===\nFor each row, compare the sentence with its EVIDENCE lines. A sentence with NO TAG CITED must state nothing the brief does not say.\n" + sentence_table(text, answer))
    return "\n\n".join([CHECKLIST, "=== BRIEF ===", text, "=== ANSWER ===", answer.strip(), table])
