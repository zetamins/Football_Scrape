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

from .orchestrate import SourceStatus, run_search
from .report import build_report_json

_NOOP_PROGRESS: Callable[[str], None] = lambda msg: None
_NOOP_SOURCE_PROGRESS: Callable[[str], None] = lambda status_json: None


def run_report(
    team_name: str,
    on_progress: Callable[[str], None] = _NOOP_PROGRESS,
    on_source_progress: Callable[[str], None] = _NOOP_SOURCE_PROGRESS,
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

    Both callbacks are optional. Kotlin passes a `fun interface` instance
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

    result = asyncio.run(run_search(team_name, on_progress, _on_source_progress))
    return json.dumps(build_report_json(result), default=str)
