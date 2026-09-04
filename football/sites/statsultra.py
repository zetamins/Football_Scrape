"""StatsUltra scraper. Ported from src/sites/statsultra.ts.

statsultra.com's robots.txt (Content-Signal: use=reference, explicit
Allow: / for User-agent: *) only disallows specifically-named crawlers
(ClaudeBot, GPTBot, etc.), same distinction this project has drawn
throughout -- and unlike worldfootball.net, plain fetch works with no
Cloudflare challenge at all, confirmed live. The whole ratings table (480
clubs across 30 leagues, recalculated daily from FootyStats' own data)
renders server-side in one page, so one fetch covers every team a search
could name -- one shared request, match locally against the full table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..http import fetch_text
from ..team_aliases import known_aliases_for
from ..team_name_match import normalize_for_match as _normalize, strip_diacritics
from ..types import ClubStrengthRating

_FULL_NAME_RE = re.compile(r'<span class="full-name">([^<]+)</span>')
_STRENGTH_RE = re.compile(r'<span class="strength-num">([\d.]+)</span>')
_ATTACK_RE = re.compile(r'<span class="profile-num off">([\d.]+)</span>')
_DEFENSE_RE = re.compile(r'<span class="profile-num def">([\d.]+)</span>')
# The row's first bare <td>N</td> is this club's rank in the flat 480-club
# table (confirmed live) -- every other numeric cell in the row is inside a
# classed <span>, not a bare <td>, so the first match is unambiguous.
_RANK_RE = re.compile(r"<td>(\d+)</td>")
_STRENGTH_CHANGE_RE = re.compile(r'data-strength-change="([+-]?[\d.]+)"')


@dataclass
class _StrengthRow:
    name: str
    overall: float
    attack: float
    defense: float
    rank: int | None
    strength_change: float | None


def _parse_rows(html: str) -> list[_StrengthRow]:
    rows = []
    for row_html in html.split('<tr id="')[1:]:
        name_m = _FULL_NAME_RE.search(row_html)
        overall_m = _STRENGTH_RE.search(row_html)
        attack_m = _ATTACK_RE.search(row_html)
        defense_m = _DEFENSE_RE.search(row_html)
        if name_m and overall_m and attack_m and defense_m:
            rank_m = _RANK_RE.search(row_html)
            change_m = _STRENGTH_CHANGE_RE.search(row_html)
            rows.append(
                _StrengthRow(
                    name=name_m.group(1),
                    overall=float(overall_m.group(1)),
                    attack=float(attack_m.group(1)),
                    defense=float(defense_m.group(1)),
                    rank=(int(rank_m.group(1)) if rank_m else None),
                    strength_change=(float(change_m.group(1)) if change_m else None),
                )
            )
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
