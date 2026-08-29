from football.cli import _parse_team_names


def test_single_team_no_comma():
    assert _parse_team_names("Real Madrid") == ["Real Madrid"]


def test_multiple_teams_comma_separated():
    assert _parse_team_names("Real Madrid, Liverpool, Bayern Munich") == [
        "Real Madrid",
        "Liverpool",
        "Bayern Munich",
    ]


def test_extra_whitespace_and_commas_are_ignored():
    assert _parse_team_names(" Real Madrid ,, Liverpool ,") == ["Real Madrid", "Liverpool"]


def test_empty_string_yields_empty_list():
    assert _parse_team_names("") == []
    assert _parse_team_names("   ") == []
