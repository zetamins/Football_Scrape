import math
import json
import random
from datetime import date

import pytest

from football import history_model, history_train
from football.history_model import FittedModel, expected_goals, predict_grid, score_grid
from football.history_train import Match, backtest, fit, outcome_probs, parse_archive
from football.prediction import compute_match_prediction


def _synthetic(n=1500, seed=3):
    """Strong > mid > weak, home advantage, deterministic."""
    rng = random.Random(seed)
    strength = {"strong": 1.0, "mid": 0.0, "weak": -1.0}
    teams = list(strength)
    out = []
    for k in range(n):
        h, a = rng.sample(teams, 2)
        lam_h = 1.3 * 2.718 ** (0.25 + 0.4 * (strength[h] - strength[a]) * 0.5)
        lam_a = 1.3 * 2.718 ** (-0.4 * (strength[h] - strength[a]) * 0.5)
        goals = lambda lam: sum(1 for _ in range(12) if rng.random() < lam / 12)
        out.append(Match(date(2018, 1, 1).fromordinal(date(2018, 1, 1).toordinal() + k * 2), h, a, goals(lam_h), goals(lam_a), "Qualifier", False))
    return out


def test_parse_archive_skips_unplayed_and_normalises_names():
    text = (
        "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
        "2026-01-01,Türkiye,Spain,1,2,Friendly,X,Y,FALSE\n"
        "2026-12-01,Spain,France,,,Friendly,X,Y,TRUE\n"
    )
    matches = parse_archive(text)
    assert len(matches) == 1
    assert matches[0].home == "turkey" and matches[0].neutral is False


def test_fit_orders_teams_by_strength_and_finds_home_advantage():
    model = fit(_synthetic(), date(2026, 1, 1), half_life_years=50, start_year=2000)
    assert model.attack["strong"] > model.attack["mid"] > model.attack["weak"]
    assert model.defence["strong"] > model.defence["weak"]
    assert model.home_adv > 0.1


def test_score_grid_is_a_distribution_with_dixon_coles_correction():
    grid = score_grid(1.4, 1.1, -0.1)
    assert abs(sum(grid.values()) - 1) < 1e-9
    plain = score_grid(1.4, 1.1, 0.0)
    assert grid[(0, 0)] != plain[(0, 0)]


def test_expected_goals_unknown_team_none_and_rates_clamped():
    model = FittedModel(mu=0.2, home_adv=0.2, rho=0.0, attack={"a": 9.0, "b": -9.0}, defence={"a": 9.0, "b": -9.0}, as_of="x", matches_used=1)
    assert expected_goals(model, "a", "zzz") is None
    hr, ar = expected_goals(model, "a", "b")
    assert hr == 6.0 and ar >= 0.1
    assert abs(sum(score_grid(hr, ar, 0.0).values()) - 1) < 1e-9


def test_neutral_venue_removes_home_advantage():
    model = FittedModel(mu=0.2, home_adv=0.3, rho=0.0, attack={"a": 0.0, "b": 0.0}, defence={"a": 0.0, "b": 0.0}, as_of="x", matches_used=1)
    assert expected_goals(model, "a", "b", neutral=True)[0] < expected_goals(model, "a", "b")[0]
    assert expected_goals(model, "a", "b", neutral=True)[0] == expected_goals(model, "b", "a", neutral=True)[0]


def test_backtest_never_scores_with_a_model_that_saw_the_match():
    matches = _synthetic(n=900)
    cutoff = matches[600].day
    result = backtest(matches, cutoff, None, 6, half_life_years=50, ridge=1.0, start_year=2000)
    assert result["n"] > 0
    # Trained on the past only, a real model beats uniform; leakage would make it implausibly good.
    assert result["model"] < result["uniform"]
    assert result["model"] > 0.3


def test_load_model_missing_file_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(history_model, "_model_path", lambda: tmp_path / "nope.json")
    history_model.load_model.cache_clear()
    try:
        assert history_model.load_model() is None
        assert predict_grid("Spain", "France") is None
    finally:
        history_model.load_model.cache_clear()


def test_written_model_round_trips(tmp_path, monkeypatch):
    path = tmp_path / "m.json"
    monkeypatch.setattr(history_model, "_model_path", lambda: path)
    history_model.load_model.cache_clear()
    model = fit(_synthetic(400), date(2026, 1, 1), half_life_years=50, start_year=2000)
    history_train.write_model(model)
    try:
        loaded = history_model.load_model()
        assert loaded.attack.keys() == model.attack.keys()
        assert abs(loaded.mu - model.mu) < 1e-4
    finally:
        history_model.load_model.cache_clear()


@pytest.fixture
def seeded_model(tmp_path, monkeypatch):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({
        "as_of": "2026-09-01", "mu": 0.2, "home_adv": 0.25, "rho": -0.03, "matches_used": 10,
        "attack": {"Spain": 0.8, "Gibraltar": -0.7}, "defence": {"Spain": 0.8, "Gibraltar": -0.7},
    }), encoding="utf-8")
    monkeypatch.setattr(history_model, "_model_path", lambda: path)
    history_model.load_model.cache_clear()
    yield
    history_model.load_model.cache_clear()


def test_prediction_uses_history_model_and_its_grid_when_both_teams_known(seeded_model):
    result = compute_match_prediction(None, None, None, home_team="Spain", away_team="Gibraltar")
    assert result.history_model.home_win_pct > 80
    assert result.model == "history"
    assert result.home_expected_goals > 2 > result.away_expected_goals
    assert {s.outcome for s in result.likely_scorelines} == {"home_win", "draw", "away_win"}


def test_prediction_ignores_history_for_unknown_or_missing_teams(seeded_model):
    assert compute_match_prediction(None, None, None, home_team="Spain", away_team="Real Madrid") is None
    assert compute_match_prediction(None, None, None) is None


def test_outcome_probs_sum_to_one(seeded_model):
    p = outcome_probs(history_model.load_model(), "Spain", "Gibraltar", False)
    assert abs(sum(p) - 1) < 1e-9


def test_tournament_categories_and_non_fifa_exclusion():
    from football.history_train import tournament_category

    assert tournament_category("Friendly") == "friendly"
    assert tournament_category("FIFA World Cup qualification") == "qualifier"
    assert tournament_category("UEFA Nations League") == "nations_league"
    assert tournament_category("CONCACAF Nations League qualification") == "qualifier"
    assert tournament_category("FIFA World Cup") == "major"
    assert tournament_category("Copa América") == "major"
    assert tournament_category("COSAFA Cup") == "other"
    assert tournament_category("CONIFA World Football Cup") == "nonfifa"
    assert tournament_category("Island Games") == "nonfifa"


def test_fit_ignores_non_fifa_matches_and_honours_tournament_weights():
    matches = _synthetic(600) + [Match(date(2025, 1, 1), "padania", "mid", 9, 0, "CONIFA World Football Cup", False)]
    model = fit(matches, date(2026, 1, 1), half_life_years=50, start_year=2000)
    assert "padania" not in model.attack
    with pytest.raises(ValueError):
        fit(_synthetic(600), date(2026, 1, 1), half_life_years=50, start_year=2000, tournament_weights={"other": 0.0})
    mixed = [Match(m.day, m.home, m.away, m.hg, m.ag, "Friendly" if k % 2 else m.tournament, False) for k, m in enumerate(_synthetic(600))]
    full = fit(mixed, date(2026, 1, 1), half_life_years=50, start_year=2000)
    friendlies_muted = fit(mixed, date(2026, 1, 1), half_life_years=50, start_year=2000, tournament_weights={"friendly": 0.0})
    assert full.matches_used == friendlies_muted.matches_used
    assert full.mu != friendlies_muted.mu


# ---------------------------------------------------------------- venue model (basic / split / confed)
def _venue_matches():
    """Two confederations; in 'AF' hosts win far more than in 'EU', neutral-venue listed-home sides get a boost."""
    rng = random.Random(11)
    teams = {"AF": ["a1", "a2", "a3", "a4"], "EU": ["e1", "e2", "e3", "e4"]}
    out = []
    for k in range(3000):
        conf = "AF" if k % 2 else "EU"
        h, a = rng.sample(teams[conf], 2)
        neutral = rng.random() < 0.25
        lam_h = 1.3 * (2.718 ** (0.15 if neutral else (0.5 if conf == "AF" else 0.15)))
        lam_a = 1.1 * (1.0 if neutral else (0.55 if conf == "AF" else 0.9))
        g = lambda lam: sum(1 for _ in range(14) if rng.random() < lam / 14)
        out.append(Match(date.fromordinal(date(2016, 1, 1).toordinal() + k), h, a, g(lam_h), g(lam_a), "AFC Asian Cup qualification" if conf == "AF" else "UEFA Euro qualification", neutral))
    return out


def test_infer_confederations_from_regional_tournaments_ignoring_friendlies():
    from football.history_train import infer_confederations

    ms = [Match(date(2020, 1, 1), "x", "y", 1, 0, "Friendly", False), Match(date(2020, 1, 2), "x", "y", 1, 0, "African Cup of Nations qualification", False),
          Match(date(2020, 1, 3), "z", "w", 1, 0, "FIFA World Cup", True), Match(date(2020, 1, 4), "z", "w", 1, 0, "CONCACAF Nations League", False),
          Match(date(2020, 1, 5), "p", "q", 0, 0, "UEFA Nations League", False)]
    c = infer_confederations(ms)
    assert c["x"] == "CAF" and c["z"] == "CONCACAF" and c["p"] == "UEFA" and "q" in c
    assert infer_confederations([ms[0], ms[2]]) == {}


def test_venue_modes_recover_confederation_specific_home_effects():
    ms = _venue_matches()
    basic = fit(ms, date(2030, 1, 1), half_life_years=50, start_year=2000, venue="basic")
    confed = fit(ms, date(2030, 1, 1), half_life_years=50, start_year=2000, venue="confed")
    split = fit(ms, date(2030, 1, 1), half_life_years=50, start_year=2000, venue="split")
    assert basic.away_adv == 0.0 and not basic.confed and not basic.home_dev
    assert split.away_adv < 0 and split.neutral_adv > 0 and not split.confed
    assert confed.confed["a1"] == confed.confed["a3"] != confed.confed["e1"] or confed.confed["a1"] != confed.confed["e1"]
    caf = confed.confed["a1"]; eu = confed.confed["e1"]
    assert confed.home_dev[caf] > confed.home_dev[eu] and confed.away_dev[caf] < confed.away_dev[eu]      # the African host boost is larger, the visitor drag deeper


def test_expected_goals_uses_the_hosts_confederation_and_neutral_label_boost():
    model = FittedModel(mu=0.2, home_adv=0.2, rho=0.0, attack={"a": 0.0, "b": 0.0}, defence={"a": 0.0, "b": 0.0}, as_of="x", matches_used=1,
                        neutral_adv=0.1, away_adv=-0.05, home_dev={"CAF": 0.15, "UEFA": -0.1}, away_dev={"CAF": -0.1, "UEFA": 0.05}, confed={"a": "CAF", "b": "UEFA"})
    ha, aa = expected_goals(model, "a", "b")               # a hosts, in CAF
    hb, ab = expected_goals(model, "b", "a")               # b hosts, in UEFA
    assert ha > hb and aa < ab
    nh, na = expected_goals(model, "a", "b", neutral=True)
    assert nh == pytest.approx(math.exp(0.2 + 0.1)) and na == pytest.approx(math.exp(0.2))
    assert expected_goals(model, "a", "zzz") is None
    plain = FittedModel(mu=0.2, home_adv=0.2, rho=0.0, attack={"a": 0.0, "b": 0.0}, defence={"a": 0.0, "b": 0.0}, as_of="x", matches_used=1)
    assert expected_goals(plain, "a", "b")[0] == pytest.approx(math.exp(0.4)) and expected_goals(plain, "a", "b")[1] == pytest.approx(math.exp(0.2))   # old files: unchanged


def test_venue_fields_round_trip_through_the_json_file(tmp_path, monkeypatch):
    path = tmp_path / "m.json"
    monkeypatch.setattr(history_model, "_model_path", lambda: path)
    history_model.load_model.cache_clear()
    model = fit(_venue_matches(), date(2030, 1, 1), half_life_years=50, start_year=2000)        # default venue = confed
    assert model.confed and model.home_dev
    history_train.write_model(model)
    try:
        loaded = history_model.load_model()
        assert loaded.confed == model.confed and loaded.away_adv == pytest.approx(model.away_adv, abs=1e-4)
        assert loaded.home_dev.keys() == model.home_dev.keys()
        assert expected_goals(loaded, "a1", "a2") == pytest.approx(expected_goals(model, "a1", "a2"), rel=1e-3)
    finally:
        history_model.load_model.cache_clear()
