"""StatsUltra scraper. Ported from src/sites/statsultra.ts.

statsultra.com's robots.txt (Content-Signal: use=reference, explicit
Allow: / for User-agent: *) only disallows specifically-named crawlers
(ClaudeBot, GPTBot, etc.), same distinction this project has drawn
throughout -- and unlike worldfootball.net, plain fetch works with no
Cloudflare challenge at all, confirmed live. The whole ratings table (526
clubs across ~30 leagues as of this writing, recalculated daily from
FootyStats' own data) is embedded in one page, so one fetch covers every
team a search could name -- one shared request, match locally against the
full table.

The site was re-platformed at some point after this scraper was first
written: confirmed live the table body this module used to scrape
(`<tr id="...">` rows with `full-name`/`strength-num`/`profile-num`
spans) is now built CLIENT-SIDE by JavaScript from a JSON payload -- the
old markup only survives as a JS template literal inside a function body
(`'<tr id="' + esc(row.id) + '" ...'`), never real rendered HTML, so the
previous row-scraping regexes always matched zero rows. The underlying
data itself is still server-side and needs no JS execution: it's a plain
JSON blob sitting in a `<script id="st-strength-rows">` tag's text
content -- see _parse_rows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..http import fetch_text
from ..team_aliases import known_aliases_for
from ..team_name_match import normalize_for_match as _normalize
from ..types import ClubStrengthRating

_ROWS_SCRIPT_ID_MARKER = 'id="st-strength-rows"'


@dataclass
class _StrengthRow:
    name: str
    overall: float
    attack: float
    defense: float
    rank: int | None
    strength_change: float | None


def _extract_rows_script_json(html: str) -> str | None:
    """Plain string search rather than a regex spanning the whole script
    body -- a `[\\s\\S]*?` (or `.*?` with DOTALL) pattern reaching across a
    large embedded JSON blob is exactly the shape that risks super-linear
    backtracking on adversarial input (python:S8786); `str.find` has no
    such risk and this tag's structure (one `id="..."` attribute, plain
    text content, no nested `<script>`) doesn't need a regex at all."""
    id_pos = html.find(_ROWS_SCRIPT_ID_MARKER)
    if id_pos == -1:
        return None
    tag_end = html.find(">", id_pos)
    if tag_end == -1:
        return None
    content_end = html.find("</script>", tag_end)
    if content_end == -1:
        return None
    return html[tag_end + 1 : content_end]


def _parse_rows(html: str) -> list[_StrengthRow]:
    """Each row in the embedded payload's `rows` array is a fixed-position
    list, confirmed live against the real payload (matching the page's
    own JS buildModel() field order): [0] global rank, [1] slug, [2]
    short name, [3] full name (a falsy `0` when identical to the short
    name -- e.g. Tottenham/Man City have no separate full name), [4]
    abbreviation, [5] CSS color vars, [6] overall strength, [7] attack,
    [8] defense, [9] rank change, [10] strength change, [11] league
    index, [12:] assorted sub-ranks not needed here. Uses the full name
    when present, else the short name -- _find_rating's alias matching
    handles either spelling."""
    raw = _extract_rows_script_json(html)
    if raw is None:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    rows = []
    for r in payload.get("rows", []):
        if not isinstance(r, list) or len(r) < 11:
            continue
        rows.append(_StrengthRow(name=(r[3] or r[2]), overall=r[6], attack=r[7], defense=r[8], rank=r[0], strength_change=r[10]))
    return rows


def _find_rating(rows: list[_StrengthRow], team_name: str) -> ClubStrengthRating | None:
    # Try the searched name and every known alias (team_aliases.py) --
    # e.g. StatsUltra's own literal name for Nottingham Forest is
    # "Nott'ham Forest", confirmed live, sharing no substring with
    # "Nottingham Forest". known_aliases_for() returns just
    # [normalize(team_name)] for any team not in the table, so this is a
    # no-op for most lookups.
    hit = None
    for target in known_aliases_for(team_name):
        hit = next((r for r in rows if _normalize(r.name) == target), None)
        if hit is None:
            hit = next((r for r in rows if _normalize(r.name) in target or target in _normalize(r.name)), None)
        if hit:
            break
    if hit is None:
        return None
    return ClubStrengthRating(
        overall=hit.overall, attack=hit.attack, defense=hit.defense, rank=hit.rank, strength_change=hit.strength_change
    )


async def get_club_strength_ratings(home_team: str, away_team: str) -> dict[str, ClubStrengthRating | None]:
    """One shared fetch covers both teams -- no per-team search endpoint
    exists, matching happens locally against the full 480-club table.
    Best-effort: a team outside statsultra's 30-league coverage just
    resolves to None for that side."""
    rows = _parse_rows(await fetch_text("https://statsultra.com/club-strength/"))
    return {"home": _find_rating(rows, home_team), "away": _find_rating(rows, away_team)}
