"""Proof-of-concept bridge for MainActivity.kt to call, to verify the
WebView browser backend (browser.py's Android branch) works end to end
against a real site. Not part of the actual scraping pipeline --
orchestrate.py/cli.py call the sites/ modules directly.

Exists as a plain synchronous function because Chaquopy's Java-calls-
Python interop has no concept of awaiting a coroutine -- Kotlin calls a
regular callable and gets a regular return value, so the async entry
point is wrapped in asyncio.run() here rather than asking Kotlin to
understand Python's async machinery."""

from __future__ import annotations

import asyncio
import json

from .android_bridge import get_application_context
from .browser import launch_browser
from .http import USER_AGENT
from .insights import compute_data_completeness
from .orchestrate import run_search
from .report import build_report_json
from .sites.sofascore import (
    get_sofascore_match_details,
    get_sofascore_matches,
    get_sofascore_team_profile,
)
from .sites.squawka import (
    _STAT_NAMES,
    _fetch_stat_values,
    _load_page_context,
    _resolve_competition_id,
    get_squawka_defensive_stats,
)
from .sites.worldfootball import (
    _COMPETITION_PATHS,
    _fetch_referee_table,
    get_referee_worldfootball_stats,
)
from .team_aliases import known_aliases_for


async def _diagnose(competition: str, referee_name: str) -> str:
    """Reports the raw row count/names too, not just the final match --
    get_referee_worldfootball_stats itself catches every exception
    internally (mirrors the TS original's catch-all) and returns None for
    both "evaluate failed" and "genuinely no match", which look identical
    from test_worldfootball_referee_stats alone."""
    path = _COMPETITION_PATHS.get(competition)
    if not path:
        return f"Unknown competition: {competition}"
    async with launch_browser() as browser:
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()
        rows = await _fetch_referee_table(page, path)
        names = ", ".join(r.name for r in rows[:5])
        return f"{len(rows)} rows scraped. First few: {names}"


def run_full_report(team_name: str) -> str:
    """The REAL end-to-end path, not an isolated diagnostic call: the same
    orchestrate.run_search() + report.build_report_json() sequence
    cli.py's own CLI entry point uses. Exercises all 13 sources (10
    plain-HTTP via httpx + the 3 WebView-backed ones), merge.py,
    insights.py, elo.py/prediction.py, and report.py's JSON serialization
    together in one run -- every other function in this module tests one
    piece of the WebView bridge in isolation; this is the only one that
    proves the whole pipeline actually produces a correct report on
    Android.

    Writes the JSON to the app's own private files directory (not
    anywhere requiring extra permissions) so it can be pulled off-device
    with `adb pull` and inspected directly -- the same way the desktop
    CLI's output/*.json files get inspected."""
    try:
        result = asyncio.run(run_search(team_name))
    except Exception as e:  # noqa: BLE001
        return f"FAILED during run_search: {type(e).__name__}: {e}"

    try:
        report = build_report_json(result)
        payload = json.dumps(report, indent=2, default=str)
    except Exception as e:  # noqa: BLE001
        return f"FAILED during build_report_json/serialization: {type(e).__name__}: {e}"

    files_dir = get_application_context().getFilesDir().getAbsolutePath()
    out_path = f"{files_dir}/report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(payload)

    if not result.merged:
        return f"OK (no upcoming match found from any source) -- wrote {len(payload)} bytes to {out_path}"

    completeness = compute_data_completeness(result.merged, result.insights)
    source_summary = ", ".join(f"{s.source}={s.fixtures_scraped}" for s in result.statuses)
    return (
        f"OK -- {result.merged.home_team} vs {result.merged.away_team}. "
        f"{completeness['populated']}/{completeness['total']} fields populated. "
        f"Sources: {source_summary}. Wrote {len(payload)} bytes to {out_path}"
    )


def run_worldfootball_referee_stats(competition: str, referee_name: str) -> str:
    # Not named test_* -- pytest's default collection pattern would try
    # to run this as a test itself (parameters looking like unresolvable
    # fixtures) despite testpaths already excluding this file's directory.
    result = asyncio.run(get_referee_worldfootball_stats(competition, referee_name))
    if result is not None:
        return f"penalties={result.penalties}, second_yellow={result.second_yellow}"
    diagnosis = asyncio.run(_diagnose(competition, referee_name))
    return f"No match for '{referee_name}'. Diagnosis: {diagnosis}"


def run_sofascore_matches(team_name: str) -> str:
    """Exercises the WebView bridge much harder than worldfootball's
    single goto+evaluate: _find_team's search call, then a full fixture
    list fetch, each wrapped in _retry_with_backoff (up to 3 attempts),
    all through the same one WebView page/context."""
    try:
        matches = asyncio.run(get_sofascore_matches(team_name))
    except Exception as e:  # noqa: BLE001 - report to the screen, don't crash the app
        return f"FAILED: {type(e).__name__}: {e}"
    if not matches:
        return "0 matches returned (search may have found no team, or the fixture fetch failed)"
    sample = matches[0]
    return f"{len(matches)} matches. First: {sample.home_team} vs {sample.away_team} ({sample.kickoff_utc})"


def run_sofascore_match_details(team_name: str) -> str:
    """Never exercised via WebView before this -- get_sofascore_matches
    (already tested) only covers the search+fixture-list call shape;
    match_details is a separate function hitting a different, larger set
    of same-origin /api/v1/... endpoints (lineups, stats, head-to-head,
    etc.) through the SAME WebView page."""
    try:
        matches = asyncio.run(get_sofascore_matches(team_name))
        if not matches:
            return "FAILED: get_sofascore_matches returned 0 matches, can't fetch details for none"
        details = asyncio.run(get_sofascore_match_details(matches[0]))
    except Exception as e:  # noqa: BLE001
        return f"FAILED: {type(e).__name__}: {e}"
    return (
        f"OK -- {matches[0].home_team} vs {matches[0].away_team}: "
        f"referee={details.referee}, venue={details.venue_name}, "
        f"h2h_summary_present={details.head_to_head_summary is not None}"
    )


def run_sofascore_team_profile(team_name: str) -> str:
    """Never exercised via WebView before this -- a third, independent
    Sofascore call shape (squad + transfers endpoints)."""
    try:
        profile = asyncio.run(get_sofascore_team_profile(team_name))
    except Exception as e:  # noqa: BLE001
        return f"FAILED: {type(e).__name__}: {e}"
    squad_size = len(profile.squad) if profile.squad else 0
    transfers = len(profile.recent_transfers) if profile.recent_transfers else 0
    return f"OK -- squad_size={squad_size}, recent_transfers={transfers}, average_age={profile.average_age}"


async def _diagnose_squawka(team_name: str, competition: str) -> str:
    """get_squawka_defensive_stats has 3 silent-empty-result exit points
    (no competition match, no player_keys at all, or player_keys present
    but none matching team_name's aliases) that all look identical from
    the outside -- checks each stage directly instead of guessing which
    one is responsible."""
    async with launch_browser() as browser:
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()
        nonce, competitions = await _load_page_context(page)
        if not nonce:
            return "_load_page_context returned no nonce -- WebView evaluate() likely failed"
        competition_id = _resolve_competition_id(competitions, competition)
        if not competition_id:
            names = ", ".join(c.get("competition", "?") for c in competitions[:8])
            return f"nonce OK ({len(competitions)} competitions loaded), but '{competition}' didn't resolve. Sample names: {names}"
        _, sample_label = _STAT_NAMES[0]
        values = await _fetch_stat_values(page, nonce, competition_id, sample_label)
        if not values:
            return f"competition_id resolved ({competition_id}), but '{sample_label}' fetch returned 0 values"
        variants = set(known_aliases_for(team_name))
        # Checks every key, not just a sample -- a 5-key sample from a
        # 400+-entry dict landing on 5 other teams by chance doesn't prove
        # team_name's team is genuinely absent.
        matching = [k for k in values if k.split("::", 1)[1] in variants]
        all_team_norms = sorted({k.split("::", 1)[1] for k in values})
        if matching:
            return f"{len(values)} values fetched, {len(matching)} matched team aliases {sorted(variants)}: {matching[:5]}"
        close = [t for t in all_team_norms if any(v[:4] in t for v in variants)]
        return (
            f"{len(values)} values fetched across {len(all_team_norms)} teams, but NONE matched "
            f"team aliases {sorted(variants)}. Closest-looking team names present: {close or all_team_norms[:10]}"
        )


def run_squawka_defensive_stats(team_name: str, competition: str) -> str:
    """Exercises the async-fetch()-with-custom-header path specifically
    (_FETCH_STAT_JS does `fetch(..., headers: {"X-WP-Nonce": nonce}})`
    from within the injected script) -- the one call shape worldfootball
    and sofascore's own evaluate() calls don't cover."""
    try:
        stats_by_name = asyncio.run(get_squawka_defensive_stats(team_name, [competition]))
    except Exception as e:  # noqa: BLE001
        return f"FAILED: {type(e).__name__}: {e}"
    if stats_by_name:
        names = ", ".join(list(stats_by_name.keys())[:5])
        return f"{len(stats_by_name)} players. First few: {names}"
    try:
        diagnosis = asyncio.run(_diagnose_squawka(team_name, competition))
    except Exception as e:  # noqa: BLE001
        diagnosis = f"diagnose itself failed: {type(e).__name__}: {e}"
    return f"0 players. Diagnosis: {diagnosis}"
