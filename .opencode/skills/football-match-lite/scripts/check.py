#!/usr/bin/env python3
"""Checks an analyst answer for errors and inconsistencies (Python standard library only). Run it before you finish and fix every FAIL.

    python3 check.py answer.md report.json            (a forecasts.jsonl as a third argument is optional)

answer.md       your answer in the skill's template
report.json     the match report you analysed
forecasts.jsonl the log file you wrote with calc.py --log (the LAST entry for this match is the one checked)

It checks that the answer agrees with your own calc.py numbers (probabilities, expected goals, odds, the probability of the bet), that it is complete and symmetric
(all lenses, both sides, both cases, at least three data links), that it keeps its own rules (one bet, confidence matches probability, a disagreement check when you
differ from the bookmaker by 8 points or more, no invented rounds or guarantees) and that the numbers it quotes as facts appear in the report. FAIL means fix it;
WARN means check it. It does not judge whether your football reasoning is right.
"""

from __future__ import annotations

import io
import json
import re
import sys
import contextlib
import importlib.util
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


calc, facts = _load("calc"), _load("facts")

LENSES = {"luck": ("luck", "performance"), "attack": ("attack",), "defence": ("defence", "defense"), "style": ("style", "matchup"), "opposition": ("opposition",), "stakes": ("stakes",),
          "schedule": ("schedule", "fatigue"), "physiology": ("physiology", "load"), "personnel": ("personnel",), "environment": ("environment",)}
RATING_MOVE_TOL = 0.05                     # without odds the rating anchor moves ONLY for team news: on the 28 scored matches of Oct 2026 every share of the decider's other moves made the forecasts worse (Brier 0.442 kept at the anchor, 0.451 half the move, 0.466 all of it; 0.474 v 0.490 without Spain and Belarus), and luck or 5-game moves were accepted in some runs and rejected in others
NOT_TEAM_NEWS = re.compile(r"\bluck|unlucky|lucky|regress|rebound|finishing|save (?:rate|%|percentage)|saves? \d|over-?perform|under-?perform|scor(?:ed|ing) rate|goals? (?:minus|above|below|over) (?:x?g|expected)|\bform\b|\b\d+-game|last \d+ games|shots? on target|big chances|chance creation|\bSOT\b|set[- ]piece|press|tactic|midfield|matchup|\bxg anchor|\bshrunk|composite|midpoint|average of the|judge?ment|keeper arithmetic", re.I)
ADJ_LINE = re.compile(r"expected goals adjustment[^:\n]{0,40}:([^\n]*)", re.I)
BET_DEVIATION_POINTS = 5.0                  # a bet this far under the calculator's suggestion (any probability) needs a 'Why not <suggestion>:' line, so the same numbers give the same pick unless a reason is named
NEEDED_SECTIONS = ("Symmetric table", "Data links", "Case for", "My view", "Own odds", "Best bet", "Draw risk", "Underlying evidence", "From the report", "Own knowledge", "Risks")
GUARANTEE = re.compile(r"\b(guarantee[sd]?|sure thing|can't lose|cannot lose|risk[- ]free|lock(?:ed)? in|stake \d|units?\b|bet \d+% of)\b", re.I)
INVENTED_COMPETITION = re.compile(r"\b(round|matchday|game ?week|gameweek) (\d+)( of (\d+))?\b", re.I)
PCT = r"(\d+(?:\.\d+)?)"


def _name_words(team: str) -> list[str]:
    """The words of a team name that identify it ('HNK Hajduk Split' -> Hajduk, Split; 'AFC Ajax' -> Ajax): club prefixes of 3 letters or fewer are skipped."""
    w = [x for x in re.split(r"\s+", team.strip()) if len(x) > 3]
    return w or team.split()[:1]


def norm(s) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(c))
    return "".join(c for c in s.lower() if c.isalnum())


def over25_fair(report: dict) -> float | None:
    """The market's fair probability (0-1) of over 2.5 goals from the report's totals prices, or None when it holds none."""
    m = report.get("match") if isinstance(report.get("match"), dict) else {}
    o = m.get("betting_odds") or m.get("sofascore_betting_odds") or {}
    if not isinstance(o, dict):
        return None
    ov, un = o.get("over_2_5_fair_pct"), o.get("under_2_5_fair_pct")
    if isinstance(ov, (int, float)) and isinstance(un, (int, float)) and ov + un > 0:
        return ov / (ov + un)
    ro, ru = o.get("over_2_5_odds"), o.get("under_2_5_odds")
    if isinstance(ro, (int, float)) and isinstance(ru, (int, float)) and ro > 1 and ru > 1:
        return (1 / ro) / (1 / ro + 1 / ru)
    return None


def bookmaker(report: dict) -> list[float] | None:
    m = report.get("match") if isinstance(report.get("match"), dict) else {}
    o = m.get("betting_odds") or m.get("sofascore_betting_odds") or {}
    if not isinstance(o, dict):
        return None
    fair = [o.get(k) for k in ("home_win_fair_pct", "draw_fair_pct", "away_win_fair_pct")]
    if not all(isinstance(v, (int, float)) for v in fair):
        raw = [o.get(k) for k in ("home_win_odds", "draw_odds", "away_win_odds")]
        if not all(isinstance(v, (int, float)) and v > 1 for v in raw):
            return None
        fair = [100 / v for v in raw]
    t = sum(fair)
    return [100 * v / t for v in fair]


def value_label(edge: float, need: float) -> str:
    """REAL from the bar, THIN above zero, NONE at zero or below. The edge is compared as printed (one decimal), so '+0.0' is NONE in every script."""
    e = round(edge, 1)
    return "REAL" if e >= need else "THIN" if e > 0 else "NONE"


def guarantee_hit(answer: str) -> str:
    """The first guarantee or staking phrase, ignoring 'guarantee' words that are negated ('not a guaranteed recovery', 'rather than a guaranteed ...')."""
    for m in GUARANTEE.finditer(answer):
        if m.group(1).lower().startswith("guarantee") and re.search(r"\b(?:not|no|never|without|nor|rather than|instead of|isn't|aren't|n't)\b[^.;\n]{0,30}$", answer[max(0, m.start() - 40):m.start()], re.I):
            continue
        return m.group(0)
    return ""


def bet_probability(bet: str, home: str, away: str, a: dict) -> float | None:
    """The probability (in %) that calc.py's grid gives for a named bet, or None when the bet is not one of the markets it prices."""
    first = re.split(r",\s|\.\s", bet.strip())[0]
    if first != bet.strip() and not re.match(r"^\s*double chance\s*$", first, re.I):
        got = bet_probability(first, home, away, a)                  # "Draw or Scotland, double chance, confidence low ..." is the bet before the first comma
        if got is not None:
            return got
    b, h, w = norm(re.sub(r"^\s*double chance\s*[,:\-]?\s*", "", bet, flags=re.I)), norm(home), norm(away)
    ph, pd, pa = a["home"], a["draw"], a["away"]
    if "over25" in b:
        return 100 * a["over_2_5"]
    if "under25" in b:
        return 100 * (1 - a["over_2_5"])
    if "bothteamstoscore" in b or b.startswith("btts"):
        return 100 * ((1 - a["btts"]) if b.endswith("no") else a["btts"])
    if "eithersidetowin" in b or "homeoraway" in b or b.endswith("nodraw"):
        return 100 * (ph + pa)
    if b == f"{h}ordraw" or b == f"drawor{h}" or b in ("homeordraw", "draworhome", "1x"):
        return 100 * (ph + pd)
    if b == f"drawor{w}" or b == f"{w}ordraw" or b in ("draworaway", "awayordraw", "x2"):
        return 100 * (pd + pa)
    if b == "draw":
        return 100 * pd
    if b in (f"{h}towin", f"{h}win", h, "homewin"):
        return 100 * ph
    if b in (f"{w}towin", f"{w}win", w, "awaywin"):
        return 100 * pa
    return None


def section(text: str, label: str) -> str:
    """The text of the line or block that starts with `label` (up to the next template label)."""
    labels = "|".join(re.escape(x) for x in ("Symmetric table", "Media focus", "Specialist notes", "Advocates", "Deciding factors", "Data links", "Case for", "My view", "Own odds", "Best bet", "Draw risk", "Underlying evidence", "From the report", "Own knowledge", "Risks"))
    m = re.search(rf"(?:^|\n)[*#\s]*{re.escape(label)}[^\n]*(?:\n(?![*#\s]*(?:{labels}))[^\n]*)*", text, re.I)
    return m.group(0) if m else ""


def sheet_of(report_path: str) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        facts.main(report_path, deep=True)
    return buf.getvalue()


def numbers(text: str) -> list[str]:
    return re.findall(r"(?<![\w.])\d+(?:\.\d+)?", text)


def entry_from_answer(answer: str, home: str, away: str, report: dict) -> dict | None:
    """No saved forecast: rebuild the calculator entry from the answer itself (its headline expected goals and its Best bet line)."""
    xg = re.search(rf"expected goals {PCT}\s*[-–]\s*{PCT}", answer, re.I)
    if not xg:
        return None
    lh, la = float(xg.group(1)), float(xg.group(2))
    a = calc.analyse(lh, la)
    rec = calc.recommend(a, home, away)
    bl = [ln for ln in answer.splitlines() if re.match(r"[*#\s|]*best bet", ln, re.I) and re.search(r"\d\s*%", ln)]
    bm = re.search(rf"^\**\s*(.+?)\s*\(\s*{PCT}\s*%(?:[,;][^)]*)?\)", re.sub(r"^[*#\s|]*best bet:?[*\s]*", "", bl[0], flags=re.I)) if bl else None
    return {"home": home, "away": away, "lam_home": lh, "lam_away": la, "bet": re.sub(r"\s*\([^)]*\)", "", bm.group(1)).strip(" *:-") if bm else rec["selection"], "suggested": rec["selection"]}


def _dc_reason_has_fact(answer: str) -> bool:
    """The 'Why a double chance:' line names a fact with a number: a count, record or rate that is not one of the answer's own percentages or the 2.5 goals line."""
    m = re.search(r"why a double chance\s*:([^\n]*)", answer, re.I)
    if not m:
        return False
    line = re.sub(r"\d+(?:\.\d+)?\s*%", " ", m.group(1))          # your own probabilities restate the view, they are not evidence
    line = re.sub(r"\b2\.5\b|\b1X\b|\bX2\b", " ", line, flags=re.I)
    return bool(re.search(r"\d", line))


def news_window_label(report: dict) -> str:
    """Same rule as facts.news_window: a STALE REPORT (7+ days before kickoff) or a LATE-NEWS WINDOW (lineups unconfirmed, kickoff within 24 h of the scrape). Empty when neither."""
    import datetime
    m = report.get("match") if isinstance(report.get("match"), dict) else {}
    def t(x):
        try:
            v = datetime.datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        except ValueError:
            return None
        return v if v.tzinfo else v.replace(tzinfo=datetime.timezone.utc)
    ko, gen = t(m.get("kickoff_utc")), t(report.get("generatedAt"))
    if ko is None or gen is None:
        return ""
    hours = (ko - gen).total_seconds() / 3600
    if hours >= 7 * 24:
        return f"STALE REPORT ({hours / 24:.0f} days before kickoff)"
    if not m.get("lineup_confirmed") and 0 <= hours <= 24:
        return f"LATE-NEWS WINDOW ({hours:.0f} h, lineups unconfirmed)"
    return ""


def _check_full(answer: str, report_path: str, log_path: str | None = None) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    add = lambda status, name, detail="": rows.append((status, name, detail))
    report = _load("blind").blind(json.loads(Path(report_path).read_text(encoding="utf-8")))[0]     # market-independent: the answer is checked as if the report had no price
    m = report.get("match") if isinstance(report.get("match"), dict) else {}
    home, away = str(m.get("home_team") or "Home"), str(m.get("away_team") or "Away")
    entries = []
    try:
        entries = [json.loads(x) for x in Path(log_path).read_text(encoding="utf-8").splitlines() if x.strip()] if log_path else []
    except (OSError, ValueError):
        pass
    mine = [e for e in entries if isinstance(e, dict) and norm(e.get("home")) == norm(home) and norm(e.get("away")) == norm(away)]
    if mine:
        e = mine[-1]
        add("ok", "forecast logged for this match", f"expected goals {e['lam_home']}-{e['lam_away']}")
    else:
        e = entry_from_answer(answer, home, away, report)
        if e is None:
            add("FAIL", "expected goals found in the headline", "no 'expected goals X-Y' in the headline: the checker rebuilds the calculator numbers from it (no forecast is saved)")
            return rows
        add("ok", "expected goals read from the headline (no forecast is saved)", f"{e['lam_home']}-{e['lam_away']}")
    a = calc.analyse(e["lam_home"], e["lam_away"])

    missing = [s for s in NEEDED_SECTIONS if s.lower() not in answer.lower()]
    add("FAIL" if missing else "ok", "all template sections present", ", ".join(missing))

    # expected goals against the report's own xG anchor: a big move needs the arithmetic and the reason
    def _xgpg(side: str, key: str):
        x = report.get("insights", {}).get(f"{side}_xg_estimate") if isinstance(report.get("insights"), dict) else None
        x = x if isinstance(x, dict) else {}
        try:
            n, v = float(x.get("sample_size")), float(x.get(key))
            return v / n if n > 0 else None
        except (TypeError, ValueError):
            return None
    hf, ha, af, aa = _xgpg("home", "xg_for"), _xgpg("home", "xg_against"), _xgpg("away", "xg_for"), _xgpg("away", "xg_against")
    facts.set_venue(report)
    rating = facts.rating_anchor(report.get("insights") if isinstance(report.get("insights"), dict) else {}, report.get("match"))
    if rating or None not in (hf, ha, af, aa):
        if rating:                                                  # club class counts: the rating anchor is the starting point (it scored about like the bookmaker on held-out matches)
            anchor_h, anchor_a, kind = rating[0], rating[1], "rating anchor"
        else:
            (anchor_h, anchor_a), kind = facts.venue_anchor(hf, aa, af, ha), "xG anchor"
        moved = [(n, e["lam_home" if n == home else "lam_away"], an) for n, an in ((home, anchor_h), (away, anchor_a)) if abs(e["lam_home" if n == home else "lam_away"] - an) > (RATING_MOVE_TOL if rating else 0.5)]
        adjs = ADJ_LINE.findall(answer)
        if moved and not adjs:
            add("FAIL", f"a big move from the {kind} needs an 'Expected goals adjustment:' line", "; ".join(f"{n}: your {lam:.2f} v {kind} {an:.2f} ({lam - an:+.2f})" for n, lam, an in moved) + ": show the arithmetic and the reason for each change (an absence is capped at the absentee's share of team xG minus what the replacement adds)")
        elif moved and rating:
            team_news = lambda t: re.search(r"absen|injur|suspen|ruled out|unavailable|confirmed|line-?up|starting xi|\bout\b", t, re.I)
            bad = [t.strip()[:90] for t in adjs if not team_news(t) or NOT_TEAM_NEWS.search(t)]
            if bad:
                add("FAIL", "a move from the rating anchor rests on form or scoring rates (or luck, or a 5-game sample), not on team news",
                    "not team news: " + " | ".join(bad) + ". " + "; ".join(f"{n}: your {lam:.2f} v rating anchor {an:.2f} ({lam - an:+.2f})" for n, lam, an in moved) + ": in 4 test batches (16 national matches) the judgment lost to the rating anchor (Brier lift -0.016 per match), almost all from the one big form-based move: Belarus 3.59 cut to 2.30 on a 10-game scoring rate, then 4-0; the rating already carries class and results, so move it for a confirmed absence or lineup, or keep it")
            else:
                add("ok", f"expected goals sit near the {kind} or the move is explained", f"anchors {anchor_h:.2f}-{anchor_a:.2f}, yours {e['lam_home']}-{e['lam_away']}")
        else:
            add("ok", f"expected goals sit near the {kind} or the move is explained", f"anchors {anchor_h:.2f}-{anchor_a:.2f}, yours {e['lam_home']}-{e['lam_away']}")

    # headline equals the calculator
    head = re.search(rf"{PCT}%\s*/\s*Draw\s*{PCT}%\s*/\s*[^\n]*?{PCT}%", answer)
    if head:
        got = [float(head.group(i)) for i in (1, 2, 3)]
        want = [100 * a["home"], 100 * a["draw"], 100 * a["away"]]
        ok = all(abs(g - w) <= 0.15 for g, w in zip(got, want))
        add("ok" if ok else "FAIL", "headline probabilities equal calc.py's", f"written {got} vs calc.py {[round(x, 1) for x in want]}")
    else:
        add("FAIL", "headline probabilities equal calc.py's", "no 'H% / Draw D% / A%' headline found")
    xg = re.search(rf"expected goals {PCT}\s*[-–]\s*{PCT}", answer, re.I)
    if xg:
        ok = abs(float(xg.group(1)) - e["lam_home"]) <= 0.06 and abs(float(xg.group(2)) - e["lam_away"]) <= 0.06
        add("ok" if ok else "FAIL", "expected goals equal the logged pair", f"written {xg.group(1)}-{xg.group(2)} vs logged {e['lam_home']}-{e['lam_away']}")
    else:
        add("WARN", "expected goals equal the logged pair", "no 'expected goals X-Y' found in the headline")

    # own odds equal 1/p
    od = re.search(rf"home\s*{PCT}\D+draw\s*{PCT}\D+away\s*{PCT}", section(answer, "Own odds"), re.I)
    if od:
        got = [float(od.group(i)) for i in (1, 2, 3)]
        want = [1 / a["home"], 1 / a["draw"], 1 / a["away"]]
        ok = all(abs(g - w) <= 0.03 for g, w in zip(got, want))
        add("ok" if ok else "FAIL", "own odds are 1 / your probabilities", f"written {got} vs {[round(x, 2) for x in want]}")
    else:
        add("FAIL", "own odds are 1 / your probabilities", "no 'home x, draw y, away z' in the Own odds line")

    # exactly one best bet; it is the logged one; its probability is right; confidence matches
    bet_lines = [ln for ln in answer.splitlines() if re.match(r"[*#\s|]*best bet", ln, re.I) and re.search(r"\d\s*%", ln)]
    bets = [re.sub(r"^[*#\s|]*best bet:?[*\s]*", "", ln, flags=re.I) for ln in bet_lines]
    add("ok" if len(bets) == 1 else "FAIL", "exactly one Best bet line", f"{len(bets)} found")
    line = bets[0] if bets else ""
    bm = re.search(rf"^\**\s*(.+?)\s*\(\s*{PCT}\s*%(?:[,;][^)]*)?\)", line)
    conf = re.search(r"confidence\W{0,3}(low|medium|high)", line + "\n" + section(answer, "Best bet"), re.I)
    if bm:
        text_bet, said = re.sub(r"\s*\([^)]*\)", "", bm.group(1)).strip(" *:-"), float(bm.group(2))
        add("ok" if norm(text_bet) == norm(e.get("bet")) or norm(e.get("bet")) in norm(text_bet) or norm(text_bet) in norm(e.get("bet")) else "FAIL", "the headline bet is the logged bet", f"answer '{text_bet}' vs log '{e.get('bet')}'")
        want = bet_probability(text_bet, home, away, a)
        if want is None:
            add("WARN", "the bet's probability equals the grid's", f"'{text_bet}' is not a market calc.py prices (1X2, double chance, over/under 2.5, both teams to score): state how you priced it")
        else:
            add("ok" if abs(said - want) <= 0.6 else "FAIL", "the bet's probability equals the grid's", f"written {said}% vs calc.py {want:.1f}%")
        gline = re.search(rf"^[*#\s|]*goals bet:?[*\s]*(.+?)\s*\(\s*{PCT}\s*%", answer, re.I | re.M)
        gsel, gpct = calc.goals_bet(a)
        if not gline:
            add("FAIL", "a Goals bet line gives the likeliest goals selection", f"no 'Goals bet:' line: calc.py's goals bet is {gsel} {gpct}% (over/under 2.5 and both teams to score are always priced, whatever the main bet)")
        else:
            gtext, gsaid = gline.group(1).strip(" *:-"), float(gline.group(2))
            gwant = bet_probability(gtext, home, away, a)
            same = norm(gtext).replace("goals", "") == norm(gsel).replace("goals", "")
            add("ok" if same and gwant is not None and abs(gsaid - gwant) <= 0.6 else "FAIL", "a Goals bet line gives the likeliest goals selection",
                f"written {gtext} {gsaid}% vs calc.py's goals bet {gsel} {gpct}%" + ("" if same else ": name the likeliest of over 2.5, under 2.5, both score yes and no"))
        draw_pct = 100 * a["draw"]
        if "eithersidetowin" in norm(text_bet) or "nodraw" in norm(text_bet):
            add("FAIL", "never 'either side to win' (it loses on the draw)", f"your draw is {draw_pct:.0f}%: bet {home} or draw / draw or {away} instead")
        elif want is not None and want < 50 and draw_pct >= 25 and "draw" not in norm(text_bet) and not re.search(r"draw cover\s*:", answer, re.I):
            add("FAIL", "a single-outcome bet below 50% needs a draw cover", f"{text_bet} at {want:.0f}% with your draw at {draw_pct:.0f}%: add a 'Draw cover:' line saying why this match will probably not end level, or bet something else")
        else:
            add("ok", "draw cover (no 'either side', single bets below 60% explained)", f"draw {draw_pct:.0f}%")
        fav_ = home if a["home"] >= a["away"] else away
        if want is not None and want < 60 and norm(text_bet) in (f"{norm(fav_)}towin", f"{norm(fav_)}win", norm(fav_)) and not re.search(r"underdog first\s*:", answer, re.I):
            add("FAIL", "a favourite-to-win bet below 60% needs an 'Underdog first:' line", f"{text_bet} at {want:.0f}%: say how the match goes if the underdog scores first (calc.py's 'If the underdog scores first' line against the sheet's IF THE UNDERDOG SCORES record): does {fav_} come back, settle for a draw or lose, and does the bet still hold (Alavés 1-1 Málaga, 2026-10-23: Málaga scored first and the win bet lost)")
        nb0 = norm(text_bet)
        goals_bet ="over25" in nb0 or "under25" in nb0 or "bothteams" in nb0 or nb0.startswith("btts")
        if goals_bet and want is not None:
            r1 = calc.recommend(a, home, away)
            if want < r1["pick_1x2_pct"] - 0.05:
                add("FAIL", "a goals bet as the main pick beats the best 1X2 or double-chance pick", f"{text_bet} at {want:.1f}% is below {r1['pick_1x2']} at {r1['pick_1x2_pct']:.1f}%: a goals bet is the main pick only when its probability is higher (otherwise keep it as the separate Goals bet)")
        single = nb0 in (f"{norm(home)}towin", f"{norm(away)}towin", "draw", f"{norm(home)}win", f"{norm(away)}win", norm(home), norm(away))
        if single and want is not None and want < 100 * max(a["home"], a["draw"], a["away"]) - 0.5:
            add("FAIL", "a single-outcome bet is your most likely outcome", f"{text_bet} is {want:.0f}% but your most likely outcome is {100 * max(a['home'], a['draw'], a['away']):.0f}%: a pick against your own favourite is a contrarian bet; pick the likeliest outcome or a double chance that covers it (backing against the market loses more often than not)")
        nb = norm(text_bet)
        is_dc = nb in (f"{norm(home)}ordraw", f"drawor{norm(home)}", f"{norm(away)}ordraw", f"drawor{norm(away)}", "homeordraw", "draworaway", "draworhome", "awayordraw", "1x", "x2")
        if is_dc and want is not None:
            best_single = 100 * max(a["home"], a["draw"], a["away"])
            if want > 78:
                add("FAIL", "a double chance is not too short a price", f"{text_bet} at {want:.0f}% pays almost nothing: bet the outcome you believe in, or another market")
            elif not _dc_reason_has_fact(answer):
                add("FAIL", "a double chance needs a reason with a number", f"best single outcome {best_single:.0f}%: add a 'Why a double chance:' line naming the specific risk to the single outcome WITH its number (a stat, an absence, a record), or bet the single outcome; a double chance is never the default")
            else:
                add("ok", "a double chance is justified", f"best single outcome {best_single:.0f}%")
        nw = news_window_label(report)
        if conf and conf.group(1).lower() == "high" and nw:
            add("FAIL", "no high confidence on stale or late-news evidence", f"{nw}: write medium or low (the evidence can still change)")
        if conf and conf.group(1).lower() == "high" and (want or said) < 70:
            add("FAIL", "confidence matches probability", f"HIGH confidence on a {want or said:.0f}% bet: high needs about 70% and a named edge")
        else:
            add("ok" if conf else "WARN", "confidence matches probability", "no confidence (low/medium/high) found" if not conf else f"{conf.group(1)} on {want or said:.0f}%")
    else:
        add("FAIL", "the headline bet is the logged bet", "could not read 'Best bet: <bet> (NN%)'")

    if bm and want is not None:
        sug = bet_probability(str(e.get("suggested") or ""), home, away, a)
        if sug is not None and sug - want >= BET_DEVIATION_POINTS and norm(str(e.get("suggested") or "")) != norm(text_bet):
            if re.search(r"why not\b", answer, re.I):
                add("ok", "a bet far below the calculator's suggestion explains why", f"{text_bet} {want:.0f}% v suggested {e.get('suggested')} {sug:.0f}%")
            else:
                add("FAIL", "a bet far below the calculator's suggestion explains why", f"{text_bet} at {want:.0f}% while calc.py suggests {e.get('suggested')} at {sug:.0f}%: add a 'Why not {e.get('suggested')}:' line giving the evidence that makes the lower bet better")
        view = section(answer, "My view")
        for t, o in ((home, away), (away, home)):
            expects = re.search(rf"\b(?:expect|predict|call|lean|see)\w*[^.\n]*\b{re.escape(t)}\b[^.\n]*\bwin\b|\b{re.escape(t)}\b[^.\n]*\bwin\b[^.\n]*\b(?:expected|my call)\b", view, re.I)
            if expects and norm(o) in norm(text_bet) and norm(t) not in norm(text_bet):
                add("WARN", "the bet agrees with the view", f"'My view' expects {t} to win but the bet backs {o}: explain the gap or change the bet")
    block = section(answer, "Best bet")
    extra = re.findall(rf"{PCT}\s*%", block)
    runner = re.search(r"\b(better|instead|alternatively|or (?:the )?(?:double chance|draw no bet)|runner-?up)\b[^\n]*?{pct}\s*%".replace("{pct}", PCT), block, re.I)
    add("FAIL" if runner else "ok", "one bet only (a runner-up is mentioned without a second percentage)", f"second bet with a percentage in the Best bet block: '{runner.group(0)[:90]}'" if runner else "")

    # no disagreement check against a bookmaker: the analysis is price-free (removed 2026-10-25)

    # symmetry
    table = section(answer, "Symmetric table")
    rows_t = [ln for ln in table.splitlines() if ln.strip().startswith(("-", "|", "*", "1", "2", "3", "4", "5", "6", "7", "8", "9"))]
    labels = [re.split(r"[:|]", re.sub(r"^[|*#\-\s\d.)]+", "", ln), maxsplit=1)[0].lower() for ln in rows_t]          # the row's label: the text before the first colon or cell border
    miss_l = [k for k, words in LENSES.items() if not any(w in lab for w in words for lab in labels)]
    add("FAIL" if miss_l else "ok", "symmetric table covers every lens", ", ".join(miss_l))
    one_sided = [ln.strip()[:70] for ln in rows_t if (norm(home) in norm(ln)) != (norm(away) in norm(ln)) and "vs" not in ln.lower()]
    add("WARN" if len(one_sided) > 2 else "ok", "every table row speaks about BOTH sides", f"{len(one_sided)} rows name only one side: " + "; ".join(one_sided[:3]) if len(one_sided) > 2 else "")
    links = len(re.findall(r"=>|→|⇒", section(answer, "Data links")))
    add("ok" if links >= 3 else "FAIL", "at least three data links (signal + signal => meaning)", f"{links} found")
    ch, ca = section(answer, f"Case for {home}"), section(answer, f"Case for {away}")
    if ch and ca:
        r = len(ch) / max(len(ca), 1)
        add("ok" if 0.6 <= r <= 1.67 else "FAIL", "both cases are argued to similar depth", f"home case {len(ch)} characters, away case {len(ca)} (ratio {r:.2f}; keep within 0.6-1.67)")
    else:
        add("FAIL", "both cases are argued to similar depth", "a 'Case for {team}' block is missing for " + (home if not ch else away))

    # rules
    _g = guarantee_hit(answer)
    add("FAIL" if _g else "ok", "no guarantees or staking advice", _g)
    sheet = sheet_of(report_path)
    inv = [x.group(0) for x in INVENTED_COMPETITION.finditer(answer) if x.group(0).lower() not in sheet.lower() and x.group(0).lower() not in json.dumps(report).lower()]
    add("FAIL" if inv else "ok", "no invented rounds or matchdays", ", ".join(inv))
    has_flank = bool(re.search(r"flank map|left.{0,40}right|\bright (?:wing|back|flank|side)|\bleft (?:wing|back|flank|side)", answer, re.I))
    add("ok" if has_flank else "WARN", "flanks are analysed for both sides (left, centre, right, mirror pairs)", "" if has_flank else "no flank map: place each side's wide players and pair each attack with the opposite full-back")
    mc_words = ("sharpness", "form", "system", "morale", "rotation", "opponent", "importance", "bench")
    mc_found = [w for w in mc_words if re.search(w, answer, re.I)]
    has_mc = bool(re.search(r"manager'?s checklist", answer, re.I))
    no_mc = "no Manager's checklist block"
    add("ok" if has_mc and len(mc_found) >= 7 else "WARN", "the manager's checklist covers the eight items for both sides", "" if has_mc and len(mc_found) >= 7 else f"{no_mc if not has_mc else 'items missing: ' + ', '.join(w for w in mc_words if w not in mc_found)}: add one short line per item (fitness and sharpness, form, system fit, morale, availability and rotation, opponent setup, importance, bench) for each side")
    df = section(answer, "Deciding factors")
    ok_df = bool(df) and sum(bool(re.search(w, df, re.I)) for w in ("team news|injur|absen", "tactical|matchup|shape", "xg|shot|stats|set.piece", "home|away|venue", "motivation|stakes|context|title|relegation")) >= 3
    add("ok" if ok_df else "WARN", "the deciding factors name the highest-priority areas", "" if ok_df else "no 'Deciding factors:' line naming at least three of: team news, tactical matchup, underlying stats, home v away split, motivation (then the secondary adjustments)")
    sb = bool(re.search(r"substitut", answer, re.I)) and bool(re.search(r"bench|impact|come on|comes on|rested|taken off|subbed", answer, re.I))
    add("ok" if sb else "WARN", "substitution habits are covered", "" if sb else "no 'Substitutions:' line: who comes on, who is taken off early, timing and scoreline, bench impact (say the sample is thin)")
    hv = bool(re.search(r"home v away", answer, re.I)) and bool(re.search(r"intensity|initiative", answer, re.I)) and bool(re.search(r"cautious|compact|transition", answer, re.I))
    add("ok" if hv else "WARN", "home v away style and intensity are covered", "" if hv else "no 'Home v away:' line on initiative, pressing, caution and intensity at this venue, and whether game state or stakes reverse the default")
    notes = sorted(Path(report_path).parent.glob("notes/*.md"))
    if notes:
        cited = bool(re.search(r"specialist notes\s*:", answer, re.I)) and all(re.search(re.escape(n.stem.replace("-", "[- ]")), answer, re.I) or re.search(n.stem.split("-")[0], answer, re.I) for n in notes)
        add("ok" if cited else "FAIL", "specialist notes are cited (accepted or rejected with a reason)", "" if cited else f"{len(notes)} note(s) exist ({', '.join(n.name for n in notes)}): add a 'Specialist notes:' line naming each, what it favours, its strength and the xG change you accepted or rejected")
    vm = re.search(r"value\s*:\**\s*\**(real|thin|none|unmeasured)\b", answer, re.I)
    if not vm:
        add("FAIL", "a final Value: line is given", "add 'Value: UNMEASURED' (the analysis is price-free, so an edge is never measurable)")
    else:
        said = vm.group(1).upper()
        if said != "UNMEASURED":
            add("FAIL", "the analysis is price-free, so Value is always UNMEASURED", f"write 'Value: UNMEASURED' (got '{said}'): there is no market price in the report to measure an edge against")
        else:
            add("ok", "the value label is UNMEASURED (price-free)", "")
    try:
        import importlib.util as _iu
        _spec = _iu.spec_from_file_location("note_check_for_answer", Path(__file__).with_name("note_check.py"))
        _nc = _iu.module_from_spec(_spec)
        _spec.loader.exec_module(_nc)
        _run = Path(report_path).parent
        _side = " ".join(p.read_text(encoding="utf-8") for sub in ("notes", "advocates") for p in sorted((_run / sub).glob("*.md"))) if (_run / "notes").exists() or (_run / "advocates").exists() else ""
        _dec = (_run / "decision.md").read_text(encoding="utf-8") if (_run / "decision.md").exists() else ""      # the calculator output (probabilities, edge) is saved there
        _known = _nc._sheet_numbers(report_path) | set(re.findall(r"(?<![\w.])\d+(?:\.\d+)?", _side + " " + _dec)) | {f"{x:.2f}".rstrip("0").rstrip(".") for x in (e["lam_home"], e["lam_away"])}
        _ops = _nc.unknown_operands(answer, _known)
        add("FAIL" if len(_ops) > 3 else "WARN" if _ops else "ok", "the operands of every calculation in the answer are in the sheet, a note or a brief", f"not found: {', '.join(_ops)}: show where each number comes from (a calculation on an invented number is worse than none)" if _ops else "")
        _contra = _nc.replacement_contradictions(answer, sheet)
        add("WARN" if _contra else "ok", "replacement claims in the answer agree with the sheet", "; ".join(_contra[:2]))
    except Exception:                                      # noqa: BLE001 - these two checks never stop the others
        pass
    sc_words = ("possession", "set piece", "set-piece", "pressing", "weak", "key player")
    sc_found = [w for w in sc_words if re.search(w, answer, re.I)]
    ok_sc = bool(re.search(r"scouting report", answer, re.I)) and len(sc_found) >= 5
    add("ok" if ok_sc else "WARN", "the scouting report covers both sides", "" if ok_sc else f"{'no Scouting report line' if not re.search('scouting report', answer, re.I) else 'topics missing: ' + ', '.join(w for w in sc_words if w not in sc_found)}: shape in and out of possession, build-up and creation, key players, set pieces, pressing/line/transitions, weak areas")
    ga_words = ("current state", "target state", "gap", "root cause", "fix")
    ga_found = [w for w in ga_words if re.search(w, answer, re.I)]
    adj_found = [w for w in ("pressing", "line", "width", "set piece", "marking", "rotation") if re.search(w, answer, re.I)]
    ok_ga = bool(re.search(r"gap analysis", answer, re.I)) and len(ga_found) == 5 and len(adj_found) >= 5
    add("ok" if ok_ga else "WARN", "gap analysis, tactical adjustments and rotation are covered for both sides", "" if ok_ga else f"missing: {'a Gap analysis block' if not re.search('gap analysis', answer, re.I) else ', '.join(w for w in ga_words if w not in ga_found) or 'none'}; adjustments mentioned {len(adj_found)} of 6 (pressing, line, width, set piece, marking, rotation)")
    mf = section(answer, "Media focus")
    if mf:
        loose = [ln for ln in mf.strip().splitlines()[1:] if ln.strip() and not (re.search(r"20\d\d|\b\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", ln, re.I) and re.search(r"unverified", ln, re.I))]
        add("ok" if not loose and re.search(r"unverified", mf, re.I) else "WARN", "media headlines are dated and labelled (unverified)", "" if not loose and re.search(r"unverified", mf, re.I) else "each media line needs a source, a date and the word (unverified)")
    own = section(answer, "Own knowledge")
    add("ok" if own else "WARN", "own knowledge is labelled", "" if own else "no 'Own knowledge (unverified)' line")

    absolutes = sorted({m_.group(0) for m_ in re.finditer(r"\b(every dimension|across the board|in every (?:lens|respect|department)|completely|totally|no chance|certain(?:ly)?|cannot lose|clear(?:ly)? superior|dominat\w+ in every)\b", answer, re.I)})
    add("WARN" if absolutes else "ok", "no absolute claims (a sound case rarely wins every lens)", ", ".join(absolutes))
    favours = [re.search(r"(?:->|→|=>|favours?|edge)\W*([A-Za-z&' .]+?)(?:[.;,)]|$)", ln) for ln in rows_t]
    names = [norm(x.group(1)) for x in favours if x]
    top_side = max((names.count(norm(home)), norm(home)), (names.count(norm(away)), norm(away)))
    if len(names) >= 8 and top_side[0] >= len(names) - 1:
        add("WARN", "the table is not one-sided by construction", f"{top_side[0]} of {len(names)} rows favour the same side: confirm the other side was given its best lens and a fair reading")
    else:
        add("ok", "the table is not one-sided by construction", "")

    market = sorted({m_.group(0)[:100] for m_ in re.finditer(r"\b(?:the )?(?:market|bookmakers?|odds)\b[^.\n]{0,140}?\b(?:has not|hasn't|have not|likely|probably|underweight\w*|overweight\w*|ignor\w*|too much credit|mispric\w*|undervalu\w*|overvalu\w*|not weigh\w*|not adjust\w*|not price\w*)\b", answer, re.I)})
    add("FAIL" if market else "ok", "no argument from what the bookmakers know (the analysis is price-free)", "; ".join(market) + (": the market knows injuries, form and squads; name the specific information it lacks or drop the claim" if market else ""))

    venue = sorted({m_.group(0).strip()[:110] for m_ in re.finditer(r"[^.\n;]*\b(?:home (?:loss|win|defeat|draw|victory)|away (?:loss|win|defeat|draw|victory)|at home|on the road|same venue|same ground|home ground|own ground)\b[^.\n;]*", answer, re.I)})
    past = [v for v in venue if re.search(r"\b(beat|lost|won|drew|held|defeat\w*|loss|win|draw|\d-\d)\b", v, re.I)]
    add("WARN" if past else "ok", "venue claims about past matches (check each against the 'home'/'away' in the sheet's result rows)", " | ".join(past[:5]))
    both = sorted({m_.group(0).strip()[:110] for m_ in re.finditer(r"[^.\n;]*\b(?:beat|won|defeated|victory)\b[^.\n;]*(?:\b(\d+)-\1\b|\bdraw(?:n)?\b|\bheld\b)[^.\n;]*", answer, re.I)})
    add("FAIL" if both else "ok", "no result is called both a win and a draw", " | ".join(both[:4]))
    prose = "\n".join(ln for ln in answer.splitlines() if not ln.lstrip().startswith("|"))       # table cells are attributed by their column
    unattributed = sorted({m_.group(0).strip()[:110] for m_ in re.finditer(r"[^.\n;|]*\b(?:aerial|save rate|save %|win rate|pass accuracy|conversion)\b[^.\n;|]*\d+(?:\.\d+)?\s*%[^.\n;|]*", prose, re.I) if not any(re.search(r'\b' + re.escape(w) + r'\b', m_.group(0), re.I) for w in _name_words(home) + _name_words(away))})
    add("WARN" if unattributed else "ok", "every rate names the team it belongs to", " | ".join(unattributed[:4]))

    # a sentence about one team must not quote a number that appears only in the OTHER team's column of the key-metrics table
    tab = [ln for ln in sheet.splitlines() if ln.startswith("| ") and ln.count("|") >= 4 and not ln.startswith(("| metric", "|---"))]
    hn, an = set(), set()
    for ln in tab:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) >= 3:
            hn |= {x for x in numbers(cells[1]) if len(x.replace(".", "")) >= 2}
            an |= {x for x in numbers(cells[2]) if len(x.replace(".", "")) >= 2}
    swapped = []
    hw, aw = home.split()[0].lower(), away.split()[0].lower()
    hp, ap = set(), set()      # the sheet's own prose gives a team's figure too ("Lille away 2.33 points a game in 9 games", Arsenal-Lille test2): it clears that team, never flags the other
    for seg in (s_ for ln in sheet.splitlines() if not ln.startswith("|") for s_ in re.split(r";\s+", ln)):
        lo = seg.lower()
        if (hw in lo) != (aw in lo):
            (hp if hw in lo else ap).update(x for x in numbers(seg) if len(x.replace(".", "")) >= 2)
    for sent in re.split(r"(?<=[\w\]%)])\.\s+(?=[A-Z\[(])|;\s+|\n", prose):
        low = sent.lower()
        has_h, has_a = hw in low, aw in low
        if has_h == has_a or re.search(r"\bvs\.?\b|\bv\b|\bversus\b|\bcompared\b|\bwhile\b|\bwhereas\b", low) or not re.search(r"aerial|save|xg|pass|corner|shots|big chance|touches|clean sheet|ppg|points per game|cross|card|rest", low):
            continue
        mine, other = (hn | hp, an) if has_h else (an | ap, hn)
        wrong = sorted({x for x in numbers(sent) if x in other and x not in mine and len(x.replace(".", "")) >= 2 and ("." in x or float(x) > 20)})      # a bare small integer is a game count ("8 of 10"), not a rate
        if wrong:
            swapped.append(f"{(home if has_h else away)}: {', '.join(wrong)} in '{sent.strip()[:80]}'")
    add("WARN" if swapped else "ok", "numbers in a sentence about one team are not the other team's figures", " | ".join(swapped[:4]) + (" (re-read the KEY METRICS columns)" if swapped else ""))

    wrong_math = []
    for m_ in re.finditer(r"(-?\d+(?:\.\d+)?)\s*([-+*x×/÷])\s*(-?\d+(?:\.\d+)?)\s*=\s*(-?\d+(?:\.\d+)?)", answer):
        a_, op, b_, c_ = float(m_.group(1)), m_.group(2), float(m_.group(3)), float(m_.group(4))
        val = {"-": a_ - b_, "+": a_ + b_, "*": a_ * b_, "x": a_ * b_, "×": a_ * b_, "/": a_ / b_ if b_ else None, "÷": a_ / b_ if b_ else None}[op]
        if val is None or abs(val - c_) > max(0.02, abs(c_) * 0.01):
            wrong_math.append(f"{m_.group(0)} (it is {val if val is None else round(val, 3)})")
    add("FAIL" if wrong_math else "ok", "arithmetic written in the answer is right", "; ".join(wrong_math[:4]))

    grid_scores = {sc: 100 * p for sc, p in a["top_scores"]}
    grid_scores.update({k: 100 * v for k, v in a["draw_scores"].items()})
    off = []
    for m_ in re.finditer(r"\b(\d)\s*[-–]\s*(\d)\s*\(\s*(?:[^()%]{0,25}?)(\d+(?:\.\d+)?)\s*%", answer):
        sc = f"{m_.group(1)}-{m_.group(2)}"
        if sc in grid_scores and abs(float(m_.group(3)) - grid_scores[sc]) > 0.15:
            off.append(f"{sc} written {m_.group(3)}% vs calc.py {grid_scores[sc]:.1f}%")
    add("FAIL" if off else "ok", "scoreline percentages equal calc.py's grid", "; ".join(off[:4]))

    # numbers quoted as facts exist in the report
    known = set(numbers(sheet)) | set(numbers(json.dumps(report))) | {f"{x:.2f}" for x in (e["lam_home"], e["lam_away"])}
    for n in list(known):                                  # values quoted in millions or thousands (26,041,000 -> 26.041M, 26.0M, 26M)
        try:
            v = float(n)
        except ValueError:
            continue
        if v >= 1e5:
            for div in (1e6, 1e3):
                known |= {f"{v / div:.{k}f}".rstrip("0").rstrip(".") if k else f"{v / div:.0f}" for k in (0, 1, 2, 3)}
    allowed_text = " ".join([answer.split("Best bet")[0]])
    claims = section(answer, "From the report") + "\n" + section(answer, "Underlying evidence")
    unknown = sorted({n for n in numbers(claims) if len(n.replace(".", "")) >= 2 and n not in known and n.lstrip("0") not in known and (n.rstrip("0").rstrip(".") not in known)})
    shown = {n for n in unknown if re.search(rf"(?<![\w.]){re.escape(n)}(?![\w.])[^\n.;]{{0,40}}=|=\s*{re.escape(n)}(?![\w.])|\([^)\n]{{0,60}}[-+*/÷×x][^)\n]{{0,60}}\)", claims)}
    unexplained = [n for n in unknown if n not in shown]
    add("FAIL" if len(unexplained) > 3 else "WARN" if unexplained else "ok", "numbers in 'From the report' and 'Underlying evidence' are in the sheet or their arithmetic is shown", f"{len(unexplained)} not in the sheet and with no arithmetic shown: " + ", ".join(unexplained[:12]) + " (work each out with python3 -c and write it as 'X (a - b = X)')" if unexplained else "")

    # empty or backwards reasoning seen in an audit (Ajax): a draw always needs a concession, and a weak keeper helps the OTHER side
    taut = re.search(r"[^.\n]*\b(draws?|level)\b[^.\n]*\b(all|each|every)\b[^.\n]*\b(came|were)\b[^.\n]*\b(after|when)\b[^.\n]*\bconced[^.\n]*", answer, re.I) or re.search(r"[^.\n]*\b(all|every)\b[^.\n]*\bdraws?\b[^.\n]*\b(came|were)\b[^.\n]*\b(after|when)\b[^.\n]*\bconced[^.\n]*", answer, re.I)
    add("WARN" if taut else "ok", "no 'all the draws came after conceding' as evidence", f"a 1-1 or 2-2 draw always needs a concession: use the win/draw/loss record after conceding instead ('{taut.group(0).strip()[:90]}')" if taut else "")
    wrong = []
    for key in ("Deciding factors", "My view"):
        for sent in re.split(r"(?<=[\w\]%)])\.\s+(?=[A-Z\[])|\n", section(answer, key)):
            m_ = re.search(r"([A-Z][\w.'-]*(?: [A-Z][\w.'-]*)*)'s (?:own )?(?:goalkeeper|keeper)'?s? (?:save rate|saves)[^.]{0,40}?\b(?:weak|low|poor|only|bad)\b", sent) or re.search(r"(?:goalkeeper|keeper)'s save rate[^.]{0,30}\b(?:favour|favours|helps)\b", sent)
            if m_ and re.search(r"\bfavour(?:s)?\b|\bkeep(?:s)? [^.]{0,20}\blive\b|\bhelps?\b", sent):
                wrong.append(sent.strip()[:110])
    add("WARN" if wrong else "ok", "a weak keeper is not listed as that side's own advantage", f"check the direction: {wrong[0]!r}" if wrong else "")

    # a move priced on an invented number (Ajax run 5: "assumed 0.38 Brandt recovery", "the figure is a guess")
    _inv = re.search(r"[^.\n]*\bassum(?:ed|ing|e)\b[^.\n]{0,40}?\d+\.\d+[^.\n]*", answer, re.I) or re.search(r"[^.\n]*\b(?:is|are|was) (?:a|just a) guess\b[^.\n]*", answer, re.I)
    add("WARN" if _inv else "ok", "no move is priced on an assumed or guessed number", f"price it from the sheet or leave it at 0.00 ('{_inv.group(0).strip()[:100]}')" if _inv else "")

    # "home record" must be the home-venue rows, not the last 10 games of all venues (Ajax run 6: "the home record: 8 wins from 10 at 2.50 ppg")
    _hr = re.search(r"[^.\n]*\bhome (?:record|form)\b[^.\n]*\b(?:of|from|in|last) (?:its |the |their )?(?:last )?(?:10|ten)\b[^.\n]*", answer, re.I)
    add("WARN" if _hr else "ok", "a 'home record' is the home-venue rows only", f"the last 10 games are all venues: count the home rows or call it 'form' ('{_hr.group(0).strip()[:100]}')" if _hr else "")

    # a set-piece route the sheet calls level (Ajax run 6: "set pieces give Hajduk a second route" against "edge none (level)")
    _sp = re.search(r"SET-PIECE EDGE[^\n]*edge none", sheet)
    _spc = [x.strip()[:100] for x in re.split(r"(?<=[\w\]%)])\.\s+(?=[A-Z\[])|\n", answer) if re.search(r"set[- ]pieces?\W+(?:\w+\W+){0,5}?(?:route|edge|advantage|favour\w*|weapon)\b|\b(?:route|edge|advantage|weapon)\W+(?:\w+\W+){0,4}?(?:from|via|through|at|on) set[- ]pieces?", x, re.I) and not re.search(r"\b(level|no edge|none|equal|cancel\w*|lack\w*|balanced|even(?:ly)?|without|neither)\b", x, re.I)]      # "lacks a set-piece advantage", "roughly balanced set-piece route" (Arsenal-Lille runs) are not claims if _sp else []
    add("WARN" if _spc else "ok", "a set-piece edge is claimed only when the sheet finds one", f"the sheet's SET-PIECE EDGE says none (level): '{_spc[0]}'" if _spc else "")

    # a travel cut on a short trip double counts the home edge (Ajax audit): under ~3000 km and under 3 time zones gets 0.00
    _tr = ((report.get("insights") or {}).get("travel_info") or {})
    _km, _tz = _tr.get("away_travel_distance_km"), _tr.get("away_timezone_diff_hours")
    _short = isinstance(_km, (int, float)) and _km < 3000 and (not isinstance(_tz, (int, float)) or abs(_tz) < 3)
    _cut = re.search(r"[^.\n]*\b(travel|trip|journey)\b[^.\n]*(?<![\d.])-\s?0?\.\d+[^.\n]*", answer, re.I)
    add("WARN" if _short and _cut else "ok", "no travel cut on a short trip", f"the trip is {_km} km and {_tz} time zones: the home edge already counts ordinary travel, so the cut is 0.00 ('{_cut.group(0).strip()[:90]}')" if _short and _cut else "")
    _ins = report.get("insights") if isinstance(report.get("insights"), dict) else {}
    _pts = [(_ins.get(f"{s_}_standings_impact") or {}).get("current_points") if isinstance(_ins.get(f"{s_}_standings_impact"), dict) else None for s_ in ("home", "away")]
    _unformed = all(isinstance(p_, (int, float)) and p_ == 0 for p_ in _pts)
    _tbls = [x.group(0) for x in re.finditer(r"[^.\n]*(?:\b\d{1,2}(?:st|nd|rd|th)\s+(?:of\s+\d+|in the|place)|top of the table|top spot|table position|chas\w+|top-of-table)[^.\n]*", answer, re.I)] if _unformed else []
    _disclaimed = lambda x: re.search(r"\b(?:0|zero|no) (?:pts|points|games|matches)\b|not formed|unreliable|listing order|meaningless|says nothing", x, re.I)      # a position quoted as meaningless is not a claim
    _negated = lambda x: re.search(r"not formed|nobody|no one|neither|no side|no team|nothing to chase", x, re.I)      # "TABLE NOT FORMED leaves nobody chasing" follows the rule
    _tbl = next((x for x in _tbls if (re.search(r"chas\w+|top spot|top of the table|top-of-table", x, re.I) and not _negated(x)) or not (_disclaimed(x) or _negated(x))), None)
    add("WARN" if _tbl else "ok", "no table position is cited from a table where both sides have 0 points", f"the table has not started (0 points each), so a position is a listing order: '{_tbl.strip()[:110]}'" if _tbl else "")

    # xG direction
    bad = []
    for sent in re.split(r"(?<=[\w\]%)])\.\s+(?=[A-Z\[])|;\s+|\n", answer):
        if not re.search(r"\bxG\b", sent):
            continue
        pair = re.search(r"([+-]\d+\.\d+)\s*(?:vs\.?|against|to|and)\s*(?:\w+'?s?\s+)?([+-]\d+\.\d+)", sent)
        if not pair:
            continue
        x, y = float(pair.group(1)), float(pair.group(2))
        worse = re.search(r"\b(worse|weaker|lower|poorer|underperform\w*)\b", sent, re.I)
        better = re.search(r"\b(better|stronger|higher|superior|outperform\w*)\b", sent, re.I)
        if (x > y and worse) or (x < y and better):
            bad.append(sent.strip()[:110])
    add("FAIL" if bad else "ok", "xG comparisons read the numbers the right way round", " | ".join(bad))
    return rows


# in collection mode (3 or more specialist notes beside the report) these blocks live in the notes, not in the answer
COVERED_BY_NOTES = ("flanks are analysed for both sides (left, centre, right, mirror pairs)", "the manager's checklist covers the eight items for both sides",
                    "substitution habits are covered", "home v away style and intensity are covered", "the scouting report covers both sides",
                    "gap analysis, tactical adjustments and rotation are covered for both sides", "media headlines are dated and labelled (unverified)",
                    "the deciding factors name the highest-priority areas")


def check(answer: str, report_path: str, log_path: str | None = None) -> list[tuple[str, str, str]]:
    rows = _check_full(answer, report_path, log_path)
    notes = sorted(Path(report_path).parent.glob("notes/*.md"))
    briefs = sorted(Path(report_path).parent.glob("advocates/*.md"))
    if briefs:
        said = bool(re.search(r"advocates\s*:", answer, re.I)) and all(re.search(b.stem, answer[re.search(r"advocates\s*:", answer, re.I).start():], re.I) for b in briefs) if re.search(r"advocates\s*:", answer, re.I) else False
        rows.append(("ok" if said else "FAIL", "the council is weighed (the advocates are cited and the stronger case named)", "" if said else f"{len(briefs)} advocate brief(s) exist ({', '.join(b.name for b in briefs)}): add an 'Advocates:' line saying what the home and the away advocate argued and which case is stronger and why"))
    if len(notes) < 3:
        return rows
    rows = [r for r in rows if r[1] not in COVERED_BY_NOTES]
    return rows


def main(answer_path: str, report_path: str, log_path: str | None = None) -> int:
    try:
        answer = Path(answer_path).read_text(encoding="utf-8")
        rows = check(answer, report_path, log_path)
    except (OSError, ValueError) as err:
        print(f"cannot run the check: {err}", file=sys.stderr)
        return 2
    print("| Status | Check | Detail |\n|---|---|---|")
    for status, name, detail in rows:
        print(f"| {status} | {name} | {detail} |")
    fails = sum(1 for r in rows if r[0] == "FAIL")
    warns = sum(1 for r in rows if r[0] == "WARN")
    print(f"\nResult: {'clean' if not fails else 'fix the FAIL rows and run again'}" + (f" ({warns} warning(s) to check)" if warns else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print("usage: python3 check.py answer.md report.json [forecasts.jsonl]   (the log is optional: the checker rebuilds the calculator numbers from the answer's headline)", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:]))
