import asyncio

import pytest

from football.retry import retry_with_backoff


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    # retry_with_backoff's real delays are 3s/6s/12s -- every test here
    # exercises the retry path, so skip actually waiting through them.
    async def instant_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)


def test_returns_the_first_successful_result_without_retrying():
    calls = []

    async def fn():
        calls.append(1)
        return "ok"

    result = asyncio.run(retry_with_backoff(fn))
    assert result == "ok"
    assert len(calls) == 1


def test_retries_after_a_failure_and_returns_the_eventual_success():
    calls = []

    async def fn():
        calls.append(1)
        if len(calls) < 2:
            raise RuntimeError("transient")
        return "recovered"

    result = asyncio.run(retry_with_backoff(fn))
    assert result == "recovered"
    assert len(calls) == 2


def test_raises_the_last_error_after_exhausting_all_attempts():
    calls = []

    async def fn():
        calls.append(1)
        raise ValueError(f"attempt {len(calls)}")

    with pytest.raises(ValueError, match="attempt 3"):
        asyncio.run(retry_with_backoff(fn, attempts=3))
    assert len(calls) == 3


def test_respects_a_custom_attempts_count():
    calls = []

    async def fn():
        calls.append(1)
        raise RuntimeError("always fails")

    with pytest.raises(RuntimeError):
        asyncio.run(retry_with_backoff(fn, attempts=1))
    assert len(calls) == 1
