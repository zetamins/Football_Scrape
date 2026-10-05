import json
from datetime import date

from football.oracle import forward_log as F
from football.oracle import oracle as O
from football.oracle import quant as Q
from football.oracle.facts import extract_facts
from test_oracle import _report


def _record(report):
    facts = extract_facts(report)
    return F.make_record(facts, Q.rate_sources(facts, use_market=False))


def test_record_stores_off_and_on_probabilities_and_absences_change_them():
    rec = _record(_report(home_missing=[{"name": "F4"}, {"name": "H4"}, {"name": "H5"}, {"name": "H1"}], odds=False))
    assert abs(sum(rec["off"]) - 1) < 1e-3 and abs(sum(rec["on"]) - 1) < 1e-3
    assert rec["n_absent"]["home"] == 3 or rec["n_absent"]["home"] == 4
    assert rec["on"] != rec["off"]


def test_no_absentees_means_identical_versions():
    rec = _record(_report(odds=False))
    assert rec["on"] == rec["off"] and rec["starters_out"] == {"home": [], "away": []}


def test_log_appends_once_and_cli_flag_is_opt_in(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "r.json"
    p.write_text(json.dumps(_report(odds=False)))
    assert O.main(["oracle", str(p), "--llm", "none"]) == 0
    assert not (tmp_path / "output").exists()
    assert O.main(["oracle", str(p), "--llm", "none", "--log"]) == 0
    assert O.main(["oracle", str(p), "--llm", "none", "--log"]) == 0
    assert len(F.load()) == 1


def _rec(i, off, on, gen="2026-10-01T00:00:00Z"):
    return {"home_team": f"Home{i}", "away_team": f"Away{i}", "kickoff_utc": "2026-10-03T18:00:00Z", "generated_at": gen, "off": off, "on": on}


def test_settle_skips_post_kickoff_reports_and_matches_results():
    recs = [_rec(1, [.4, .3, .3], [.5, .25, .25]), _rec(2, [.4, .3, .3], [.5, .25, .25], gen="2026-10-03T19:00:00Z")]
    res = [{"day": date(2026, 10, 3), "home": "home1", "away": "away1", "hg": 2, "ag": 0}, {"day": date(2026, 10, 3), "home": "home2", "away": "away2", "hg": 0, "ag": 0}]
    settled = F.settle(recs, res)
    assert len(settled) == 1 and settled[0][1] == 0


def test_verdict_needs_enough_matches_and_a_clear_win():
    better = [({"off": [.4, .3, .3], "on": [.7, .15, .15]}, 0) for _ in range(40)]
    few = F.evaluate(better)
    assert few["verdict"].startswith("keep OFF: only 40") and few["metrics"]["brier"]["diff"] < 0
    many = F.evaluate(better * 8)
    assert many["verdict"].startswith("gate passed")
    worse = F.evaluate([({"off": [.7, .15, .15], "on": [.4, .3, .3]}, 0) for _ in range(300)])
    assert worse["verdict"] == "keep OFF: absences ON is worse"
    assert F.evaluate([])["verdict"] == "not enough data"


def test_score_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    F.append(_rec(1, [.4, .3, .3], [.5, .25, .25]))
    csv = tmp_path / "res.csv"
    csv.write_text("date,home_team,away_team,home_score,away_score\n2026-10-03,Home1,Away1,1,0\n")
    assert F.main(["x", "score", str(csv)]) == 0
    assert "Settled matches: 1" in capsys.readouterr().out
    assert F.main(["x"]) == 2


def test_accuracy_summary_counts_picks_draws_and_brier():
    settled = [({"off": [.6, .25, .15]}, 0), ({"off": [.3, .4, .3]}, 1), ({"off": [.2, .3, .5]}, 0)]
    a = F.accuracy(settled)
    assert a["n"] == 3 and abs(a["pick_right"] - 2 / 3) < 1e-9 and a["draw_picks"] == 1 and a["draws_actual"] == 1 and abs(a["draws_expected"] - 0.95) < 1e-9
    assert "pick right 67%" in F.format_accuracy(a) and F.format_accuracy(F.accuracy([])) == "Accuracy: no settled matches yet"


def test_strata_report_tiers_without_drawing_a_verdict():
    from football.oracle import forward_log as F
    def rec(on, off, confirmed, out):
        return {"on": on, "off": off, "lineup_confirmed": confirmed, "starters_out": {"home": out, "away": 0}}
    settled = [(rec([0.6, 0.2, 0.2], [0.5, 0.25, 0.25], True, 1), 0), (rec([0.4, 0.3, 0.3], [0.5, 0.25, 0.25], False, 0), 0), (rec([0.5, 0.25, 0.25], [0.5, 0.25, 0.25], False, 0), 1)]
    t = {x["stratum"]: x for x in F.strata(settled)}
    assert t["confirmed lineup"]["n"] == 1 and t["confirmed lineup"]["brier_diff"] < 0       # ON helped where it moved the number the right way
    assert t["predicted lineup"]["n"] == 1 and t["predicted lineup"]["brier_diff"] > 0       # the match with no change is not counted
    assert t["a starter is out"]["n"] == 1 and "no starter out" in t
    text = F.format_evaluation(F.evaluate(settled))
    assert "tier confirmed lineup" in text and "no verdict from a tier" in text
