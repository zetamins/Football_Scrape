from football.prediction import compute_match_prediction
from football.types import BettingOdds, EloRating, SeasonXGEstimate, SquadStrengthInfo


def _elo(value: float) -> EloRating:
    return EloRating(elo=value, as_of="2026-01-01")


def _odds(home_fair_pct, draw_fair_pct, away_fair_pct) -> BettingOdds:
    # compute_match_prediction reads the de-vigged fair_pct fields, not
    # the raw implied_pct fields (which sum to the overround, not 100%).
    return BettingOdds(
        home_win_odds=None, draw_odds=None, away_win_odds=None,
        home_win_implied_pct=None, draw_implied_pct=None, away_win_implied_pct=None,
        over_2_5_odds=None, under_2_5_odds=None,
        home_win_fair_pct=home_fair_pct, draw_fair_pct=draw_fair_pct, away_win_fair_pct=away_fair_pct,
    )


def _xg(xg_for: float, xg_against: float, sample_size: int = 10) -> SeasonXGEstimate:
    return SeasonXGEstimate(
        sample_size=sample_size, xg_for=xg_for, xg_against=xg_against,
        actual_goals_for=0, actual_goals_against=0, source="fotmob",
    )


def _strength(total_value: float, available_value: float) -> SquadStrengthInfo:
    return SquadStrengthInfo(
        total_value=total_value, attack_value=None, midfield_value=None,
        defense_value=None, goalkeeper_value=None, available_value=available_value,
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


# -- rest-day adjustment --------------------------------------------------

def test_more_rested_home_team_gets_a_higher_win_share_than_equal_rest():
    baseline = compute_match_prediction(None, _elo(1500), _elo(1500), 3, 3).heuristic_blend
    rested = compute_match_prediction(None, _elo(1500), _elo(1500), 6, 1).heuristic_blend
    assert rested.home_win_pct > baseline.home_win_pct
    assert rested.away_win_pct < baseline.away_win_pct


def test_rest_adjustment_is_capped_not_unbounded():
    # 5 days' worth (the cap) vs. a much larger 20-day gap should land on
    # the same probabilities -- proves the cap actually engages rather
    # than just being a documentation comment.
    capped = compute_match_prediction(None, _elo(1500), _elo(1500), 8, 3).heuristic_blend
    far_beyond_cap = compute_match_prediction(None, _elo(1500), _elo(1500), 28, 3).heuristic_blend
    assert capped.home_win_pct == far_beyond_cap.home_win_pct


def test_missing_rest_days_leaves_heuristic_blend_unchanged():
    baseline = compute_match_prediction(None, _elo(1500), _elo(1500)).heuristic_blend
    with_partial_data = compute_match_prediction(None, _elo(1500), _elo(1500), 6, None).heuristic_blend
    assert baseline.home_win_pct == with_partial_data.home_win_pct


# -- availability (injury) adjustment --------------------------------------

def test_team_missing_squad_value_gets_a_lower_win_share():
    full_strength = compute_match_prediction(
        None, _elo(1500), _elo(1500), home_squad_strength=_strength(100_000_000, 100_000_000),
    ).heuristic_blend
    depleted = compute_match_prediction(
        None, _elo(1500), _elo(1500), home_squad_strength=_strength(100_000_000, 60_000_000),
    ).heuristic_blend
    assert depleted.home_win_pct < full_strength.home_win_pct


def test_availability_penalty_is_capped():
    half_missing = compute_match_prediction(
        None, _elo(1500), _elo(1500), home_squad_strength=_strength(100_000_000, 50_000_000),
    ).heuristic_blend
    almost_all_missing = compute_match_prediction(
        None, _elo(1500), _elo(1500), home_squad_strength=_strength(100_000_000, 1_000_000),
    ).heuristic_blend
    # Both exceed the fraction where the cap engages (60 Elo points), so
    # they should land on the same result, not scale further down.
    assert half_missing.home_win_pct == almost_all_missing.home_win_pct


def test_zero_total_value_does_not_crash_or_apply_a_penalty():
    result = compute_match_prediction(
        None, _elo(1500), _elo(1500), home_squad_strength=_strength(0, 0),
    ).heuristic_blend
    baseline = compute_match_prediction(None, _elo(1500), _elo(1500)).heuristic_blend
    assert result.home_win_pct == baseline.home_win_pct


def test_unknown_available_value_does_not_apply_a_penalty():
    # total_value known but available_value unknown -- can't compute a
    # missing fraction without both, so no penalty rather than a
    # fabricated one.
    result = compute_match_prediction(
        None, _elo(1500), _elo(1500), home_squad_strength=_strength(100_000_000, None),
    ).heuristic_blend
    baseline = compute_match_prediction(None, _elo(1500), _elo(1500)).heuristic_blend
    assert result.home_win_pct == baseline.home_win_pct


# -- xg_model (Poisson) ----------------------------------------------------

def test_xg_model_none_when_either_teams_xg_missing():
    # odds also passed so the overall result isn't None outright (that
    # "nothing at all available" case is covered separately above) --
    # this test is specifically about xg_model staying None when only
    # one side's xG estimate exists.
    result = compute_match_prediction(_odds(50.0, 25.0, 25.0), None, None, home_xg=_xg(15.0, 10.0))
    assert result.xg_model is None


def test_xg_model_equal_attack_and_defense_still_favors_home_via_home_advantage():
    # Same rates both sides -- only _HOME_ADVANTAGE_GOALS should separate them.
    result = compute_match_prediction(None, None, None, home_xg=_xg(15.0, 12.0), away_xg=_xg(15.0, 12.0))
    m = result.xg_model
    assert m is not None
    assert m.home_win_pct > m.away_win_pct
    assert abs((m.home_win_pct + m.draw_pct + m.away_win_pct) - 100.0) < 0.5


def test_xg_model_stronger_attack_and_weaker_opponent_defense_favors_that_side():
    # Home team scores a lot (18/10), away team concedes a lot (25/10) --
    # both push the same direction, so home should be heavily favored.
    result = compute_match_prediction(
        None, None, None,
        home_xg=_xg(xg_for=18.0, xg_against=8.0, sample_size=10),
        away_xg=_xg(xg_for=6.0, xg_against=25.0, sample_size=10),
    )
    m = result.xg_model
    assert m.home_win_pct > 70.0


def test_xg_model_zero_sample_size_returns_none_not_a_divide_by_zero():
    result = compute_match_prediction(
        None, None, None, home_xg=_xg(0.0, 0.0, sample_size=0), away_xg=_xg(15.0, 12.0),
    )
    assert result is None


def test_all_three_methods_populate_independently():
    result = compute_match_prediction(
        _odds(50.0, 25.0, 25.0),
        _elo(1500), _elo(1500),
        home_xg=_xg(15.0, 12.0), away_xg=_xg(14.0, 13.0),
    )
    assert result.market_implied is not None
    assert result.heuristic_blend is not None
    assert result.xg_model is not None


# --- model name / expected goals / likely scorelines / goal markets -------------------


def test_model_name_lists_only_the_methods_that_ran():
    only_heuristic = compute_match_prediction(None, _elo(1500), _elo(1500))
    assert only_heuristic.model == "heuristic"

    market_and_xg = compute_match_prediction(
        _odds(50.0, 25.0, 25.0), None, None, home_xg=_xg(15.0, 12.0), away_xg=_xg(14.0, 13.0),
    )
    assert market_and_xg.model == "market+xg"

    all_three = compute_match_prediction(
        _odds(50.0, 25.0, 25.0), _elo(1500), _elo(1500), home_xg=_xg(15.0, 12.0), away_xg=_xg(14.0, 13.0),
    )
    assert all_three.model == "market+heuristic+xg"


def test_expected_goals_and_extras_none_without_xg_model():
    result = compute_match_prediction(_odds(50.0, 25.0, 25.0), None, None)
    assert result.home_expected_goals is None
    assert result.away_expected_goals is None
    assert result.likely_scorelines is None
    assert result.goal_markets is None


def test_expected_goals_and_scorelines_populate_with_xg_model():
    result = compute_match_prediction(
        None, None, None, home_xg=_xg(20.0, 10.0, sample_size=10), away_xg=_xg(10.0, 20.0, sample_size=10),
    )
    assert result.home_expected_goals > result.away_expected_goals
    assert len(result.likely_scorelines) == 3
    # Scorelines are sorted most-likely first.
    probs = [s.probability_pct for s in result.likely_scorelines]
    assert probs == sorted(probs, reverse=True)


def test_goal_markets_sum_to_100():
    result = compute_match_prediction(
        None, None, None, home_xg=_xg(20.0, 10.0, sample_size=10), away_xg=_xg(15.0, 15.0, sample_size=10),
    )
    gm = result.goal_markets
    assert round(gm.over_2_5_pct + gm.under_2_5_pct, 1) == 100.0
    assert round(gm.btts_yes_pct + gm.btts_no_pct, 1) == 100.0


def test_goal_markets_high_scoring_teams_favor_over_and_btts():
    result = compute_match_prediction(
        None, None, None, home_xg=_xg(30.0, 25.0, sample_size=10), away_xg=_xg(28.0, 22.0, sample_size=10),
    )
    assert result.goal_markets.over_2_5_pct > 50.0
    assert result.goal_markets.btts_yes_pct > 50.0
