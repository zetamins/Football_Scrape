"""Mechanical audit of a written answer against the engine: tags that exist, headline and double-chance numbers that match, the right draw
level, own-side absences kept out of a side's own case, no banned claims. Judgement (is the reasoning good?) stays with a human.

    python -m football.oracle audit <report.json> <answer.md> [--opinion-file opinion.json] [--with-odds]
"""

from __future__ import annotations

import re

from . import draft as draft_mod
from . import oracle
from .facts import extract_facts, norm
from .lineup import lineup_picture

TOLERANCE = 0.15
REQUIRED = ("In plain words:", "Recommended bet:", "Draw:", "Weak points:", "Odds challenge:", "Goals:", "Why:", "Lineups:", "Risks and data gaps:", "Data audit:")
BANNED = (
    (r"priced into", "absences are not priced into the independent engine; say they are unmodelled"),
    (r"unpriced by the odds", "the odds DO price known absences"),
    (r"(absen\w*|injur\w*|missing|loss)[^.\n]{0,70}\bunpriced|unpriced[^.\n]{0,70}(absen\w*|injur\w*|missing|loss)", "the odds DO price known absences: call them unmodelled by the engine, never unpriced"),
    (r"all three (outcomes )?(are )?within", "toss-up means home and away within 5 points and draw >= 28%"),
    (r"\bstak(e|ing) (size|sizing|plan|a|\u00a3|\$|\d)|\bbet (size|sizing)\b|(?<!not a )(?<!no )\bguarantee[ds]?\b|\bsure thing\b|can'?t lose|cannot lose|\bbanker\b|free money|\bsafe bet\b", "no staking advice and no guarantees: the bet is the model's most likely selection with its probability and hit rate"),
    (r"\b(we|the model|the engine|our model)\s+predict(s|ed)?\s+(a\s+|the\s+)?draw|draw\s+(is\s+)?predicted", "do not claim to predict draws: a draw flag is a risk hint, about 1 in 3"),
    (r"(odds|bookmakers?|market)[^.\n]{0,45}\b(usually|historically|typically|generally|almost always|normally|tend to)\b[^.\n]{0,25}\b(win|prevail|right|correct|better|accurate)|\b(historically|typically|usually|generally)\b[^.\n]{0,30}(odds|bookmakers?|market)[^.\n]{0,25}\b(win|prevail|right|correct|better|accurate)|(odds|bookmakers?)[^.\n]{0,30}track record|track record[^.\n]{0,30}(odds|bookmakers?)|\b17 (of|out of|to) (20|3)\b|\b17[- ]3\b",
     "independence: do not cite the odds' track record as an argument; decide from the tagged evidence"),
)
CHARACTER_WORDS = re.compile(r"\b(resilien\w*|stable|solid|organi[sz]ed|dominant|momentum|dangerous|clinical|ruthless|fragile|world-class|brilliant|cohesi\w*|intact|spine|cautious|stabilit\w*|flexib\w*|substantial|inherent|overwhelming|vastly|massive|drain|drag|burden|toll|stress|fragil\w*|routed|vulnerab\w*|physical|counter-?attack\w*|on the counter|transitions?|narrow|tiny|huge|rhythm|available at kickoff|major|dominat\w*|ability to execute|control\w*|possession|chemistry|skeptic\w*|sceptic\w*|cautious|caution about)\b", re.I)
SCORE_CLAIM = re.compile(r"(\d+)\s*[-\u2013]\s*(\d+)\s+(?:draw |win |loss |defeat |victory )?(vs\.?|v|against|in|at)\s+([A-Z][\w'.\u2019\u00c0-\u00ff]+(?: [A-Z][\w'.\u2019\u00c0-\u00ff]+)?)")
NAME = r"([A-Z\u00c0-\u00de][\w'.\u2019\u00c0-\u00ff-]+(?: [A-Z\u00c0-\u00de][\w'.\u2019\u00c0-\u00ff-]+)?)"
MANAGER_CLAIM = re.compile(r"(?:under|manager|coach|boss|head coach)\s+" + NAME)
MISSING_CLAIM = re.compile(r"(?:missing|without|absence of|loss of|loses|lose|absent:?)\s+" + NAME)
FORM_COUNT = [
    re.compile(r"(\d+)\s+(?:of|from)\s+(?:the |their |its )?(?:last|previous|recent)\s+(\d+)(?:\s+(?:matches|games|results|league games))?,?\s+(wins?|draws?|losses|defeats)", re.I),
    re.compile(r"(\d+)\s+(wins?|draws?|losses|defeats)\s+(?:in|from|over)\s+(?:the |their |its )?(?:last|previous|recent)\s+(\d+)", re.I),
    re.compile(r"(won|drew|lost)\s+(\d+)\s+(?:of|from)\s+(?:the |their |its )?(?:last|previous|recent)\s+(\d+)", re.I),
]
_KIND = {"w": "W", "d": "D", "l": "L", "won": "W", "drew": "D", "lost": "L"}
GAP_CLAIM = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*(?:percentage points?|points?|pp)\b(?!\s*(?:per|from|each|a game|in the table|in the group|in the league|in the standings|on the board|clear|ahead|behind|off the (?:top|lead|pace|leaders?|summit|bottom|relegation|playoff)|adrift|away|more than|fewer))", re.I)   # "50-point gap" counts; league points do not
GAP_EXEMPT = re.compile(r"(within|at most|up to|worth|typical|\+-|\+/-|threshold|>=|<=|about 1 in)", re.I)
FORM_GOOD = re.compile(r"\b(strong|good|excellent|great|impressive|winning)\b[^.\n\[]{0,25}\bform\b|\bform\b[^.\n\[]{0,12}\b(strong|excellent|impressive)\b", re.I)
FORM_BAD = re.compile(r"\b(poor|bad|weak|struggling|dreadful|dismal|losing)\b[^.\n\[]{0,25}\bform\b", re.I)
LEVELS = {"alert": "ALERT", "watch": "WATCH", "none": "no alert"}


def _plain(line: str) -> str:
    """A line without markdown decoration (bold markers, bullets) and with single spaces, for comparing it with the draft."""
    return re.sub(r"\s+", " ", re.sub(r"^\s*[-*]\s+", "", line.replace("**", ""))).strip()


def _pcts(text: str) -> list[float]:
    return [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", text)]


def audit_answer(report: dict, text: str, opinion: dict | None = None, use_odds: bool = False) -> dict:
    rows: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = ""):
        rows.append((name, ok, detail))

    b = oracle.brief(report, use_odds=use_odds)
    full = oracle.predict(report, panel="none", opinions=[opinion] if opinion else None, use_odds=use_odds)
    pred = full.get("prediction")
    if not pred:
        return {"rows": [("engine prediction", False, "no prediction could be computed for this report")], "clean": False}
    valid = set(b["tags"])
    unknown = sorted({t for t in re.findall(r"\[[^\]]+\]", text) if t not in valid and not t.startswith("[WRITE")})
    combined = [t for t in unknown if re.search(r"[,;]", t)]
    hint = "; ".join(f"{t}: write one tag per bracket, e.g. " + " ".join(f"[{x.strip()}]" for x in re.split(r"[,;]", t[1:-1])) for t in combined)
    check("every [TAG] exists in the brief", not unknown, hint or ", ".join(unknown))
    head = next((ln for ln in text.splitlines() if re.search(r"\bDraw\b", ln) and len(_pcts(ln)) >= 3), "")   # the headline, wherever it sits (a title line may precede it)
    nums = _pcts(head)[:3]
    want = [pred["home_win_pct"], pred["draw_pct"], pred["away_win_pct"]]
    check("headline H/D/A equals the engine's final numbers", len(nums) >= 3 and all(abs(a - w) <= TOLERANCE for a, w in zip(nums, want)), f"written {nums[:3]} vs engine {want}")
    dl = pred["draw"]
    dc_line = next((ln for ln in text.splitlines() if ln.lstrip().startswith("Draw:") and "double chance" in ln.lower()), "")   # the Draw line, not the Recommended bet line that also says "Double chance"
    after = _pcts(dc_line[dc_line.lower().index("double chance"):]) if dc_line else []
    dc = dl["double_chance_pct"]
    check("double chance equals the engine's", len(after) >= 2 and abs(after[0] - dc["home_or_draw"]) <= TOLERANCE and abs(after[1] - dc["draw_or_away"]) <= TOLERANCE,
          f"written {after[:2]} vs engine {[dc['home_or_draw'], dc['draw_or_away']]}")
    reco = pred["recommendation"]
    reco_line = next((ln for ln in text.splitlines() if "Recommended bet:" in ln), "")
    reco_nums = _pcts(reco_line)
    check("recommended bet equals the engine's (selection and probability)", reco["selection"].lower() in reco_line.lower() and any(abs(x - reco["probability_pct"]) <= TOLERANCE for x in reco_nums),
          f"engine recommends {reco['selection']} {reco['probability_pct']}% ({reco['strength']})")
    mismatched = []
    ans_lines = [_plain(ln) for ln in text.splitlines()]
    for label, expected, exact in draft_mod.fixed_lines(report, opinion, use_odds):
        want = _plain(expected)
        if label == "headline":
            got = next((l for l, raw in zip(ans_lines, text.splitlines()) if re.search(r"\bDraw\b", raw) and len(_pcts(raw)) >= 3), "")
        else:
            got = next((l for l in ans_lines if l.startswith(_plain(label))), "")
        if not (got == want if exact else got.startswith(want)):
            mismatched.append(f"{label} ({'missing' if not got else 'changed'})")
    check("the lines the draft filled from the engine are kept as drafted", not mismatched,
          "; ".join(mismatched) + (": run `oracle draft` and keep these lines word for word (append to Lineups and Data audit only; fill the [WRITE ...] parts)" if mismatched else ""))
    draw_line = next((ln for ln in text.splitlines() if ln.lstrip().startswith("Draw:")), "")
    level = LEVELS[dl["alert"]]
    check("draw level matches the engine", level.lower() in draw_line.lower() and not (level == "no alert" and re.search(r"ALERT|WATCH", draw_line.split("no alert")[0])), f"engine says {level}")
    bad_scores = []
    for k, v in dl["draw_scores_pct"].items():
        m = re.search(re.escape(k) + r"\s*(\d+(?:\.\d+)?)\s*%", draw_line)
        if m and abs(float(m.group(1)) - v) > TOLERANCE:
            bad_scores.append(f"{k}: written {m.group(1)} vs engine {v}")
    check("drawn-score percentages match", not bad_scores, "; ".join(bad_scores))
    parts = re.split(r"Case for ", text)
    if len(parts) >= 3:
        away_case = parts[2].split("\n", 1)[0]          # the away Case text ends with its own line: later lines (Weak points, Lineups) may name that side's absences
        own = [t for seg, pre in ((parts[1], "[H.absent."), (away_case, "[A.absent.")) for t in re.findall(re.escape(pre) + r"[^\]]+\]", seg)]
        check("no side's own absence inside its own Case line", not own, ", ".join(own))
    else:
        check("both Case lines present", False, "expected 'Case for {Home}' and 'Case for {Away}'")
    hits = [msg for pat, msg in BANNED if re.search(pat, text, re.I)]
    check("no banned claims", not hits, "; ".join(hits))
    left = text.count("[WRITE")
    check("no unfilled [WRITE ...] placeholders left from the draft", left == 0, f"{left} placeholder(s) still to write" if left else "")
    missing = [r for r in REQUIRED if r not in text]
    check("all deliverable lines present", not missing, ", ".join(missing))
    notes = [ln.split(":", 1)[1] for ln in text.splitlines() if ln.startswith("Analyst note")]
    untagged = [x.strip()[:70] for n in notes for x in re.split(r"(?<=[\w\]%)])\.\s+(?=[A-Z\[])|;\s+", n) if x.strip() and not re.search(r"\[[^\]]+\]", x)]
    check("every analyst-note sentence cites a [TAG]", not untagged, "; ".join(f"'{u}'" for u in untagged))
    guesses = sorted({m.group(0) for m in SPECULATION.finditer(text)})
    check("no guesses about causes, the odds or the data", not guesses, "reword with the tag or number it rests on: " + "; ".join(f"'{g}'" for g in guesses))
    why = " ".join(ln for ln in text.splitlines() if ln.lstrip().startswith("Why:"))
    non_inputs = re.findall(r"\[[HA]\.(?:stakes|rotation|fatigue|travel|manager|referee)\]", why)
    goals_line = next((ln for ln in text.splitlines() if ln.startswith("Goals:")), "")
    shown = set(re.findall(r"(\d+-\d+) \((\d+(?:\.\d+)?)%\)", goals_line))
    stray = []
    for ln in text.splitlines():
        if ln.startswith(("Case for", "Weak points", "Why:", "Risks", "Analyst note", "Odds challenge")):
            stray += [f"{a} ({b}%)" for a, b in re.findall(r"(\d+-\d+) \((\d+(?:\.\d+)?)%\)", ln) if (a, b) not in shown]
    check("scores quoted in the judgement lines are the Goals line's own", not stray, "not in the Goals line: " + ", ".join(dict.fromkeys(stray)) if stray else "")
    wrong = _reasoning_failures(text, extract_facts(report))
    check("claims agree with the numbers and the verdict beside them", not wrong, " | ".join(wrong))
    warns = _fact_warnings(report, text, rows)
    if len(parts) >= 3:
        for label, seg in (("home", parts[1]), ("away", parts[2].split("\n", 1)[0])):
            if not CONCESSION.search(seg):
                warns.append(f"the {label} Case line has no concession: a strong case also names its side's honest weak spot (but / however / although / despite), from a tag")
    warns += _absentee_tag_warnings(extract_facts(report), text)
    warns += _tag_number_warnings(report, text)
    if DRIVER_CLAIM.search(why):
        warns.append(f"'{DRIVER_CLAIM.search(why).group(0)}': the engine's biggest input is the trained goals model (weight 25 of about 28.5); recent form and results carry weight 1. Do not call a tag the primary driver; say what the engine's numbers rest on")
    if non_inputs and DRIVER_WORDS.search(why):
        warns.append(f"Why names {', '.join(sorted(set(non_inputs)))} as a driver, but the forecast comes only from history, xG, results and strength (plus any applied opinion factor): say these are context, not drivers")
    warns += _gap_warnings(text, [pred["home_win_pct"], pred["draw_pct"], pred["away_win_pct"]], [100 * x for x in full["engine"]["after_absences"]["probs"]], extract_facts(report)["odds"], full["home"], full["away"])
    return {"rows": rows, "warnings": warns, "clean": all(ok for _, ok, _ in rows)}


def _gap_warnings(text: str, final: list[float], baseline: list[float], odds: dict | None, home: str = "", away: str = "") -> list[str]:
    """'The model leans away by N points' style comparisons must equal a real gap between the final forecast, the engine baseline and the odds, ON THE OUTCOME THE SENTENCE NAMES
    (home / draw / away, or a team name), or a gap between two outcomes of one forecast. A real number attached to the wrong outcome is still a miscalculation."""
    sets = {"final": final, "baseline": baseline}
    if odds:
        sets["odds"] = [100 * odds["home"], 100 * odds["draw"], 100 * odds["away"]]
    allowed: list[tuple[float, frozenset]] = []
    names = list(sets)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            allowed += [(abs(sets[a][k] - sets[b][k]), frozenset({k})) for k in range(3)]
        allowed += [(abs(sets[a][j] - sets[a][k]), frozenset({j, k})) for j in range(3) for k in range(j + 1, 3)]
    warns = []
    hn, an = norm(home), norm(away)
    for sentence in _sentences(text):
        low = sentence.lower()
        named = {1} if re.search(r"\bdraw", low) else set()
        if re.search(r"\bhome\b", low) or (hn and hn in norm(sentence)):
            named.add(0)
        if re.search(r"\baway\b", low) or (an and an in norm(sentence)):
            named.add(2)
        for m in GAP_CLAIM.finditer(sentence):
            before = sentence[max(0, m.start() - 30):m.start()]
            if GAP_EXEMPT.search(before):
                continue
            if RATE_ADJUSTMENT.search(sentence[max(0, m.start() - 40):m.end() + 25]):
                continue                                      # "away rate down 3 points" is the reviewer's adjustment, not a probability gap
            n = float(m.group(1))
            if n < 2:
                continue
            pool = [(g, ix) for g, ix in allowed if not named or ix & named]
            if any(abs(n - g) <= 0.6 for g, _ in pool):
                continue
            where = f" on {'/'.join({0: 'the home side', 1: 'the draw', 2: 'the away side'}[k] for k in sorted(named))}" if named else ""
            warns.append(f"'{m.group(0)}': no gap{where} between the final forecast, the baseline and the odds is {n:g} points (real gaps{where}: " + ", ".join(sorted({f'{g:.1f}' for g, _ in pool if g >= 2}, key=float)[:8]) + ")")
    return warns


RATE_ADJUSTMENT = re.compile(r"\b(rates?|adjust\w*|reviewer|opinion|factor)\b", re.I)
DRIVER_WORDS = re.compile(r"\b(drivers?|drives?|driving|driven|decisive|settles?|tilts?|explains?)\b", re.I)
SPECULATION = re.compile(r"\b(likely|probably|perhaps|maybe|possibly)\s+(explained|because|due to|driven by|reflects?)\b|(odds|bookmakers?|market)[^.\n]{0,60}\b(overweights?|overreact\w*|underweights?|overpric\w*|underpric\w*)\b|\bmay (yet )?be priced\b|\b(likely|probably|presumably|possibly)\s+(already\s+)?priced\b|\b(data|squad lists?|feeds?|sources?)\b[^.\n]{0,60}\b(typically|usually|normally|generally)\b[^.\n]{0,40}\b(exclude|omit|miss|lack|drop)\w*|explained (only )?by rounding|\b(odds|market|bookmakers?)\b[^\n]{0,70}?\b(due to|because of|thanks to|driven by|reflect(?:s|ing)?)\b|\b(gap|difference)\b[^\n]{0,40}?\b(due to|because of|explained by|reflects?)\b|\b(explain|explains|explained|account(?:s|ed)? for)\b[^\n]{0,30}\b(gap|difference|movement)\b|\b(gap|difference|movement)\b[^\n]{0,60}\b(explain\w*|account(?:s|ed)? for)\b|(?<!most )\b(potentially|presumably|probably)\b|(?<!most )\blikely\s+(a\s+|the\s+)?(shootout|data|due|because|result|reason|cause)\b|\bgiving\s+\w+\s+(a\s+)?(small |real |clear )?(window|opening|edge|chance)\b|\b(may|might|could)\s+(shift|move|change|alter|affect|matter|improve|hurt|help|swing|decide|create|cause|lead to|result in|deliver|produce|trigger|unsettle|get routed|resolve)\b|(odds|market)[^.\n]{0,40}\b(optimistic|pessimistic|too (high|low))\b|scrape[- ]timing|\b(will|should|likely to|expected to|can|could|may|to|sure to|bound to)\s+(\w+\s+)?bounce[- ]?back\b|\b(desperate|hungry|wounded|fired up|something to prove|backs against the wall)\b|\b(often|usually|typically|generally|commonly|tends? to|almost certainly|in international football|common in)\b|(?<!the )\b(key|crucial|vital)\s+(\w+\s+){0,2}(absentees?|absences?)\b", re.I)


VENUE_OF_MEETINGS = re.compile(r"\bon the road\b|\baway from home\b|\bin away (games|matches|fixtures)\b|\b(at|in) their (own )?(ground|stadium)\b|\bhome (games|matches|fixtures|record)\b|\bat home in (the )?(past|previous|earlier)", re.I)
H2H_CUE = re.compile(r"head[- ]to[- ]head|\bh2h\b|\[H2H\]|\bmeetings?\b|\bencounters?\b|against each other|previous clashes|\bfixtures between\b", re.I)


def _sentences(text: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.!?])\s+|\n", text) if x.strip()]


_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_N = r"(\d+|" + "|".join(_NUM) + r")"
UNBEATEN = re.compile(r"\b(unbeaten|undefeated|without (?:a )?defeat|not lost|no defeats?)\b(?:\s+in\s+(?:the\s+|their\s+)?(?:last\s+)?" + _N + r")?", re.I)
WINLESS = re.compile(r"\b(winless|without (?:a )?win|no wins?)\b(?:\s+in\s+(?:the\s+|their\s+)?(?:last\s+)?" + _N + r")?", re.I)
WIN_STREAK = re.compile(_N + r"[- ](?:game|match)\s+(?:winning|win)\s+(?:streak|run)|winning\s+(?:streak|run)\s+of\s+" + _N + r"|" + _N + r"\s+(?:straight|consecutive)\s+(?:wins|victories)|" + _N + r"\s+wins\s+in\s+a\s+row", re.I)
LOSS_STREAK = re.compile(_N + r"[- ](?:game|match)\s+(?:losing|defeat)\s+(?:streak|run)|losing\s+(?:streak|run)\s+of\s+" + _N + r"|" + _N + r"\s+(?:straight|consecutive)\s+(?:defeats|losses)|" + _N + r"\s+(?:defeats|losses)\s+in\s+a\s+row", re.I)


def _num(token: str | None) -> int | None:
    if not token:
        return None
    return int(token) if token.isdigit() else _NUM.get(token.lower())


def _claim_side(sentence: str, facts: dict) -> str | None:
    """The side a sentence is about: the one whose form tag it cites, else the one whose name it mentions (only if exactly one of the two)."""
    h, a = "[H.form]" in sentence, "[A.form]" in sentence
    if h != a:
        return "home" if h else "away"
    hn, an = norm(facts["home"]) in norm(sentence), norm(facts["away"]) in norm(sentence)
    return ("home" if hn else "away") if hn != an else None


def _streak_claims_ok(facts: dict, text: str, report: dict) -> tuple[bool, str]:
    """'Unbeaten', 'winless' and 'N-game winning streak' claims against the side's form letters (newest first)."""
    bad = []
    for sentence in _sentences(text):
        if H2H_CUE.search(sentence):
            continue
        side = _claim_side(sentence, facts)
        if not side:
            continue
        res = [r["result"] for r in facts["sides"][side]["form"] if r["result"]]
        if len(res) < 3:
            continue
        for m in UNBEATEN.finditer(sentence):
            n = _num(m.group(2)) or 6
            if "L" in res[:n]:
                bad.append(f"'{m.group(0)}' for {side}, but its last {min(n, len(res))} results are {''.join(res[:n])}")
        for m in WINLESS.finditer(sentence):
            n = _num(m.group(2)) or 6
            if "W" in res[:n]:
                bad.append(f"'{m.group(0)}' for {side}, but its last {min(n, len(res))} results are {''.join(res[:n])}")
        for pat, letter in ((WIN_STREAK, "W"), (LOSS_STREAK, "L")):
            for m in pat.finditer(sentence):
                n = next((_num(g) for g in m.groups() if g), None)
                if n and res[:n].count(letter) != min(n, len(res)):
                    bad.append(f"'{m.group(0)}' for {side}, but its last {n} results are {''.join(res[:n])}")
    return not bad, "; ".join(bad)


def _absentee_count_warnings(facts: dict, text: str) -> list[str]:
    """'N absentees not in the squad list' next to tags of ONE side must not exceed that side's count of such players (it is easy to credit one side with both teams' players)."""
    pic = lineup_picture(facts)
    warns = []
    for sentence in _sentences(text):
        sides = {m for m in re.findall(r"\[([HA])\.absent\.", sentence)}
        m = re.search(_N + r"\s+(?:\w+\s+){0,2}(?:absentees|absences|players)\s+(?:who are\s+|that are\s+)?not in (?:the |their )?squad", sentence, re.I)
        if len(sides) != 1 or not m or _num(m.group(1)) is None:
            continue
        side = "home" if "H" in sides else "away"
        have = sum(1 for a in pic[side]["absentees"] if a["status"] == "unknown")
        if _num(m.group(1)) > have:
            warns.append(f"'{m.group(0)}' next to {side}-side tags, but only {have} {side}-side absentee(s) are not in the squad list (the other side's count is separate)")
    return warns


def _form_counts_ok(facts: dict, text: str) -> tuple[bool, str]:
    """Counts are checked against the data they are about. Recent form ('N of the last M' wins/draws/losses, anywhere but in a head-to-head sentence) must match the
    form letters of at least one side; a head-to-head sentence must match the H2H record (home wins, draws, away wins, n). They are different data."""
    letters = {sd: [r["result"] for r in facts["sides"][sd]["form"] if r["result"]] for sd in ("home", "away")}
    h2h = facts["h2h"]
    bad = []
    for sentence in _sentences(text):
        if H2H_CUE.search(sentence):
            bad += _h2h_claims(h2h, sentence)
            continue
        claims = []
        for m in FORM_COUNT[0].finditer(sentence):
            claims.append((m.group(0), int(m.group(1)), int(m.group(2)), _KIND[m.group(3)[0].lower()]))
        for m in FORM_COUNT[1].finditer(sentence):
            claims.append((m.group(0), int(m.group(1)), int(m.group(3)), _KIND[m.group(2)[0].lower()]))
        for m in FORM_COUNT[2].finditer(sentence):
            claims.append((m.group(0), int(m.group(2)), int(m.group(3)), _KIND[m.group(1).lower()]))
        sides = ("home",) if "[H.form]" in sentence and "[A.form]" not in sentence else ("away",) if "[A.form]" in sentence and "[H.form]" not in sentence else ("home", "away")
        for quote, n, last, kind in claims:
            counts = {sum(1 for x in letters[sd][:last] if x == kind) for sd in sides}
            if n not in counts:
                bad.append(f"'{quote}': the form data has {sorted(counts)} {kind} in the last {last}")
    return not bad, "; ".join(bad)


def _h2h_claims(h2h: dict | None, sentence: str) -> list[str]:
    """Numbers quoted about head-to-head meetings against the H2H record. (Recent form is a different thing: it is checked against the form letters.)"""
    if not h2h or not h2h.get("n"):
        return []
    n, hw, dr, aw = h2h["n"], h2h["home_wins"], h2h["draws"], h2h["away_wins"]
    wins = {hw, aw}
    bad = []
    for m in re.finditer(r"(\d+)\s+of\s+(?:the\s+|their\s+|those\s+)?(?:last\s+)?(\d+)(?=\s+(?:meetings?|encounters?|matches|games|head))", sentence, re.I):
        k, total = int(m.group(1)), int(m.group(2))
        if total > n or (total == n and k not in {hw, dr, aw}):
            bad.append(f"'{m.group(0)}': the head-to-head record has home {hw}, draws {dr}, away {aw} (n={n})")
    for m in re.finditer(r"\b(home|away|draws?)\s*[:=]?\s*(\d+)\b", sentence, re.I):
        word, k = m.group(1).lower(), int(m.group(2))
        want = hw if word == "home" else aw if word == "away" else dr
        if k != want:
            bad.append(f"'{m.group(0)}': the head-to-head record has {word} {want} (home {hw}, draws {dr}, away {aw}, n={n})")
    for m in re.finditer(r"\bn\s*=\s*(\d+)", sentence):
        if int(m.group(1)) != n:
            bad.append(f"'{m.group(0)}': the head-to-head record has n={n}")
    for m in re.finditer(r"(?<![\w.])(\d+)\s+(wins?|draws?|defeats?|losses)\b(?!\s+(?:in|from|over)\s+(?:the\s+|their\s+)?(?:last|previous|recent)\s+\d)", sentence, re.I):
        k, kind = int(m.group(1)), m.group(2).lower()
        ok = k == dr if kind.startswith("draw") else k in wins
        if not ok and k <= n:
            bad.append(f"'{m.group(0)}': the head-to-head record has home {hw}, draws {dr}, away {aw} (n={n})")
    return bad


ROTATION_HEAVY_MIN = 8
CONCESSION = re.compile(r"\b(but|however|although|though|despite|yet|even so|concede[sd]?|admittedly|whereas|while)\b", re.I)
XG_SENTENCE = re.compile(r"[^.\n]*\bxG\b[^.\n]*?([+-]\d+\.\d+)\s*(?:vs\.?|against|to|and)\s*(?:\w+'?s?\s+)?([+-]\d+\.\d+)[^.\n]*", re.I)
XG_WORSE = re.compile(r"\b(worse|weaker|lower|poorer|underperform\w*|overstate\w*|flatter\w*)\b", re.I)
XG_BETTER = re.compile(r"\b(better|stronger|higher|superior|outperform\w*)\b", re.I)


HEAVY_ROTATION = re.compile(r"\b(heavy|significant|major|mass(?:ive)?|wholesale|extensive)\s+(rotation|turnover|squad changes|changes)\b", re.I)
DRIVER_CLAIM = re.compile(r"\b(primary|main|biggest|largest|key|chief|top|strongest|major)\s+(\w+\s+)?(drivers?|reasons?|factors?)\b", re.I)


def _reasoning_failures(text: str, facts: dict | None = None) -> list[str]:
    """Claims that contradict the numbers or the verdict they sit next to."""
    bad = []
    if facts:
        changed = [(facts["sides"][sd]["rotation"] or {}).get("changed_players") or 0 for sd in ("home", "away")]
        for m in HEAVY_ROTATION.finditer(text):
            if max(changed) < ROTATION_HEAVY_MIN:
                bad.append(f"'{m.group(0)}' but the most changes either side made is {max(changed)} of 11: heavy rotation means {ROTATION_HEAVY_MIN}+; say the number instead")
    for m in XG_SENTENCE.finditer(text):
        a, b = float(m.group(1)), float(m.group(2))
        if a > b and XG_WORSE.search(m.group(0)):
            bad.append(f"xG sentence reads the numbers backwards ({a:+.2f} vs {b:+.2f}: the first side is BETTER, the sentence says worse/underperforming): {m.group(0).strip()[:120]}")
        elif a < b and XG_BETTER.search(m.group(0)):
            bad.append(f"xG sentence reads the numbers backwards ({a:+.2f} vs {b:+.2f}: the first side is WORSE, the sentence says better): {m.group(0).strip()[:120]}")
    for m in re.finditer(r"\b[Ee]xpected goals\b[^\n]{0,100}", text):         # decimals contain dots, so do not split on them
        if re.search(r"\bxG\b", m.group(0)) and not re.search(r"\bxG (difference|sources?|data)", m.group(0)):
            bad.append(f"the engine's expected goals are a MODEL estimate, not data xG: {m.group(0).strip()[:110]}")
    for line in text.splitlines():
        if line.lstrip().startswith("Odds challenge:"):
            if "odds_right" in line and re.search(r"\boverrat\w+", line):
                bad.append("Odds challenge says `odds_right` but the text says the odds overrate a side: pick `odds_overrate_home|away` or `unclear`, or reword")
            if re.search(r"odds_overrate_(home|away)", line) and re.search(r"supports? the odds|odds are right|odds' caution", line, re.I):
                bad.append("Odds challenge names an overrated side but also says the evidence supports the odds: the verdict and the text disagree")
    return bad


def _absentee_tag_warnings(facts: dict, text: str) -> list[str]:
    warns = []
    names = {x["name"] for side in ("home", "away") for x in facts["sides"][side]["absentees"]}
    for sentence in (x for ln in text.splitlines() for x in re.split(r"(?<=[.;])\s+", ln)):
        tags = re.findall(r"\[[^\]]+\]", sentence)
        if not tags or any(".absent." in t for t in tags):
            continue
        for n in names:
            if n in sentence:
                warns.append(f"{n} is discussed under {', '.join(tags)} but not the absentee tag: cite `[H.absent.{n}]` / `[A.absent.{n}]` exactly (a rotation or form tag does not describe an absence)")
    return warns



def _tag_number_warnings(report: dict, text: str) -> list[str]:
    """A signed decimal quoted next to ONE tag must appear in that tag's own lines (a goal difference under the table tag, or an xG number under the form tag, is a misattribution)."""
    b = oracle.brief(report)
    tag_text: dict[str, str] = {}
    for ln in oracle.format_brief(b).splitlines():
        for t in re.findall(r"\[[^\]]+\]", ln[:60]):
            tag_text[t] = tag_text.get(t, "") + " " + ln
    skip = ("**", "In plain words", "Recommended bet", "Draw:", "Goals:", "Lineups:", "Data audit")
    warns = []
    for line in text.splitlines():
        if line.startswith(skip):
            continue
        for sentence in re.split(r"(?<=[\w\]%)])\.\s+(?=[A-Z\[])|;\s+", line):
            for nm in re.finditer(r"(?<![\d.])[+-]?\d+\.\d+(?![\d%])", sentence):
                after = re.search(r"\[[^\]]+\]", sentence[nm.end():])          # a tag follows the claim it supports
                before = list(re.finditer(r"\[[^\]]+\]", sentence[:nm.start()]))
                tag = after.group(0) if after else (before[-1].group(0) if before else None)
                if tag is None or tag in ("[BASELINE]", "[LINEUPS]") or tag not in tag_text:
                    continue
                num = nm.group(0)
                if num.lstrip("+") not in tag_text[tag].replace("+", "") and num not in tag_text[tag]:
                    warns.append(f"{num} is quoted under {tag} but does not appear in that tag's lines: put each [TAG] right AFTER the claim it supports ('goal difference +0.5 vs -0.7 [H.form]'), and quote numbers only from their own tag line")
    return list(dict.fromkeys(warns))


def _fact_warnings(report: dict, text: str, rows: list) -> list[str]:
    """Factual claims the data cannot back. A wrong score against a known opponent is a FAIL row; the rest are warnings to verify against the tag lines."""
    facts = extract_facts(report)
    results: dict[str, set[tuple[int, int]]] = {}
    for side in ("home", "away"):
        for r in facts["sides"][side]["form"]:
            if r["gf"] is not None:
                results.setdefault(norm(r["opponent"]), set()).add((r["gf"], r["ga"]))
    warns, wrong = [], []
    for m in SCORE_CLAIM.finditer(text):
        a, b, conn, opp = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4).strip()
        key = norm(opp)
        known = results.get(key) or next((v for k, v in results.items() if key and (key in k or k in key)), None)
        if known is None:
            if conn in ("in", "at"):
                warns.append(f"'{m.group(0)}': {opp} is not an opponent in either side's form data (invented, or a venue)")
            else:
                wrong.append(f"'{m.group(0)}': {opp} is not an opponent in the form data")
        elif (a, b) not in known and (b, a) not in known:
            wrong.append(f"'{m.group(0)}': the form data has {sorted(known)} against {opp}")
    rows.append(("scorelines quoted against opponents exist in the form data", not wrong, "; ".join(wrong)))
    rows.append(("recent-form counts quoted match the form data", *_form_counts_ok(facts, text)))
    rows.append(("unbeaten / winless / streak claims match the form letters", *_streak_claims_ok(facts, text, report)))
    for m in CHARACTER_WORDS.finditer(text):
        warns.append(f"'{m.group(0)}' characterises beyond the data: replace it with the number or tag line it rests on")
    managers = [norm(facts["sides"][sd]["manager"]) for sd in ("home", "away") if facts["sides"][sd]["manager"]]
    for m in MANAGER_CLAIM.finditer(text):
        name = norm(m.group(1))
        if name and not any(name in mg or mg in name for mg in managers) and not any(norm(w) in mg for w in m.group(1).split() for mg in managers):
            warns.append(f"manager '{m.group(1)}' is not in the data (the tags give: {', '.join(facts['sides'][sd]['manager'] for sd in ('home', 'away') if facts['sides'][sd]['manager']) or 'no manager'})")
    absent = [norm(a["name"]) for sd in ("home", "away") for a in facts["sides"][sd]["absentees"]]
    teams = {norm(facts["home"]), norm(facts["away"])}
    for m in MISSING_CLAIM.finditer(text):
        name = norm(re.sub(r"['\u2019]s$", "", m.group(1)))
        if name and name not in teams and not any(name in a or a in name or any(norm(w) in a for w in m.group(1).split() if len(w) > 3) for a in absent):
            warns.append(f"'{m.group(0)}': named as missing but not in either side's absentee list")
    status = {norm(a["name"]): a["status"] for a in lineup_picture(facts)["home"]["absentees"] + lineup_picture(facts)["away"]["absentees"]}
    for seg in re.finditer(r"starters? out[:\s-]+([^.;\n]*)", text, re.I):
        for nm, st in status.items():
            if st != "starter" and nm and nm in norm(seg.group(1)):
                warns.append(f"a player is listed under 'starters out' but is classified {st} (not a starter): {nm}")
    for m in re.finditer(r"explained by (?![\[\d])([^.\n]{0,60})", text, re.I):
        if not re.search(r"\[[^\]]+\]|\d", m.group(1)):
            warns.append(f"'explained by {m.group(1).strip()}': an explanation for a gap must cite a tag or a number, not a mechanism the data does not show")
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        for tag, side in (("[H.form]", "home"), ("[A.form]", "away")):
            if tag not in sentence or ("[H.form]" in sentence and "[A.form]" in sentence):
                continue                                  # a sentence comparing both sides is not checked
            res = [r["result"] for r in facts["sides"][side]["form"][:6] if r["result"]]
            if len(res) < 5:
                continue
            wins, losses = res.count("W"), res.count("L")
            letters = "".join(res)
            if FORM_GOOD.search(sentence) and wins <= 2:
                warns.append(f"'{FORM_GOOD.search(sentence).group(0)}' for the {side} side, but its last {len(res)} results are {letters} ({wins} win{'s' if wins != 1 else ''}): say what the numbers show")
            if FORM_BAD.search(sentence) and losses <= 1 and wins >= 4:
                warns.append(f"'{FORM_BAD.search(sentence).group(0)}' for the {side} side, but its last {len(res)} results are {letters} ({wins} wins): say what the numbers show")
    h2h = facts["h2h"]
    for sentence in _sentences(text):
        if H2H_CUE.search(sentence) and (v := VENUE_OF_MEETINGS.search(sentence)):
            warns.append(f"'{v.group(0)}' about head-to-head meetings: the H2H counts are wins by the fixture's home TEAM and away TEAM, the venues of past meetings are not in the data")
    warns += _absentee_count_warnings(facts, text)
    cites = list(re.finditer(r"\[H2H\]", text))
    if cites and h2h and h2h.get("n"):
        # one citation that quotes the full record (with its sample size) is enough; further bare [H2H] mentions may refer back to it
        quoted = any(h2h["n"] in {int(x) for x in re.findall(r"\d+", text[max(0, m.start() - 110):m.end() + 40])} for m in cites)
        if not quoted:
            warns.append(f"head-to-head quoted without the full record: the tag says home {h2h['home_wins']}, draws {h2h['draws']}, away {h2h['away_wins']} (n={h2h['n']})")
    return warns


def format_audit(r: dict) -> str:
    lines = ["| Check | Result | Detail |", "|---|---|---|"] + [f"| {n} | {'ok' if ok else 'FAIL'} | {d or '-'} |" for n, ok, d in r["rows"]]
    lines += [""] + [f"WARN: {w}" for w in r.get("warnings", [])]
    return "\n".join(lines + ["", "Result: " + ("clean" if r["clean"] else "fix the FAIL rows, then re-run the audit") + (f" ({len(r['warnings'])} warning(s) to verify)" if r.get("warnings") else "")])
