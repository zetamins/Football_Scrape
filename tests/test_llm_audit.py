import json
import urllib.error

import pytest

from football import analyze as A
from football import llm_audit as L
from tests.test_analyze import NOW, _report, _row


def _analysis(report=None):
    report = report or _report(home_missing_players=[{"name": "Star Striker", "description": "Knee Injury", "absence_type": "injury"}])
    return report, A.analyze_report(report, draws=200, now=NOW)


def test_brief_contains_facts_numbers_and_absentees_but_no_raw_dump():
    report, a = _analysis()
    brief = L.build_brief(report, a)
    for needle in ("FIXTURE: Alpha (home) vs Beta (away)", "RECENT FORM", "HOME ABSENT: Star Striker (Knee Injury)", "AWAY ABSENT: none reported",
                   "CALCULATIONS", "- market:", "PREDICTION:", "RANGE (10-90%)", "DATA QUALITY"):
        assert needle in brief
    assert len(brief) < 6000 and "{" not in brief          # condensed prose/table, never the raw JSON


def test_brief_puts_form_on_the_right_side_when_the_report_is_from_the_away_team():
    rep = _report(team="Beta", home="Alpha", away="Beta")
    rep["form"] = {"last5_overall": [_row("0-1", "away", "W")] * 5}          # Beta (away) winning
    rep["opponentForm"] = {"last5_overall": [_row("0-1", "home", "L")] * 5}   # Alpha (home) losing
    a = A.analyze_report(rep, draws=100, now=NOW)
    assert "home LLLLL; away WWWWW" in L.build_brief(rep, a)


class _Resp:
    def __init__(self, body):
        self._b = json.dumps(body).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


GOOD = {"verdict": "consistent", "summary": "ok", "concerns": ["h2h"], "missing_context": [], "lean_if_any": "home"}


def test_audit_sends_a_schema_constrained_low_temperature_request_and_parses_the_reply(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"], seen["payload"], seen["timeout"] = req.full_url, json.loads(req.data), timeout
        return _Resp({"message": {"content": json.dumps(GOOD)}, "total_duration": 12_500_000_000})

    monkeypatch.setattr(L.urllib.request, "urlopen", fake_urlopen)
    out = L.audit_with_llm("brief", model="qwen3:1.7b")
    assert out == {"ok": True, "model": "qwen3:1.7b", "opinion": GOOD, "seconds": 12.5}
    p = seen["payload"]
    assert seen["url"].endswith("/api/chat") and p["model"] == "qwen3:1.7b" and p["stream"] is False
    assert p["format"] == L.SCHEMA and p["options"]["temperature"] == 0 and p["keep_alive"] == L.KEEP_ALIVE
    assert p["think"] is True and p["messages"][1]["content"] == "brief" and "ONLY facts" in p["messages"][0]["content"]
    L.audit_with_llm("brief", think=False)
    assert seen["payload"]["think"] is False


def test_audit_never_raises_and_reports_why(monkeypatch):
    monkeypatch.setattr(L, "RETRY_WAIT_S", 0.0)
    calls = []

    def down(req, timeout):
        calls.append(1)
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(L.urllib.request, "urlopen", down)
    r = L.audit_with_llm("b")
    assert r["ok"] is False and "connection refused" in r["error"] and f"after {L.RETRIES} attempts" in r["error"]
    assert len(calls) == L.RETRIES
    monkeypatch.setattr(L.urllib.request, "urlopen", lambda req, timeout: _Resp({"message": {"content": "not json"}}))
    assert L.audit_with_llm("b")["ok"] is False
    monkeypatch.setattr(L.urllib.request, "urlopen", lambda req, timeout: _Resp({"message": {"content": json.dumps({"verdict": "consistent"})}}))
    r = L.audit_with_llm("b")
    assert r["ok"] is False and "lacked" in r["error"]


def test_ollama_host_env_is_honoured(monkeypatch):
    seen = {}
    monkeypatch.setenv("OLLAMA_HOST", "10.0.0.5:11434")
    monkeypatch.setattr(L.urllib.request, "urlopen", lambda req, timeout: seen.setdefault("url", req.full_url) and _Resp({"message": {"content": json.dumps(GOOD)}}))
    L.audit_with_llm("b")
    assert seen["url"] == "http://10.0.0.5:11434/api/chat"


def test_format_section_labels_it_advisory_and_handles_failure():
    text = L.format_llm_section({"ok": True, "model": "m", "seconds": 3.0, "opinion": GOOD})
    assert "advisory" in text and "never changes the numbers" in text and "Verdict: **consistent**" in text and "Concern: h2h" in text
    assert "unavailable: boom" in L.format_llm_section({"ok": False, "error": "boom"})


def test_cli_llm_flag_parses_model_and_never_changes_the_probabilities(monkeypatch, tmp_path, capsys):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(_report()))
    calls = []
    monkeypatch.setattr(L, "audit_with_llm", lambda brief, model=None, think=True: calls.append((model, think)) or {"ok": True, "model": model or "default", "opinion": GOOD, "seconds": 1.0})
    A.main(["analyze", str(p), "--json"])
    base = json.loads(capsys.readouterr().out)[0]["prediction"]
    A.main(["analyze", str(p), "--llm", "qwen2.5:3b", "--fast", "--json"])
    with_llm = json.loads(capsys.readouterr().out)[0]
    assert calls == [("qwen2.5:3b", False)]
    assert with_llm["prediction"] == base and with_llm["llm"]["opinion"] == GOOD
    A.main(["analyze", str(p), "--llm"])                    # bare --llm: default model, thinking on
    out = capsys.readouterr().out
    assert calls[-1] == (None, True) and "## LLM audit" in out
    assert A._llm_args(["analyze", "--llm", str(p)]) == (True, None, ["analyze", str(p)])


def test_audit_retries_through_a_server_restart_but_not_through_bad_json(monkeypatch):
    import http.client

    monkeypatch.setattr(L, "RETRY_WAIT_S", 0.0)
    state = {"n": 0}

    def flaky(req, timeout):
        state["n"] += 1
        if state["n"] == 1:
            raise http.client.RemoteDisconnected("closed")
        if state["n"] == 2:
            raise urllib.error.URLError("refused")
        return _Resp({"message": {"content": json.dumps(GOOD)}})

    monkeypatch.setattr(L.urllib.request, "urlopen", flaky)
    assert L.audit_with_llm("b")["ok"] is True and state["n"] == 3
    state["n"] = 0
    monkeypatch.setattr(L.urllib.request, "urlopen", lambda req, timeout: state.__setitem__("n", state["n"] + 1) or _Resp({"message": {"content": "garbage"}}))
    assert L.audit_with_llm("b")["ok"] is False and state["n"] == 1
