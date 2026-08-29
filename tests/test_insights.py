from football.insights import _parse_xg_stat_value


def test_parses_genuine_zero_xg_as_zero_not_none():
    # Regression test: a prior `float(raw) or None` implementation turned
    # a real 0.0 xG (Python falsy-zero) into a misleading null, silently
    # conflating "the team had 0.00 xG" with "xG wasn't published".
    assert _parse_xg_stat_value("0") == 0.0
    assert _parse_xg_stat_value("0.0") == 0.0


def test_parses_real_nonzero_xg():
    assert _parse_xg_stat_value("1.85") == 1.85


def test_returns_none_for_unparseable_value():
    assert _parse_xg_stat_value("N/A") is None


def test_returns_none_for_missing_value():
    assert _parse_xg_stat_value(None) is None
