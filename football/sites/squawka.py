"""Squawka scraper. Ported from src/sites/squawka.ts.

Requires Playwright: the data API (`/wp-json/vcsw/v2/statistics`) needs an
`X-WP-Nonce` header that's only ever embedded in a page's own server-
rendered HTML (`<script id="swp--common-block-args">`), not obtainable any
other way -- same category as a normal page's CSRF token, not a bypass of
anything (the endpoint itself isn't disallowed by robots.txt; only
/wp-admin/ and /cdn-cgi/* are). The competitions list (`window.swpConfig`)
comes free on the same page load.

Confirmed by direct testing: "Errors Leading to Goals", "Pressures", and
"PPDA" are all listed as selectable stat-filter options but return ZERO
actual items when queried, in every competition checked -- the option
existing doesn't mean the data exists. A handful of other guessed labels
also came back empty ("Big Chances Created", "Key Passes", "Pass Accuracy
%", "Crosses", "Saves", "Fouls Committed", "Dribbles Completed", "Expected
Goals", "Expected Assists") -- these may be real stats under a different
exact label string Squawka uses internally, or may not exist at all;
either way, not guessed at further here. See _STAT_NAMES below for the
current list of labels confirmed to return real data.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import fields

from playwright.async_api import Page

from ..browser import launch_browser
from ..http import USER_AGENT
from ..team_aliases import known_aliases_for
from ..team_name_match import strip_diacritics
from ..types import DefensiveStats


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", strip_diacritics(s).lower()).strip()


_LOAD_PAGE_CONTEXT_JS = """
() => {
  const args = JSON.parse(document.getElementById("swp--common-block-args").textContent);
  const competitions = (window.swpConfig && window.swpConfig.competitions) || [];
  return { nonce: args.nonce, competitions };
}
"""


async def _load_page_context(page: Page) -> tuple[str, list[dict]]:
    await page.goto("https://www.squawka.com/en/stats/clubs/arsenal/", timeout=20000, wait_until="networkidle")
    ctx = await page.evaluate(_LOAD_PAGE_CONTEXT_JS)
    return ctx["nonce"], ctx.get("competitions", [])


# Squawka's own competition list uses different names than the sources
# this project bases competition strings on for a couple of leagues --
# confirmed live: Spain's top division is "Primera Division" there, never
# "LaLiga"/"La Liga" (Sofascore's own naming), so an exact-match lookup
# silently returned zero results for every La Liga team. Small,
# hand-maintained, same convention as every other alias table in this
# project -- only covers mismatches actually observed.
_COMPETITION_ALIASES: dict[str, str] = {
    "laliga": "primera division",
    "la liga": "primera division",
}


def _resolve_competition_id(competitions: list[dict], competition_name: str) -> str | None:
    """Picks the most recent season among duplicate entries for the same
    competition name. Picking the latest start_date alone picks next
    season's not-yet-played entry once fixtures are announced (confirmed:
    a "Premier League 2026/27" entry existed with zero stats data, since
    that season hadn't started -- picking it silently produced empty
    results for every player). Filtering to seasons that have actually
    started avoids that trap.

    Squawka's own start_date strings have no timezone marker at all
    ("2026-08-21 00:00:00", space-separated, not ISO-8601) -- confirmed
    live. Parsed and compared as naive (no tzinfo) here rather than
    assuming a zone that isn't actually in the data; JS's `new Date()` on
    this non-standard format falls back to the host's local time, an
    equally approximate reading, not a precisely-specified one either."""
    import datetime as _dt

    normalized = _normalize(competition_name)
    target = _COMPETITION_ALIASES.get(normalized, normalized)
    now = _dt.datetime.now()
    matches = [
        c
        for c in competitions
        if _normalize(c["competition"]) == target
        and _dt.datetime.strptime(c["start_date"], "%Y-%m-%d %H:%M:%S") <= now
    ]
    if not matches:
        return None
    matches.sort(key=lambda c: c["start_date"], reverse=True)
    return matches[0]["_id"]


_STAT_NAMES: list[tuple[str, str]] = [
    ("tackles_made", "Tackles Made"),
    ("interceptions", "Interceptions"),
    ("ball_recoveries", "Ball Recoveries"),
    ("clearances", "Clearances"),
    ("ground_duel_success_pct", "Ground Duel Success %"),
    ("chances_created", "Chances Created"),
    # Confirmed live: these 5 all return real non-empty data (never tried
    # before -- the module's own docstring only ever checked the six
    # above plus 3 confirmed-empty options, never the Shooting/Passing/
    # Duels categories these come from).
    ("shots", "Shots"),
    ("shots_on_target", "Shots On Target"),
    ("passes_completed", "Passes Completed"),
    ("fouls_won", "Fouls Won"),
    ("aerial_duels_won", "Aerial Duels Won"),
    # Confirmed live a second time, this pass reading the exact label
    # strings off the site's own rendered column headers (via the stat
    # group tables on a club's squad-stats page) rather than guessing --
    # two earlier guesses had been wrong for exactly this reason ("Pass
    # Accuracy %" isn't real, "Passing Accuracy %" is; "Red Cards" isn't
    # real, and even the exact header text "Total Red Cards" still comes
    # back empty -- plausibly genuine sparse data this early in a season,
    # not a label mismatch, so not pursued further).
    ("goals_from_inside_box", "Goals From Inside Box"),
    ("goals_from_outside_box", "Goals From Outside Box"),
    ("conversion_rate_pct", "Conversion Rate %"),
    ("shots_off_target", "Shots Off Target"),
    ("passes_attempted", "Passes Attempted"),
    ("passing_accuracy_pct", "Passing Accuracy %"),
    ("blocked_shots", "Blocked Shots"),
    ("take_ons_completed", "Take-ons completed"),
    ("ground_duels_won", "Ground Duels Won"),
]

_FETCH_STAT_JS = """
async ({ nonce, competitionId, statLabel }) => {
  const res = await fetch("https://www.squawka.com/en/wp-json/vcsw/v2/statistics", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json", "X-WP-Nonce": nonce },
    body: JSON.stringify({ sports_type: "football", top_count: 9999, entity_type: "members", competition_id: competitionId, stats: [statLabel] }),
  });
  return res.json();
}
"""


async def _fetch_stat_values(page: Page, nonce: str, competition_id: str, stat_label: str) -> dict[str, float]:
    result = await page.evaluate(_FETCH_STAT_JS, {"nonce": nonce, "competitionId": competition_id, "statLabel": stat_label})
    values: dict[str, float] = {}
    for item in (result or {}).get("items", []):
        groups = item.get("statistic_groups") or []
        value = groups[0].get("statistics", [{}])[0].get("value") if groups else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            key = f"{_normalize(item['name'])}::{_normalize(item['participant_name'])}"
            values[key] = value
    return values


async def get_squawka_defensive_stats(team_name: str, competition_candidates: list[str]) -> dict[str, DefensiveStats]:
    """Returns per-player defensive stats for a team, keyed by normalized
    player name -- empty if the competition isn't in Squawka's coverage
    (skews English/European top leagues; confirmed no Brasileirao, for
    example) or the team name doesn't match any entry.

    Takes CANDIDATE competition names (a team's own recent competitions),
    not the upcoming match's specific competition. That distinction
    matters: the upcoming fixture is often a friendly or cup tie ("Club
    Friendly Games", "Copa Betano do Brasil"), which Squawka obviously
    doesn't track as a league -- using it directly would silently return
    nothing for most searches. Tries each candidate in order and uses the
    first one that actually resolves to a real Squawka competition."""
    result: dict[str, DefensiveStats] = {}
    if not competition_candidates:
        return result

    # Browser launch happens OUTSIDE the try/except (mirrors the TS
    # version): a launch failure is a real, loud error (environment/
    # infrastructure problem), while failures fetching Squawka's own data
    # after that degrade gracefully to an empty result. Collapsing both
    # into one try/except would silently swallow launch failures too.
    browser_cm = launch_browser()
    browser = await browser_cm.__aenter__()
    try:
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()
        nonce, competitions = await _load_page_context(page)

        competition_id: str | None = None
        for candidate in competition_candidates:
            competition_id = _resolve_competition_id(competitions, candidate)
            if competition_id:
                break
        if not competition_id:
            return result

        # Exact-equality matching against Squawka's own embedded team name
        # is stricter than every other site in this project (no substring
        # fallback), so a site-specific spelling silently returns nothing.
        # Comparing against every known alias (team_aliases.py), not just
        # the searched name itself, closes that gap the same way the other
        # sites' resolvers do.
        target_team_variants = set(known_aliases_for(team_name))
        by_stat: dict[str, dict[str, float]] = {}
        for _, label in _STAT_NAMES:
            by_stat[label] = await _fetch_stat_values(page, nonce, competition_id, label)
            await asyncio.sleep(0.4)

        player_keys: set[str] = set()
        for values in by_stat.values():
            player_keys.update(values.keys())

        defensive_field_names = {f.name for f in fields(DefensiveStats)}
        for key in player_keys:
            player_norm, team_norm = key.split("::", 1)
            if team_norm not in target_team_variants:
                continue
            stat_kwargs = {name: None for name in defensive_field_names}
            for attr_name, label in _STAT_NAMES:
                stat_kwargs[attr_name] = by_stat[label].get(key)
            result[player_norm] = DefensiveStats(**stat_kwargs)
        return result
    except Exception:  # noqa: BLE001 - mirrors TS's catch { return result }
        return result
    finally:
        await browser_cm.__aexit__(None, None, None)
