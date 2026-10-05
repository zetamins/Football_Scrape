import re
import json
import urllib.error

import pytest

from football.oracle import context as C
from football.oracle import llm
from football.oracle import oracle as O
from football.oracle import quant as Q
from football.oracle.facts import audit_facts, extract_facts, norm, own_is_home


def _row(score, venue, result, comp="Nations League", xg=(None, None)):
    return {"scoreline": score, "venue": venue, "result": result, "competition": comp, "date": "2026-09-01T00:00:00Z", "opponent": "X", "xg_for": xg[0], "xg_against": xg[1]}


def _squad(prefix, n=6, value=10e6):
    roles = ["G", "D", "D", "M", "F", "F"]
    return [{"name": f"{prefix}{i}", "role": roles[i % 6], "market_value": value, "age": 25,
             "recent_usage": {"matches_in_squad": 5, "total_minutes": 450, "starts": 5, "xg_per_90": 0.2}} for i in range(n)]


_LAST = {}


def _report(team="Alpha", odds=True, xg=True, home_missing=None, away_missing=None, **match_extra):
    m = {"home_team": "Alpha", "away_team": "Beta", "kickoff_utc": "2026-10-03T18:00:00Z", "status": "notstarted", "competition": "Test League",
         "lineup_confirmed": True, "neutral": None, "home_missing_players": home_missing or [], "away_missing_players": away_missing or [],
         "betting_odds": ({"home_win_fair_pct": 55.0, "draw_fair_pct": 25.0, "away_win_fair_pct": 20.0, "over_2_5_fair_pct": 50.0, "under_2_5_fair_pct": 50.0} if odds else None),
         "home_team_standing": {"position": 1, "total_teams": 4, "points": 3, "played": 1, "goal_diff": "+1"}, "head_to_head_summary": {"home_wins": 2, "draws": 1, "away_wins": 1, "sample_size": 4}}
    m.update(match_extra)
    ins = {"home_elo_rating": {"elo": 1600, "sample_source": "eloratings.net"}, "away_elo_rating": {"elo": 1500, "sample_source": "eloratings.net"},
           "home_standings_impact": {"current_position": 1, "scenarios": [{"outcome": "win", "new_points": 6, "new_position": 1}]},
           "travel_info": {"away_traveling": True, "away_travel_distance_km": 1700, "home_travel_distance_km": 0}}
    if xg:
        ins["home_xg_estimate"] = {"sample_size": 6, "xg_for": 9.0, "xg_against": 4.0}
        ins["away_xg_estimate"] = {"sample_size": 6, "xg_for": 6.0, "xg_against": 8.0}
    own = [_row("2-0", "home", "W")] * 6
    opp = [_row("1-1", "away", "D")] * 6
    home_side = {"squad": _squad("H")}
    away_side = {"squad": _squad("A")}
    _LAST["rep"] = {"team": team, "generatedAt": "2026-10-01T10:00:00Z", "match": m, "form": {"last10_overall": own}, "opponentForm": {"last10_overall": opp},
                    "insights": ins, "teamProfile": home_side, "opponentProfile": away_side}
    return _LAST["rep"]


# ---------------------------------------------------------------- facts
def test_norm_strips_accents_and_punctuation_and_own_is_home():
    assert norm("Marc Cucurella-Sáez") == norm("marc cucurella saez")
    assert own_is_home(_report(team="alpha")) is True and own_is_home(_report(team="Beta")) is False


def test_facts_are_in_the_home_away_frame_whichever_team_the_report_is_for():
    a = extract_facts(_report(team="Alpha"))
    rep = _report(team="Beta")
    rep["form"], rep["opponentForm"] = rep["opponentForm"], rep["form"]
    rep["teamProfile"], rep["opponentProfile"] = rep["opponentProfile"], rep["teamProfile"]
    b = extract_facts(rep)
    assert a["sides"]["home"]["form"][0]["gf"] == 2 and b["sides"]["home"]["form"][0]["gf"] == 2
    assert a["sides"]["home"]["squad"][0]["name"] == "H0" and b["sides"]["home"]["squad"][0]["name"] == "H0"
    assert {k: a["odds"][k] for k in ("home", "draw", "away", "over_2_5")} == pytest.approx({"home": 0.55, "draw": 0.25, "away": 0.20, "over_2_5": 0.5})


def test_absentees_are_weighted_by_value_share_and_recent_minutes_per_role_group():
    miss = [{"name": "A4", "description": "knee"}, {"name": "A1", "description": "ill"}, {"name": "Unknown Guy", "description": "x"}]
    f = extract_facts(_report(away_missing=miss))
    ab = f["sides"]["away"]["absentees"]
    assert [a["role"] for a in ab] == ["F", "D", None] and ab[2]["in_squad_list"] is False and ab[2]["impact"] == 0
    assert ab[0]["impact"] == pytest.approx((10e6 / 60e6) * 1.0, abs=1e-4)       # full minutes -> weight = value share
    loss = f["sides"]["away"]["absence_loss"]
    assert loss["attack_loss"] == pytest.approx(ab[0]["impact"], abs=1e-4) and loss["defence_loss"] == pytest.approx(ab[1]["impact"], abs=1e-4)
    benched = _report(away_missing=[{"name": "A4"}])
    benched["opponentProfile"]["squad"][4]["recent_usage"]["total_minutes"] = 0
    assert extract_facts(benched)["sides"]["away"]["absentees"][0]["impact"] == pytest.approx((10e6 / 60e6) * 0.5, abs=1e-4)


def test_odds_fall_back_to_raw_prices_and_none_when_unusable():
    raw = _report(odds=False, betting_odds={"home_win_odds": 2.0, "draw_odds": 4.0, "away_win_odds": 4.0})
    assert extract_facts(raw)["odds"]["home"] == pytest.approx(0.5)
    assert extract_facts(_report(odds=False))["odds"] is None
    assert extract_facts(_report(odds=False, betting_odds={"home_win_odds": 0.9, "draw_odds": 4, "away_win_odds": 4}))["odds"] is None


def test_audit_flags_and_quality():
    full = audit_facts(extract_facts(_report()))
    poor = audit_facts(extract_facts(_report(odds=False, xg=False, lineup_confirmed=False, home_missing=[{"name": "Nobody"}])))
    codes = {f["code"] for f in poor["findings"]}
    assert {"no_odds", "no_xg", "lineup_unconfirmed", "absentee_not_in_squad"} <= codes
    assert poor["quality"] < full["quality"] <= 1.0
    live = audit_facts(extract_facts(_report(status="inprogress")))
    assert any(f["code"] == "not_pre_match" and f["severity"] == "error" for f in live["findings"])
    late = _report(); late["generatedAt"] = "2026-10-03T19:00:00Z"
    assert any(f["code"] == "after_kickoff" for f in audit_facts(extract_facts(late))["findings"])


# ---------------------------------------------------------------- quant
def test_market_rates_reproduce_the_odds_and_over_under():
    rates = Q.market_rates({"home": 0.55, "draw": 0.25, "away": 0.20, "over_2_5": 0.50})
    h, d, a = Q.outcome_probs(*rates)
    assert (h, d, a) == pytest.approx((0.55, 0.25, 0.20), abs=0.025)
    assert Q.over_prob(*rates) == pytest.approx(0.50, abs=0.04)
    lo, hi = Q.market_rates({"home": 0.5, "draw": 0.3, "away": 0.2, "over_2_5": 0.35}), Q.market_rates({"home": 0.5, "draw": 0.3, "away": 0.2, "over_2_5": 0.65})
    assert sum(hi) > sum(lo)                                            # a higher over line means more total goals


def test_all_four_sources_run_and_combine_between_their_extremes():
    f = extract_facts(_report())
    src = Q.rate_sources(f)
    assert {s["name"] for s in src} == {"market", "xg", "results", "strength"}
    lh, la, spread = Q.combine_rates(src)
    assert min(s["lam"][0] for s in src) <= lh <= max(s["lam"][0] for s in src) and spread >= 0
    assert Q.combine_rates([src[0]])[2] == 0.25                          # single source: wide default uncertainty


def test_neutral_venue_removes_home_edge_from_goal_models():
    base = _report(); neutral = _report(neutral=True)
    for r in (base, neutral):
        r["match"]["betting_odds"] = None
    h = {s["name"]: s for s in Q.rate_sources(extract_facts(base))}
    n = {s["name"]: s for s in Q.rate_sources(extract_facts(neutral))}
    assert h["results"]["lam"][0] > n["results"]["lam"][0] and h["results"]["lam"][1] < n["results"]["lam"][1]


def test_short_samples_are_shrunk_toward_the_pooled_mean():
    sparse = Q._poisson_rates((4.0, 0.0, 1.0), (1.0, 1.0, 1.0), True)
    solid = Q._poisson_rates((4.0, 0.0, 20.0), (1.0, 1.0, 20.0), True)
    assert solid[0] > sparse[0]


def test_absence_multipliers_direction_and_cap():
    f = extract_facts(_report(away_missing=[{"name": "A4"}, {"name": "A5"}, {"name": "A1"}], home_missing=[{"name": "H0"}, {"name": "H1"}]))
    mh, ma, notes = Q.absence_multipliers(f, scale=1.0)
    assert ma < 1 and mh > 1 and len(notes) == 2     # away loses attackers (and home GK/D are out): away scores less/more net; away D out -> home scores more
    only_att = Q.absence_multipliers(extract_facts(_report(away_missing=[{"name": "A4"}, {"name": "A5"}])), scale=1.0)
    assert only_att[1] < 1 and only_att[0] == 1.0     # missing attackers only lower that side's own rate
    huge = {"sides": {"home": {"absence_loss": {"attack_loss": 5.0, "defence_loss": 5.0}}, "away": {"absence_loss": {"attack_loss": 5.0, "defence_loss": 5.0}}}}
    mh2, ma2, _ = Q.absence_multipliers(huge, scale=1.0)
    assert 1 - Q.MAX_ABSENCE_EFFECT <= mh2 <= 1 + Q.MAX_ABSENCE_EFFECT and 1 - Q.MAX_ABSENCE_EFFECT <= ma2 <= 1 + Q.MAX_ABSENCE_EFFECT
    assert Q.absence_multipliers(extract_facts(_report()), scale=1.0)[:2] == (1.0, 1.0)
    off = Q.absence_multipliers(f)                                        # default: computed and reported, not applied
    assert off[:2] == (1.0, 1.0) and "NOT applied" in off[2][0] and Q.ABSENCE_APPLY_SCALE == 0.0


def test_exact_distribution_is_the_validated_grid_deterministic_and_internally_consistent():
    d = Q.exact_distribution(1.8, 1.0)
    h, dr, a = Q.outcome_probs(1.8, 1.0)
    assert (d["home"], d["draw"], d["away"]) == pytest.approx((h, dr, a)) and d["home"] + d["draw"] + d["away"] == pytest.approx(1.0)
    assert d == Q.exact_distribution(1.8, 1.0)                                       # no sampling: identical every time
    assert d["expected_goals"] == pytest.approx((1.8, 1.0), abs=0.06)
    m = d["markets"]
    assert 0 < m["over_3_5"] < m["over_2_5"] < m["over_1_5"] < 1 and 0 < m["btts"] < 1 and m["home_cs"] > m["away_cs"]
    pcts = [x["pct"] for x in d["top_scores"]]
    assert pcts == sorted(pcts, reverse=True) and d["top_scores"][0]["score"] in ("1-0", "2-1", "2-0", "1-1")
    assert sum(d["margin_pct"].values()) > 95 and d["draw_scores_pct"]["1-1"] > d["draw_scores_pct"]["2-2"] > d["draw_scores_pct"]["3-3"]
    assert Q.exact_distribution(1.0, 1.0)["home"] == pytest.approx(Q.exact_distribution(1.0, 1.0)["away"])     # symmetric rates, symmetric result


def test_probability_spread_brackets_the_point_estimate():
    rng = Q.probability_spread(1.6, 1.0, 0.2, draws=300)
    point = Q.outcome_probs(1.6, 1.0)
    for k, name in enumerate(("home", "draw", "away")):
        lo, hi = rng[name]
        assert lo <= 100 * point[k] <= hi or abs(100 * point[k] - lo) < 3 or abs(100 * point[k] - hi) < 3
    wide = Q.probability_spread(1.6, 1.0, 0.45, draws=300)
    assert wide["home"][1] - wide["home"][0] > rng["home"][1] - rng["home"][0]


# ---------------------------------------------------------------- context panel
def _tags():
    return {"[H.stakes]", "[TRAVEL]", "[A.rotation]"}


def test_validation_clamps_numbers_and_drops_unevidenced_claims():
    op = {"home_rate_pct": 50, "away_rate_pct": -40, "draw_bias_pct": 9, "confidence": 0.9,
          "factors": [{"effect": "home_rate_pct", "evidence": "[H.stakes]", "note": "ok"}, {"effect": "away_rate_pct", "evidence": "[MADE.UP]", "note": "invented"}]}
    v = C.validate_opinion(op, _tags())
    assert v["adjust"]["home_rate_pct"] == C.MAX_RATE_PCT                   # clamped, supported
    assert v["adjust"]["away_rate_pct"] == 0.0                              # only an invented tag -> ignored
    assert v["adjust"]["draw_bias_pct"] == 0.0                              # no factor at all -> ignored
    assert len(v["rejected"]) == 1 and v["rejected"][0]["evidence"] == "[MADE.UP]"


def test_validation_scales_partly_supported_adjustments_and_ignores_low_confidence():
    op = {"home_rate_pct": 8, "confidence": 0.8, "factors": [{"effect": "home_rate_pct", "evidence": "H.stakes"}, {"effect": "home_rate_pct", "evidence": "[nope]"}]}
    assert C.validate_opinion(op, _tags())["adjust"]["home_rate_pct"] == pytest.approx(4.0)     # half the claims supported; bare tag text is accepted
    op["confidence"] = 0.1
    assert C.validate_opinion(op, _tags())["adjust"]["home_rate_pct"] == 0.0
    assert C.validate_opinion({"home_rate_pct": "abc", "confidence": "x", "factors": ["junk", 3]}, _tags())["adjust"] == {"home_rate_pct": 0.0, "away_rate_pct": 0.0, "draw_bias_pct": 0.0}


def test_aggregation_trusts_fewer_voices_less():
    def v(h, a=0.0, d=0.0):
        return {"adjust": {"home_rate_pct": h, "away_rate_pct": a, "draw_bias_pct": d}}
    assert C.aggregate([])["adjust"] == {e: 0.0 for e in C.EFFECTS}
    assert C.aggregate([v(8)])["adjust"]["home_rate_pct"] == 4.0                          # single voice x0.5
    assert C.aggregate([v(8), v(4)])["adjust"]["home_rate_pct"] == pytest.approx(4.5)     # mean x0.75
    three = C.aggregate([v(8), v(4), v(-10)])                                             # median: a lone outlier is ignored
    assert three["adjust"]["home_rate_pct"] == 4.0 and three["trust"] == 1.0 and three["agreement"] == pytest.approx(0.67, abs=0.01)


def test_brief_has_tagged_lines_facts_and_baseline_but_not_the_prediction():
    f = extract_facts(_report(away_missing=[{"name": "A4", "description": "knee"}]))
    brief, tags = C.build_brief(f, {"lam_home": 1.8, "lam_away": 0.9, "home": 0.6, "draw": 0.25, "away": 0.15})
    assert "[A.absent.A4]" in tags and "[H.form]" in tags and "[BASELINE]" in tags and "[H2H]" in tags
    assert all(line.startswith("[") for line in brief.splitlines())
    assert "knee" in brief and "1.80-0.90" in brief


def _fake_llm(monkeypatch, replies):
    """replies: {model: dict | Exception}; records every call."""
    calls = []

    def fake(provider, model, system, user, key):
        calls.append((provider, model))
        r = replies[model]
        if isinstance(r, Exception):
            raise r
        return json.dumps(r)

    monkeypatch.setattr(llm, "_dispatch", fake)
    monkeypatch.setattr(llm, "PROVIDERS", {**llm.PROVIDERS, "nvidia": {**llm.PROVIDERS["nvidia"], "interval": 0.0}, "openrouter": {**llm.PROVIDERS["openrouter"], "interval": 0.0}})
    monkeypatch.setenv("NVIDIA_API_KEY", "k1"); monkeypatch.setenv("OPENROUTER_API_KEY", "k2")
    return calls


OPINION = {"home_rate_pct": 4, "away_rate_pct": -2, "draw_bias_pct": 1, "confidence": 0.7,
           "factors": [{"effect": "home_rate_pct", "evidence": "[H.stakes]", "note": "must win"}, {"effect": "away_rate_pct", "evidence": "[TRAVEL]", "note": "long trip"}, {"effect": "draw_bias_pct", "evidence": "[H2H]", "note": "x"}],
           "data_gaps": ["lineups"]}


def test_panel_survives_a_failing_member_and_reports_it(monkeypatch, tmp_path):
    monkeypatch.setenv("ORACLE_LLM_CACHE", str(tmp_path / "c.jsonl"))
    monkeypatch.setattr(llm, "MAX_RETRIES", 1)
    calls = _fake_llm(monkeypatch, {"m1": OPINION, "m2": OPINION, "m3": urllib.error.HTTPError("u", 401, "no", {}, None)})
    f = extract_facts(_report())
    res = C.run_panel(f, {"lam_home": 1.8, "lam_away": 0.9, "home": 0.6, "draw": 0.25, "away": 0.15}, [("nvidia", "m1"), ("openrouter", "m2"), ("nvidia", "m3")])
    assert res["n"] == 2 and [m["ok"] for m in res["members"]] == [True, True, False]
    assert "HTTP 401" in res["members"][2]["error"] and "k1" not in json.dumps(res) and "k2" not in json.dumps(res)   # keys never leak
    assert res["adjust"]["home_rate_pct"] == pytest.approx(0.75 * 4)
    assert res["data_gaps"] == ["lineups"] and len(calls) == 3


# ---------------------------------------------------------------- llm client
def test_extract_json_handles_fences_prose_and_rejects_garbage():
    assert llm.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.extract_json('Sure! {"a": {"b": 2}} done') == {"a": {"b": 2}}
    for bad in ("no json here", "[1,2]", ""):
        with pytest.raises(ValueError):
            llm.extract_json(bad)


def test_ask_json_caches_responses_and_a_cache_hit_makes_no_call(monkeypatch, tmp_path):
    monkeypatch.setenv("ORACLE_LLM_CACHE", str(tmp_path / "c.jsonl"))
    calls = _fake_llm(monkeypatch, {"m1": {"x": 1}})
    first = llm.ask_json("nvidia", "sys", "usr", model="m1")
    second = llm.ask_json("nvidia", "sys", "usr", model="m1")
    assert first["ok"] and first["cached"] is False and second["cached"] is True and second["data"] == {"x": 1} and len(calls) == 1
    assert llm.ask_json("nvidia", "sys", "other prompt", model="m1")["cached"] is False and len(calls) == 2
    assert llm.ask_json("nvidia", "sys", "usr", model="m1", use_cache=False)["cached"] is False and len(calls) == 3


def test_ask_json_retries_transient_errors_but_not_auth_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("ORACLE_LLM_CACHE", str(tmp_path / "c.jsonl"))
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    seq = iter([urllib.error.HTTPError("u", 429, "slow", {}, None), urllib.error.URLError("down"), '{"ok": 1}'])

    def flaky(provider, model, system, user, key):
        v = next(seq)
        if isinstance(v, Exception):
            raise v
        return v

    _fake_llm(monkeypatch, {})
    monkeypatch.setattr(llm, "_dispatch", flaky)
    assert llm.ask_json("nvidia", "s", "u")["data"] == {"ok": 1}
    calls = []
    monkeypatch.setattr(llm, "_dispatch", lambda *a: calls.append(1) or (_ for _ in ()).throw(urllib.error.HTTPError("u", 403, "denied", {}, None)))
    r = llm.ask_json("nvidia", "s", "u2")
    assert r["ok"] is False and "HTTP 403" in r["error"] and len(calls) == 1


def test_missing_key_and_unknown_provider_fail_cleanly_and_panel_defaults(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    assert "NVIDIA_API_KEY is not set" in llm.ask_json("nvidia", "s", "u", use_cache=False)["error"]
    assert llm.ask_json("nope", "s", "u")["ok"] is False
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert llm.default_panel() == [("ollama", llm.PROVIDERS["ollama"]["model"])]
    monkeypatch.setenv("NVIDIA_API_KEY", "x")
    assert [p for p, _ in llm.default_panel()] == ["nvidia", "nvidia", "nvidia"]
    assert "gemini" not in llm.available_providers()


# ---------------------------------------------------------------- pipeline
def test_panel_spec_parsing():
    assert O._parse_panel("none") == []
    assert O._parse_panel("nvidia:foo/bar,openrouter:baz") == [("nvidia", "foo/bar"), ("openrouter", "baz")]
    assert all(p == "nvidia" for p, _ in O._parse_panel("nvidia"))


def test_predict_without_llm_is_a_consistent_purely_quantitative_prediction():
    r = O.predict(_report(), panel="none", sims=20_000)
    p = r["prediction"]
    assert r["panel"] is None and p["home_win_pct"] > p["away_win_pct"] and p["pick"] == "home"
    assert p["home_win_pct"] + p["draw_pct"] + p["away_win_pct"] == pytest.approx(100.0, abs=0.2)
    assert p["confidence_pct"] > 40 and p["ranges_pct"]["home"][0] < p["home_win_pct"] < p["ranges_pct"]["home"][1] + 8
    assert O.predict(_report(), panel="none", sims=20_000) == r                  # deterministic


def test_llm_adjustments_move_the_rates_but_never_beyond_the_bounds(monkeypatch, tmp_path):
    monkeypatch.setenv("ORACLE_LLM_CACHE", str(tmp_path / "c.jsonl"))
    _fake_llm(monkeypatch, {"m1": OPINION, "m2": OPINION, "m3": OPINION})
    base = O.predict(_report(), panel="none", sims=20_000)["prediction"]
    withllm = O.predict(_report(), panel=[("nvidia", "m1"), ("nvidia", "m2"), ("openrouter", "m3")], sims=20_000)
    q = withllm["prediction"]
    assert q["lam_home"] == pytest.approx(base["lam_home"] * 1.04, rel=3e-3) and q["lam_away"] == pytest.approx(base["lam_away"] * 0.98, rel=3e-3)
    wild = dict(OPINION, home_rate_pct=500, away_rate_pct=-500)
    _fake_llm(monkeypatch, {"m1": wild, "m2": wild, "m3": wild})
    extreme = O.predict(_report(), panel=[("nvidia", "m1"), ("nvidia", "m2"), ("openrouter", "m3")], sims=20_000, use_cache=False)["prediction"]
    assert extreme["lam_home"] <= base["lam_home"] * 1.12 * 1.002 and extreme["lam_away"] >= base["lam_away"] * 0.88 * 0.998   # +-12% cap (rates are rounded to 3 decimals)
    assert extreme["lam_home"] > base["lam_home"] * 1.10 and extreme["lam_away"] < base["lam_away"] * 0.90        # ...and the cap is actually reached


def test_no_sources_gives_no_prediction_and_markdown_says_so():
    empty = {"team": "A", "match": {"home_team": "A", "away_team": "B", "status": "notstarted"}, "form": None, "opponentForm": None, "insights": {}}
    r = O.predict(empty, panel="none", sims=1000)
    assert r["prediction"] is None and "No prediction" in O.format_report(r)


def test_report_and_cli(tmp_path, capsys, monkeypatch):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(_report(away_missing=[{"name": "A4"}])))
    assert O.main(["oracle", str(p), "--llm", "none", "--sims", "5000"]) == 0
    text = capsys.readouterr().out
    for needle in ("## 1. Data audit", "## 2. Quantitative engine", "## 3. Context review (LLM panel or reviewer)", "## 4. Score distribution", "Player-level absences", "calibrated chance"):
        assert needle in text
    assert O.main(["oracle", str(tmp_path), "--llm", "none", "--sims", "2000", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["prediction"]["pick"] in O.OUTCOMES
    assert O.main(["oracle"]) == 2
    bad = tmp_path / "bad.json"; bad.write_text("garbage")
    assert O.main(["oracle", str(bad), "--llm", "none"]) == 0


def test_panel_calls_run_concurrently_and_results_keep_panel_order(monkeypatch, tmp_path):
    import threading
    import time

    monkeypatch.setenv("ORACLE_LLM_CACHE", str(tmp_path / "c.jsonl"))
    monkeypatch.setattr(llm, "PROVIDERS", {**llm.PROVIDERS, "nvidia": {**llm.PROVIDERS["nvidia"], "interval": 0.0}})
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    active, peak, lock = [0], [0], threading.Lock()

    def slow(provider, model, system, user, key):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.15)
        with lock:
            active[0] -= 1
        return json.dumps(dict(OPINION, home_rate_pct={"a": 1, "b": 2, "c": 3}[model]))

    monkeypatch.setattr(llm, "_dispatch", slow)
    t = time.time()
    res = C.run_panel(extract_facts(_report()), {"lam_home": 1.8, "lam_away": 0.9, "home": 0.6, "draw": 0.25, "away": 0.15}, [("nvidia", "a"), ("nvidia", "b"), ("nvidia", "c")])
    assert peak[0] == 3 and time.time() - t < 0.4                      # three 0.15 s calls overlapped
    assert [m["model"] for m in res["members"]] == ["a", "b", "c"]     # order preserved


def test_throttle_spaces_calls_for_one_provider_even_across_threads(monkeypatch):
    import threading

    monkeypatch.setattr(llm, "PROVIDERS", {**llm.PROVIDERS, "nvidia": {**llm.PROVIDERS["nvidia"], "interval": 0.1}})
    monkeypatch.setattr(llm, "_last_call", {})
    stamps = []
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    monkeypatch.setattr(llm, "_dispatch", lambda *a: stamps.append(__import__("time").monotonic()) or '{"x": 1}')
    threads = [threading.Thread(target=lambda i=i: llm.ask_json("nvidia", "s", f"u{i}", use_cache=False)) for i in range(4)]
    [t.start() for t in threads]; [t.join() for t in threads]
    gaps = sorted(stamps)
    assert all(b - a >= 0.08 for a, b in zip(gaps, gaps[1:]))


# ---------------------------------------------------------------- agent hooks (brief + --opinion)
def test_brief_lists_tags_baseline_audit_and_the_reply_format():
    b = O.brief(_report(away_missing=[{"name": "A4", "description": "knee"}]))
    assert "[A.absent.A4]" in b["tags"] and "[H.form]" in b["tags"] and b["baseline"]["lam_home"] > 0
    assert b["bounds"] == {"rate_pct": 12.0, "draw_pp": 3.0} and "factors" in b["opinion_format"] and b["mode"] == "independent"
    assert any(f["code"] == "weak_model" for f in b["audit"]["findings"])        # Alpha/Beta have no trained model
    text = O.format_brief(b)
    assert "# BRIEF: Alpha vs Beta" in text and "Opinion file (--opinion-file)" in text and "[H.stakes]" in text
    empty = {"team": "A", "match": {"home_team": "A", "away_team": "B"}, "form": None, "opponentForm": None, "insights": {}}
    assert O.brief(empty)["brief"] is None and "No quantitative baseline" in O.format_brief(O.brief(empty))


def test_agent_opinion_is_validated_like_a_panel_member():
    rep = _report(away_missing=[{"name": "A4", "description": "knee"}])
    base = O.predict(rep, panel="none", sims=10_000)["prediction"]
    good = {"away_rate_pct": -6, "confidence": 0.8, "factors": [{"effect": "away_rate_pct", "evidence": "[A.absent.A4]", "note": "x"}]}
    half = O.predict(rep, panel="none", sims=10_000, opinions=[good])                     # default: a lone voice counts x0.5
    full = O.predict(rep, panel="none", sims=10_000, opinions=[good], opinion_trust=1.0)
    assert half["prediction"]["lam_away"] == pytest.approx(base["lam_away"] * 0.97, rel=2e-3)
    assert full["prediction"]["lam_away"] == pytest.approx(base["lam_away"] * 0.94, rel=2e-3)
    assert half["panel"]["members"][0]["provider"] == "reviewer" and half["panel"]["factors"][0]["by"] == "reviewer"
    bad = {"home_rate_pct": 10, "away_rate_pct": -10, "confidence": 0.9, "factors": [{"effect": "home_rate_pct", "evidence": "[INVENTED]", "note": "x"}]}
    ignored = O.predict(rep, panel="none", sims=10_000, opinions=[bad], opinion_trust=1.0)["prediction"]
    assert ignored["lam_home"] == base["lam_home"] and ignored["lam_away"] == base["lam_away"]       # unevidenced claims change nothing
    wild = dict(good, away_rate_pct=-99)
    assert O.predict(rep, panel="none", sims=10_000, opinions=[wild], opinion_trust=1.0)["prediction"]["lam_away"] >= base["lam_away"] * 0.88 * 0.998


def test_cli_brief_and_opinion_flags(tmp_path, capsys):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(_report(away_missing=[{"name": "A4"}])))
    assert O.main(["oracle", "brief", str(p)]) == 0
    assert "# BRIEF" in capsys.readouterr().out
    assert O.main(["oracle", "brief", str(p), "--json"]) == 0
    assert "[A.absent.A4]" in json.loads(capsys.readouterr().out)[0]["tags"]
    op = json.dumps({"away_rate_pct": -4, "confidence": 0.7, "factors": [{"effect": "away_rate_pct", "evidence": "[A.absent.A4]", "note": "x"}]})
    assert O.main(["oracle", str(p), "--opinion", op, "--trust", "1", "--sims", "3000", "--json"]) == 0
    res = json.loads(capsys.readouterr().out)[0]
    assert res["panel"]["adjust"]["away_rate_pct"] == -4.0 and res["panel"]["trust"] == 1.0
    of = tmp_path / "op.json"; of.write_text(op)
    assert O.main(["oracle", str(p), "--opinion-file", str(of), "--sims", "3000"]) == 0
    assert "reviewer" in capsys.readouterr().out
    assert O.main(["oracle", str(p), "--opinion", "{not json"]) == 2


# ---------------------------------------------------------------- fixes found by the skill test on 38 reports
def test_home_edge_follows_the_venue_not_the_label():
    from football.oracle.facts import home_edge

    base = {"home_team_country": "Botswana", "away_team_country": "Tunisia"}
    assert home_edge({**base, "venue_country": "Botswana"})[0] == 1
    edge, why = home_edge({**base, "venue_country": "Tunisia"})        # labelled home, played in the away side's country
    assert edge == -1 and "AWAY" in why
    assert home_edge({**base, "venue_country": "Slovakia"})[0] == 0     # third country: neutral
    assert home_edge({**base, "venue_country": "Tunisia", "neutral": True})[0] == 0
    assert home_edge({"home_team_country": "Ivory Coast", "away_team_country": "Somalia", "venue_country": "Côte d'Ivoire"})[0] == 1   # spelling aliases
    assert home_edge({"venue_country": "Spain"})[0] == 1                # no team countries: trust the label


def test_goal_models_flip_the_home_edge_when_the_away_side_hosts():
    rows = ((1.5, 1.0, 8.0), (1.5, 1.0, 8.0))
    home, away, neutral = (Q._poisson_rates(*rows, e) for e in (1, -1, 0))
    assert home[0] > neutral[0] > away[0] and home[1] < neutral[1] < away[1]
    assert neutral[0] == pytest.approx(neutral[1])
    rep = _report(odds=False, away_team_country="Beta", home_team_country="Alpha", venue_country="Beta")
    flipped = {s["name"]: s for s in Q.rate_sources(extract_facts(rep))}
    plain = {s["name"]: s for s in Q.rate_sources(extract_facts(_report(odds=False)))}
    assert flipped["results"]["lam"][0] < plain["results"]["lam"][0] and flipped["strength"]["lam"][0] < plain["strength"]["lam"][0]


def test_audit_reports_the_venue_override():
    facts = extract_facts(_report(away_team_country="Beta", home_team_country="Alpha", venue_country="Beta"))
    finding = next(f for f in audit_facts(facts)["findings"] if f["code"] == "venue_edge")
    assert "AWAY" in finding["message"]
    brief, _ = C.build_brief(facts, {"lam_home": 1.0, "lam_away": 1.0, "home": 0.4, "draw": 0.3, "away": 0.3})
    assert "home edge goes to: AWAY side" in brief


def test_absences_are_not_applied_to_the_odds_source(monkeypatch):
    monkeypatch.setattr(Q, "ABSENCE_APPLY_SCALE", 1.0)
    srcs = [{"name": "market", "lam": (2.0, 0.6), "weight": 20.0}, {"name": "results", "lam": (1.5, 1.0), "weight": 1.0}]
    out = Q.apply_absences(srcs, 0.8, 1.2)
    assert out[0]["lam"] == (2.0, 0.6) and out[1]["lam"] == pytest.approx((1.2, 1.2))
    miss = [{"name": "A4", "description": "knee"}, {"name": "A5", "description": "knee"}]
    with_odds = O._engine(extract_facts(_report(away_missing=miss)), use_odds=True)
    plain = O._engine(extract_facts(_report()), use_odds=True)
    shift_odds = with_odds["lam_a1"] / plain["lam_a1"]
    no_odds = O._engine(extract_facts(_report(odds=False, away_missing=miss)), use_odds=True)
    no_odds_plain = O._engine(extract_facts(_report(odds=False)), use_odds=True)
    shift_no_odds = no_odds["lam_a1"] / no_odds_plain["lam_a1"]
    assert shift_no_odds < shift_odds < 1.0 and (1 - shift_odds) < 0.25 * (1 - shift_no_odds) + 0.01     # odds absorb ~85% of the blend: absences barely move it
    assert any("non-odds sources only" in n for n in with_odds["absence_notes"])


def test_implausible_scores_are_capped_and_flagged():
    rows = [_row("10-0", "home", "W")] + [_row("1-1", "home", "D")] * 5
    rep = _report()
    rep["form"] = {"last10_overall": rows}
    f = extract_facts(rep)
    assert any(x["code"] == "implausible_score" for x in audit_facts(f)["findings"])
    capped = Q._weighted(f["sides"]["home"]["form"], "gf", "ga")
    raw_row_sum = sum(r["gf"] for r in f["sides"]["home"]["form"])
    assert capped[0] < raw_row_sum / 6 and capped[0] < 2.2          # 10 goals counted as 6, not 10


def test_audit_flags_rotation_artefacts_travel_contradictions_and_zero_value_squads():
    rep = _report()
    rep["insights"]["home_rotation"] = {"changed_players": 11, "starting_xi_size": 11}
    rep["insights"]["travel_info"] = {"home_traveling": True, "away_traveling": True, "away_travel_distance_km": 100}
    for p in rep["teamProfile"]["squad"]:
        p["market_value"] = 0
    codes = {x["code"] for x in audit_facts(extract_facts(rep))["findings"]}
    assert {"rotation_artefact", "travel_contradiction"} <= codes
    rep["teamProfile"]["squad"] = _squad("H", n=8, value=0)
    assert "zero_value_players" in {x["code"] for x in audit_facts(extract_facts(rep))["findings"]}


def test_evidence_field_accepts_several_tags_only_if_every_tag_exists():
    tags = {"[H.stakes]", "[TRAVEL]"}
    both = {"home_rate_pct": 4, "confidence": 0.8, "factors": [{"effect": "home_rate_pct", "evidence": "[H.stakes], [TRAVEL]"}]}
    assert C.validate_opinion(both, tags)["adjust"]["home_rate_pct"] == 4.0
    partly = {"home_rate_pct": 4, "confidence": 0.8, "factors": [{"effect": "home_rate_pct", "evidence": "[H.stakes], [NOPE]"}]}
    assert C.validate_opinion(partly, tags)["adjust"]["home_rate_pct"] == 0.0


def test_brief_says_unmodelled_for_absentees_missing_from_the_squad_list():
    f = extract_facts(_report(away_missing=[{"name": "A4", "description": "knee"}, {"name": "Stranger", "description": "ill"}]))
    brief, _ = C.build_brief(f, {"lam_home": 1.0, "lam_away": 1.0, "home": 0.4, "draw": 0.3, "away": 0.3})
    assert "modelled impact" in brief and "NOT in the squad list: impact unknown and unmodelled" in brief


# ---------------------------------------------------------------- draw lens
def _lens(final, lam=(1.4, 1.1)):
    sim = {"draw_scores_pct": {"0-0": 9.0, "1-1": 11.0, "2-2": 3.0, "3-3": 0.4}}
    return O.draw_lens(final, sim, lam[0], lam[1])


def test_draw_tiers_follow_the_draw_probability_with_observed_rates():
    assert _lens([0.85, 0.10, 0.05])["tier"] == "very low" and _lens([0.85, 0.10, 0.05])["observed_draw_rate_pct"] == 7.8
    assert _lens([0.50, 0.21, 0.29])["tier"] == "moderate"
    assert _lens([0.36, 0.29, 0.35])["tier"] == "elevated"
    top = _lens([0.34, 0.32, 0.34])
    assert top["tier"] == "high" and top["observed_draw_rate_pct"] < 35          # even the top tier is ~3 in 10, never a likely result
    rates = [t[2] for t in O.DRAW_TIERS]
    assert [t[0] for t in O.DRAW_TIERS] == sorted(t[0] for t in O.DRAW_TIERS) and max(rates) < 35


def test_toss_up_label_needs_level_sides_and_a_high_draw_but_does_not_change_the_pick():
    assert _lens([0.355, 0.29, 0.355])["toss_up"] is True
    assert _lens([0.40, 0.29, 0.31])["toss_up"] is False                         # sides 9 points apart
    assert _lens([0.38, 0.24, 0.38])["toss_up"] is False                         # level but the draw is not high
    r = O.predict(_report(odds=False), panel="none", sims=5000)["prediction"]
    assert r["pick"] in O.OUTCOMES and "toss_up" in r["draw"]


def test_double_chance_probabilities_are_consistent():
    d = _lens([0.5, 0.25, 0.25])
    dc = d["double_chance_pct"]
    assert dc == {"home_or_draw": 75.0, "draw_or_away": 50.0, "home_or_away": 75.0}
    assert dc["home_or_draw"] + dc["draw_or_away"] - d["draw_pct"] == pytest.approx(100.0, abs=0.2)     # H+D and D+A overlap only on the draw


def test_flags_describe_toss_ups_low_scoring_games_and_heavy_favourites_only_when_true():
    assert any("toss-up" in f for f in _lens([0.355, 0.29, 0.355])["flags"])
    assert any("low-scoring" in f for f in _lens([0.4, 0.3, 0.3], lam=(1.0, 0.9))["flags"])
    assert not any("low-scoring" in f for f in _lens([0.4, 0.3, 0.3], lam=(1.6, 1.3))["flags"])
    assert any("heavy favourite" in f for f in _lens([0.80, 0.13, 0.07])["flags"])
    assert _lens([0.45, 0.25, 0.30], lam=(1.6, 1.3))["flags"] == []


def test_simulation_reports_drawn_scorelines_and_the_report_has_a_draw_lens_section():
    sim = Q.exact_distribution(1.0, 1.0)
    ds = sim["draw_scores_pct"]
    assert set(ds) == {"0-0", "1-1", "2-2", "3-3"} and ds["1-1"] > ds["2-2"] > ds["3-3"] and sum(ds.values()) <= 100 * sim["draw"] + 0.2
    text = O.format_report(O.predict(_report(), panel="none", sims=5000))
    assert "### Draw lens" in text and "draw risk" in text and "Double chance" in text and "Drawn scorelines" in text


def test_draw_alert_levels_match_the_measured_thresholds():
    assert _lens([0.45, 0.30, 0.25])["alert"] == "alert" and _lens([0.45, 0.30, 0.25])["alert_stats"]["precision_pct"] == 31.8
    assert _lens([0.45, 0.28, 0.27])["alert"] == "watch" and _lens([0.45, 0.28, 0.27])["alert_stats"]["recall_pct"] == 51.9
    none = _lens([0.60, 0.20, 0.20])
    assert none["alert"] == "none" and none["alert_stats"] is None
    for name, stats in ((x[1], x[2]) for x in O.DRAW_ALERTS):                      # measured stats must be internally sane
        assert 23.2 < stats["precision_pct"] < 40 and 0 < stats["recall_pct"] < 100 and 0 < stats["fires_pct"] < 100
    text = O.format_report(O.predict(_report(odds=False), panel="none", sims=3000))
    assert "Draw lens" in text and ("Draw ALERT" in text or "Draw WATCH" in text or "No draw alert" in text)


# ---------------------------------------------------------------- odds challenge + advocates
from football.oracle import debate as D


def test_challenge_compares_odds_with_the_models_without_odds_and_states_the_base_rate():
    rep = _report()
    rep["match"]["betting_odds"] = {"home_win_fair_pct": 20.0, "draw_fair_pct": 25.0, "away_win_fair_pct": 55.0, "over_2_5_fair_pct": 50, "under_2_5_fair_pct": 50}
    f = extract_facts(rep)
    ch = D.challenge(f, O._engine(f))
    assert ch["market"] == [20.0, 25.0, 55.0] and sum(ch["model_only"]) == pytest.approx(100.0, abs=0.3)
    assert ch["gap_pp"]["home"] > 0 > ch["gap_pp"]["away"] and ch["models_lean"] == "home" and ch["stance"] == "challenge-strong"      # models like the home side, odds do not
    assert "36 labelled fixtures" in ch["history"] and "burden" not in ch["history"] and "challenge only with specific, unpriced evidence" in ch["history"]
    agree = _report()
    agree["match"]["betting_odds"] = {"home_win_fair_pct": 55.0, "draw_fair_pct": 25.0, "away_win_fair_pct": 20.0}
    f2 = extract_facts(agree)
    assert D.challenge(f2, O._engine(f2))["stance"] in ("agree", "challenge-light") and D.challenge(extract_facts(_report(odds=False)), O._engine(extract_facts(_report(odds=False)))) is None


def test_dossier_attributes_evidence_to_the_right_side_and_marks_what_is_priced():
    rep = _report(home_missing=[{"name": "H4", "description": "knee"}, {"name": "Stranger", "description": "ill"}])
    f = extract_facts(rep)
    d = D.dossier(f)
    assert set(d) == {"home", "away", "both"}
    assert any(p["tag"] == "[H.form]" and p["priced"] for p in d["home"])                        # home form (2-0 wins) beats away draws
    away_absence = [p for p in d["away"] if "absent" in p["tag"]]                                 # home absentees help the AWAY side
    assert away_absence and any(not p["priced"] for p in away_absence) and any(p["priced"] for p in away_absence)
    assert any(p["tag"] == "[TRAVEL]" and not p["priced"] for p in d["home"])
    order = {"strong": 0, "moderate": 1, "slight": 2}
    assert [order[p["strength"]] for p in d["home"]] == sorted(order[p["strength"]] for p in d["home"])
    text = D.format_dossier(d, "Alpha", "Beta")
    assert "Evidence for Alpha (home)" in text and "NOT priced" in text and "already priced" in text


def test_advocates_are_validated_and_kept_for_display_only():
    tags = {"[H.form]", "[TRAVEL]"}
    adv = D.check_advocates({"home": "Strong run [H.form] and a short trip [TRAVEL].", "away": "They are good, trust me.", "odds_challenge": "Odds ignore [MADE.UP].", "verdict": "odds_overrate_home"}, tags)
    assert adv["home"]["unknown_tags"] == [] and adv["home"]["uncited"] is False
    assert adv["away"]["uncited"] is True and adv["odds_challenge"]["unknown_tags"] == ["[MADE.UP]"] and adv["verdict"] == "odds_overrate_home"
    assert D.check_advocates({"verdict": "bogus", "home": "x"}, tags)["verdict"] == "unclear"
    assert D.check_advocates("nope", tags) is None and D.check_advocates({}, tags) is None


def test_predict_and_brief_include_the_debate_sections_and_advocates_never_move_the_numbers():
    rep = _report()
    base = O.predict(rep, panel="none", sims=8000)
    assert base["dossier"]["home"] and base["advocates"]["home"]["tags"] and "## 3b. Odds challenge and advocates" in O.format_report(base)
    op = {"confidence": 0.5, "factors": [], "advocates": {"home": GOOD_HOME, "away": GOOD_AWAY, "odds_challenge": "Fine [BASELINE].", "verdict": "odds_right"}}
    with_adv = O.predict(rep, panel="none", sims=8000, opinions=[op])
    assert with_adv["prediction"]["lam_home"] == base["prediction"]["lam_home"] and with_adv["prediction"]["lam_away"] == base["prediction"]["lam_away"]
    text = O.format_report(with_adv)
    assert "Home advocate (Alpha)" in text and "Away advocate (Beta)" in text and "Odds challenger" in text and "Verdict on the odds: odds_right" in text
    b = O.brief(rep)
    assert b["challenge"] is not None and b["dossier"]["home"] and "advocates" in b["opinion_format"]
    bt = O.format_brief(b)
    assert "## Odds challenge" in bt and "## Advocate dossier" in bt and "Evidence for Alpha (home)" in bt


# ---------------------------------------------------------------- independent mode (odds are not an input)
@pytest.fixture
def seeded_history(tmp_path, monkeypatch):
    from football import history_model

    path = tmp_path / "m.json"
    path.write_text(json.dumps({"as_of": "2026-09-01", "mu": 0.2, "home_adv": 0.25, "rho": -0.03, "matches_used": 10,
                                "attack": {"Alpha": 0.7, "Beta": -0.5}, "defence": {"Alpha": 0.6, "Beta": -0.4}}), encoding="utf-8")
    monkeypatch.setattr(history_model, "_model_path", lambda: path)
    history_model.load_model.cache_clear()
    yield
    history_model.load_model.cache_clear()


def test_independent_is_the_default_and_odds_are_not_an_input():
    ind = O.predict(_report(), panel="none", sims=10_000)
    withodds = O.predict(_report(), panel="none", sims=10_000, use_odds=True)
    assert ind["mode"] == "independent" and withodds["mode"] == "market-informed"
    assert "market" not in {s["name"] for s in ind["engine"]["sources"]} and "market" in {s["name"] for s in withodds["engine"]["sources"]}
    skewed = _report()
    skewed["match"]["betting_odds"] = {"home_win_fair_pct": 5.0, "draw_fair_pct": 10.0, "away_win_fair_pct": 85.0}
    assert O.predict(skewed, panel="none", sims=10_000)["prediction"]["lam_home"] == ind["prediction"]["lam_home"]       # odds change nothing in independent mode
    assert O.predict(skewed, panel="none", sims=10_000, use_odds=True)["prediction"]["lam_home"] < withodds["prediction"]["lam_home"]


def test_challenge_still_compares_with_the_odds_in_independent_mode():
    rep = _report()
    rep["match"]["betting_odds"] = {"home_win_fair_pct": 10.0, "draw_fair_pct": 20.0, "away_win_fair_pct": 70.0}
    out = O.predict(rep, panel="none", sims=5000)
    assert out["challenge"]["stance"] == "challenge-strong" and out["challenge"]["market"] == [10.0, 20.0, 70.0]
    assert not any(f["code"] == "no_odds" and f["severity"] == "warn" for f in out["audit"]["findings"])       # odds are optional here


def test_history_source_is_used_for_known_national_teams_and_dominates(seeded_history):
    f = extract_facts(_report(odds=False))
    src = {s["name"]: s for s in Q.rate_sources(f, use_market=False)}
    assert "history" in src and src["history"]["weight"] == 25.0
    lh, la, _ = Q.combine_rates(list(src.values()))
    assert abs(lh - src["history"]["lam"][0]) < abs(lh - src["results"]["lam"][0])           # the blend sits near the trained model
    assert not any(x["code"] == "weak_model" for x in O.predict(_report(odds=False), panel="none", sims=3000)["audit"]["findings"])


def test_history_source_follows_the_venue_for_the_home_edge(seeded_history):
    base = Q.rate_sources(extract_facts(_report(odds=False)), use_market=False)
    away_hosts = Q.rate_sources(extract_facts(_report(odds=False, home_team_country="Alpha", away_team_country="Beta", venue_country="Beta")), use_market=False)
    neutral = Q.rate_sources(extract_facts(_report(odds=False, neutral=True)), use_market=False)
    h = lambda srcs: next(s for s in srcs if s["name"] == "history")["lam"]
    # the model puts the home edge on the HOST's goals only: host rate up, the visitor's rate equals its neutral rate
    assert h(base)[0] > h(neutral)[0] and h(away_hosts)[0] == pytest.approx(h(neutral)[0])
    assert h(base)[1] == pytest.approx(h(neutral)[1]) and h(away_hosts)[1] > h(neutral)[1]


def test_weak_model_warning_and_extra_shrink_when_no_trained_model():
    out = O.predict(_report(odds=False), panel="none", sims=5000)         # Alpha/Beta are unknown to the history model
    finding = next(f for f in out["audit"]["findings"] if f["code"] == "weak_model")
    assert finding["severity"] == "warn" and "0.658" in finding["message"]
    assert out["prediction"]["shrink_toward_base_rates"] >= 0.3 * 0.25 - 1e-9


def test_cli_independent_default_and_with_odds_flag(tmp_path, capsys):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(_report()))
    assert O.main(["oracle", str(p), "--llm", "none", "--sims", "3000", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["mode"] == "independent"
    assert O.main(["oracle", str(p), "--llm", "none", "--sims", "3000", "--json", "--with-odds"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["mode"] == "market-informed"
    assert O.main(["oracle", "brief", str(p), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["mode"] == "independent"


def test_history_weight_is_small_when_odds_are_also_an_input(seeded_history):
    f = extract_facts(_report())
    ind = {s["name"]: s["weight"] for s in Q.rate_sources(f, use_market=False)}
    both = {s["name"]: s["weight"] for s in Q.rate_sources(f, use_market=True)}
    assert ind["history"] == 25.0 and both["history"] == Q.HISTORY_WEIGHT_WITH_ODDS == 6.0 and both["market"] == 20.0


def test_knockout_matches_get_the_extra_time_definition_note():
    ko = extract_facts(_report(competition="FIFA World Cup, Knockout stage"))
    assert any(f["code"] == "knockout_definition" and "120 minutes" in f["message"] for f in audit_facts(ko)["findings"])
    assert not any(f["code"] == "knockout_definition" for f in audit_facts(extract_facts(_report(competition="UEFA Nations League, League A")))["findings"])


def test_factors_citing_priced_tags_are_rejected_but_advocates_may_cite_them():
    tags = {"[BASELINE]", "[FIXTURE]", "[H.stakes]"}
    op = {"home_rate_pct": 5, "away_rate_pct": 4, "confidence": 0.8, "factors": [{"effect": "home_rate_pct", "evidence": "[BASELINE]"}, {"effect": "away_rate_pct", "evidence": "[FIXTURE]"}]}
    v = C.validate_opinion(op, tags)
    assert v["adjust"]["home_rate_pct"] == 0.0 and v["adjust"]["away_rate_pct"] == 0.0 and len(v["rejected"]) == 2 and v["factors"] == []
    mixed = {"home_rate_pct": 4, "confidence": 0.8, "factors": [{"effect": "home_rate_pct", "evidence": "[H.stakes], [BASELINE]"}]}
    assert C.validate_opinion(mixed, tags)["adjust"]["home_rate_pct"] == 0.0                  # one priced tag spoils the claim
    ok = {"home_rate_pct": 4, "confidence": 0.8, "factors": [{"effect": "home_rate_pct", "evidence": "[H.stakes]"}]}
    assert C.validate_opinion(ok, tags)["adjust"]["home_rate_pct"] == 4.0
    adv = D.check_advocates({"home": "Squad value x3 [BASELINE], home edge [FIXTURE].", "verdict": "odds_right"}, tags)
    assert adv["home"]["unknown_tags"] == [] and adv["home"]["uncited"] is False                 # explaining priced evidence in an advocate is fine


def test_absence_tag_is_accepted_but_a_number_needs_a_factor_with_the_same_effect():
    rep = _report(home_missing=[{"name": "H1"}])
    tags = C.build_brief(extract_facts(rep), {"lam_home": 1.4, "lam_away": 1.0, "home": 0.45, "draw": 0.27, "away": 0.28}, "independent")[1]
    assert "[H.absent.H1]" in tags
    ok = C.validate_opinion({"home_rate_pct": -2, "confidence": 0.6, "factors": [{"effect": "home_rate_pct", "evidence": "[H.absent.H1]", "note": "x"}]}, tags)
    assert ok["adjust"]["home_rate_pct"] == -2 and not ok["rejected"]
    wrong = C.validate_opinion({"away_rate_pct": -2, "confidence": 0.6, "factors": [{"effect": "home_rate_pct", "evidence": "[H.absent.H1]", "note": "x"}]}, tags)
    assert wrong["adjust"]["away_rate_pct"] == 0.0


def test_norm_folds_letters_that_accent_stripping_misses():
    assert norm("Kenan Yıldız") == norm("Kenan Yildiz") and norm("Łukasz") == norm("Lukasz") and norm("Mørk") == norm("Mork") and norm("Doğan") == norm("Dogan")


def test_fringe_or_unknown_absentees_cannot_justify_an_adjustment():
    rep = _report(home_missing=[{"name": "H1"}, {"name": "Nobody"}])
    rep["teamProfile"]["squad"][1]["recent_usage"]["total_minutes"] = 20            # H1 becomes a fringe player
    rep["teamProfile"]["squad"][2]["recent_usage"]["total_minutes"] = 450           # H2 stays a starter
    rep["match"]["home_missing_players"].append({"name": "H2"})
    facts = extract_facts(rep)
    tags = C.build_brief(facts, {"lam_home": 1.4, "lam_away": 1.0, "home": 0.45, "draw": 0.27, "away": 0.28}, "independent")[1]
    assert C.weak_absence_tags(facts) == {"[H.absent.H1]", "[H.absent.Nobody]"}
    def op(tag):
        return {"home_rate_pct": -2, "confidence": 0.6, "factors": [{"effect": "home_rate_pct", "evidence": tag, "note": "x"}]}
    weak = C.weak_absence_tags(facts)
    for tag in ("[H.absent.H1]", "[H.absent.Nobody]"):
        v = C.validate_opinion(op(tag), tags, weak)
        assert v["adjust"]["home_rate_pct"] == 0.0 and v["rejected"]
    assert C.validate_opinion(op("[H.absent.H2]"), tags, weak)["adjust"]["home_rate_pct"] == -2
    out = O.predict(rep, panel="none", opinions=[op("[H.absent.Nobody]")], opinion_trust=1)
    assert out["panel"]["adjust"]["home_rate_pct"] == 0.0


def test_table_has_one_row_per_match_with_pick_flag_and_findings(tmp_path, capsys):
    for i, name in enumerate(("Alpha", "Gamma")):
        rep = _report(odds=False)
        rep["match"]["home_team"] = name
        (tmp_path / f"r{i}.json").write_text(json.dumps(rep))
    assert O.main(["oracle", str(tmp_path), "--llm", "none", "--table"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out[0].startswith("| # | Match") and len(out) == 4 and "Alpha v Beta" in out[2] and "Gamma v Beta" in out[3]
    assert all(row.count("|") == out[0].count("|") for row in out)


def test_lint_reports_rejections_ignored_numbers_and_advocate_problems(tmp_path, capsys):
    from football.oracle import lint
    rep = _report(home_missing=[{"name": "H1"}, {"name": "Nobody"}], lineup_confirmed=False)
    rep["teamProfile"]["squad"][1]["recent_usage"]["total_minutes"] = 450
    op = {"home_rate_pct": -2, "away_rate_pct": 20, "draw_bias_pct": 2, "confidence": 0.6,
          "factors": [{"effect": "home_rate_pct", "evidence": "[H.absent.Nobody]", "note": "x"}, {"effect": "away_rate_pct", "evidence": "[TRAVEL]", "note": "x"},
                      {"effect": "draw_bias_pct", "evidence": "[BASELINE]", "note": "x"}, {"effect": "bogus", "evidence": "[H2H]", "note": "x"}],
          "advocates": {"home": "no tags here", "away": "see [NOPE]", "verdict": "maybe"}}
    r = lint.lint_opinion(rep, op)
    status = [f["status"] for f in r["factors"]]
    assert "unknown-role" in status[0] and status[1] == "accepted" and "already priced" in status[2] and "unknown effect" in status[3]
    notes = {n["effect"]: n["note"] for n in r["numbers"]}
    assert "SAME effect" in notes["home_rate_pct"] and notes["away_rate_pct"].startswith("clamped") and "SAME effect" in notes["draw_bias_pct"]
    text = " ".join(r["advocate_problems"])
    assert "'home' cites no" in text and "unknown tags: [NOPE]" in text and "'odds_challenge' is missing" in text and "data_gaps" in text and not r["clean"]
    p1, p2 = tmp_path / "r.json", tmp_path / "o.json"
    p1.write_text(json.dumps(rep)); p2.write_text(json.dumps(op))
    assert O.main(["oracle", "lint", str(p1), str(p2)]) == 0
    assert "## Factors" in capsys.readouterr().out and O.main(["oracle", "lint", str(p1)]) == 2


GOOD_HOME = ("Form [H.form] and the venue [FIXTURE] give the home side the better start and they lead on strength [BASELINE]; the visitors travel far [TRAVEL]. "
             "The head to head [H2H] is thin so we concede that unconfirmed lineups still matter.")
GOOD_AWAY = "The visitors have little tagged support here, so the case is thin: only the table [H.table] helps them, and that is already reflected in the strength numbers."


def test_lint_is_clean_for_the_skill_example_shaped_opinion():
    from football.oracle import lint
    rep = _report()
    rep["insights"]["away_rotation"] = {"changed_players": 6, "starting_xi_size": 11}
    op = {"home_rate_pct": 0, "away_rate_pct": -2, "draw_bias_pct": 0, "confidence": 0.3,
          "factors": [{"effect": "away_rate_pct", "evidence": "[A.rotation]", "note": "x"}],
          "advocates": {"home": GOOD_HOME, "away": GOOD_AWAY, "odds_challenge": "Priced [BASELINE].", "verdict": "odds_right"}, "data_gaps": []}
    assert lint.lint_opinion(rep, op)["clean"] is True


def test_lint_hints_when_a_factor_has_a_zero_number():
    from football.oracle import lint
    rep = _report(home_missing=[{"name": "H1"}])
    op = {"home_rate_pct": 0, "confidence": 0.3, "factors": [{"effect": "home_rate_pct", "evidence": "[H.absent.H1]", "note": "x"}],
          "advocates": {"home": GOOD_HOME, "away": GOOD_AWAY, "odds_challenge": "[BASELINE]", "verdict": "odds_right"}, "data_gaps": []}
    r = lint.lint_opinion(rep, op)
    assert next(n for n in r["numbers"] if n["effect"] == "home_rate_pct")["note"].startswith("hint:") and r["clean"] is True


def _answer(pred, extra_case_home="", extra_case_away="", draw_level=None):
    """The draft for the most recently built _report(), placeholders filled, with the Case line the older tests expect."""
    from football.oracle import draft as _dr
    text = re.sub(r"\[WRITE: [^\]]*\]", "Priced in already.", _dr.draft_answer(_LAST["rep"]))
    out = []
    for ln in text.split("\n"):
        if ln.startswith("Case for "):
            ln = f"Case for Alpha: strong form [H.form]{extra_case_home}, but unconfirmed lineups remain a risk      Case for Beta: table [H.table]{extra_case_away}, although the visitors lack form"
        if draw_level and ln.startswith("Draw: "):
            ln = re.sub(r"^Draw: (ALERT|WATCH|no alert)", f"Draw: {draw_level}", ln)
        out.append(ln)
    return "\n".join(out) + "\n"


def test_answer_audit_passes_a_faithful_answer_and_catches_each_kind_of_error():
    from football.oracle import audit_answer as AA
    rep = _report(home_missing=[{"name": "H1"}], odds=False)
    pred = O.predict(rep, panel="none")["prediction"]
    assert AA.audit_answer(rep, _answer(pred))["clean"] is True
    def failed(text):
        return [n for n, ok, _ in AA.audit_answer(rep, text)["rows"] if not ok]
    assert "headline H/D/A equals the engine's final numbers" in failed(_answer(pred).replace(str(pred["home_win_pct"]), "99.9", 1))
    assert "every [TAG] exists in the brief" in failed(_answer(pred, extra_case_home=" [NOPE]"))
    assert "no side's own absence inside its own Case line" in failed(_answer(pred, extra_case_home=" [H.absent.H1]"))
    assert "no banned claims" in failed(_answer(pred) + "Varga is priced into Elo.")
    assert "draw level matches the engine" in failed(_answer(pred, draw_level="ALERT" if pred["draw"]["alert"] != "alert" else "no alert"))
    assert "all deliverable lines present" in failed(re.sub(r"Weak points:[^\n]*\n", "", _answer(pred)))


def test_audit_cli(tmp_path, capsys):
    rep = _report(odds=False)
    pred = O.predict(rep, panel="none")["prediction"]
    (tmp_path / "r.json").write_text(json.dumps(rep)); (tmp_path / "a.md").write_text(_answer(pred))
    assert O.main(["oracle", "audit", str(tmp_path / "r.json"), str(tmp_path / "a.md")]) == 0
    assert "Result: clean" in capsys.readouterr().out and O.main(["oracle", "audit", str(tmp_path / "r.json")]) == 2


def test_answer_audit_checks_scorelines_characterisations_and_h2h_record():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False)
    pred = O.predict(rep, panel="none")["prediction"]
    base = _answer(pred)
    def run(extra):
        r = AA.audit_answer(rep, base + extra)
        return [n for n, ok, _ in r["rows"] if not ok], r["warnings"]
    assert run("Alpha beat X 2-0 vs X earlier.")[0] == []                       # real: form rows are 2-0 W vs X (home) and 1-1 D (away)
    assert run("Beta drew 1-1 vs X.")[0] == []
    assert run("Alpha lost 4-3 vs X.")[0] == ["scorelines quoted against opponents exist in the form data"]
    assert run("Alpha won 3-0 vs Nobody.")[0] == ["scorelines quoted against opponents exist in the form data"]
    fails, warns = run("A 2-2 draw in Austria.")
    assert fails == [] and any("Austria" in w for w in warns)
    assert any("resilient" in w for w in run("A resilient side.")[1]) and run("A plain side.")[1] == []
    assert any("head-to-head" in w for w in run("Record 2 wins [H2H].")[1]) and run("Record 2 wins in 4 meetings [H2H].")[1] == []


def test_answer_audit_flags_unpriced_absences_and_new_characterisations():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False)
    pred = O.predict(rep, panel="none")["prediction"]
    def run(extra):
        r = AA.audit_answer(rep, _answer(pred) + extra)
        return [n for n, ok, _ in r["rows"] if not ok], r["warnings"]
    assert run("Varga's absence is the key unpriced factor.")[0] == ["no banned claims"]
    assert run("An unpriced loss for the forward.")[0] == ["no banned claims"]
    assert run("Travel is an unpriced edge.")[0] == []
    assert any("intact" in w for w in run("The spine is intact.")[1]) and any("cautious" in w for w in run("A cautious approach.")[1])


def test_answer_audit_flags_invented_managers_and_missing_players():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False, home_missing=[{"name": "H1"}])
    rep["match"]["home_manager"] = {"name": "Pat Smith"}
    pred = O.predict(rep, panel="none")["prediction"]
    def warns(extra):
        return AA.audit_answer(rep, _answer(pred) + extra)["warnings"]
    assert warns("Strong under Pat Smith.") == [] and warns("Alpha without H1 today.") == []
    assert any("Xavi" in w for w in warns("Beta play under Xavi."))
    assert any("Pat Smith" not in w and "named as missing" in w for w in warns("Alpha without Mo Salah today."))
    assert warns("Alpha without Beta fans.") == []


def test_lint_questions_a_draw_adjustment_without_draw_specific_evidence():
    from football.oracle import lint
    rep = _report(odds=False)
    def op(tag):
        return {"home_rate_pct": 0, "draw_bias_pct": 1, "confidence": 0.5, "factors": [{"effect": "draw_bias_pct", "evidence": tag, "note": "x"}],
                "advocates": {"home": GOOD_HOME, "away": GOOD_AWAY, "odds_challenge": "[H2H]", "verdict": "unclear"}, "data_gaps": []}
    assert any("draw adjustment cites [TRAVEL]" in p for p in lint.lint_opinion(rep, op("[TRAVEL]"))["advocate_problems"])
    assert not any("draw adjustment" in p for p in lint.lint_opinion(rep, op("[H.stakes]"))["advocate_problems"])


def test_answer_audit_ignores_possessive_team_names_after_missing_words():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False)
    pred = O.predict(rep, panel="none")["prediction"]
    assert AA.audit_answer(rep, _answer(pred) + "Alpha has the absence of Beta's travel plans.")["warnings"] == []


def test_answer_audit_finds_the_headline_below_a_title_line():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False)
    pred = O.predict(rep, panel="none")["prediction"]
    assert AA.audit_answer(rep, "# Alpha vs Beta\n\n" + _answer(pred))["clean"] is True


def test_answer_audit_checks_form_counts_starters_out_and_unsupported_explanations():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False, home_missing=[{"name": "H1"}, {"name": "Nobody"}])
    pred = O.predict(rep, panel="none")["prediction"]
    def run(extra):
        r = AA.audit_answer(rep, _answer(pred) + extra)
        return [n for n, ok, _ in r["rows"] if not ok], r["warnings"]
    # fixture form: home = six wins (W), away = six draws (D)
    assert run("Alpha won 6 of their last 6.")[0] == [] and run("6 of the last 6 draws.")[0] == []
    assert run("Alpha won 4 of the last 6.")[0] == ["recent-form counts quoted match the form data"]
    assert run("Alpha took 5 of the last 6 wins.")[0] == ["recent-form counts quoted match the form data"]
    assert run("Beta has 3 wins in their last 6.")[0] == ["recent-form counts quoted match the form data"]
    assert run("Beta has 6 draws in their last 6.")[0] == []
    assert any("nobody" in w and "starters out" in w for w in run("Alpha starters out: Nobody (unknown role).")[1])
    assert not any("starters out" in w for w in run("Alpha starters out: H1.")[1])
    assert any("explained by" in w for w in run("The gap is explained by home-bias in Elo.")[1]) and not any("explained by" in w for w in run("The gap is explained by 2.1 xG per game [H.form].")[1])


def test_answer_audit_flags_spin_words():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False)
    pred = O.predict(rep, panel="none")["prediction"]
    w = AA.audit_answer(rep, _answer(pred) + "Real and substantial edge, vastly better, tactical flexibility, overwhelming quality.")["warnings"]
    assert {"substantial", "vastly", "flexibility", "overwhelming"} <= {x.split("'")[1] for x in w}


def test_answer_audit_explains_combined_tags():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False)
    pred = O.predict(rep, panel="none")["prediction"]
    r = AA.audit_answer(rep, _answer(pred) + "Form [H.form, H.table].")
    detail = next(d for n, ok, d in r["rows"] if n == "every [TAG] exists in the brief")
    assert "one tag per bracket" in detail and "[H.form] [H.table]" in detail


def test_every_match_gets_a_recommended_bet_and_it_is_the_most_likely_eligible_selection():
    for kw in ({}, {"odds": False}, {"home_missing": [{"name": "H1"}]}):
        pred = O.predict(_report(**kw), panel="none")["prediction"]
        rec = pred["recommendation"]
        mk = pred["simulation"]["markets_pct"]
        h, d, a = pred["home_win_pct"], pred["draw_pct"], pred["away_win_pct"]
        pool = [max(h, d, a)] + [x for x in (mk["over_2_5"], 100 - mk["over_2_5"], mk["btts"], 100 - mk["btts"]) if x >= O.GOALS_BET_MIN_PCT] + ([max(h + d, d + a, h + a)] if max(h, d, a) < O.DOUBLE_CHANCE_BELOW_PCT else [])
        assert rec["probability_pct"] == pytest.approx(max(pool), abs=0.15) and rec["selection"] and rec["strength"] in ("lean", "moderate", "strong", "very strong")
        assert rec["market"] in ("1X2", "Double chance") or rec["probability_pct"] >= O.GOALS_BET_MIN_PCT      # a goals bet below 60% is never the recommendation
        assert rec["alternatives"] and all(x["probability_pct"] <= rec["probability_pct"] + 1e-9 for x in rec["alternatives"] if x["market"] != "Double chance")
        assert rec["observed_hit_pct"] == O.observed_hit_for(rec["probability_pct"], rec["market"]) and rec["market_hit_pct"] == O.OBSERVED_HIT_PCT[rec["market"]]


def test_recommend_picks_each_market_when_it_is_the_most_likely_and_caps_a_weak_model():
    m = {"over_2_5": 0.30, "btts": 0.40}
    assert O.recommend("A", "B", [0.40, 0.30, 0.30], m)["selection"] == "Under 2.5 goals"            # 70% beats 40% and 60%
    assert O.recommend("A", "B", [0.80, 0.12, 0.08], m)["selection"] == "A to win"                  # 80% beats 70%
    assert O.recommend("A", "B", [0.40, 0.30, 0.30], {"over_2_5": 0.55, "btts": 0.20})["selection"] == "Both teams to score: No"
    assert O.recommend("A", "B", [0.40, 0.30, 0.30], {"over_2_5": 0.80, "btts": 0.60})["selection"] == "Over 2.5 goals"
    assert O.recommend("A", "B", [0.20, 0.20, 0.60], {"over_2_5": 0.5, "btts": 0.5})["selection"] == "B to win"
    assert O.recommend("A", "B", [0.9, 0.05, 0.05], m)["strength"] == "very strong" and O.recommend("A", "B", [0.9, 0.05, 0.05], m, weak_model=True)["strength"] == "lean"


def test_recommendation_is_in_the_report_and_the_table_and_audited(tmp_path, capsys):
    from football.oracle import audit_answer as AA
    rep = _report(odds=False)
    r = O.predict(rep, panel="none")
    assert "**Recommended bet:" in O.format_report(r)
    p = tmp_path / "r.json"; p.write_text(json.dumps(rep))
    assert O.main(["oracle", str(p), "--llm", "none", "--table"]) == 0
    out = capsys.readouterr().out
    assert "| Recommended bet |" in out and r["prediction"]["recommendation"]["selection"] in out
    pred = r["prediction"]; ans = _answer(pred)
    assert AA.audit_answer(rep, ans)["clean"] is True
    wrong = ans.replace(pred["recommendation"]["selection"], "Something else")
    assert "recommended bet equals the engine's (selection and probability)" in [n for n, ok, _ in AA.audit_answer(rep, wrong)["rows"] if not ok]
    assert "all deliverable lines present" in [n for n, ok, _ in AA.audit_answer(rep, ans.replace("Recommended bet:", "Pick:"))["rows"] if not ok]


def test_answer_audit_checks_point_gap_comparisons():
    from football.oracle import audit_answer as AA
    rep = _report()   # has odds 55/25/20
    pred = O.predict(rep, panel="none")["prediction"]
    odds_home = 55.0
    gap = abs(pred["home_win_pct"] - odds_home)
    def warns(extra):
        return [w for w in AA.audit_answer(rep, _answer(pred) + extra)["warnings"] if "points" in w and "no gap" in w]
    assert warns(f"The model is {gap:.1f} points below the odds on the home side.") == []
    assert warns(f"The model is {round(gap)} points below the odds.") == []
    assert len(warns("The model favours home by 19 points over the odds.")) == 1
    assert warns("Home and away within 5 points of each other, worth at most 3 points.") == []
    assert warns("A key absentee is worth 2-3 points.") == []


def test_point_gap_check_ignores_league_points():
    from football.oracle import audit_answer as AA
    rep = _report()
    pred = O.predict(rep, panel="none")["prediction"]
    for extra in ("Slovakia 2.0 pts/game vs 1.3.", "Sits second with 3 pts from 2 games.", "Level at 4 points each.", "Six points clear at the top.", "Three points from safety, 9 points per game."):
        assert not [w for w in AA.audit_answer(rep, _answer(pred) + extra)["warnings"] if "no gap" in w]
    assert [w for w in AA.audit_answer(rep, _answer(pred) + "Model is 19 points above the odds.")["warnings"] if "no gap" in w]


def test_case_line_check_only_reads_the_case_line_not_later_lines():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False, home_missing=[{"name": "H1"}])
    pred = O.predict(rep, panel="none")["prediction"]
    ok = _answer(pred) + "Weak points: Alpha miss [H.absent.H1]; Beta miss [A.absent.A1].\nLineups: [H.absent.H1] [A.absent.A1]\n"
    assert "no side's own absence inside its own Case line" not in [n for n, v, _ in AA.audit_answer(rep, ok)["rows"] if not v]
    bad = _answer(pred).replace("table [H.table]", "table [H.table] [A.absent.A1]")
    assert "no side's own absence inside its own Case line" in [n for n, v, _ in AA.audit_answer(rep, bad)["rows"] if not v]


def test_goal_market_shrink_moves_the_total_toward_the_mean_and_leaves_1x2_alone():
    lh, la = Q.shrink_total_goals(0.8, 1.0)                       # total 1.8 is below the 2.676 mean: it rises
    assert lh + la == pytest.approx(1.8 + Q.TOTAL_SHRINK * (Q.MEAN_TOTAL_GOALS - 1.8)) and lh / la == pytest.approx(0.8)
    hi = Q.shrink_total_goals(2.5, 2.0)
    assert hi[0] + hi[1] < 4.5 and hi[0] / hi[1] == pytest.approx(1.25)
    assert Q.shrink_total_goals(1.338, 1.338) == pytest.approx((1.338, 1.338), abs=1e-3)   # at the mean nothing moves
    assert Q.shrink_total_goals(0.0, 0.0) == (0.0, 0.0)
    rep = _report(odds=False)
    pred = O.predict(rep, panel="none")["prediction"]
    raw = Q.exact_distribution(pred["lam_home"], pred["lam_away"])
    assert pred["home_win_pct"] > 0 and abs(pred["draw"]["draw_pct"] - pred["draw_pct"]) < 1e-9
    assert pred["simulation"]["markets_pct"]["over_2_5"] != round(100 * raw["markets"]["over_2_5"], 1) or abs(pred["lam_home"] + pred["lam_away"] - Q.MEAN_TOTAL_GOALS) < 0.05
    assert O.OBSERVED_HIT_PCT["Under 2.5"] == 61.2
    assert [O.observed_hit_for(x, "Under 2.5") for x in (50, 59.9, 62, 68, 72, 78, 85, 95)] == [56.7, 56.7, 59.8, 65.0, 65.9, 76.2, 81.2, 81.2]      # goal bets flatten: 70-75% quoted wins 66%
    assert [O.observed_hit_for(x, "Double chance") for x in (60, 68, 72, 78, 85)] == [64.8, 64.8, 73.2, 78.7, 86.5]
    assert O.observed_hit_for(68.4, "1X2") == O.observed_hit_for(68.4) and O.observed_hit_for(55.5, "1X2") < O.observed_hit_for(55.5, "BTTS Yes") + 5


def test_draft_fills_every_number_so_only_the_placeholders_fail_the_audit(tmp_path, capsys):
    import re
    from football.oracle import audit_answer as AA, draft as DR
    for kw in ({}, {"odds": False}, {"home_missing": [{"name": "H1"}, {"name": "Nobody"}], "lineup_confirmed": False}):
        rep = _report(**kw)
        text = DR.draft_answer(rep)
        r = AA.audit_answer(rep, text)
        failed = [n for n, ok, _ in r["rows"] if not ok]
        assert failed == ["no unfilled [WRITE ...] placeholders left from the draft"], failed
        filled = re.sub(r"\[WRITE: [^\]]*\]", "Priced in already.", text)
        r2 = AA.audit_answer(rep, filled)
        assert r2["clean"] is True, [x for x in r2["rows"] if not x[1]]
    p = tmp_path / "r.json"; p.write_text(json.dumps(_report()))
    assert O.main(["oracle", "draft", str(p)]) == 0
    assert "Recommended bet:" in capsys.readouterr().out and O.main(["oracle", "draft"]) == 2


def test_draft_follows_the_opinion_numbers():
    from football.oracle import draft as DR
    rep = _report(odds=False)
    op = {"home_rate_pct": 5, "confidence": 0.9, "factors": [{"effect": "home_rate_pct", "evidence": "[H.form]", "note": "x"}]}
    base = O.predict(rep, panel="none")["prediction"]; adj = O.predict(rep, panel="none", opinions=[op])["prediction"]
    assert f"{adj['home_win_pct']}%" in DR.draft_answer(rep, op) and adj["home_win_pct"] != base["home_win_pct"]


def test_h2h_warning_only_when_no_citation_quotes_the_full_record():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False)    # h2h tag: home 2, draws 1, away 1 (n=4)
    pred = O.predict(rep, panel="none")["prediction"]
    def warns(extra):
        return [w for w in AA.audit_answer(rep, _answer(pred) + extra)["warnings"] if "head-to-head" in w]
    assert len(warns("Record 2 wins [H2H].")) == 1
    assert warns("Record: home 2, draws 1, away 1 (n=4) [H2H]. Later no unpriced evidence [H2H] overrides this.") == []


def test_cautions_list_unconfirmed_lineups_unknown_absentees_rotation_and_quality():
    rep = _report(odds=False, home_missing=[{"name": "Nobody"}, {"name": "Ghost"}], lineup_confirmed=False)
    rep["insights"]["home_rotation"] = {"changed_players": 9, "starting_xi_size": 11}
    rec = O.predict(rep, panel="none")["prediction"]["recommendation"]
    text = " | ".join(rec["cautions"])
    assert "lineups unconfirmed" in text and "2 absentees are not in the squad list" in text and "changed 9 starters" in text
    clean = O.predict(_report(odds=False), panel="none")["prediction"]["recommendation"]["cautions"]
    assert not any("lineups unconfirmed" in c or "absentees" in c for c in clean)


def test_plain_words_line_is_simple_and_follows_the_numbers():
    from football.oracle import draft as DR
    p = {"home_win_pct": 68.4, "away_win_pct": 11.6, "draw_pct": 20.1, "draw": {"alert": "none"},
         "recommendation": {"selection": "Spain to win", "probability_pct": 68.4, "strength": "moderate", "observed_hit_pct": 76.8, "weak_model": False, "cautions": ["lineups unconfirmed: re-run once they are"]}}
    t = DR.plain_words("Spain", "Croatia", p)
    assert t.startswith("Spain are the clear favourites (68% to win).") and "A draw is 20% likely." in t and "Best bet: Spain to win (68% chance, moderate)" in t and "won about 77 in 100" in t and t.endswith("Be careful: lineups unconfirmed: re-run once they are.")
    p2 = {**p, "home_win_pct": 35.0, "away_win_pct": 33.0, "draw_pct": 31.0, "draw": {"alert": "alert"}, "recommendation": {**p["recommendation"], "cautions": []}}
    t2 = DR.plain_words("A", "B", p2)
    assert "toss-up" in t2 or "slight favourites" not in t2
    assert "A draw is a real risk (31%)." in t2 and "Be careful" not in t2
    assert "slight favourites (48% to win)" in DR.plain_words("A", "B", {**p, "home_win_pct": 48.0, "away_win_pct": 20.0})
    assert "Draw" not in DR.plain_words("A", "B", p)          # a capital Draw would be mistaken for the headline by the audit


def test_scorecard_matches_results_labels_misses_and_counts_draws(tmp_path, capsys):
    from football.oracle import scorecard as SC
    reps = []
    for i, (name, ) in enumerate((("Alpha",), ("Gamma",), ("Delta",))):
        rep = _report(odds=(i != 2))
        rep["match"]["home_team"] = name
        rep["match"]["away_team"] = "Beta"
        reps.append(rep)
        (tmp_path / f"r{i}.json").write_text(json.dumps(rep))
    csv = tmp_path / "res.csv"
    csv.write_text("date,home_team,away_team,home_score,away_score\n2026-10-03,Alpha,Beta,3,0\n2026-10-03,Gamma,Beta,1,1\n2026-10-03,Delta,Beta,0,2\n2026-10-03,Nobody,Beta,1,0\n")
    assert O.main(["oracle", "score", str(tmp_path), "--results", str(csv)]) == 0
    out = capsys.readouterr().out
    assert "# Scorecard: 3 settled matches" in out and "## Misses" in out and "| Draws | 1 actual" in out
    assert O.main(["oracle", "score", str(tmp_path)]) == 2
    assert SC.bet_hit("Alpha to win", "Alpha", "Beta", 2, 0) and not SC.bet_hit("Beta to win", "Alpha", "Beta", 2, 0) and SC.bet_hit("Draw", "A", "B", 1, 1)
    assert SC.bet_hit("Under 2.5 goals", "A", "B", 1, 1) and not SC.bet_hit("Under 2.5 goals", "A", "B", 2, 1) and SC.bet_hit("Both teams to score: No", "A", "B", 2, 0)
    rec = {"market": "BTTS Yes"}
    assert SC.why_missed(rec, "A", "B", 2, 0) == "B did not score" and SC.why_missed(rec, "A", "B", 0, 0) == "nobody scored"
    assert SC.why_missed({"market": "1X2"}, "A", "B", 1, 1) == "draw" and SC.why_missed({"market": "1X2"}, "A", "B", 0, 1) == "upset: B won"
    assert SC.why_missed({"market": "Under 2.5"}, "A", "B", 2, 2) == "4 goals" and SC.why_missed({"market": "Over 2.5"}, "A", "B", 1, 0) == "only 1 goal" and SC.why_missed({"market": "Over 2.5"}, "A", "B", 1, 1) == "only 2 goals"
    assert "No settled matches" in SC.format_scorecard({"rows": []})


def test_an_empty_or_fixtureless_report_gives_an_audit_error_not_a_crash(tmp_path, capsys):
    from football.oracle import audit_answer as AA, draft as DR, lint as LT, scorecard as SC
    for rep in ({}, {"match": {}}, {"match": {"home_team": None, "away_team": None}}):
        r = O.predict(rep, panel="none")
        assert r["prediction"] is None and any(f["code"] == "no_fixture" for f in r["audit"]["findings"])
        assert O.brief(rep)["brief"] is None
        assert DR.draft_answer(rep).startswith("No prediction")
        assert AA.audit_answer(rep, "anything")["clean"] is False
        assert "No prediction" in O.format_report(r)
        assert SC.score_reports([rep], [])["rows"] == []
    p = tmp_path / "empty.json"; p.write_text("{}")
    assert O.main(["oracle", str(p), "--llm", "none"]) == 0 and O.main(["oracle", "brief", str(p)]) == 0 and O.main(["oracle", str(p), "--llm", "none", "--table"]) == 0
    assert O.main(["oracle", "draft", str(p)]) == 0


def test_non_object_opinions_and_junk_logs_do_not_crash(tmp_path, capsys, monkeypatch):
    from football.oracle import forward_log as FL, lint as LT
    rep = _report(odds=False)
    base = O.predict(rep, panel="none")["prediction"]
    for bad in ([], "text", 5, None, [1, 2], {"factors": "x"}, {"factors": [None, 3, {"effect": None}]}, {"home_rate_pct": "abc", "confidence": "high"}):
        v = C.validate_opinion(bad, {"[H.form]"})
        assert v["adjust"] == {"home_rate_pct": 0.0, "away_rate_pct": 0.0, "draw_bias_pct": 0.0}
        assert O.predict(rep, panel="none", opinions=[bad])["prediction"]["home_win_pct"] == base["home_win_pct"]
        assert LT.lint_opinion(rep, bad)["numbers"]
    p = tmp_path / "r.json"; p.write_text(json.dumps(rep)); o = tmp_path / "o.json"; o.write_text("[1, 2]")
    assert O.main(["oracle", str(p), "--llm", "none", "--opinion-file", str(o)]) == 2
    assert "must be a JSON object" in capsys.readouterr().err
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / FL.LOG_NAME).write_text('not json\n{"home_team": "A"}\n[1]\n"x"\n' + json.dumps({"home_team": "Home1", "away_team": "Away1", "kickoff_utc": "2026-10-03T18:00:00Z", "generated_at": "2026-10-01T00:00:00Z", "off": [.4, .3, .3], "on": [.5, .25, .25]}) + "\n")
    assert len(FL.load()) == 1
    csv = tmp_path / "r.csv"; csv.write_text("date,home_team,away_team,home_score,away_score\n2026-10-03,Home1,Away1,1,0\n")
    assert FL.main(["x", "score", str(csv)]) == 0


def test_the_odds_never_change_a_bet_its_strength_its_cautions_or_any_probability():
    """The user's rule: the model is independent. The same report with and without odds, or with wildly different odds, gives the same forecast and bet."""
    base = _report(odds=False)
    variants = [_report(odds=False), _report(odds=True)]
    wild = _report(odds=True)
    wild["match"]["betting_odds"] = {"home_win_fair_pct": 5.0, "draw_fair_pct": 10.0, "away_win_fair_pct": 85.0, "over_2_5_fair_pct": 90.0, "under_2_5_fair_pct": 10.0}
    variants.append(wild)
    keys = ("home_win_pct", "draw_pct", "away_win_pct", "pick", "lam_home", "lam_away", "confidence_pct")
    ref = O.predict(base, panel="none")["prediction"]
    for rep in variants:
        got = O.predict(rep, panel="none")["prediction"]
        assert {k: got[k] for k in keys} == {k: ref[k] for k in keys}
        for field in ("market", "selection", "probability_pct", "strength", "observed_hit_pct", "cautions", "alternatives"):
            assert got["recommendation"][field] == ref["recommendation"][field], field
        assert got["simulation"]["markets_pct"] == ref["simulation"]["markets_pct"] and got["draw"] == ref["draw"]
    assert ref["recommendation"]["odds_gap"] is None and O.predict(wild, panel="none")["prediction"]["recommendation"]["odds_gap"]["gap_pct"] != 0


def test_recommend_reports_the_gap_to_the_odds_as_a_benchmark_only():
    m = {"over_2_5": 0.3, "btts": 0.45}
    plain = O.recommend("A", "B", [0.28, 0.33, 0.39], m)
    with_odds = O.recommend("A", "B", [0.28, 0.33, 0.39], m, odds={"home": 0.14, "draw": 0.28, "away": 0.58})
    assert with_odds["odds_gap"]["outcome"] == "B win" and with_odds["odds_gap"]["gap_pct"] == pytest.approx(-19.0)
    for field in ("market", "selection", "probability_pct", "strength", "cautions"):
        assert with_odds[field] == plain[field]
    assert "odds_check" not in with_odds and not any("odds" in c for c in with_odds["cautions"])
    rep = _report()
    rep["match"]["betting_odds"] = {"home_win_fair_pct": 10.0, "draw_fair_pct": 20.0, "away_win_fair_pct": 70.0, "over_2_5_fair_pct": 50.0, "under_2_5_fair_pct": 50.0}
    text = O.format_report(O.predict(rep, panel="none"))
    assert "Benchmark only (odds are not an input" in text


def test_point_gap_check_catches_hyphenated_claims_but_not_league_points():
    from football.oracle import audit_answer as AA
    rep = _report()
    pred = O.predict(rep, panel="none")["prediction"]
    def gaps(extra):
        return [w for w in AA.audit_answer(rep, _answer(pred) + extra)["warnings"] if "no gap" in w]
    assert len(gaps("The 50-point odds gap is extreme.")) == 1 and len(gaps("A 47 point gap to the odds.")) == 1
    for ok in ("Norway hold 3 points in the group while Wales have none.", "Level on 4 points in the league.", "Six points on the board."):
        assert gaps(ok) == [], ok


def test_form_adjectives_are_checked_against_the_form_letters():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False)          # fixture form: home six wins (W), away six draws (D)
    pred = O.predict(rep, panel="none")["prediction"]
    def warns(extra):
        return [w for w in AA.audit_answer(rep, _answer(pred) + extra)["warnings"] if "say what the numbers show" in w]
    assert warns("Alpha have strong recent form [H.form].") == [] and warns("Beta have poor form [A.form].") == []     # 6 wins is strong; six draws is not poor
    assert len(warns("Beta have strong recent form [A.form].")) == 1                                              # six draws, no wins
    assert len(warns("Alpha are in poor form [H.form].")) == 1                                                     # six wins is not poor
    assert warns("Alpha have better form than Beta [H.form] [A.form].") == []                                     # comparison sentences are skipped
    assert warns("Beta have strong squad value [BASELINE].") == []


def test_audit_requires_the_draft_lines_to_be_kept_as_drafted():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False, lineup_confirmed=False)
    pred = O.predict(rep, panel="none")["prediction"]
    good = _answer(pred)
    ROW = "the lines the draft filled from the engine are kept as drafted"
    def row(text):
        r = next(x for x in AA.audit_answer(rep, text)["rows"] if x[0] == ROW)
        return r[1], r[2]
    assert row(good)[0] is True
    assert row("- " + good.replace("**", "", 2).replace("\n", "\n- "))[0] is True           # bullets and bold markers are decoration, not a change
    lines = good.split("\n")
    def swap(prefix, new):
        return "\n".join(new if ln.startswith(prefix) else ln for ln in lines)
    ok, why = row(swap("In plain words:", "In plain words: Alpha will crush them."))
    assert not ok and "In plain words:" in why and "changed" in why
    ok, why = row(swap("Recommended bet:", "Recommended bet: Alpha to win - 99%"))
    assert not ok and "Recommended bet:" in why
    cut = good.replace(". Cautions: lineups unconfirmed: re-run once they are", "")
    assert cut != good and not row(cut)[0]                                                                  # dropping a caution changes the bet line
    assert not row(good.replace("Goals: expected", "Goals: roughly"))[0] and not row("\n".join(ln for ln in lines if not ln.startswith("Lineups:")))[0]
    assert row(good.replace("Lineups: guessed (unconfirmed);", "Lineups: guessed (unconfirmed);", 1) + "")[0] is True
    appended = "\n".join(ln + " Extra note from the reviewer." if ln.startswith(("Lineups:", "Data audit:", "Draw:")) else ln for ln in lines)
    assert row(appended)[0] is True                                                                          # appending is allowed on prefix lines


def test_draft_notes_draw_flags_knockouts_and_weak_models():
    from football.oracle import draft as DR
    rep = _report(odds=False, competition="Africa Cup of Nations, Knockout, Quarter-final")
    text = DR.draft_answer(rep)
    assert "knockout match: the result means level after 120 minutes" in text
    assert text.count("In plain words: Weak data: the trained model does not know these teams") == 1       # the fixture teams are unknown to the trained model
    rep2 = _report(odds=False)
    d = O.predict(rep2, panel="none")["prediction"]["draw"]
    assert ("a risk flag, not a prediction" in DR.draft_answer(rep2)) == (d["alert"] != "none")


def test_banned_claims_cover_staking_guarantees_predicted_draws_and_the_odds_track_record():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False)
    pred = O.predict(rep, panel="none")["prediction"]
    def banned(extra):
        return "no banned claims" in [n for n, ok, _ in AA.audit_answer(rep, _answer(pred) + extra)["rows"] if not ok]
    for bad in ("Stake 5 units on Alpha.", "A staking plan of 2%.", "Alpha is a sure thing.", "A guaranteed winner.", "Alpha cannot lose.", "We predict a draw.",
                "The odds usually win these.", "Historically the bookmakers are right here.", "The odds track record favours Beta.", "The odds won 17 of 20 such cases.", "odds won 17-3."):
        assert banned(bad), bad
    for fine in ("The result is not a guarantee.", "Table [H.stakes] matter.", "No guarantee either way.", "A draw is a risk flag.", "The odds are a benchmark only."):
        assert not banned(fine), fine


def test_lint_enforces_the_skill_rules_the_engine_does_not():
    from football.oracle import lint as LT
    rep = _report(home_missing=[{"name": "H1"}], odds=False)
    adv = {"home": GOOD_HOME, "away": GOOD_AWAY, "odds_challenge": "Priced [BASELINE].", "verdict": "unclear"}
    base = {"home_rate_pct": 0, "confidence": 0.3, "advocates": adv, "data_gaps": ["lineups"], "factors": []}
    def problems(**kw):
        return " | ".join(LT.lint_opinion(rep, {**base, **kw})["advocate_problems"])
    assert "words (the limit is 90)" in problems(advocates={**adv, "home": "word " * 90 + "[H.form] [FIXTURE] [BASELINE]"}) and "has 9" not in problems(advocates={**adv, "home": "word " * 80 + "[H.form] [FIXTURE]"})
    assert "ONE tag per factor" in problems(factors=[{"effect": "home_rate_pct", "evidence": "[H.form] [H.table]", "note": "x"}], home_rate_pct=1)
    assert "at most +-3" in problems(factors=[{"effect": "home_rate_pct", "evidence": "[H.absent.H1]", "note": "x"}], home_rate_pct=-5)
    assert "at most" not in problems(factors=[{"effect": "home_rate_pct", "evidence": "[H.absent.H1]", "note": "x"}], home_rate_pct=-3)
    assert "weak_model: confidence must be <= 0.4" in problems(confidence=0.6)                            # the fixture teams are unknown to the trained model
    assert "weak_model: every adjustment must be within +-2" in problems(factors=[{"effect": "home_rate_pct", "evidence": "[H.form]", "note": "x"}], home_rate_pct=3)
    assert "weak_model" not in problems(factors=[{"effect": "home_rate_pct", "evidence": "[H.form]", "note": "x"}], home_rate_pct=2)


def _judgement(**over):
    j = {"vs_odds": "No odds in this report.", "case_home": "Strong form [H.form] and the home venue [FIXTURE].", "case_away": "A better table position [H.table].",
         "weak_points": "Neither side has a confirmed XI [LINEUPS].", "odds_challenge": "unclear - the cited evidence does not settle it.", "why": "Form [H.form], venue [FIXTURE] and the table [H.table].",
         "risks": "Lineups are unconfirmed; re-check before kickoff.", "data_note": "The unconfirmed lineups are a data limit."}
    j.update(over)
    return j


def test_compose_keeps_every_engine_line_exactly_and_the_audit_passes(tmp_path, capsys):
    from football.oracle import audit_answer as AA, draft as DR
    for kw in ({}, {"odds": False}, {"home_missing": [{"name": "H1"}, {"name": "Nobody"}], "lineup_confirmed": False}):
        rep = _report(**kw)
        text = DR.compose_answer(rep, _judgement())
        assert "[WRITE" not in text
        r = AA.audit_answer(rep, text)
        assert r["clean"] is True, [x for x in r["rows"] if not x[1]]
        draft_lines = {l.split(":", 1)[0]: l for l in DR.draft_answer(rep).split("\n")}
        for line in text.split("\n"):
            label = line.split(":", 1)[0]
            if label in ("In plain words", "Recommended bet", "Draw", "Goals", "Lineups"):
                assert line == draft_lines[label]                      # not one engine line differs from the draft
    p = tmp_path / "r.json"; j = tmp_path / "j.json"; p.write_text(json.dumps(_report())); j.write_text(json.dumps(_judgement()))
    assert O.main(["oracle", "compose", str(p), str(j)]) == 0
    out = capsys.readouterr().out
    assert "Recommended bet:" in out and "[WRITE" not in out and O.main(["oracle", "compose", str(p)]) == 2


def test_compose_cannot_be_used_to_change_a_number_and_survives_bad_input():
    from football.oracle import audit_answer as AA, draft as DR
    rep = _report(odds=False)
    sneaky = _judgement(why="Recommended bet: Beta to win - 99%\nIn plain words: Beta will crush them. [WRITE: x]", unknown_key="ignored")
    text = DR.compose_answer(rep, sneaky)
    assert text.count("\n") == DR.draft_answer(rep).count("\n")                                  # newlines in the reviewer text cannot add lines
    assert "unknown_key" not in text and sum(1 for l in text.split("\n") if l.startswith("Recommended bet:")) == 1
    assert [x[0] for x in AA.audit_answer(rep, text)["rows"] if x[1] is False and "draft" in x[0]] == []
    partial = DR.compose_answer(rep, {"why": "Form [H.form]."})
    assert partial.count("[WRITE") == 0 and "Why: Form [H.form]." in partial          # keys the reviewer leaves out are built from the dossier and the engine
    for bad in (None, [], "text", 5, {"why": None}, {"why": ["x"]}, {"why": "   "}):
        auto = DR.compose_answer(rep, bad)
        assert "[WRITE" not in auto and "Why: The forecast comes from the engine only" in auto


def test_head_to_head_and_recent_form_are_checked_against_their_own_data():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False)     # H2H record: home 2, draws 1, away 1 (n=4); recent form: home six wins, away six draws
    pred = O.predict(rep, panel="none")["prediction"]
    ROW = "recent-form counts quoted match the form data"
    def fails(extra):
        r = AA.audit_answer(rep, _answer(pred) + extra)
        return next(x for x in r["rows"] if x[0] == ROW)
    # a head-to-head sentence is NOT judged against the form letters (the bug: 'won 2 of the last 4 meetings' was failed because the home side won 4 of its last 6)
    assert fails("Alpha won 2 of the last 4 meetings [H2H].")[1] is True
    assert fails("Record: home 2, draws 1, away 1 (n=4) [H2H].")[1] is True
    assert fails("Beta won 1 of 4 head-to-head meetings.")[1] is True
    # ... but its numbers must match the head-to-head record
    for wrong in ("Beta won 3 of the last 4 meetings [H2H].", "Record: home 3, draws 1, away 1 (n=4) [H2H].", "Record: home 2, draws 1, away 1 (n=5) [H2H].",
                  "Alpha won 7 of 10 meetings [H2H].", "Beta has 3 wins in the head-to-head [H2H]."):
        ok, detail = fails(wrong)[1], fails(wrong)[2]
        assert ok is False and "head-to-head record" in detail, wrong
    # recent form is still checked against the form letters
    assert fails("Alpha won 6 of their last 6 [H.form].")[1] is True
    ok, detail = fails("Alpha won 4 of the last 6 [H.form].")[1:]
    assert ok is False and "form data has" in detail and "head-to-head" not in detail


def test_a_1x2_bet_quotes_the_same_calibrated_chance_as_the_headline():
    """Two different hit rates for one 1X2 pick contradicted each other (headline 70.9% vs bet line 66.2%): they are now the same number."""
    for kw in ({}, {"odds": False}, {"home_missing": [{"name": "H1"}]}):
        pred = O.predict(_report(**kw), panel="none")["prediction"]
        rec = pred["recommendation"]
        if rec["market"] == "1X2":
            assert rec["observed_hit_pct"] == pred["confidence_pct"]
    big = O.recommend("A", "B", [0.684, 0.20, 0.116], {"over_2_5": 0.5, "btts": 0.5})
    assert big["market"] == "1X2" and big["observed_hit_pct"] == O._calibrated_confidence(68.4)
    goals = O.recommend("A", "B", [0.4, 0.3, 0.3], {"over_2_5": 0.2, "btts": 0.4})            # Under 2.5 at 80%
    assert goals["market"] == "Under 2.5" and goals["observed_hit_pct"] == 81.2                 # goals bets get their own table, never the 1X2 one


def test_plain_words_uses_toss_up_only_for_the_draw_lens_definition():
    from football.oracle import draft as DR
    base = {"draw_pct": 26.0, "recommendation": {"selection": "x", "probability_pct": 55.0, "strength": "lean", "observed_hit_pct": 56.0, "weak_model": False, "cautions": []}}
    gap = {**base, "home_win_pct": 41.5, "away_win_pct": 32.8, "draw": {"alert": "none", "toss_up": False}}                 # Belgium v France: 8.7-point gap
    level = {**base, "home_win_pct": 35.3, "away_win_pct": 33.6, "draw": {"alert": "alert", "toss_up": True}}
    t1, t2 = DR.plain_words("Belgium", "France", gap), DR.plain_words("Alpha", "Beta", level)
    assert "toss-up" not in t1 and t1.startswith("No side is a clear favourite (Belgium 42% to win).")
    assert t2.startswith("This looks like a toss-up: the sides are level")


def test_form_counts_are_checked_against_the_side_whose_form_tag_is_cited():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False)      # home: six wins, away: six draws
    pred = O.predict(rep, panel="none")["prediction"]
    ROW = "recent-form counts quoted match the form data"
    def ok(extra):
        return next(x for x in AA.audit_answer(rep, _answer(pred) + extra)["rows"] if x[0] == ROW)[1]
    assert ok("Alpha won 6 of the last 6 [H.form].") is True
    assert ok("Beta won 6 of the last 6 [A.form].") is False          # six draws: wrong for the away side even though the HOME side did win 6
    assert ok("Beta drew 6 of the last 6 [A.form].") is True
    assert ok("Alpha won 6 of the last 6 [A.form].") is False
    assert ok("Alpha won 6 of the last 6.") is True                     # no tag: either side may match


def test_lineups_line_classifies_every_absentee_and_lint_rejects_adjusting_for_heavy_rotation():
    from football.oracle import draft as DR, lint as LT
    rep = _report(odds=False, home_missing=[{"name": "H1"}, {"name": "H2"}, {"name": "Nobody"}], lineup_confirmed=False)
    rep["teamProfile"]["squad"][1]["recent_usage"]["total_minutes"] = 450      # H1: starter
    rep["teamProfile"]["squad"][2]["recent_usage"]["total_minutes"] = 150      # H2: rotation
    line = next(ln for ln in DR.draft_answer(rep).split("\n") if ln.startswith("Lineups:"))
    assert "Alpha starters out: H1; other absentees: H2 (rotation player)" in line and "unknown (not in the squad list): Nobody" in line
    heavy = _report(odds=False)
    heavy["insights"]["home_rotation"] = {"changed_players": 9, "starting_xi_size": 11}
    op = {"home_rate_pct": -1, "confidence": 0.3, "factors": [{"effect": "home_rate_pct", "evidence": "[H.rotation]", "note": "x"}],
          "advocates": {"home": GOOD_HOME, "away": GOOD_AWAY, "odds_challenge": "[BASELINE]", "verdict": "unclear"}, "data_gaps": ["lineups"]}
    assert "heavy rotation: mention it, never adjust for it" in " ".join(LT.lint_opinion(heavy, op)["advocate_problems"])
    light = _report(odds=False)
    light["insights"]["home_rotation"] = {"changed_players": 6, "starting_xi_size": 11}
    assert "heavy rotation" not in " ".join(LT.lint_opinion(light, op)["advocate_problems"])


def test_h2h_conflict_is_flagged_and_venue_claims_about_meetings_are_warned():
    from football.oracle import audit_answer as AA
    from football.oracle.facts import audit_facts
    rep = _report(odds=False)      # summary: home 2, draws 1, away 1 (n=4)
    rep["match"]["recent_meetings"] = [{"scoreline": "1-1", "home_team": "Alpha", "away_team": "Beta"}, {"scoreline": "2-0", "home_team": "Alpha", "away_team": "Beta"},
                                       {"scoreline": "3-1", "home_team": "Beta", "away_team": "Alpha"}]     # a draw, an Alpha win and a Beta win: consistent with home 2, draws 1, away 1
    facts = extract_facts(rep)
    assert facts["h2h_seen"] == {"home": 1, "draws": 1, "away": 1, "n": 3}
    assert not any(f["code"] == "h2h_conflict" for f in audit_facts(facts)["findings"])
    rep["match"]["recent_meetings"].append({"scoreline": "2-1", "home_team": "Beta", "away_team": "Alpha"})     # a second Beta win: away 2 > summary away 1
    codes = [f["code"] for f in audit_facts(extract_facts(rep))["findings"]]
    assert "h2h_conflict" in codes
    other = _report(odds=False)
    other["match"]["recent_meetings"] = [{"scoreline": "1-0", "home_team": "Gamma", "away_team": "Delta"}]      # other teams: ignored
    assert extract_facts(other)["h2h_seen"] is None
    pred = O.predict(rep, panel="none")["prediction"]
    def venue_warns(extra):
        return [w for w in AA.audit_answer(rep, _answer(pred) + extra)["warnings"] if "venues of past meetings" in w]
    assert len(venue_warns("Beta won 1 of the last 4 meetings on the road [H2H].")) == 1 and len(venue_warns("Alpha has a strong home record in these meetings [H2H].")) == 1
    assert venue_warns("Beta won 1 of 4 meetings [H2H]. The match is at home for Alpha.") == []


def test_point_gap_claims_must_match_the_outcome_the_sentence_names_and_speculation_is_warned():
    from football.oracle import audit_answer as AA
    rep = _report()
    rep["match"]["betting_odds"] = {"home_win_fair_pct": 40.0, "draw_fair_pct": 30.0, "away_win_fair_pct": 30.0, "over_2_5_fair_pct": 50.0, "under_2_5_fair_pct": 50.0}     # distinct gaps per outcome
    full = O.predict(rep, panel="none")
    pred = full["prediction"]
    base = [100 * x for x in full["engine"]["after_absences"]["probs"]]
    gaps = {"home": abs(pred["home_win_pct"] - 40.0), "draw": abs(pred["draw_pct"] - 30.0), "away": abs(pred["away_win_pct"] - 30.0)}
    assert abs(gaps["home"] - gaps["away"]) > 1.5 and abs(gaps["home"] - gaps["draw"]) > 1.5          # the three gaps differ enough to tell outcomes apart
    def gap_warns(extra):
        return [w for w in AA.audit_answer(rep, _answer(pred) + extra)["warnings"] if "no gap" in w]
    assert gap_warns(f"The model is {gaps['home']:.1f} points off the odds on the home side.") == []
    assert gap_warns(f"The model is {gaps['away']:.1f} points off the odds on the away side.") == []
    assert gap_warns(f"The model is {gaps['draw']:.1f} points off the odds on the draw.") == []
    ws = gap_warns(f"The model is {gaps['home']:.1f} points off the odds on the away side.")           # a real number, but the HOME gap
    assert len(ws) == 1 and "the away side" in ws[0]
    assert gap_warns(f"The model is {gaps['home']:.1f} points off the odds.") == []                          # no outcome named: any real gap is fine
    def spec(extra):
        return [r for r in AA.audit_answer(rep, _answer(pred) + extra)["rows"] if r[0].startswith("no guesses") and not r[1]]
    for guess in ("The odds' slight overweight on the home side, likely explained by the lineups [LINEUPS].", "The bookmaker probably overprices the favourite.", "That is likely because the lineups may yet be priced."):
        assert spec(guess), guess
    for fine in ("The engine is 3 points below the odds [BASELINE] and the gap is unexplained.", "Lineups are unconfirmed [LINEUPS] so the odds may yet shift."):
        assert not spec(fine), fine


def test_points_off_the_odds_is_a_gap_claim_but_points_off_the_top_is_not():
    from football.oracle import audit_answer as AA
    rep = _report()
    pred = O.predict(rep, panel="none")["prediction"]
    def gaps(extra):
        return [w for w in AA.audit_answer(rep, _answer(pred) + extra)["warnings"] if "no gap" in w]
    assert len(gaps("The model is 47 points off the odds.")) == 1 and gaps("They are 9 points off the top.") == [] and gaps("Three points off the lead in the group.") == []


def test_rate_adjustments_are_not_probability_gaps():
    from football.oracle import audit_answer as AA
    rep = _report()
    pred = O.predict(rep, panel="none")["prediction"]
    def gaps(extra):
        return [w for w in AA.audit_answer(rep, _answer(pred) + extra)["warnings"] if "no gap" in w]
    assert gaps("The away rate is down 3 points due to the absences.") == [] and gaps("Reviewer adjustment of 4 points on the home side.") == []
    assert len(gaps("The model is 47 points above the odds on the home side.")) == 1


def test_unbeaten_winless_and_streak_claims_are_checked_against_the_form_letters():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False)
    rep["form"] = {"last10_overall": [_row("1-0", "home", "W"), _row("2-0", "home", "W"), _row("1-1", "home", "D"), _row("1-0", "away", "W"), _row("0-1", "away", "L"), _row("0-2", "away", "L")]}
    pred = O.predict(rep, panel="none")["prediction"]       # Alpha (home), newest first: W W D W L L; Beta (away): six draws
    ROW = "unbeaten / winless / streak claims match the form letters"
    def ok(extra):
        return next(x for x in AA.audit_answer(rep, _answer(pred) + extra)["rows"] if x[0] == ROW)[1]
    assert ok("Alpha are unbeaten in the last 4 [H.form].") is True and ok("Alpha have a 2-game winning streak [H.form].") is True and ok("Beta are unbeaten [A.form].") is True
    assert ok("Alpha are unbeaten in recent form [H.form].") is False                                    # two losses in the last six (the Greece mistake)
    assert ok("Alpha have a 4-game winning streak [H.form].") is False and ok("Alpha are winless [H.form].") is False
    assert ok("Beta are winless [A.form].") is True and ok("Beta have three consecutive wins [A.form].") is False and ok("Beta have two straight defeats [A.form].") is False
    assert ok("Alpha are unbeaten in recent form.") is False                                             # the team name picks the side, so it is checked without a tag too
    assert ok("They are unbeaten in recent form.") is True                                               # no tag and no team name: no side to check
    assert ok("Alpha are unbeaten in six against Beta [H2H].") is True                                   # meetings are not form


def test_absentee_counts_next_to_one_sides_tags_cannot_exceed_that_sides_count():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False, away_missing=[{"name": "Zed"}, {"name": "Yan"}, {"name": "A1"}])      # Zed and Yan are not in the squad list, A1 is
    pred = O.predict(rep, panel="none")["prediction"]
    def warns(extra):
        return [w for w in AA.audit_answer(rep, _answer(pred) + extra)["warnings"] if "absentee(s) are not in the squad list" in w]
    assert warns("Two absentees not in the squad list [A.absent.Zed] [A.absent.Yan].") == []
    assert len(warns("Eight Dutch absentees not in the squad list [A.absent.Zed] [A.absent.Yan].")) == 1
    assert len(warns("Three players not in the squad list [A.absent.Zed] [A.absent.Yan].")) == 1
    assert warns("Three players not in the squad list [A.absent.Zed] [H.absent.Q].") == []             # tags of both sides: not attributed to one


def test_a_count_of_players_about_something_else_is_not_an_absentee_count():
    from football.oracle import audit_answer as AA
    rep = _report(odds=False, away_missing=[{"name": "Zed"}])
    pred = O.predict(rep, panel="none")["prediction"]
    def warns(extra):
        return [w for w in AA.audit_answer(rep, _answer(pred) + extra)["warnings"] if "absentee(s) are not in the squad list" in w]
    assert warns("Zed is not in the squad list [A.absent.Zed]; the squad has 14 players with no valuation.") == []
    assert len(warns("Five players not in the squad list [A.absent.Zed].")) == 1


def test_goals_bets_need_60_percent_and_a_double_chance_replaces_a_weak_1x2_pick():
    m50 = {"over_2_5": 0.47, "btts": 0.45}                                  # Under 53%, BTTS No 55%: both in the 50s
    r = O.recommend("A", "B", [0.62, 0.20, 0.18], m50)                      # a clear 1X2 pick wins; the goals picks are not eligible
    assert r["market"] == "1X2" and r["selection"] == "A to win" and r["reason"] == "" and r["not_recommended"] == []
    r2 = O.recommend("A", "B", [0.35, 0.30, 0.35], m50)                      # no outcome reaches 60%: the better double chance, not a 55% goals bet
    assert r2["market"] == "Double chance" and r2["selection"] == "Either side to win (no draw)" and r2["probability_pct"] == 70.0
    assert "no single outcome reaches 60%" in r2["reason"] and r2["not_recommended"][0]["selection"] == "Both teams to score: No"   # the 55% goals bet it would have picked before
    assert r2["observed_hit_pct"] == 73.2
    r3 = O.recommend("A", "B", [0.45, 0.30, 0.25], {"over_2_5": 0.3, "btts": 0.4})      # Under 70% is eligible and beats the 45% pick; the double chance 1X (75%) wins the contest
    assert r3["market"] == "Double chance" and r3["selection"] == "A or draw" and r3["probability_pct"] == 75.0
    r4 = O.recommend("A", "B", [0.62, 0.20, 0.18], {"over_2_5": 0.3, "btts": 0.4})      # a 62% 1X2 pick: double chance is not eligible (pick >= 60%), Under 70% is
    assert r4["market"] == "Under 2.5" and r4["probability_pct"] == 70.0 and any(a["market"] == "Double chance" for a in r4["alternatives"])
    r5 = O.recommend("A", "B", [0.55, 0.25, 0.20], {"over_2_5": 0.3, "btts": 0.4})      # a 55% pick is below the 60% trigger: the double chance A or draw (80%) now wins
    assert r5["market"] == "Double chance" and r5["selection"] == "A or draw" and r5["probability_pct"] == 80.0
    assert O.recommend("A", "B", [0.35, 0.30, 0.35], m50, weak_model=True)["strength"] == "lean"


def test_double_chance_bets_are_scored_and_explained_and_shown_in_the_draft():
    from football.oracle import draft as DR, scorecard as SC
    assert SC.bet_hit("A or draw", "A", "B", 1, 1) and SC.bet_hit("A or draw", "A", "B", 2, 0) and not SC.bet_hit("A or draw", "A", "B", 0, 1)
    assert SC.bet_hit("draw or B", "A", "B", 1, 1) and SC.bet_hit("draw or B", "A", "B", 0, 2) and not SC.bet_hit("draw or B", "A", "B", 1, 0)
    assert SC.bet_hit("Either side to win (no draw)", "A", "B", 2, 1) and not SC.bet_hit("Either side to win (no draw)", "A", "B", 1, 1)
    assert SC.why_missed({"market": "Double chance"}, "A", "B", 1, 1) == "draw" and SC.why_missed({"market": "Double chance"}, "A", "B", 0, 3) == "B won"
    rep = _report(odds=False)
    rec = O.predict(rep, panel="none")["prediction"]["recommendation"]
    line = next(l for l in DR.draft_answer(rep).split("\n") if l.startswith("Recommended bet:"))
    assert (("Why this market:" in line) == bool(rec["reason"])) and (("Not recommended:" in line) == bool(rec["not_recommended"]))


def test_speculation_pattern_catches_priced_by_odds_guesses_and_invented_data_generalisations():
    from football.oracle.audit_answer import SPECULATION
    for text in ("Their absences are likely priced by the odds.", "Lewandowski is probably already priced by bookmakers.",
                 "Squad list data typically excludes injured players."):
        assert SPECULATION.search(text), text
    assert not SPECULATION.search("The engine does not model these absences.")


def test_speculation_pattern_catches_invented_causes_odds_verdicts_and_unsupported_key_absentees():
    from football.oracle.audit_answer import SPECULATION
    for text in ("a 0.3-point gap explained only by rounding", "making the 43.8% odds optimistic", "a scrape-timing artefact",
                 "three key Austrian absentees are not in the squad list"):
        assert SPECULATION.search(text), text


def test_a_guess_fails_the_audit_and_a_context_tag_named_as_a_driver_is_warned():
    from football.oracle import audit_answer as AA
    rep = _report()
    pred = O.predict(rep, panel="none")["prediction"]
    clean = AA.audit_answer(rep, _answer(pred))
    assert all(ok for name, ok, _ in clean["rows"] if name.startswith("no guesses"))
    bad = AA.audit_answer(rep, _answer(pred) + "\nThe odds are optimistic here.")
    assert [r for r in bad["rows"] if r[0].startswith("no guesses") and not r[1]] and not bad["clean"]
    why = AA.audit_answer(rep, _answer(pred) + "\nWhy: the table position [A.stakes] is the main driver.")
    assert any("[A.stakes]" in w and "context, not drivers" in w for w in why["warnings"])


def test_scorecard_skips_json_files_that_are_not_report_objects(tmp_path):
    from football.oracle import scorecard
    (tmp_path / "list.json").write_text("[1, 2]", encoding="utf-8")
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    (tmp_path / "rep.json").write_text('{"match": {}}', encoding="utf-8")
    assert scorecard._reports([str(tmp_path)]) == [{"match": {}}]


def test_advocates_need_two_of_their_sides_points_and_enough_words_and_the_brief_shows_how_to_argue():
    from football.oracle import lint as LT, debate
    rep = _report(odds=False)
    base = {"home_rate_pct": 0, "confidence": 0.3, "data_gaps": ["lineups"], "factors": []}
    def problems(home):
        adv = {"home": home, "away": GOOD_AWAY, "odds_challenge": "Priced [BASELINE].", "verdict": "unclear"}
        return " | ".join(LT.lint_opinion(rep, {**base, "advocates": adv})["advocate_problems"])
    assert "fewer than two" in problems("The home side has the better recent form [H.form] and that is the whole argument we can make for them here today.")
    assert "too short" in problems("Form [H.form] [FIXTURE].")
    assert "fewer than two" not in problems(GOOD_HOME) and "too short" not in problems(GOOD_HOME)
    d = {"home": [{"tag": "[H.form]", "strength": "moderate", "priced": True, "text": "form"}], "away": [{"tag": "[A.form]", "strength": "slight", "priced": True, "text": "away form"}],
         "both": [{"tag": "[H.rotation]", "strength": "slight", "priced": False, "text": "rot"}]}
    kit = " ".join(debate.advocate_kit(d, "Alpha", "Beta"))
    assert "LEAD with [H.form]" in kit and "REBUT Beta's best point: [A.form]" in kit and "CONCEDE [H.rotation]" in kit and "Base rate" not in debate.format_challenge(None)


def test_losing_form_is_context_not_an_upside_and_bounce_back_claims_fail_the_audit():
    from football.oracle import debate
    from football.oracle.audit_answer import SPECULATION
    from football.oracle.facts import extract_facts
    f = extract_facts(_report())
    for side, res in (("home", "LLLWDW"), ("away", "WWDLWW")):
        f["sides"][side]["form"] = [{"result": r, "gf": 0, "ga": 1} for r in res]
    d = debate.dossier(f)
    both = [p for p in d["both"] if p["tag"] == "[H.form]"]
    assert both and "lost the last 3 matches" in both[0]["text"] and "NOT bounce back" in both[0]["text"] and not [p for p in d["both"] if p["tag"] == "[A.form]"]
    for text in ("They will bounce back at home.", "The side is hungry after the defeat.", "Poland have something to prove."):
        assert SPECULATION.search(text), text
    assert not SPECULATION.search("Sides on losing form did not bounce back in the data [H.form].")


def test_audit_fails_backwards_xg_claims_and_a_verdict_that_contradicts_its_text_and_warns_on_wrong_absentee_tags():
    from football.oracle import audit_answer as AA
    rep = _report()
    pred = O.predict(rep, panel="none")["prediction"]
    def rows(extra):
        return [r for r in AA.audit_answer(rep, _answer(pred) + extra)["rows"] if r[0].startswith("claims agree") and not r[1]]
    assert rows("\nTheir xG is worse than Latvia's (-0.48 vs -0.81), suggesting underperformance [BASELINE].")
    assert rows("\nTheir xG is better than Latvia's (-0.81 vs -0.48) [BASELINE].")
    assert not rows("\nTheir xG is better than Latvia's (-0.48 vs -0.81) [BASELINE].")
    assert rows("\nOdds challenge: odds_right - the odds overrate the home side by 7 points [BASELINE].")
    assert not rows("\nOdds challenge: odds_right - the odds and the model agree [BASELINE].")
    rep2 = _report(home_missing=[{"name": "H1", "description": "knee"}])
    w = AA.audit_answer(rep2, _answer(O.predict(rep2, panel="none")["prediction"]) + "\nH1 returns today [H.rotation].")["warnings"]
    assert any("H1 is discussed under [H.rotation]" in x for x in w)


def test_audit_fails_heavy_rotation_below_eight_changes_and_warns_on_primary_driver_claims():
    from football.oracle import audit_answer as AA
    rep = _report()
    rep["insights"]["home_rotation"] = {"changed_players": 5, "starting_xi_size": 11}
    pred = O.predict(rep, panel="none")["prediction"]
    res = AA.audit_answer(rep, _answer(pred) + "\nCyprus made heavy rotation last match [H.rotation].")
    assert any(r[0].startswith("claims agree") and not r[1] and "heavy rotation" in r[2] for r in res["rows"])
    rep["insights"]["home_rotation"] = {"changed_players": 9, "starting_xi_size": 11}
    ok = AA.audit_answer(rep, _answer(O.predict(rep, panel="none")["prediction"]) + "\nCyprus made heavy rotation last match [H.rotation].")
    assert not any("heavy rotation" in r[2] for r in ok["rows"] if not r[1])
    w = AA.audit_answer(rep, _answer(pred) + "\nWhy: form [H.form] is the primary driver.")["warnings"]
    assert any("primary driver" in x for x in w)


def test_review_pack_contains_the_checklist_the_brief_and_the_answer(tmp_path, capsys):
    from football.oracle import review_pack
    rep = _report()
    pack = review_pack.review_pack(rep, "Cyprus 46.8% ANSWER-MARKER")
    assert "REVIEWER" in pack and "less negative number is BETTER" in pack and "Heavy rotation means 8 or more" in pack
    assert "=== BRIEF ===" in pack and "# BRIEF" in pack and "ANSWER-MARKER" in pack and "SENTENCE TABLE" in pack
    p1, p2 = tmp_path / "r.json", tmp_path / "a.md"
    p1.write_text(json.dumps(rep)); p2.write_text("x")
    assert O.main(["oracle", "review", str(p1), str(p2)]) == 0 and "VERDICT: FIX" in capsys.readouterr().out
    assert O.main(["oracle", "review", str(p1)]) == 2


def test_audit_fails_model_expected_goals_called_xg():
    from football.oracle import audit_answer as AA
    rep = _report()
    pred = O.predict(rep, panel="none")["prediction"]
    bad = AA.audit_answer(rep, _answer(pred) + "\nExpected goals (1.42-0.96) show Cyprus lead 0.45 xG per game.")
    assert any(r[0].startswith("claims agree") and not r[1] and "MODEL estimate" in r[2] for r in bad["rows"])
    ok = AA.audit_answer(rep, _answer(pred) + "\nExpected goals are 1.42-0.96 and the xG difference per game favours Cyprus.")
    assert not any("MODEL estimate" in r[2] for r in ok["rows"] if not r[1])


def test_speculation_pattern_catches_causes_given_for_the_odds_or_the_gap():
    from football.oracle.audit_answer import SPECULATION
    for text in ("Odds are 7.3 points higher on Cyprus due to form [H.form].", "The gap is explained by squad strength [BASELINE].", "The market reflects Cyprus's form."):
        assert SPECULATION.search(text), text
    assert not SPECULATION.search("The odds are 7.3 points higher on Cyprus (54.3% vs 47.0%); the gap is unexplained.")


def test_audit_warns_on_a_case_line_without_a_concession():
    from football.oracle import audit_answer as AA
    rep = _report()
    pred = O.predict(rep, panel="none")["prediction"]
    base = _answer(pred, extra_case_home="Strong form [H.form] and venue [FIXTURE] favour the hosts.", extra_case_away="Table [H.table] helps the visitors.")
    base = base.replace(", but unconfirmed lineups remain a risk", "").replace(", although the visitors lack form", "")
    w = AA.audit_answer(rep, base)["warnings"]
    assert any("no concession" in x for x in w)
    ok = AA.audit_answer(rep, _answer(pred, extra_case_home="Strong form [H.form] but rotation [H.rotation] is a risk.", extra_case_away="Table [H.table] helps, although the form [A.form] is weak."))["warnings"]
    assert not any("no concession" in x for x in ok)


def test_audit_warns_on_numbers_under_the_wrong_tag_and_on_invented_tactics_and_modal_guesses():
    from football.oracle import audit_answer as AA
    from football.oracle.audit_answer import SPECULATION, DRIVER_CLAIM
    rep = _report()
    pred = O.predict(rep, panel="none")["prediction"]
    w = AA.audit_answer(rep, _answer(pred) + "\nThey concede at -9.9 per game [H.table].")["warnings"]
    assert any("-9.9 is quoted under [H.table]" in x for x in w)
    for text in ("Form may create fragility.", "Latvia could get routed.", "Form and travel do not fully explain the 7-point gap."):
        assert SPECULATION.search(text), text
    assert DRIVER_CLAIM.search("the three largest drivers") and DRIVER_CLAIM.search("the strongest factor")


def test_audit_catches_hedged_consequences_size_words_and_does_not_split_decimals():
    from football.oracle import audit_answer as AA
    from football.oracle.audit_answer import SPECULATION, CHARACTER_WORDS
    for text in ("potentially disrupting rhythm", "giving Latvia a small window", "likely shootout notation", "probably fine"):
        assert SPECULATION.search(text), text
    assert not SPECULATION.search("The most likely 1X2 is Cyprus; likeliest scores 1-1 (13.2%).")
    assert CHARACTER_WORDS.search("The goal difference is narrow")
    rep = _report()
    pred = O.predict(rep, panel="none")["prediction"]
    w = AA.audit_answer(rep, _answer(pred) + "\nGoal difference [H.form] is +0.5 vs -0.7. Home venue [FIXTURE] helps.")["warnings"]
    assert not any("quoted under [FIXTURE]" in x for x in w)


def test_auto_built_judgement_lines_pass_the_audit_with_no_failures_or_warnings():
    from football.oracle import audit_answer as AA, draft as DR
    for kw in ({"odds": False}, {}, {"home_missing": [{"name": "H1", "description": "knee"}]}):
        rep = _report(**kw)
        text = DR.compose_answer(rep, {})
        res = AA.audit_answer(rep, text)
        assert res["clean"] and res["warnings"] == [], (kw, res["warnings"], [r for r in res["rows"] if not r[1]])


def test_cli_compose_ignores_all_free_text_and_free_text_mode_caps_the_analyst_note(tmp_path, capsys):
    from football.oracle import draft as DR
    from football.oracle.audit_answer import SPECULATION, CHARACTER_WORDS
    rep = _report()
    judgement = {"why": "Invented claim that form often wins [H.form].", "case_home": "Made up.", "analyst_note": "word " * 100 + "[H.form]"}
    free = DR.compose_answer(rep, judgement, free_text=True)
    safe = DR.compose_answer(rep, judgement, free_text=False)
    assert "Invented claim" in free and "Invented claim" not in safe and "Made up." not in safe and "Analyst note" not in safe
    note = [l for l in free.split("\n") if l.startswith("Analyst note")][0]
    assert len(note.split()) <= DR.NOTE_WORDS + 11 and "[WRITE" not in safe
    p1, p2 = tmp_path / "r.json", tmp_path / "j.json"
    p1.write_text(json.dumps(rep)); p2.write_text(json.dumps(judgement))
    assert O.main(["oracle", "compose", str(p1), str(p2)]) == 0 and "Invented claim" not in capsys.readouterr().out
    assert O.main(["oracle", "compose", str(p1), str(p2), "--free-text"]) == 0 and "Invented claim" in capsys.readouterr().out
    for text in ("form often outweighs squad value", "may shift the odds", "almost certainly change", "common in early reports"):
        assert SPECULATION.search(text), text
    assert CHARACTER_WORDS.search("Denmark dominated the head to head") and CHARACTER_WORDS.search("a major advantage")


def test_review_sentence_table_pairs_each_author_sentence_with_the_brief_lines_of_its_tags():
    from football.oracle.review_pack import sentence_table
    brief_text = "[H.form] Alpha last results (newest first) WWL\n- [BASELINE] (slight, already priced): xG difference per game: Alpha +0.4 vs Beta -0.7"
    answer = "Case for Alpha: strong form [H.form]. It is better [BASELINE]; this has no tag.     Case for Beta: a made up claim [H.nope].\nHeadline: ignored"
    t = sentence_table(brief_text, answer)
    assert "S1." in t and "[H.form] -> [H.form] Alpha last results" in t and "[BASELINE] -> - [BASELINE]" in t
    assert "NO TAG CITED" in t and "NO SUCH TAG" in t and "Headline" not in t


def test_analyst_note_sentences_need_tags_and_advocates_are_screened_for_guesses():
    from football.oracle import audit_answer as AA, draft as DR, lint as LT
    rep = _report(odds=False)
    pred = O.predict(rep, panel="none")["prediction"]
    bad = AA.audit_answer(rep, _answer(pred) + "\nAnalyst note (the author's own words, audited as free text): Form is good [H.form]. They will win easily.")
    assert any(r[0].startswith("every analyst-note") and not r[1] and "They will win easily" in r[2] for r in bad["rows"])
    ok = AA.audit_answer(rep, _answer(pred) + "\nAnalyst note (the author's own words, audited as free text): Form is good [H.form]. Squad value helps [BASELINE].")
    assert all(r[1] for r in ok["rows"] if r[0].startswith("every analyst-note"))
    adv = {"home": GOOD_HOME + " They are dominant and may create chances.", "away": GOOD_AWAY, "odds_challenge": "Priced [BASELINE].", "verdict": "unclear"}
    res = LT.lint_opinion(rep, {"home_rate_pct": 0, "confidence": 0.3, "advocates": adv, "data_gaps": ["lineups"], "factors": []})
    assert any("guesses or characterising" in x for x in res["advocate_problems"])


def test_audit_flags_control_possession_and_scepticism_words():
    from football.oracle.audit_answer import CHARACTER_WORDS
    for text in ("form suggests control", "Cyprus controls possession", "the odds' skepticism is justified", "the odds are sceptical", "a cautious market"):
        assert CHARACTER_WORDS.search(text), text


def test_scores_in_judgement_lines_must_be_the_goals_lines_own():
    from football.oracle import audit_answer as AA, draft as DR
    rep = _report()
    pred = O.predict(rep, panel="none")["prediction"]
    shown = [t["score"] for t in pred["simulation"]["top_scores"][:4]]
    text = DR.compose_answer(rep, {}, free_text=False)
    for ln in text.splitlines():
        if ln.startswith("Case for"):
            import re as _re
            assert all(a in shown for a, _ in _re.findall(r"(\d+-\d+) \((\d+(?:\.\d+)?)%\)", ln)), ln
    bad = AA.audit_answer(rep, text + "\nWhy: a 9-9 (99.9%) scoreline is likely.")
    assert any(r[0].startswith("scores quoted") and not r[1] for r in bad["rows"])
    assert all(r[1] for r in AA.audit_answer(rep, text)["rows"] if r[0].startswith("scores quoted"))


def test_shootout_inflated_scores_count_as_a_draw_with_ignored_goals_but_real_qualifier_scores_stay():
    import copy
    def rows(score, comp, result="W"):
        r = _row(score, "home", result)
        r["competition"] = comp
        return [r] + [_row("1-1", "home", "D")] * 5
    for score, comp in (("10-9", "FIFA Series, Azerbaijan"), ("6-4", "FIFA World Cup, Knockout"), ("6-5", "World Cup Qual. UEFA Playoff")):
        rep = _report(); rep["form"] = {"last10_overall": rows(score, comp)}
        f = extract_facts(rep)
        first = f["sides"]["home"]["form"][0]
        assert first["shootout"] and first["result"] == "D"
        assert any(x["code"] == "shootout_score_ignored" for x in audit_facts(f)["findings"]) and not any(x["code"] == "implausible_score" for x in audit_facts(f)["findings"])
        goals = Q._weighted(f["sides"]["home"]["form"], "gf", "ga")
        assert abs(goals[0] - 1.0) < 1e-9               # only the five real 1-1 draws count
    rep = _report(); rep["form"] = {"last10_overall": rows("5-4", "World Cup Qual. UEFA I")}
    first = extract_facts(rep)["sides"]["home"]["form"][0]
    assert not first["shootout"] and first["result"] == "W"


def test_a_large_gap_to_the_odds_adds_a_benchmark_only_note_that_changes_nothing():
    from football.oracle import draft as DR, audit_answer as AA
    rep = _report()
    rep["match"]["betting_odds"] = {"home_win_fair_pct": 20.0, "draw_fair_pct": 25.0, "away_win_fair_pct": 55.0, "over_2_5_fair_pct": 50.0, "under_2_5_fair_pct": 50.0}
    full = O.predict(rep, panel="none")
    text = DR.compose_answer(rep, {}, free_text=False)
    assert "large disagreement with the benchmark" in text and "changes nothing in the forecast, the bet or the cautions" in text
    rep2 = json.loads(json.dumps(rep)); rep2["match"]["betting_odds"] = None
    again = O.predict(rep2, panel="none")
    assert full["prediction"]["home_win_pct"] == again["prediction"]["home_win_pct"] and full["prediction"]["recommendation"]["selection"] == again["prediction"]["recommendation"]["selection"]
    res = AA.audit_answer(rep, text)
    assert res["clean"] and res["warnings"] == [], res["warnings"]


def test_unknown_absentees_get_a_position_from_the_outside_reference_without_changing_any_number():
    rep = _report(home_missing=[{"name": "Declan Rice", "description": "knee"}])
    f = extract_facts(rep)
    a = [x for x in f["sides"]["home"]["absentees"] if x["name"] == "Declan Rice"][0]
    assert a["role"] == "M" and a["role_reference"] and not a["in_squad_list"] and a["impact"] == 0
    rep2 = _report(home_missing=[{"name": "Nobody Known", "description": "knee"}])
    b = extract_facts(rep2)["sides"]["home"]["absentees"][-1]
    assert b["role"] is None and not b["role_reference"]
    assert O.predict(rep, panel="none")["prediction"]["home_win_pct"] == O.predict(_report(home_missing=[{"name": "Nobody Known", "description": "knee"}]), panel="none")["prediction"]["home_win_pct"]


def test_roles_command_lists_only_absentees_without_a_position(tmp_path, capsys):
    rep = _report(home_missing=[{"name": "Declan Rice", "description": "knee"}, {"name": "Nobody Known", "description": "knee"}])
    p = tmp_path / "r.json"; p.write_text(json.dumps(rep))
    assert O.main(["oracle", "roles", str(p)]) == 0
    out = capsys.readouterr().out
    assert "Nobody Known" in out and "Declan Rice" not in out and "1 absentee(s) need a position" in out
    assert O.main(["oracle", "roles"]) == 2


def test_wrong_typed_fields_never_crash_and_unreadable_reports_say_so(tmp_path, capsys):
    from football.oracle.facts import as_number, norm
    assert as_number("7") == 7.0 and as_number("") is None and as_number("n/a") is None and as_number(True) is None and as_number(float("nan")) is None and as_number(3) == 3
    assert norm(5) == "5" and norm(None) == "" and norm({"a": 1}) == "" and norm("Ünal") == "unal"
    rep = _report()
    rep["dataCompleteness"] = {"populated": "", "total": 10}
    rep["insights"]["rest_comparison"] = {"own_rest_days": "x", "opponent_rest_days": ""}
    rep["insights"]["home_xg_estimate"] = {"sample_size": "5", "xg_for": 4, "xg_against": None}
    rep["insights"]["away_standings_impact"] = 5
    rep["match"]["away_missing_players"] = [{"description": "no name"}, 7, {"name": None}]
    rep["match"]["home_lineup"] = [{"name": {"x": 1}}, {"name": "Ok Player"}, 3]
    assert O.predict(rep, panel="none")["prediction"] is not None and O.brief(rep)["brief"]
    broken = _report(); broken["form"] = {"last10_overall": [{"scoreline": "1-0", "date": 5, "opponent": 9, "result": 4}]}
    out = O.predict({"match": {"home_team": "A", "away_team": "B"}, "form": 5, "teamProfile": [1]}, panel="none")
    assert out["prediction"] is None or isinstance(out["prediction"], dict)
    p1, p2 = tmp_path / "l.json", tmp_path / "o.json"
    p1.write_text("[1, 2]"); p2.write_text("{}")
    assert O.main(["oracle", "lint", str(p1), str(p2)]) == 2 and "does not hold a JSON object" in capsys.readouterr().err


def test_scorecard_settles_a_fixture_listed_the_other_way_round_with_the_score_swapped(tmp_path):
    import datetime as dt
    from football.oracle import scorecard as SC
    from football.national_elo import canonical_name as cn
    rep = _report(odds=False)
    m = rep["match"]
    day = dt.date.fromisoformat(m["kickoff_utc"][:10])
    straight = SC.score_reports([rep], [{"home": cn(m["home_team"]), "away": cn(m["away_team"]), "hg": 3, "ag": 1, "day": day}])
    flipped = SC.score_reports([rep], [{"home": cn(m["away_team"]), "away": cn(m["home_team"]), "hg": 1, "ag": 3, "day": day}])
    assert straight["rows"] and flipped["rows"] and straight["rows"][0]["score"] == flipped["rows"][0]["score"] == "3-1"
    rep2 = json.loads(json.dumps(rep)); rep2["match"]["kickoff_utc"] = "not a date"
    assert SC.score_reports([rep2], []) is not None


def test_the_audit_stays_fast_on_a_huge_answer_and_the_engine_is_deterministic():
    import time
    from football.oracle import audit_answer as AA, draft as DR
    rep = _report(odds=False)
    base = DR.compose_answer(rep, {}, free_text=False)
    for junk in ("the odds and the gap and the market " * 3000, "xG -0.4 vs -0.8 worse " * 3000, "The odds are fine. " * 5000):
        t0 = time.time()
        AA.audit_answer(rep, base + "\nWhy: " + junk)
        assert time.time() - t0 < 15, "a pattern is quadratic in the length of a sentence"
    a, b = O.predict(rep, panel="none"), O.predict(rep, panel="none")
    assert json.dumps(a["prediction"], sort_keys=True) == json.dumps(b["prediction"], sort_keys=True)
    assert DR.compose_answer(rep, {}, free_text=False) == base


def test_lint_says_so_when_the_report_cannot_be_analysed():
    from football.oracle import lint as LT
    res = LT.lint_opinion({"match": {"home_team": "A", "away_team": "B", "head_to_head_summary": {"draws": "x"}}, "form": 5}, {"confidence": 0.3})
    assert res["clean"] is False and res["advocate_problems"] and LT.format_lint(res)


def test_table_shows_the_latest_report_of_a_fixture_once():
    rep = _report(odds=False)
    a = O.predict(rep, panel="none")
    table = O.format_table([a, a, {**a, "home": "Other", "away": "Team"}])
    rows = [l for l in table.splitlines() if l.startswith("| ") and not l.startswith("| #") and "---" not in l]
    assert len(rows) == 2 and "1 older report(s) of the same fixture hidden" in table
