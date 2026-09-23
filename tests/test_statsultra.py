import asyncio
import json

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


def _payload_html(rows):
    payload = {"rows": rows}
    return f'<script id="st-strength-rows" type="application/json">{json.dumps(payload)}</script>'


def _row(rank=3, slug="arsenal", short="Arsenal", full=0, overall=85.2, attack=80.1, defense=75.4, change=1.2):
    # Real shape confirmed live: [rank, slug, short, full-or-0, abbrev,
    # css, overall, attack, defense, rank_change, strength_change, league].
    return [rank, slug, short, full, "ARS", "--p:#fff", overall, attack, defense, 0, change, 20]


def test_parse_rows_extracts_all_fields():
    rows = _parse_rows(_payload_html([_row()]))
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "Arsenal"  # full name is 0 (falsy) -> falls back to short name
    assert row.overall == 85.2
    assert row.attack == 80.1
    assert row.defense == 75.4
    assert row.rank == 3
    assert row.strength_change == 1.2


def test_parse_rows_prefers_the_full_name_when_present():
    rows = _parse_rows(_payload_html([_row(short="Manchester Utd", full="Manchester United")]))
    assert rows[0].name == "Manchester United"


def test_parse_rows_skips_malformed_rows():
    assert _parse_rows(_payload_html([[1, "too", "short"]])) == []
    assert _parse_rows(_payload_html(["not-a-list"])) == []


def test_parse_rows_empty_without_the_script_tag_or_invalid_json():
    assert _parse_rows("<html>nothing here</html>") == []
    assert _parse_rows('<script id="st-strength-rows">not json</script>') == []


def test_parse_rows_handles_multiple_rows():
    rows = _parse_rows(_payload_html([_row(slug="arsenal", short="Arsenal"), _row(slug="chelsea", short="Chelsea", overall=70.0, attack=60.0, defense=65.0)]))
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
    html = _payload_html([_row(slug="arsenal", short="Arsenal"), _row(slug="chelsea", short="Chelsea", overall=70.0, attack=60.0, defense=65.0)])

    async def fake_fetch_text(_url):
        return html

    monkeypatch.setattr(statsultra, "fetch_text", fake_fetch_text)
    result = asyncio.run(get_club_strength_ratings("Arsenal", "Chelsea"))
    assert result["home"].overall == 85.2
    assert result["away"].overall == 70.0


def test_get_club_strength_ratings_none_for_unmatched_side(monkeypatch):
    html = _payload_html([_row(slug="arsenal", short="Arsenal")])

    async def fake_fetch_text(_url):
        return html

    monkeypatch.setattr(statsultra, "fetch_text", fake_fetch_text)
    result = asyncio.run(get_club_strength_ratings("Arsenal", "Some Unrelated Club"))
    assert result["home"] is not None
    assert result["away"] is None
