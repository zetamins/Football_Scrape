import asyncio

from football.sites import statsultra
from football.sites.statsultra import (
    _find_rating,
    _normalize,
    _parse_rows,
    _StrengthRow,
    get_club_strength_ratings,
)

# --- _normalize ------------------------------------------------------------------------


def test_normalize_strips_diacritics_and_punctuation():
    assert _normalize("Bayern München!") == "bayern munchen"


# --- _parse_rows ------------------------------------------------------------------------


def _row_html(name="Arsenal", overall="85.2", attack="80.1", defense="75.4", rank="3", change="+1.2"):
    return (
        f'<tr id="row1"><td>{rank}</td>'
        f'<span class="full-name">{name}</span>'
        f'<span class="strength-num">{overall}</span>'
        f'<span class="profile-num off">{attack}</span>'
        f'<span class="profile-num def">{defense}</span>'
        f'<div data-strength-change="{change}"></div></tr>'
    )


def test_parse_rows_extracts_all_fields():
    rows = _parse_rows(_row_html())
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "Arsenal"
    assert row.overall == 85.2
    assert row.attack == 80.1
    assert row.defense == 75.4
    assert row.rank == 3
    assert row.strength_change == 1.2


def test_parse_rows_handles_missing_rank_and_change():
    html = (
        '<tr id="row1">'
        '<span class="full-name">Arsenal</span>'
        '<span class="strength-num">85.2</span>'
        '<span class="profile-num off">80.1</span>'
        '<span class="profile-num def">75.4</span>'
        "</tr>"
    )
    rows = _parse_rows(html)
    assert rows[0].rank is None
    assert rows[0].strength_change is None


def test_parse_rows_skips_incomplete_rows():
    html = '<tr id="row1"><span class="full-name">Arsenal</span></tr>'
    assert _parse_rows(html) == []


def test_parse_rows_empty_without_any_rows():
    assert _parse_rows("<html>nothing here</html>") == []


def test_parse_rows_handles_multiple_rows():
    html = _row_html(name="Arsenal") + _row_html(name="Chelsea", overall="70.0", attack="60.0", defense="65.0")
    rows = _parse_rows(html)
    assert [r.name for r in rows] == ["Arsenal", "Chelsea"]


# --- _find_rating ------------------------------------------------------------------------


def _srow(name, overall=80.0, attack=75.0, defense=70.0, rank=1, strength_change=None):
    return _StrengthRow(name=name, overall=overall, attack=attack, defense=defense, rank=rank, strength_change=strength_change)


def test_find_rating_exact_match():
    rows = [_srow("Arsenal")]
    result = _find_rating(rows, "Arsenal")
    assert result is not None
    assert result.overall == 80.0
    assert result.rank == 1


def test_find_rating_via_alias_table():
    # team_aliases.py's own alias for Nottingham Forest -- StatsUltra's
    # literal row text, confirmed live, shares no substring with the full
    # club name at all.
    rows = [_srow("Nott'ham Forest")]
    result = _find_rating(rows, "Nottingham Forest")
    assert result is not None


def test_find_rating_fuzzy_substring_fallback():
    rows = [_srow("Manchester United FC")]
    result = _find_rating(rows, "Manchester United")
    assert result is not None


def test_find_rating_none_without_any_match():
    rows = [_srow("Chelsea")]
    assert _find_rating(rows, "Some Totally Unrelated Club") is None


def test_find_rating_preserves_negative_strength_change():
    rows = [_srow("Arsenal", strength_change=-0.6)]
    result = _find_rating(rows, "Arsenal")
    assert result.strength_change == -0.6


# --- get_club_strength_ratings ------------------------------------------------------------


def test_get_club_strength_ratings_resolves_both_sides(monkeypatch):
    html = _row_html(name="Arsenal") + _row_html(name="Chelsea", overall="70.0", attack="60.0", defense="65.0")

    async def fake_fetch_text(_url):
        return html

    monkeypatch.setattr(statsultra, "fetch_text", fake_fetch_text)
    result = asyncio.run(get_club_strength_ratings("Arsenal", "Chelsea"))
    assert result["home"].overall == 85.2
    assert result["away"].overall == 70.0


def test_get_club_strength_ratings_none_for_unmatched_side(monkeypatch):
    html = _row_html(name="Arsenal")

    async def fake_fetch_text(_url):
        return html

    monkeypatch.setattr(statsultra, "fetch_text", fake_fetch_text)
    result = asyncio.run(get_club_strength_ratings("Arsenal", "Some Unrelated Club"))
    assert result["home"] is not None
    assert result["away"] is None
