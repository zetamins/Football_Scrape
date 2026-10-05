import json
import random
from datetime import date

import pytest

from football import history_model, history_train
from football.history_model import (
    PI_BLEND_WEIGHT, FittedModel, PiModel, blended_outcome, pi_features, pi_probabilities, predict_outcome,
)
from football.history_train import Match, fit_full, fit_pi
from football.pi_ratings import PiRatings


def test_winner_gains_and_loser_drops_with_cross_update():
    pi = PiRatings()
    pi.update("a", "b", 3, 0, neutral=False)
    assert pi.home["a"] > 0 > pi.away["b"]
    assert pi.away["a"] == pytest.approx(pi.gamma * pi.home["a"])   # home rating result also nudges away rating
    assert pi.home["b"] == pytest.approx(pi.gamma * pi.away["b"])


def test_expected_result_barely_moves_ratings_and_surprises_move_more():
    big = PiRatings(); big.update("a", "b", 4, 0, False)
    small = PiRatings(); small.update("a", "b", 1, 0, False)
    assert big.home["a"] > small.home["a"] > 0
    pi = PiRatings()
    for _ in range(40):
        pi.update("a", "b", 2, 0, False)
    before = pi.home["a"]
    pi.update("a", "b", 2, 0, False)           # now expected -> tiny change
    assert abs(pi.home["a"] - before) < 0.02


def test_neutral_venue_moves_both_ratings_of_a_team_equally():
    pi = PiRatings(); pi.update("a", "b", 2, 0, neutral=True)
    assert pi.home["a"] == pytest.approx(pi.away["a"]) and pi.home["b"] == pytest.approx(pi.away["b"])


def test_pre_does_not_mutate_state():
    pi = PiRatings(); pi.update("a", "b", 1, 0, False)
    snapshot = (dict(pi.home), dict(pi.away))
    pi.pre("a", "b", False); pi.pre("a", "zzz", True)
    assert (pi.home, pi.away) == snapshot


def test_pi_features_none_for_unrated_team_and_neutral_zeroes_home_advantage():
    elo = {"a": 1500.0, "b": 1500.0}
    assert pi_features({}, {}, elo, "a", "zzz", False) is None
    home = pi_features({}, {}, elo, "a", "b", False)
    neutral = pi_features({}, {}, elo, "a", "b", True)
    assert home[5] == pytest.approx(100 / 400) and neutral[5] == 0 and neutral[6] == 1.0 and home[6] == 0.0


def _tiny_pi_model(w_home_bias=2.0):
    # one feature set standardised to mean 0 / std 1; home-class bias dominates
    return PiModel(pi_home={"a": 0.0, "b": 0.0}, pi_away={"a": 0.0, "b": 0.0}, elo={"a": 1500.0, "b": 1500.0},
                   mean=[0.0] * 7, std=[1.0] * 7, weights=[[w_home_bias] + [0.0] * 7, [0.0] * 8, [0.0] * 8])


def _model(pi):
    return FittedModel(mu=0.2, home_adv=0.25, rho=0.0, attack={"a": 0.0, "b": 0.0}, defence={"a": 0.0, "b": 0.0},
                       as_of="x", matches_used=1, pi=pi)


def test_pi_probabilities_sum_to_one_and_follow_weights():
    p = pi_probabilities(_model(_tiny_pi_model()), "a", "b")
    assert sum(p) == pytest.approx(1.0) and p[0] > 0.7
    assert pi_probabilities(_model(None), "a", "b") is None
    assert pi_probabilities(_model(_tiny_pi_model()), "a", "zzz") is None


def test_blend_uses_configured_weight_and_falls_back_to_poisson():
    poisson = (0.5, 0.3, 0.2)
    model = _model(_tiny_pi_model())
    pi = pi_probabilities(model, "a", "b")
    mixed = blended_outcome(model, "a", "b", False, poisson)
    for got, a, b in zip(mixed, poisson, pi):
        assert got == pytest.approx((1 - PI_BLEND_WEIGHT) * a + PI_BLEND_WEIGHT * b)
    assert blended_outcome(_model(None), "a", "b", False, poisson) == poisson
    assert blended_outcome(model, "a", "zzz", False, poisson) == poisson


def _synthetic(n=900, seed=5):
    rng = random.Random(seed)
    strength = {"strong": 1.0, "mid": 0.0, "weak": -1.0}
    out = []
    for k in range(n):
        h, a = rng.sample(list(strength), 2)
        lam_h = 1.3 * 2.718 ** (0.25 + 0.2 * (strength[h] - strength[a])); lam_a = 1.3 * 2.718 ** (-0.2 * (strength[h] - strength[a]))
        g = lambda lam: sum(1 for _ in range(12) if rng.random() < lam / 12)
        out.append(Match(date.fromordinal(date(2011, 1, 1).toordinal() + k * 3), h, a, g(lam_h), g(lam_a), "Qualifier", False))
    return out


def test_fit_pi_learns_that_stronger_teams_win_more_often():
    matches = _synthetic()
    model = fit_pi(matches, date(2030, 1, 1))
    assert model is not None
    full = FittedModel(mu=0.2, home_adv=0.2, rho=0.0, attack={t: 0.0 for t in model.elo}, defence={t: 0.0 for t in model.elo}, as_of="x", matches_used=1, pi=model)
    strong_home = pi_probabilities(full, "strong", "weak")
    weak_home = pi_probabilities(full, "weak", "strong")
    assert strong_home[0] > strong_home[2] and weak_home[2] > weak_home[0]
    assert strong_home[0] > weak_home[0]


def test_fit_pi_returns_none_with_too_little_data():
    assert fit_pi(_synthetic(50), date(2030, 1, 1)) is None


def test_features_use_only_past_matches():
    """Changing the very last match's score must not change the trained model's treatment of earlier rows:
    the model fitted before that match is identical whatever its result."""
    matches = _synthetic(400)
    last = matches[-1]
    flipped = matches[:-1] + [Match(last.day, last.home, last.away, last.ag + 5, last.hg, last.tournament, last.neutral)]
    a = fit_pi(matches, last.day)        # as_of excludes the final match entirely
    b = fit_pi(flipped, last.day)
    assert a.weights == b.weights and a.elo == b.elo


def test_fit_full_round_trips_through_json_and_predict_outcome(tmp_path, monkeypatch):
    path = tmp_path / "m.json"
    monkeypatch.setattr(history_model, "_model_path", lambda: path)
    history_model.load_model.cache_clear()
    model = fit_full(_synthetic(600), date(2030, 1, 1), half_life_years=50, start_year=2000)
    assert model.pi is not None
    history_train.write_model(model)
    try:
        loaded = history_model.load_model()
        assert loaded.pi is not None and loaded.pi.weights[0][0] == pytest.approx(model.pi.weights[0][0], abs=1e-5)
        p = predict_outcome("strong", "weak")
        assert sum(p) == pytest.approx(1.0) and p[0] > p[2]
        assert predict_outcome("strong", "unknown team") is None
    finally:
        history_model.load_model.cache_clear()
