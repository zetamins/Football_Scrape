import math

from football._jsmath import (
    js_number,
    js_number_or,
    js_number_to_string,
    js_round,
    js_round_to,
    js_to_fixed,
)


def test_js_round_matches_js_math_round_ties():
    # JS Math.round ties towards +Infinity for both signs.
    assert js_round(1.5) == 2
    assert js_round(2.5) == 3
    assert js_round(-1.5) == -1
    assert js_round(-2.5) == -2


def test_js_round_to_exact_half_midpoint():
    # The concrete case caught while porting geo.ts's travelTimeHours.
    assert js_round_to(1.25, 1) == 1.3


def test_js_to_fixed_matches_js_tofixed_string():
    assert js_to_fixed(1.25, 1) == "1.3"
    assert js_to_fixed(2.0, 1) == "2.0"
    assert js_to_fixed(0.12345, 3) == "0.123"


def test_js_number_to_string_drops_trailing_zero():
    # The concrete case caught while porting three65scores.py's standings
    # parsing: String(-1) is "-1" in JS, but str(-1.0) is "-1.0" in Python.
    assert js_number_to_string(-1.0) == "-1"
    assert js_number_to_string(0.0) == "0"
    assert js_number_to_string(3.5) == "3.5"


# --- js_number ------------------------------------------------------------------------------


def test_js_number_none_is_nan():
    assert math.isnan(js_number(None))


def test_js_number_empty_string_is_zero():
    assert js_number("") == 0.0
    assert js_number("   ") == 0.0


def test_js_number_parses_valid_numeric_string():
    assert js_number(" 42.5 ") == 42.5


def test_js_number_unparseable_string_is_nan():
    assert math.isnan(js_number("not a number"))


# --- js_number_or ----------------------------------------------------------------------------


def test_js_number_or_uses_default_for_nan_zero_and_empty():
    assert js_number_or(None, default=7) == 7
    assert js_number_or("not a number", default=7) == 7
    assert js_number_or("0", default=7) == 7
    assert js_number_or("", default=7) == 7


def test_js_number_or_returns_real_nonzero_value():
    assert js_number_or("42.5", default=7) == 42.5


def test_js_number_or_default_is_zero_by_default():
    assert js_number_or(None) == 0
