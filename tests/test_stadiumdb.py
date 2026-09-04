import asyncio
import json

from football.sites import stadiumdb
from football.sites.stadiumdb import (
    _build_country_index,
    _CountryEntry,
    _find_club_row,
    _load_country_index,
    _normalize,
    _parse_country_page,
    _parse_stadium_page,
    _resolve_country_code,
    _StadiumRow,
    get_stadium_db_venue_details,
)

# --- _normalize / _resolve_country_code ------------------------------------------------


def test_normalize_strips_punctuation():
    assert _normalize("São Paulo!") == "sao paulo"


def test_resolve_country_code_exact_match():
    entries = [_CountryEntry(code="eng", name="England"), _CountryEntry(code="esp", name="Spain")]
    assert _resolve_country_code(entries, "England") == "eng"


def test_resolve_country_code_uses_alias_table():
    entries = [_CountryEntry(code="usa", name="United States of America")]
    assert _resolve_country_code(entries, "USA") == "usa"


def test_resolve_country_code_partial_match_fallback():
    entries = [_CountryEntry(code="kor", name="South Korea")]
    assert _resolve_country_code(entries, "Korea Republic") == "kor"


def test_resolve_country_code_none_when_no_match():
    assert _resolve_country_code([], "Atlantis") is None


# --- _parse_country_page ------------------------------------------------------------------


def test_parse_country_page_extracts_rows():
    html = (
        '<a href="https://stadiumdb.com/stadiums/eng/emirates" class="nu-reward">Emirates Stadium</a>'
        "</td><td> London </td><td> Arsenal </td>"
        '<td class="figure"> 60 704 </td>'
    )
    rows = _parse_country_page(html)
    assert len(rows) == 1
    assert rows[0].stadium_name == "Emirates Stadium"
    assert rows[0].city == "London"
    assert rows[0].clubs == ["Arsenal"]
    assert rows[0].capacity == 60704


def test_parse_country_page_drops_dash_placeholder_club():
    html = (
        '<a href="https://stadiumdb.com/stadiums/eng/somespeedway" class="nu-reward">Some Speedway</a>'
        "</td><td> City </td><td> - </td>"
        '<td class="figure"> 5000 </td>'
    )
    rows = _parse_country_page(html)
    assert rows[0].clubs == []


def test_parse_country_page_empty_without_matching_rows():
    assert _parse_country_page("<html>no rows here</html>") == []


# --- _find_club_row -------------------------------------------------------------------------


def _row(clubs, capacity=50000, city="City", name="Stadium"):
    return _StadiumRow(url="https://x", stadium_name=name, city=city, clubs=clubs, capacity=capacity)


def test_find_club_row_exact_match():
    rows = [_row(["Arsenal"]), _row(["Chelsea"])]
    result = _find_club_row(rows, "Arsenal")
    assert result.clubs == ["Arsenal"]


def test_find_club_row_exact_match_via_known_alias():
    # team_aliases.py maps "paris saint germain" -> "psg" among others --
    # StadiumDB's own row lists just "PSG", which only matches via that
    # alias, not the full searched name directly.
    rows = [_row(["PSG"]), _row(["Some Other Club"])]
    result = _find_club_row(rows, "Paris Saint Germain")
    assert result is not None
    assert result.clubs == ["PSG"]


def test_find_club_row_fuzzy_match_via_substring():
    rows = [_row(["Manchester United"])]
    result = _find_club_row(rows, "Man United")
    assert result is not None
    assert result.clubs == ["Manchester United"]


def test_find_club_row_disambiguates_multiple_candidates_by_city():
    rows = [
        _row(["Borussia"], capacity=81365, city="Dortmund"),
        _row(["Borussia"], capacity=54014, city="Monchengladbach"),
    ]
    result = _find_club_row(rows, "Borussia Dortmund")
    assert result.city == "Dortmund"


def test_find_club_row_disambiguates_by_largest_capacity_without_city_match():
    rows = [_row(["Borussia"], capacity=10000, city="X"), _row(["Borussia"], capacity=81365, city="Y")]
    result = _find_club_row(rows, "Borussia FC")
    assert result.capacity == 81365


def test_find_club_row_none_without_any_match():
    rows = [_row(["Chelsea"])]
    assert _find_club_row(rows, "Some Totally Unrelated Club") is None


def test_find_club_row_returns_single_fuzzy_candidate_when_no_exact_match_exists(monkeypatch):
    # "arsenal" fuzzy-matches "Arsenal FC" (substring) but not exactly --
    # exercises the single-fuzzy-candidate return path specifically,
    # distinct from the exact-match and multi-candidate-disambiguation
    # paths already covered above.
    monkeypatch.setattr(stadiumdb, "known_aliases_for", lambda _name: ["arsenal"])
    rows = [_row(["Arsenal FC"]), _row(["Chelsea FC"])]
    result = _find_club_row(rows, "Arsenal")
    assert result is not None
    assert result.clubs == ["Arsenal FC"]


# --- _parse_stadium_page ---------------------------------------------------------------------


def test_parse_stadium_page_extracts_all_fields():
    html = (
        '<table class="stadium-info">'
        "<tr><th>Capacity</th><td> 60 704 </td></tr>"
        "<tr><th>Inauguration</th><td> 2006 (opened) </td></tr>"
        "<tr><th>City</th><td> London </td></tr>"
        "</table>"
    )
    parsed = _parse_stadium_page(html)
    assert parsed["capacity"] == 60704
    assert parsed["opened"] == 2006
    assert parsed["city"] == "London"


def test_parse_stadium_page_none_fields_without_table():
    parsed = _parse_stadium_page("<html>no table</html>")
    assert parsed["capacity"] is None
    assert parsed["opened"] is None


# --- _build_country_index / _load_country_index (async, filesystem-touching) ------------


_COUNTRY_INDEX_HTML = (
    '<a href="https://stadiumdb.com/stadiums/eng" class="x">England</a>'
    '<a href="https://stadiumdb.com/stadiums/esp" class="x">Spain</a>'
)


def test_build_country_index_parses_country_links(monkeypatch):
    async def fake_fetch_text(_url):
        return _COUNTRY_INDEX_HTML

    monkeypatch.setattr(stadiumdb, "fetch_text", fake_fetch_text)
    entries = asyncio.run(_build_country_index())
    assert entries == [_CountryEntry(code="eng", name="England"), _CountryEntry(code="esp", name="Spain")]


def test_load_country_index_writes_seed_file_on_cache_miss(monkeypatch, tmp_path):
    async def fake_fetch_text(_url):
        return _COUNTRY_INDEX_HTML

    monkeypatch.setattr(stadiumdb, "fetch_text", fake_fetch_text)
    monkeypatch.setattr(stadiumdb, "data_dir", lambda: tmp_path)

    entries = asyncio.run(_load_country_index())
    assert entries == [_CountryEntry(code="eng", name="England"), _CountryEntry(code="esp", name="Spain")]

    seed_path = tmp_path / "stadiumdb-countries.json"
    assert seed_path.exists()
    saved = json.loads(seed_path.read_text(encoding="utf-8"))
    assert saved == [{"code": "eng", "name": "England"}, {"code": "esp", "name": "Spain"}]


def test_load_country_index_reads_existing_seed_file_without_fetching(monkeypatch, tmp_path):
    seed_path = tmp_path / "stadiumdb-countries.json"
    seed_path.write_text(json.dumps([{"code": "eng", "name": "England"}]), encoding="utf-8")

    async def unexpected_fetch(_url):
        raise AssertionError("should not fetch -- seed file already exists")

    monkeypatch.setattr(stadiumdb, "fetch_text", unexpected_fetch)
    monkeypatch.setattr(stadiumdb, "data_dir", lambda: tmp_path)

    entries = asyncio.run(_load_country_index())
    assert entries == [_CountryEntry(code="eng", name="England")]


def test_load_country_index_rebuilds_on_corrupt_seed_file(monkeypatch, tmp_path):
    seed_path = tmp_path / "stadiumdb-countries.json"
    seed_path.write_text("not valid json", encoding="utf-8")

    async def fake_fetch_text(_url):
        return _COUNTRY_INDEX_HTML

    monkeypatch.setattr(stadiumdb, "fetch_text", fake_fetch_text)
    monkeypatch.setattr(stadiumdb, "data_dir", lambda: tmp_path)

    entries = asyncio.run(_load_country_index())
    assert entries == [_CountryEntry(code="eng", name="England"), _CountryEntry(code="esp", name="Spain")]


# --- get_stadium_db_venue_details (async, full orchestration) ---------------------------


_COUNTRY_PAGE_HTML = (
    '<a href="https://stadiumdb.com/stadiums/eng/emirates" class="nu-reward">Emirates Stadium</a>'
    "</td><td> London </td><td> Arsenal </td>"
    '<td class="figure"> 60 704 </td>'
)

_STADIUM_PAGE_HTML = (
    '<table class="stadium-info">'
    "<tr><th>Capacity</th><td> 60 704 </td></tr>"
    "<tr><th>Inauguration</th><td> 2006 (opened) </td></tr>"
    "<tr><th>City</th><td> London </td></tr>"
    "</table>"
)


def test_get_stadium_db_venue_details_none_without_venue_country():
    assert asyncio.run(get_stadium_db_venue_details("Arsenal", None)) is None


def test_get_stadium_db_venue_details_none_when_country_unresolvable(monkeypatch, tmp_path):
    seed_path = tmp_path / "stadiumdb-countries.json"
    seed_path.write_text(json.dumps([{"code": "eng", "name": "England"}]), encoding="utf-8")
    monkeypatch.setattr(stadiumdb, "data_dir", lambda: tmp_path)

    result = asyncio.run(get_stadium_db_venue_details("Arsenal", "Atlantis"))
    assert result is None


def test_get_stadium_db_venue_details_none_when_no_club_row_matches(monkeypatch, tmp_path):
    seed_path = tmp_path / "stadiumdb-countries.json"
    seed_path.write_text(json.dumps([{"code": "eng", "name": "England"}]), encoding="utf-8")
    monkeypatch.setattr(stadiumdb, "data_dir", lambda: tmp_path)

    async def fake_fetch_text(_url):
        return _COUNTRY_PAGE_HTML

    monkeypatch.setattr(stadiumdb, "fetch_text", fake_fetch_text)
    result = asyncio.run(get_stadium_db_venue_details("Some Totally Unrelated Club", "England"))
    assert result is None


def test_get_stadium_db_venue_details_full_success(monkeypatch, tmp_path):
    seed_path = tmp_path / "stadiumdb-countries.json"
    seed_path.write_text(json.dumps([{"code": "eng", "name": "England"}]), encoding="utf-8")
    monkeypatch.setattr(stadiumdb, "data_dir", lambda: tmp_path)

    async def fake_fetch_text(url):
        return _STADIUM_PAGE_HTML if "emirates" in url else _COUNTRY_PAGE_HTML

    monkeypatch.setattr(stadiumdb, "fetch_text", fake_fetch_text)
    result = asyncio.run(get_stadium_db_venue_details("Arsenal", "England"))
    assert result is not None
    assert result.stadium_name == "Emirates Stadium"
    assert result.capacity == 60704
    assert result.opened == 2006
    assert result.city == "London"
    assert result.clubs == ["Arsenal"]
