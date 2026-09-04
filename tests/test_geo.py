from football.geo import (
    country_distance_km,
    country_timezone_diff_hours,
    travel_time_hours,
)


def test_distance_unknown_country_is_none():
    assert country_distance_km("England", "Narnia") is None


def test_distance_same_country_is_zero():
    assert country_distance_km("England", "England") == 0


def test_distance_known_pair_roughly_correct():
    # London to Paris is ~344km great-circle.
    km = country_distance_km("England", "France")
    assert km is not None
    assert 330 <= km <= 360


def test_timezone_diff_unknown_is_none():
    assert country_timezone_diff_hours("England", "Narnia") is None


def test_timezone_diff_known_pair():
    assert country_timezone_diff_hours("England", "Japan") == 9.0
    assert country_timezone_diff_hours("Japan", "England") == 9.0


def test_travel_time_short_distance_is_ground():
    # 100/80 = 1.25 exactly, rounded per JS toFixed(1) tie-break (towards
    # +Infinity, i.e. 1.3) -- not Python's native round-half-to-even (1.2).
    assert travel_time_hours(100) == 1.3


def test_travel_time_long_distance_is_air_plus_overhead():
    assert travel_time_hours(850) == 3.0
