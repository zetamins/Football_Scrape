"""worldfootball.net scraper. Ported from src/sites/worldfootball.ts.

worldfootball.net's robots.txt (Content-Signal: search=yes, ai-train=no,
use=reference; explicit Allow: / for User-agent: *) doesn't disallow this
path for a normal browser UA -- only specifically-named crawlers
(ClaudeBot, GPTBot, etc., in the Cloudflare-managed block) are disallowed,
same distinction this project has drawn throughout. It's behind Cloudflare
and returns 403 to a plain fetch, but 200s through a real headless browser
(confirmed live) -- the same "satisfy a JS challenge" case as Sofascore,
not a harder block like FBref.

Only the "big 5" competitions this project has real continental/relegation-
spot data for are mapped here -- deliberately small, same convention as
every other static table in this project. A competition not in this map
just resolves to no data rather than guessing at a URL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

from ..browser import launch_browser
from ..fetch_log import record_failure
from ..http import USER_AGENT
from ..retry import retry_with_backoff
from ..team_name_match import normalize_for_match as _normalize

_COMPETITION_PATHS: dict[str, str] = {
    "Premier League": "co91/england-premier-league",
    "LaLiga": "co97/spain-primera-division",
    "La Liga": "co97/spain-primera-division",
    "Serie A": "co111/italy-serie-a",
    "Bundesliga": "co12/germany-bundesliga",
    "Ligue 1": "co71/france-ligue-1",
}


@dataclass
class _RefereeRow:
    name: str
    penalties: int | None
    # Second-yellow-then-red count -- distinct from a straight red (the
    # table's separate "Red" column, not currently used by this project
    # since Sofascore's season red_cards total already covers that).
    second_yellow: int | None


@dataclass
class WorldfootballRefereeStats:
    penalties: int | None
    second_yellow: int | None


_TABLE_JS = """
() => {
  const tables = [...document.querySelectorAll("table.module-statistics")];
  for (const table of tables) {
    const headerCells = [...(table.querySelector("tr")?.querySelectorAll("th") ?? [])].map((th) => th.textContent?.trim() ?? "");
    const penaltyCol = headerCells.findIndex((h) => h === "11m");
    const secondYellowCol = headerCells.findIndex((h) => h === "Yellow-Red");
    const nameCol = headerCells.findIndex((h) => h.toLowerCase() === "name");
    if (penaltyCol === -1 || nameCol === -1) continue;
    const rows = [...table.querySelectorAll("tr")].slice(1);
    return rows.map((tr) => {
      const cells = [...tr.querySelectorAll("td")];
      const name = cells[nameCol]?.textContent?.trim() ?? "";
      const cellNum = (col) => {
        if (col === -1) return null;
        const text = cells[col]?.textContent?.trim() ?? "";
        const n = text === "" ? null : Number(text);
        return Number.isFinite(n) ? n : null;
      };
      return { name, penalties: cellNum(penaltyCol), secondYellow: cellNum(secondYellowCol) };
    });
  }
  return [];
}
"""


async def _fetch_referee_table(page: Page, competition_path: str) -> list[_RefereeRow]:
    # Retried like sofascore.py's own goto()+evaluate() calls -- confirmed
    # live (this project's own Android/WebView work) that a single attempt
    # against this Cloudflare-protected site can genuinely fail or time out
    # even when the site itself is reachable and a second attempt succeeds
    # quickly, e.g. because Cloudflare already set a clearance cookie
    # during the failed first attempt. Unlike sofascore.py's _find_team
    # (which explicitly does NOT retry, because a real CDN-level block was
    # confirmed to make retrying pointless there), this endpoint has no
    # evidence of that failure mode -- only of transient slowness.
    url = f"https://www.worldfootball.net/competition/{competition_path}/referees/"

    async def attempt() -> list[_RefereeRow]:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        rows = await page.evaluate(_TABLE_JS)
        return [_RefereeRow(name=r["name"], penalties=r["penalties"], second_yellow=r["secondYellow"]) for r in rows]

    try:
        return await retry_with_backoff(attempt)
    except Exception as err:
        record_failure(url, err)
        raise


async def get_referee_worldfootball_stats(
    competition: str | None, referee_name: str | None
) -> WorldfootballRefereeStats | None:
    """Current-season penalties-awarded and second-yellow-card counts for
    one referee, both from the same fetch/row of worldfootball.net's own
    competition referee-stats page (zero extra requests for the second
    stat). Returns None (not an error) whenever the competition isn't in
    _COMPETITION_PATHS or the referee doesn't appear in that table -- same
    graceful-degradation as every other supplemental lookup in this
    project."""
    if not competition or not referee_name:
        return None
    path = _COMPETITION_PATHS.get(competition)
    if not path:
        return None

    # Browser launch happens OUTSIDE the try/except (mirrors the TS
    # version) -- see squawka.py's get_squawka_defensive_stats for why.
    browser_cm = launch_browser()
    browser = await browser_cm.__aenter__()
    try:
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()
        rows = await _fetch_referee_table(page, path)
        target = _normalize(referee_name)
        hit = next((r for r in rows if _normalize(r.name) == target), None)
        if hit is None:
            hit = next(
                (r for r in rows if _normalize(r.name) in target or target in _normalize(r.name)), None
            )
        if hit is None:
            return None
        return WorldfootballRefereeStats(penalties=hit.penalties, second_yellow=hit.second_yellow)
    except Exception:  # noqa: BLE001 - mirrors TS's catch { return null }
        return None
    finally:
        await browser_cm.__aexit__(None, None, None)
