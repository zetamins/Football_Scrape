"""Draft of the written answer with EVERY number filled from the engine, so the reviewer only writes the reasoning.

Every first-run audit failure on headline, double chance, draw level, drawn scores and recommended bet came from numbers retyped by hand.
The draft leaves `[WRITE: ...]` placeholders for the judgement lines (Case for each side, Weak points, Odds challenge, Why, Risks) and the
audit refuses an answer that still contains one.

    python -m football.oracle draft <report.json> [--opinion-file opinion.json] [--with-odds] > /tmp/answer.md
"""

from __future__ import annotations

import re

from . import debate
from . import oracle
from .facts import extract_facts
from .lineup import lineup_picture

PLACEHOLDER = "[WRITE"
# What the reviewer writes (compose fills these into the draft; every other line comes from the engine and cannot be changed).
JUDGEMENT = {
    "vs_odds": "one line on the biggest gap between the engine and the odds and why, using only tags and numbers",
    "case_home": "1-2 sentences, only evidence FOR the home side, with tags (its own absences belong in weak_points)",
    "case_away": "1-2 sentences, only evidence FOR the away side, with tags",
    "weak_points": "each side's OWN absences, rotation and risks, with tags",
    "odds_challenge": "odds_right | odds_overrate_home | odds_overrate_away | unclear, and why, from the tagged evidence (never the odds' track record)",
    "why": "the 3 biggest drivers, each tied to a tag or number",
    "risks": "what could make this wrong; what to re-check before kickoff",
    "data_note": "which audit findings are data artefacts",
    "analyst_note": f"optional, at most {60} words, every claim tied to a [TAG] line; appended as its own line and audited as free text",
}


def plain_words(home: str, away: str, p: dict) -> str:
    """Two or three short sentences a non-expert understands: who is favoured, the draw risk, the best bet and how often such bets won, the first caution."""
    rec, d = p["recommendation"], p["draw"]
    fav, fp = (home, p["home_win_pct"]) if p["home_win_pct"] >= p["away_win_pct"] else (away, p["away_win_pct"])
    first = (f"{fav} are the clear favourites ({fp:.0f}% to win)." if fp >= 60 else f"{fav} are slight favourites ({fp:.0f}% to win)." if fp >= 45
             else "This looks like a toss-up: the sides are level and a draw is about as likely as either win." if d.get("toss_up")       # the draw lens' own definition
             else f"No side is a clear favourite ({fav} {fp:.0f}% to win).")
    risk = f"A draw is a real risk ({p['draw_pct']:.0f}%)." if d["alert"] != "none" else f"A draw is {p['draw_pct']:.0f}% likely."
    track = ("no validated hit rate exists for these teams." if rec["weak_model"] else f"bets of this kind at this level won about {rec['observed_hit_pct']:.0f} in 100 in past matches.")
    bet = f"Best bet: {rec['selection']} ({rec['probability_pct']:.0f}% chance, {rec['strength']}); {track}"
    care = f" Be careful: {rec['cautions'][0]}." if rec["cautions"] else ""
    weak = "Weak data: the trained model does not know these teams, so treat everything here as a rough lean. " if rec["weak_model"] else ""
    return f"{weak}{first} {risk} {bet}{care}"


def draft_answer(report: dict, opinion: dict | None = None, use_odds: bool = False) -> str:
    return "\n".join(_draft_lines(report, opinion, use_odds))


NOTE_WORDS = 60


def compose_answer(report: dict, judgement: dict, opinion: dict | None = None, use_odds: bool = False, free_text: bool = True) -> str:
    """The final answer: every engine line exactly as drafted, the reviewer's judgement in the placeholders. A missing field leaves its [WRITE ...] placeholder, which the audit refuses."""
    if not free_text:                                  # the command line default: only one short analyst note may be added, every other line is the engine's
        judgement = {}                                  # the command line takes NO free text: every line is the engine's (--free-text restores the author's words)
    clean = {k: re.sub(r"\s+", " ", str(v)).replace(PLACEHOLDER, "[").strip() for k, v in (judgement if isinstance(judgement, dict) else {}).items() if k in JUDGEMENT and isinstance(v, (str, int, float)) and str(v).strip()}
    full = oracle.predict(report, panel="none", opinions=[opinion] if opinion else None, use_odds=use_odds)
    if full.get("prediction"):                         # keys the reviewer did not write are built from the dossier and the engine's numbers
        clean = {**auto_judgement(full, extract_facts(report), opinion, set(oracle.brief(report, use_odds)["tags"])), **clean}
    return "\n".join(_draft_lines(report, opinion, use_odds, clean))


WEAK_SPOT = re.compile(r"\.(rotation|fatigue|form)\]$")      # context that can hurt a side; table position (top of the table, relegation zone) is not a weak spot


def _weak(dos: dict, tag: str) -> list[dict]:
    return [q for q in dos["both"] if q["tag"].startswith(f"[{tag}.") and WEAK_SPOT.search(q["tag"])]


def _thin(pt: dict) -> bool:
    return pt["tag"] == "[H2H]" or "not in the squad list" in pt["text"]


def _short(text: str) -> str:
    """The dossier keeps its full caveats; the sentences built from it carry the point without repeating them."""
    text = re.sub(r"\s*\(describes the previous match; direction for this one is ambiguous\)", "", text)
    text = re.sub(r": tested on 8,054 internationals.*$", " (tested: no bounce-back effect in the data)", text)
    return text.replace("; weak evidence once current strength is known", "")


def _cite(pts: list[dict], n: int = 2) -> str:
    return "; ".join(f"{_short(q['text'])} {q['tag']}" for q in pts[:n])


def auto_judgement(full: dict, facts: dict, opinion: dict | None = None, tags: set[str] | None = None) -> dict[str, str]:
    """Judgement lines built only from the tagged dossier and the engine's numbers: no free text, so nothing can be invented. The reviewer may override any key."""
    p = full["prediction"]
    home, away, dos = full["home"], full["away"], full["dossier"]
    out: dict[str, str] = {}
    for side, name, key in (("home", home, "case_home"), ("away", away, "case_away")):
        other = "away" if side == "home" else "home"
        tag = "H" if side == "home" else "A"
        mine = [q for q in dos[side] if not _thin(q)] or dos[side]
        weak = _weak(dos, tag)
        if len(mine) < 2:                                 # a thin side argues from the opponent's tagged weak spots
            mine = mine + _weak(dos, "A" if side == "home" else "H")
        lead = _cite(mine) or "the tagged data gives this side little: the case is thin"
        concede = f"but {_cite(weak, 1)}" if weak else ("but lineups are unconfirmed [LINEUPS]" if not facts["lineup_confirmed"] else "but no tagged weak spot stands out")
        best = next((q for q in dos[other] if not _thin(q) and ".absent." not in q["tag"]), None)       # the opponent's best point (its own absences stay out of this side's Case line)
        rebut = (f" Against {home if other == 'home' else away}'s best point ({_short(best['text'])} {best['tag']}): "
                 + ("the engine's numbers already include it." if best["priced"] else "it is outside the engine's numbers.")) if best else (
                     f" {home if other == 'home' else away}'s tagged points are absences, listed on the weak-points line." if dos[other] else "")
        wins = [f"{t['score']} ({t['pct']}%)" for t in p["simulation"]["top_scores"][:4] if (int(t["score"].split("-")[0]) > int(t["score"].split("-")[1])) == (side == "home") and t["score"].split("-")[0] != t["score"].split("-")[1]][:3]
        scenario = f" Likeliest winning scores for {name}: " + (", ".join(wins) if wins else "none of the four likeliest scores (see the Goals line) is a win for this side") + "."
        out[key] = f"{lead}.{scenario}{rebut} {concede[0].upper() + concede[1:]}."
    pic = lineup_picture(facts)
    weak_parts = []
    for side, name, tag in (("home", home, "H"), ("away", away, "A")):
        bits = [f"{_short(q['text'])} {q['tag']}" for q in _weak(dos, tag)]
        for a in pic[side]["absentees"]:
            val = f", injury-list value {a['value'] / 1e6:.1f}M" if a.get("from_injury_list") and a.get("value") else ""
            role = (a.get("role") or "role unknown") + val + (", role from an outside reference" if a.get("role_reference") else "") + (", not in the squad list: starter status unknown" if a["status"] == "unknown" else f", {a['status']}")
            mark = f" [{tag}.absent.{a['name']}]" if tags is None or f"[{tag}.absent.{a['name']}]" in tags else ""
            bits.append(f"{a['name']} ({role}) is out{mark}")
        weak_parts.append(f"{name}: " + ("; ".join(bits) if bits else "nothing notable in the data"))
    out["weak_points"] = ". ".join(weak_parts) + "."
    ch = full.get("challenge")
    verdict = (opinion or {}).get("advocates", {}).get("verdict") if isinstance((opinion or {}).get("advocates"), dict) else None
    verdict = verdict if verdict in debate.VERDICTS else ("odds_right" if ch and ch["stance"] == "agree" else "unclear")
    if ch:
        g = ch["gap_pp"]
        names = {"home": home, "draw": "the draw", "away": away}
        big = max(g, key=lambda k: abs(g[k]))
        out["vs_odds"] = f"The largest gap is on {names[big]} ({g[big]:+.1f} points, models without the odds minus odds); the odds are a benchmark and not an input."
        if abs(g[big]) >= oracle.BENCHMARK_NOTE_PCT:
            out["vs_odds"] += " This is a large disagreement with the benchmark: it changes nothing in the forecast, the bet or the cautions, and it is a reason to re-check the data (unknown absentees, rotation, form) before relying on either side."
        gaps = f"{g['home']:+.1f} (home), {g['draw']:+.1f} (draw), {g['away']:+.1f} (away) points"
        out["odds_challenge"] = (f"odds_right - gaps of {gaps}; the engine's own comparison rates this as agreement, not a disagreement." if verdict == "odds_right" else
                                 f"{verdict} - the models without the odds differ from the odds by {gaps}; the tags do not settle the difference.")
    else:
        out["vs_odds"] = "No odds in the report: no comparison is possible."
        out["odds_challenge"] = "unclear - no odds in the report, so no challenge is possible."
    lead_side = "home" if p["home_win_pct"] >= p["away_win_pct"] else "away"
    ctx = _cite([q for q in dos[lead_side] if not _thin(q)], 2)
    out["why"] = ("The forecast comes from the engine only: the trained national-team goals model (weight 25), xG (1.5), recent results (1) and strength (1)."
                  + (f" Tagged context for {home if lead_side == 'home' else away}: {ctx}." if ctx else ""))
    out["risks"] = ("Lineups are unconfirmed [LINEUPS]: re-run once they are." if not facts["lineup_confirmed"] else "Lineups are confirmed [LINEUPS].") + " Absentees not in the squad list have an unknown impact."
    out["data_note"] = "Findings above come from the data checks; none of them is a forecast input."
    return out


def fixed_lines(report: dict, opinion: dict | None = None, use_odds: bool = False) -> list[tuple[str, str, bool]]:
    """(label, expected text, exact) for every line the draft fills from the engine. The audit requires the final answer to keep them: `exact` lines word for
    word, the others as their opening (the reviewer may append to Lineups and Data audit, and fills the [WRITE ...] part of Own model vs odds)."""
    lines = _draft_lines(report, opinion, use_odds)
    if len(lines) < 2:
        return []
    out = [("headline", lines[0], True)]
    for ln in lines[1:]:
        label = ln.split(":", 1)[0] + ":"
        if label == "In plain words:":
            out.append((label, ln, True))
        elif label in ("Recommended bet:", "Draw:", "Goals:", "Lineups:"):
            out.append((label, ln, False))
        elif label in ("Own model vs odds:", "Data audit:"):
            out.append((label, ln.split(f". {PLACEHOLDER}")[0], False))
    return out


def _draft_lines(report: dict, opinion: dict | None, use_odds: bool, fill: dict | None = None) -> list[str]:
    full = oracle.predict(report, panel="none", opinions=[opinion] if opinion else None, use_odds=use_odds)
    p = full.get("prediction")
    if not p:
        return [f"No prediction: {full.get('reason')}"]
    facts = extract_facts(report)
    home, away = full["home"], full["away"]
    pick = {"home": f"{home} win", "draw": "Draw", "away": f"{away} win"}[p["pick"]]
    rec, d = p["recommendation"], p["draw"]
    dc = d["double_chance_pct"]
    base = [100 * x for x in full["engine"]["after_absences"]["probs"]]
    odds = facts["odds"]
    odds_txt = f"odds (benchmark, not an input) {100*odds['home']:.1f}/{100*odds['draw']:.1f}/{100*odds['away']:.1f}" if odds else "no odds in the report"
    level = {"alert": "ALERT", "watch": "WATCH", "none": "no alert"}[d["alert"]]
    scores = ", ".join(f"{k} {v}%" for k, v in d["draw_scores_pct"].items() if v >= 0.5)
    sim = p["simulation"]
    pic = lineup_picture(facts)
    out_lines = []
    unknown = []
    for side, name in (("home", home), ("away", away)):
        starters = pic[side]["starters_out"]
        unk = [a["name"] for a in pic[side]["absentees"] if a["status"] == "unknown"]
        others = [f"{a['name']} ({a['status']} player)" for a in pic[side]["absentees"] if a["status"] in ("rotation", "fringe")]
        out_lines.append(f"{name} starters out: {', '.join(starters) if starters else 'none identified'}" + (f"; other absentees: {', '.join(others)}" if others else ""))
        if unk:
            unknown.append(f"{name} unknown (not in the squad list): {', '.join(unk)}")
    codes = [f["code"] for f in full["audit"]["findings"]]
    fill = fill or {}

    def slot(key: str, hint: str) -> str:
        return fill[key] if key in fill else f"{PLACEHOLDER}: {hint}]"
    lines = [
        f"**{home} {p['home_win_pct']}% / Draw {p['draw_pct']}% / {away} {p['away_win_pct']}%**  - most likely 1X2: {pick} ({p['pick_probability_pct']}%); " + (f"calibrated chance the pick is right {p['confidence_pct']}% (observed hit rate of such picks in held-out matches, not a guarantee)" if not p["recommendation"]["weak_model"] else "no calibrated chance: the trained model does not know these teams and the held-out tables are for national teams, so the percentages are the raw model's, not a validated hit rate"),
        f"In plain words: {plain_words(home, away, p)}",
        f"Recommended bet: {rec['selection']} - {rec['probability_pct']}% ({rec['market']}); strength {rec['strength']}; " + (f"bets of this kind at this probability hit {rec['observed_hit_pct']}% in held-out matches" if not rec["weak_model"] else "no validated hit rate for these teams (the held-out tables are for national teams)") + "; next best: "
        + ", ".join(f"{a['selection']} {a['probability_pct']}%" for a in rec["alternatives"][:2]) + (" (weak model: a lean)" if rec["weak_model"] else "")
        + (f". Why this market: {rec['reason']}" if rec["reason"] else "")
        + (f". Not recommended: {rec['not_recommended'][0]['selection']} {rec['not_recommended'][0]['probability_pct']}% (goals bets need 60%, below that they are coin flips)" if rec["not_recommended"] else "")
        + (f". Cautions: {'; '.join(rec['cautions'])}" if rec["cautions"] else ""),
        f"Own model vs odds: engine baseline {base[0]:.1f}/{base[1]:.1f}/{base[2]:.1f}, final {p['home_win_pct']}/{p['draw_pct']}/{p['away_win_pct']}, {odds_txt}. " + slot("vs_odds", "one line on the biggest gap and why, using only tags and numbers"),
        f"Draw: {level} - draw {p['draw_pct']}% ({d['tier']}: ~{d['observed_draw_rate_pct']}% of such matches end level); double chance {dc['home_or_draw']}% / {dc['draw_or_away']}%; drawn scores {scores}" + "".join(f"; {x}" for x in d["flags"])
        + ("; a risk flag, not a prediction (about 1 in 3 flagged matches end level)" if d["alert"] != "none" else "")
        + ("; knockout match: the result means level after 120 minutes" if "knockout_definition" in codes else ""),
        f"Case for {home}: " + slot("case_home", f"1-2 sentences, only evidence FOR {home}, tags") + f"      Case for {away}: " + slot("case_away", f"1-2 sentences, only evidence FOR {away}, tags"),
        "Weak points: " + slot("weak_points", "each side's OWN absences, rotation and risks, with tags"),
        "Odds challenge: " + slot("odds_challenge", "odds_right | odds_overrate_home | odds_overrate_away | unclear, and why"),
        f"Goals: expected {sim['expected_goals'][0]}-{sim['expected_goals'][1]}; likeliest scores " + ", ".join(f"{s['score']} ({s['pct']}%)" for s in sim["top_scores"][:4])
        + f"; over 2.5 {sim['markets_pct']['over_2_5']}%, both score {sim['markets_pct']['btts']}%",
        "Why: " + slot("why", "3 biggest drivers, each tied to a tag or number"),
        f"Lineups: {'confirmed' if facts['lineup_confirmed'] else 'guessed (unconfirmed)'}; " + "; ".join(out_lines) + ("; " + "; ".join(unknown) + " (impact unknown: may be the key absences the engine cannot weigh)" if unknown else "")
        + (f"; flags: {', '.join(c for c in codes if c in ('xi_overlap', 'missing_in_xi', 'injured_in_xi', 'xi_not_in_squad', 'empty_absentee_list', 'heavy_rotation'))}" if any(c in ('xi_overlap', 'missing_in_xi', 'injured_in_xi', 'xi_not_in_squad', 'empty_absentee_list', 'heavy_rotation') for c in codes) else ""),
        "Risks and data gaps: " + slot("risks", "what could make this wrong; what to re-check before kickoff"),
        f"Data audit: quality {full['audit']['quality']:.0%}; findings: " + (", ".join(dict.fromkeys(codes)) if codes else "none") + ". " + slot("data_note", "mark which findings are data artefacts"),
    ]
    note = " ".join(str(fill.get("analyst_note", "")).split()[:NOTE_WORDS]) if fill else ""
    if note:
        lines.append(f"Analyst note (the author's own words, audited as free text): {note}")
    return lines
