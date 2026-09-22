"""Production Chaquopy entry point for the Android app: runs the full
search/insights pipeline and returns the report as a JSON string,
streaming per-source progress along the way. Replaces
android_test.py::run_full_report for the app's real search flow -- that
function stays as-is for its own diagnostic purpose (see its own
docstring); this module is the non-diagnostic production path.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import asdict

from .fetch_log import FetchFailure, capture_failures
from .orchestrate import SourceStatus, run_search
from .report import build_report_json

_NOOP_PROGRESS: Callable[[str], None] = lambda msg: None
_NOOP_SOURCE_PROGRESS: Callable[[str], None] = lambda status_json: None
_NOOP_FAILURE: Callable[[str], None] = lambda failure_json: None


def run_report(
    team_name: str,
    on_progress: Callable[[str], None] = _NOOP_PROGRESS,
    on_source_progress: Callable[[str], None] = _NOOP_SOURCE_PROGRESS,
    on_failure: Callable[[str], None] = _NOOP_FAILURE,
    past_predictions_json: str = "[]",
) -> str:
    """Runs the full search/insights pipeline and returns
    report.build_report_json's JSON shape as a string.

    on_progress: fired with free-text status lines ("Scraping fotmob...",
    "Next match found: ...", "Done.") -- the same messages
    orchestrate.py's CLI usage already prints. Useful for a simple
    "searching..." label, not for structured per-source state.

    on_source_progress: fired once per source, right after that source
    finishes (matches/details/profile all attempted), with a JSON string
    of one SourceStatus record, e.g.: {"source": "fotmob",
    "fixtures_scraped": 42, "matches_error": null, "details_error": null,
    "profile_error": null}. This is the structured per-source data a
    loading checklist needs (see frontend/DESIGN.md's Premium direction
    section) -- on_progress's free text alone isn't reliably parseable
    for that.

    on_failure: fired the moment any single link/API request fails for
    good (retries exhausted, or a 403/429 block), once per distinct URL,
    with a JSON string like {"source": "fotmob", "url": "https://...",
    "reason": "HTTP 403"} -- finer-grained than on_source_progress, which
    only reports a whole source's own summarized errors after it finishes.
    Lets the UI list failed links live as the search runs.

    past_predictions_json: a JSON array of the predictions the app saved
    earlier (each: home_team, away_team, kickoff_utc, generated_at,
    prediction). They're scored against finished results found in this
    run and reported under the report's "calibration" key -- see
    calibration.py. "[]" still yields a calibration block (nothing
    evaluated yet), so the key is always present from the app.

    All callbacks are optional. Kotlin passes a `fun interface` instance
    (e.g. `fun interface ProgressListener { fun invoke(message: String) }`)
    -- Chaquopy calls a Java/Kotlin single-abstract-method object exactly
    like a Python callable, so no extra glue is needed on the Python side
    for the on_progress(msg)/on_source_progress(status_json) call sites
    below.

    Synchronous/blocking (wraps asyncio.run() internally) -- Chaquopy's
    Kotlin-calls-Python interop has no concept of awaiting a coroutine,
    same reasoning as android_test.py::run_full_report. Call this from a
    background thread on the Kotlin side, never the main thread; both
    callbacks then also fire on that background thread, so a
    ProgressListener implementation that touches UI must itself hop to
    the main thread (the same pattern android_test.py's runStage() already
    uses via runOnUiThread)."""

    def _on_source_progress(status: SourceStatus) -> None:
        on_source_progress(json.dumps(asdict(status)))

    def _on_failure(failure: FetchFailure) -> None:
        on_failure(json.dumps(asdict(failure)))

    with capture_failures(_on_failure):
        result = asyncio.run(run_search(team_name, on_progress, _on_source_progress, json.loads(past_predictions_json)))
    return json.dumps(build_report_json(result), default=str)
