import json
from datetime import date

from football import prediction_log as pl


def _pred(home, draw, away):
    return {"home_win_pct": home, "draw_pct": draw, "away_win_pct": away}


def _report(home="Spain", away="Croatia", kickoff="2026-09-30T18:45:00.000Z", generated="2026-09-28T07:00:00.000Z", blended=(60, 25, 15), market=(70, 20, 10)):
    return {
        "generatedAt": generated,
        "match": {"home_team": home, "away_team": away, "kickoff_utc": kickoff, "competition": "Nations League"},
        "insights": {"prediction": {
            "blended": _pred(*blended), "market_implied": _pred(*market), "heuristic_blend": None, "model": "market+history",
        }},
    }


def test_record_from_report_needs_fixture_and_prediction():
    assert pl.record_from_report(_report())["home_team"] == "Spain"
    assert pl.record_from_report({"generatedAt": "x", "match": None, "insights": None}) is None
    no_pred = _report()
    no_pred["insights"]["prediction"] = None
    assert pl.record_from_report(no_pred) is None


def test_append_is_idempotent_and_load_skips_garbage(tmp_path):
    path = tmp_path / "log.jsonl"
    assert pl.append_report(_report(), path) is True
    assert pl.append_report(_report(), path) is False
    assert pl.append_report(_report(generated="2026-09-29T07:00:00.000Z"), path) is True
    with path.open("a") as fh:
        fh.write("{not json\n")
    assert len(pl.load(path)) == 2
    assert pl.load(tmp_path / "missing.jsonl") == []


def test_import_reports_counts_written_and_skipped(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(_report()))
    (tmp_path / "b.json").write_text(json.dumps({"generatedAt": "x"}))
    (tmp_path / "c.json").write_text("garbage")
    written, skipped = pl.import_reports(tmp_path, tmp_path / "log.jsonl")
    assert (written, skipped) == (1, 2)


def _results(rows):
    csv = "date,home_team,away_team,home_score,away_score\n" + "\n".join(rows)
    return pl.parse_results_csv(csv)


def test_settle_matches_names_aliases_and_one_day_tolerance(tmp_path):
    rec = pl.record_from_report(_report(home="Türkiye", away="Côte d'Ivoire", kickoff="2026-09-30T23:00:00.000Z"))
    results = _results(["2026-10-01,Turkey,Ivory Coast,2,0", "2026-10-01,Spain,Croatia,1,1", "2026-09-30,Turkey,Ivory Coast,,"])
    settled = pl.settle([rec], results)
    assert len(settled) == 1 and settled[0][1:] == (0, 2, 0)


def test_settle_ignores_predictions_made_after_kickoff_and_far_dates():
    late = pl.record_from_report(_report(generated="2026-09-30T20:00:00.000Z"))
    wrong_day = pl.record_from_report(_report())
    assert pl.settle([late], _results(["2026-09-30,Spain,Croatia,1,0"])) == []
    assert pl.settle([wrong_day], _results(["2026-10-09,Spain,Croatia,1,0"])) == []


def test_summarize_scores_methods_and_compares_to_market_on_same_matches():
    good = pl.record_from_report(_report(blended=(80, 10, 10), market=(50, 25, 25)))
    settled = pl.settle([good], _results(["2026-09-30,Spain,Croatia,2,0"]))
    rows = {r["method"]: r for r in pl.summarize(settled)}
    assert set(rows) == {"blended", "market_implied"}
    assert rows["blended"]["accuracy"] == 1.0
    assert rows["blended"]["brier"] < rows["market_implied"]["brier"]
    assert rows["blended"]["vs_market"] < 0 and rows["blended"]["vs_market_n"] == 1
    assert rows["market_implied"]["vs_market"] is None
    # Brier for (0.8,0.1,0.1) vs home win = 0.04+0.01+0.01
    assert abs(rows["blended"]["brier"] - 0.06) < 1e-9


def test_format_summary_handles_empty_and_populated():
    assert "No scored predictions" in pl.format_summary([], 0, 3)
    settled = pl.settle([pl.record_from_report(_report())], _results(["2026-09-30,Spain,Croatia,1,0"]))
    text = pl.format_summary(pl.summarize(settled), 1, 0)
    assert "blended" in text and "vs market" in text


def test_cli_logs_the_prediction_and_feeds_the_log_back(monkeypatch, tmp_path):
    import asyncio

    from football import cli

    seen = {}

    async def fake_run_search(team_name, on_progress, past_predictions=None):
        seen["past"] = past_predictions
        from types import SimpleNamespace

        return SimpleNamespace(generated_at="2026-09-28T07:00:00.000Z")

    monkeypatch.setattr(cli, "run_search", fake_run_search)
    monkeypatch.setattr(cli, "_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(cli, "build_report_json", lambda result: _report())
    monkeypatch.setattr(cli, "build_report_markdown", lambda result: "# md")
    asyncio.run(cli._run_one("Spain", announce=False))
    assert seen["past"] == []
    asyncio.run(cli._run_one("Spain", announce=False))
    assert len(seen["past"]) == 1
    assert len(pl.load(tmp_path / pl.LOG_NAME)) == 1
