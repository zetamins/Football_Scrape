from football.prediction import compute_match_prediction
from football.types import BettingOdds, EloRating


def _elo(value: float) -> EloRating:
    return EloRating(elo=value, rank=None, as_of="2026-01-01")


def _odds(home_pct, draw_pct, away_pct) -> BettingOdds:
    return BettingOdds(
        home_win_odds=None, draw_odds=None, away_win_odds=None,
        home_win_implied_pct=home_pct, draw_implied_pct=draw_pct, away_win_implied_pct=away_pct,
        over_2_5_odds=None, under_2_5_odds=None,
    )


def test_returns_none_when_nothing_available():
    assert compute_match_prediction(None, None, None) is None


def test_market_implied_passes_through_odds_percentages():
    result = compute_match_prediction(_odds(60.9, 21.8, 17.3), None, None)
    assert result is not None
    assert result.market_implied.home_win_pct == 60.9
    assert result.market_implied.draw_pct == 21.8
    assert result.market_implied.away_win_pct == 17.3
    assert result.heuristic_blend is None


def test_heuristic_blend_equal_elo_gives_home_team_the_edge():
    # Equal underlying strength -- only the home-advantage constant
    # should separate the two, so home > away, and draw should land near
    # the ~25% average draw rate the Davidson parameter was calibrated to.
    result = compute_match_prediction(None, _elo(1500), _elo(1500))
    assert result is not None
    b = result.heuristic_blend
    assert b.home_win_pct > b.away_win_pct
    assert 20 <= b.draw_pct <= 30
    assert abs((b.home_win_pct + b.draw_pct + b.away_win_pct) - 100.0) < 0.2


def test_heuristic_blend_much_stronger_away_team_still_favors_away():
    # A large enough Elo gap should overcome the fixed +100 home bonus.
    result = compute_match_prediction(None, _elo(1400), _elo(1700))
    assert result is not None
    b = result.heuristic_blend
    assert b.away_win_pct > b.home_win_pct


def test_heuristic_blend_percentages_always_sum_to_100():
    for home_elo, away_elo in [(1500, 1500), (1200, 1800), (1900, 1100), (1500.5, 1499.5)]:
        result = compute_match_prediction(None, _elo(home_elo), _elo(away_elo))
        b = result.heuristic_blend
        assert abs((b.home_win_pct + b.draw_pct + b.away_win_pct) - 100.0) < 0.2


def test_both_methods_populate_independently_when_both_available():
    result = compute_match_prediction(_odds(50.0, 25.0, 25.0), _elo(1500), _elo(1500))
    assert result.market_implied is not None
    assert result.heuristic_blend is not None
