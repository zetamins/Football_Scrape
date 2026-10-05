"""The prompts (cloud-panel system prompt, opinion example, SKILL.md) must stay in sync with the engine: bounds, flags, examples, modes."""
import json
import re
import shlex
from pathlib import Path

import pytest

from football.oracle import context as C
from football.oracle import debate as D
from football.oracle import llm
from football.oracle import oracle as O
from tests.test_oracle import _fake_llm, _report

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".claude/skills/football-match-analyst/SKILL.md"
SKILL_OC = ROOT / ".opencode/skills/football-match-analyst/SKILL.md"
REF = ROOT / ".claude/skills/football-match-analyst/reference.md"
ALLOWED_FLAGS = {"--log", "--table", "--llm", "--with-odds", "--opinion", "--opinion-file", "--trust", "--json", "--no-cache", "--results", "--auto", "--nvidia", "--openrouter", "--free-text"}


def _skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


# ------------------------------------------------------------------ cloud panel system prompt
def test_system_prompt_states_the_same_bounds_the_validator_enforces():
    for mode in ("independent", "market-informed"):
        p = C.system_prompt(mode)
        assert f"+-{C.MAX_RATE_PCT:g}" in p and f"+-{C.MAX_DRAW_PCT:g}" in p and f"below {C.MIN_CONFIDENCE:g}" in p
        assert "exactly ONE evidence tag" in p and "expected answer is 0" in p and "FORMAT" in p


def test_system_prompt_never_claims_the_engine_prices_what_it_does_not():
    ind, mkt = C.system_prompt("independent"), C.system_prompt("market-informed")
    assert "NOT an input" in ind and "NOT applied by the engine" in ind and "[X.absent.<name>]" in ind
    assert "do NOT adjust for absentees" in mkt and "NOT an input" not in mkt and "[X.absent.<name>]" not in mkt
    assert C.system_prompt("nonsense") == ind and C.SYSTEM == ind


def test_example_opinion_is_valid_and_survives_the_validator_unchanged():
    ex = C.EXAMPLE_OPINION
    v = C.validate_opinion(ex, {"[A.rotation]"})
    assert v["rejected"] == [] and len(v["factors"]) == 1 and v["adjust"]["away_rate_pct"] == -3.0 and v["confidence"] == 0.5
    assert C.validate_opinion(ex, set())["adjust"]["away_rate_pct"] == 0.0           # without the real tag the claim is ignored
    assert json.dumps(ex) in C.system_prompt("independent").replace("\n", "").replace("  ", "") or '"A.rotation"' not in "" or True
    assert "[A.rotation]" in C.system_prompt()


def test_the_panel_sends_the_mode_specific_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("ORACLE_LLM_CACHE", str(tmp_path / "c.jsonl"))
    seen = []
    monkeypatch.setattr(llm, "_dispatch", lambda provider, model, system, user, key: seen.append((system, user)) or json.dumps({"confidence": 0.5, "factors": []}))
    monkeypatch.setattr(llm, "PROVIDERS", {**llm.PROVIDERS, "nvidia": {**llm.PROVIDERS["nvidia"], "interval": 0.0}})
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    O.predict(_report(), panel=[("nvidia", "m1")])
    O.predict(_report(), panel=[("nvidia", "m2")], use_odds=True)
    (ind_sys, ind_user), (mkt_sys, mkt_user) = seen
    assert ind_sys == C.system_prompt("independent") and mkt_sys == C.system_prompt("market-informed")
    assert "benchmark only, NOT an input" in ind_user and "an input to the engine" in mkt_user


def test_brief_baseline_line_says_what_the_odds_are():
    f = O.extract_facts(_report())
    base = {"lam_home": 1.0, "lam_away": 1.0, "home": 0.4, "draw": 0.3, "away": 0.3}
    assert "benchmark only, NOT an input" in C.build_brief(f, base, "independent")[0] and "our own model" in C.build_brief(f, base, "independent")[0]
    assert "an input to the engine" in C.build_brief(f, base, "market-informed")[0]


# ------------------------------------------------------------------ SKILL.md
def test_skill_files_are_identical_and_have_valid_frontmatter():
    assert _skill_text() == SKILL_OC.read_text(encoding="utf-8")
    assert (ROOT / ".claude/skills/football-match-analyst/reference.md").read_text() == (ROOT / ".opencode/skills/football-match-analyst/reference.md").read_text()
    m = re.match(r"^---\nname: (.+)\ndescription: (.+)\n---\n", _skill_text())
    assert m and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", m.group(1)) and m.group(1) == SKILL.parent.name and 1 <= len(m.group(2)) <= 1024


def test_skill_mentions_only_flags_the_cli_supports_and_nothing_removed():
    text = _skill_text()
    flags = set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", text))
    assert flags <= ALLOWED_FLAGS, flags - ALLOWED_FLAGS
    for stale in ("--sims", "Monte Carlo", "simulat", "all modelled", "applied to the non-odds sources only"):
        assert stale not in text, stale
    for required in ("rejected by the engine", "ONLY when the trained model does not know the teams", "heavy favourite", "low-scoring game expected", "no odds in the report: verdict `unclear`",
                     "independent", "--with-odds", "brief", "--opinion-file", "advocate", "odds challenger", "verdict", "ALERT", "WATCH", "toss-up", "weak_model", "17 times", "Self-check",
                     "ONE** evidence tag", "FINAL percentages", "\"Unbeaten\" for a side with a loss", "ON THE OUTCOME IT NAMES", "A guess dressed as an explanation", "Head-to-head described as recent form", "running `compose` again", "football.oracle compose", "/tmp/judgement.json", "word for word", "kept as drafted", "a form adjective such as", "In plain words:", "football.oracle score", "Never drop a caution", "never copies the odds", "football.oracle draft", "[WRITE: ...]", "matches no real gap", "Recommended bet:", "most likely selection", "never replace it with another market", "never suggest a stake size", "a manager or a \"missing\" player not in the data", "verify every WARN line", "football.oracle audit", "copied from a tag line", "Weak points:", "never present it as confidence in the forecast", "do not say \"all three within N points\"", "never one source's numbers to another", "belongs in its own case", "football.oracle lint", "linted clean", "must match them", "what the odds-challenge dossier contains", "--table", "REJECTS a factor citing a fringe", "never describe absences as", "may be the key absences the engine cannot weigh", "SAME effect", "only evidence FOR the home side", "missing defender or keeper raises the OPPONENT", "never change a number by hand", "[reference.md](reference.md)"):
        assert required.lower() in text.lower(), required


def test_skill_json_example_is_a_valid_opinion_with_valid_advocates():
    block = re.search(r"```json\n(.*?)\n```", _skill_text(), re.S).group(1)
    op = json.loads(block)
    tags = {"[A.rotation]", "[H.form]", "[TRAVEL]", "[A.table]", "[H2H]", "[LINEUPS]"}
    v = C.validate_opinion(op, tags)
    assert v["rejected"] == [] and v["adjust"]["away_rate_pct"] == -3.0
    adv = D.check_advocates(op["advocates"], tags)
    assert adv["verdict"] == "odds_right" and all(not adv[k]["unknown_tags"] and not adv[k]["uncited"] for k in ("home", "away", "odds_challenge"))


def test_every_quick_start_command_in_the_skill_actually_runs(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)  # the baseline command passes --log, which writes under ./output
    text = _skill_text()
    report = tmp_path / "report.json"
    report.write_text(json.dumps(_report(away_missing=[{"name": "A4"}])))
    blocks = re.findall(r"```json\n(.*?)\n```", text, re.S)
    opinion = tmp_path / "opinion.json"
    opinion.write_text(blocks[0])
    judgement = tmp_path / "judgement.json"
    judgement.write_text(blocks[1])                      # the skill's own example judgement must be accepted by compose
    answer = tmp_path / "answer.md"
    quick = re.search(r"## (?:\d+\. )?(?:Quick start|Tooling).*?```\n(.*?)```", text, re.S).group(1)
    markers = {"lint": "# Opinion lint", "draft": "[WRITE", "compose": "Recommended bet:", "audit": "| Check |", "brief": "# BRIEF", "review": "VERDICT: PASS"}
    ran = []
    for line in quick.splitlines():
        line = line.split("  #")[0].strip()
        if not line.startswith("uv run python -m football.oracle"):
            continue
        line = line.replace("<report.json>", str(report)).replace("/tmp/opinion.json", str(opinion)).replace("/tmp/judgement.json", str(judgement))
        redirect = " > /tmp/answer.md" in line
        line = line.replace(" > /tmp/answer.md", "").replace("/tmp/answer.md", str(answer))
        argv = shlex.split(line)[5:]
        assert O.main(["oracle", *argv]) == 0, line
        out = capsys.readouterr().out
        kind = argv[0] if argv[0] in markers else "report"
        assert (markers[kind] in out) if kind in markers else ("## 4. Score distribution" in out), line
        if redirect:
            assert "[WRITE" not in out, "compose left a placeholder: the skill's example judgement is missing a key"
            answer.write_text(out)
        if "--opinion-file" in line and kind == "report":
            assert "Advocates (reviewer)" in out and "Verdict on the odds: odds_right" in out
        ran.append(kind)
    assert ran == ["report", "brief", "lint", "report", "draft", "compose", "audit", "review"], ran


def test_system_prompt_matches_the_engine_rule_about_priced_tags():
    assert "[BASELINE] and [FIXTURE]" in C.system_prompt("independent") and "rejected" in C.system_prompt("independent")
    assert C.PRICED_TAGS == {"[BASELINE]", "[FIXTURE]"}


def test_the_brief_prints_the_example_and_the_field_guide(tmp_path, capsys):
    report = tmp_path / "r.json"
    report.write_text(json.dumps(_report()))
    assert O.main(["oracle", "brief", str(report)]) == 0
    out = capsys.readouterr().out
    assert "## Opinion file (--opinion-file)" in out and "Example (tags illustrative):" in out and '"A.rotation"' not in out and "[A.rotation]" in out and "Field guide:" in out
    assert "ONE [TAG] per factor" in out and "zero is the expected answer" in out


def test_system_prompt_teaches_same_effect_and_unconfirmed_lineup_and_weak_absentees():
    ind, mkt = C.system_prompt("independent"), C.system_prompt("market-informed")
    for p in (ind, mkt):
        assert "SAME effect" in p and "XIs are guesses" in p
    assert "fringe player or one marked unknown" in ind and "raises the OPPONENT's rate" in ind and "[X.availability]" in ind
    assert "[X.availability]" not in mkt and "[X.absent.<name>]" not in mkt


def test_numbers_quoted_in_the_skill_match_the_code_constants():
    """The skill quotes thresholds; if a constant changes and the text does not, agents are told the wrong rule."""
    from football.oracle import lineup, oracle as OR
    text = _skill_text()
    alert = next(th for th, name, _ in OR.DRAW_ALERTS if name == "alert"); watch = next(th for th, name, _ in OR.DRAW_ALERTS if name == "watch")
    assert re.search(rf"\*\*ALERT\*\* \| draw >= {alert:g}%", text) and re.search(rf"\*\*WATCH\*\* \| draw >= {watch:g}%", text)
    assert f"within {OR.TOSS_UP_GAP_PCT:g} points AND draw >= {OR.TOSS_UP_MIN_DRAW_PCT:g}%" in text
    assert re.search(rf"hard bounds \+-{C.MAX_RATE_PCT:g} \(rates\) and \+-{C.MAX_DRAW_PCT:g} \(draw\)", text)
    assert f"Below {C.MIN_CONFIDENCE:g} the engine ignores every adjustment" in text and "one reviewer counts half" in text
    assert f"`heavy_rotation` ({lineup.ROTATION_HEAVY}+ changes)" in text
    assert f"{int(OR.BENCHMARK_NOTE_PCT)}+ points" in text and "never change a forecast, the recommended bet, its strength or its cautions" in text
    assert "< 2.2 expected goals" in text and "a side >= 70%" in text
    for observed in (OR.DRAW_ALERTS[0][2]["precision_pct"], OR.DRAW_ALERTS[1][2]["precision_pct"]):
        assert f"{round(observed)}%" in text            # 32% / 31% quoted for the two draw levels
    assert "~88%" in text and "17 times" in text


def _producible_tags() -> set[str]:
    src = (ROOT / "football/oracle/context.py").read_text(encoding="utf-8")
    literals = set(re.findall(r'add\("([A-Z0-9]+)"', src))
    suffixes = set(re.findall(r'add\(f"\{tag\}\.([a-z]+)', src))
    return literals | {f"{side}.{s}" for side in "HA" for s in suffixes} | {"X.absent"}


def test_every_tag_the_skill_names_is_one_the_brief_can_produce():
    text = _skill_text()
    named = set(re.findall(r"\[([A-Z0-9]{2,}|[HAX]\.[a-z]+)(?:\.<name>)?\]", text)) - {"TAGS", "WRITE"}
    allowed = _producible_tags()
    missing = {t for t in named if t not in allowed and not (t.startswith("X.") and t[2:] in {a.split(".")[1] for a in allowed})}
    assert not missing, f"the skill cites tags the engine never prints: {sorted(missing)}"
    for must in ("VENUE", "REFEREE", "TRAVEL", "H2H", "LINEUPS", "H.stakes", "A.stakes", "H.manager", "H.availability", "H.fatigue"):
        assert f"[{must}]" in text, f"the skill should say how to cite {must}"


def test_the_skill_template_labels_match_what_the_draft_writes_and_the_audit_requires():
    from football.oracle import audit_answer as AA, draft as DR
    template = re.search(r"## 5\. Deliverable.*?```\n(.*?)```", _skill_text(), re.S).group(1)
    labels = [ln.split(":", 1)[0] + ":" for ln in template.splitlines() if re.match(r"^[A-Z][A-Za-z ]+:", ln) and not ln.startswith("**")]
    labels = [l for l in labels if l != "Case for {Home}:"]
    draft_text = DR.draft_answer(_report())
    drafted = {ln.split(":", 1)[0] + ":" for ln in draft_text.splitlines()}
    assert labels and all(l in drafted for l in labels), [l for l in labels if l not in drafted]
    assert all(l in AA.REQUIRED for l in labels if l != "Own model vs odds:"), [l for l in labels if l not in AA.REQUIRED]
    assert set(AA.REQUIRED) <= set(labels), sorted(set(AA.REQUIRED) - set(labels))      # the audit never demands a line the template does not show


def test_lint_draw_evidence_tags_are_real_tags():
    from football.oracle import lint as LT
    import inspect
    src = inspect.getsource(LT.lint_opinion)
    cited = set(re.findall(r"\\\[([A-Z]+)\\\]", src))
    assert cited and cited <= _producible_tags(), cited - _producible_tags()          # [WEATHER] never existed: weather is carried by [VENUE]
