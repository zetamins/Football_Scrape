import json
from datetime import datetime, timezone

import pytest

from football import analyze as A

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _row(score, venue, result, comp="UEFA Nations League", xg=(None, None)):
    return {"scoreline": score, "venue": venue, "result": result, "competition": comp, "xg_for": xg[0], "xg_against": xg[1]}


def _report(home="Alpha", away="Beta", team="Alpha", odds=True, xg=True, rows_home=None, rows_away=None, **match_extra):
    own_rows = rows_home if rows_home is not None else [_row("2-0", "home", "W")] * 6
    opp_rows = rows_away if rows_away is not None else [_row("1-1", "away", "D")] * 6
    match = {
        "home_team": home, "away_team": away, "kickoff_utc": "2026-10-03T18:00:00.000Z", "status": "notstarted",
        "competition": "Test League", "lineup_confirmed": True, "neutral": None,
        "betting_odds": ({"home_win_fair_pct": 55.0, "draw_fair_pct": 25.0, "away_win_fair_pct": 20.0} if odds else None),
        "home_missing_players": [], "away_missing_players": [],
    }
    match.update(match_extra)
    insights = {"home_elo_rating": {"elo": 1600, "sample_source": "eloratings.net"}, "away_elo_rating": {"elo": 1500, "sample_source": "eloratings.net"},
                "home_squad_strength": {"total_value": 300e6, "available_value": 300e6}, "away_squad_strength": {"total_value": 100e6, "available_value": 100e6}}
    if xg:
        insights["home_xg_estimate"] = {"sample_size": 6, "xg_for": 9.0, "xg_against": 4.0}
        insights["away_xg_estimate"] = {"sample_size": 6, "xg_for": 6.0, "xg_against": 8.0}
    return {"team": team, "generatedAt": "2026-10-01T10:00:00.000Z", "match": match, "form": {"last10_overall": own_rows},
            "opponentForm": {"last10_overall": opp_rows}, "insights": insights}


def test_parse_score_resolves_home_away_frame_and_checks_result_letter():
    assert A._parse_score(_row("3-1", "home", "W")) == (3, 1)
    assert A._parse_score(_row("3-1", "away", "L")) == (1, 3)          # away: first number is the opponent's
    assert A._parse_score(_row("0-3", "away", "W")) == (3, 0)
    assert A._parse_score(_row("1-2", "home", "W")) == (2, 1)          # letter disagrees with venue -> trust the letter
    assert A._parse_score({"scoreline": "x"}) is None


def test_weighted_rates_prefer_recent_games_and_downweight_friendlies():
    rows = [_row("4-0", "home", "W"), _row("0-0", "home", "D"), _row("0-0", "home", "D")]
    gf, ga, n = A._weighted_rates(rows)
    assert gf > 4 / 3 and ga == 0 and n > 2                              # newest 4-0 weighs most
    friendly = [_row("4-0", "home", "W", comp="International Friendlies"), _row("0-0", "home", "D")]
    assert A._weighted_rates(friendly)[0] < A._weighted_rates([_row("4-0", "home", "W"), _row("0-0", "home", "D")])[0]


def test_own_is_home_handles_perspective():
    assert A._own_is_home(_report(team="Alpha")) is True
    assert A._own_is_home(_report(team="Beta")) is False
    assert A._own_is_home(_report(team="alpha")) is True


def test_market_uses_fair_pct_then_falls_back_to_raw_odds():
    m = A._market(_report())
    assert m["probs"] == pytest.approx((0.55, 0.25, 0.20))
    raw = _report(odds=False, betting_odds={"home_win_odds": 2.0, "draw_odds": 4.0, "away_win_odds": 4.0})
    assert A._market(raw)["probs"] == pytest.approx((0.5, 0.25, 0.25))
    assert A._market(_report(odds=False)) is None
    assert A._market(_report(odds=False, betting_odds={"home_win_odds": 0.5, "draw_odds": 4.0, "away_win_odds": 4.0})) is None


def test_all_methods_run_and_probabilities_sum_to_one():
    methods = A.calculate(_report())
    assert {m["name"] for m in methods} == {"market", "results_poisson", "xg_poisson", "elo", "squad_value"}
    for m in methods:
        assert sum(m["probs"]) == pytest.approx(1.0) and all(0 <= p <= 1 for p in m["probs"])
    assert next(m for m in methods if m["name"] == "elo")["weight"] == 2.0     # national Elo earns more weight


def test_stronger_home_side_is_favoured_and_perspective_flip_mirrors_result():
    a = A.analyze_report(_report(team="Alpha"), draws=500, now=NOW)["prediction"]
    assert a["home_win_pct"] > a["away_win_pct"] and a["pick"] == "home"
    # same fixture reported from the other team's point of view must give the same answer
    flipped = _report(team="Beta", rows_home=[_row("1-1", "away", "D")] * 6, rows_away=[_row("2-0", "home", "W")] * 6)
    flipped["form"], flipped["opponentForm"] = {"last10_overall": [_row("1-1", "away", "D")] * 6}, {"last10_overall": [_row("2-0", "home", "W")] * 6}
    b = A.analyze_report(flipped, draws=500, now=NOW)["prediction"]
    assert b["home_win_pct"] == pytest.approx(a["home_win_pct"], abs=0.2)


def test_neutral_venue_removes_home_advantage_from_goal_models():
    home = A._poisson_method("p", (1.5, 1.0, 8.0), (1.5, 1.0, 8.0), False, 1.0, "x")
    neutral = A._poisson_method("p", (1.5, 1.0, 8.0), (1.5, 1.0, 8.0), True, 1.0, "x")
    assert home["probs"][0] > neutral["probs"][0] and neutral["probs"][0] == pytest.approx(neutral["probs"][2])


def test_short_samples_are_shrunk_toward_the_pooled_mean():
    sparse = A._poisson_method("p", (4.0, 0.0, 1.0), (1.0, 1.0, 1.0), True, 1.0, "x")
    solid = A._poisson_method("p", (4.0, 0.0, 20.0), (1.0, 1.0, 20.0), True, 1.0, "x")
    assert solid["probs"][0] > sparse["probs"][0]
    assert solid["rates"][0] > sparse["rates"][0]


def test_absences_and_rest_shift_the_elo_method():
    base = A._elo_method(_report(), False)["probs"][0]
    hurt = _report()
    hurt["insights"]["home_squad_strength"] = {"total_value": 300e6, "available_value": 150e6}
    assert A._elo_method(hurt, False)["probs"][0] < base
    rested = _report()
    rested["insights"]["rest_comparison"] = {"own_rest_days": 7, "opponent_rest_days": 3}
    assert A._elo_method(rested, False)["probs"][0] > base


def test_audit_flags_missing_odds_thin_form_unconfirmed_lineup_and_post_kickoff():
    r = _report(odds=False, xg=False, rows_home=[_row("1-0", "home", "W")] * 3, lineup_confirmed=False)
    codes = {f["code"] for f in A.audit(r, A.calculate(r), NOW)["findings"]}
    assert {"no_odds", "no_xg", "short_form", "lineup_unconfirmed"} <= codes
    done = _report(status="finished")
    assert "not_pre_match" in {f["code"] for f in A.audit(done, A.calculate(done), NOW)["findings"]}
    late = _report()
    late["generatedAt"] = "2026-10-03T19:00:00.000Z"
    assert "after_kickoff" in {f["code"] for f in A.audit(late, A.calculate(late), datetime(2026, 10, 4, tzinfo=timezone.utc))["findings"]}


def test_audit_quality_drops_with_missing_data_and_flags_market_disagreement():
    full = A.audit(_report(), A.calculate(_report()), NOW)["quality"]
    poor_report = _report(odds=False, xg=False, lineup_confirmed=False)
    poor = A.audit(poor_report, A.calculate(poor_report), NOW)["quality"]
    assert poor < full <= 1.0
    contrarian = _report()
    contrarian["match"]["betting_odds"] = {"home_win_fair_pct": 10.0, "draw_fair_pct": 20.0, "away_win_fair_pct": 70.0}
    codes = {f["code"] for f in A.audit(contrarian, A.calculate(contrarian), NOW)["findings"]}
    assert {"market_vs_models", "methods_disagree"} <= codes


def test_poor_data_pulls_prediction_toward_base_rates():
    methods = A.calculate(_report())
    sure = A.combine(methods, 1.0)
    unsure = A.combine(methods, 0.3)
    assert unsure["final"][0] < sure["final"][0] and unsure["shrink"] > sure["shrink"] == 0
    assert sum(unsure["final"]) == pytest.approx(1.0)


def test_confidence_is_calibrated_pick_probability_and_goal_summary_is_sane():
    out = A.analyze_report(_report(), draws=300, now=NOW)["prediction"]
    assert out["confidence_pct"] == A._calibrated_confidence(out["pick_probability_pct"])
    g = out["goals"]
    assert g["likely_scorelines"][0]["pct"] >= g["likely_scorelines"][-1]["pct"]
    assert 0 < g["over_2_5_pct"] < 100 and 0 < g["btts_pct"] < 100


def test_monte_carlo_is_reproducible_and_ranges_bracket_the_point_estimate():
    methods = A.calculate(_report())
    a, b = A.monte_carlo(methods, 1.0, 400, seed=3), A.monte_carlo(methods, 1.0, 400, seed=3)
    assert a == b
    point = A.combine(methods, 1.0)["final"]
    for k, o in enumerate(A.OUTCOMES):
        lo, hi = a["ranges_pct"][o]
        assert lo <= 100 * point[k] + 3 and hi >= 100 * point[k] - 3 and lo <= hi
    assert sum(a["favourite_share_pct"].values()) == pytest.approx(100.0, abs=0.2)
    assert A.monte_carlo(methods, 1.0, 400, seed=4) != a


def test_no_methods_gives_no_prediction_and_an_error_finding():
    empty = {"team": "A", "match": {"home_team": "A", "away_team": "B", "status": "notstarted"}, "form": None, "opponentForm": None, "insights": {}}
    out = A.analyze_report(empty, draws=50, now=NOW)
    assert out["prediction"] is None
    assert "no_form" in {f["code"] for f in out["audit"]["findings"]}
    assert "no prediction" in A.format_markdown(out).lower()


def test_markdown_and_cli_json_output(tmp_path, capsys):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(_report()))
    assert A.main(["analyze", str(p)]) == 0
    text = capsys.readouterr().out
    assert "## Data audit" in text and "## Calculations" in text and "## Prediction" in text and "calibrated chance" in text
    assert A.main(["analyze", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["prediction"]["pick"] in A.OUTCOMES
    assert A.main(["analyze"]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    assert A.main(["analyze", str(bad)]) == 0                # skipped with a message, not a crash
