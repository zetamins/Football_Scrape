from football.format_markdown import prediction_str
from football.types import MatchPrediction, OutcomeProbabilities


def _probs(home, draw, away):
    return OutcomeProbabilities(home_win_pct=home, draw_pct=draw, away_win_pct=away)


def test_market_implied_labeled_as_primary_when_both_available():
    p = MatchPrediction(market_implied=_probs(60, 25, 15), heuristic_blend=_probs(55, 25, 20))
    lines = prediction_str(p, "Home FC", "Away FC")
    assert "primary" in lines[0]
    assert "not a trained model" in lines[1]
    assert "no market odds" not in lines[1]


def test_heuristic_notes_it_is_the_only_estimate_when_no_market_odds():
    p = MatchPrediction(market_implied=None, heuristic_blend=_probs(55, 25, 20))
    lines = prediction_str(p, "Home FC", "Away FC")
    assert len(lines) == 1
    assert "no market odds available" in lines[0]


def test_flags_disagreement_when_methods_favor_different_sides():
    # Market favors home, heuristic favors away.
    p = MatchPrediction(market_implied=_probs(50, 20, 30), heuristic_blend=_probs(35, 25, 40))
    lines = prediction_str(p, "Home FC", "Away FC")
    assert len(lines) == 3
    assert "disagree" in lines[2]


def test_flags_disagreement_when_same_side_favored_but_gap_exceeds_15_points():
    p = MatchPrediction(market_implied=_probs(71.7, 17.4, 10.9), heuristic_blend=_probs(49.2, 24.1, 26.6))
    lines = prediction_str(p, "Home FC", "Away FC")
    assert len(lines) == 3
    assert "disagree" in lines[2]


def test_no_disagreement_note_when_methods_roughly_agree():
    p = MatchPrediction(market_implied=_probs(52, 26, 22), heuristic_blend=_probs(48, 27, 25))
    lines = prediction_str(p, "Home FC", "Away FC")
    assert len(lines) == 2
