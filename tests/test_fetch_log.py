import asyncio
import json

import httpx
import pytest

from football.fetch_log import FetchFailure, capture_failures, describe_failure, record_failure
from football.http import fetch_json, fetch_text


def _client_with(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- describe_failure ------------------------------------------------------------------


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://x.test/a")
    return httpx.HTTPStatusError("boom", request=request, response=httpx.Response(code, request=request))


def test_describe_failure_http_status():
    assert describe_failure(_status_error(403)) == "HTTP 403"


def test_describe_failure_timeout():
    assert describe_failure(httpx.ReadTimeout("slow")) == "timed out"


def test_describe_failure_network_error():
    assert describe_failure(httpx.ConnectError("refused")) == "network error (ConnectError)"


def test_describe_failure_non_json_is_reported_as_likely_blocked():
    err = json.JSONDecodeError("Expecting value", "<html>", 0)
    assert "likely blocked" in describe_failure(err)


def test_describe_failure_generic_uses_type_and_first_line_only():
    assert describe_failure(ValueError("first line\nsecond line")) == "ValueError: first line"


def test_describe_failure_generic_with_empty_message_falls_back_to_type_name():
    assert describe_failure(RuntimeError()) == "RuntimeError"


# --- record_failure / capture_failures ---------------------------------------------------


def test_record_failure_is_a_noop_without_an_active_capture():
    record_failure("https://api.fotmob.com/x", "HTTP 500")  # must not raise


def test_source_is_derived_from_the_hostname():
    seen: list[FetchFailure] = []
    with capture_failures(seen.append):
        record_failure("https://api.fotmob.com/x", "HTTP 500")
        record_failure("https://webws.365scores.com/y", "HTTP 500")
        record_failure("https://www.sofascore.com/api/v1/z", "HTTP 403")
    assert [f.source for f in seen] == ["fotmob", "365scores", "sofascore"]


def test_source_label_handles_country_code_second_level_domains():
    seen: list[FetchFailure] = []
    with capture_failures(seen.append):
        record_failure("https://www.football-data.co.uk/mmz4281/2627/E0.csv", "HTTP 500")
        record_failure("https://www.example.com.br/x", "HTTP 500")
    assert [f.source for f in seen] == ["football-data", "example"]


def test_same_url_is_reported_once_even_if_it_fails_repeatedly():
    seen: list[FetchFailure] = []
    with capture_failures(seen.append):
        record_failure("https://api.fotmob.com/x", "HTTP 500")
        record_failure("https://api.fotmob.com/x", "HTTP 502")
    assert len(seen) == 1
    assert seen[0].reason == "HTTP 500"


def test_a_raising_listener_never_propagates_into_the_scraper():
    def broken(_failure: FetchFailure) -> None:
        raise RuntimeError("ui exploded")

    with capture_failures(broken):
        record_failure("https://api.fotmob.com/x", "HTTP 500")  # must not raise


def test_capture_is_removed_after_the_block_exits():
    seen: list[FetchFailure] = []
    with capture_failures(seen.append):
        pass
    record_failure("https://api.fotmob.com/x", "HTTP 500")
    assert seen == []


def test_capture_reaches_coroutines_run_via_asyncio_run_and_gather():
    seen: list[FetchFailure] = []

    async def failing(n: int) -> None:
        record_failure(f"https://api.fotmob.com/{n}", "HTTP 500")

    async def main() -> None:
        await asyncio.gather(failing(1), failing(2))

    with capture_failures(seen.append):
        asyncio.run(main())
    assert sorted(f.url for f in seen) == ["https://api.fotmob.com/1", "https://api.fotmob.com/2"]


# --- http.py hooks ----------------------------------------------------------------------------


def test_fetch_text_records_the_failed_url_and_status_then_still_raises():
    client = _client_with(lambda _r: httpx.Response(503))
    seen: list[FetchFailure] = []
    with capture_failures(seen.append), pytest.raises(httpx.HTTPStatusError):
        asyncio.run(fetch_text("https://api.fotmob.com/matches", client=client))
    asyncio.run(client.aclose())
    assert seen == [FetchFailure(source="fotmob", url="https://api.fotmob.com/matches", reason="HTTP 503")]


def test_fetch_json_records_a_failure_for_an_unparseable_body():
    client = _client_with(lambda _r: httpx.Response(200, text="<html>blocked</html>"))
    seen: list[FetchFailure] = []
    with capture_failures(seen.append), pytest.raises(ValueError):
        asyncio.run(fetch_json("https://api.goal.com/x", client=client))
    asyncio.run(client.aclose())
    assert len(seen) == 1
    assert seen[0].source == "goal"


def test_successful_fetch_records_nothing():
    client = _client_with(lambda _r: httpx.Response(200, json={"ok": True}))
    seen: list[FetchFailure] = []
    with capture_failures(seen.append):
        assert asyncio.run(fetch_json("https://api.fotmob.com/x", client=client)) == {"ok": True}
    asyncio.run(client.aclose())
    assert seen == []


# --- sofascore browser fetch hooks -------------------------------------------------------------


class _Page:
    def __init__(self, body: str | Exception):
        self.body = body

    async def goto(self, *_a, **_k):
        return None

    async def evaluate(self, _script, *_args, **_kwargs):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


@pytest.fixture
def no_retry_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr("football.retry.asyncio.sleep", instant)


def test_sofascore_403_block_body_is_recorded_but_still_returned(no_retry_sleep):
    from football.sites.sofascore import _fetch_json

    seen: list[FetchFailure] = []
    page = _Page('{"error":{"code":403,"reason":"Forbidden"}}')
    with capture_failures(seen.append):
        data = asyncio.run(_fetch_json(page, "https://www.sofascore.com/api/v1/team/1"))
    assert data == {"error": {"code": 403, "reason": "Forbidden"}}
    assert [f.source for f in seen] == ["sofascore"]
    assert seen[0].reason.startswith("HTTP 403 Forbidden")


def test_sofascore_404_not_published_yet_is_not_a_failure(no_retry_sleep):
    from football.sites.sofascore import _fetch_json

    seen: list[FetchFailure] = []
    page = _Page('{"error":{"code":404,"reason":"Not Found"}}')
    with capture_failures(seen.append):
        asyncio.run(_fetch_json(page, "https://www.sofascore.com/api/v1/event/1/lineups"))
    assert seen == []


def test_sofascore_exhausted_retries_are_recorded_then_raised(no_retry_sleep):
    from football.sites.sofascore import _fetch_json

    seen: list[FetchFailure] = []
    page = _Page(RuntimeError("navigation failed"))
    with capture_failures(seen.append), pytest.raises(RuntimeError):
        asyncio.run(_fetch_json(page, "https://www.sofascore.com/api/v1/team/2"))
    assert len(seen) == 1
    assert "navigation failed" in seen[0].reason



# --- record_step_failure -----------------------------------------------------------------


def test_step_failure_uses_the_step_name_as_source_and_a_step_pseudo_url():
    from football.fetch_log import record_step_failure

    seen: list[FetchFailure] = []
    with capture_failures(seen.append):
        record_step_failure("weather (wttr.in)", KeyError("current_condition"))
    assert seen == [FetchFailure(source="weather (wttr.in)", url="step:weather (wttr.in)", reason="KeyError: 'current_condition'")]


def test_step_failure_skips_an_error_a_request_helper_already_recorded():
    from football.fetch_log import record_step_failure

    err = httpx.ConnectError("refused")
    seen: list[FetchFailure] = []
    with capture_failures(seen.append):
        record_failure("https://wttr.in/London", err)
        record_step_failure("weather (wttr.in)", err)
    assert [f.source for f in seen] == ["wttr"]


def test_step_failure_is_a_noop_without_an_active_capture():
    from football.fetch_log import record_step_failure

    record_step_failure("anything", ValueError("x"))  # must not raise


# --- previously silent fetchers ---------------------------------------------------------------


def _mock_client_factory(handler):
    def factory():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return factory


@pytest.mark.parametrize(("status", "recorded"), [(200, False), (404, False), (403, True), (429, True), (500, True)])
def test_wikipedia_article_fetch_records_only_real_failures(monkeypatch, status, recorded):
    from football.sites import wikipedia

    monkeypatch.setattr(wikipedia, "new_client", _mock_client_factory(lambda _r: httpx.Response(status, text="x")))
    seen: list[FetchFailure] = []
    with capture_failures(seen.append):
        asyncio.run(wikipedia._fetch_article_html("Some Manager"))
    assert bool(seen) is recorded
    if recorded:
        assert seen[0].reason == f"HTTP {status}"


@pytest.mark.parametrize(("status", "recorded"), [(200, False), (404, False), (403, True), (503, True)])
def test_footballdata_csv_fetch_records_only_real_failures(monkeypatch, status, recorded):
    from football.sites import footballdata

    monkeypatch.setattr(footballdata, "new_client", _mock_client_factory(lambda _r: httpx.Response(status, text="x")))
    seen: list[FetchFailure] = []
    with capture_failures(seen.append):
        asyncio.run(footballdata._fetch_csv_or_none("https://www.football-data.co.uk/mmz4281/2627/E0.csv"))
    assert bool(seen) is recorded


def test_footballdata_csv_network_error_is_recorded_then_raised(monkeypatch):
    from football.sites import footballdata

    def boom(_r):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(footballdata, "new_client", _mock_client_factory(boom))
    seen: list[FetchFailure] = []
    with capture_failures(seen.append), pytest.raises(httpx.ConnectError):
        asyncio.run(footballdata._fetch_csv_or_none("https://www.football-data.co.uk/x.csv"))
    assert seen[0].source == "football-data"


def test_soccerdesk_fetch_json_records_the_url_on_failure(monkeypatch):
    from football.sites import soccerdesk

    monkeypatch.setattr(soccerdesk, "new_client", _mock_client_factory(lambda _r: httpx.Response(500)))
    seen: list[FetchFailure] = []
    with capture_failures(seen.append), pytest.raises(httpx.HTTPStatusError):
        asyncio.run(soccerdesk._fetch_json("https://www.soccerdesk.com/v1/en/x"))
    assert seen == [FetchFailure(source="soccerdesk", url="https://www.soccerdesk.com/v1/en/x", reason="HTTP 500")]


def test_a_swallowed_enrichment_step_reports_itself(monkeypatch):
    from football import orchestrate

    async def broken(*_a, **_k):
        raise KeyError("weather")

    monkeypatch.setattr(orchestrate.wttrin, "get_wttr_weather_detail", broken)
    merged = type("M", (), {"venue_city": "Manchester", "venue_name": None, "kickoff_utc": "2026-10-10T16:30:00.000Z", "venue_country": "England"})()
    seen: list[FetchFailure] = []
    with capture_failures(seen.append):
        asyncio.run(orchestrate._enrich_weather(merged))
    assert [f.source for f in seen] == ["weather (wttr.in)"]


# --- Sofascore circuit breaker -----------------------------------------------------------------


class _CountingPage(_Page):
    def __init__(self, body):
        super().__init__(body)
        self.requests = 0

    async def evaluate(self, *args, **kwargs):
        # _fetch_json now XHRs via in-page evaluate (no goto to /api/),
        # so evaluate is the network call this counter tracks.
        self.requests += 1
        return await super().evaluate(*args, **kwargs)


def test_first_403_trips_the_breaker_and_later_requests_make_no_network_call(no_retry_sleep):
    from football.sites.sofascore import SofascoreBlockedError, _fetch_json

    page = _CountingPage('{"error":{"code":403,"reason":"Forbidden"}}')
    seen: list[FetchFailure] = []
    with capture_failures(seen.append):
        asyncio.run(_fetch_json(page, "https://www.sofascore.com/api/v1/team/1"))
        assert page.requests == 1
        for n in range(2, 8):
            with pytest.raises(SofascoreBlockedError):
                asyncio.run(_fetch_json(page, f"https://www.sofascore.com/api/v1/team/{n}"))
    assert page.requests == 1  # nothing further was sent to the blocked connection
    assert len(seen) == 1  # ...and the list shows the block once, not once per skipped call
    assert "remaining Sofascore requests skipped" in seen[0].reason


def test_a_404_does_not_trip_the_breaker(no_retry_sleep):
    from football.sites.sofascore import _fetch_json

    page = _CountingPage('{"error":{"code":404,"reason":"Not Found"}}')
    asyncio.run(_fetch_json(page, "https://www.sofascore.com/api/v1/event/1/lineups"))
    asyncio.run(_fetch_json(page, "https://www.sofascore.com/api/v1/event/2/lineups"))
    assert page.requests == 2


def test_429_also_trips_the_breaker(no_retry_sleep):
    from football.sites.sofascore import SofascoreBlockedError, _fetch_json

    page = _CountingPage('{"error":{"code":429,"reason":"Too Many Requests"}}')
    asyncio.run(_fetch_json(page, "https://www.sofascore.com/api/v1/x"))
    with pytest.raises(SofascoreBlockedError):
        asyncio.run(_fetch_json(page, "https://www.sofascore.com/api/v1/y"))


def test_reset_block_state_lets_the_next_run_use_sofascore_again(no_retry_sleep):
    from football.sites.sofascore import _fetch_json, reset_block_state

    page = _CountingPage('{"error":{"code":403,"reason":"Forbidden"}}')
    asyncio.run(_fetch_json(page, "https://www.sofascore.com/api/v1/a"))
    reset_block_state()
    asyncio.run(_fetch_json(page, "https://www.sofascore.com/api/v1/b"))
    assert page.requests == 2


def test_a_skipped_request_is_not_listed_again_by_an_outer_step_handler(no_retry_sleep):
    from football.fetch_log import record_step_failure
    from football.sites.sofascore import SofascoreBlockedError, _fetch_json

    page = _CountingPage('{"error":{"code":403,"reason":"Forbidden"}}')
    seen: list[FetchFailure] = []
    with capture_failures(seen.append):
        asyncio.run(_fetch_json(page, "https://www.sofascore.com/api/v1/a"))
        try:
            asyncio.run(_fetch_json(page, "https://www.sofascore.com/api/v1/b"))
        except SofascoreBlockedError as err:
            record_step_failure("form enrichment (own team)", err)
    assert len(seen) == 1


def test_run_search_resets_the_breaker_at_the_start(monkeypatch):
    from football import orchestrate
    from football.sites import sofascore

    sofascore._block_reason = "HTTP 403 Forbidden"

    async def boom(_team):
        raise RuntimeError("stop here")

    monkeypatch.setattr(orchestrate, "SCRAPERS", {s: orchestrate._Scraper(run=boom, details=boom, profile=boom) for s in orchestrate.SOURCE_ORDER})
    with pytest.raises(RuntimeError):
        asyncio.run(orchestrate.run_search("X"))
    assert sofascore._block_reason is None
