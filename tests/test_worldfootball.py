import asyncio

from football.sites import worldfootball
from football.sites.worldfootball import (
    _fetch_referee_table,
    _normalize,
    get_referee_worldfootball_stats,
)


def test_normalize_strips_diacritics_and_punctuation():
    assert _normalize("Björn Kuipers!") == "bjorn kuipers"


def test_normalize_lowercases_and_collapses_whitespace():
    assert _normalize("C.  Pawson") == "c pawson"


def test_normalize_empty_for_blank_string():
    assert _normalize("") == ""


# --- _fetch_referee_table (async) --------------------------------------------------------


class _FakePage:
    def __init__(self, evaluate_result):
        self._evaluate_result = evaluate_result
        self.goto_calls = []

    async def goto(self, url, **kwargs):
        self.goto_calls.append(url)

    async def evaluate(self, _script):
        return self._evaluate_result


def test_fetch_referee_table_parses_rows():
    page = _FakePage([{"name": "C Pawson", "penalties": 3, "secondYellow": 1}])
    rows = asyncio.run(_fetch_referee_table(page, "co91/england-premier-league"))
    assert len(rows) == 1
    assert rows[0].name == "C Pawson"
    assert rows[0].penalties == 3
    assert "referees" in page.goto_calls[0]


def test_fetch_referee_table_empty_without_rows():
    page = _FakePage([])
    rows = asyncio.run(_fetch_referee_table(page, "co91/england-premier-league"))
    assert rows == []


# --- get_referee_worldfootball_stats (async, full orchestration) -------------------------


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


def test_get_referee_worldfootball_stats_none_without_competition_or_referee():
    assert asyncio.run(get_referee_worldfootball_stats(None, "C Pawson")) is None
    assert asyncio.run(get_referee_worldfootball_stats("Premier League", None)) is None


def test_get_referee_worldfootball_stats_none_for_unmapped_competition():
    assert asyncio.run(get_referee_worldfootball_stats("Not A Real League", "C Pawson")) is None


def test_get_referee_worldfootball_stats_exact_match(monkeypatch):
    page = _FakePage([{"name": "C Pawson", "penalties": 3, "secondYellow": 1}])
    monkeypatch.setattr(worldfootball, "launch_browser", lambda: _FakeBrowserCM(page))
    result = asyncio.run(get_referee_worldfootball_stats("Premier League", "C Pawson"))
    assert result is not None
    assert result.penalties == 3
    assert result.second_yellow == 1


def test_get_referee_worldfootball_stats_fuzzy_match(monkeypatch):
    # "Pawson" (target) is a substring of the table's "Craig Pawson" --
    # exercises the fuzzy fallback specifically, distinct from the exact
    # match tested above.
    page = _FakePage([{"name": "Craig Pawson", "penalties": 3, "secondYellow": 1}])
    monkeypatch.setattr(worldfootball, "launch_browser", lambda: _FakeBrowserCM(page))
    result = asyncio.run(get_referee_worldfootball_stats("Premier League", "Pawson"))
    assert result is not None
    assert result.penalties == 3


def test_get_referee_worldfootball_stats_none_without_a_match(monkeypatch):
    page = _FakePage([{"name": "Michael Oliver", "penalties": 2, "secondYellow": 0}])
    monkeypatch.setattr(worldfootball, "launch_browser", lambda: _FakeBrowserCM(page))
    result = asyncio.run(get_referee_worldfootball_stats("Premier League", "C Pawson"))
    assert result is None


def test_get_referee_worldfootball_stats_none_when_page_interaction_raises(monkeypatch):
    import football.retry as retry_module

    async def no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(retry_module.asyncio, "sleep", no_sleep)

    class _RaisingPage(_FakePage):
        async def goto(self, url, **kwargs):
            raise RuntimeError("navigation failed")

    monkeypatch.setattr(worldfootball, "launch_browser", lambda: _FakeBrowserCM(_RaisingPage([])))
    result = asyncio.run(get_referee_worldfootball_stats("Premier League", "C Pawson"))
    assert result is None
