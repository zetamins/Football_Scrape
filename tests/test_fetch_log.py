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

    async def evaluate(self, _script):
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
    assert [(f.source, f.reason) for f in seen] == [("sofascore", "HTTP 403 Forbidden")]


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

