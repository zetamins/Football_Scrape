import asyncio

from football.sites import squawka
from football.sites.squawka import (
    _fetch_stat_values,
    _load_page_context,
    _normalize,
    _resolve_competition_id,
    get_squawka_defensive_stats,
)

# --- _normalize ------------------------------------------------------------------------


def test_normalize_strips_diacritics_and_punctuation():
    assert _normalize("Björn Kuipers!") == "bjorn kuipers"


def test_fetch_stat_js_is_bounded_by_abort_signal():
    """Unbounded in-page fetch pins page.evaluate forever on desktop
    Playwright (no default timeout) -- same class of hang as Sofascore's
    _FETCH_JSON_JS."""
    assert "AbortSignal.timeout" in squawka._FETCH_STAT_JS


# --- _resolve_competition_id -------------------------------------------------------------


def _competition(comp_id, name, start_date):
    return {"_id": comp_id, "competition": name, "start_date": start_date}


def test_resolve_competition_id_exact_name_match():
    competitions = [_competition("c1", "Premier League", "2025-08-01 00:00:00")]
    assert _resolve_competition_id(competitions, "Premier League") == "c1"


def test_resolve_competition_id_uses_alias_for_laliga():
    # Squawka's own name is "Primera Division", never "LaLiga" -- an
    # exact-match lookup without the alias table silently returns nothing.
    competitions = [_competition("c1", "Primera Division", "2025-08-01 00:00:00")]
    assert _resolve_competition_id(competitions, "LaLiga") == "c1"
    assert _resolve_competition_id(competitions, "La Liga") == "c1"


def test_resolve_competition_id_excludes_not_yet_started_season():
    competitions = [_competition("future", "Premier League", "2099-08-01 00:00:00")]
    assert _resolve_competition_id(competitions, "Premier League") is None


def test_resolve_competition_id_picks_most_recent_started_season():
    competitions = [
        _competition("old", "Premier League", "2023-08-01 00:00:00"),
        _competition("new", "Premier League", "2024-08-01 00:00:00"),
    ]
    assert _resolve_competition_id(competitions, "Premier League") == "new"


def test_resolve_competition_id_none_without_any_match():
    assert _resolve_competition_id([], "Premier League") is None


# --- _fetch_stat_values -----------------------------------------------------------------


class _FakePage:
    def __init__(self, response):
        self._response = response
        self.goto_calls = []

    async def evaluate(self, _js, _args=None):
        return self._response

    async def goto(self, url, **_kwargs):
        self.goto_calls.append(url)


def test_fetch_stat_values_keys_by_player_and_team():
    response = {
        "items": [
            {
                "name": "Bukayo Saka",
                "participant_name": "Arsenal",
                "statistic_groups": [{"statistics": [{"value": 12}]}],
            }
        ]
    }
    page = _FakePage(response)
    values = asyncio.run(_fetch_stat_values(page, "nonce", "comp1", "Tackles Made"))
    assert values == {"bukayo saka::arsenal": 12}


def test_fetch_stat_values_skips_items_without_numeric_value():
    response = {
        "items": [
            {"name": "A", "participant_name": "B", "statistic_groups": []},
            {"name": "C", "participant_name": "D", "statistic_groups": [{"statistics": [{"value": None}]}]},
            {"name": "E", "participant_name": "F", "statistic_groups": [{"statistics": [{"value": True}]}]},
        ]
    }
    page = _FakePage(response)
    values = asyncio.run(_fetch_stat_values(page, "nonce", "comp1", "Tackles Made"))
    assert values == {}


def test_fetch_stat_values_empty_without_items():
    page = _FakePage({})
    values = asyncio.run(_fetch_stat_values(page, "nonce", "comp1", "Tackles Made"))
    assert values == {}


def test_fetch_stat_values_empty_when_result_is_none():
    page = _FakePage(None)
    values = asyncio.run(_fetch_stat_values(page, "nonce", "comp1", "Tackles Made"))
    assert values == {}


# --- _load_page_context (async) -----------------------------------------------------------


def test_load_page_context_parses_nonce_and_competitions():
    page = _FakePage({"nonce": "abc123", "competitions": [{"_id": "c1", "competition": "Premier League", "start_date": "2025-08-01 00:00:00"}]})
    nonce, competitions = asyncio.run(_load_page_context(page))
    assert nonce == "abc123"
    assert competitions[0]["_id"] == "c1"
    assert page.goto_calls[0] == "https://www.squawka.com/en/stats/clubs/arsenal/"


# --- get_squawka_defensive_stats (async, full orchestration) -----------------------------


class _FakeContext:
    def __init__(self, page):
        self._page = page

    async def new_page(self):
        return self._page


class _FakeBrowser:
    def __init__(self, page):
        self._page = page

    async def new_context(self, **_kwargs):
        return _FakeContext(self._page)


class _FakeBrowserCM:
    def __init__(self, page):
        self._page = page

    async def __aenter__(self):
        return _FakeBrowser(self._page)

    async def __aexit__(self, *_exc):
        return False


class _DefensiveStatsPage(_FakePage):
    """Returns the page-context payload on the first evaluate() call
    (goto's own JS), then per-stat player values keyed by the requested
    statLabel for every subsequent call -- mirrors the real page's two
    distinct evaluate() call shapes (_LOAD_PAGE_CONTEXT_JS vs
    _FETCH_STAT_JS)."""

    def __init__(self, context_response, stat_responses: dict[str, dict]):
        super().__init__(context_response)
        self._stat_responses = stat_responses

    async def evaluate(self, _js, args=None):
        if args is None:
            return self._response
        stat_label = args["statLabel"]
        items = self._stat_responses.get(stat_label, {})
        return {"items": items}


def _stat_item(name, participant_name, value):
    return {"name": name, "participant_name": participant_name, "statistic_groups": [{"statistics": [{"value": value}]}]}


def test_get_squawka_defensive_stats_empty_without_competition_candidates():
    result = asyncio.run(get_squawka_defensive_stats("Arsenal", []))
    assert result == {}


def test_get_squawka_defensive_stats_empty_when_no_competition_resolves(monkeypatch):
    context_response = {"nonce": "abc123", "competitions": []}
    page = _DefensiveStatsPage(context_response, {})
    monkeypatch.setattr(squawka, "launch_browser", lambda: _FakeBrowserCM(page))
    result = asyncio.run(get_squawka_defensive_stats("Arsenal", ["Premier League"]))
    assert result == {}


async def _no_sleep(*_args, **_kwargs):
    return None


def test_get_squawka_defensive_stats_builds_stats_for_matched_team(monkeypatch):
    monkeypatch.setattr(squawka.asyncio, "sleep", _no_sleep)
    context_response = {"nonce": "abc123", "competitions": [{"_id": "c1", "competition": "Premier League", "start_date": "2020-08-01 00:00:00"}]}
    stat_responses = {
        "Tackles Made": [_stat_item("Bukayo Saka", "Arsenal", 5)],
        "Interceptions": [_stat_item("Bukayo Saka", "Arsenal", 3)],
    }
    page = _DefensiveStatsPage(context_response, stat_responses)
    monkeypatch.setattr(squawka, "launch_browser", lambda: _FakeBrowserCM(page))
    result = asyncio.run(get_squawka_defensive_stats("Arsenal", ["Premier League"]))
    assert "bukayo saka" in result
    assert result["bukayo saka"].tackles_made == 5
    assert result["bukayo saka"].interceptions == 3


def test_get_squawka_defensive_stats_excludes_players_from_other_teams(monkeypatch):
    monkeypatch.setattr(squawka.asyncio, "sleep", _no_sleep)
    context_response = {"nonce": "abc123", "competitions": [{"_id": "c1", "competition": "Premier League", "start_date": "2020-08-01 00:00:00"}]}
    stat_responses = {"Tackles Made": [_stat_item("Some Player", "Chelsea", 5)]}
    page = _DefensiveStatsPage(context_response, stat_responses)
    monkeypatch.setattr(squawka, "launch_browser", lambda: _FakeBrowserCM(page))
    result = asyncio.run(get_squawka_defensive_stats("Arsenal", ["Premier League"]))
    assert result == {}


def test_get_squawka_defensive_stats_tries_next_competition_candidate(monkeypatch):
    monkeypatch.setattr(squawka.asyncio, "sleep", _no_sleep)
    context_response = {"nonce": "abc123", "competitions": [{"_id": "c1", "competition": "Premier League", "start_date": "2020-08-01 00:00:00"}]}
    stat_responses = {"Tackles Made": [_stat_item("Bukayo Saka", "Arsenal", 5)]}
    page = _DefensiveStatsPage(context_response, stat_responses)
    monkeypatch.setattr(squawka, "launch_browser", lambda: _FakeBrowserCM(page))
    # First candidate ("Club Friendly Games") doesn't resolve to any real
    # competition; the second ("Premier League") does -- confirms the
    # candidate loop tries more than just the first entry.
    result = asyncio.run(get_squawka_defensive_stats("Arsenal", ["Club Friendly Games", "Premier League"]))
    assert "bukayo saka" in result


def test_get_squawka_defensive_stats_returns_empty_on_unexpected_error(monkeypatch):
    import football.retry as retry_module

    monkeypatch.setattr(squawka.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(retry_module.asyncio, "sleep", _no_sleep)

    class _BrokenPage(_FakePage):
        async def goto(self, url, **_kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(squawka, "launch_browser", lambda: _FakeBrowserCM(_BrokenPage(None)))
    result = asyncio.run(get_squawka_defensive_stats("Arsenal", ["Premier League"]))
    assert result == {}
