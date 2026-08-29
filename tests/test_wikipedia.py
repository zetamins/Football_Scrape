from football.sites.wikipedia import _parse_tenure_fields, _select_current_row


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
