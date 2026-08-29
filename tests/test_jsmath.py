from football._jsmath import js_number_to_string, js_round, js_round_to, js_to_fixed


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
