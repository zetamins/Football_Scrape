import asyncio

import httpx

from football.sites import wikipedia
from football.sites.wikipedia import (
    _find_manager_table,
    _find_win_pct_index,
    _parse_tenure_fields,
    _row_cells,
    _select_current_row,
    _strip_tags,
    get_current_tenure_row,
    get_manager_appointment_date,
    get_manager_tenure_record,
    get_previous_manager,
    parse_wiki_date,
)


def test_parse_tenure_fields_with_leading_icon_cell():
    # Paulo Fonseca's real row shape -- Team, icon, From, To, P, W, D, L,
    # GF, GA, GD, Win% (12 cells). Without end-anchoring this silently read
    # from_date as the empty icon cell and win_pct as the Losses count.
    row = ["Lyon", "", "31 January 2025", "Present", "72", "41", "10", "21", "134", "87", "+47", "056.94"]
    from_date, played, wins, draws, losses, win_pct = _parse_tenure_fields(row)
    assert from_date == "31 January 2025"
    assert (played, wins, draws, losses) == (72, 41, 10, 21)
    assert win_pct == 56.94


def test_parse_tenure_fields_without_leading_icon_cell():
    # Didier Digard's real row shape -- Team, From, To, P, W, D, L, GF, GA,
    # GD, Win% (11 cells, no icon). Without end-anchoring this silently
    # read win_pct as the Goals-For count (71.0 instead of the real 24.29).
    row = ["Le Havre", "1 July 2024", "Present", "70", "17", "18", "35", "71", "117", "−46", "024.29"]
    from_date, played, wins, draws, losses, win_pct = _parse_tenure_fields(row)
    assert from_date == "1 July 2024"
    assert (played, wins, draws, losses) == (70, 17, 18, 35)
    assert win_pct == 24.29


def test_parse_tenure_fields_returns_none_for_short_row():
    assert _parse_tenure_fields(["Some Team", "2020"]) == (None, None, None, None, None, None)


def test_parse_tenure_fields_five_column_record_group_no_goals_columns():
    # Real bug confirmed live 2026-09-04: Mikel Arteta/Pep Guardiola/Arne
    # Slot/Unai Emery's current pages all dropped the GF/GA/GD columns from
    # this table entirely (Team, From, To, P, W, D, L, Win% -- 8 cells, no
    # goals-for/against/difference at all), which the previous fixed
    # 9-cell-back offset (calibrated for the 11/12-cell GF/GA/GD shape)
    # couldn't reach -- it silently returned all-None for every one of
    # them. Also exercises the 1-decimal-digit win% shape ("060.7", not
    # "060.70") those same live pages use -- see the next test for that in
    # isolation.
    row = ["Arsenal", "22 December 2019", "Present", "356", "216", "67", "73", "060.7"]
    from_date, played, wins, draws, losses, win_pct = _parse_tenure_fields(row)
    assert from_date == "22 December 2019"
    assert (played, wins, draws, losses) == (356, 216, 67, 73)
    assert win_pct == 60.7


def test_parse_tenure_fields_none_when_win_pct_has_no_preceding_record_cells():
    # wp is found, but nothing record-shaped (a date string, not a plain
    # or signed integer) sits immediately before it -- numeric_run stays 0,
    # so there's no P/W/D/L to extract at all.
    row = ["Team", "20 December 2019", "050.00"]
    assert _parse_tenure_fields(row) == (None, None, None, None, None, None)


def test_find_win_pct_index_matches_single_decimal_digit():
    # Real bug confirmed live 2026-09-04: _WIN_PCT_RE used to require
    # exactly 2 decimal digits, but several current manager pages show
    # only 1 ("060.7") -- the old regex made _find_win_pct_index return
    # None for these rows before any offset math even ran.
    row = ["Arsenal", "22 December 2019", "Present", "356", "216", "67", "73", "060.7"]
    assert _find_win_pct_index(row) == 7


def test_select_current_row_prefers_present_five_column_shape():
    past = ["Everton", "1 July 2015", "1 December 2016", "70", "20", "20", "30", "030.0"]
    present = ["Arsenal", "22 December 2019", "Present", "356", "216", "67", "73", "060.7"]
    assert _select_current_row([past, present]) is present


def test_parse_tenure_fields_with_trailing_empty_ref_cell():
    # Niko Kovač's real row shape -- Team, From, To, P, W, D, L, GF, GA,
    # GD, Win%, [empty Ref-column cell] (12 cells, no leading icon this
    # time but a trailing empty cell instead). A pure end-anchored count
    # misread this as played=43 (actually GF... no, actually the row's own
    # W value), wins=14 (D), draws=17 (L), losses=151 (GF), win_pct=None
    # (the empty trailing cell) -- none of which reconciled (14+17+151 !=
    # 43). Locating Win% by content sidesteps this entirely.
    row = ["Borussia Dortmund", "2 February 2025", "present", "74", "43", "14", "17", "151", "92", "+59", "058.11", ""]
    from_date, played, wins, draws, losses, win_pct = _parse_tenure_fields(row)
    assert from_date == "2 February 2025"
    assert (played, wins, draws, losses) == (74, 43, 14, 17)
    assert win_pct == 58.11


def test_select_current_row_prefers_present_with_trailing_empty_cell():
    past = ["Wolfsburg", "24 May 2022", "17 March 2024", "66", "23", "17", "26", "96", "93", "+3", "034.85", ""]
    present = ["Borussia Dortmund", "2 February 2025", "present", "74", "43", "14", "17", "151", "92", "+59", "058.11", ""]
    assert _select_current_row([past, present]) is present


def test_select_current_row_prefers_present_over_fixed_end_date():
    fixed_term = ["Liverpool", "1 July 2023", "30 May 2026", "50", "30", "10", "10", "90", "40", "+50", "060.00"]
    present = ["Feyenoord", "1 July 2020", "Present", "80", "50", "15", "15", "150", "70", "+80", "062.50"]
    assert _select_current_row([fixed_term, present]) is present


def test_select_current_row_falls_back_to_last_row_when_none_marked_present():
    fixed_term = ["Liverpool", "1 July 2023", "30 May 2026", "50", "30", "10", "10", "90", "40", "+50", "060.00"]
    assert _select_current_row([fixed_term]) is fixed_term


# --- _strip_tags ---------------------------------------------------------------------


def test_strip_tags_removes_html_and_truncates_at_footnote_marker():
    html = 'Present<sup class="reference" data-mw=\'{"a": "b > c"}\'>[1]</sup>'
    assert _strip_tags(html) == "Present"


def test_strip_tags_strips_bracketed_citations():
    assert _strip_tags("Text [1] more") == "Text  more"


# --- parse_wiki_date -------------------------------------------------------------------


def test_parse_wiki_date_parses_valid_date():
    assert parse_wiki_date("22 December 2019") == "2019-12-22T00:00:00.000Z"


def test_parse_wiki_date_none_for_unparseable_format():
    assert parse_wiki_date("not a date") is None


def test_parse_wiki_date_none_for_unknown_month():
    assert parse_wiki_date("22 Frobtember 2019") is None


# --- _find_win_pct_index ----------------------------------------------------------------


def test_find_win_pct_index_locates_from_the_end():
    row = ["Team", "1 July 2020", "Present", "50", "30", "10", "10", "90", "40", "+50", "060.00"]
    assert _find_win_pct_index(row) == 10


def test_find_win_pct_index_none_without_a_matching_cell():
    assert _find_win_pct_index(["a", "b", "c"]) is None


# --- _row_cells ---------------------------------------------------------------------------


def test_row_cells_extracts_link_title_when_present():
    html = '<td><a href="/wiki/Pep_Guardiola" title="Pep Guardiola">Guardiola</a></td><td>2016</td>'
    assert _row_cells(html) == ["Pep Guardiola", "2016"]


def test_row_cells_strips_tags_when_no_link():
    html = "<th>Manager</th><td>To</td>"
    assert _row_cells(html) == ["Manager", "To"]


# --- _find_manager_table -----------------------------------------------------------------


def test_find_manager_table_finds_the_table_with_manager_and_to_columns():
    html = (
        "<table><tr><th>Legend</th></tr></table>"  # decoy table, no Manager/To columns
        "<table><tr><th>Manager</th><th>From</th><th>To</th></tr>"
        "<tr><td>Pep Guardiola</td><td>2016</td><td>Present</td></tr></table>"
    )
    result = _find_manager_table(html)
    assert result is not None
    name_col, to_col, rows = result
    assert name_col == 0
    assert to_col == 2
    assert rows[0][name_col] == "Pep Guardiola"


def test_find_manager_table_none_without_a_matching_table():
    html = "<table><tr><th>Legend</th></tr></table>"
    assert _find_manager_table(html) is None


def test_find_manager_table_none_when_table_never_closes():
    html = "<table><tr><th>Manager</th><th>To</th></tr>"  # no </table> at all
    assert _find_manager_table(html) is None


def test_find_manager_table_skips_an_empty_table_and_checks_the_next():
    html = (
        "<table></table>"  # no <tr at all -- must be skipped, not treated as a match
        "<table><tr><th>Manager</th><th>From</th><th>To</th></tr>"
        "<tr><td>Pep Guardiola</td><td>2016</td><td>Present</td></tr></table>"
    )
    result = _find_manager_table(html)
    assert result is not None
    name_col, _to_col, rows = result
    assert rows[0][name_col] == "Pep Guardiola"


# --- get_current_tenure_row / get_manager_appointment_date / get_manager_tenure_record (async) --


def _mock_client_factory(handler):
    def factory():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return factory


def _manager_page_html(row_cells: list[str], bday: str = "1975-05-01") -> str:
    header = "<tr><th>Team</th><th>From</th><th>To</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Win%</th></tr>"
    row = "<tr>" + "".join(f"<td>{c}</td>" for c in row_cells) + "</tr>"
    return f'<span class="bday">{bday}</span><div id="Managerial_statistics"></div><table>{header}{row}</table>'


_TENURE_ROW_CELLS = ["Some Club", "1 July 2024", "Present", "70", "17", "18", "35", "71", "117", "-46", "024.29"]


def test_get_current_tenure_row_none_when_page_fetch_fails(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_current_tenure_row("Some Manager")) is None


def test_get_current_tenure_row_none_without_managerial_statistics_heading(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>no relevant section</html>")

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_current_tenure_row("Some Manager")) is None


def test_get_current_tenure_row_finds_table_under_plain_managerial_heading(monkeypatch):
    # Some pages (e.g. Pep Guardiola's) use a plain "Managerial" heading
    # instead of "Managerial statistics" -- both must resolve to the
    # same table.
    header = "<tr><th>Team</th><th>From</th><th>To</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Win%</th></tr>"
    row = "<tr>" + "".join(f"<td>{c}</td>" for c in _TENURE_ROW_CELLS) + "</tr>"
    html = f'<div id="Managerial"></div><table>{header}{row}</table>'

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    result = asyncio.run(get_current_tenure_row("Some Manager"))
    assert result is not None
    assert result.from_date == "1 July 2024"


def test_get_current_tenure_row_none_without_a_table_after_heading(monkeypatch):
    html = '<div id="Managerial_statistics"></div>no table here'

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_current_tenure_row("Some Manager")) is None


def test_get_current_tenure_row_none_when_every_row_is_the_totals_summary(monkeypatch):
    # A row whose first cell is purely numeric (the career-totals row) is
    # excluded -- if that's the only row present, no team_rows survive.
    header = "<tr><th>Team</th></tr>"
    totals_row = "<tr><td>500</td><td>1 July 2024</td><td>Present</td></tr>"
    html = f'<div id="Managerial_statistics"></div><table>{header}{totals_row}</table>'

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_current_tenure_row("Some Manager")) is None


def test_get_current_tenure_row_extracts_full_record_and_date_of_birth(monkeypatch):
    html = _manager_page_html(_TENURE_ROW_CELLS)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    result = asyncio.run(get_current_tenure_row("Some Manager"))
    assert result.from_date == "1 July 2024"
    assert result.played == 70
    assert result.wins == 17
    assert result.win_pct == 24.29
    assert result.date_of_birth == "1975-05-01"


def test_get_manager_appointment_date_parses_the_from_date(monkeypatch):
    html = _manager_page_html(_TENURE_ROW_CELLS)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    result = asyncio.run(get_manager_appointment_date("Some Manager"))
    assert result == "2024-07-01T00:00:00.000Z"


def test_get_manager_appointment_date_none_without_a_row(monkeypatch):
    async def fake_current(_name):
        return None

    monkeypatch.setattr(wikipedia, "get_current_tenure_row", fake_current)
    assert asyncio.run(get_manager_appointment_date("Some Manager")) is None


def test_get_manager_tenure_record_builds_full_record(monkeypatch):
    html = _manager_page_html(_TENURE_ROW_CELLS)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    result = asyncio.run(get_manager_tenure_record("Some Manager"))
    assert result.played == 70
    assert result.wins == 17
    assert result.losses == 35


def test_get_manager_tenure_record_none_when_fields_incomplete(monkeypatch):
    # A row that resolves but is missing the win_pct-anchored group
    # entirely (e.g. too few cells) -- get_current_tenure_row still
    # returns a row object, just with played=None etc.
    header = "<tr><th>Team</th></tr>"
    row = "<tr><td>Some Club</td><td>x</td><td>y</td></tr>"
    html = f'<div id="Managerial_statistics"></div><table>{header}{row}</table>'

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_manager_tenure_record("Some Manager")) is None


# --- get_previous_manager (async) -------------------------------------------------------------


def _managers_list_html(rows: list[tuple[str, str]]) -> str:
    header = "<tr><th>Manager</th><th>From</th><th>To</th></tr>"
    body = "".join(f"<tr><td>{name}</td><td>2020</td><td>{to}</td></tr>" for name, to in rows)
    return f"<table>{header}{body}</table>"


def test_get_previous_manager_none_when_neither_title_variant_fetches(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_previous_manager("Some Club")) is None


def test_get_previous_manager_tries_fc_variant_first(monkeypatch):
    seen_urls = []
    html = _managers_list_html([("Old Boss", "2023"), ("Current Boss", "Present")])

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, text=html)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    result = asyncio.run(get_previous_manager("Arsenal"))
    assert result == "Old Boss"
    assert "F.C." in seen_urls[0] or "F.C" in seen_urls[0]


def test_get_previous_manager_falls_back_to_plain_title_variant(monkeypatch):
    html = _managers_list_html([("Old Boss", "2023"), ("Current Boss", "Present")])
    call_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(404)
        return httpx.Response(200, text=html)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    result = asyncio.run(get_previous_manager("Arsenal"))
    assert result == "Old Boss"
    assert call_count == 2


def test_get_previous_manager_none_without_a_matching_table(monkeypatch):
    html = "<table><tr><th>Legend</th></tr></table>"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_previous_manager("Arsenal")) is None


def test_get_previous_manager_none_with_fewer_than_two_rows(monkeypatch):
    html = _managers_list_html([("Only Boss", "Present")])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_previous_manager("Arsenal")) is None


def test_get_previous_manager_falls_back_to_last_row_without_a_present_marker(monkeypatch):
    html = _managers_list_html([("First Boss", "2020"), ("Second Boss", "2023"), ("Third Boss", "2025")])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    result = asyncio.run(get_previous_manager("Arsenal"))
    assert result == "Second Boss"


def test_manager_list_titles_cover_the_common_wikipedia_naming_shapes_in_order():
    from football.sites.wikipedia import _manager_list_titles

    titles = _manager_list_titles("Barcelona")
    assert titles[0] == "List of Barcelona F.C. managers"
    assert titles[1] == "List of Barcelona managers"
    assert "List of FC Barcelona managers" in titles
    assert "List of Real CF managers" not in titles
    assert _manager_list_titles("Madrid")[3] == "List of Madrid CF managers"
    assert "List of AC Milan managers" in _manager_list_titles("Milan")


def test_get_previous_manager_finds_a_club_titled_with_the_fc_prefix(monkeypatch):
    html = _managers_list_html([("Old Boss", "2023"), ("Current Boss", "Present")])
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text=html) if "FC_Barcelona" in str(request.url) else httpx.Response(404)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_previous_manager("Barcelona")) == "Old Boss"
    assert all("/wiki/" in url for url in seen)  # never the /w/ API, which robots.txt disallows


def test_get_previous_manager_reports_a_step_failure_when_no_title_pattern_exists(monkeypatch):
    from football.fetch_log import capture_failures

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(lambda _r: httpx.Response(404)))
    seen = []
    with capture_failures(seen.append):
        assert asyncio.run(get_previous_manager("Some Club")) is None
    assert any("previous manager (Wikipedia)" in f.source for f in seen)


def test_manager_list_titles_includes_the_clubs_known_aliases_from_the_shared_table():
    from football.sites.wikipedia import _manager_list_titles

    # Confirmed live: Tottenham's real Wikipedia title is "List of
    # Tottenham Hotspur F.C. managers" -- not reachable from any of the
    # fixed "{c} ..." patterns applied to the bare searched name "Tottenham".
    titles = _manager_list_titles("Tottenham")
    assert "List of Tottenham Hotspur F.C. managers" in titles
    assert "List of Spurs F.C. managers" in titles


def test_get_previous_manager_finds_a_club_only_reachable_through_its_alias(monkeypatch):
    html = _managers_list_html([("Old Boss", "2023"), ("Current Boss", "Present")])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html) if "Tottenham_Hotspur_F" in str(request.url) else httpx.Response(404)

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_previous_manager("Tottenham")) == "Old Boss"
