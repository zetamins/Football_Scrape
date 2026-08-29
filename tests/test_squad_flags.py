from football.insights import compute_card_risks, compute_duel_vulnerabilities, compute_fullback_exposure
from football.types import DefensiveStats, SeasonPlayerStats, SquadMember


def _season_stats(yellow=0, red=0, appearances=10) -> SeasonPlayerStats:
    return SeasonPlayerStats(appearances=appearances, goals=0, assists=0, yellow_cards=yellow, red_cards=red, rating=None, expected_goals=None)


def _player(name, role="D", season_stats=None, defensive_stats=None) -> SquadMember:
    return SquadMember(
        name=name, role=role, injury=None, age=25, market_value=None,
        season_stats=season_stats, season_stats_source=None,
        defensive_stats=defensive_stats, recent_usage=None,
    )


def _defensive(chances_created=None, ground_duel_success_pct=None) -> DefensiveStats:
    return DefensiveStats(
        tackles_made=None, interceptions=None, ball_recoveries=None, clearances=None,
        ground_duel_success_pct=ground_duel_success_pct, chances_created=chances_created,
    )


# ---- compute_card_risks ----

def test_card_risks_none_when_no_squad_data_at_all():
    # Distinct from a real, checked "nobody at risk" -- see the bug this
    # fixed earlier this session (both cases used to return the same []).
    assert compute_card_risks(None) is None
    assert compute_card_risks([]) is None


def test_card_risks_real_empty_list_when_squad_checked_and_nobody_qualifies():
    squad = [_player("Safe Player", season_stats=_season_stats(yellow=1, red=0))]
    result = compute_card_risks(squad)
    assert result == []


def test_card_risks_flags_accumulation_and_dismissal():
    squad = [
        _player("Four Yellows", season_stats=_season_stats(yellow=4, red=0)),
        _player("Sent Off", season_stats=_season_stats(yellow=0, red=1)),
        _player("Clean", season_stats=_season_stats(yellow=1, red=0)),
        _player("No Stats", season_stats=None),
    ]
    result = compute_card_risks(squad)
    names = {r.name for r in result}
    assert names == {"Four Yellows", "Sent Off"}


def test_card_risks_sorted_worst_first():
    squad = [
        _player("Two Yellows", season_stats=_season_stats(yellow=4, red=0)),
        _player("Sent Off", season_stats=_season_stats(yellow=0, red=1)),
    ]
    result = compute_card_risks(squad)
    # red_cards weighted x10 in the sort key -- a single red outranks 4 yellows.
    assert result[0].name == "Sent Off"


# ---- compute_duel_vulnerabilities ----

def test_duel_vulnerabilities_none_when_no_squad_data_at_all():
    assert compute_duel_vulnerabilities(None) is None
    assert compute_duel_vulnerabilities([]) is None


def test_duel_vulnerabilities_real_empty_list_when_nobody_below_threshold():
    squad = [_player("Solid CB", defensive_stats=_defensive(ground_duel_success_pct=70))]
    assert compute_duel_vulnerabilities(squad) == []


def test_duel_vulnerabilities_only_flags_defenders_below_50pct():
    squad = [
        _player("Weak CB", role="D", defensive_stats=_defensive(ground_duel_success_pct=35)),
        _player("Weak Striker", role="F", defensive_stats=_defensive(ground_duel_success_pct=20)),
        _player("No Stats CB", role="D", defensive_stats=None),
    ]
    result = compute_duel_vulnerabilities(squad)
    assert [r.name for r in result] == ["Weak CB"]


# ---- compute_fullback_exposure ----

def test_fullback_exposure_none_when_no_squad_data_at_all():
    assert compute_fullback_exposure(None) is None
    assert compute_fullback_exposure([]) is None


def test_fullback_exposure_none_when_fewer_than_two_defenders_have_both_stats():
    squad = [_player("Only CB", role="D", defensive_stats=_defensive(chances_created=3, ground_duel_success_pct=40))]
    assert compute_fullback_exposure(squad) is None


def test_fullback_exposure_flags_above_median_creation_and_below_55pct_duels():
    squad = [
        _player("Attacking FB", role="D", defensive_stats=_defensive(chances_created=5, ground_duel_success_pct=45)),
        _player("Defensive CB", role="D", defensive_stats=_defensive(chances_created=1, ground_duel_success_pct=70)),
    ]
    result = compute_fullback_exposure(squad)
    assert [r.name for r in result] == ["Attacking FB"]
