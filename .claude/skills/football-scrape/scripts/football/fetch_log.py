"""Collects every link/API request that failed during one search run so a
caller (the Android app's loading screen) can show the user a live list.

A ContextVar holds the active sink rather than threading a callback
through every scraper: asyncio.run() copies the current context into its
task, so setting the sink before asyncio.run() reaches every scraper
coroutine (including ones started via asyncio.gather).
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True)
class FetchFailure:
    source: str
    url: str
    reason: str


_sink: ContextVar[Callable[[FetchFailure], None] | None] = ContextVar("fetch_failure_sink", default=None)


STEP_PREFIX = "step:"
_SECOND_LEVEL_LABELS = frozenset({"co", "com", "org", "net", "gov", "ac"})


def _source_from_url(url: str) -> str:
    """'api.fotmob.com' -> 'fotmob', 'webws.365scores.com' -> '365scores';
    a processing step ("step:weather (wttr.in)") is its own source label."""
    if url.startswith(STEP_PREFIX):
        return url.removeprefix(STEP_PREFIX)
    host = (urlparse(url).hostname or "").removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL_LABELS:
        return parts[-3]  # 'www.football-data.co.uk' -> 'football-data'
    return parts[-2] if len(parts) >= 2 else (host or "unknown")


def describe_failure(err: BaseException) -> str:
    """Short, user-readable reason -- not a traceback."""
    if isinstance(err, httpx.HTTPStatusError):
        return f"HTTP {err.response.status_code}"
    if isinstance(err, httpx.TimeoutException):
        return "timed out"
    if isinstance(err, httpx.RequestError):
        return f"network error ({type(err).__name__})"
    if isinstance(err, json.JSONDecodeError):
        return "non-JSON response (likely blocked)"
    message = str(err).strip().splitlines()[0][:80] if str(err).strip() else ""
    return f"{type(err).__name__}: {message}" if message else type(err).__name__


def record_failure(url: str, reason: str | BaseException) -> None:
    """No-op unless a capture_failures() block is active."""
    sink = _sink.get()
    if sink is None:
        return
    if isinstance(reason, BaseException):
        reason._failure_recorded = True  # lets an outer step handler skip the same error
    text = reason if isinstance(reason, str) else describe_failure(reason)
    sink(FetchFailure(source=_source_from_url(url), url=url, reason=text))


def record_step_failure(step: str, reason: str | BaseException) -> None:
    """A failure that isn't a request itself -- a parse error or changed
    response shape inside an enrichment step that otherwise degrades
    quietly to "no data". Shows in the same list as failed links, with a
    "step:" pseudo-URL instead of a link. An exception a request helper
    already recorded is not listed a second time."""
    if isinstance(reason, BaseException) and getattr(reason, "_failure_recorded", False):
        return
    record_failure(f"{STEP_PREFIX}{step}", reason)


@contextlib.contextmanager
def capture_failures(on_failure: Callable[[FetchFailure], None]) -> Iterator[None]:
    """Reports each distinct failed URL once, however many times it's tried."""
    seen: set[str] = set()

    def sink(failure: FetchFailure) -> None:
        if failure.url in seen:
            return
        seen.add(failure.url)
        # A broken listener (e.g. the UI side throwing) must never turn
        # into an exception inside the scraper that is merely reporting
        # its own failure -- that would mask the real error.
        with contextlib.suppress(Exception):
            on_failure(failure)

    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)
