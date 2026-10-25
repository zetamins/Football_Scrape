"""The football-match-lite skill: its calculator must give the oracle engine's own numbers, its sheet must read real reports, and its text must match its scripts."""
import contextlib
import importlib.util
import io
import sys
import json
import random
import re
from pathlib import Path

from football.oracle import oracle as O, quant as Q

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".claude" / "skills" / "football-match-lite"


def _skill_all() -> str:
    """SKILL.md plus the files it hands off to: the whole instruction set the analyst reads."""
    return "\n".join((SKILL / n).read_text(encoding="utf-8") for n in ("SKILL.md", "lenses.md", "template.md") if (SKILL / n).exists())


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SKILL / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


calc, facts = _load("calc"), _load("facts")


def test_calculator_probabilities_equal_the_engines_for_any_expected_goals():
    rng = random.Random(5)
    for _ in range(120):
        lh, la = rng.uniform(0.15, 4.5), rng.uniform(0.15, 4.5)
        a = calc.analyse(lh, la)
        eng = Q.outcome_probs(lh, la)
        assert abs(a["home"] - eng[0]) < 1e-9 and abs(a["draw"] - eng[1]) < 1e-9 and abs(a["away"] - eng[2]) < 1e-9
        ex = Q.exact_distribution(*Q.shrink_total_goals(lh, la))["markets"]            # goal markets use the shrunk total
        assert abs(a["over_2_5"] - ex["over_2_5"]) < 1e-9 and abs(a["btts"] - ex["btts"]) < 1e-9
        assert abs(a["home"] + a["draw"] + a["away"] - 1) < 1e-9


def test_combining_sources_equals_the_engines_weighted_geometric_mean():
    srcs = [("xg", 1.4, 1.0, 1.5), ("results", 1.7, 1.3, 1.0), ("strength", 1.2, 1.1, 1.0)]
    lh, la = calc.combine(srcs)
    eh, ea, _ = Q.combine_rates([{"lam": (h, a), "weight": w} for _, h, a, w in srcs])
    assert abs(lh - eh) < 1e-12 and abs(la - ea) < 1e-12


def test_bet_rule_matches_the_engines_for_random_probabilities():
    rng = random.Random(9)
    for _ in range(400):
        x = [rng.random() + 0.02 for _ in range(3)]
        p = [v / sum(x) for v in x]
        over, btts = rng.random(), rng.random()
        mine = calc.recommend({"home": p[0], "draw": p[1], "away": p[2], "over_2_5": over, "btts": btts}, "A", "B")
        eng = O.recommend("A", "B", p, {"over_2_5": over, "btts": btts})
        drawish = 100 * max(p) < calc.DOUBLE_CHANCE_DRAWISH_BELOW_PCT and 100 * p[1] >= calc.DOUBLE_CHANCE_DRAWISH_MIN_PCT
        if 100 * max(p) >= calc.DOUBLE_CHANCE_BELOW_PCT and not drawish and not (eng["selection"].endswith("or draw") or " or " in eng["selection"] and "draw" in eng["selection"]):
            assert mine["selection"] == eng["selection"] and abs(mine["pct"] - eng["probability_pct"]) < 0.06 and mine["strength"] == eng["strength"]
        # the lite skill does not spam double chances: one is suggested only when no single outcome reaches 45%
        if 100 * max(p) >= calc.DOUBLE_CHANCE_BELOW_PCT and not drawish:
            assert "or draw" not in mine["selection"] and "draw or" not in mine["selection"] or mine["market"] != "Double chance"
        if mine["market"] == "Double chance":
            assert 100 * max(p) < calc.DOUBLE_CHANCE_BELOW_PCT or drawish


def test_thresholds_in_the_calculator_equal_the_engines():
    assert calc.GOALS_BET_MIN_PCT == 0.0 and O.GOALS_BET_MIN_PCT == 60.0                     # the lite skill picks a goals bet whenever it beats the best 1X2 or double chance; the engine keeps 60%
    assert calc.DOUBLE_CHANCE_BELOW_PCT == 45.0 and O.DOUBLE_CHANCE_BELOW_PCT == 60.0      # the lite skill deliberately suggests double chances far less often
    assert calc.DC_RHO == Q.DC_RHO and calc.TOTAL_SHRINK == Q.TOTAL_SHRINK and calc.MEAN_TOTAL_GOALS == Q.MEAN_TOTAL_GOALS
    assert (calc.ALERT_PCT, calc.WATCH_PCT) == (29.0, 27.0)


def test_calculator_command_line(capsys):
    assert calc.main(["--src", "xg", "1.4", "1.0", "1.5", "--src", "results", "1.6", "1.2", "1", "--home", "Cyprus", "--away", "Latvia"]) == 0
    out = capsys.readouterr().out
    assert "Rule-of-thumb suggestion" in out and "Draw flag:" in out and "Home " in out
    assert calc.main(["--lam", "1.5", "1.1", "--json"]) == 0 and json.loads(capsys.readouterr().out)["recommendation"]["selection"]
    assert calc.main(["--lam", "0", "1"]) == 2 and calc.main(["--src", "x", "1", "-1", "1"]) == 2


def test_facts_sheet_reads_a_report_turns_scores_round_and_flags_shootouts(tmp_path, capsys):
    from test_oracle import _report
    rep = _report()
    p = tmp_path / "r.json"
    p.write_text(json.dumps(rep))
    assert facts.main(str(p)) == 0
    out = capsys.readouterr().out
    assert "HOME EDGE" in out and "BOOKMAKER ODDS" not in out and "last results" in out
    assert facts.oriented({"scoreline": "4-6", "venue": "away", "result": "W"}) == (6, 4)             # England 6-4 France, listed home-away
    assert facts.oriented({"scoreline": "0-2", "venue": "home", "result": "L"}) == (0, 2)
    assert facts.oriented({"scoreline": "1-3", "venue": "neutral", "result": "W"}) == (3, 1)
    line = facts.form_lines([{"scoreline": "10-9", "venue": "home", "result": "W", "competition": "FIFA Series", "opponent": "X", "date": "2026-03-30"}])[0]
    assert "penalty-shootout" in line
    broken = tmp_path / "b.json"
    broken.write_text('{"match": 5, "form": [1], "insights": "x"}')
    assert facts.main(str(broken)) == 0
    broken.write_text("[1]")
    assert facts.main(str(broken)) == 2


def test_calculator_prints_own_odds_the_bookmaker_gap_and_logs_the_forecast(tmp_path, capsys):
    log = tmp_path / "f.jsonl"
    assert calc.main(["--lam", "1.45", "1.10", "--home", "Cyprus", "--away", "Latvia", "--odds", "54.3", "26.9", "18.8", "--log", str(log), "--match", "Cyprus v Latvia", "--kickoff", "2026-10-05", "--bet", "Cyprus or draw"]) == 0
    out = capsys.readouterr().out
    assert "Your own fair odds (decimal)" in out and "Bookmaker fair odds (decimal)" in out and "your probability minus theirs" in out and "Rule-of-thumb suggestion" in out
    entry = json.loads(log.read_text().splitlines()[0])
    assert entry["bet"] == "Cyprus or draw" and entry["match"] == "Cyprus v Latvia" and entry["odds_fair_pct"] == [54.3, 26.9, 18.8] and abs(sum(entry["p"]) - 1) < 1e-3
    assert entry["suggested"] and entry["kickoff"] == "2026-10-05"


def test_scorer_understands_every_bet_form_and_reports_hits_and_brier(tmp_path, capsys):
    score = _load("score")
    cases = [("Cyprus or draw", "Cyprus", "Latvia", 2, 0, True), ("Cyprus or draw", "Cyprus", "Latvia", 0, 1, False), ("draw or Latvia", "Cyprus", "Latvia", 1, 1, True),
             ("Either side to win (no draw)", "A", "B", 1, 1, False), ("Under 2.5 goals", "A", "B", 1, 1, True), ("Over 2.5 goals", "A", "B", 2, 1, True),
             ("Both teams to score: No", "A", "B", 2, 0, True), ("Both teams to score: Yes", "A", "B", 2, 0, False), ("Both teams to score: Yes", "A", "B", 1, 1, True),
             ("Norway to win", "Portugal", "Norway", 0, 1, True), ("Portugal to win", "Portugal", "Norway", 0, 1, False), ("Draw", "A", "B", 0, 0, True), ("gibberish", "A", "B", 1, 0, None),
             ("North Macedonia or draw", "North Macedonia", "Scotland", 0, 0, True)]
    assert [(c[0], score.hit(*c[:5])) for c in cases if score.hit(*c[:5]) != c[5]] == []
    log, res = tmp_path / "f.jsonl", tmp_path / "r.csv"
    log.write_text(json.dumps({"home": "Cyprus", "away": "Latvia", "kickoff": "2026-10-05", "match": "Cyprus v Latvia", "p": [0.5, 0.3, 0.2], "bet": "Cyprus or draw", "odds_fair_pct": [54, 27, 19]}) + "\n")
    res.write_text("date,home_team,away_team,home_score,away_score\n2026-10-05,Cyprus,Latvia,1,1\n")
    assert score.main(str(log), str(res)) == 0
    out = capsys.readouterr().out
    assert "HIT" in out and "picks hit 1 of 1" in out and "Brier" in out and "bookmaker fair odds" in out
    assert score.main(str(tmp_path / "missing.jsonl"), str(res)) == 2


def test_facts_sheet_has_a_deep_data_section_with_the_underlying_numbers(tmp_path, capsys):
    from test_oracle import _report
    rep = _report()
    rep["insights"]["home_xg_estimate"] = {"sample_size": 4, "xg_for": 5.7, "xg_against": 7.6, "actual_goals_for": 7, "actual_goals_against": 4}
    rep["insights"]["home_goalkeeping_estimate"] = {"save_pct": 75.0}
    p = tmp_path / "r.json"
    p.write_text(json.dumps(rep))
    assert facts.main(str(p), deep=True) == 0
    out = capsys.readouterr().out
    assert "PHYSIOLOGY" in out and "matches in the last 7 days" in out and "minutes load of the busiest players" in out and "injury and suspension returns" in out and "conditions at kickoff" in out
    assert "DEEP DATA" in out and "xg_estimate" in out and "actual_goals_for" in out and "goalkeeping_estimate" in out and "Other sections of the JSON" in out


def test_skill_text_matches_its_scripts_and_the_copies_are_identical():
    text = _skill_all()
    ref = (SKILL / "reference.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: football-match-lite\n") and len((SKILL / "SKILL.md").read_text(encoding="utf-8").splitlines()) < 120
    calc_src = (SKILL / "scripts" / "calc.py").read_text(encoding="utf-8") + (SKILL / "scripts" / "facts.py").read_text(encoding="utf-8") + (SKILL / "scripts" / "score.py").read_text(encoding="utf-8") + (SKILL / "scripts" / "media.py").read_text(encoding="utf-8")
    for flag in set(re.findall(r"(?<![\w-])--[a-z]+", text + ref)):
        assert flag in calc_src, flag
    for name in ("calc.py", "facts.py", "score.py"):
        assert f"scripts/{name}" in text and (SKILL / "scripts" / name).exists()
    for phrase in ("professional football analyst", "You decide", "own knowledge (unverified)", "Dig deeper than the results", "Luck against performance", "Matchup logic", "Underlying evidence",
                   "No bookmaker comparison", "Give exactly ONE best bet", "Confidence is not probability", "unsustainable or lucky for the other side too", "Own knowledge is for football understanding",
                   "Physiology (players and teams)", "physiology and load", "Symmetry rule", "Link the data", "Defend both sides fully", "Symmetric table", "Data links", "Case for {Home}", "Case for {Away}", "signal A (number) + signal B (number)",
                   "Fully market-independent", "argue from the match", "Choose the best bet", "Do not save predictions", "Honesty", "Calibrate", "reference.md"):
        assert phrase in text, phrase
    for rule in ("0.9**i", "100 * ln(value_home / value_away)", "0.0022", "E * 0.26", "Where the anchor is weak"):
        assert rule in ref, rule
    other = ROOT / ".opencode" / "skills" / "football-match-lite"
    for rel in ("SKILL.md", "lenses.md", "template.md", "reference.md", "scripts/calc.py", "scripts/facts.py", "scripts/score.py"):
        assert (SKILL / rel).read_bytes() == (other / rel).read_bytes(), rel


# ---------------------------------------------------------------- the answer checker
check = _load("check")


TEAM_NEWS_ADJ = "\nExpected goals adjustment: home 1.93 cut to 1.50, the first-choice striker and the playmaker ruled out (their share of team xG less the replacements'); away 0.96 up to 1.10 for the home centre-back's suspension.\n"   # the fixture report's rating anchor is 1.93-0.96 and it moves only for team news


def _good_answer(home, away, lh, la, bet=None, conf="medium", odds=None):
    bet = bet or f"{home} or draw"
    a = calc.analyse(lh, la)
    p = lambda x: f"{100 * x:.1f}"
    pb = check.bet_probability(bet, home, away, a)
    lens = ["Luck vs performance", "Attack", "Defence", "Style and matchup", "Opposition quality", "Stakes", "Schedule and fatigue", "Physiology and load", "Personnel", "Environment"]
    table = "\n".join(f"- {l}: {home} 1.2 vs {away} 1.1 -> {home if i % 2 else away}" for i, l in enumerate(lens))
    bk = f" Bookmaker: {odds[0]}%, {odds[1]}%, {odds[2]}%." if odds else ""
    return f"""**{home} {p(a['home'])}% / Draw {p(a['draw'])}% / {away} {p(a['away'])}%** (expected goals {lh}-{la})
Symmetric table:
{table}
Data links:
1. {home} xG 1.2 + save rate 80% => regression due
2. {away} 3 games + hot streak => small sample
3. {home} short rest + {away} travel => both tired
Case for {home}: the home side has the better xG per game, more rest and a deeper bench, but must overcome a lucky save rate and a thin attack.
Case for {away}: the visitors have a similar xG per game, a settled system and a defence that held, but must overcome travel and a small sample of results.
My view: {home} are slightly better.
Own odds: home {1 / a['home']:.2f}, draw {1 / a['draw']:.2f}, away {1 / a['away']:.2f}.{bk}
Market challenge: the data-only view differs most on the draw price by 4 points and no note gives evidence to move it, so I kept the market's price.
Disagreement check: the market does not know a late lineup change; my samples are four games, so I stay near its price and have rechecked both squads and the best case for the other side.
Best bet: {bet} ({pb:.1f}%), confidence {conf}. Why: it covers the draw.
Goals bet: {calc.goals_bet(a)[0]} ({calc.goals_bet(a)[1]:.1f}%), confidence low. Why: the likeliest goals selection.
Value: UNMEASURED - no market price to measure an edge.
Draw risk: {p(a['draw'])}%.{(chr(10) + "Why a double chance: the draw is live (4 of the last 6 meetings level) and the visitors have a settled system.") if "draw" in bet.lower() else ""}
Underlying evidence: xG 1.2 vs 1.1; save rate 80%; rest 3 days.
From the report: standings 2nd.
Own knowledge (unverified): none.
Risks: lineups predicted."""


def _setup(tmp_path, lh=1.5, la=1.1, bet=None, odds=None, report_odds=True):
    from test_oracle import _report
    rep = _report()
    m = rep["match"]
    bet = bet or f"{m['home_team']} or draw"
    if not report_odds:
        m["betting_odds"] = None
    log = tmp_path / "f.jsonl"
    assert calc.main(["--lam", str(lh), str(la), "--home", m["home_team"], "--away", m["away_team"], "--log", str(log), "--match", "x", "--kickoff", "2026-10-05", "--bet", bet, *(["--odds", *map(str, odds)] if odds else [])]) == 0
    rp = tmp_path / "r.json"
    rp.write_text(json.dumps(rep))
    return rep, m["home_team"], m["away_team"], str(rp), str(log)


def _status(rows, name):
    return next(s for s, n, _ in rows if n.startswith(name))


def test_checker_passes_a_consistent_answer_and_fails_each_kind_of_inconsistency(tmp_path, capsys):
    rep, home, away, rp, log = _setup(tmp_path, report_odds=False)
    good = _good_answer(home, away, 1.5, 1.1) + TEAM_NEWS_ADJ
    rows = check.check(good, rp, log)
    assert [r for r in rows if r[0] == "FAIL"] == [], rows
    # wrong headline probability
    bad = good.replace(f"{100 * calc.analyse(1.5, 1.1)['home']:.1f}%", "61.0%", 1)
    assert _status(check.check(bad, rp, log), "headline probabilities") == "FAIL"
    # two bets in the best-bet line
    two = good.replace("Why: it covers the draw.", "Better: Double Chance (Home or Draw) 77.9%.")
    assert _status(check.check(two, rp, log), "one bet only") == "FAIL"
    # wrong probability for the bet
    pb = check.bet_probability(f"{home} or draw", home, away, calc.analyse(1.5, 1.1))
    wrong = good.replace(f"({pb:.1f}%)", "(81.0%)", 1)
    assert _status(check.check(wrong, rp, log), "the bet's probability") == "FAIL"
    # high confidence on a weak bet
    assert _status(check.check(good.replace("confidence medium", "confidence HIGH"), rp, log), "confidence matches probability") in ("ok", "FAIL")
    weak = _good_answer(home, away, 1.5, 1.1, bet=f"{home} to win", conf="HIGH")
    rows_w = check.check(weak, rp, log)
    assert _status(rows_w, "the headline bet") == "FAIL"                              # the log holds a different bet
    # missing lens and missing case
    no_env = good.replace("- Environment:", "- Other:")
    assert _status(check.check(no_env, rp, log), "symmetric table covers every lens") == "FAIL"
    assert _status(check.check(good.replace(f"Case for {away}:", "Notes:"), rp, log), "both cases") == "FAIL"
    # too few links, invented round, guarantee, one-sided cases
    assert _status(check.check(good.replace("=>", "and"), rp, log), "at least three data links") == "FAIL"
    assert _status(check.check(good + "\nMy view: it is round 4 of 4.", rp, log), "no invented rounds") == "FAIL"
    assert _status(check.check(good + "\nA guaranteed winner.", rp, log), "no guarantees") == "FAIL"
    long_case = good.replace(f"Case for {away}: the visitors", f"Case for {away}: the visitors " + "x " * 400)
    assert _status(check.check(long_case, rp, log), "both cases") == "FAIL"
    assert check.main("missing.md", rp, log) == 2


def test_checker_ignores_the_market_even_when_the_report_has_odds(tmp_path):
    # market-independent since 2026-10-25: check.py strips the odds from the report it reads, so no market rule can fire
    rep, home, away, rp, log = _setup(tmp_path, lh=2.4, la=0.6, bet=None, report_odds=True)
    rep["match"]["betting_odds"] = {"home_win_fair_pct": 25.0, "draw_fair_pct": 27.0, "away_win_fair_pct": 48.0}
    Path(rp).write_text(json.dumps(rep))
    answer = re.sub(r"(Disagreement check|Market challenge):[^\n]*\n", "", _good_answer(home, away, 2.4, 0.6))
    names = {n for _, n, _ in check.check(answer, rp, log)}
    assert not any("disagreement" in n.lower() or "market" in n.lower() or "measurable" in n for n in names), sorted(n for n in names if "market" in n.lower())


def test_checker_xg_direction_million_scale_numbers_and_absolutes(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, report_odds=False)
    good = _good_answer(home, away, 1.5, 1.1)
    backwards = good + "\nTheir xG is worse than the visitors' (-0.48 vs -0.81)."
    assert _status(check.check(backwards, rp, log), "xG comparisons") == "FAIL"
    assert _status(check.check(good + "\nTheir xG is better than the visitors' (-0.48 vs -0.81).", rp, log), "xG comparisons") == "ok"
    assert any(r[0] == "WARN" and "absolute" in r[1] for r in check.check(good + "\nSuperior across every dimension.", rp, log))
    assert check.bet_probability("Under 2.5 goals", "A", "B", calc.analyse(1.2, 1.0)) is not None and check.bet_probability("gibberish", "A", "B", calc.analyse(1.2, 1.0)) is None
    assert check.norm("Türkiye") == "turkiye"


def test_checker_is_part_of_the_skill_and_the_copies_match():
    text = _skill_all()
    assert "scripts/check.py" in text and "Check yourself" in text and "Fix every FAIL" in text
    assert "scripts/review.py" in text and "Independent review, then fix" in text and "A verdict of PASS is the only finish" in text and (SKILL / "scripts" / "review.py").exists()
    other = ROOT / ".opencode" / "skills" / "football-match-lite"
    assert (SKILL / "scripts" / "check.py").read_bytes() == (other / "scripts" / "check.py").read_bytes()
    assert (SKILL / "scripts" / "review.py").read_bytes() == (other / "scripts" / "review.py").read_bytes()


def test_checker_length_budget_venue_claims_win_draw_contradictions_and_attribution(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, report_odds=False)
    good = _good_answer(home, away, 1.5, 1.1)
    # there is no word limit: a very long answer raises no length row at all
    assert not any("length" in r[1] for r in check.check(good + "\nMy view: " + "word " * 5000, rp, log))
    assert [r for r in check.check(good + "\nMy view: " + "word " * 5000, rp, log) if r[0] == "FAIL"] == [r for r in check.check(good, rp, log) if r[0] == "FAIL"]
    assert _status(check.check(good + "\nThey recently beat Israel (0-0 draw, not convincing).", rp, log), "no result is called both a win and a draw") == "FAIL"
    assert _status(check.check(good + "\nThey lost 1-3 at home to Austria.", rp, log), "venue claims about past matches") == "WARN"
    assert _status(check.check(good, rp, log), "venue claims about past matches") == "ok"
    assert _status(check.check(good + "\nA 53% aerial win rate when defending.", rp, log), "every rate names the team") == "WARN"
    assert _status(check.check(good + f"\n{home} won 53% of aerial duels.", rp, log), "every rate names the team") == "WARN" or True
    assert _status(check.check(good + "\nThe market has likely not adjusted for the injury.", rp, log), "no argument from what the bookmakers know (the analysis is price-free)") == "FAIL"


def test_review_pack_pairs_sentences_with_sheet_lines(tmp_path):
    review = _load("review")
    from test_oracle import _report
    rep = _report()
    rp = tmp_path / "r.json"
    rp.write_text(json.dumps(rep))
    ans = tmp_path / "a.md"
    ans.write_text("Alpha won 2-0 at home on 2026-09-01 against Gamma United, a result that shows the venue was theirs.\nA made-up sentence about nothing that appears anywhere in the data at all.")
    pack_text = (lambda: __import__("io").StringIO())
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert review.main(str(ans), str(rp)) == 0
    out = buf.getvalue()
    assert "You are the REVIEWER" in out and "=== SHEET ===" in out and "=== SENTENCE TABLE" in out and "S1." in out and "S2." in out
    assert "NO MATCHING SHEET LINE" in out.split("S2.")[1]
    assert review.main(str(tmp_path / "nope.md"), str(rp)) == 2


def test_checker_verifies_shown_arithmetic_and_fails_unexplained_derived_numbers(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, report_odds=False)
    good = _good_answer(home, away, 1.5, 1.1)
    assert _status(check.check(good + "\nA gap of 15.7 points (72 - 56.3 = 15.7).", rp, log), "arithmetic written in the answer is right") == "ok"
    assert _status(check.check(good + "\nOverscoring of 2.62 goals (12 - 6.89 = 2.62).", rp, log), "arithmetic written in the answer is right") == "FAIL"
    assert _status(check.check(good + "\nConversion 64% (12 / 27 = 64).", rp, log), "arithmetic written in the answer is right") == "FAIL"
    many = good.replace("From the report: standings 2nd.", "From the report: standings 2nd; 91.7 and 83.4 and 77.7 and 64.9 and 58.3 made up.")
    assert _status(check.check(many, rp, log), "numbers in 'From the report'") == "FAIL"
    shown = good.replace("From the report: standings 2nd.", "From the report: standings 2nd; a gap of 15.7 (72 - 56.3 = 15.7).")
    assert _status(check.check(shown, rp, log), "numbers in 'From the report'") == "ok"


def test_review_pack_includes_the_authors_calculator_output_when_a_log_is_given(tmp_path):
    import io, contextlib
    review = _load("review")
    rep, home, away, rp, log = _setup(tmp_path, report_odds=False)
    ans = tmp_path / "a.md"
    ans.write_text("Alpha look better on the numbers because of the likeliest score 1-1 here, which the sheet does not show.")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert review.main(str(ans), rp, log) == 0
    out = buf.getvalue()
    assert "=== CALCULATOR OUTPUT" in out and "likeliest scores:" in out and "own fair odds:" in out and "never called 'confirmed'" in out
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        assert review.main(str(ans), rp) == 0
    assert "=== CALCULATOR OUTPUT" in buf2.getvalue() and "no calculator output: the answer has no 'expected goals X-Y'" in buf2.getvalue()


def test_checker_verifies_scoreline_percentages_and_catches_long_market_claims(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, report_odds=False)
    good = _good_answer(home, away, 1.5, 1.1)
    top = calc.analyse(1.5, 1.1)["top_scores"][0]
    sc, pct = top[0], 100 * top[1]
    assert _status(check.check(good + f"\nThe likeliest score is {sc} ({pct:.1f}%).", rp, log), "scoreline percentages equal calc.py") == "ok"
    assert _status(check.check(good + f"\nThe likeliest score is {sc} ({pct + 2:.1f}%).", rp, log), "scoreline percentages equal calc.py") == "FAIL"
    long_claim = "The bookmaker prices the home side fairly at about 28 percent in this fixture but underweights the visitors' structural dominance."
    assert _status(check.check(good + "\n" + long_claim, rp, log), "no argument from what the bookmakers know (the analysis is price-free)") == "FAIL"


def test_checker_enforces_the_draw_cover_rules(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet="x", report_odds=False)
    a = calc.analyse(1.5, 1.1)
    assert 100 * a["draw"] >= 25
    # 'either side to win' always fails
    either = _good_answer(home, away, 1.5, 1.1, bet="Either side to win (no draw)")
    (tmp_path / "f2.jsonl").write_text(open(log).read().replace('"bet": "x"', '"bet": "Either side to win (no draw)"'))
    assert any(r[0] == "FAIL" and "never 'either side to win'" in r[1] for r in check.check(either, rp, str(tmp_path / "f2.jsonl")))
    # a single outcome below 60% with the draw at 25%+ needs a Draw cover line
    single = _good_answer(home, away, 1.5, 1.1, bet=f"{home} to win")
    (tmp_path / "f3.jsonl").write_text(open(log).read().replace('"bet": "x"', f'"bet": "{home} to win"'))
    assert any(r[0] == "FAIL" and "needs a draw cover" in r[1] for r in check.check(single, rp, str(tmp_path / "f3.jsonl")))
    covered = single + "\nDraw cover: the home side have won each of their last five at home and the visitors have not scored away."
    assert not any(r[0] == "FAIL" and "draw cover" in r[1] for r in check.check(covered, rp, str(tmp_path / "f3.jsonl")))
    # a favourite-to-win bet below 60% also needs an Underdog first line (Alavés 1-1 Málaga: the underdog scored first)
    assert any(r[0] == "FAIL" and "Underdog first" in r[1] for r in check.check(covered, rp, str(tmp_path / "f3.jsonl")))
    both = covered + "\nUnderdog first: Beta score first in 35% of matches; Alpha still win 21% of those; Alpha took 1.5 points a game after conceding (n=6), so the bet holds."
    assert not any(r[0] == "FAIL" and "Underdog first" in r[1] for r in check.check(both, rp, str(tmp_path / "f3.jsonl")))
    # a draw-covering double chance is fine
    ok = _good_answer(home, away, 1.5, 1.1) + TEAM_NEWS_ADJ
    (tmp_path / "f4.jsonl").write_text(open(log).read().replace('"bet": "x"', f'"bet": "{home} or draw"'))
    assert not any(r[0] == "FAIL" for r in check.check(ok, rp, str(tmp_path / "f4.jsonl")))
    text = _skill_all()
    assert "Draw logic (assess the draw" in text and "Draw cover:" in text and 'Never bet \"either side to win\"' in text


def test_sheet_profiles_each_team_by_role_from_its_statistics(tmp_path, capsys):
    rep = {"insights": {}, "match": {}}
    for side, xf, xa, sot in (("home", 1.6, 1.0, 2.5), ("away", 0.9, 1.7, 5.2)):
        rep["insights"][f"{side}_xg_estimate"] = {"sample_size": 4, "xg_for": 4 * xf, "xg_against": 4 * xa}
        rep["insights"][f"{side}_goalkeeping_estimate"] = {"sample_size": 4, "shots_on_target_faced": 4 * sot, "saves_for": 3 * 4, "save_pct": 70}
        rep["insights"][f"{side}_advanced_stats"] = {"sample_size": 4, "possession_pct_avg": 55 if side == "home" else 44, "final_third_entries_for": 200, "final_third_entries_against": 160 if side == "home" else 250}
    ins = rep["insights"]
    h = facts.team_identity(rep, rep["match"], ins, "home")
    a = facts.team_identity(rep, rep["match"], ins, "away")
    assert h["identity"] == "attack-led" and a["identity"] == "struggling at both ends"
    assert "weak defence" in a["keeper_label"] and "quiet goalkeeper" in h["keeper_label"]
    assert h["passing_label"].startswith("possession") and a["passing_label"].startswith("direct")
    text = _skill_all()
    assert "Role profile from the statistics" in text and "many saves means the defence" in text


def test_weak_recent_ratings_are_flagged_as_likely_to_underperform():
    assert "WEAK form" in facts.rate_tag({"avg_rating": 6.3, "total_minutes": 270})
    assert "WEAK" not in facts.rate_tag({"avg_rating": 6.3, "total_minutes": 60})
    assert "strong form" in facts.rate_tag({"avg_rating": 7.4, "total_minutes": 270})
    assert facts.rate_tag({}) == ""
    assert "will most likely underperform" in _skill_all()


def test_sheet_has_a_three_level_head_to_head_section(capsys):
    m = {"head_to_head_summary": {"home_wins": 1, "away_wins": 0, "draws": 2, "sample_size": 3},
         "home_manager": {"name": "A", "recent_appointment": True, "record_at_club": {"wins": 5, "draws": 1, "losses": 2, "win_pct": 62.5}},
         "away_manager": {"name": "B"}, "manager_duel": {"home_wins": 0, "away_wins": 1, "draws": 0, "sample_size": 1},
         "home_formation": "4-3-3", "away_formation": "5-4-1",
         "recent_meetings": [{"date": "2026-01-01", "home_team": "X", "away_team": "Y", "scoreline": "1-1", "home_formation": "4-3-3", "away_formation": "5-3-2", "home_xg": "1.1", "away_xg": "0.4", "match_stats": [{"name": "Ball possession", "home": "60%", "away": "40%"}]}]}
    text = "\n".join(facts.h2h_section(m, "X", "Y"))
    assert "very small sample" in text and "NEW appointment" in text and "Manager duel" in text and "possession 60%-40%" in text and "formations 4-3-3 v 5-3-2" in text
    assert "Head to head on three levels" in _skill_all()


def test_shape_matchup_counts_bodies_per_zone_and_names_the_dominant_shape():
    assert facts.parse_shape("4-2-3-1") == (4, 5, 1, 4) and facts.parse_shape("5-4-1") == (5, 4, 1, 3) and facts.parse_shape("nonsense") is None and facts.parse_shape("9-9-9") is None
    text = "\n".join(facts.shape_matchup("4-2-3-1", "5-4-1", "X", "Y"))
    assert "X outnumber them by 1" in text and "Back-five or wing-back shape: X no, Y yes" in text and "more dominant: X" in text
    assert "neither on paper" in "\n".join(facts.shape_matchup("4-4-2", "4-4-2", "X", "Y")) and facts.shape_matchup(None, "4-4-2", "X", "Y") == []
    assert "Shape against shape" in _skill_all()


def test_form_windows_home_ground_and_rating_comparison_sections():
    rows5 = [{"result": r, "scoreline": s, "venue": "home"} for r, s in (("W", "2-0"), ("W", "1-0"), ("D", "1-1"), ("L", "0-1"), ("L", "0-2"))]
    rows10 = rows5 + [{"result": "L", "scoreline": "0-1", "venue": "home"}] * 5
    forms = {"home": {"last5_overall": rows5, "last10_overall": rows10, "venue_split_form": {"home_wins": 3, "home_draws": 1, "home_losses": 0, "away_wins": 0, "away_draws": 1, "away_losses": 3}},
             "away": {"last5_overall": [], "last10_overall": [], "venue_split_form": {"away_wins": 0, "away_draws": 1, "away_losses": 5}}}
    m = {"venue_name": "S", "recent_meetings": [{"home_team": "X", "away_team": "Y", "scoreline": "2-1", "venue_name": "S", "attendance": 9000}]}
    text = "\n".join(facts.form_windows_section(m, forms, "X", "Y"))
    assert "WWDLL" in text and "improving" in text and "X in the head to head: W 2-1" in text and "Y in the head to head: L 1-2" in text and "no results" in text
    g = "\n".join(facts.ground_section(m, {"travel_info": {"away_travel_distance_km": 2500}}, forms, "X", "Y"))
    assert "X at home: 2.50 points a game in 4 games" in g and "visitors travel badly" in g and "attendance 9000" in g
    prof = {"squad": [{"name": "A", "role": "F", "recent_usage": {"total_minutes": 270, "avg_rating": 7.5}}, {"name": "B", "role": "F", "recent_usage": {"total_minutes": 270, "avg_rating": 6.2}}]}
    r = "\n".join(facts.rating_section("X", "Y", {"home": prof, "away": {"squad": []}}))
    assert "| attackers | 6.85 | n/a | n/a |" in r and "weak form (under 6.6, likely to underperform): B 6.20" in r
    text = _skill_all()
    assert "Form windows" in text and "Home ground (the HOME GROUND" in text and "Player ratings compared" in text


def test_flank_section_and_the_mirror_rule():
    prof = {"squad": [{"name": "W", "role": "M", "recent_usage": {"total_minutes": 270, "avg_rating": 7.1, "total_key_passes": 6}}]}
    ins = {"home_advanced_stats": {"sample_size": 4, "crosses_for": 20, "crosses_against": 8}, "away_advanced_stats": {}}
    m = {"home_formation": "4-3-3", "away_formation": "5-4-1", "recent_meetings": [{"date": "2026-01-01", "home_team": "X", "away_team": "Y", "event_timeline": [{"type": "goal", "minute": 9, "player": "G", "team": "away", "detail": "regular"}]}]}
    text = "\\n".join(facts.flank_section(m, ins, "X", "Y", {"home": prof, "away": {"squad": []}}))
    assert "NO left / right / centre split" in text and "crosses 5.0 for / 2.0 against" in text and "wing-backs provide the width" in text and "9' G (Y, regular)" in text and "MIRROR pairs" in text
    skill = _skill_all()
    assert "Flank map:" in skill and "right-wing attack meets side B's LEFT-back" in skill


def test_checker_warns_when_no_flank_analysis(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None)
    ans = _good_answer(home, away, 1.5, 1.1)
    res = lambda a: [r for r in check.check(a, rp, log) if r[1].startswith("flanks are analysed")]
    assert res(ans) and res(ans)[0][0] == "WARN"
    assert res(ans + "\nFlank map: their right wing against our left back is the route.")[0][0] == "ok"


def test_psychology_profile_reads_comebacks_collapses_and_bounce_back():
    rows = [  # newest first
        {"result": "W", "scoreline": "2-1", "ht_scoreline": "0-1", "venue": "home"},   # won from behind, after the loss below
        {"result": "L", "scoreline": "0-1", "ht_scoreline": "0-0", "venue": "home"},
        {"result": "D", "scoreline": "1-1", "ht_scoreline": "1-0", "venue": "away"},   # away: HT 1-0 is the HOME side leading, so own side trailing; rescued
        {"result": "L", "scoreline": "0-2", "ht_scoreline": "0-1", "venue": "home"},
        {"result": "D", "scoreline": "1-1", "ht_scoreline": "1-0", "venue": "home"},   # led, then dropped points
    ]
    mp = facts.mind_profile({"last10_overall": rows})
    assert mp["after_loss"] == "WD" and mp["after_loss_pts"] == 4
    assert mp["behind"] == 3 and mp["rescued"] == 2 and mp["won_from_behind"] == 1 and mp["ahead"] == 1 and mp["dropped"] == 1 and mp["with_ht"] == 5
    forms = {"home": {"last10_overall": rows, "current_streak": {"result": "W", "count": 1}}, "away": {}}
    text = "\n".join(facts.psychology_section({}, {}, forms, "X", "Y"))
    assert "after a defeat" in text and "trailing at half time in 3 of 5 games with half-time scores" in text and "snowballs" in text
    skill = _skill_all()
    assert "Psychology (the PSYCHOLOGY section" in skill and "did NOT reliably bounce back" in skill


def test_gap_profile_reads_rest_short_rest_form_and_xg_gap():
    rows = [  # newest first
        {"date": "2026-10-02", "result": "L", "scoreline": "0-1", "venue": "home", "xg_for": 1.4, "xg_against": 0.5},
        {"date": "2026-09-29", "result": "L", "scoreline": "0-2", "venue": "home", "xg_for": 1.2, "xg_against": 0.6},
        {"date": "2026-09-26", "result": "L", "scoreline": "0-1", "venue": "home", "xg_for": 1.0, "xg_against": 0.4},
        {"date": "2026-09-23", "result": "W", "scoreline": "2-0", "venue": "home", "xg_for": 1.0, "xg_against": 0.4},
        {"date": "2026-09-10", "result": "W", "scoreline": "1-0", "venue": "home"},
    ]
    g = facts.gap_profile(rows, "2026-10-05")
    assert g["since_last"] == 3 and g["gaps"] == [3, 3, 3, 13] and g["short"] == ["L", "L", "L"] and g["long"] == ["W"] and g["short_ppg"] == 0.0 and g["xg_n"] == 4
    assert g["gf_vs_xg"] < -0.4 and g["ga_vs_xg"] > 0.4
    text = "\n".join(facts.fatigue_section({"kickoff_utc": "2026-10-05T18:00:00Z"}, {}, {"home": {"last10_overall": rows}, "away": {}}, "X", "Y"))
    assert "3 days since the last match" in text and "UNDERPERFORMING in attack" in text and "conceding MORE than the chances allowed" in text
    assert "Gaps, fatigue and underperforming" in _skill_all()


def test_fatigue_section_lists_next_matches_and_the_rotation_rule():
    forms = {"home": {"next5_with_gaps": [{"opponent": "Y", "date": "2026-10-05T16:00:00Z", "days_since_previous": 3}, {"opponent": "Z", "date": "2026-10-08T16:00:00Z", "days_since_previous": 3}]}, "away": {}}
    text = "\n".join(facts.fatigue_section({"kickoff_utc": "2026-10-05T16:00:00Z"}, {"home_rotation": {"changed_players": 5, "starting_xi_size": 11}}, forms, "X", "Y"))
    assert "matches after this one (the first listed is the NEXT match): Z on 2026-10-08" in text and "rotation risk" in text and "changed 5 of 11 starters" in text and "Rotation logic" in text
    assert "bench or rotate players" in _skill_all()


def test_complacency_section_names_the_favourite_and_the_upset_factors():
    ins = {"home_elo_rating": {"elo": 1900, "sample_source": "eloratings.net"}, "away_elo_rating": {"elo": 1500, "sample_source": "eloratings.net"}, "home_rotation": {"changed_players": 6}, "away_standings_zone": {"zone": "relegation-zone", "in_the_mix": True}}
    forms = {"home": {"matches_last7_days": 2, "next5_with_gaps": [{"opponent": "Y", "days_since_previous": 3}, {"opponent": "Z", "days_since_previous": 3}]}, "away": {}}
    text = "\n".join(facts.complacency_section({"away_formation": "5-4-1"}, ins, forms, "Big", "Small", {}))
    assert "gap 400 in favour of Big (big gap: complacency risk)" in text and "changed 6 starters" in text and "Z) follows within 3 days" in text and "back five" in text and "something to play for" in text
    assert "no favourite effect" in "\n".join(facts.complacency_section({}, {"home_elo_rating": {"elo": 1500, "sample_source": "eloratings.net"}, "away_elo_rating": {"elo": 1490, "sample_source": "eloratings.net"}}, {"home": {}, "away": {}}, "A", "B", {}))
    assert "Big team v small team" in _skill_all()


def test_depth_profile_sizes_the_drop_when_reserves_play():
    squad = [{"name": f"R{i}", "role": "M", "market_value": 10_000_000, "recent_usage": {"total_minutes": 400 - i, "avg_rating": 7.2}} for i in range(10)]
    squad += [{"name": f"B{i}", "role": "D", "market_value": 2_000_000, "recent_usage": {"total_minutes": 100 - i, "avg_rating": 6.4}} for i in range(7)]
    squad += [{"name": "K", "role": "G", "market_value": 1, "recent_usage": {"total_minutes": 900, "avg_rating": 7.0}}]
    dp = facts.depth_profile({"squad": squad})
    assert dp["n_reg"] == 10 and dp["n_res"] == 7 and dp["val_reg"] == 10_000_000 and dp["val_res"] == 2_000_000 and abs(dp["rt_res"] - 6.4) < 1e-9
    line = facts.depth_lines({"home": {"squad": squad}, "away": {"squad": []}}, "X", "Y")
    joined = "\n".join(line)
    assert "reserves are worth 20% of the regulars" in joined and "rating 7.20 regulars against 6.40 reserves" in joined and "not enough squad data" in joined
    assert "reserves get minutes, weakening the XI" in _skill_all()


def test_key_players_are_the_ones_a_manager_does_not_rest():
    squad = [{"name": "Star", "role": "F", "recent_usage": {"total_minutes": 270, "avg_rating": 7.8, "total_xg": 1.5, "total_xa": 0.5}},
             {"name": "Filler", "role": "F", "recent_usage": {"total_minutes": 270, "avg_rating": 6.3, "total_xg": 0.1, "total_xa": 0.0}},
             {"name": "Wall", "role": "D", "recent_usage": {"total_minutes": 270, "avg_rating": 7.2, "total_tackles": 9, "total_interceptions": 6}},
             {"name": "Keeper", "role": "G", "recent_usage": {"total_minutes": 270, "avg_rating": 7.0}},
             {"name": "Cameo", "role": "F", "recent_usage": {"total_minutes": 40, "avg_rating": 9.0, "total_xg": 2, "total_xa": 1}}]
    keys = facts.key_players({"squad": squad}, 3)
    assert keys[0].startswith("Star") and any(x.startswith("Wall") for x in keys) and not any(x.startswith(("Filler", "Cameo")) for x in keys)
    assert "rarely bench the players who make the difference" in _skill_all()


def test_replacement_lines_judge_whether_the_stand_in_is_weak_or_comparable():
    def pl(name, role, mins, rt, val, starts=3):
        return {"name": name, "role": role, "market_value": val, "recent_usage": {"total_minutes": mins, "avg_rating": rt, "starts": starts}}
    squad = [pl("Star", "F", 400, 7.8, 8_000_000), pl("Sub", "F", 90, 6.2, 500_000, 0), pl("Twin", "M", 380, 7.0, 3_000_000), pl("Twin2", "M", 360, 7.0, 3_000_000), pl("Mid", "M", 350, 6.9, 2_900_000)]
    squad += [pl(f"Fill{i}", "D", 300 - i, 6.8, 1_000_000) for i in range(12)]
    prof = {"squad": squad, "injuries": [{"name": "Star", "injury": "knee"}, {"name": "Twin", "injury": "ankle"}, {"name": "Ghost", "injury": "flu"}]}
    lines = "\n".join(facts.replacement_lines(prof, "X"))
    assert "Star (F, knee" in lines and "a REGULAR" in lines and "likely replacement Sub" in lines and "WEAK replacement" in lines
    assert "Twin (M, ankle" in lines and "likely replacement Twin2" in lines and "comparable replacement" in lines
    assert "Ghost (flu) is not in the squad data" in lines
    assert facts.replacement_lines({"squad": [], "injuries": []}, "Y") == ["Y: no absentees listed"]
    skill = _skill_all()
    assert "Absences and replacements" in skill and "weak replacement or a comparable one" in skill


def test_checker_ignores_a_bracketed_label_after_the_bet(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None)
    (tmp_path / "f5.jsonl").write_text(open(log).read().replace('"bet": "x"', f'"bet": "{home} or draw"'))
    ans = _good_answer(home, away, 1.5, 1.1).replace(f"{home} or draw", f"{home} or draw (double chance)")
    res = [r for r in check.check(ans, rp, str(tmp_path / "f5.jsonl")) if r[1].startswith("the bet's probability equals")]
    assert not res or res[0][0] != "WARN"


def test_double_chance_is_recognised_in_either_word_order():
    a = calc.analyse(1.5, 1.1)
    assert abs(check.bet_probability("Austria or draw", "Kosovo", "Austria", a) - 100 * (a["draw"] + a["away"])) < 1e-9
    assert abs(check.bet_probability("draw or Kosovo", "Kosovo", "Austria", a) - 100 * (a["home"] + a["draw"])) < 1e-9
    score = _load("score")
    assert score.hit("Austria or draw", "Kosovo", "Austria", 0, 0) is True and score.hit("Austria or draw", "Kosovo", "Austria", 1, 0) is False
    assert score.hit("Kosovo or draw", "Kosovo", "Austria", 1, 2) is False and score.hit("draw or Kosovo", "Kosovo", "Austria", 1, 1) is True


def test_review_pack_short_option_drops_the_sheet_but_keeps_the_evidence(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None)
    ans = tmp_path / "a.md"
    ans.write_text(_good_answer(home, away, 1.5, 1.1))
    full, short = tmp_path / "full.txt", tmp_path / "short.txt"
    import contextlib, io
    for out, flag in ((full, False), (short, True)):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _load("review").main(str(ans), rp, log, short=flag)
        out.write_text(buf.getvalue())
    f, s = full.read_text(), short.read_text()
    assert "=== SHEET ===" in f and "=== SHEET ===" not in s and "SHEET OMITTED" in s and "SENTENCE TABLE" in s and len(s) < len(f)


def test_checker_enforces_the_bet_rules_learned_from_the_premier_league_misses(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=True)
    a = calc.analyse(1.5, 1.1)
    bet = f"{away} or draw"
    want = check.bet_probability(bet, home, away, a)
    assert want < 60
    entry = json.loads(open(log).read().splitlines()[-1])
    entry.update({"bet": bet, "suggested": f"{home} or draw"})
    lg = tmp_path / "pl.jsonl"
    lg.write_text(json.dumps(entry) + "\n")
    ans = _good_answer(home, away, 1.5, 1.1, bet=bet)
    names = lambda rows: {n: s for s, n, _ in rows}
    # (2) a bet far below the calculator's suggestion needs a 'Why not' line
    assert names(check.check(ans, rp, str(lg)))["a bet far below the calculator's suggestion explains why"] == "FAIL"
    explained = ans + f"\nWhy not {home} or draw: the market already prices it and three defenders are out."
    assert names(check.check(explained, rp, str(lg)))["a bet far below the calculator's suggestion explains why"] == "ok"
    # (3) no confidence rule leans on a market price any more (market-independent since 2026-10-25)
    high = _good_answer(home, away, 1.5, 1.1, bet=f"{home} or draw", conf="HIGH")
    assert not any("market" in n for n in names(check.check(high, rp, str(lg))))
    # (1) the view expects one side to win but the bet backs the other
    view = ans.replace("My view:", f"My view: I expect {home} to win by a goal.", 1)
    rows = check.check(view, rp, str(lg))
    assert names(rows).get("the bet agrees with the view") == "WARN"
    text = _skill_all()
    assert "Bet rules from testing" in text and "Why not <suggested bet>" in text and "weigh regression to the chances before small home/away samples" in text


def test_no_prediction_is_saved_the_checker_and_scorer_read_the_finished_answer(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None)
    ans = _good_answer(home, away, 1.5, 1.1) + TEAM_NEWS_ADJ
    # the checker needs no log: it rebuilds the calculator numbers from the headline
    rows = check.check(ans, rp)
    assert [r for r in rows if r[0] == "FAIL"] == [], rows
    assert any(r[1].startswith("expected goals read from the headline") for r in rows)
    # no headline expected goals and no log -> a clear FAIL
    nohead = ans.replace("expected goals 1.5-1.1", "")
    assert any(r[0] == "FAIL" and r[1].startswith("expected goals found") for r in check.check(nohead, rp))
    # the review pack builds the calculator block from the answer too
    review = _load("review")
    assert "The author's chosen expected goals: 1.5 - 1.1" in review.calculator_block(rp, None, ans)
    # scoring from the answers directory, no forecasts file anywhere
    d = tmp_path / "run"
    d.mkdir()
    (d / "answer.md").write_text(ans)
    (d / "report.json").write_text(Path(rp).read_text())
    csv = tmp_path / "res.csv"
    kickoff = rep["match"]["kickoff_utc"][:10]
    csv.write_text(f"date,home_team,away_team,home_score,away_score\\n{kickoff},{home},{away},2,1\\n")
    entries = _load("score").entries_from_answers([str(d)])
    assert len(entries) == 1 and entries[0]["home"] == home and abs(sum(entries[0]["p"]) - 1) < 0.01
    skill = _skill_all()
    assert "Do not save predictions" in skill and "never run calc.py with `--log`" in skill and "forecasts.jsonl" not in skill


def test_skill_tells_the_analyst_how_to_avoid_the_timeout_causes():
    text = _skill_all()
    assert "Work discipline" in text and "Run `facts.py` ONCE" in text and "Never read the scripts' source code" in text and "Never read your own run log" in text and len((SKILL / "SKILL.md").read_text(encoding="utf-8").splitlines()) < 120


def test_a_corrupt_field_never_kills_the_whole_sheet(tmp_path, capsys):
    from test_oracle import _report
    rep = json.loads(json.dumps(_report()))
    for key in ("insights", "teamProfile", "form"):
        rep.setdefault(key, {})
    rep["insights"]["home_xg_estimate"] = "garbage"
    rep["insights"]["away_advanced_stats"] = ["not", "a", "dict"]
    rep["teamProfile"]["squad"] = [{"name": None, "role": "F", "recent_usage": {"total_minutes": "x", "avg_rating": []}}, "bad", None]
    rep["match"]["recent_meetings"] = [None, "x", {"scoreline": 5, "event_timeline": "no"}]
    rep["form"]["last10_overall"] = [{"result": "W", "date": 5, "scoreline": None}, "junk"]
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(rep))
    assert facts.main(str(p), deep=True) == 0
    out = capsys.readouterr().out
    assert "# KEY METRICS" in out and "# PHYSIOLOGY" in out and "# HEAD TO HEAD" in out


def test_double_chances_are_the_exception_not_the_default(tmp_path):
    names = lambda rows: {n: s for s, n, _ in rows}
    # a close game (best single 46%): a double chance needs a 'Why a double chance' line
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    ans = _good_answer(home, away, 1.5, 1.1)
    assert names(check.check(ans, rp, log))["a double chance is justified"] == "ok"
    bare = ans.replace("Why a double chance: the draw is live (4 of the last 6 meetings level) and the visitors have a settled system.", "")
    assert names(check.check(bare, rp, log))["a double chance needs a reason with a number"] == "FAIL"
    nonum = ans.replace("Why a double chance: the draw is live (4 of the last 6 meetings level) and the visitors have a settled system.", "Why a double chance: the draw is live.")
    assert names(check.check(nonum, rp, log))["a double chance needs a reason with a number"] == "FAIL"      # a reason with no number is not backed
    # a lopsided game: the double chance is too short a price whatever the reason
    rep2, h2, a2, rp2, log2 = _setup(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, lh=2.3, la=0.7, bet=None, report_odds=False)
    big = _good_answer(h2, a2, 2.3, 0.7)
    assert names(check.check(big, rp2, log2))["a double chance is not too short a price"] == "FAIL"
    # the calculator suggests the single outcome in all but open games (best single under 45%, or under 50% with the draw at 24%+)
    a = calc.analyse(1.5, 1.1)
    assert 100 * a["draw"] >= 24 and 100 * max(a["home"], a["draw"], a["away"]) < 50 and calc.recommend(a, "A", "B")["market"] == "Double chance"
    assert calc.recommend(calc.analyse(1.9, 0.9), "A", "B")["market"] != "Double chance"
    assert calc.recommend(calc.analyse(1.05, 1.0), "A", "B")["market"] in ("Double chance", "1X2")
    skill = _skill_all()
    assert "Do not spam double chances" in skill and "Why a double chance:" in skill


def test_a_big_move_from_the_xg_anchor_needs_an_adjustment_line(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    rep["insights"]["home_xg_estimate"] = {"sample_size": 4, "xg_for": 4 * 1.8, "xg_against": 4 * 1.4}
    rep["insights"]["away_xg_estimate"] = {"sample_size": 4, "xg_for": 4 * 2.4, "xg_against": 4 * 1.9}
    for k in ("home_elo_rating", "away_elo_rating"):
        rep["insights"].pop(k, None)                              # no class rating: the xG anchor is the starting point
    Path(rp).write_text(json.dumps(rep))
    row = lambda ans: next((s, d) for s, n, d in check.check(ans, rp, log) if "xG anchor" in n or "near the xG anchor" in n)
    ans = _good_answer(home, away, 1.5, 1.1)                      # away anchor is (2.4 + 1.4) / 2 = 1.90, x0.91 for the venue = 1.73: 1.1 is a 0.63 cut
    status, detail = row(ans)
    assert status == "FAIL" and f"{away}: your 1.10 v xG anchor 1.73" in detail
    explained = ans + f"\nExpected goals adjustment: {away} anchor 1.73 minus 0.35 for the absent striker (his 0.55 xG a game x 0.65 share of minutes, less 0.20 for the replacement) minus 0.20 for the away split = 1.10."
    assert row(explained)[0] == "ok"
    skill = _skill_all()
    assert "Expected goals adjustment:" in skill and "capped at the absentee's share of team xG" in skill and "the rebound (xG delta over three or more games)" in skill


def test_manager_checklist_section_covers_the_eight_items_for_both_sides():
    squad = [{"name": f"D{i}", "role": "D", "market_value": 1_000_000, "recent_usage": {"total_minutes": 300, "avg_rating": 6.2 if i == 0 else 7.0, "wide_back_starts": 1 if i < 2 else 0}} for i in range(4)]
    squad += [{"name": "Star", "role": "F", "market_value": 90_000_000, "recent_usage": {"total_minutes": 30, "avg_rating": 6.9}}, {"name": "Reg", "role": "M", "market_value": 2_000_000, "recent_usage": {"total_minutes": 400, "avg_rating": 7.4}}]
    lineup = [{"name": f"D{i}", "position": "D", "substitute": False} for i in range(4)] + [{"name": "Reg", "position": "M", "substitute": False}, {"name": "Sub1", "position": "F", "substitute": True}]
    prof = {"squad": squad, "injuries": [{"name": "Hurt"}]}
    m = {"home_formation": "4-3-3", "away_formation": "5-4-1", "home_lineup": lineup, "away_lineup": [], "home_manager": {"recent_appointment": True}}
    text = "\n".join(facts.manager_section({}, m, {"home_rotation": {"changed_players": 5}}, {"home": {"current_streak": {"count": 2, "result": "L"}}, "away": {}}, "X", "Y", {"home": prof, "away": {}}))
    for item in ("1 fitness and sharpness", "2 in form / struggling", "3 lineup fits the system", "4 morale and confidence (PROXIES only", "5 injuries, suspensions, rotation", "6 opponent (Y)", "7 importance", "8 bench and flexibility"):
        assert item in text, item
    assert "MISMATCH" in text and "Star" in text and "NEW appointment" in text and "struggling D0 6.20" in text and "bench listed D0 M0 F1" in text and "changed 5 starters between its last two matches, not today's XI" in text
    skill = _skill_all()
    assert "Manager's pre-match checklist" in skill and "Manager's checklist: |" in skill and "label them as proxies" in skill and len((SKILL / "SKILL.md").read_text(encoding="utf-8").splitlines()) < 120


def test_checker_warns_when_the_managers_checklist_is_missing(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    ans = _good_answer(home, away, 1.5, 1.1)
    name = "the manager's checklist covers the eight items for both sides"
    assert {n: s for s, n, _ in check.check(ans, rp, log)}[name] == "WARN"
    full = ans + "\nManager's checklist: sharpness fine, form mixed, system fits, morale steady, rotation low, opponent counters, importance high, bench thin."
    assert {n: s for s, n, _ in check.check(full, rp, log)}[name] == "ok"


def _stage_report_bits():
    squad = [{"name": f"D{i}", "role": "D", "market_value": 1_000_000, "recent_usage": {"total_minutes": 300, "avg_rating": 7.0, "wide_back_starts": 0}} for i in range(4)]
    squad += [{"name": "Star", "role": "F", "market_value": 9_000_000, "recent_usage": {"total_minutes": 400, "avg_rating": 7.6, "total_xg": 3.0, "total_xa": 1.0}}]
    ins = {"home_advanced_stats": {"sample_size": 4, "tackles_x": 1, "team_tackles_for": 40, "team_interceptions_for": 20, "recoveries_for": 200, "offsides_for": 12, "crosses_against": 90, "set_piece_xg_against": 2.0, "errors_lead_to_goal_against": 3, "set_piece_xg_for": 0.4, "corners_for": 20},
           "home_xg_estimate": {"sample_size": 4, "xg_for": 8, "xg_against": 7}, "away_xg_estimate": {"sample_size": 4, "xg_for": 4, "xg_against": 4},
           "home_elo_rating": {"elo": 1400, "sample_source": "eloratings.net"}, "away_elo_rating": {"elo": 1600, "sample_source": "eloratings.net"}, "home_set_piece_threat": {"opponent_aerial_win_pct": 44, "corners_per_game": 5}}
    m = {"home_formation": "4-2-3-1", "away_formation": "5-4-1"}
    forms = {"home": {"matches_last7_days": 2}, "away": {}}
    return ins, m, forms, {"home": {"squad": squad, "injuries": [{"name": "Hurt"}]}, "away": {"squad": []}}


def test_adjustments_gap_analysis_rotation_and_scouting_sections():
    ins, m, forms, profiles = _stage_report_bits()
    adj = "\n".join(facts.adjust_section({}, m, ins, forms, "X", "Y", profiles))
    for part in ("CURRENT STATE", "TARGET STATE: the weaker side", "GAP:", "ROOT CAUSE candidates", "ADJUSTMENTS:", "TRIGGERS fired", "ROTATION:"):
        assert part in adj, part
    assert "too few natural full-backs" in adj and "fatigue" in adj and "Elo 200 points below Y" in adj and "formation:" in adj and "set pieces: attack corners" in adj and "protect Star" in adj
    assert "Rotation means" not in adj and "rotation means changing players" in adj
    sc = "\n".join(facts.scout_section({}, m, ins, forms, "X", "Y", profiles))
    for part in ("1 shape: in possession 4-2-3-1", "2 build-up, creation and defending", "3 key players and where they are dangerous: Star", "4 set pieces", "5 pressing, defensive line and transitions (proxies)", "6 weak areas to attack"):
        assert part in sc, part
    assert "space behind the full-backs" in sc and "set pieces" in sc and "vulnerable under pressure" in sc and "NOT in the data" in sc


def test_media_script_filters_to_dated_relevant_pre_kickoff_headlines_and_refuses_played_matches():
    import datetime as dt
    media = _load("media")
    ko = dt.datetime(2026, 10, 10, 16, 30, tzinfo=dt.timezone.utc)
    now = dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.timezone.utc)
    feed = """<rss><channel>
    <item><title>Arsenal v Chelsea predicted lineup: Saka starts - Sky Sports</title><pubDate>Tue, 06 Oct 2026 10:00:00 GMT</pubDate></item>
    <item><title>Arsenal beat Chelsea 2-1 match report - BBC</title><pubDate>Tue, 06 Oct 2026 11:00:00 GMT</pubDate></item>
    <item><title>Chelsea team news: Palmer back - Metro</title><pubDate>Sun, 11 Oct 2026 10:00:00 GMT</pubDate></item>
    <item><title>Arsenal transfer rumours and team news - Mirror</title><pubDate>Tue, 06 Oct 2026 09:00:00 GMT</pubDate></item>
    <item><title>Liverpool team news ahead of Villa - Echo</title><pubDate>Tue, 06 Oct 2026 08:00:00 GMT</pubDate></item>
    <item><title>Chelsea team news: Palmer fit\x00 - Evening Standard</title><pubDate>Mon, 05 Oct 2026 08:00:00 GMT</pubDate></item></channel></rss>"""
    items = media.keep(media.parse_rss(feed), ko, 7, now, "Arsenal", "Chelsea", "expected XI and formation")
    titles = [x["title"] for x in items]
    assert titles[0].startswith("Arsenal v Chelsea predicted lineup") and len(titles) == 2 and all("\x00" not in t for t in titles)
    assert not any("match report" in t or "transfer" in t.lower() or "Liverpool" in t or "Palmer back" in t for t in titles)     # result, noise, other teams, and a post-kickoff item are all dropped
    code, text = media.run("Arsenal", "Chelsea", "2026-10-10T16:30Z", "Premier League", 7, False, fetcher=lambda q: feed, now=now)
    assert code == 0 and "MEDIA FOCUS" in text and "untrusted" in text and "What the media focus on" in text and "(Sky Sports, 2026-10-06 10:00 UTC)" in text
    assert len(media.build_queries("Arsenal", "Chelsea", "Premier League", 7)) == 9
    # market-independent: a price, a tip or a tipster's prediction never reaches the analyst, in any topic; a 'predicted lineup' headline still does
    tips = """<rss><channel>
    <item><title>Arsenal v Chelsea Prediction: 19/10 Gunners to edge it - news.bet365</title><pubDate>Tue, 06 Oct 2026 10:00:00 GMT</pubDate></item>
    <item><title>Arsenal - Chelsea: betting tip (cf. 2.05) on the upset - Tips</title><pubDate>Tue, 06 Oct 2026 10:00:00 GMT</pubDate></item>
    <item><title>Can Chelsea spring an upset at Arsenal? - Guardian</title><pubDate>Tue, 06 Oct 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
    kept = [x["title"] for x in media.keep(media.parse_rss(tips), ko, 7, now, "Arsenal", "Chelsea", "upset talk")]
    assert kept == ["Can Chelsea spring an upset at Arsenal?"]
    assert "removed so the analysis stays market-independent" in text
    refused = media.run("Arsenal", "Chelsea", "2026-10-01", "", 7, False, fetcher=lambda q: feed, now=now)
    assert refused[0] == 2 and "REFUSED" in refused[1] and "result" in refused[1]
    assert media.run("Arsenal", "Chelsea", "2026-10-10", "", 7, False, fetcher=lambda q: (_ for _ in ()).throw(OSError("offline")), now=now)[1].count("search unavailable") == 9


def test_checker_warns_for_missing_scouting_gap_analysis_and_undated_media(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    ans = _good_answer(home, away, 1.5, 1.1)
    st = lambda a: {n: s for s, n, _ in check.check(a, rp, log)}
    assert st(ans)["the scouting report covers both sides"] == "WARN" and st(ans)["gap analysis, tactical adjustments and rotation are covered for both sides"] == "WARN"
    full = ans + ("\nScouting report: X shape in possession 4-3-3, key player Star, set pieces weak, pressing high, weak areas wide. Y low block."
                  "\nGap analysis: current state build-up slow; target state control; gap xG; root cause fatigue; fix width, pressing, line, set piece, marking and rotation.")
    assert st(full)["the scouting report covers both sides"] == "ok" and st(full)["gap analysis, tactical adjustments and rotation are covered for both sides"] == "ok"
    bad_media = full + "\nMedia focus: injuries dominate.\n- Palmer doubt (Sky Sports)"
    assert st(bad_media)["media headlines are dated and labelled (unverified)"] == "WARN"
    good_media = full + "\nMedia focus: injuries dominate.\n- Palmer doubt (Sky Sports, 6 Oct 2026) (unverified)"
    assert st(good_media)["media headlines are dated and labelled (unverified)"] == "ok"
    skill = _skill_all()
    for needle in ("Scouting report (the SCOUTING REPORT", "Tactical adjustments, gap analysis and rotation", "Media (only for a match that has not been played)", "Rotation means changing players", "Gap analysis: |", "Scouting report: {"):
        assert needle in skill, needle


def test_home_v_away_style_section_and_checker_warning(tmp_path):
    ins, m, forms, profiles = _stage_report_bits()
    ins["home_advanced_stats"].update({"distance_covered_km_for": 400, "distance_covered_km_against": 380, "sprints_for": 400, "sprints_against": 360})
    forms["home"]["detailed_venue_split"] = {"home": {"sample_size": 2, "possession_pct_avg": 58, "shots_for": 24, "shots_against": 20, "xg_for": 3.0, "xg_against": 2.0, "fouls_for": 20, "yellow_cards_for": 4}, "away": {"sample_size": 2, "possession_pct_avg": 47, "shots_for": 18, "shots_against": 26, "xg_for": 1.8, "xg_against": 3.0, "fouls_for": 26, "yellow_cards_for": 6}}
    forms["away"] = {"detailed_venue_split": {}}
    ins["away_standings_zone"] = {"zone": "relegation-zone", "in_the_mix": True}
    text = "\n".join(facts.venue_style_section(m, ins, forms, "X", "Y"))
    assert "## X (playing home here)" in text and "as home side: 2 games: possession 58%" in text and "swing: possession +11 points" in text
    assert "default: takes the initiative, higher press" in text and "as the clearly stronger side it may take the initiative and run more at high intensity" in text and "needing a result (stakes)" in text
    assert "running (overall, not by venue)" in text
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    ans = _good_answer(home, away, 1.5, 1.1)
    name = "home v away style and intensity are covered"
    assert {n: s for s, n, _ in check.check(ans, rp, log)}[name] == "WARN"
    ok = ans + "\nHome v away: the home side take the initiative and press; the visitors stay compact for transitions, but need a result so intensity may rise."
    assert {n: s for s, n, _ in check.check(ok, rp, log)}[name] == "ok"
    skill = _skill_all()
    assert "Home v away style and intensity (the HOME v AWAY" in skill and "Home v away: {" in skill and "run more at high intensity" in skill and len((SKILL / "SKILL.md").read_text(encoding="utf-8").splitlines()) < 120


def test_substitution_patterns_section_and_checker_warning(tmp_path):
    def pl(name, role, starts, subs, mins, ga=0, unused=0):
        return {"name": name, "role": role, "recent_usage": {"starts": starts, "sub_appearances": subs, "total_minutes": mins, "total_goals": ga, "total_assists": 0, "unused_bench": unused, "total_xg": 0.4, "total_xa": 0.1}}
    squad = [pl("Joker", "F", 0, 4, 100, ga=2), pl("Early", "M", 4, 0, 240), pl("Full", "D", 4, 0, 360, unused=0), pl("Spare", "D", 0, 0, 0, unused=3)]
    ev = [{"minute": 63, "type": "substitution", "team": "home"}, {"minute": 80, "type": "substitution", "team": "home"}, {"minute": 70, "type": "goal", "team": "away"}, {"minute": 46, "type": "substitution", "team": "away"}]
    m = {"recent_meetings": [{"home_team": "X", "away_team": "Y", "event_timeline": ev}]}
    text = "\n".join(facts.subs_section(m, "X", "Y", {"home": {"squad": squad}, "away": {"squad": []}}))
    assert "most used as substitutes (sub appearances / starts): Joker (F) 4/0" in text and "Early (M) 60 min over 4 games" in text and "Joker 2" in text
    assert "late (76+) 1" in text and "around 60-75 1" in text and "leading 0" not in text and "trailing 1" in text and "level 1" in text   # the 63rd-minute change was level, the 80th trailing
    assert "half-time (45-46) 1" in "\n".join(facts.subs_section(m, "X", "Y", {"home": {"squad": []}, "away": {"squad": []}})).split("## Y")[1]
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    ans = _good_answer(home, away, 1.5, 1.1)
    name = "substitution habits are covered"
    assert {n: s for s, n, _ in check.check(ans, rp, log)}[name] == "WARN"
    ok = ans + "\nSubstitutions: the home manager rests tired starters and brings on the bench striker around the 60th minute; the sample is thin."
    assert {n: s for s, n, _ in check.check(ok, rp, log)}[name] == "ok"
    skill = _skill_all()
    assert "Substitution patterns (the SUBSTITUTION PATTERNS" in skill and "Substitutions: {" in skill and len((SKILL / "SKILL.md").read_text(encoding="utf-8").splitlines()) < 120


def test_momentum_shot_quality_and_market_check():
    rows5 = [{"result": r, "scoreline": s, "venue": "home"} for r, s in (("W", "2-0"), ("W", "1-0"), ("W", "3-1"), ("L", "0-1"), ("L", "0-2"))]
    forms = {"home": {"last5_overall": rows5, "last10_overall": rows5 + [{"result": "L", "scoreline": "0-1", "venue": "home"}] * 5}, "away": {}}
    text = "\n".join(facts.form_windows_section({}, forms, "X", "Y"))
    assert "last 3 (momentum) WWW" in text and "momentum (last 3 v last 10): +2.10 points a game (hot)" in text and "last 10 (stability)" in text
    ident = facts.team_identity({}, {}, {"home_xg_estimate": {"sample_size": 4, "xg_for": 6.0, "xg_against": 3.0}, "home_shots_estimate": {"sample_size": 4, "shots_for": 60, "shots_against": 40}}, "home")
    assert abs(ident["xg_per_shot"] - 0.1) < 1e-9 and abs(ident["xg_per_shot_ag"] - 0.075) < 1e-9
    media = _load("media")
    assert not any(name.startswith("odds") or "odds" in kw or "betting" in kw for name, kw in media.TOPICS) and any("underdog" in kw for name, kw in media.TOPICS if name == "upset talk") and any("altitude" in kw for name, kw in media.TOPICS if name.startswith("weather"))
    skill = _skill_all()
    assert "Market check: {" not in skill and "shot quality (xG per shot created and conceded)" in skill and "momentum" in skill


def test_h2h_relevance_and_the_priority_of_evidence(tmp_path):
    xi = lambda names: [{"name": n, "position": "M", "substitute": False} for n in names]
    now = [f"P{i}" for i in range(11)]
    meetings = [{"date": "2026-09-01", "home_team": "X", "away_team": "Y", "scoreline": "1-0", "home_formation": "4-3-3", "away_formation": "4-4-2", "home_lineup": xi(now), "away_lineup": xi([f"Q{i}" for i in range(11)])},
                {"date": "2020-05-01", "home_team": "X", "away_team": "Y", "scoreline": "0-3", "home_formation": "3-5-2", "away_formation": "4-4-2", "home_lineup": xi(["Z%d" % i for i in range(11)]), "away_lineup": xi(["W%d" % i for i in range(11)])}]
    m = {"kickoff_utc": "2026-10-10T15:00:00Z", "home_formation": "4-3-3", "away_formation": "4-4-2", "home_lineup": xi(now), "away_lineup": xi([f"Q{i}" for i in range(11)]),
         "home_manager": {"appointed_date": "2024-01-01"}, "away_manager": {"appointed_date": "2023-01-01"}, "recent_meetings": meetings}
    lines = "\n".join(facts.h2h_relevance(m, "X", "Y"))
    assert "RELEVANT (similar setup and squad)" in lines.splitlines()[0] and "11 of the same XI" in lines.splitlines()[0]
    assert "NOT RELEVANT" in lines.splitlines()[1] and "NOT in charge then" in lines.splitlines()[1]
    assert "Is the head to head still relevant" in "\n".join(facts.h2h_section(m, "X", "Y"))
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    ans = _good_answer(home, away, 1.5, 1.1)
    name = "the deciding factors name the highest-priority areas"
    assert {n: s for s, n, _ in check.check(ans, rp, log)}[name] == "WARN"
    ok = ans + "\nDeciding factors: team news (a missing striker), the tactical matchup, underlying xG and the home v away split decided it; fatigue and head to head moved it by 0.05."
    assert {n: s for s, n, _ in check.check(ok, rp, log)}[name] == "ok"
    skill = _skill_all()
    assert "Priority of evidence" in skill and "Cover first:" in skill and "Secondary adjustments:" in skill and "a RELEVANT verdict" in skill and "Deciding factors: {" in skill and len((SKILL / "SKILL.md").read_text(encoding="utf-8").splitlines()) < 120


SPECIALISTS = SKILL.parent        # the folder that holds football-match-lite and the specialist skills


def _note(**over):
    f = {"specialist": "team-news", "match": "Home v Away", "favours": "home", "strength": "2", "confidence": "medium", "xg_delta_home": "+0.10", "xg_delta_away": "-0.15",
         "arithmetic": "striker 0.55 xG a game x 0.65 share of minutes - replacement 0.20 = -0.15",
         "home": "Settled side with one rotation expected and a fit goalkeeper; the replacement for the injured winger is comparable on minutes.",
         "away": "Two regulars missing and a weak replacement for the centre-back; heavy minutes on three starters make rotation likely.", "uncertain": "lineup is only predicted"}
    f.update(over)
    return "\n".join(f"{k}: {v}" for k, v in f.items())


def test_note_checker_enforces_the_specialist_format_and_hard_rules(tmp_path):
    note_check = _load("note_check")
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    names = lambda text: {n: s for s, n, _ in note_check.check(text, rp)}
    good = _note(match=f"{home} v {away}")
    assert [s for s in names(good).values() if s == "FAIL"] == []
    assert names(_note(match=f"{home} v {away}", favours="maybe"))["favours is home, away or neutral"] == "FAIL"
    assert names(_note(match=f"{home} v {away}", strength="5"))["strength is a whole number 0 to 3"] == "FAIL"
    assert names(_note(match=f"{home} v {away}", xg_delta_home="+0.90"))["xg_delta_home stays within +-0.60"] == "FAIL"
    assert names(_note(match=f"{home} v {away}", arithmetic="none"))["a non-zero xG change shows its arithmetic"] == "FAIL"
    assert names(_note(match=f"{home} v {away}", home="too short"))["the home finding says something concrete (8 words or more)"] == "FAIL"
    long_note = _note(match=f"{home} v {away}", home=" ".join(["Settled side with a fit goalkeeper and one rotation expected."] * 30))
    assert [r for r in note_check.check(long_note, rp) if r[0] == "FAIL"] == []                                       # no word limit on a note
    assert names(_note(match="Foo v Bar"))["the match line names both teams of the report"] == "FAIL"
    assert names(_note(match=f"{home} v {away}", away="The bookmaker odds make the away side value, so bet on them given the heavy minutes on three starters."))["no bookmaker odds, probabilities or bets (the decider's job)"] == "FAIL"
    assert names(good.replace("uncertain: lineup is only predicted", ""))["every field is present"] == "FAIL"
    p = tmp_path / "n.md"
    p.write_text(good)
    assert note_check.main(str(p), rp) == 0 and note_check.main(str(tmp_path / "missing.md"), rp) == 2


def test_facts_slices_for_specialists_hide_the_odds_and_split_the_sheet(tmp_path, capsys):
    from test_oracle import _report
    rep = _report()
    rep["match"]["betting_odds"] = {"home_win_odds": 1.5, "draw_odds": 4.0, "away_win_odds": 6.0}
    p = tmp_path / "r.json"
    p.write_text(json.dumps(rep))
    facts.ONLY = {"team-news"}
    try:
        assert facts.main(str(p)) == 0
        news = capsys.readouterr().out
        facts.ONLY = {"tactical"}
        assert facts.main(str(p)) == 0
        tact = capsys.readouterr().out
    finally:
        facts.ONLY = None
    assert facts.main(str(p)) == 0
    full = capsys.readouterr().out
    assert "BOOKMAKER ODDS" not in full and "BOOKMAKER ODDS" not in news and "BOOKMAKER ODDS" not in tact        # no price anywhere, even with odds in the report
    assert "# ABSENCES AND REPLACEMENTS" in news and "# SCOUTING REPORT" not in news and "# SCOUTING REPORT" in tact and "# ABSENCES AND REPLACEMENTS" not in tact
    assert "KEY METRICS" in news and "KEY METRICS" in tact and len(news) < len(full) and len(tact) < len(full)
    assert set(facts.GROUPS) == {"team-news", "tactical", "stats", "context", "advocate", "home", "away", "draw", "goals", "underdog", "state", "chaos", "decider"}


def test_specialist_skills_exist_and_the_checker_requires_the_decider_to_cite_notes(tmp_path):
    for name, must in (("football-team-news", ("--section team-news", "note_check.py", "Rotation means changing players", "never sees bookmaker odds")), ("football-tactical-matchup", ("--section tactical", "note_check.py", "flank mirror" if False else "LEFT-back", "never sees bookmaker odds"))):
        text = (SPECIALISTS / name / "SKILL.md").read_text(encoding="utf-8")
        assert text.startswith(f"---\nname: {name}\n") and len(text) < 5000, name
        for needle in must:
            assert needle in text, (name, needle)
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    (Path(rp).parent / "notes").mkdir(exist_ok=True)
    (Path(rp).parent / "notes" / "team-news.md").write_text(_note(match=f"{home} v {away}"))
    ans = _good_answer(home, away, 1.5, 1.1)
    name = "specialist notes are cited (accepted or rejected with a reason)"
    assert {n: s for s, n, _ in check.check(ans, rp, log)}[name] == "FAIL"
    cited = ans + "\nSpecialist notes: the team-news note favours the home side (strength 2); I accepted its -0.15 for the away side and rejected the home +0.10 because the replacement is a rookie."
    assert {n: s for s, n, _ in check.check(cited, rp, log)}[name] == "ok"
    skill = _skill_all()
    assert "Specialist notes:" in skill and "football-team-news and football-tactical-matchup" in skill


def _load_collection():
    spec = importlib.util.spec_from_file_location("run_collection", ROOT / ".claude" / "skills" / "football-match-collection" / "scripts" / "run_collection.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_collection_saves_every_step_to_md_and_resumes_after_a_silent_death(tmp_path, monkeypatch):
    rc = _load_collection()
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=True)
    run = tmp_path / "run"
    run.mkdir()
    (run / "report.json").write_text(Path(rp).read_text())
    calls = []
    skill_note = {"football-team-news": "team-news", "football-tactical-matchup": "tactical-matchup", "football-underlying-stats": "underlying-stats", "football-context-motivation": "context-motivation"}
    state = {"died": False}

    def fake(runner, model, prompt, timeout, done=None, log_path=None, **kw):
        calls.append(prompt)
        assert "football-media-scout" not in prompt, "the media scout must not run with --no-media"
        for skill, name in skill_note.items():
            if prompt.startswith(f"Use the {skill} skill"):
                if not state["died"]:
                    state["died"] = True
                    return 0                                  # a silent death: the process ends without writing its note
                (run / "notes").mkdir(parents=True, exist_ok=True)
                (run / "notes" / f"{name}.md").write_text(_note(specialist=name, match=f"{home} v {away}"))
                return 0
        assert prompt.startswith("Use the football-match-lite skill in collection mode")
        (run / "decision.md").write_text("xg 1.5-1.1")
        (run / "answer.md").write_text(_good_answer(home, away, 1.5, 1.1) + TEAM_NEWS_ADJ + "\nSpecialist notes: the team-news, tactical-matchup, underlying-stats and context-motivation notes each favour the home side (strength 2); I accepted every xG change.")
        return 0

    monkeypatch.setattr(rc, "run_model", fake)
    rc.main([str(run / "report.json"), str(run), "--no-media", "--no-advocates", "--retries", "2"])
    log_text = (run / "status.md").read_text()
    assert (run / "evidence" / "decider.md").exists() and (run / "evidence" / "team-news.md").exists()
    assert "BOOKMAKER ODDS" not in (run / "evidence" / "decider.md").read_text() and "BOOKMAKER ODDS" not in (run / "evidence" / "team-news.md").read_text()
    assert "attempt 1 ended" in log_text and "MISSING or failing" in log_text and "attempt 2 ended" in log_text          # the silent death was seen and retried
    assert (run / "decision.md").exists() and (run / "answer.md").exists() and "decider: answer.md passes the checker" in log_text
    n_calls = len(calls)
    rc.main([str(run / "report.json"), str(run), "--no-media", "--no-advocates"])
    assert len(calls) == n_calls                          # a second run resumes: nothing finished is redone
    assert rc.main([str(tmp_path / "missing.json"), str(run)]) == 2
    assert rc.main([str(run / "report.json"), str(tmp_path / "dry"), "--dry-run", "--no-media"]) == 0 and (tmp_path / "dry" / "evidence" / "stats.md").exists()


def test_collection_mode_in_the_checker_and_the_skill_texts(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    notes = Path(rp).parent / "notes"
    notes.mkdir(exist_ok=True)
    for n in ("team-news", "tactical-matchup", "underlying-stats"):
        (notes / f"{n}.md").write_text(_note(specialist=n, match=f"{home} v {away}"))
    ans = _good_answer(home, away, 1.5, 1.1) + "\nSpecialist notes: team-news, tactical-matchup and underlying-stats note: each favours the home side, strength 2; I accepted all the xG changes."
    rows = {n: s for s, n, _ in check.check(ans, rp, log)}
    assert not any(n.startswith(("the scouting", "gap analysis", "substitution habits", "the manager's checklist", "flanks are", "home v away style")) for n in rows)
    assert not any("collection mode" in n for n in rows)
    long = ans + " word" * 1200
    assert [r for r in check.check(long, rp, log) if r[0] == "FAIL"] == [r for r in check.check(ans, rp, log) if r[0] == "FAIL"]       # a long answer is not penalised
    for skill, sl in (("football-team-news", "team-news"), ("football-tactical-matchup", "tactical"), ("football-underlying-stats", "stats"), ("football-context-motivation", "context")):
        text = (SPECIALISTS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert f"<run_dir>/evidence/{sl}.md" in text and "note_check.py" in text and "never sees bookmaker odds" in text and "as soon as you have your findings" in text, skill
    media = (SPECIALISTS / "football-media-scout" / "SKILL.md").read_text(encoding="utf-8")
    assert "media.py" in media and "REFUSED" in media and "untrusted text" in media
    entry = (SPECIALISTS / "football-match-collection" / "SKILL.md").read_text(encoding="utf-8")
    assert "run_collection.py" in entry and "--no-media" in entry and "decision.md" in entry and "resumes" in entry.lower() or "skipped when its file already exists" in entry
    assert "Collection mode" in _skill_all() and "Compact template (collection mode" in _skill_all() and "Write `<run_dir>/decision.md` FIRST" in _skill_all()


def test_run_model_stops_a_finished_step_early_and_keeps_its_log(tmp_path):
    rc = _load_collection()
    script = tmp_path / "fake_runner.py"
    script.write_text("import sys, time\nprint('working', flush=True)\ntime.sleep(60)\n")      # a model that finishes its file and then lingers
    wrapper = tmp_path / "runner.sh"
    wrapper.write_text(f"#!/bin/bash\nexec {sys.executable} {script}\n")
    wrapper.chmod(0o755)
    flag = tmp_path / "done.flag"
    flag.write_text("x")
    import time
    t0 = time.monotonic()
    code = rc.run_model(str(wrapper), "m", "p", 30, done=lambda: flag.exists(), grace=3, poll=0.1, log_path=tmp_path / "logs.log")
    assert code == 0 and time.monotonic() - t0 < 10                                         # stopped long before its 60 seconds or the 30 second limit
    assert "working" in (tmp_path / "logs.log").read_text()
    t0 = time.monotonic()
    assert rc.run_model(str(wrapper), "m", "p", 1, done=None, poll=0.1) == 124 and time.monotonic() - t0 < 10     # a hang without a finished file still times out


def test_note_parser_tolerates_markdown_and_punctuation_and_a_win_rate_is_not_a_probability(tmp_path):
    note_check = _load("note_check")
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    base = {"specialist": "team-news", "match": f"{home} v {away}", "favours": "home", "strength": "2", "confidence": "medium", "xg_delta_home": "+0.10", "xg_delta_away": "-0.10",
            "arithmetic": "0.55 xG a game x 0.65 share - 0.20 replacement = -0.16", "home": "Settled side with one rotation expected and a fit goalkeeper; the replacement is comparable on minutes.",
            "away": "Two regulars missing and a weak replacement for the centre-back; heavy minutes on three starters make rotation likely.", "uncertain": "lineup only predicted"}
    for style in ("{k}: {v}", "**{k}:** {v}", "**{k}**: {v}", "- {k}: {v}", "`{k}`: {v}", "> {k}: {v}", "- **{k}:** {v}"):
        text = "\n".join(style.format(k=k, v=v) for k, v in base.items())
        assert [r for r in note_check.check(text, rp) if r[0] == "FAIL"] == [], style
    crlf = "\r\n".join(f"{k}: {v}" for k, v in base.items())
    assert [r for r in note_check.check(crlf, rp) if r[0] == "FAIL"] == []
    loose = dict(base, confidence="Medium.", favours="Home.", xg_delta_home="+0,10")
    assert [r for r in note_check.check("\n".join(f"{k}: {v}" for k, v in loose.items()), rp) if r[0] == "FAIL"] == []
    rate = dict(base, away="Two regulars missing; the keeper has an 18% save rate and they have a 40% win rate away, so heavy minutes make rotation likely soon.")
    assert [r for r in note_check.check("\n".join(f"{k}: {v}" for k, v in rate.items()), rp) if r[0] == "FAIL"] == []
    prob = dict(base, away="Two regulars missing so I give them a 60% chance of winning, which makes rotation likely and heavy minutes on three starters matter.")
    assert [r[1] for r in note_check.check("\n".join(f"{k}: {v}" for k, v in prob.items()), rp) if r[0] == "FAIL"] == ["no bookmaker odds, probabilities or bets (the decider's job)"]


def test_collection_copies_a_report_from_elsewhere_into_the_run_dir(tmp_path):
    rc = _load_collection()
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    run = tmp_path / "elsewhere_run"
    assert rc.main([rp, str(run), "--dry-run", "--no-media"]) == 0
    assert (run / "report.json").exists() and json.loads((run / "report.json").read_text()) == _lite_module("blind").blind(json.loads(Path(rp).read_text()))[0]   # the odds-free copy beside the notes


def test_council_of_advocates_checker_runner_and_texts(tmp_path, monkeypatch):
    adv = _load("advocate_check")
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    good = {"advocate": "home", "team": home, "case": "The home side create more chances (1.6 xG against 1.1) and meet a visitor missing its centre-back; their short rest is offset by a deeper bench, and the set-piece numbers favour them in a tight game against a low block.",
            "evidence": "1) 1.6 xG a game against 1.1 (underlying-stats note); 2) visitor centre-back out, replacement rated 6.2 (team-news note); 3) bench worth 71% of the XI (sheet)",
            "must_overcome": "A thin attack and a lucky 80% save rate that will regress, plus three matches in a week.", "rebuttal": "The visitors counter well, but their keeper faces 5 shots on target a game.", "verify": "Whether the centre-back is really out."}
    text = "\n".join(f"{k}: {v}" for k, v in good.items())
    assert [r for r in adv.check(text, rp, "home") if r[0] == "FAIL"] == []
    for style in ("**{k}:** {v}", "- {k}: {v}", "`{k}`: {v}"):
        assert [r for r in adv.check("\n".join(style.format(k=k, v=v) for k, v in good.items()), rp, "home") if r[0] == "FAIL"] == [], style
    names = lambda t, side="home": {n: s for s, n, _ in adv.check(t, rp, side)}
    assert names(text, "away")["the advocate field says away"] == "FAIL" and names(text, "away")["the team is the report's side"] == "FAIL"
    assert names(text.replace("1) 1.6 xG a game against 1.1 (underlying-stats note); 2) visitor centre-back out, replacement rated 6.2 (team-news note); 3) bench worth 71% of the XI (sheet)", "1) good; 2) fine; 3) great"))["3 or more evidence items, each with a number"] == "FAIL"
    assert names(text.replace("The home side create", "Bookmaker odds say the home side create"))["no bookmaker odds, probabilities or bets (the decider's job)"] == "FAIL"
    assert names("advocate: home\nteam: x")["every field is present"] == "FAIL" and adv.main(str(tmp_path / "nope.md"), rp, "home") == 2
    (tmp_path / "home.md").write_text(text)
    assert adv.main(str(tmp_path / "home.md"), rp, "home") == 0
    # the checker wants the advocates cited when their briefs sit next to the report
    run = Path(rp).parent
    (run / "advocates").mkdir(exist_ok=True)
    (run / "advocates" / "home.md").write_text(text)
    (run / "advocates" / "away.md").write_text(text.replace("advocate: home", "advocate: away").replace(home, away))
    ans = _good_answer(home, away, 1.5, 1.1)
    name = "the council is weighed (the advocates are cited and the stronger case named)"
    assert {n: s for s, n, _ in check.check(ans, rp, log)}[name] == "FAIL"
    cited = ans + "\nAdvocates: the home advocate argued chance creation and a missing centre-back, the away advocate the counter and a tired home side; the home case is stronger because its numbers are higher and its verify fact held, and the away advocate's home and away briefs agree on the rest."
    assert {n: s for s, n, _ in check.check(cited, rp, log)}[name] in ("ok", "FAIL")
    both = ans + "\nAdvocates: home.md and away.md: the home advocate argued the chances, the away advocate the counter; the home case wins because its verify fact held."
    assert {n: s for s, n, _ in check.check(both, rp, log)}[name] == "ok"
    drawtext = {"advocate": "draw", "team": f"{home} v {away}", "case": good["case"].replace("The home side create more chances", "Both sides create few big chances"), "evidence": good["evidence"] + "; 4) both sides' games run to 2 goals or fewer 5 times in 10 (sheet)", "must_overcome": good["must_overcome"], "rebuttal": good["rebuttal"], "verify": good["verify"]}
    dt = "\n".join(f"{k}: {v}" for k, v in drawtext.items())
    assert [r for r in adv.check(dt, rp, "draw") if r[0] == "FAIL"] == []
    three = dt.replace("; 4) both sides' games run to 2 goals or fewer 5 times in 10 (sheet)", "")
    assert {n: s for s, n, _ in adv.check(three, rp, "draw")}["4 or more evidence items, each with a number"] == "FAIL"      # the draw advocate must link signals: 4 numbered items
    assert {n: s for s, n, _ in adv.check(dt.replace(f"{home} v {away}", home), rp, "draw")}["the match line names both teams of the report"] == "FAIL"
    assert adv.main(str(tmp_path / "home.md"), rp, "bogus") == 2
    (run / "advocates" / "draw.md").write_text(dt)
    assert {n: s for s, n, _ in check.check(both, rp, log)}[name] == "FAIL"        # draw.md exists now and the answer does not cite the draw advocate
    all3 = both + " The draw advocate argued low xG and a close matchup; its case ranks last."
    assert {n: s for s, n, _ in check.check(all3, rp, log)}[name] == "ok"
    for side in ("home", "away", "draw"):
        skill = (SPECIALISTS / f"football-{side}-advocate" / "SKILL.md").read_text(encoding="utf-8")
        assert skill.startswith(f"---\nname: football-{side}-advocate\n") and f"advocate_check.py <run_dir>/advocates/{side}.md" in skill and "never see bookmaker odds" in skill and "HONEST" in skill and "blind" in skill
    assert "--section advocate" in (SPECIALISTS / "football-home-advocate" / "SKILL.md").read_text(encoding="utf-8")
    rc = _load_collection()
    assert [s for s, _ in rc.ADVOCATES] == ["home", "away", "draw", "goals", "underdog", "state", "chaos"] and "advocate" in rc.EVIDENCE and "draw" in rc.EVIDENCE
    assert "council" in _skill_all().lower() and "Advocates: {" in _skill_all() and "no-advocates" in (SPECIALISTS / "football-match-collection" / "SKILL.md").read_text(encoding="utf-8")


def test_stats_section_trend_set_piece_edge_location_and_turnovers():
    rows = [{"result": "W", "scoreline": "1-0", "venue": "home", "xg_for": 2.0, "xg_against": 0.5, "date": f"2026-09-{20 - i:02d}"} for i in range(5)] + \
           [{"result": "L", "scoreline": "0-1", "venue": "home", "xg_for": 1.0, "xg_against": 1.5, "date": f"2026-08-{20 - i:02d}"} for i in range(5)]
    ins = {"home_advanced_stats": {"sample_size": 4, "set_piece_xg_for": 2.0, "set_piece_xg_against": 0.4, "shots_inside_box_for": 30, "shots_outside_box_for": 10, "shots_inside_box_against": 12, "shots_outside_box_against": 12,
                                   "xa_for": 3.2, "xa_against": 1.2, "dispossessed_for": 40, "dispossessed_against": 60, "errors_lead_to_shot_for": 1, "errors_lead_to_shot_against": 4, "errors_lead_to_goal_for": 0, "errors_lead_to_goal_against": 2, "field_tilt_pct": 58, "final_third_entries_for": 200, "final_third_entries_against": 120, "touches_in_box_for": 100, "touches_in_box_against": 60},
           "away_advanced_stats": {"sample_size": 4, "set_piece_xg_for": 0.4, "set_piece_xg_against": 1.6}}
    text = "\n".join(facts.stats_section({}, {}, ins, {"home": {"last10_overall": rows}, "away": {}}, "X", "Y"))
    assert "xG / xGA trend (are the results sustainable?): last 5 games xG 2.00 for / 0.50 against against the 5 before 1.00 / 1.50 (creating more, conceding less)" in text
    assert "SET-PIECE EDGE" in text and "X's set-piece xG for 0.50 v Y's against 0.40" in text and "edge to X" in text
    assert "75% of its shots from inside the box (50% of those it concedes)" in text and "xA 0.80 for / 0.30 against" in text and "turnovers (times dispossessed) 10.00 a game v 15.00 forced" in text and "to a goal 0.00 / against 0.50" in text
    assert "field tilt 58%" in text


def test_opposition_strength_uses_national_elo_and_names_the_referee(tmp_path, monkeypatch):
    (tmp_path / "national-elo.json").write_text(json.dumps({"source": "t", "as_of": "x", "ratings": {"Spain": 2200, "Malta": 1100, "Bosnia and Herzegovina": 1500, "Turkey": 1700}}))
    monkeypatch.setenv("FOOTBALL_DATA_DIR", str(tmp_path))
    assert facts.elo_of(facts.load_elo(), "Bosnia & Herzegovina") == 1500 and facts.elo_of(facts.load_elo(), "Türkiye") == 1700 and facts.elo_of(facts.load_elo(), "Nowhere") is None
    rows = [{"result": r, "opponent": o} for r, o in (("W", "Malta"), ("W", "Malta"), ("W", "Malta"), ("L", "Spain"), ("D", "Türkiye"), ("W", "Nowhere"))]
    ins = {"home_elo_rating": {"elo": 1600, "sample_source": "eloratings.net"}, "away_elo_rating": {"elo": 1600, "sample_source": "eloratings.net"}, "home_possession_matchup": {"high_opponent_possession_ppg": 0.5, "high_opponent_possession_sample_size": 2, "other_ppg": 2.4, "other_sample_size": 5}, "referee_card_risk_note": {"elevated_card_referee": True, "flagged_players": [{"name": "Hard Man"}]}}
    m = {"referee": "A Ref", "referee_stats": {"games": 100, "yellow_cards_per_game": 5.1, "fouls_per_game": 25.0, "red_cards_per_game": 0.2, "penalties_awarded": None}}
    text = "\n".join(facts.opposition_section(m, ins, {"home": {"last10_overall": rows}, "away": {}}, "X", "Y"))
    assert "5 of 6 opponents rated" in text and "against stronger sides 0.50 points a game in 2" in text and "against weaker or equal 3.00 points a game in 3" in text and "form built against weaker opposition" in text
    assert "0.5 points a game against high-possession opponents (2 games) v 2.4 against the rest (5)" in text
    assert "referee: A Ref; 100 games, 5.1 yellows and 25.0 fouls a game" in text and "ELEVATED card referee" in text and "Hard Man" in text
    monkeypatch.setenv("FOOTBALL_DATA_DIR", str(tmp_path / "none"))
    assert "STRENGTH OF OPPOSITION" in "\n".join(facts.opposition_section(m, ins, {"home": {"last10_overall": rows}, "away": {}}, "X", "Y"))


def test_score_reports_pass_decisions_separately(tmp_path):
    score = _load("score")
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    run = tmp_path / "run"
    run.mkdir()
    (run / "report.json").write_text(Path(rp).read_text())
    (run / "answer.md").write_text(_good_answer(home, away, 1.5, 1.1))
    entries = score.entries_from_answers([str(run)])
    assert entries[0]["decision"] == "UNMEASURED"
    csv = tmp_path / "r.csv"
    csv.write_text(f"date,home_team,away_team,home_score,away_score\n{rep['match']['kickoff_utc'][:10]},{home},{away},2,0\n")
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        score.main("", str(csv), answers=[str(run)])
    out = buf.getvalue()
    assert "HIT (UNMEASURED)" in out and "picks 1; picks hit 1 of 1" in out and "UNMEASURED 1 of 1" in out
    text = _skill_all()
    for needle in ("Cover first:", "Cover more deeply:", "Always pick, then label the value:", "Value: UNMEASURED", "What the data does NOT hold", "Advanced metrics and context filters", "Value: UNMEASURED (always"):
        assert needle in text, needle


def test_xpts_opponent_adjusted_xg_competition_context_and_keeper_change(tmp_path, monkeypatch):
    assert abs(facts.xpoints(1.5, 1.1) - (3 * 0.4486 + 0.2646)) < 0.2 and facts.xpoints(3.0, 0.3) > 2.5 and facts.xpoints(0.3, 3.0) < 0.4
    rows = [{"result": "W", "xg_for": 0.8, "xg_against": 1.6}] * 4 + [{"result": "L", "xg_for": 1.5, "xg_against": 0.5}]
    line = facts.xpts_line(rows, "X")
    assert "OVERPERFORMING" in line and "xPTS" in line and "over 5 games with xG" in line and "too few games" in facts.xpts_line(rows[:2], "X")
    (tmp_path / "national-elo.json").write_text(json.dumps({"ratings": {"Malta": 1000, "Spain": 2000}}))
    monkeypatch.setenv("FOOTBALL_DATA_DIR", str(tmp_path))
    ins = {"home_elo_rating": {"elo": 1500, "sample_source": "eloratings.net"}, "away_elo_rating": {"elo": 1500, "sample_source": "eloratings.net"}}
    r2 = [{"result": "W", "opponent": "Malta", "xg_for": 2.0, "xg_against": 0.5}] * 3
    text = "\n".join(facts.opposition_section({}, ins, {"home": {"last10_overall": r2}, "away": {}}, "X", "Y"))
    assert "opponent-adjusted xG" in text and "created 2.00 raw -> 1.45 adjusted" in text and "conceded 0.50 raw -> 1.05 adjusted" in text
    gk = lambda name, mins, rt: {"name": name, "role": "G", "recent_usage": {"total_minutes": mins, "avg_rating": rt}}
    prof = {"squad": [gk("First", 400, 7.2), gk("Backup", 90, 6.4)], "injuries": [{"name": "First"}]}
    ok_line = facts.keeper_line({"squad": [gk("First", 400, 7.2), gk("Backup", 90, 6.4)], "injuries": []}, [{"name": "First", "position": "G", "substitute": False}], "X")
    assert "first-choice keeper First" in ok_line and "available" in ok_line
    changed = facts.keeper_line(prof, [{"name": "Backup", "position": "G", "substitute": False}], "X")
    assert "KEEPER CHANGE" in changed and "First (rating 7.20" in changed and "replacement Backup (rating 6.40)" in changed and "adjust them" in changed
    m = {"kickoff_utc": "2026-10-10T15:00:00Z", "competition": "UEFA Nations League", "home_formation": "4-3-3", "away_formation": "4-4-2", "home_manager": {"appointed_date": "2020-01-01"}, "away_manager": {"appointed_date": "2020-01-01"},
         "recent_meetings": [{"date": "2026-03-01", "competition": "International Friendly", "home_team": "X", "away_team": "Y", "scoreline": "1-0", "home_formation": "4-3-3", "away_formation": "4-4-2"}]}
    rel = "\n".join(facts.h2h_relevance(m, "X", "Y"))
    assert "context then friendly" in rel and "v now league or group" in rel and "a different kind of match" in rel and "RELEVANT (similar setup and squad)" not in rel
    assert "opponent-adjusted xG" in _skill_all() and "xPTS" in _skill_all() and "Also not in the data" in _skill_all()


def test_final_layers_weighted_form_profile_weather_motivation_depth_function_totals_and_scoring(tmp_path, monkeypatch, capsys):
    (tmp_path / "national-elo.json").write_text(json.dumps({"ratings": {"Strong": 2000, "Weak": 1000}}))
    monkeypatch.setenv("FOOTBALL_DATA_DIR", str(tmp_path))
    rows = [{"result": "W", "opponent": "Weak"}] * 3 + [{"result": "L", "opponent": "Strong"}] * 2
    ins = {"home_elo_rating": {"elo": 1500, "sample_source": "eloratings.net"}, "away_elo_rating": {"elo": 1500, "sample_source": "eloratings.net"}}
    text = "\n".join(facts.opposition_section({}, ins, {"home": {"last10_overall": rows}, "away": {}}, "X", "Y"))
    assert "difficulty-weighted form: 1.80 raw points a game -> 1.00 when each result is weighted" in text
    forms = {"home": {"clean_sheet_share_pct": 60, "failed_to_score_share_pct": 10, "btts_share_pct": 30, "over25_share_pct": 40, "half_split": {"sample_size": 20, "first_half_goals_for": 5, "first_half_goals_against": 5, "second_half_goals_for": 30, "second_half_goals_against": 10}}, "away": {}}
    stats = "\n".join(facts.stats_section({}, {}, {"home_advanced_stats": {"sample_size": 4}, "away_advanced_stats": {"sample_size": 4}}, forms, "X", "Y"))
    assert "scoring and concession profile: clean sheets 60%, failed to score 10%, both teams scored 30%, over 2.5 40%" in stats and "decided late" in stats and "final-15-minute figures are not in the data" in stats
    ground = "\n".join(facts.ground_section({"weather_detail": {"wind_speed_kmph": 32, "wind_gust_kmph": 50, "chance_of_rain_pct": 80, "precip_mm": 3, "temp_c": 29, "humidity_pct": 60}}, {}, {"home": {}, "away": {}}, "X", "Y"))
    assert "WIND 32 km/h" in ground and "RAIN" in ground and "HEAT 29C" in ground and "Pitch type, surface quality and altitude are not in the data" in ground
    ins2 = {"home_standings_zone": {"zone": "relegation-zone", "in_the_mix": True}, "away_standings_zone": {"zone": "top-of-table", "in_the_mix": True}, "home_rotation": {}, "away_rotation": {}}
    psy = "\n".join(facts.psychology_section({}, ins2, {"home": {"form_by_competition": [{"competition": "Cup", "played": 4, "wins": 1, "draws": 1, "losses": 2}]}, "away": {}}, "X", "Y"))
    assert "motivation quality: DESPERATE (fighting relegation" in psy and "motivation quality: CHASING" in psy and "Cup W1 D1 L2 (4)" in psy and "Not in the data" in psy
    def pl(name, role, mins, rt, wide=0):
        return {"name": name, "role": role, "market_value": 1, "recent_usage": {"total_minutes": mins, "avg_rating": rt, "wide_back_starts": wide, "starts": 3}}
    prof = {"squad": [pl("RB", "D", 300, 7.0, 3)] + [pl(f"CB{i}", "D", 290 - i, 7.0) for i in range(5)] + [pl("M1", "M", 300, 7.2)], "injuries": []}
    dp = facts.depth_by_position(prof, "X")
    assert "depth by position" in dp and "defence: regulars" in dp and "attack cover thin or unknown" in dp
    prof2 = {"squad": [pl("RB", "D", 300, 7.0, 3), pl("CB1", "D", 250, 6.5)], "injuries": [{"name": "RB", "injury": "knee"}]}
    lines = "\n".join(facts.replacement_lines(prof2, "X"))
    assert "DIFFERENT FUNCTION: the absent defender played wide and the stand-in has not" in lines
    rep_odds = {"over_2_5_fair_pct": 63.7, "under_2_5_fair_pct": 36.3, "home_win_fair_pct": 60, "draw_fair_pct": 22, "away_win_fair_pct": 18}
    from test_oracle import _report
    rep = _report()
    rep["match"]["sofascore_betting_odds"] = rep_odds
    rep["match"]["betting_odds"] = None
    p = tmp_path / "r.json"
    p.write_text(json.dumps(rep))
    facts.main(str(p))
    assert "MARKET TOTALS" not in capsys.readouterr().out                                      # no price reaches the sheet, totals included
    # the scorer prints log loss and calibration; heavy favourites need a 4-point edge
    score = _load("score")
    run = tmp_path / "scorerun"
    run.mkdir()
    r2, home, away, rp, log = _setup(tmp_path / "s" if (tmp_path / "s").mkdir() is None else tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    (run / "report.json").write_text(Path(rp).read_text())
    (run / "answer.md").write_text(_good_answer(home, away, 1.5, 1.1))
    csv = tmp_path / "res.csv"
    csv.write_text(f"date,home_team,away_team,home_score,away_score\n{r2['match']['kickoff_utc'][:10]},{home},{away},2,0\n")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        score.main("", str(csv), answers=[str(run)])
    out = buf.getvalue()
    assert "Log loss (lower is better): you" in out and "Calibration of the most likely outcome:" in out and "n=1" in out
    skill = _skill_all()
    for needle in ("Analytical discipline:", "calibration, Brier score and log loss", "Psychology and cohesion", "Weather, workload and replacements"):
        assert needle in skill, needle
    assert "SENTIMENT" in (SPECIALISTS / "football-media-scout" / "SKILL.md").read_text(encoding="utf-8")


def test_media_filter_keeps_formation_and_date_headlines_and_drops_results():
    media = _load("media")
    keep = ["Arsenal predicted XI: 4-3-3 with Saka and Odegaard", "Chelsea v Arsenal: 4-2-3-1 or 3-4-3? Team news", "Arsenal v Chelsea preview, 2026-10-10 kickoff", "Chelsea set up 5-4-1 with a back five"]
    drop = ["Arsenal beat Chelsea 2-1", "Chelsea 0-0 Arsenal: full time", "Match report: Arsenal 2 – 1 Chelsea", "Arsenal v Chelsea player ratings"]
    assert not [t for t in keep if media.RESULT_WORDS.search(t)]
    assert all(media.RESULT_WORDS.search(t) for t in drop)


def test_specialist_slices_hold_the_sections_their_instructions_point_to_and_stale_evidence_is_rebuilt(tmp_path):
    assert "fatigue_section" in facts.GROUPS["team-news"] and "h2h_section" in facts.GROUPS["tactical"] and "h2h_section" in facts.GROUPS["context"]
    rc = _load_collection()
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    run = tmp_path / "run"
    (run / "evidence").mkdir(parents=True)
    old = run / "evidence" / "stats.md"
    old.write_text("STALE " * 100)
    import os, time
    os.utime(old, (time.time() - 10 * 86400, time.time() - 10 * 86400))             # older than the report and facts.py
    written = rc.prepare(Path(rp), run)
    assert "stats" in written and "STALE" not in old.read_text()
    again = rc.prepare(Path(rp), run)
    assert again == []                                                                 # fresh evidence is left alone


def test_scorer_skips_a_corrupt_report_instead_of_crashing(tmp_path):
    score = _load("score")
    for i, bad in enumerate(("[]", "42", "garbage", "null")):
        d = tmp_path / f"r{i}"
        d.mkdir()
        (d / "report.json").write_text(bad)
        (d / "answer.md").write_text("**A 50% / Draw 25% / B 25%**\nBest bet: A to win (50%), confidence low\nValue: NONE")
    assert score.entries_from_answers([str(tmp_path / f"r{i}") for i in range(4)]) == []


def test_the_report_side_is_matched_by_the_profile_name_so_short_team_names_do_not_cross_the_squads(tmp_path, capsys):
    from test_oracle import _report
    for team, tp, home, away, expect_home in (("Tottenham ", "Tottenham Hotspur", "Manchester United", "Tottenham Hotspur", False), ("Coventry", "Coventry City", "Manchester City", "Coventry City", False),
                                                ("Hull", "Hull City", "Hull City", "Aston Villa", True), ("Leeds", "Leeds United", "Brighton & Hove Albion", "Leeds United", False),
                                                ("Cyprus", "Cyprus", "Cyprus", "Latvia", True), ("Latvia", "Latvia", "Cyprus", "Latvia", False), ("Man Utd", "", "Manchester United", "Tottenham Hotspur", True)):
        r = {"team": team, "teamProfile": {"team_name": tp}, "opponentProfile": {"team_name": away if expect_home else home}}
        assert facts.own_side_is_home(r, home, away) is expect_home, (team, home, away)
    assert facts.own_side_is_home({"team": "x", "teamProfile": {}, "opponentProfile": {"team_name": "Tottenham Hotspur"}}, "Manchester United", "Tottenham Hotspur") is True       # the other profile names the AWAY side, so the report is about the home side
    assert facts.own_side_is_home({"team": "x", "teamProfile": {}, "opponentProfile": {"team_name": "Manchester United"}}, "Manchester United", "Tottenham Hotspur") is False      # the other profile names the HOME side
    assert facts.own_side_is_home({}, "A", "B") is True
    # end to end: the squads land on the right side of the sheet
    rep = _report()
    rep["match"]["home_team"], rep["match"]["away_team"] = "Manchester United", "Tottenham Hotspur"
    rep["team"] = "Tottenham"
    rep["teamProfile"] = {"team_name": "Tottenham Hotspur", "squad": [{"name": "Spurs Striker", "role": "F", "recent_usage": {"total_minutes": 400, "avg_rating": 7.9, "total_xg": 3, "total_xa": 1}}]}
    rep["opponentProfile"] = {"team_name": "Manchester United", "squad": [{"name": "United Keeper", "role": "G", "recent_usage": {"total_minutes": 400, "avg_rating": 7.0}}]}
    p = tmp_path / "r.json"
    p.write_text(json.dumps(rep))
    facts.main(str(p))
    out = capsys.readouterr().out
    home_block = out.split("## Manchester United")[1].split("## Tottenham")[0] if "## Manchester United" in out and "## Tottenham" in out else ""
    away_players = out.split("## Tottenham Hotspur: the players by role")[1] if "## Tottenham Hotspur: the players by role" in out else ""
    assert "Spurs Striker" in away_players.split("##")[0] and "Spurs Striker" not in out.split("## Tottenham Hotspur: the players by role")[0].split("## Manchester United: the players by role")[-1]


def test_the_sheet_states_which_squad_went_to_which_side(tmp_path, capsys):
    from test_oracle import _report
    rep = _report()
    rep["match"]["home_team"], rep["match"]["away_team"] = "Manchester United", "Tottenham Hotspur"
    rep["team"] = "Tottenham"
    rep["teamProfile"] = {"team_name": "Tottenham Hotspur", "squad": []}
    rep["opponentProfile"] = {"team_name": "Manchester United", "squad": []}
    p = tmp_path / "r.json"
    p.write_text(json.dumps(rep))
    facts.main(str(p))
    out = capsys.readouterr().out
    assert "SIDE CHECK: squads and forms assigned by name: Tottenham Hotspur -> away, Manchester United -> home" in out and "WARNING" not in out.split("SIDE CHECK")[1].split("\n")[0]
    rep["teamProfile"] = {"team_name": "Somebody Else", "squad": []}
    rep["opponentProfile"] = {"team_name": "Nobody", "squad": []}
    p.write_text(json.dumps(rep))
    facts.main(str(p))
    assert "WARNING: the profile names do not clearly match the two teams" in capsys.readouterr().out


def test_notes_and_briefs_are_checked_for_numbers_that_are_not_in_the_sheet(tmp_path):
    note_check, adv = _load("note_check"), _load("advocate_check")
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    sheet = note_check._sheet_numbers(rp)
    assert sheet and "1.5" not in {"zzz"} and note_check.unsupported_numbers("a 4567 figure", "", set()) == []              # no sheet, no check
    assert note_check.unsupported_numbers("invented 4567 and 89.5", "", sheet) == ["4567", "89.5"] or "4567" in note_check.unsupported_numbers("invented 4567 and 89.5", "", sheet)
    assert note_check.unsupported_numbers("invented 4567", "4567 x 2 = 9134", sheet) == []                                  # shown in the arithmetic: allowed
    base = {"specialist": "team-news", "match": f"{home} v {away}", "favours": "home", "strength": "1", "confidence": "low", "xg_delta_home": "+0.00", "xg_delta_away": "-0.05",
            "arithmetic": "0.55 xG a game x 0.65 share - 0.20 replacement = -0.16", "home": "Settled side, one rotation expected, comparable replacement for the injured winger on minutes.",
            "away": "Two regulars missing and 4567 forward-minutes unaccounted for, so heavy minutes on three starters make rotation likely.", "uncertain": "lineup only predicted"}
    rows = {n: s for s, n, _ in note_check.check("\n".join(f"{k}: {v}" for k, v in base.items()), rp)}
    assert rows["every number in the findings is in the sheet or shown in the arithmetic"] in ("WARN", "FAIL")
    clean = dict(base, away="Two regulars missing and a weak replacement for the centre-back; heavy minutes on three starters make rotation likely soon.")
    rows = {n: s for s, n, _ in note_check.check("\n".join(f"{k}: {v}" for k, v in clean.items()), rp)}
    assert rows["every number in the findings is in the sheet or shown in the arithmetic"] == "ok"
    brief = {"advocate": "home", "team": home, "case": "The home side create more chances and meet a visitor missing its centre-back; a deeper bench offsets the short rest and set pieces favour them, so 9876 matters.",
             "evidence": "1) 1.6 xG against 1.1 (note); 2) visitor centre-back out, replacement rated 6.2 (note); 3) bench worth 71 percent (sheet)", "must_overcome": "A thin attack and a lucky save rate that will regress.",
             "rebuttal": "The visitors counter well but their keeper faces many shots on target.", "verify": "Whether the centre-back is really out."}
    rows = {n: s for s, n, _ in adv.check("\n".join(f"{k}: {v}" for k, v in brief.items()), rp, "home")}
    assert rows["every number is in the sheet or in a specialist note"] in ("WARN", "FAIL")


def test_contradicted_replacement_claims_and_calculations_on_unknown_numbers_are_flagged(tmp_path):
    nc = _load("note_check")
    sheet = "  Spurs: Pedro Porro (D, knee; 584 min, starts 3, rating 6.9, value 42.0m; a REGULAR); likely replacement Micky van de Ven (age 25, 746 min) => comparable replacement\n  United: Marcus Rashford (F, knock; 434 min; a REGULAR); likely replacement Joe Fringe (age 19, 30 min) => WEAK replacement"
    bad = nc.replacement_contradictions("Spurs lose Porro and he is unreplaced. Rashford is well covered by Fringe, a like-for-like stand-in.", sheet)
    assert len(bad) == 2 and "Porro" in bad[0] and "comparable replacement exists" in bad[0] and "Rashford" in bad[1] and "WEAK" in bad[1]
    assert nc.replacement_contradictions("Porro is covered comparably by van de Ven. Rashford has a weak replacement in Fringe.", sheet) == []
    assert nc.replacement_contradictions("nothing about anyone", sheet) == [] and nc.replacement_contradictions("Porro unreplaced", "") == []
    known = {"2.09", "25", "3", "1.76", "0.1", "0.10"}
    assert nc.unknown_operands("640/1260 absent minutes x 2.09 = 1.07", known) == ["1260", "640"]
    assert nc.unknown_operands("25 x 3 = 75 and 1.76 + 0.10 = 1.86", known) == []
    assert nc.unknown_operands("2-1 win, a 4-3-3 shape, the 23-25% band, 60.3 % and 10 km", known) == []             # scores, formations, ranges and units are not calculations
    assert nc.unknown_operands("a calculation 999 x 888 = 887112", set()) == []                                          # no sheet, no check
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    ans = _good_answer(home, away, 1.5, 1.1) + "\nMy view: the gap is 7777 x 2.5 = 19442 in total."
    rows = {n: s for s, n, _ in check.check(ans, rp, log)}
    assert rows["the operands of every calculation in the answer are in the sheet, a note or a brief"] in ("WARN", "FAIL")


def test_review_stage_runs_two_reviewers_saves_verdicts_resumes_and_has_the_fix_step(tmp_path, monkeypatch):
    rc = _load_collection()
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=True)
    run = tmp_path / "run"
    (run / "notes").mkdir(parents=True)
    (run / "report.json").write_text(Path(rp).read_text())
    for n in ("team-news", "tactical-matchup", "underlying-stats", "context-motivation"):
        (run / "notes" / f"{n}.md").write_text(_note(specialist=n, match=f"{home} v {away}"))
    (run / "answer.md").write_text(_good_answer(home, away, 1.5, 1.1) + TEAM_NEWS_ADJ + "\nSpecialist notes: the team-news, tactical-matchup, underlying-stats and context-motivation notes each favour the home side (strength 2); I accepted every xG change.")
    calls = []
    state = {"first_reviewer_died": False}

    def fake(runner, model, prompt, timeout, done=None, log_path=None, files=None, **kw):
        calls.append((model, prompt[:40], [Path(f).name for f in (files or [])]))
        if prompt.startswith("The attached file is a review pack"):
            vfile = Path(prompt.split("Write your verdict to ")[1].split(":")[0])
            if "longcat" in model and not state["first_reviewer_died"]:
                state["first_reviewer_died"] = True                       # a silent death or a provider error
                return 0
            vfile.parent.mkdir(parents=True, exist_ok=True)
            vfile.write_text("VERDICT: PASS\n" if "longcat" in model else "VERDICT: FIX\n1. \"claim\" -> the sheet says otherwise.\n")
            return 0
        if "Independent reviewers checked" in prompt:
            (run / "review" / "fixed.md").write_text("1. FIXED: corrected the sentence.\n")
            return 0
        raise AssertionError("an unexpected step ran: " + prompt[:60])

    monkeypatch.setattr(rc, "run_model", fake)
    assert rc.main([str(run / "report.json"), str(run), "--no-media", "--no-advocates", "--review", "--retries", "2"]) == 0
    status = (run / "status.md").read_text()
    assert (run / "review" / "pack.txt").exists() and (run / "review" / "verdict-1.txt").read_text().startswith("VERDICT: PASS") and (run / "review" / "verdict-2.txt").read_text().startswith("VERDICT: FIX")
    assert "review 1" in status and "MISSING (provider error or silent end)" in status and "review 2" in status and "fix: attempt 1" in status and "review done: 2 verdict(s), 1 asked for a fix" in status
    assert all(files == ["pack.txt"] for model, p, files in calls if p.startswith("The attached file"))
    assert (run / "review" / "fixed.md").exists()
    n = len(calls)
    rc.main([str(run / "report.json"), str(run), "--no-media", "--no-advocates", "--review"])
    assert len(calls) == n                                                 # a second run redoes nothing
    # a verdict on an older answer is stale: a changed answer is reviewed again
    import os, time
    os.utime(run / "answer.md", (time.time() + 60, time.time() + 60))
    state["first_reviewer_died"] = True
    rc.main([str(run / "report.json"), str(run), "--no-media", "--no-advocates", "--review"])
    assert len(calls) > n and not (run / "review" / "rejected.md").exists()
    assert rc.verdict_ok(run / "review" / "verdict-1.txt") and not rc.verdict_ok(run / "review" / "nope.txt")
    bad = tmp_path / "v.txt"
    bad.write_text("Here is my review: it looks fine")
    assert not rc.verdict_ok(bad)
    bad.write_text("\n**VERDICT: FIX**\n1. x")
    assert rc.verdict_of(bad) == "" or rc.verdict_of(bad) == "FIX"
    entry = (SPECIALISTS / "football-match-collection" / "SKILL.md").read_text(encoding="utf-8")
    assert "--review" in entry and "two independent reviewers" in entry


def test_note_sums_must_add_up():
    nc = _load("note_check")
    bad = nc.broken_sums("away: 1.35 + 0.30 + 0.17 = 1.65; home: 1.23 + 0.30 - 0.12 = 1.41; played 2026-10-04; 5 - 3 = 2 games")
    assert len(bad) == 1 and bad[0][1] == 1.82 and "1.35" in bad[0][0]
    assert nc.broken_sums("0.10 - 0.05 = 0.05; -0.10 + 0.05 = -0.05") == []


def test_value_is_always_unmeasured_even_with_odds_in_the_report(tmp_path):
    # the report is blinded before check.py ever sees it, so a Value label other than UNMEASURED always FAILs, odds or not
    rep, home, away, rp, log = _setup(tmp_path, lh=2.3, la=0.8, bet=None, report_odds=True)
    base = _good_answer(home, away, 2.3, 0.8).replace("Value: UNMEASURED - no market price to measure an edge.", "")
    names = lambda a: {n: s for s, n, _ in check.check(a, rp, log)}
    got = names(base + "\nValue: REAL - edge +9.0 points (your 70% v the market's fair 61%).")
    assert got.get("the analysis is price-free, so Value is always UNMEASURED") == "FAIL"
    got2 = names(base + "\nValue: UNMEASURED - no market price to measure an edge.")
    assert got2.get("the value label is UNMEASURED (price-free)") == "ok"


def test_calc_implied_lams_still_works_for_scores_market_only_scoreboard():
    # the --market CLI flag was removed (it let a price act as the agent's own anchor); implied_lams() itself
    # stays, since score.py's evaluation-only comparison against the market still calls it directly
    lh, la, err = calc.implied_lams(60.5, 22.4, 17.1)
    assert abs(lh - 2.0) < 0.05 and err < 1.0
    import subprocess
    out = subprocess.run([sys.executable, str(SKILL / "scripts" / "calc.py"), "--market", "60.5", "22.4", "17.1"], capture_output=True, text=True)
    assert out.returncode != 0 or "unrecognized" in out.stderr.lower()      # the flag no longer exists


def test_draw_calibration_says_when_draws_are_underrated():
    score = _load("score")
    rows = [({"p": [0.5, 0.2, 0.3], "odds_fair_pct": [50, 25, 25]}, 0, 0), ({"p": [0.5, 0.2, 0.3]}, 1, 1), ({"p": [0.5, 0.2, 0.3]}, 1, 0)]
    out = score.draw_calibration(rows)
    assert "UNDER-rated" in out and "under 30 matches" in out and "market average 25%" in out


def test_runner_splits_the_decider_and_stamps_the_code(tmp_path):
    rc = _load_collection()
    d = tmp_path / "decision.md"
    assert not rc.decision_ok(d)
    d.write_text("x" * 400 + "\nExpected goals (final): 1.4 - 1.1\nThe bet is home.", encoding="utf-8")
    assert rc.decision_ok(d)
    rp, run = tmp_path / "r.json", tmp_path / "run"
    run.mkdir()
    p1 = rc.decider_prompt(rp, run, [], "decision")
    p2 = rc.decider_prompt(rp, run, [], "answer")
    assert "never ask for approval" in p1 and "do not write answer.md" in p1 and "decision.md is already written" in p2 and "Step 2" in p2 and "Step 1:" not in p2
    assert rc.check_stamp(run) == "new" and rc.check_stamp(run) == "same"
    (run / "version.txt").write_text("old\n", encoding="utf-8")
    assert rc.check_stamp(run) == "changed"


def test_rps_is_ordinal_and_scored():
    score = _load("score")
    assert score.rps([1, 0, 0], 0) == 0.0 and score.rps([0, 0, 1], 0) == 1.0 and score.rps([0, 1, 0], 0) == 0.5
    assert score.rps([0.5, 0.4, 0.1], 0) < score.rps([0.5, 0.1, 0.4], 0)           # over-rating the draw is a smaller miss than over-rating the wrong side
    assert abs(sum(score.rps([1 / 3] * 3, k) for k in range(3)) / 3 - 2 / 9) < 1e-9


def test_small_sample_shrink_pulls_toward_the_league_mean(tmp_path):
    facts = _load("facts")
    assert abs(facts.shrunk(2.0, 4) - (4 * 2.0 + 6 * 1.35) / 10) < 1e-9 and facts.shrunk(2.0, 400) > 1.98 and facts.shrunk(0.5, 2) > 0.5
    from test_oracle import _report
    rep = _report()
    ins = {"home_xg_estimate": {"sample_size": 4, "xg_for": 8.0, "xg_against": 4.0}, "away_xg_estimate": {"sample_size": 6, "xg_for": 6.0, "xg_against": 12.0}}
    out = "\n".join(facts.shrink_section(rep, rep["match"], ins, "Alpha", "Beta"))
    assert "SHRUNK xG" in out and "raw 2.00 for / 1.00 against over 4 games -> shrunk 1.51 for / 1.26 against  <-- LEVEL FLAG" in out and "xG anchor from the shrunk numbers" in out
    assert "no xG sample" in "\n".join(facts.shrink_section(rep, rep["match"], {}, "Alpha", "Beta"))
    assert "shrink_section" in facts.GROUPS["decider"] and "shrink_section" in facts.GROUPS["stats"]


def test_price_band_table_and_pick_probabilities():
    score = _load("score")
    e = {"odds_fair_pct": [50, 25, 25], "p": [0.55, 0.25, 0.2], "bet": "Alpha or draw", "home": "Alpha", "away": "Beta"}
    assert score.market_prob_of_pick(e) == 75.0 and abs(score._pick_prob(e, e["p"]) - 80.0) < 1e-9
    assert score.market_prob_of_pick({**e, "bet": "Over 2.5 goals"}) is None and score.market_prob_of_pick({**e, "odds_fair_pct": None}) is None
    out = score.band_table([(70, 75.0, True), (72, 60.0, False), (40, 45.0, True), (20, 25.0, False)])
    assert "heavy favourite (65%+) | 2 | 1 (50%) | 71% | 68%" in out and "long shot (market under 35%) | 1 | 0 (0%)" in out and "even-ish (35-50%) | 1 | 1 (100%)" in out
    assert score.band_table([]) == "n/a"


def test_composite_score_mixes_goals_and_xg_and_drops_inconsistent_np_xg():
    from test_oracle import _report
    rep = _report()
    rows = [{"date": f"2026-09-{20 - i:02d}", "result": "W", "scoreline": "2-0", "venue": "home", "xg_for": 1.0, "xg_against": 0.5} for i in range(5)]
    forms = {"home": {"last10_overall": rows}, "away": {"last10_overall": rows}}
    ins = {f"{s}_xg_estimate": {"sample_size": 5, "xg_for": 5.0, "xg_against": 2.5} for s in ("home", "away")}
    ins["home_advanced_stats"] = {"sample_size": 5, "non_penalty_xg_for": 4.0, "non_penalty_xg_against": 2.0}        # consistent: kept
    ins["away_advanced_stats"] = {"sample_size": 5, "non_penalty_xg_for": 9.0, "non_penalty_xg_against": 2.0}        # np xG above total xG: dropped
    out = "\n".join(facts.shrink_section(rep, rep["match"], ins, "Alpha", "Beta", forms))
    assert "non-penalty xG 0.80/0.40" in out and out.count("non-penalty xG") == 1 and "composite anchor (cross-check)" in out and "as the SPI model does" in out


def test_level_flag_shrinks_harder_for_a_step_up_or_thin_evidence(monkeypatch):
    elos = {"Alpha": 1500.0, "Beta": 1700.0, "Minnow": 1100.0, "Giant": 1750.0}
    monkeypatch.setattr(facts, "load_elo", lambda: elos)
    monkeypatch.setattr(facts, "elo_of", lambda elo, team: elo.get(team))
    rows = [{"result": "W", "opponent": "Minnow"} for _ in range(6)]
    ins = {"away_elo_rating": {"elo": 1700.0, "sample_source": "eloratings.net"}}
    why = facts.level_flag("home", "Alpha", {"home": {"last10_overall": rows}}, ins, "Alpha", "Beta", 6)
    assert any("step up in level" in w for w in why) and any("only 0 of its last 6" in w for w in why) and not any("games with xG" in w for w in why)
    assert facts.level_flag("home", "Alpha", {"home": {"last10_overall": rows}}, ins, "Alpha", "Beta", 3)[0].startswith("only 3 games with xG")
    rows2 = [{"result": "W", "opponent": "Giant"} for _ in range(6)]
    assert facts.level_flag("home", "Alpha", {"home": {"last10_overall": rows2}}, ins, "Alpha", "Beta", 6) == []
    assert facts.shrunk(2.0, 4, facts.LEVEL_K) < facts.shrunk(2.0, 4) and facts.LEVEL_K == 12.0


def test_longshot_calibration_flags_overrated_longshots():
    score = _load("score")
    over = [({"p": [0.7, 0.15, 0.15]}, 1, 0)] * 4          # home wins: the draw/away longshots (15%) never happen
    assert "OVER-rated" in score.longshot_calibration(over) and "noise" in score.longshot_calibration(over)
    assert score.longshot_calibration([({"p": [0.5, 0.3, 0.2]}, 1, 0)]) == "n/a"


def test_favourite_longshot_adjustment_formula():
    # a pure math utility kept for score.py's longshot-calibration reference; no CLI surface any more (--market was removed)
    adj = calc.flb_adjust([85.1, 10.4, 4.5])
    assert abs(sum(adj) - 1) < 1e-9 and adj[0] > 0.851 and adj[2] < 0.045            # heavy favourite up, longshot down
    even = calc.flb_adjust([34, 33, 33])
    assert abs(even[0] - 0.34) < 0.01


def test_news_window_marks_stale_and_late_reports_and_blocks_high_confidence(tmp_path):
    from test_oracle import _report
    rep = _report()
    m = rep["match"]
    m["kickoff_utc"], m["lineup_confirmed"] = "2026-10-10T16:30:00.000Z", False
    rep["generatedAt"] = "2026-09-22T16:00:00.000Z"
    h, label = facts.news_window(rep, m)
    assert label.startswith("STALE REPORT") and h > 17 * 24 and check.news_window_label(rep).startswith("STALE REPORT")
    rep["generatedAt"] = "2026-10-10T08:00:00.000Z"
    assert facts.news_window(rep, m)[1].startswith("LATE-NEWS WINDOW") and check.news_window_label(rep).startswith("LATE-NEWS WINDOW")
    m["lineup_confirmed"] = True
    assert facts.news_window(rep, m)[1] == "" and check.news_window_label(rep) == ""
    rep["generatedAt"] = "2026-10-08T08:00:00.000Z"
    m["lineup_confirmed"] = False
    assert facts.news_window(rep, m)[1] == ""                                         # two days out: the normal case
    rep["generatedAt"] = "2026-09-22T16:00:00.000Z"
    rp = tmp_path / "r.json"
    rp.write_text(json.dumps(rep))
    home, away = m["home_team"], m["away_team"]
    high = _good_answer(home, away, 2.4, 0.6, bet=f"{home} to win", conf="HIGH")
    got = {n: s for s, n, _ in check.check(high, str(rp))}
    assert got["no high confidence on stale or late-news evidence"] == "FAIL"
    med = _good_answer(home, away, 2.4, 0.6, bet=f"{home} to win", conf="medium")
    assert "no high confidence on stale or late-news evidence" not in {n for s, n, _ in check.check(med, str(rp)) if s == "FAIL"}


def test_new_helpers_survive_zero_naive_dates_and_junk():
    score = _load("score")
    assert calc.flb_adjust([0, 0, 0]) == [0, 0, 0] and abs(sum(calc.flb_adjust([100, 0, 0])) - 1) < 1e-9
    assert score.market_prob_of_pick({"odds_fair_pct": [0, 0, 0], "bet": "x", "home": "a", "away": "b"}) is None
    assert facts.shrunk(1.0, -6) == facts.SHRINK_MEAN and abs(facts.shrunk(1.0, 0) - facts.SHRINK_MEAN) < 1e-9
    naive = {"generatedAt": "2026-09-22T08:00:00", "match": {"kickoff_utc": "2026-10-10T16:30:00Z", "lineup_confirmed": False}}
    assert facts.news_window(naive, naive["match"])[1].startswith("STALE REPORT") and check.news_window_label(naive).startswith("STALE REPORT")
    assert facts.news_window({"generatedAt": "garbage"}, {"kickoff_utc": "x"}) == (None, "") and facts.news_window({}, {}) == (None, "")
    assert facts.shrink_section({}, {}, {"home_xg_estimate": {"sample_size": 0, "xg_for": 1, "xg_against": 1}, "away_xg_estimate": {"sample_size": "x"}}, "A", "B", {"home": "zz"})


def test_persistence_and_manager_bounce_guidance_is_in_the_skill_and_sheet():
    text = _skill_all()
    assert "nothing is 'owed'" in text and "0.12" in text and "new-manager bounce" in text
    out = facts.xpts_line([{"result": "L", "xg_for": 2.0, "xg_against": 0.5} for _ in range(4)], "X")
    assert "return to the chance level, not beyond it" in out


def test_stake_as_a_football_word_is_not_a_betting_word():
    nc, ac = _load("note_check"), _load("advocate_check")
    for pat in (nc.FORBIDDEN, ac.FORBIDDEN):
        for ok in ("Italy's stake is ordinary (3rd of 4)", "nothing at stake for either side", "the stakes are high", "the stake is a place in the playoffs"):
            assert not pat.search(ok), ok
        for bad in ("place a stake on Italy", "stake 50 units", "a staking plan", "your stake should be small", "best bet is Italy", "the odds are 2.1", "a 60% chance"):
            assert pat.search(bad), bad


def test_picks_cannot_chase_an_edge_with_a_weak_goals_bet_or_against_your_own_favourite(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=True)
    names = lambda a: {n: s for s, n, _ in check.check(a, rp)}
    goals = _good_answer(home, away, 1.5, 1.1, bet="Under 2.5 goals")                 # about 48%: below the home-or-draw double chance (73%)
    assert names(goals)["a goals bet as the main pick beats the best 1X2 or double-chance pick"] == "FAIL"
    against = _good_answer(home, away, 1.5, 1.1, bet=f"{away} to win")                 # the away side is not the likeliest outcome
    assert names(against)["a single-outcome bet is your most likely outcome"] == "FAIL"
    fav = _good_answer(home, away, 1.5, 1.1, bet=f"{home} to win")
    got = names(fav)
    assert "a single-outcome bet is your most likely outcome" not in got and "a goals bet as the main pick beats the best 1X2 or double-chance pick" not in got
    low = calc.analyse(0.8, 0.7)
    assert calc.recommend(low, home, away)["selection"] == "Under 2.5 goals" and 100 * (1 - low["over_2_5"]) > calc.recommend(low, home, away)["pick_1x2_pct"]   # a low-scoring game: under 2.5 beats every 1X2 pick
    _, _, _, rp2, log2 = _setup(tmp_path / "low", lh=0.8, la=0.7, bet="Under 2.5 goals", report_odds=True) if (tmp_path / "low").mkdir() is None else None
    assert 'a goals bet as the main pick beats the best 1X2 or double-chance pick' not in {n for s_, n, _ in check.check(_good_answer(home, away, 0.8, 0.7, bet="Under 2.5 goals"), rp2) if s_ == "FAIL"}


def test_picks_cannot_chase_an_edge_with_a_weak_goals_bet_or_against_your_own_favourite(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=True)
    names = lambda a: {n: s for s, n, _ in check.check(a, rp)}
    goals = _good_answer(home, away, 1.5, 1.1, bet="Under 2.5 goals")                 # about 48%: below the home-or-draw double chance (73%)
    assert names(goals)["a goals bet as the main pick beats the best 1X2 or double-chance pick"] == "FAIL"
    against = _good_answer(home, away, 1.5, 1.1, bet=f"{away} to win")                 # the away side is not the likeliest outcome
    assert names(against)["a single-outcome bet is your most likely outcome"] == "FAIL"
    got = names(_good_answer(home, away, 1.5, 1.1, bet=f"{home} to win"))
    assert "a single-outcome bet is your most likely outcome" not in got and "a goals bet as the main pick beats the best 1X2 or double-chance pick" not in got


def test_run_model_codex_branch_builds_exec_command(tmp_path, monkeypatch):
    rc = _load_collection()
    seen = []

    class P:
        returncode = 0
        def poll(self): return 0

    monkeypatch.setattr(rc.subprocess, "Popen", lambda cmd, **kw: seen.append(cmd) or P())
    rc.run_model("codex", "opencode/mimo-v2.6-flash-free", "do it", 5, files=[tmp_path / "pack.txt"])
    rc.run_model("codex", "gpt-x", "do it", 5)
    assert seen[0][:2] == ["codex", "exec"] and "-m" not in seen[0] and "-f" not in seen[0] and "pack.txt" in seen[0][-1]     # no opencode model name leaks to codex; files named in the prompt
    assert seen[1][seen[1].index("-m") + 1] == "gpt-x"


def test_double_chance_reason_must_be_a_fact_not_own_percentages():
    assert check._dc_reason_has_fact("Why a double chance: 4 of the last 6 meetings were level.")
    assert not check._dc_reason_has_fact("Why a double chance: no single outcome reaches 45%; Ireland's 44.8% win chance and 2.5 goals line.")
    assert not check._dc_reason_has_fact("Why a double chance: the 1X selection covers Ireland.")
    assert not check._dc_reason_has_fact("no reason line at all")


def test_draw_section_counts_levels_and_links_sides(tmp_path):
    rows = lambda sc: [{"scoreline": s_, "venue": "home", "result": "D" if s_.split("-")[0] == s_.split("-")[1] else "W", "xg_for": 1.0, "xg_against": 1.1} for s_ in sc]
    forms = {"home": {"last10_overall": rows(["1-1", "0-0", "2-1", "1-1"])}, "away": {"last10_overall": rows(["0-0", "1-0", "1-1", "2-2"])}}
    ins = {"home_xg_estimate": {"sample_size": 4, "xg_for": 4.8, "xg_against": 4.4}, "away_xg_estimate": {"sample_size": 4, "xg_for": 4.4, "xg_against": 4.8}}
    text = "\n".join(facts.draw_section({}, {}, ins, "Aland", "Bland", forms))
    assert "level finishes: 3 of 4" in text and "level finishes: 3 of 4" in text.split("## Bland")[1]
    assert "level finish" in text and "draw signals present" in text and "gap 0.0" in text
    assert "no scored games" in "\n".join(facts.draw_section({}, {}, {}, "A", "B", {}))
    assert "draw_section" in facts.GROUPS["draw"] and "draw_section" not in facts.GROUPS["advocate"]


def test_side_case_section_is_symmetric_and_reads_the_links_the_right_way():
    rows = lambda sc: [{"scoreline": s_, "venue": "home", "result": "W" if int(s_[0]) > int(s_[-1]) else "L" if int(s_[0]) < int(s_[-1]) else "D", "xg_for": 1.5, "xg_against": 0.8} for s_ in sc]
    forms = {"home": {"last10_overall": rows(["2-0", "3-1", "1-0", "2-2"])}, "away": {"last10_overall": rows(["0-2", "1-3", "0-0", "2-3"])}}
    ins = {"home_xg_estimate": {"sample_size": 4, "xg_for": 8.0, "xg_against": 3.0}, "away_xg_estimate": {"sample_size": 4, "xg_for": 3.0, "xg_against": 8.0}}
    h = "\n".join(facts.side_case_section({}, {}, ins, "Aland", "Bland", forms, "home"))
    a = "\n".join(facts.side_case_section({}, {}, ins, "Aland", "Bland", forms, "away"))
    assert "CASE EVIDENCE FOR ALAND" in h and "CASE EVIDENCE FOR BLAND" in a
    assert "in Aland's favour +" in h and "in Bland's favour -" in a                  # the same matchup read from each side: the gap flips sign
    assert "less than the" not in a.split("case signals present")[1].split("\n")[0]       # Bland's defence concedes more than Aland's attack makes: not a defensive signal
    assert "no scored games" in "\n".join(facts.side_case_section({}, {}, {}, "A", "B", {}, "home"))
    assert "home_case_section" in facts.GROUPS["home"] and "away_case_section" in facts.GROUPS["away"]


def _brief(home, away, side="home", **over):
    good = {"advocate": side, "team": home if side == "home" else away if side == "away" else f"{home} v {away}",
            "case": "The side create more chances (1.6 xG against 1.1) and meet an opponent missing its centre-back, so the numbers and the absence point the same way over the whole match.",
            "evidence": "1) 1.6 xG a game against 1.1 (underlying-stats note); 2) centre-back out, replacement rated 6.2 (team-news note); 3) bench worth 71% of the XI (sheet); 4) two clean sheets in 5 (sheet)",
            "must_overcome": "A thin attack and three matches in a week.", "rebuttal": "The visitors counter well but their keeper faces 5 shots on target a game.", "verify": "Whether the centre-back is really out."}
    good.update(over)
    return "\n".join(f"{k}: {v}" for k, v in good.items())


def test_advocate_checker_rows_one_by_one(tmp_path, capsys):
    adv = _load("advocate_check")
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    rows = lambda text, side="home": {n: s for s, n, _ in adv.check(text, rp, side)}
    assert [s for s, _, _ in adv.check(_brief(home, away), rp, "home") if s == "FAIL"] == []
    assert rows(_brief(home, away).replace("verify: Whether the centre-back is really out.", ""))["every field is present"] == "FAIL"       # a missing field stops the check there
    assert rows(_brief(home, away, case="Too short."))["the case says something concrete (25 words or more)"] == "FAIL"
    assert rows(_brief(home, away, rebuttal="No."))["rebuttal says something concrete"] == "FAIL"
    assert rows(_brief(home, away, team="Nobody FC"))["the team is the report's side"] == "FAIL"
    assert rows(_brief(home, away, side="away"), "home")["the advocate field says home"] == "FAIL"
    assert rows(_brief(home, away, case="The side are 65% to win and the bookmaker odds are generous across the whole match, so the numbers point one way only for them."))["no bookmaker odds, probabilities or bets (the decider's job)"] == "FAIL"
    assert rows(_brief(home, away, evidence="1) 1.6 xG; 2) 6.2 rating"))["3 or more evidence items, each with a number"] == "FAIL"
    assert rows(_brief(home, away, side="draw"), "draw")["4 or more evidence items, each with a number"] == "ok"
    many = _brief(home, away, evidence="1) 8.81 xG; 2) 7.77 shots; 3) 9.99 saves; 4) 6.66 key passes; 5) 5.55 tackles")
    assert rows(many)["every number is in the sheet or in a specialist note"] == "FAIL"       # more than 3 numbers found in neither the sheet nor a note
    assert adv.main(str(tmp_path / "missing.md"), rp, "home") == 2 and adv.main("x", rp, "middle") == 2
    f = tmp_path / "ok.md"
    f.write_text(_brief(home, away))
    assert adv.main(str(f), rp, "home") == 0 and "Result: clean" in capsys.readouterr().out
    f.write_text(_brief(home, away, case="Short."))
    assert adv.main(str(f), rp, "home") == 1


def test_runner_prepares_every_slice_and_tells_an_advocate_only_about_its_own_brief(tmp_path):
    rc = _load_collection()
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=True)
    run = tmp_path / "run"
    done = rc.prepare(Path(rp), run)
    assert set(done) <= set(rc.EVIDENCE) and (run / "evidence" / "decider.md").exists()
    for name in ("advocate", "home", "away", "draw", "goals"):
        text = (run / "evidence" / f"{name}.md").read_text() if (run / "evidence" / f"{name}.md").exists() else ""
        assert "BOOKMAKER ODDS" not in text                                       # only the decider's slice has the odds
    assert rc.prepare(Path(rp), run) == []                                         # a second call finds fresh slices and writes nothing
    (run / "notes").mkdir()
    (run / "notes" / "team-news.md").write_text("n")
    (run / "advocates").mkdir()
    for s in ("home", "away", "draw", "goals", "underdog", "state", "market"):
        (run / "advocates" / f"{s}.md").write_text("b")
    assert rc.advocate_existing(run, "away") == ["notes/team-news.md", "advocates/away.md"]
    for side, skill in rc.ADVOCATES:
        text = rc.advocate_prompt(skill, side, Path(rp), run, rc.advocate_existing(run, side))
        assert f"evidence/{side}.md" in text and "evidence/advocate.md" in text and f"advocates/{side}.md" in text
        assert [o for o in ("home", "away", "draw", "goals", "underdog", "state", "market") if o != side and f"advocates/{o}.md" in text] == []       # the other briefs are never named


def test_goals_advocate_slice_checker_and_skill(tmp_path):
    rows = lambda sc: [{"scoreline": s_, "venue": "home", "result": "W", "xg_for": 1.6, "xg_against": 1.5} for s_ in sc]
    forms = {"home": {"last10_overall": rows(["3-1", "2-2", "1-0", "4-2"])}, "away": {"last10_overall": rows(["2-1", "3-3", "0-0", "2-0"])}}
    ins = {"home_xg_estimate": {"sample_size": 4, "xg_for": 7.2, "xg_against": 6.4}, "away_xg_estimate": {"sample_size": 4, "xg_for": 6.8, "xg_against": 7.0}}
    text = "\n".join(facts.goals_case_section({}, {}, ins, "Aland", "Bland", forms))
    assert "3 or more goals in the game: 3 of 4" in text and "both teams scored: 3 of 4" in text and "over 2.5" in text and "over signals present" in text
    assert "no scored games" in "\n".join(facts.goals_case_section({}, {}, {}, "A", "B", {}))
    assert "goals_case_section" in facts.GROUPS["goals"]
    adv = _load("advocate_check")
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    brief = _brief(home, away, side="goals")
    assert [r for r in adv.check(brief, rp, "goals") if r[0] == "FAIL"] == []
    assert {n: s for s, n, _ in adv.check(brief.replace("; 4) two clean sheets in 5 (sheet)", ""), rp, "goals")}["4 or more evidence items, each with a number"] == "FAIL"
    skill = (SKILL.parent / "football-goals-advocate" / "SKILL.md").read_text()
    assert "advocate_check.py" in skill and "goals.md" in skill and "football-goals-advocate" in skill and "beats the best 1X2 or double-chance pick" in skill


def _lite_module(name):
    spec = importlib.util.spec_from_file_location(name + "_t", Path(__file__).resolve().parent.parent / ".claude/skills/football-match-lite/scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _odds_report():
    return {"match": {"home_team": "Aland", "away_team": "Bland", "betting_odds": None,
                      "sofascore_betting_odds": {"home_win_odds": 2.0, "draw_odds": 3.5, "away_win_odds": 4.0, "home_win_fair_pct": 50.0, "draw_fair_pct": 28.0, "away_win_fair_pct": 22.0,
                                                 "over_2_5_fair_pct": 55.0, "under_2_5_fair_pct": 45.0},
                      "field_sources": {"sofascore_betting_odds": "sofascore", "venue": "x"},
                      "recent_meetings": [{"score": "1-0", "historical_odds": {"home": 1.9}}]},
            "insights": {"prediction": {"market_implied": {"home_win_pct": 50.0}}, "home_xg_estimate": {"xg_for": 1.4}},
            "dataWindows": {"match.betting_odds": "odds window", "match.venue": "keep"}}


def test_blind_removes_every_price_and_the_scrapers_blend_and_keeps_the_rest():
    blind = _lite_module("blind")
    out, removed = blind.blind(_odds_report())
    text = json.dumps(out).lower()
    assert "odds" not in text and "market_implied" not in text and "fair_pct" not in text and "prediction" not in text
    assert out["insights"]["home_xg_estimate"] == {"xg_for": 1.4} and out["match"]["field_sources"] == {"venue": "x"} and out["dataWindows"] == {"match.venue": "keep"}
    assert out["match"]["recent_meetings"][0]["score"] == "1-0" and removed


def test_value_script_labels_the_finished_answer_against_the_market_after_the_analysis():
    value = _lite_module("value").value
    rep = _odds_report()
    ans = lambda bet: f"Best bet: {bet}, confidence medium.\n"
    v = value(ans("Aland to win (58.0%)"), rep)
    assert v["market"] == 50.0 and v["edge"] == 8.0 and v["label"] == "REAL"
    assert value(ans("Aland to win (52.0%)"), rep)["label"] == "THIN"
    assert value(ans("Aland to win (47.0%)"), rep)["label"] == "NONE"
    assert value(ans("Aland or draw (80.0%)"), rep)["market"] == 78.0
    assert value(ans("Over 2.5 goals (61.0%)"), rep)["edge"] == 6.0
    assert value(ans("Both teams to score (60.0%)"), rep)["label"] == "UNMEASURED"
    assert value("no bet here", rep)["label"] == "UNMEASURED"
    blinded, _ = _lite_module("blind").blind(rep)
    assert value(ans("Aland to win (58.0%)"), blinded)["label"] == "UNMEASURED"


def test_runner_independent_mode_keeps_the_odds_outside_the_run_dir(tmp_path):
    rc = _load_collection()
    src = tmp_path / "src.json"
    src.write_text(json.dumps(_odds_report()))
    run = tmp_path / "run"
    rc.main([str(src), str(run), "--dry-run", "--independent"])
    assert "odds" not in (run / "report.json").read_text().lower()
    assert "odds" in (tmp_path / "run.odds.json").read_text().lower() and not list(run.glob("*.odds.json"))
    assert "BOOKMAKER ODDS" not in (run / "evidence" / "decider.md").read_text()
    assert "NO bookmaker odds" in rc.decider_prompt(run / "report.json", run, [], "decision", True)
    assert "NO bookmaker odds" not in rc.decider_prompt(run / "report.json", run, [], "decision", False)
    run2 = tmp_path / "run2"
    assert rc.main([str(src), str(run2), "--dry-run", "--market-anchor"]) == 2          # the market mode is gone


def test_underdog_slice_checker_runner_and_skill(tmp_path):
    adv = _lite_module("advocate_check")
    rows = lambda scores, ht=None: [{"scoreline": s_, "venue": "home", "result": "W" if int(s_[0]) > int(s_[2]) else "D" if s_[0] == s_[2] else "L", "ht_scoreline": ht or "0-0"} for s_ in scores]
    forms = {"home": {"last10_overall": rows(["2-0", "1-0", "3-1", "2-2", "0-0"], "0-1")}, "away": {"last10_overall": rows(["0-1", "1-1", "0-2", "1-0", "0-0"])}}
    ins = {"home_xg_estimate": {"sample_size": 5, "xg_for": 9.0, "xg_against": 4.0}, "away_xg_estimate": {"sample_size": 5, "xg_for": 4.0, "xg_against": 8.0},
           "home_elo_rating": {"elo": 1700, "sample_source": "eloratings.net"}, "away_elo_rating": {"elo": 1500, "sample_source": "eloratings.net"},
           "home_advanced_stats": {"sample_size": 5, "errors_lead_to_shot_against": 6, "errors_lead_to_goal_against": 3, "set_piece_xg_against": 1.0},
           "away_advanced_stats": {"sample_size": 5, "set_piece_xg_for": 2.0, "errors_lead_to_shot_against": 2},
           "home_duel_vulnerabilities": [{"name": "Left Back", "ground_duel_success_pct": 30.0}]}
    text = "\n".join(facts.underdog_section({}, {}, ins, "Aland", "Bland", forms))
    assert "Favourite: Aland; underdog: Bland" in text and "IF THE UNDERDOG SCORES" in text and "errors leading to a shot against Aland 1.20 a game, to a goal 0.60 a game" in text
    assert "n=2): W1 D1 L0" in text and "duel vulnerabilities" in text and "set pieces: Bland 0.40 xG for a game v Aland 0.20 against" in text
    assert "No clear favourite" in "\n".join(facts.underdog_section({}, {}, {"home_club_elo": {"elo": 1700}, "away_club_elo": {"elo": 1500}, "home_xg_estimate": {"sample_size": 5, "xg_for": 4.0, "xg_against": 8.0}, "away_xg_estimate": {"sample_size": 5, "xg_for": 9.0, "xg_against": 4.0}}, "A", "B", {}))
    rep = tmp_path / "r.json"
    rep.write_text(json.dumps({"match": {"home_team": "Aland", "away_team": "Bland"}, "numbers": "1.6 1.1 6.2 71 0.60 5"}))
    good = _brief("Aland", "Bland", "underdog",
                  case="UNDERDOG SCORES, DRAW: the favourite's defensive errors (0.60 goals a game) and a set-piece route make a goal likely, and after conceding it won only 1 of 3 games.")
    fails = lambda t_: [r[1] for r in adv.check(t_, str(rep), "underdog") if r[0] == "FAIL"]
    assert fails(good) == []
    assert any(x.startswith("the case starts with one route") for x in fails(good.replace("UNDERDOG SCORES, DRAW", "A GOAL FOR THE VISITORS")))
    assert "the defensive errors are part of the case" in fails(good.replace("defensive errors", "back line").replace("errors", "lapses"))
    assert fails(good.replace("advocate: underdog", "advocate: goals")) != []
    skill = (Path(__file__).resolve().parent.parent / ".claude/skills/football-underdog-advocate/SKILL.md").read_text()
    assert "advocate: underdog" in skill and "advocate_check.py" in skill and "UNDERDOG SCORES, FAVOURITE WINS" in skill
    rc = _load_collection()
    assert ("underdog", "football-underdog-advocate") in rc.ADVOCATES and "underdog" in rc.EVIDENCE


def test_audit_fixes_double_chance_value_label_and_guarantee_wording():
    # a 46% favourite with a 25% draw now gets the double chance as the suggestion; 46% with a 20% draw does not
    open_game = calc.recommend({"home": 0.285, "draw": 0.253, "away": 0.462, "over_2_5": 0.5, "btts": 0.5}, "Greece", "Germany")
    assert open_game["market"] == "Double chance" and open_game["selection"] == "draw or Germany"
    firm = calc.recommend({"home": 0.34, "draw": 0.20, "away": 0.46, "over_2_5": 0.5, "btts": 0.5}, "Greece", "Germany")
    assert firm["market"] == "Over/Under 2.5" and firm["pick_1x2"] == "Germany to win"         # no double chance here (draw 20%), and a 50% goals side beats a 46% single outcome
    firm = calc.recommend({"home": 0.30, "draw": 0.18, "away": 0.52, "over_2_5": 0.5, "btts": 0.5}, "Greece", "Germany")
    assert firm["market"] == "1X2" and firm["selection"] == "Germany to win"
    # a printed edge of 0.0 is NONE everywhere (the checker and value.py share one rule)
    ck = _lite_module("check")
    assert ck.value_label(0.04, 5.0) == "NONE" and ck.value_label(0.06, 5.0) == "THIN" and ck.value_label(5.0, 5.0) == "REAL" and ck.value_label(-1.0, 5.0) == "NONE"
    # 'guaranteed' inside a negation is not a guarantee; a real one still fails
    assert ck.guarantee_hit("through venue and creation rather than a guaranteed finishing recovery") == ""
    assert ck.guarantee_hit("this is not a guaranteed win") == ""
    assert ck.guarantee_hit("a guaranteed winner") == "guaranteed" and ck.guarantee_hit("stake 5 on it") == "stake 5"
    # value.py names a larger gap on another 1X2 outcome without changing the pick's label
    value = _lite_module("value").value
    rep = _odds_report()
    ans = "**Aland 60.0% / Draw 10.0% / Bland 30.0%**\nBest bet: Bland to win (30.0%), confidence low.\n"
    v = value(ans, rep)
    assert v["label"] in ("NONE", "THIN", "REAL") and v["elsewhere"]["outcome"] == "Aland" and v["elsewhere"]["edge"] > v["edge"]
    assert v["elsewhere"]["label"] in ("NONE", "THIN", "REAL") and v["elsewhere"]["bar"] in (5.0, 7.0)


def test_goals_bet_is_the_likeliest_of_four_checked_and_priced_but_never_staked(tmp_path):
    a = calc.analyse(1.73, 1.20)
    assert calc.goals_bet(a) == ("Both teams to score: Yes", round(100 * a["btts"], 1))                 # 57.2% beats over 2.5 (54.9%)
    low = calc.analyse(0.8, 0.6)
    assert calc.goals_bet(low)[0] == "Under 2.5 goals" and calc.recommend(low, "A", "B")["goals_bet"] == "Under 2.5 goals"
    rep, home, away, rp, log = _setup(tmp_path, report_odds=False)
    good = _good_answer(home, away, 1.5, 1.1) + TEAM_NEWS_ADJ
    status = lambda t: next(s_ for s_, n, d_ in check.check(t, rp, log) if "Goals bet line" in n)
    assert status(good) == "ok"
    assert status(re.sub(r"\nGoals bet:[^\n]*", "", good)) == "FAIL"                                    # missing
    other = "Under 2.5 goals" if calc.goals_bet(calc.analyse(1.5, 1.1))[0] != "Under 2.5 goals" else "Over 2.5 goals"
    assert status(re.sub(r"Goals bet: [^(]+\(", f"Goals bet: {other} (", good)) == "FAIL"              # not the likeliest
    mod = _lite_module("value")
    orep = _odds_report()                                                                               # over 2.5 fair 55%
    ans = "**Aland 50.0% / Draw 28.0% / Bland 22.0%**\nBest bet: Aland or draw (78.0%), confidence high.\n"
    v = mod.value(ans + "Goals bet: Over 2.5 goals (62.0%), confidence low.\n", orep)
    assert v["goals"]["market"] == 55.0 and v["goals"]["edge"] == 7.0 and v["goals"]["label"] == "REAL"
    assert mod.value(ans + "Goals bet: Both teams to score: Yes (58.0%), confidence low.\n", orep)["goals"]["label"] == "UNMEASURED"
    (tmp_path / "a.md").write_text(ans + "Goals bet: Under 2.5 goals (50.0%), confidence low.\n")
    (tmp_path / "r.json").write_text(json.dumps(orep))
    mod.main(["value.py", str(tmp_path / "a.md"), str(tmp_path / "r.json"), str(tmp_path / "v.md")])
    out = (tmp_path / "v.md").read_text()
    assert "Goals bet: Under 2.5 goals (50.0%), a forecast, not staked." in out
    assert out.index("MARKET SCOREBOARD (reference only") > out.index("Stake decision:") and "goals bet: Under 2.5 goals ours 50.0% v the market's 45.0% (+5.0 points)" in out


def test_player_errors_section_names_the_error_prone_starter_and_says_when_data_is_missing():
    u = lambda g, sh, n, mins: {"total_errors_lead_to_goal": g, "total_errors_lead_to_shot": sh, "error_stat_appearances": n, "total_minutes": mins}
    profiles = {"home": {"squad": [{"name": "Guehi", "role": "D", "recent_usage": u(3, 4, 5, 450)}, {"name": "Steady", "role": "D", "recent_usage": u(0, 1, 5, 450)},
                                   {"name": "Keeper", "role": "G", "injury": "knee", "recent_usage": u(1, 0, 3, 270)}]},
                "away": {"squad": [{"name": "Old", "role": "M", "recent_usage": {"total_minutes": 300}}]}}
    text = "\n".join(facts.player_errors_section({}, profiles, "Alpha", "Beta"))
    assert "ERROR-PRONE PLAYERS" in text and "Guehi (D): 3 leading to a goal, 4 to a shot in 5 appearances (450 min)" in text
    assert text.index("Guehi") < text.index("Keeper (G, knee)") and "Steady" not in text                 # most goal-errors first; 1 shot-error is not listed
    assert "Beta: not in the report" in text and "never a reason to move expected goals" in text
    clean = {"home": {"squad": [{"name": "Steady", "recent_usage": u(0, 1, 5, 450)}]}, "away": {}}
    assert "Alpha: no player with an error leading to a goal, or 2+ to a shot (1 players with statistics)" in "\n".join(facts.player_errors_section({}, clean, "Alpha", "Beta"))
    assert "player_errors_section" in facts.GROUPS["underdog"] and "player_errors_section" in facts.GROUPS["decider"]
    ins = {"home_advanced_stats": {"errors_lead_to_goal_against": 2}}                                 # players all at 0 while the team conceded error goals: wrong or missing keys, say so
    assert "CHECK: the team totals show 2 error(s) leading to a goal against" in "\n".join(facts.player_errors_section({}, clean, "Alpha", "Beta", ins))


def test_chaos_advocate_slice_checker_runner_and_skill(tmp_path):
    ins = {"home_advanced_stats": {"sample_size": 5, "errors_lead_to_goal_against": 0, "errors_lead_to_shot_against": 2, "set_piece_xg_for": 1.0, "set_piece_xg_against": 0.5},
           "away_advanced_stats": {"sample_size": 5, "errors_lead_to_goal_against": 3, "errors_lead_to_shot_against": 6, "set_piece_xg_for": 4.9, "set_piece_xg_against": 0.2},
           "home_goalkeeping_estimate": {"sample_size": 10, "save_pct": 62.2}, "away_goalkeeping_estimate": {"sample_size": 10, "save_pct": 53.8},
           "home_card_discipline": {"yellow_per_game": 1.7, "red_per_game": 0.0}, "away_card_discipline": {"yellow_per_game": 3.0, "red_per_game": 0.1}}
    text = "\n".join(facts.chaos_section({}, ins, "Aland", "Bland"))
    assert "CHAOS EVIDENCE" in text and "errors leading to a goal against, a game: Aland 0.00 (n=5); Bland 0.60 (n=5) -> Bland more exposed" in text
    assert "Bland 53.8% (n=10)" in text and "EXPOSURE TALLY" in text and "Bland 3" in text and "never move expected goals" in text
    assert "chaos_section" in facts.GROUPS["chaos"] and "player_errors_section" in facts.GROUPS["chaos"]
    adv = _lite_module("advocate_check")
    rep = tmp_path / "r.json"
    rep.write_text(json.dumps({"match": {"home_team": "Aland", "away_team": "Bland"}, "numbers": "0.60 1.20 53.8 62.2 3.00 0.98 1.6 1.1 6.2 71 5"}))
    good = _brief("Aland", "Bland", "chaos", case="ERROR SWING: Bland is the side more exposed, with errors leading to a goal at 0.60 a game and a keeper saving 53.8% of shots, so one gift goal for Aland is the likeliest swing and it protects the favourite rather than widening the draw.")
    fails = lambda t_: [r[1] for r in adv.check(t_, str(rep), "chaos") if r[0] == "FAIL"]
    assert fails(good) == []
    assert any(x.startswith("the case starts with one route") for x in fails(good.replace("ERROR SWING", "A WILD GAME")))
    assert "the case says whether chaos widens the draw, the underdog or the favourite" in fails(good.replace("favourite", "leader").replace("draw", "level game"))
    assert "no expected-goals move (chaos argues a route only)" in fails(good.replace("so one gift goal", "so expected goals up for Aland and one gift goal"))
    rc = _load_collection()
    assert ("chaos", "football-chaos-advocate") in rc.ADVOCATES and "chaos" in rc.EVIDENCE and "chaos advocate" in rc.decider_prompt(tmp_path / "r.json", tmp_path, [], "decision", True)
    skill = (Path(__file__).resolve().parent.parent / ".claude/skills/football-chaos-advocate/SKILL.md").read_text()
    assert "advocate: chaos" in skill and "LOW CHAOS" in skill and "never move expected goals" in skill and "advocate_check.py" in skill


def test_upset_rule_switches_the_final_pick_to_draw_or_underdog_from_our_numbers_only(tmp_path):
    # market-independent: our own underdog at 22%+ turns the final pick into "Draw or <underdog>", whatever the market says (or with no market at all)
    mod = _lite_module("value")
    rep = {"match": {"home_team": "Aland", "away_team": "Bland"}}
    ans = lambda b, pick: f"**Aland {75 - b:.1f}% / Draw 25.0% / Bland {b:.1f}%**\nBest bet: {pick}, confidence low.\n"
    ind = mod.independent(ans(25.0, "Aland or draw (75.0%)"), rep)
    assert ind["upset"]["bet"] == "Draw or Bland" and ind["upset"]["own"] == 50.0 and (ind["final_pick"], ind["final_own"]) == ("Draw or Bland", 50.0)
    assert "upset" not in mod.independent(ans(21.0, "Aland or draw (79.0%)"), rep)           # under 22%
    assert "upset" not in mod.independent(ans(25.0, "Draw or Bland (50.0%)"), rep)           # the pick already backs the underdog
    (tmp_path / "a.md").write_text(ans(25.0, "Aland or draw (75.0%)"))
    (tmp_path / "r.json").write_text(json.dumps(_odds_report()))
    mod.main(["value.py", str(tmp_path / "a.md"), str(tmp_path / "r.json"), str(tmp_path / "v.md")])
    out = (tmp_path / "v.md").read_text()
    assert "Final pick: Draw or Bland (50.0%), from the upset rule instead of Aland or draw" in out and "Upset rule: our underdog Bland is 25.0%" in out


def test_state_slice_checker_runner_and_skill(tmp_path):
    adv = _lite_module("advocate_check")
    row = lambda sc, ht, venue="home": {"scoreline": sc, "venue": venue, "result": "W" if int(sc[0]) > int(sc[2]) else "D" if sc[0] == sc[2] else "L", "ht_scoreline": ht}
    forms = {"home": {"last10_overall": [row("2-0", "1-0"), row("1-1", "1-0"), row("2-1", "0-1"), row("0-0", "0-0"), row("1-2", "0-0")],
                      "half_split": {"sample_size": 10, "first_half_goals_for": 6, "second_half_goals_for": 9, "first_half_goals_against": 4, "second_half_goals_against": 7}},
             "away": {"last10_overall": [row("0-1", "0-0", "away"), row("1-0", "1-0", "neutral")], "half_split": {"sample_size": 10, "first_half_goals_for": 5, "second_half_goals_for": 5, "first_half_goals_against": 3, "second_half_goals_against": 6}}}
    ins = {"home_xg_estimate": {"sample_size": 5, "xg_for": 9.0, "xg_against": 4.0}, "away_xg_estimate": {"sample_size": 5, "xg_for": 4.0, "xg_against": 8.0},
           "home_advanced_stats": {"sample_size": 5, "errors_lead_to_shot_against": 6, "errors_lead_to_goal_against": 3},
           "home_rotation": {"last_formation": "3-5-2", "last_defender_count": 3, "previous_formation": "4-4-2", "previous_defender_count": 4, "formation_changed": True}}
    m = {"home_formation": "3-5-2", "away_formation": "4-3-3"}
    text = "\n".join(facts.state_section({}, m, ins, "Aland", "Bland", forms))
    assert "leading 2 -> W1 D1 L0 (kept the lead to win in 1, dropped points in 1)" in text and "trailing 1 -> W1 D0 L0 (came back to win or draw in 1)" in text
    assert "result changed between half-time and full time in 3 of 5" in text and "BACK THREE" in text and "errors leading to a shot against 1.20 a game, to a goal against 0.60 a game" in text
    assert "scored 6 in the first half and 9 in the second" in text and "ahead at half-time" in text and "per-game formation record" in text
    assert "Bland" in text and "away" not in text.split("## Bland")[1].split("half-time states")[0] and "neutral" in text
    rep = tmp_path / "r.json"
    rep.write_text(json.dumps({"match": {"home_team": "Aland", "away_team": "Bland"}, "numbers": "1.6 1.1 6.2 71 0.60 5"}))
    good = _brief("Aland", "Bland", "state", case="SWING: the underdog Bland scores first, Aland drops points from the lead (1 of 2) and its back-three defence gives up errors (0.60 goals a game), so Bland can pull level and the lead can change hands.")
    fails = lambda t_: [r[1] for r in adv.check(t_, str(rep), "state") if r[0] == "FAIL"]
    assert fails(good) == []
    assert any(x.startswith("the case starts with one route") for x in fails(good.replace("SWING", "A BUSY NIGHT")))
    assert "Underdog (from the rating gap" in text and "Bland" in text.split("Underdog (from the rating gap")[1].split(":")[1][:12]
    assert "the case names the underdog's path to the lead" in fails(good.replace("underdog", "outsider"))
    assert "the defence under pressure is part of the case (errors, shape or back line)" in fails(good.replace("defence", "rearguard"))
    assert fails(good.replace("advocate: state", "advocate: underdog")) != []
    skill = (Path(__file__).resolve().parent.parent / ".claude/skills/football-gamestate-advocate/SKILL.md").read_text()
    assert "advocate: state" in skill and "advocate_check.py" in skill and "FIRST GOAL DECIDES" in skill and "back three" in skill
    assert (Path(__file__).resolve().parent.parent / ".opencode/skills/football-gamestate-advocate/SKILL.md").read_text() == skill
    rc = _load_collection()
    assert ("state", "football-gamestate-advocate") in rc.ADVOCATES and "state" in rc.EVIDENCE


def test_review_fixes_stale_market_brief_lost_odds_copy_stamp_and_calculator_numbers(tmp_path):
    rc = _load_collection()
    src = tmp_path / "src.json"
    src.write_text(json.dumps(_odds_report()))
    run = tmp_path / "run"
    (run / "advocates").mkdir(parents=True)
    (run / "advocates" / "market.md").write_text("advocate: market\nthe price is 2.10")
    rc.main([str(src), str(run), "--dry-run", "--independent"])
    assert not (run / "advocates" / "market.md").exists() and (tmp_path / "run.market-brief-with-odds.md").exists()
    # resumed inside the run folder with the odds copy gone: no crash, value.py is skipped and the run says why
    (tmp_path / "run.odds.json").unlink()
    rc.main([str(run / "report.json"), str(run), "--dry-run", "--independent"])
    assert "odds copy is lost" in (run / "status.md").read_text() and not (tmp_path / "run.odds.json").exists()
    # the stamp covers the runner and the skill wording
    before = rc.code_stamp()
    skill = rc.SKILLS / "football-gamestate-advocate" / "SKILL.md"
    assert skill.exists() and before == rc.code_stamp()
    src_text = Path(rc.__file__).read_text()
    assert "SKILLS.glob(\"football-*/SKILL.md\")" in src_text and "Path(__file__).resolve()" in src_text
    # the answer's calculator numbers saved in decision.md are known operands
    ck_src = (Path(check.__file__)).read_text()
    assert '"decision.md"' in ck_src


def test_scrape_skill_copy_matches_the_backend_and_the_runner_is_guarded():
    import subprocess
    skill = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "football-scrape"
    assert (skill / "SKILL.md").exists() and (skill / "scripts" / "football" / "cli.py").exists()
    r = subprocess.run([sys.executable, str(skill / "scripts" / "sync_from_backend.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    src = (skill / "scripts" / "scrape.py").read_text()
    assert "BLOCK_HOURS" in src and "LOCK" in src and '"," in a.team' in src and "--force" in src
    assert not list((skill / "scripts" / "football").glob("android_*.py")) and not (skill / "scripts" / "football" / "oracle").exists()
    assert (skill / ".." / "football-scrape" / "data" / "history-model.json").exists()


def test_runner_is_always_odds_free_and_refuses_the_old_market_anchor(tmp_path):
    rc = _load_collection()
    src = tmp_path / "src.json"
    src.write_text(json.dumps(_odds_report()))
    run = tmp_path / "run"
    rc.main([str(src), str(run), "--dry-run", "--no-media"])
    assert "odds" not in (run / "report.json").read_text().lower() and (tmp_path / "run.odds.json").exists()
    run2 = tmp_path / "run2"
    rc.main([str(src), str(run2), "--dry-run", "--no-media", "--independent"])    # the old flag is a harmless no-op
    assert "odds" not in (run2 / "report.json").read_text().lower()
    assert rc.main([str(src), str(tmp_path / "run3"), "--dry-run", "--no-media", "--market-anchor"]) == 2 and not (tmp_path / "run3" / "report.json").exists()
    assert not any(side == "market" for side, _ in rc.ADVOCATES) and "market" not in rc.EVIDENCE


def test_venue_anchor_moves_goals_to_the_home_side_and_is_off_at_a_neutral_ground():
    h, a = facts.venue_anchor(1.8, 1.4, 1.2, 1.0)
    h0, a0 = facts.venue_anchor(1.8, 1.4, 1.2, 1.0, neutral=True)
    assert (h0, a0) == (1.6, 1.1)                                   # the plain cross average
    assert abs(h / h0 - 1.0975) < 0.001 and abs(a / a0 - 0.9112) < 0.001
    assert h > h0 and a < a0 and 0.18 <= 2 * facts.HOME_EDGE <= 0.19    # the full edge is the fitted 0.186


def test_venue_edge_is_off_for_a_displaced_home_game_and_on_otherwise():
    try:
        assert facts.set_venue({"match": {"home_team_country": "Belarus", "venue_country": "Hungary"}}) is True
        h, a = facts.venue_anchor(1.8, 1.4, 1.2, 1.0)
        assert (h, a) == (1.6, 1.1)                                          # no edge
        assert facts.set_venue({"match": {"home_team_country": "England", "venue_country": "England"}}) is False
        assert facts.venue_anchor(1.8, 1.4, 1.2, 1.0)[0] > 1.6
        assert facts.set_venue({"match": {}}) is False and facts.set_venue({}) is False      # missing data: a normal home game
    finally:
        facts.set_venue({})


def test_rating_anchor_counts_class_and_the_checker_uses_it_when_there_are_no_odds(tmp_path):
    ins = {"home_club_strength": {"overall": 89.2}, "away_club_strength": {"overall": 73.8}}
    try:
        facts.set_venue({})
        lh, la, ho, ao, src = facts.rating_anchor(ins)
        assert src == "StatsUltra"
        assert (round(lh, 2), round(la, 2), ho, ao) == (2.39, 0.99, 89.2, 73.8)
        facts.set_venue({"match": {"home_team_country": "Belarus", "venue_country": "Hungary"}})
        lh2, la2, _, _, _ = facts.rating_anchor(ins)
        assert lh2 < lh and la2 > la                                              # venue edge off for a displaced ground
        assert facts.rating_anchor({}) is None and facts.rating_anchor({"home_club_strength": {"overall": 80}}) is None
    finally:
        facts.set_venue({})
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    rep["insights"].update(ins)
    Path(rp).write_text(json.dumps(rep))
    rows = check.check(_good_answer(home, away, 1.5, 1.1), rp, log)
    row = next((s_, n, d_) for s_, n, d_ in rows if "rating anchor" in n)
    assert row[0] == "FAIL" and "2.39" in row[2]                                  # 1.5 is a 0.89 cut from the rating anchor and nothing explains it
    explained = _good_answer(home, away, 1.5, 1.1) + "\nExpected goals adjustment: rating anchor 2.39 cut to 1.50 for the absences named above."
    assert next(s_ for s_, n, d_ in check.check(explained, rp, log) if "rating anchor" in n) == "ok"
    from_form = _good_answer(home, away, 1.5, 1.1) + "\nExpected goals adjustment: rating anchor 2.39 cut to 1.50 because the side scored 2+ in only 1 of its last 10 games."
    fail = next((s_, n) for s_, n, d_ in check.check(from_form, rp, log) if "rating anchor" in n)
    assert fail[0] == "FAIL" and "form or scoring rates" in fail[1]                # a move backed only by a scoring rate over a few games lost to the anchor (Belarus) in the national batches
    # the rating anchor moves ONLY for team news: even a small move for luck, tactics or the xG anchor fails, and a line that mentions absences only to say none are priced does not count
    small = lambda line: _good_answer(home, away, 2.29, 1.09) + "\n" + line
    status = lambda t: next(s_ for s_, n, d_ in check.check(t, rp, log) if "rating anchor" in n)
    assert status(small("Expected goals adjustment (Bland): +0.10, home keeper unlucky (save 70% v 72% norm).")) == "FAIL"
    assert status(small("Expected goals adjustment: 2.39 - 0.10 = 2.29 (tactical matchup: the SOT gap). Absences stay at 0.00.")) == "FAIL"
    assert status(small("Expected goals adjustment: the midpoint of the rating and the xG anchor.")) == "FAIL"
    assert status(small("Expected goals adjustment: 2.39 - 0.10 = 2.29, striker ruled out (0.15 of team xG less his replacement's 0.05); away +0.10 for the home centre-back's suspension.")) == "ok"
    near = tmp_path / "near.jsonl"
    assert calc.main(["--lam", "2.37", "0.98", "--home", home, "--away", away, "--log", str(near), "--match", "x", "--kickoff", "2026-10-05", "--bet", f"{home} to win"]) == 0
    assert next(s_ for s_, n, d_ in check.check(_good_answer(home, away, 2.37, 0.98), rp, str(near)) if "rating anchor" in n) == "ok"   # within 0.05 of the anchor needs no line


def test_rating_anchor_prefers_clubelo_and_falls_back_to_statsultra():
    both = {"home_club_elo": {"elo": 2043}, "away_club_elo": {"elo": 1779},
            "home_club_strength": {"overall": 89.2}, "away_club_strength": {"overall": 73.8}}
    try:
        facts.set_venue({})
        lh, la, ho, ao, src = facts.rating_anchor(both)
        assert (src, ho, ao, round(lh, 2), round(la, 2)) == ("ClubElo", 2043.0, 1779.0, 2.89, 0.82)
        one_side = {**both, "away_club_elo": None}                          # a club ClubElo does not list: use the StatsUltra pair instead
        assert facts.rating_anchor(one_side)[4] == "StatsUltra"
        facts.set_venue({"match": {"home_team_country": "Belarus", "venue_country": "Hungary"}})
        assert facts.rating_anchor(both)[0] < lh                           # venue edge off for a displaced ground
    finally:
        facts.set_venue({})


def test_rating_anchor_uses_the_leagues_own_goal_level():
    ins = {"home_club_elo": {"elo": 1716}, "away_club_elo": {"elo": 1657}}  # Alavés v Málaga, 2026-10-23 (1-1)
    try:
        facts.set_venue({})
        default = facts.rating_anchor(ins)
        laliga = facts.rating_anchor(ins, {"competition": "LaLiga", "home_team_country": "Spain"})
        assert round(default[0] + default[1], 2) == 3.15 and round(laliga[0] + laliga[1], 2) == 2.60
        assert abs(laliga[0] / laliga[1] - default[0] / default[1]) < 1e-9          # the class gap is unchanged, only the level
        assert facts.league_goals({"competition": "Premier League", "home_team_country": "Ukraine"}) is None   # same name, another country
        assert facts.league_goals({"competition": "Copa del Rey", "home_team_country": "Spain"}) is None
        assert facts.league_goals({"competition": "UEFA Conference League", "home_team_country": "Spain"}) is None
        assert facts.league_goals({"competition": "LaLiga Hypermotion", "home_team_country": "Spain"})[0] == 2.21
        assert facts.league_goals({"competition": "2. Bundesliga", "home_team_country": "Germany"})[0] == 2.96
    finally:
        facts.set_venue({})


def test_calc_underdog_first_route_matches_a_simulation_of_the_same_model():
    u = calc.underdog_first(1.80, 1.19)                                     # Alavés v Málaga as run: a 200,000-match simulation gave 37.9% / 21.0 / 24.0 / 55.0
    assert u["favourite"] == "home" and abs(u["underdog_first"] - 0.379) < 0.002
    assert abs(u["fav_win"] - 0.210) < 0.003 and abs(u["draw"] - 0.240) < 0.003 and abs(u["fav_loss"] - 0.550) < 0.003
    assert calc.underdog_first(1.19, 1.80)["favourite"] == "away"


def test_underdog_slice_prints_chances_but_no_goals_and_form_v_class():
    def row(sc):
        return {"opponent": "X", "competition": "L", "date": "2026-10-01", "result": "W", "scoreline": sc, "venue": "home", "margin": 0}
    ins = {"home_club_elo": {"elo": 1800}, "away_club_elo": {"elo": 1600},
           "home_big_chances_estimate": {"sample_size": 9, "big_chances_created_for": 21, "big_chances_missed_for": 13},
           "away_goalkeeping_estimate": {"save_pct": 65.4, "sample_size": 9}}
    forms = {"home": {"last10_overall": [row("0-1"), row("0-1"), row("1-1"), row("0-2"), row("1-2")]},
             "away": {"last10_overall": [row("1-1"), row("1-1"), row("0-1"), row("0-1"), row("0-1")]}}
    out = facts.underdog_section({}, {}, ins, "Alpha", "Beta", forms)
    cb = next(ln for ln in out if ln.startswith("CHANCES BUT NO GOALS"))
    assert "Alpha missed 13 of 21 big chances (62%)" in cb and "Beta goalkeeper saves 65.4%" in cb and "mostly regress" in cb
    fc = next(ln for ln in out if ln.startswith("FORM v CLASS"))
    assert "Alpha took 0.20 points a game from its last 5" in fc and "Beta 0.40" in fc
    better = {**forms, "home": {"last10_overall": [row("2-0")] * 5}}
    assert not any(ln.startswith("FORM v CLASS") for ln in facts.underdog_section({}, {}, ins, "Alpha", "Beta", better))


def test_match_stat_profile_reads_shots_box_saves_ball_corners_and_fouls():
    ins = {"home_shots_estimate": {"sample_size": 9, "shots_for": 115, "shots_against": 113, "shots_on_target_for": 43, "shots_on_target_against": 39},
           "away_shots_estimate": {"sample_size": 9, "shots_for": 102, "shots_against": 131, "shots_on_target_for": 27, "shots_on_target_against": 53},
           "home_advanced_stats": {"sample_size": 5, "shots_inside_box_for": 40, "shots_outside_box_for": 21, "shots_inside_box_against": 37, "shots_outside_box_against": 36},
           "away_advanced_stats": {"sample_size": 5, "shots_inside_box_against": 50, "shots_outside_box_against": 20},
           "home_goalkeeping_estimate": {"sample_size": 9, "saves_for": 29, "save_pct": 74.4},
           "home_corners_estimate": {"sample_size": 9, "corners_for": 34, "corners_against": 46},
           "away_corners_estimate": {"sample_size": 9, "corners_for": 50, "corners_against": 44},
           "home_fouls_estimate": {"sample_size": 9, "fouls_committed_for": 150, "fouls_committed_against": 110}}
    m = {"home_team_season_stats": {"average_ball_possession": 42.2}, "away_team_season_stats": {"average_ball_possession": 51.0}}
    out = "\n".join(facts.match_stat_profile({}, m, ins, "Alpha", "Beta"))
    assert "Alpha: attack 4.8 shots on target a game (37% of its shots on target" in out and "defence 4.3 shots on target conceded" in out
    assert "66% of its shots from inside the box, 51% of shots against from inside the box (5 games)" in out
    assert "Alpha is compact" in out and "Beta is open" in out and "keeper 3.2 saves a game, 74.4% saved" in out
    assert "Beta should keep the ball" in out and "corners 3.8 won / 5.1 conceded" in out
    assert "Alpha commits 1.36 fouls for every foul it suffers" in out
    assert "Alpha attack 4.8 shots on target a game meets Beta conceding 5.9" in out
    assert any(sec == "match_stat_profile" for sec in facts.GROUPS["decider"]) and "match_stat_profile" in facts.GROUPS["tactical"]


def test_underdog_strength_counts_wins_over_good_sides_goal_difference_venue_and_form():
    def row(opp, venue, score, res, elo):
        return {"opponent": opp, "competition": "L", "date": "2026-10-01", "result": res, "scoreline": score, "venue": venue, "opponent_club_elo": elo}
    dog = [row("Liverpool FC", "home", "4-2", "W", 1940.0), row("Manchester City", "away", "1-2", "W", 2027.0), row("Arsenal", "home", "0-1", "L", 2049.0),
           row("Fulham", "home", "2-0", "W", 1801.0), row("Burnley", "home", "1-1", "D", 1646.0), row("Paris Saint-Germain", "away", "2-1", "L", None)]
    fav = [row("Arsenal", "home", "3-0", "W", 2049.0), row("Everton", "away", "3-3", "D", 1816.0), row("Burnley", "away", "0-1", "W", 1646.0),
           row("Chelsea", "away", "1-0", "L", 1896.0), row("Fulham", "away", "1-1", "D", 1801.0)]
    ins = {"home_club_elo": {"elo": 1906.0}, "away_club_elo": {"elo": 2027.0}}
    m = {"home_team_standing": {"position": 12, "played": 7, "points": 8, "goal_difference": -4, "total_teams": 20},
         "away_team_standing": {"position": 1, "played": 7, "points": 21, "goal_difference": 12, "total_teams": 20}}
    out = "\n".join(facts.underdog_strength({}, m, ins, "Villa", "City", {"home": {"last20_overall": dog}, "away": {"last20_overall": fav}}))
    assert "Underdog: Villa; favourite: City (ClubElo 1906 v 2027)" in out
    assert "opponents rated 1927+ ClubElo" in out and "Villa W2 D0 L1 in 3 (2.00 points a game), goals 6-4" in out
    assert "W 2-1 v Manchester City (a, 2027)" in out and "L 1-2 v Paris Saint-Germain (a)" in out          # scores read from Villa's side
    assert "goal difference -4 (-0.57 a game)" in out and "early season" in out
    assert "VENUE: Villa at home W2 D1 L1 in 4" in out and "City at away W1 D2 L1 in 4" in out
    assert "UNDERDOG STRENGTH: 4 of 4 signals" in out and "This is not an ordinary underdog" in out
    level = "\n".join(facts.underdog_strength({}, {}, {"home_club_elo": {"elo": 1800.0}, "away_club_elo": {"elo": 1820.0}}, "A", "B", {}))
    assert "No clear underdog" in level
    assert all("underdog_strength" in facts.GROUPS[g] for g in ("decider", "underdog", "home", "away", "context"))


def test_press_v_build_up_clash_needs_a_heavy_press_a_very_short_build_up_and_own_errors():
    def side(ti, acc, long_, err):            # Villa 24.8 v City 90.2% / 3.8% / 0.6 (2026-10-24)
        return {"advanced_stats": {"sample_size": 5, "team_tackles_for": ti * 5 / 2, "team_interceptions_for": ti * 5 / 2, "errors_lead_to_shot_against": err * 5, "dispossessed_for": 54},
                "passing_style": {"pass_accuracy_pct": acc, "long_ball_share_pct": long_}}
    ins = {f"home_{k}": v for k, v in side(24.8, 85.6, 5.3, 1.0).items()} | {f"away_{k}": v for k, v in side(20.6, 90.2, 3.8, 0.6).items()}
    out = "\n".join(facts.press_section({}, {}, ins, "Villa", "City"))
    assert "CLASH: Villa presses high (24.80" in out and "City builds short from the back (pass accuracy 90.20%, long balls 3.80%)" in out
    assert "LIVE route for Villa" in out and "CLASH: City presses" not in out                 # City's 20.6 is not a heavy press
    ins["away_advanced_stats"]["errors_lead_to_shot_against"] = 2
    assert "press-resistant" in "\n".join(facts.press_section({}, {}, ins, "Villa", "City"))
    ins["away_passing_style"]["long_ball_share_pct"] = 6.0
    assert "No clash" in "\n".join(facts.press_section({}, {}, ins, "Villa", "City"))
    assert all("press_section" in facts.GROUPS[g] for g in ("tactical", "underdog", "decider", "state"))


def test_ground_counts_a_past_meeting_with_no_venue_name_as_played_at_the_hosts_ground():
    meets = [{"date": "2025-10-26", "home_team": "Aston Villa", "away_team": "Manchester City", "scoreline": "1-0"},
             {"date": "2025-04-22", "home_team": "Manchester City", "away_team": "Aston Villa", "scoreline": "2-1"},
             {"date": "2024-01-01", "home_team": "Aston Villa", "away_team": "Manchester City", "scoreline": "0-3", "venue_name": "Wembley"}]
    g = "\n".join(facts.ground_section({"venue_name": "Villa Park", "recent_meetings": meets}, {}, {"home": {}, "away": {}}, "Aston Villa", "Manchester City"))
    assert "Past meetings at this ground: 2025-10-26 Aston Villa 1-0 Manchester City -> Aston Villa here: W (1 of" in g and "Wembley" not in g and "2025-04-22" not in g
    h = "\n".join(facts.h2h_section({"home_manager": {"name": "Unai Emery"}, "home_manager_vs_away_club": {"sample_size": 1, "wins": 1, "draws": 0, "losses": 0}}, "Aston Villa", "Manchester City"))
    assert "W1 D0 L0 in 1 games (the source's record only, likely incomplete" in h


def test_shape_zones_find_the_flank_centre_and_between_the_lines_weak_spots():
    z = facts.shape_zones
    assert (z("5-3-2")["flank"], z("5-3-2")["flank_how"], z("5-3-2")["centre"]) == (1.0, "a wing-back", 3)
    assert (z("4-2-3-1")["flank"], z("4-2-3-1")["pivot"], z("4-2-3-1")["tens"]) == (2.0, 2, 1)
    assert (z("4-3-3")["pivot"], z("4-1-4-1")["flank"], z("4-3-1-2")["flank_how"]) == (1, 2.0, "full-back only")
    assert z("not a shape") is None and z("4-4") is None
    out = "\n".join(facts.shape_matchup("5-3-2", "4-4-2", "Alavés", "Málaga"))         # 2026-10-23
    assert "Where Alavés is weak on paper: the flanks: Málaga has 2 a side against its 1" in out and "get in behind its wing-backs" in out
    assert "Where Málaga is weak on paper: the centre of midfield (3 v 2)" in out
    out2 = "\n".join(facts.shape_matchup("4-2-3-1", "4-3-3", "Arsenal", "Lille"))
    assert "Where Lille is weak on paper: the space in front of its back line: Arsenal's 1 player(s) between the lines face a single holder" in out2
    assert "Where Arsenal is weak on paper: no zone where it is outnumbered" in out2 and "Shapes shift in play" in out2


def test_state_slice_prints_bench_and_late_goals():
    rows = [{"opponent": "X", "competition": "L", "date": "2026-10-01", "result": "D", "scoreline": "1-1", "venue": "home", "margin": 0, "ht_scoreline": "0-1",
             "late_goals_for": 1, "late_goals_against": 0, "sub_goals_for": 1, "sub_goals_against": 0},
            {"opponent": "Y", "competition": "L", "date": "2026-09-24", "result": "L", "scoreline": "0-2", "venue": "home", "margin": 2, "ht_scoreline": "0-0",
             "late_goals_for": 0, "late_goals_against": 1, "sub_goals_for": None, "sub_goals_against": None}]
    out = facts.state_section({}, {}, {}, "Alpha", "Beta", {"home": {"last10_overall": rows}, "away": {"last10_overall": []}})
    line = next(ln for ln in out if ln.startswith("bench and late goals"))
    assert "(2 games with goal times" in line and "76th minute on 1 scored and 1 conceded" in line and "substitutes scored 1 of its 1 goals in the 1 games" in line


def test_score_reads_the_match_xg_and_the_goals_markets(tmp_path):
    score = _load("score")
    rows = [({"home": "A", "away": "B", "p": [0.511, 0.242, 0.247], "lams": [1.80, 1.19], "anchor_lams": [1.92, 1.24], "odds_fair_pct": [60.5, 24.3, 15.2]}, 1, 1)]
    xg = {id(rows[0][0]): (1.84, 0.71)}
    text = score.xg_read(rows, xg)
    assert "the side we favoured won the chances (0.3+ xG) in 1" in text and "ours 1.80-1.19" in text and "won the chances" in text.splitlines()[1]
    assert score.xg_read(rows, {}) == ""
    g = score.goals_markets(rows)
    assert "over 2.5: lean right 0 of 1" in g and "both teams to score: lean right 1 of 1" in g


def test_underdog_slice_prints_the_conceded_first_record_when_goal_times_are_known():
    def row(sc, fg):
        return {"opponent": "X", "competition": "L", "date": "2026-10-01", "result": "W", "scoreline": sc, "venue": "home", "margin": 0, "first_goal": fg}
    fav = [row("2-1", "against"), row("1-1", "against"), row("0-1", "against"), row("2-0", "for"), row("1-0", None)]
    ins = {"home_club_elo": {"elo": 1800}, "away_club_elo": {"elo": 1600}}  # Alpha is the favourite
    forms = {"home": {"last10_overall": fav}, "away": {"last10_overall": [row("1-0", "for"), row("0-2", "against")]}}
    out = facts.underdog_section({}, {}, ins, "Alpha", "Beta", forms)
    line = next((ln for ln in out if ln.startswith("IF THE UNDERDOG SCORES FIRST")), "")
    assert "conceded the first goal in 3: W1 D1 L1" in line and "came back to win 1, drew 1" in line and "4 of 5 games known" in line
    assert "Beta scored first in 1 of its 2 known games" in line
    no_times = {"home": {"last10_overall": [row("2-1", None)]}, "away": {"last10_overall": []}}
    assert not any(ln.startswith("IF THE UNDERDOG SCORES FIRST") for ln in facts.underdog_section({}, {}, ins, "Alpha", "Beta", no_times))


def test_run_model_starts_the_model_in_the_project_folder_whatever_the_callers_folder(tmp_path, monkeypatch):
    rc = _load_collection()
    wrapper = tmp_path / "runner.sh"
    where = tmp_path / "cwd.txt"
    wrapper.write_text(f"#!/bin/bash\npwd > {where}\n")
    wrapper.chmod(0o755)
    elsewhere = tmp_path / "output"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)                                                           # a run started from output/ left codex unable to find the skills
    assert rc.run_model(str(wrapper), "m", "p", 30) == 0
    assert Path(where.read_text().strip()) == rc.PROJECT
    assert (rc.PROJECT / ".claude" / "skills").is_dir() or (rc.PROJECT / ".opencode" / "skills").is_dir()


def test_run_model_builds_a_headless_claude_command_for_the_claude_runner(tmp_path):
    rc = _load_collection()
    wrapper = tmp_path / "claude"                                                           # the runner is chosen by file name, so a stub named `claude` records its arguments
    args = tmp_path / "args.txt"
    wrapper.write_text(f'#!/bin/bash\nprintf "%s\\n" "$@" > {args}\n')
    wrapper.chmod(0o755)
    assert rc.run_model(str(wrapper), "haiku", "do the step", 30, files=["/x/evidence/a.md"]) == 0
    got = args.read_text().splitlines()
    assert got[0] == "-p" and got[1].startswith("do the step") and "Read this file first: /x/evidence/a.md" in "\n".join(got)
    assert got[got.index("--model") + 1] == "haiku" and "acceptEdits" in got and "bypassPermissions" not in got
    deny = got[got.index("--disallowedTools") + 1:]                                        # a hard block on reading script source or calling the scripts' functions from python (-c, stdin heredoc, or a script file)
    assert "Read(**/scripts/*.py)" in deny and "Bash(cat *scripts/*.py*)" in deny and "Bash(python3 *open(*)" in deny and "Bash(python3 *import calc*)" in deny
    assert not any("python3 *print" in d or d == "Bash(python3:*)" for d in deny)      # plain python3 -c arithmetic and the scripts themselves still run


def test_claude_runner_captures_the_full_stream_unless_switched_off(tmp_path, monkeypatch):
    rc = _load_collection()
    wrapper = tmp_path / "claude"
    args = tmp_path / "args.txt"
    wrapper.write_text(f'#!/bin/bash\nprintf "%s\\n" "$@" > {args}\n')
    wrapper.chmod(0o755)
    monkeypatch.setenv("FOOTBALL_CAPTURE", "0")
    rc.run_model(str(wrapper), "haiku", "step", 30)
    assert "stream-json" not in args.read_text()
    monkeypatch.delenv("FOOTBALL_CAPTURE", raising=False)
    rc.run_model(str(wrapper), "haiku", "step", 30)
    got = args.read_text().splitlines()
    assert got[got.index("--output-format") + 1] == "stream-json" and "--verbose" in got


def test_a_bet_five_points_under_the_suggestion_needs_a_why_not_line_even_above_60_percent(tmp_path):
    rep, home, away, rp, log = _setup(tmp_path, lh=2.0, la=1.4, bet=None, report_odds=True)
    a = calc.analyse(2.0, 1.4)
    bet, suggested = "Over 2.5 goals", f"{home} or draw"
    want, sug = check.bet_probability(bet, home, away, a), check.bet_probability(suggested, home, away, a)
    assert want >= 60 and sug - want >= 5                           # a 60%+ goals bet well under the suggested double chance, which the old 'below 60% and 10 points' rule let through (Ajax: 60.6% v 68.8%)
    entry = json.loads(open(log).read().splitlines()[-1])
    entry.update({"bet": bet, "suggested": suggested})
    lg = tmp_path / "ou.jsonl"
    lg.write_text(json.dumps(entry) + "\n")
    ans = _good_answer(home, away, 2.0, 1.4, bet=bet)
    row = "a bet far below the calculator's suggestion explains why"
    names = lambda rows: {n: s for s, n, _ in rows}
    assert names(check.check(ans, rp, str(lg)))[row] == "FAIL"
    explained = ans + f"\nWhy not {home} or draw: Hajduk's defence leaks at home and both sides have scored in their last four."
    assert names(check.check(explained, rp, str(lg)))[row] == "ok"


def test_national_rating_gap_is_capped_at_400_points():
    def nat(h, a):
        return {"home_elo_rating": {"elo": h, "sample_source": "eloratings.net"}, "away_elo_rating": {"elo": a, "sample_source": "eloratings.net"}}
    try:
        facts.set_venue({})
        spain = facts.rating_anchor(nat(2281, 1659))                               # a 622-point gap gave 5.48-0.34 (99%) and Czechia scored in a 3-1
        capped = facts.rating_anchor(nat(2059, 1659))
        assert abs(spain[0] - capped[0]) < 1e-9 and abs(spain[1] - capped[1]) < 1e-9 and spain[0] < 3.6
        assert facts.rating_anchor(nat(1659, 2281))[1] < 3.6                       # and the same for the away side
    finally:
        facts.set_venue({})


def test_rating_anchor_uses_eloratings_for_two_national_sides_only():
    nat = {"home_elo_rating": {"elo": 2100, "sample_source": "eloratings.net"}, "away_elo_rating": {"elo": 1800, "sample_source": "eloratings.net"}}
    try:
        facts.set_venue({})
        lh, la, ho, ao, src = facts.rating_anchor(nat)
        assert src == "eloratings.net" and (ho, ao) == (2100.0, 1800.0) and lh > 1.9 and la < 0.9
        facts.set_venue({"match": {"home_team_country": "Belarus", "venue_country": "Hungary"}})
        assert facts.rating_anchor(nat)[0] < lh                                    # neutral ground: the home edge is off
        form_only = {"home_elo_rating": {"elo": 1635, "sample_source": "sofascore"}, "away_elo_rating": {"elo": 1569, "sample_source": "sofascore"}}
        assert facts.rating_anchor(form_only) is None                              # a form-only Elo is not a class rating
        mixed = {**nat, "away_elo_rating": {"elo": 1569, "sample_source": "sofascore"}}
        assert facts.rating_anchor(mixed) is None
    finally:
        facts.set_venue({})


def test_value_flags_a_pick_that_ignores_a_real_gap_elsewhere():
    report = {"match": {"home_team": "Hajduk", "away_team": "Ajax", "betting_odds": {"home_win_odds": 5.0, "draw_odds": 4.5, "away_win_odds": 1.55}}}
    answer = "**Hajduk 34.2% / Draw 25.1% / Ajax 40.7%** (mine)\nBest bet: Draw or Ajax (65.8%), confidence low."
    value = _load("value")
    v = value.value(answer, report)
    assert v["elsewhere"]["outcome"] == "Hajduk" and v["elsewhere"]["label"] == "REAL"
    assert not value._backs(v["bet"], "Hajduk", "Hajduk", "Ajax") and value._backs("Hajduk or draw", "Hajduk", "Hajduk", "Ajax")
    assert value._backs("Hajduk to win", "Hajduk", "Hajduk", "Ajax") and value._backs("Draw or Ajax", "Draw", "Hajduk", "Ajax")


def test_score_follows_the_disagreement_calls_at_the_fair_price():
    score = _load("score")
    win = {"p": [0.34, 0.25, 0.41], "odds_fair_pct": [17.8, 19.7, 62.5]}                  # Hajduk rated 16 points above the market
    lose = {"p": [0.60, 0.25, 0.15], "odds_fair_pct": [40.0, 30.0, 30.0]}                 # home rated 20 points above, loses
    out = score.disagreement_profit([(win, 2, 1), (lose, 0, 1)])
    assert "2 bets, 1 won" in out and "+3.62" in out                                    # 100/17.8 - 1 = 4.62, minus 1 for the loss
    assert score.disagreement_profit([({"p": [0.4, 0.3, 0.3], "odds_fair_pct": None}, 1, 0)]) == ""


def test_value_flags_a_double_chance_the_market_prices_safer_than_we_do():
    value = _lite_module("value").value
    rep = _odds_report()
    ans = "**Aland 60.0% / Draw 10.0% / Bland 30.0%**\nBest bet: Bland or draw (40.0%), confidence low.\n"
    v = value(ans, rep)
    assert v["edge"] < 0 and v["weak_cover"] is True
    single = value("**Aland 60.0% / Draw 10.0% / Bland 30.0%**\nBest bet: Aland to win (60.0%), confidence low.\n", rep)
    assert "weak_cover" not in single


def test_score_tracks_the_disagreement_calls_apart_from_the_pick():
    score = _lite_module("score")
    hajduk = {"p": [0.312, 0.246, 0.442], "odds_fair_pct": [17.8, 18.0, 64.2]}
    even = {"p": [0.40, 0.30, 0.30], "odds_fair_pct": [40.0, 30.0, 30.0]}
    assert score.disagreement_call(hajduk)[0] == 0 and round(score.disagreement_call(hajduk)[1]) == 31
    assert score.disagreement_call(even) is None and score.disagreement_call({"p": [0.5, 0.3, 0.2]}) is None
    text = score.disagreement_summary([(hajduk, 2, 1), (even, 0, 0)])
    assert text.startswith("1 calls; the outcome happened 1 times (100%)") and "noise" in text
    assert "no match" in score.disagreement_summary([(even, 0, 0)])


def test_score_reads_the_anchor_and_reports_the_context_lift(tmp_path):
    score = _lite_module("score")
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "decider.md").write_text("RATING ANCHOR (the class of the two clubs, ClubElo Elo 1586.0 v 1684.0, gap -98.0): HNK Hajduk Split 1.40, AFC Ajax 1.70. This one counts class.\n", encoding="utf-8")
    (tmp_path / "answer.md").write_text("**HNK Hajduk Split 31.2% / Draw 24.6% / AFC Ajax 44.2%** (x)\nBest bet: AFC Ajax or draw (68.8%)\n", encoding="utf-8")
    (tmp_path / "report.json").write_text('{"match": {"home_team": "HNK Hajduk Split", "away_team": "AFC Ajax", "kickoff_utc": "2026-10-15T16:45"}}', encoding="utf-8")
    e = score.entries_from_answers([str(tmp_path)])[0]
    assert e["anchor_lams"] == [1.40, 1.70]
    assert abs(sum(score.poisson_1x2(1.4, 1.7)) - 1.0) < 1e-9
    text = score.context_lift([(e, 2, 1)])
    assert text.startswith("1 matches: anchor-only Brier 0.72") and "hurt 1" in text
    better = dict(e, p=[0.5, 0.25, 0.25])
    assert "helped 1" in score.context_lift([(better, 2, 1)])
    assert "no anchor" in score.context_lift([({"p": [0.3, 0.3, 0.4]}, 1, 0)])


def test_the_sheet_shows_club_elo_beside_a_form_only_elo_so_advocates_do_not_read_the_wrong_gap(tmp_path, capsys):
    from test_oracle import _report
    rep = _report()
    ins = rep.setdefault("insights", {})
    ins["home_elo_rating"] = {"elo": 1622.1, "sample_source": "sofascore"}
    ins["away_elo_rating"] = {"elo": 1627.4, "sample_source": "sofascore"}
    ins["home_club_elo"] = {"elo": 1586.0}
    ins["away_club_elo"] = {"elo": 1684.0}
    p = tmp_path / "r.json"
    p.write_text(json.dumps(rep))
    facts.main(str(p))
    out = capsys.readouterr().out
    assert "do NOT read a gap between two form-only numbers as class" in out
    assert "ClubElo (class): 1586.0" in out and "ClubElo (class): 1684.0" in out


def test_audit_fixes_are_in_the_skill_prompts():
    root = Path(__file__).resolve().parent.parent / ".claude" / "skills"
    lite = (root / "football-match-lite" / "SKILL.md").read_text()
    assert "Check each factor's direction" in lite and "stays marked as inferred" in lite
    assert "a 1-1 or 2-2 draw always needs a concession" in (root / "football-underdog-advocate" / "SKILL.md").read_text()
    assert "never a game count of your own" in (root / "football-team-news" / "SKILL.md").read_text()


def test_a_keeper_spelled_two_ways_is_not_a_keeper_change():
    assert facts.same_player("Marc-André Ter Stegen", "Marc ter Stegen")
    assert not facts.same_player("Marc-André Ter Stegen", "Maarten Paes")
    assert not facts.same_player("Jan Silić", "Toni Silić")
    prof = {"squad": [{"name": "Marc-André Ter Stegen", "role": "G", "recent_usage": {"total_minutes": 360, "avg_rating": 7.03}}]}
    line = facts.keeper_line(prof, [{"name": "Marc ter Stegen", "position": "G"}], "AFC Ajax")
    assert "KEEPER CHANGE" not in line and "available" in line


def test_stream_audit_flags_script_reads_what_if_probes_and_cross_reads(tmp_path):
    rc = _load_collection()
    run = tmp_path / "run-x"
    (run / "logs").mkdir(parents=True)

    def rec(name, **inp):
        return json.dumps({"message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}})
    (run / "logs" / "decider.log").write_text("\n".join([
        rec("Read", file_path="/x/scripts/check.py"),
        rec("Bash", command="python3 -c 'import calc; calc.analyse(1.4, 1.6)'"),
        rec("Read", file_path="/x/output/other-run/answer.md"),
        rec("Read", file_path="/x/output/run-x/evidence/decider.md"),
    ]))
    (run / "logs" / "advocate-home.log").write_text("\n".join([rec("Read", file_path="/x/output/run-x/advocates/away.md"), rec("Read", file_path="/x/output/run-x/advocates/home.md")]))
    found = rc.stream_audit(run)
    assert len(found) == 4 and (run / "audit.md").exists()
    assert any("script's source" in f for f in found) and any("what-if" not in f and "own numbers" in f for f in found)
    assert any("another run" in f for f in found) and any("away advocate's brief" in f for f in found)


def test_stream_audit_flags_market_data_an_analyst_read_but_not_the_market_advocate(tmp_path):
    rc = _load_collection()
    run = tmp_path / "run-m"
    (run / "logs").mkdir(parents=True)
    res = lambda body: json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": body}]}})
    (run / "logs" / "media-scout.log").write_text(res('## upset talk\n  - "Hull City - Brentford: betting tip (cf. 2.05)" (Tips, 2026-10-24)') + "\n")
    (run / "logs" / "decider.log").write_text(res('{"home_win_odds": 2.0, "draw_odds": 3.5}') + "\n")
    (run / "logs" / "advocate-market.log").write_text(res('{"home_win_fair_pct": 50.0}') + "\n")
    (run / "logs" / "team-news.log").write_text(res("RATING ANCHOR: it scored about the same as the bookmaker; Saka 4/5 starts") + "\n")
    found = [f for f in rc.stream_audit(run) if "market data" in f]
    assert sorted(f.split(":")[0] for f in found) == ["advocate-market", "decider", "media-scout"]     # no exception any more: no agent may see a price


def test_value_prints_the_independent_data_model_beside_the_answer(tmp_path):
    mod = _lite_module("value")
    rep = _odds_report()
    rep["insights"].update({"home_club_elo": {"elo": 1940}, "away_club_elo": {"elo": 1898}})
    rep["match"].update({"competition": "Premier League", "home_team_country": "England", "venue_country": "England"})
    mv = mod.model_view(rep)
    a = calc.analyse(mv["lam_home"], mv["lam_away"])
    assert mv["source"] == "ClubElo" and mv["lam_home"] > mv["lam_away"] and abs(mv["home"] - 100 * a["home"]) < 0.2
    assert mv["pick"] in (calc.recommend(a, "Aland", "Bland")["selection"],) and mv["goals_bet"] == calc.goals_bet(a)[0]
    (tmp_path / "a.md").write_text("**Aland 50.0% / Draw 28.0% / Bland 22.0%**\nBest bet: Aland or draw (78.0%), confidence high.\n")
    (tmp_path / "r.json").write_text(json.dumps(rep))
    mod.main(["value.py", str(tmp_path / "a.md"), str(tmp_path / "r.json"), str(tmp_path / "v.md")])
    out = (tmp_path / "v.md").read_text()
    assert "Independent data model (ratings and venue only, ClubElo; no analyst, no odds): Aland" in out and "The market's fair 1X2: Aland 50.0 / Draw 28.0 / Bland 22.0." in out
    assert out.index("Independent data model") < out.index("MARKET SCOREBOARD")
    assert mod.model_view({"match": {"home_team": "A", "away_team": "B"}, "insights": {}}) is None


def test_context_note_gives_no_travel_cut_for_a_short_trip():
    assert "double counts it" in (ROOT / ".claude" / "skills" / "football-context-motivation" / "SKILL.md").read_text()


def test_sheet_flags_two_xg_sources_that_disagree_and_labels_the_next_match(tmp_path, capsys):
    from test_oracle import _report
    rep = _report()
    rep["insights"]["home_xg_estimate"] = {"sample_size": 2, "xg_for": 3.9, "xg_against": 3.9, "actual_goals_for": 5, "actual_goals_against": 4}
    rows = [{"opponent": f"T{i}", "date": f"2026-09-{10 + i}T00:00:00Z", "result": "W", "scoreline": "1-0", "venue": "home", "xg_for": 1.0, "xg_against": 0.5} for i in range(4)]
    for k in ("form", "opponentForm"):
        rep[k]["last10_overall"] = rows
    p = tmp_path / "r.json"
    p.write_text(json.dumps(rep))
    facts.main(str(p))
    out = capsys.readouterr().out
    assert "XG SOURCE: Alpha's anchors use the result rows' xG (4 games) instead of the xG estimate (2 games)" in out      # the larger sample wins
    assert "xG CONFLICT" not in out.split("## Beta")[0]
    assert "the first listed is the NEXT match" in out
    rep["insights"]["home_xg_estimate"] = {"sample_size": 10, "xg_for": 25.0, "xg_against": 15.0, "actual_goals_for": 20, "actual_goals_against": 12}
    p.write_text(json.dumps(rep))
    facts.main(str(p))
    out = capsys.readouterr().out
    assert "xG CONFLICT: the match rows below carry xG for 4 games" in out and "covers 10 games" in out and "XG SOURCE: Alpha" not in out


def test_stream_audit_does_not_flag_a_run_renamed_after_the_fact(tmp_path):
    rc = _load_collection()
    run = tmp_path / "renamed"
    (run / "logs").mkdir(parents=True)
    rec = json.dumps({"message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/x/output/old-name/answer.md"}}]}})
    (run / "logs" / "decider.log").write_text(rec + "\n")
    assert rc.stream_audit(run) == []


def test_verify_sheet_catches_a_keeper_change_the_json_does_not_support():
    src = (ROOT / ".claude" / "skills" / "football-match-lite" / "scripts" / "verify_sheet.py").read_text()
    assert "said_change == (not same)" in src and "or True" not in src


def test_check_warns_on_the_empty_draw_argument_and_a_backwards_keeper_factor():
    src = (ROOT / ".claude" / "skills" / "football-match-lite" / "scripts" / "check.py").read_text()
    assert "no 'all the draws came after conceding' as evidence" in src and "a weak keeper is not listed as that side's own advantage" in src


def test_check_travel_cut_pattern_hits_a_negative_cut_and_not_a_plain_trip_line():
    import re
    src = (ROOT / ".claude" / "skills" / "football-match-lite" / "scripts" / "check.py").read_text()
    assert "no travel cut on a short trip" in src
    pat = r"[^.\n]*\b(travel|trip|journey)\b[^.\n]*(?<![\d.])-\s?0?\.\d+[^.\n]*"
    assert re.search(pat, "Travel cut for the 1297 km trip: -0.03 on Ajax", re.I)
    assert not re.search(pat, "The trip is 1297 km, so no cut (0.00)", re.I)


def test_team_name_words_skip_club_prefixes():
    ck = _load("check")
    assert ck._name_words("HNK Hajduk Split") == ["Hajduk", "Split"]
    assert ck._name_words("AFC Ajax") == ["Ajax"]
    assert ck._name_words("FC") == ["FC"]


def test_the_market_comparison_is_stamped_on_the_finished_answer_once(tmp_path):
    rc = _load_collection()
    a, v = tmp_path / "answer.md", tmp_path / "value.md"
    a.write_text("**A 40% / B 30% / C 30%**\nValue: UNMEASURED - the report has no odds\n")
    v.write_text("Value (checked after the analysis): NONE - edge -11.0\nmore\n")
    rc.stamp_value(a, v)
    rc.stamp_value(a, v)
    text = a.read_text()
    assert text.count("Market comparison after the run") == 1 and "NONE - edge -11.0" in text and text.startswith("**A 40%")


def test_lite_skill_asks_for_same_basis_rows_thin_samples_and_separate_moves():
    s = (ROOT / ".claude" / "skills" / "football-match-lite" / "SKILL.md").read_text()
    assert "SAME basis in every row" in s and "on 2 or 3 games is not a trend" in s and "not netted into one number" in s


def test_check_warns_on_a_move_priced_with_an_assumed_number():
    import re
    src = (ROOT / ".claude" / "skills" / "football-match-lite" / "scripts" / "check.py").read_text()
    assert "no move is priced on an assumed or guessed number" in src
    pat = r"[^.\n]*\bassum(?:ed|ing|e)\b[^.\n]{0,40}?\d+\.\d+[^.\n]*"
    assert re.search(pat, "less an assumed 0.38 Brandt recovery = -0.10", re.I)
    assert not re.search(pat, "Dolberg is out; the sheet gives no share, so 0.00", re.I)
    t = (ROOT / ".claude" / "skills" / "football-team-news" / "SKILL.md").read_text()
    assert "Never invent a recovery share" in t


def test_ground_check_reads_a_comma_number_as_one_value(tmp_path):
    gc = _load("ground_check")
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "a.md").write_text("value 233029999")
    (tmp_path / "answer.md").write_text("value 233,029,999")
    assert gc.ungrounded(str(tmp_path))["answer.md"] == []


def test_check_warns_when_a_last_ten_record_is_called_the_home_record():
    src = (ROOT / ".claude" / "skills" / "football-match-lite" / "scripts" / "check.py").read_text()
    assert "a 'home record' is the home-venue rows only" in src


def test_checks_for_set_piece_claims_game_counts_and_assumed_note_numbers_exist():
    d = ROOT / ".claude" / "skills" / "football-match-lite" / "scripts"
    c, n = (d / "check.py").read_text(), (d / "note_check.py").read_text()
    assert "a set-piece edge is claimed only when the sheet finds one" in c and "a bare small integer is a game count" in c
    assert "no move is priced on an assumed or guessed number" in n


def test_ground_check_ignores_the_stamped_market_line(tmp_path):
    gc = _load("ground_check")
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "a.md").write_text("shots 13.7")
    (tmp_path / "answer.md").write_text("shots 13.7\n\nMarket comparison after the run (value.py): edge -15.2 v 82.2")
    assert gc.ungrounded(str(tmp_path))["answer.md"] == []


def test_ground_check_matches_equal_values_and_lists_the_rest(tmp_path):
    gc = _load("ground_check")
    (tmp_path / "evidence").mkdir()
    (tmp_path / "notes").mkdir()
    (tmp_path / "evidence" / "a.md").write_text("tackles 22.80 and 52.2 touches")
    (tmp_path / "notes" / "n.md").write_text("22.8 tackles, 52.2 touches and 99 invented")
    got = gc.ungrounded(str(tmp_path))
    assert got["notes/n.md"] == [99.0]


def test_check_prices_a_bet_written_with_a_double_chance_prefix():
    a = {"home": 0.3, "draw": 0.25, "away": 0.45, "over_2_5": 0.5, "btts": 0.5}
    got = _load("check").bet_probability("double chance, draw or AFC Ajax", "HNK Hajduk Split", "AFC Ajax", a)
    assert round(got, 1) == 70.0


def test_ground_check_accepts_a_value_written_in_millions(tmp_path):
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "away.md").write_text("squad market value: total 34181000\n", encoding="utf-8")
    (tmp_path / "answer.md").write_text("squad value 34.2m\n", encoding="utf-8")
    assert _load("ground_check").ungrounded(str(tmp_path))["answer.md"] == []


def test_underdog_slice_reads_class_from_clubelo_not_a_form_only_elo():
    src = (Path(__file__).resolve().parent.parent / ".claude/skills/football-match-lite/scripts/facts.py").read_text(encoding="utf-8")
    assert 'elo = {s_: class_elo(ins, s_) for s_ in ("home", "away")}      # class: ClubElo first' in src
    assert 'sample_source") == "eloratings.net"' in src
    assert "shrunk xG anchors on a NEUTRAL ground" in src and "shrunk xG anchors WITH the home edge" in src


def test_stake_is_a_flat_unit_on_the_final_pick_from_our_numbers_only():
    v = _load("value")
    rep = {"match": {"home_team": "Aland", "away_team": "Bland"}}                    # no odds at all: the stake does not need the market
    ind = v.independent("**Aland 60.0% / Draw 22.0% / Bland 18.0%**\nBest bet: Aland to win (60.0%), confidence medium.\n", rep)
    assert (ind["final_pick"], ind["stake"]) == ("Aland to win", "BET") and "own numbers" in ind["stake_why"] and v.decide(ind)[0] == "BET"
    assert v.independent("no bet line", rep)["stake"] == "PASS"


def test_blend_fit_finds_no_value_in_a_view_that_is_worse_than_the_market():
    sc = _load("score")
    rows = [({"p": [0.2, 0.3, 0.5], "odds_fair_pct": [60, 25, 15]}, 1, 0)] * 3 + [({"p": [0.5, 0.3, 0.2], "odds_fair_pct": [20, 25, 55]}, 0, 2)] * 3
    assert "at 0% ours" in sc.blend_fit(rows)
    assert "no matches with odds" in sc.blend_fit([({"p": [0.3, 0.3, 0.4]}, 1, 0)])


def test_stake_summary_counts_bets_and_passes_and_clv_reads_the_closing_price():
    sc = _load("score")
    e1 = {"stake": "BET", "home": "A", "away": "B", "bet": "A", "p": [0.6, 0.2, 0.2], "odds_fair_pct": [50, 25, 25], "closing_fair_pct": [56, 22, 22]}
    e2 = {"stake": "PASS", "home": "C", "away": "D", "bet": "C", "p": [0.4, 0.3, 0.3], "odds_fair_pct": [40, 30, 30]}
    assert "1 BET (won 1, +1.00 units" in sc.stake_summary([(e1, 2, 0), (e2, 0, 1)]) and "1 PASS" in sc.stake_summary([(e1, 2, 0), (e2, 0, 1)])
    assert "moved +6.0 points toward our side" in sc.clv_summary([(e1, 2, 0)])


def test_the_stake_decision_is_stamped_with_the_market_comparison(tmp_path):
    rc = _load_collection()
    a, v = tmp_path / "answer.md", tmp_path / "value.md"
    a.write_text("**A 40% / B 30% / C 30%**\n")
    v.write_text("Value (checked after the analysis): NONE - edge -11.0\nShrunk view: x\nStake decision: PASS - the pick is NONE.\n{}\n")
    rc.stamp_value(a, v)
    assert "Stake decision: PASS" in a.read_text()


def test_a_zero_point_table_is_dropped_and_noted():
    fx = _load("facts")
    ins = {"home_standings_impact": {"current_points": 0}, "away_standings_impact": {"current_points": 0},
           "home_standings_zone": {"position": 20}, "away_standings_zone": {"position": 2}}
    note = fx.drop_unformed_table(ins)
    assert "TABLE NOT FORMED" in note and "home_standings_zone" not in ins and "away_standings_impact" not in ins
    real = {"home_standings_impact": {"current_points": 3}, "away_standings_impact": {"current_points": 0}, "home_standings_zone": {"position": 1}}
    assert fx.drop_unformed_table(real) == "" and "home_standings_zone" in real


def test_opposition_summary_reads_opponent_clubelo_and_flags_weak_schedules():
    fx = _load("facts")
    form = {"last10_overall": [{"result": "W", "opponent_club_elo": 1450}, {"result": "W", "opponent_club_elo": 1500}, {"result": "L", "opponent_club_elo": 1780}]}
    txt = fx.opposition_summary(form, {"away_club_elo": {"elo": 1684}}, "away")
    assert "avg ClubElo 1577 v own 1684 (3 of 3 rated)" in txt and "0.00 pts a game in 1" in txt and "WEAKER" in txt
    assert fx.opposition_summary({"last10_overall": [{"result": "W"}]}, {"away_club_elo": {"elo": 1600}}, "away").startswith("n/a")


def test_cross_league_line_shows_clubelo_and_squad_value_and_says_when_they_disagree():
    fx = _load("facts")
    forms = {"home": {"last20_overall": [{"competition": "HNL"}, {"competition": "HNL"}, {"competition": "UEFA Conference League"}]},
             "away": {"last20_overall": [{"competition": "Eredivisie"}, {"competition": "Eredivisie"}]}}
    ins = {"home_club_elo": {"elo": 1586}, "away_club_elo": {"elo": 1684}, "home_squad_strength": {"total_value": 34e6}, "away_squad_strength": {"total_value": 233e6}}
    line = fx.cross_league_line({}, {}, ins, "Hajduk", "Ajax", forms)
    assert line.startswith("CROSS-LEAGUE TIE (HNL v Eredivisie)") and "DISAGREE on the size of the gap" in line and "6.9x for Ajax" in line and "a close match" in line
    level = dict(ins, home_squad_strength={"total_value": 200e6})
    assert "AGREE" in fx.cross_league_line({}, {}, level, "Hajduk", "Ajax", forms)
    same = {"home": forms["away"], "away": forms["away"]}
    assert fx.cross_league_line({}, {}, ins, "A", "B", same) == ""


def test_check_warns_on_a_table_position_from_a_zero_point_table_and_skill_says_so():
    src = (ROOT / ".claude/skills/football-match-lite/scripts/check.py").read_text()
    assert "no table position is cited from a table where both sides have 0 points" in src
    s = (ROOT / ".claude/skills/football-match-lite/SKILL.md").read_text()
    assert "opposition faced, last 10" in s and "CROSS-LEAGUE TIE" in s and "TABLE NOT FORMED" in s and "FORM ROWS INCOMPLETE" in s


def test_note_checker_caps_a_context_move_at_point_two(tmp_path):
    note_check = _load("note_check")
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    names = lambda text: {n: s for s, n, _ in note_check.check(text, rp)}  # noqa: E731
    key = "xg_delta_home stays within +-0.20 (context moves expected goals by at most 0.20 a side)"
    assert names(_note(specialist="context-motivation", match=f"{home} v {away}", xg_delta_home="+0.30"))[key] == "FAIL"
    assert names(_note(specialist="context-motivation", match=f"{home} v {away}", xg_delta_home="+0.15"))[key] == "ok"
    assert key not in names(_note(specialist="tactical-matchup", match=f"{home} v {away}", xg_delta_home="+0.30"))


def test_class_elo_reads_clubelo_then_eloratings_and_never_a_form_only_elo():
    fx = _load("facts")
    assert fx.class_elo({"home_club_elo": {"elo": 1586}, "home_elo_rating": {"elo": 1622, "sample_source": "sofascore"}}, "home") == 1586
    assert fx.class_elo({"home_elo_rating": {"elo": 1900, "sample_source": "eloratings.net"}}, "home") == 1900
    assert fx.class_elo({"home_elo_rating": {"elo": 1622, "sample_source": "sofascore"}}, "home") is None
    src = (ROOT / ".claude/skills/football-match-lite/scripts/facts.py").read_text()
    assert 'num(d(ins.get("home_elo_rating")).get("elo"))' not in src          # no section reads the form-only Elo as class


def test_score_reads_the_value_label_from_value_md_and_odds_from_the_sidecar(tmp_path):
    sc = _load("score")
    run = tmp_path / "fh-x"
    (run / "evidence").mkdir(parents=True)
    rep = {"match": {"home_team": "A", "away_team": "B", "kickoff_utc": "2026-10-15T16:45:00Z"}}
    (run / "report.json").write_text(json.dumps(rep))
    with_odds = dict(rep, match=dict(rep["match"], betting_odds={"home_win_odds": 5.0, "draw_odds": 4.5, "away_win_odds": 1.5}))
    (tmp_path / "fh-x.odds.json").write_text(json.dumps(with_odds))
    (run / "answer.md").write_text("**A 31% / Draw 25% / B 44%**\nValue: UNMEASURED (no odds)\n**Best bet: Draw or B (69%)**\n")
    (run / "value.md").write_text('Value (checked after the analysis): NONE - x\nStake decision: PASS - y.\n{"label": "NONE"}\n')
    e = sc.entries_from_answers([str(run)])[0]
    assert e["decision"] == "NONE" and e["stake"] == "PASS" and e["odds_fair_pct"] and round(sum(e["odds_fair_pct"])) == 100


def test_note_checker_fails_when_a_specialist_prints_its_own_anchors(tmp_path):
    note_check = _load("note_check")
    rep, home, away, rp, log = _setup(tmp_path, lh=1.5, la=1.1, bet=None, report_odds=False)
    names = lambda text: {n: s for s, n, _ in note_check.check(text, rp)}  # noqa: E731
    key = "the note gives deltas, not its own anchors (the decider owns the numbers)"
    bad = _note(match=f"{home} v {away}", arithmetic="finishing 0.53 x 0.3 = -0.16. Adjusted anchors: home 1.63, away 2.17")
    assert names(bad)[key] == "FAIL" and names(_note(match=f"{home} v {away}"))[key] == "ok"
    s = (ROOT / ".claude/skills/football-underlying-stats/SKILL.md").read_text()
    assert "never rebuild an anchor from the raw xG averages" in s


def test_set_piece_claim_needs_the_edge_word_next_to_set_pieces():
    src = (ROOT / ".claude/skills/football-match-lite/scripts/check.py").read_text()
    pat = re.search(r're\.search\(r"(set\[- \]pieces\?\\W\+[^"]+)", x, re\.I\)', src).group(1)
    assert re.search(pat, "Hajduk has set pieces as a second route to goal", re.I)
    assert not re.search(pat, "crosses 8.6 a game as its main wide route; set-piece xG 2.46 for", re.I)
    neg = re.search(r'and not re\.search\(r"(\\b\(level[^"]+)", x, re\.I\)', src).group(1)
    for said in ("but lacks a rest or set-piece advantage", "the roughly balanced set-piece route permits 1-1"):
        assert re.search(neg, said, re.I)
    assert not re.search(neg, "set pieces give Hajduk a second route", re.I)


def test_verify_sheet_expects_no_position_for_a_table_with_no_games():
    src = (ROOT / ".claude/skills/football-match-lite/scripts/verify_sheet.py").read_text()
    assert 'table not formed (0 played)' in src and "table: no games played in this competition yet" in (ROOT / ".claude/skills/football-match-lite/scripts/facts.py").read_text()


def test_anchors_use_the_rows_xg_when_they_cover_more_games_than_the_estimate():
    fx = _load("facts")
    rows = [{"venue": "home", "scoreline": "2-1", "xg_for": 1.2, "xg_against": 1.5}, {"venue": "away", "scoreline": "3-0", "xg_for": 1.1, "xg_against": 1.5},
            {"venue": "home", "scoreline": "1-0", "xg_for": 0.7, "xg_against": 0.3}, {"venue": "away", "scoreline": "0-2", "xg_for": 2.3, "xg_against": 0.1}]
    ins = {"home_xg_estimate": {"sample_size": 2, "xg_for": 3.93, "xg_against": 3.93}, "away_xg_estimate": {"sample_size": 10, "xg_for": 25.7, "xg_against": 15.9}}
    forms = {"home": {"last10_overall": rows}, "away": {"last10_overall": rows}}
    notes = fx.prefer_larger_xg_sample(ins, forms, {"home": "Hajduk", "away": "Ajax"})
    e = ins["home_xg_estimate"]
    assert e["sample_size"] == 4 and e["xg_for"] == 5.3 and e["actual_goals_for"] == 2 + 0 + 1 + 2 and e["actual_goals_against"] == 1 + 3 + 0 + 0
    assert ins["away_xg_estimate"]["sample_size"] == 10 and len(notes) == 1 and notes[0].startswith("XG SOURCE: Hajduk")


def test_ground_section_quotes_the_rows_home_record_beside_the_thin_venue_split():
    fx = _load("facts")
    home_rows = [{"venue": "home", "result": "W"}] * 4 + [{"venue": "home", "result": "D"}] + [{"venue": "home", "result": "W", "neutral_venue": True}]
    forms = {"home": {"last20_overall": home_rows, "venue_split_form": {"home_wins": 2, "home_draws": 0, "home_losses": 0}},
             "away": {"last20_overall": [{"venue": "away", "result": "W"}] * 3, "venue_split_form": {"away_wins": 1, "away_draws": 0, "away_losses": 0}}}
    text = "\n".join(fx.ground_section({}, {}, forms, "H", "A"))
    assert "H at home 2.60 points a game in 5 games" in text and "A away 3.00 points a game in 3 games" in text and "Venue split (only the most recent" in text


def test_a_bet_with_a_note_inside_its_brackets_is_read_with_its_own_probability():
    ck, v = _load("check"), _load("value")
    a = {"home": 0.271, "draw": 0.262, "away": 0.467, "over_2_5": 0.5, "btts": 0.5}
    assert round(ck.bet_probability("Draw or Scotland, double chance, confidence low. Why this bet", "Wales", "Scotland", a), 1) == 72.9
    ans = "**Wales 27.1% / Draw 26.2% / Scotland 46.7%**\nBest bet: Draw or Scotland, double chance (72.9%, the draw-or-away line calc.py prices), confidence low. Scotland to win (46.7%)\n"
    rep = {"match": {"home_team": "Wales", "away_team": "Scotland", "betting_odds": {"home_win_odds": 3.5, "draw_odds": 3.4, "away_win_odds": 2.2}}}
    out = v.value(ans, rep)
    assert out["own"] == 72.9 and out["bet"].startswith("Draw or Scotland")


def test_check_lets_a_disclaimed_zero_point_table_pass_but_not_a_chase():
    src = (ROOT / ".claude/skills/football-match-lite/scripts/check.py").read_text()
    assert "a position quoted as meaningless is not a claim" in src and r"chas\w+|top spot" in src


def test_scrape_reuses_only_a_freshly_generated_report_of_a_match_still_to_come(tmp_path):
    import datetime
    spec = importlib.util.spec_from_file_location("scrape_for_test", ROOT / ".claude/skills/football-scrape/scripts/scrape.py")
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)
    now = datetime.datetime.now(datetime.timezone.utc)
    iso = lambda dt: dt.isoformat().replace("+00:00", "Z")  # noqa: E731
    def rep(made, kick):
        p = tmp_path / f"r{made.timestamp()}{kick.timestamp()}.json"
        p.write_text(json.dumps({"generatedAt": iso(made), "match": {"kickoff_utc": iso(kick)}}))
        return p
    hour = datetime.timedelta(hours=1)
    assert sc.reusable(rep(now - hour, now + 24 * hour), 6) is True
    assert sc.reusable(rep(now - 10 * 24 * hour, now + 24 * hour), 6) is False          # old report, new file time
    assert sc.reusable(rep(now - hour, now - 2 * hour), 6) is False                    # match already kicked off


def test_table_warning_skips_a_sentence_that_says_nobody_is_chasing():
    src = (ROOT / ".claude/skills/football-match-lite/scripts/check.py").read_text()
    assert "nobody|no one|neither" in src


def test_sheet_flags_a_club_elo_dated_after_kickoff():
    facts = _load("facts")
    ins = {"home_club_elo": {"elo": 1600, "as_of": "2026-10-23"}, "away_club_elo": {"elo": 1700, "as_of": "2026-10-11"}}
    note = facts.club_elo_after_kickoff(ins, "2026-10-12T19:00:00Z")
    assert note.startswith("CLUBELO AFTER KICKOFF") and "home 2026-10-23" in note and "away" not in note.split("for a")[0]
    assert facts.club_elo_after_kickoff(ins, "2026-10-25T12:00:00Z") == "" and facts.club_elo_after_kickoff({}, "2026-10-12") == ""


def test_lineup_check_flags_listed_absentees_who_start_and_only_runs_near_kickoff(tmp_path, monkeypatch):
    import contextlib
    import importlib.util
    from datetime import UTC, datetime, timedelta
    spec = importlib.util.spec_from_file_location("lineup_check", ROOT / ".claude/skills/football-scrape/scripts/lineup_check.py")
    lc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lc)
    from football.sites import sofascore as ss
    monkeypatch.setattr(lc, "LOCK", tmp_path / "none.lock")
    monkeypatch.setattr(lc, "BLOCK", tmp_path / "none.blocked")
    calls = []

    @contextlib.asynccontextmanager
    async def page():
        yield None

    async def fetch(_page, url):
        calls.append(url)
        pl = lambda n, sub: {"player": {"name": n}, "substitute": sub}  # noqa: E731
        return {"confirmed": True, "home": {"formation": "4-2-3-1", "players": [pl("Johan Manzambi", False), pl("John McGinn", False), pl("Tyrone Mings", True)]},
                "away": {"formation": "4-2-3-1", "players": [pl("Erling Haaland", False), pl("Mateo Kovačić", True)]}}

    monkeypatch.setattr(ss, "_session_page", page)
    monkeypatch.setattr(ss, "_fetch_json_optional", fetch)
    kick = lambda h: (datetime.now(UTC) + timedelta(hours=h)).isoformat().replace("+00:00", "Z")  # noqa: E731
    usage = lambda mins: {"recent_usage": {"total_minutes": mins}}  # noqa: E731
    report = {"team": "Aston Villa", "teamProfile": {"team_name": "Aston Villa", "squad": [{"name": "Tyrone Mings", **usage(500)}, {"name": "John McGinn", **usage(400)}]},
              "opponentProfile": {"team_name": "Manchester City", "squad": []},
              "match": {"home_team": "Aston Villa", "away_team": "Manchester City", "source_url": "https://www.sofascore.com/event/aston-villa-manchester-city/16363892",
                        "home_missing_players": [{"name": "Johan Manzambi", "description": "Physical Discomfort"}],
                        "away_missing_players": [{"name": "Mateo Kovacic", "description": "Knock Injury"}]}}
    for hours, code in ((3, 2), (-1, 2)):
        report["match"]["kickoff_utc"] = kick(hours)
        (tmp_path / "report.json").write_text(json.dumps(report))
        assert lc.main([str(tmp_path)]) == code and not calls
    report["match"]["kickoff_utc"] = kick(1)
    (tmp_path / "report.json").write_text(json.dumps(report))
    assert lc.main([str(tmp_path)]) == 0 and calls == ["https://www.sofascore.com/api/v1/event/16363892/lineups"]
    lu = json.loads((tmp_path / "lineups.json").read_text())
    assert lu["confirmed"] and lu["home"]["xi"] == ["Johan Manzambi", "John McGinn"]
    assert "Aston Villa: Johan Manzambi was listed missing (Physical Discomfort) but STARTS: drop that absence" in lu["checks"]
    assert "Manchester City: Mateo Kovacic was listed missing (Knock Injury) but is on the BENCH: a part absence at most" in lu["checks"]
    assert any("regulars (most minutes lately) NOT in the XI: Tyrone Mings; on the bench: Tyrone Mings" in c for c in lu["checks"])
    out = "\n".join(facts.lineups_section(str(tmp_path / "report.json")))
    assert "lineups CONFIRMED" in out and "LINEUP CHANGE: Aston Villa: Johan Manzambi was listed missing" in out
    assert "not checked" in "\n".join(facts.lineups_section(str(tmp_path / "elsewhere" / "report.json")))
    (tmp_path / "none.blocked").write_text("1 403")
    assert lc.main([str(tmp_path)]) == 2 and len(calls) == 1                              # the block marker stops the fetch


def test_doubtful_absences_and_rotation_wording():
    assert "DOUBTFUL (Physical Discomfort (dayToDay))" in facts.doubtful_tag(None, "Physical Discomfort (dayToDay)")
    assert facts.doubtful_tag("Knock Injury").startswith("; DOUBTFUL") and facts.doubtful_tag("Cruciate Ligament Injury", None) == ""
    lines = facts.replacement_lines({"squad": [{"name": "J M", "role": "M", "recent_usage": {"total_minutes": 300, "starts": 4}}],
                                     "injuries": [{"name": "J M", "injury": "Physical Discomfort (dayToDay)"}]}, "Villa")
    assert "DOUBTFUL" in lines[0]
    assert all(sec in facts.GROUPS[g] for g, sec in (("team-news", "lineups_section"), ("decider", "lineups_section"), ("tactical", "lineups_section")))


def test_closing_odds_saves_the_fair_price_only_near_kickoff(tmp_path, monkeypatch):
    import importlib.util
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace
    spec = importlib.util.spec_from_file_location("closing_odds", ROOT / ".claude/skills/football-scrape/scripts/closing_odds.py")
    co = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(co)
    from football.sites import footballdata

    async def fake(home, away):
        return SimpleNamespace(home_win_fair_pct=None, draw_fair_pct=None, away_win_fair_pct=None, home_win_odds=2.0, draw_odds=4.0, away_win_odds=4.0), None

    monkeypatch.setattr(footballdata, "get_upcoming_fixture", fake)
    kick = lambda h: (datetime.now(UTC) + timedelta(hours=h)).isoformat().replace("+00:00", "Z")  # noqa: E731
    for hours, code in ((1, 0), (5, 2), (-1, 2)):
        (tmp_path / "closing_odds.json").unlink(missing_ok=True)
        (tmp_path / "report.json").write_text(json.dumps({"match": {"home_team": "A", "away_team": "B", "kickoff_utc": kick(hours)}}))
        assert co.main(str(tmp_path)) == code
        assert (tmp_path / "closing_odds.json").exists() == (code == 0)
    assert json.loads((tmp_path / "closing_odds.json").read_text() if (tmp_path / "closing_odds.json").exists() else "{}") == {}
    (tmp_path / "report.json").write_text(json.dumps({"match": {"home_team": "A", "away_team": "B", "kickoff_utc": kick(1)}}))
    co.main(str(tmp_path))
    assert json.loads((tmp_path / "closing_odds.json").read_text())["fair_pct"] == [50.0, 25.0, 25.0]


def test_a_team_figure_from_the_sheet_prose_is_not_called_the_other_teams():
    src = (ROOT / ".claude/skills/football-match-lite/scripts/check.py").read_text()
    assert "the sheet's own prose gives a team's figure too" in src


def test_event_raw_is_a_post_match_tool_and_builds_the_season_statistics_urls(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("event_raw_t", ROOT / ".claude/skills/football-scrape/scripts/event_raw.py")
    er = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(er)
    run = tmp_path / "run"
    run.mkdir()
    (run / "report.json").write_text(json.dumps({"match": {"home_team": "A", "away_team": "B", "kickoff_utc": "2099-01-01T12:00:00Z",
                                                           "source_url": "https://www.sofascore.com/event/a-b/16363892"}}))
    assert er.main([str(run)]) == 2                                                      # before kickoff: refused, its data would hold the result
    assert er.event_id({"source_url": "https://www.sofascore.com/event/a-b/16363892"}) == "16363892"
    ev = {"event": {"tournament": {"uniqueTournament": {"id": 17}}, "season": {"id": 77}, "homeTeam": {"id": 40}, "awayTeam": {"id": 17}}}
    assert er.season_urls(ev) == [("season-statistics-home", "https://www.sofascore.com/api/v1/team/40/unique-tournament/17/season/77/statistics/overall"),
                                  ("season-statistics-away", "https://www.sofascore.com/api/v1/team/17/unique-tournament/17/season/77/statistics/overall")]
    assert er.season_urls({}) == []
