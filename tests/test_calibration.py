import math

import pytest

from football.calibration import brier_score, compute_calibration, log_loss
from football.types import MatchInfo


def _played(home, away, hs, as_, day="2026-01-10"):
    return MatchInfo(
        source="sofascore", source_url="https://x", competition="Premier League", home_team=home, away_team=away,
        kickoff_utc=f"{day}T15:00:00.000Z", venue=None, status="finished", home_score=hs, away_score=as_,
        home_score_ht=None, away_score_ht=None, season=None, round=None, match_id="1",
    )


def _pred(home="Arsenal", away="Chelsea", kickoff="2026-01-10T15:00:00.000Z", generated="2026-01-05T10:00:00.000Z", blended=(60, 25, 15), **methods):
    prediction = {"blended": _probs(blended)} if blended else {}
    prediction.update({k: _probs(v) for k, v in methods.items()})
    return {"home_team": home, "away_team": away, "kickoff_utc": kickoff, "generated_at": generated, "prediction": prediction}


def _probs(triple):
    return {"home_win_pct": triple[0], "draw_pct": triple[1], "away_win_pct": triple[2]}


# --- the scores themselves -------------------------------------------------------------------


def test_brier_score_perfect_worst_and_uniform():
    assert brier_score((1.0, 0.0, 0.0), 0) == 0.0
    assert brier_score((0.0, 0.0, 1.0), 0) == 2.0
    assert brier_score((1 / 3, 1 / 3, 1 / 3), 1) == pytest.approx(2 / 3)


def test_brier_score_matches_a_hand_worked_example():
    # 60/25/15 and the home side won: (0.4)^2 + 0.25^2 + 0.15^2 = 0.16 + 0.0625 + 0.0225
    assert brier_score((0.6, 0.25, 0.15), 0) == pytest.approx(0.245)


def test_log_loss_is_minus_ln_of_the_probability_given_to_what_happened():
    assert log_loss((0.5, 0.3, 0.2), 0) == pytest.approx(-math.log(0.5))
    assert log_loss((1.0, 0.0, 0.0), 1) > 20  # confidently wrong is punished hard but stays finite


# --- evaluating predictions ------------------------------------------------------------------


def test_a_prediction_is_scored_against_the_finished_match_it_was_about():
    summary = compute_calibration([_pred()], [_played("Arsenal", "Chelsea", 2, 0)])
    assert (summary.evaluated, summary.pending) == (1, 0)
    assert summary.brier_score == pytest.approx(0.245, abs=1e-4)
    assert summary.accuracy_pct == 100.0
    assert summary.brier_skill_vs_uniform_pct == pytest.approx(100 * (1 - 0.245 / (2 / 3)), abs=0.1)


def test_a_wrong_favourite_scores_worse_and_is_not_counted_accurate():
    summary = compute_calibration([_pred()], [_played("Arsenal", "Chelsea", 0, 1)])
    assert summary.accuracy_pct == 0.0
    assert summary.brier_score > 2 / 3


def test_predictions_whose_match_has_no_result_yet_are_pending_not_guessed():
    upcoming = MatchInfo(
        source="sofascore", source_url="x", competition="PL", home_team="Arsenal", away_team="Chelsea", kickoff_utc="2026-01-10T15:00:00.000Z",
        venue=None, status="notstarted", home_score=None, away_score=None, home_score_ht=None, away_score_ht=None, season=None, round=None, match_id="1",
    )
    summary = compute_calibration([_pred()], [upcoming])
    assert (summary.evaluated, summary.pending) == (0, 1)
    assert summary.brier_score is None
    assert "No earlier prediction has a known result" in summary.note


def test_the_match_is_found_through_team_aliases_and_the_same_day_only():
    matches = [_played("Man Utd", "Spurs", 1, 1, day="2026-01-10"), _played("Man Utd", "Spurs", 4, 0, day="2026-03-01")]
    summary = compute_calibration([_pred(home="Manchester United", away="Tottenham Hotspur", kickoff="2026-01-10T15:00:00.000Z")], matches)
    assert summary.evaluated == 1
    assert summary.accuracy_pct == 0.0  # it was a 1-1 draw, not the March 4-0


def test_a_prediction_generated_after_kickoff_never_counts():
    late = _pred(generated="2026-01-10T18:00:00.000Z")
    summary = compute_calibration([late], [_played("Arsenal", "Chelsea", 2, 0)])
    assert (summary.evaluated, summary.pending) == (0, 0)


def test_only_the_newest_pre_kickoff_prediction_of_a_match_counts():
    older = _pred(generated="2026-01-01T10:00:00.000Z", blended=(10, 10, 80))
    newer = _pred(generated="2026-01-09T10:00:00.000Z", blended=(70, 20, 10))
    summary = compute_calibration([older, newer], [_played("Arsenal", "Chelsea", 2, 0)])
    assert summary.evaluated == 1
    assert summary.accuracy_pct == 100.0  # scored on the newer 70/20/10


def test_each_method_is_scored_separately_and_the_headline_is_the_blended_one():
    pred = _pred(blended=(50, 30, 20), market_implied=(70, 20, 10), heuristic_blend=(20, 30, 50))
    summary = compute_calibration([pred], [_played("Arsenal", "Chelsea", 2, 0)])
    by = {m.method: m for m in summary.by_method}
    assert set(by) == {"blended", "market_implied", "heuristic_blend"}
    assert by["market_implied"].brier_score < by["blended"].brier_score < by["heuristic_blend"].brier_score
    assert summary.brier_score == by["blended"].brier_score


def test_scores_average_across_several_matches():
    preds = [_pred(home="A", away="B"), _pred(home="C", away="D", blended=(20, 30, 50))]
    matches = [_played("A", "B", 1, 0), _played("C", "D", 1, 0)]
    summary = compute_calibration(preds, matches)
    assert summary.evaluated == 2
    assert summary.accuracy_pct == 50.0
    assert summary.by_method[0].sample_size == 2


def test_malformed_or_incomplete_records_are_ignored_not_fatal():
    junk = [{}, {"home_team": "A"}, _pred(blended=None), {"home_team": "A", "away_team": "B", "kickoff_utc": "2026-01-10T15:00:00.000Z", "generated_at": "2026-01-01T00:00:00.000Z", "prediction": {"blended": {"home_win_pct": "x"}}}]
    summary = compute_calibration(junk, [_played("Arsenal", "Chelsea", 2, 0), _played("A", "B", 1, 0)])
    assert summary.brier_score is None
    assert summary.evaluated == 0


def test_no_predictions_at_all_gives_an_empty_summary_with_an_explanation():
    summary = compute_calibration([], [])
    assert (summary.evaluated, summary.pending, summary.by_method) == (0, 0, [])
    assert summary.note


# --- wiring: run_search and the report JSON -----------------------------------------------------


def test_score_past_predictions_is_none_without_predictions_and_never_raises(monkeypatch):
    from football import orchestrate
    from football.fetch_log import capture_failures

    # No history: still a real CalibrationSummary with evaluated=0 and an
    # explanatory note, not null with no reason.
    empty = orchestrate._score_past_predictions(None, {})
    assert empty is not None
    assert empty.evaluated == 0
    assert empty.note

    scored = orchestrate._score_past_predictions([_pred()], {"sofascore": [_played("Arsenal", "Chelsea", 2, 0)]})
    assert scored.evaluated == 1

    monkeypatch.setattr(orchestrate, "compute_calibration", lambda *_a: (_ for _ in ()).throw(KeyError("kickoff_utc")))
    seen = []
    with capture_failures(seen.append):
        failed = orchestrate._score_past_predictions([_pred()], {})
    assert failed is not None
    assert failed.evaluated == 0
    assert [f.source for f in seen] == ["calibration"]


def test_the_report_json_carries_the_calibration_block_or_none():
    from football.orchestrate import RunSearchResult
    from football.report import build_report_json

    base = dict(
        team="Arsenal", generated_at="2026-01-01T00:00:00.000Z", statuses=[], merged=None, opponent_name=None, form=None, form_source=None,
        opponent_form=None, opponent_form_source=None, merged_profile=None, opponent_profile=None, insights=None, venue_details=None,
    )
    assert build_report_json(RunSearchResult(**base))["calibration"] is None
    summary = compute_calibration([_pred()], [_played("Arsenal", "Chelsea", 2, 0)])
    report = build_report_json(RunSearchResult(**base, calibration=summary))
    assert report["calibration"]["evaluated"] == 1
    assert report["calibration"]["by_method"][0]["method"] == "blended"
