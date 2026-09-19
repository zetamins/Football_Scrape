import asyncio

import httpx

from football.odds_math import implied_and_fair_percentages
from football.sites import footballdata
from football.sites.footballdata import (
    _find_matching_row,
    _names_match,
    _parse_rows,
    _surname,
    get_referee_home_away_bias,
    get_upcoming_match_odds,
)

# --- _parse_rows ------------------------------------------------------------------------


def test_parse_rows_extracts_referee_and_cards():
    csv = "Div,Referee,HY,AY,HR,AR\nE0,C Pawson,2,3,0,1\n"
    rows = _parse_rows(csv)
    assert len(rows) == 1
    assert rows[0].referee == "C Pawson"
    assert rows[0].home_yellow == 2
    assert rows[0].away_red == 1


def test_parse_rows_skips_blank_lines_and_missing_referee():
    csv = "Div,Referee,HY,AY,HR,AR\nE0,,2,3,0,1\n\nE0,C Pawson,1,1,0,0\n"
    rows = _parse_rows(csv)
    assert len(rows) == 1
    assert rows[0].referee == "C Pawson"


def test_parse_rows_empty_when_required_columns_missing():
    csv = "Div,Date\nE0,2026-01-01\n"
    assert _parse_rows(csv) == []


# --- _surname -----------------------------------------------------------------------------


def test_surname_takes_last_token():
    assert _surname("C Pawson") == "pawson"


def test_surname_empty_for_blank_name():
    assert _surname("") == ""
    assert _surname("   ") == ""


# --- _names_match ---------------------------------------------------------------------------


def test_names_match_via_substring_after_canonicalization():
    assert _names_match("Arsenal", "Arsenal FC") is True


def test_names_match_false_for_unrelated_teams():
    assert _names_match("Arsenal", "Chelsea") is False


# --- _find_matching_row -----------------------------------------------------------------------


def test_find_matching_row_locates_by_home_and_away_names():
    lines = ["HomeTeam,AwayTeam", "Arsenal,Chelsea", "Liverpool,Everton"]
    idx = {"home": 0, "away": 1}
    row = _find_matching_row(lines, idx, "Arsenal", "Chelsea")
    assert row == ["Arsenal", "Chelsea"]


def test_find_matching_row_none_when_no_match():
    lines = ["HomeTeam,AwayTeam", "Arsenal,Chelsea"]
    idx = {"home": 0, "away": 1}
    assert _find_matching_row(lines, idx, "Liverpool", "Everton") is None


def test_find_matching_row_skips_short_rows():
    lines = ["HomeTeam,AwayTeam,Extra", "Arsenal"]  # too short -- skipped, not IndexError
    idx = {"home": 0, "away": 1}
    assert _find_matching_row(lines, idx, "Arsenal", "Chelsea") is None


def test_find_matching_row_skips_blank_lines():
    lines = ["HomeTeam,AwayTeam", "", "Arsenal,Chelsea"]
    idx = {"home": 0, "away": 1}
    assert _find_matching_row(lines, idx, "Arsenal", "Chelsea") == ["Arsenal", "Chelsea"]


# --- implied_and_fair_percentages ---------------------------------------------------------------


def test_implied_percentages_raw_is_100_over_odds_not_devigged():
    home_pct, draw_pct, away_pct, overround, home_fair, draw_fair, away_fair = implied_and_fair_percentages(2.0, 3.5, 4.0)
    assert home_pct == 50.0  # 100/2.0, NOT renormalized
    assert draw_pct == 28.6  # 100/3.5
    assert away_pct == 25.0  # 100/4.0
    assert overround is not None
    assert overround > 100.0  # bookmaker margin
    assert home_pct + draw_pct + away_pct == overround


def test_implied_percentages_fair_devig_sums_to_100():
    *_, home_fair, draw_fair, away_fair = implied_and_fair_percentages(2.0, 3.5, 4.0)
    assert home_fair + draw_fair + away_fair == 100.0


def test_implied_percentages_none_when_any_odd_missing():
    assert implied_and_fair_percentages(2.0, None, 4.0) == (None, None, None, None, None, None, None)
    assert implied_and_fair_percentages(None, None, None) == (None, None, None, None, None, None, None)


# --- get_referee_home_away_bias (async) ----------------------------------------------------


def _mock_client_factory(handler):
    def factory():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return factory


def test_get_referee_home_away_bias_none_without_competition_or_referee():
    assert asyncio.run(get_referee_home_away_bias(None, "C Pawson")) is None
    assert asyncio.run(get_referee_home_away_bias("Premier League", None)) is None


def test_get_referee_home_away_bias_none_for_unmapped_competition():
    assert asyncio.run(get_referee_home_away_bias("Not A Real League", "C Pawson")) is None


def test_get_referee_home_away_bias_computes_cards_per_game(monkeypatch):
    csv = "Div,Referee,HY,AY,HR,AR\nE0,C Pawson,2,3,0,1\nE0,C Pawson,1,2,0,0\n"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=csv)

    monkeypatch.setattr(footballdata, "new_client", _mock_client_factory(handler))
    result = asyncio.run(get_referee_home_away_bias("Premier League", "C Pawson"))
    assert result.sample_size == 2
    assert result.home_cards_per_game == 1.5  # (2+1)/2
    assert result.away_cards_per_game == 3.0  # (3+1+2+0)/2


def test_get_referee_home_away_bias_falls_back_to_last_season_when_current_missing(monkeypatch):
    csv = "Div,Referee,HY,AY,HR,AR\nE0,C Pawson,2,1,0,0\n"
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(404)
        return httpx.Response(200, text=csv)

    monkeypatch.setattr(footballdata, "new_client", _mock_client_factory(handler))
    result = asyncio.run(get_referee_home_away_bias("Premier League", "C Pawson"))
    assert result is not None
    assert len(calls) == 2


def test_get_referee_home_away_bias_none_when_referee_not_in_either_season(monkeypatch):
    csv = "Div,Referee,HY,AY,HR,AR\nE0,M Oliver,2,1,0,0\n"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=csv)

    monkeypatch.setattr(footballdata, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_referee_home_away_bias("Premier League", "C Pawson")) is None


def test_get_referee_home_away_bias_none_when_both_fetches_fail(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    monkeypatch.setattr(footballdata, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_referee_home_away_bias("Premier League", "C Pawson")) is None


def test_get_referee_home_away_bias_tolerates_transport_error(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(footballdata, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_referee_home_away_bias("Premier League", "C Pawson")) is None


# --- get_upcoming_match_odds (async) -------------------------------------------------------


def test_get_upcoming_match_odds_none_when_fetch_fails(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    monkeypatch.setattr(footballdata, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_upcoming_match_odds("Arsenal", "Chelsea")) is None


def test_get_upcoming_match_odds_none_without_required_columns(monkeypatch):
    csv = "Div,Date\nE0,2026-01-01\n"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=csv)

    monkeypatch.setattr(footballdata, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_upcoming_match_odds("Arsenal", "Chelsea")) is None


def test_get_upcoming_match_odds_none_when_match_not_found(monkeypatch):
    csv = "Div,HomeTeam,AwayTeam,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5\nE0,Liverpool,Everton,2.0,3.5,4.0,1.9,1.95\n"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=csv)

    monkeypatch.setattr(footballdata, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_upcoming_match_odds("Arsenal", "Chelsea")) is None


def test_get_upcoming_match_odds_computes_odds_and_implied_pct(monkeypatch):
    csv = "Div,HomeTeam,AwayTeam,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5\nE0,Arsenal,Chelsea,2.0,3.5,4.0,1.9,1.95\n"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=csv)

    monkeypatch.setattr(footballdata, "new_client", _mock_client_factory(handler))
    result = asyncio.run(get_upcoming_match_odds("Arsenal", "Chelsea"))
    assert result.home_win_odds == 2.0
    assert result.draw_odds == 3.5
    assert result.away_win_odds == 4.0
    assert result.over_2_5_odds == 1.9
    assert result.under_2_5_odds == 1.95
    assert result.home_win_implied_pct is not None


def test_get_upcoming_match_odds_over_under_has_overround_and_fair_pct(monkeypatch):
    # Regression: the Over/Under 2.5 market previously had no derived
    # stats at all -- raw odds only, with implied percentages summing
    # above 100% and no overround exposed anywhere.
    csv = "Div,HomeTeam,AwayTeam,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5\nE0,Arsenal,Chelsea,2.0,3.5,4.0,1.67,2.12\n"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=csv)

    monkeypatch.setattr(footballdata, "new_client", _mock_client_factory(handler))
    result = asyncio.run(get_upcoming_match_odds("Arsenal", "Chelsea"))
    assert result.over_2_5_implied_pct == 59.9  # 100/1.67, raw
    assert result.under_2_5_implied_pct == 47.2  # 100/2.12, raw
    assert result.over_under_2_5_overround_pct > 100.0
    assert result.over_2_5_fair_pct + result.under_2_5_fair_pct == 100.0


def test_get_upcoming_match_odds_tolerates_transport_error(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(footballdata, "new_client", _mock_client_factory(handler))
    assert asyncio.run(get_upcoming_match_odds("Arsenal", "Chelsea")) is None


def test_get_upcoming_match_odds_handles_missing_empty_and_unparseable_cells(monkeypatch):
    # Avg>2.5/Avg<2.5 columns absent entirely (index -1), AvgD is an empty
    # cell, AvgA is a genuinely unparseable value -- all three must
    # degrade to None rather than raising.
    csv = "Div,HomeTeam,AwayTeam,AvgH,AvgD,AvgA\nE0,Arsenal,Chelsea,2.0,,n/a\n"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=csv)

    monkeypatch.setattr(footballdata, "new_client", _mock_client_factory(handler))
    result = asyncio.run(get_upcoming_match_odds("Arsenal", "Chelsea"))
    assert result.home_win_odds == 2.0
    assert result.draw_odds is None
    assert result.away_win_odds is None
    assert result.over_2_5_odds is None
    assert result.under_2_5_odds is None
