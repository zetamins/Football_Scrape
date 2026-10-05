import json

import pytest

from football import national_elo
from football.national_elo import lookup_national_elo, parse_tables


@pytest.fixture(autouse=True)
def _seed(tmp_path, monkeypatch):
    path = tmp_path / "national-elo.json"
    path.write_text(json.dumps({"source": "eloratings.net", "as_of": "2026-10-03", "ratings": {
        "Spain": 2281, "Turkey": 1781, "Ivory Coast": 1700, "Bosnia and Herzegovina": 1655, "Congo": 1207,
        "DR Congo": 1693, "Czechia": 1659, "Niger": 1371, "Nigeria": 1706, "Ireland": 1717,
    }}), encoding="utf-8")
    monkeypatch.setattr(national_elo, "_cache_path", lambda: path)
    national_elo._load.cache_clear()
    yield
    national_elo._load.cache_clear()


def test_exact_and_diacritic_names_resolve():
    assert lookup_national_elo("Spain") == (2281.0, "2026-10-03")
    assert lookup_national_elo("Türkiye")[0] == 1781.0


def test_source_spellings_resolve_through_aliases():
    assert lookup_national_elo("Côte d'Ivoire")[0] == 1700.0
    assert lookup_national_elo("Bosnia & Herzegovina")[0] == 1655.0
    assert lookup_national_elo("Congo Republic")[0] == 1207.0


def test_no_substring_matching_between_similar_names():
    assert lookup_national_elo("DR Congo")[0] == 1693.0
    assert lookup_national_elo("Niger")[0] == 1371.0
    assert lookup_national_elo("Nigeria")[0] == 1706.0
    assert lookup_national_elo("Congo DR") is None


def test_clubs_womens_sides_and_blank_do_not_match():
    assert lookup_national_elo("Barcelona") is None
    assert lookup_national_elo("Spain Women") is None
    assert lookup_national_elo("Spain U21") is None
    assert lookup_national_elo(None) is None
    assert lookup_national_elo("") is None


def test_missing_cache_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(national_elo, "_cache_path", lambda: tmp_path / "nope.json")
    national_elo._load.cache_clear()
    assert lookup_national_elo("Spain") is None


def test_parse_tables_maps_codes_to_names_and_skips_bad_rows():
    world = "1\t1\tES\t2281\t1\n2\t2\tAR\tnotanumber\n3\t3\tXX\t1500\n"
    teams = "ES\tSpain\tKingdom of Spain\nAR\tArgentina\n"
    assert parse_tables(world, teams) == {"Spain": 2281, "XX": 1500}


def test_refresh_refuses_to_overwrite_with_a_tiny_table(monkeypatch):
    monkeypatch.setattr(national_elo, "_get", lambda path: "1\t1\tES\t2281\n" if "World" in path else "ES\tSpain\n")
    with pytest.raises(RuntimeError):
        national_elo.refresh()
