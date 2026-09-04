"""RefsRadar scraper. Ported from src/sites/refsradar.ts.

refsradar.com's robots.txt (Allow: / for User-agent: *, only /api/
disallowed) permits the referee profile pages themselves -- the page is a
React Server Components payload, but it's plain server-rendered text over a
normal fetch, no JS execution needed (confirmed live: the "Fouls/g" figure
is readable directly in the raw response body).
"""

from __future__ import annotations

import re

from .._jsmath import js_number
from ..http import fetch_text
from ..team_name_match import normalize_for_match as _normalize, strip_diacritics

_SLUG_RE = re.compile(r"referees/([a-z0-9-]+)")
_TRAILING_ID_RE = re.compile(r"-\d+$")


def _slug_to_name(slug: str) -> str:
    """Slug -> name: "craig-pawson-367" -> "craig pawson". The sitemap
    lists both full-name and abbreviated ("c-pawson-1178") entries for the
    same referee -- preferring the longer slug (more words) picks the
    full-name one when both exist, rather than an arbitrary pick."""
    return _TRAILING_ID_RE.sub("", slug).replace("-", " ")


async def _find_referee_url(referee_name: str) -> str | None:
    sitemap = await fetch_text("https://refsradar.com/sitemap.xml")
    slugs = _SLUG_RE.findall(sitemap)
    target = _normalize(referee_name)

    candidates = [
        (slug, _normalize(_slug_to_name(slug)))
        for slug in slugs
    ]
    candidates = [
        (slug, name) for slug, name in candidates if name == target or target in name or name in target
    ]
    if not candidates:
        return None

    candidates.sort(key=lambda c: len(c[1]), reverse=True)
    return f"https://refsradar.com/referees/{candidates[0][0]}"


def _extract_kpi(html: str, label: str) -> float | None:
    """Real shape confirmed live: `<span class="lab">{label}</span><span
    class="val num">22.08</span>` -- except the RED/g figure specifically
    carries an extra `style="color:var(--red)"` attribute between `class`
    and `>` (confirmed live), so the value regex tolerates any attributes
    after `class="val num"` rather than requiring an exact `">` match.
    Next.js serves an RSC-JSON payload shape to some request profiles and
    this plain-HTML shape to others (content negotiated via the "vary:
    rsc" response header) -- this code path always gets the plain-HTML one
    in practice."""
    # A bare `>{label}<` search can collide with unrelated page furniture
    # sharing the same text (confirmed live: "Matches" also appears as a
    # nav link and a disabled tab label elsewhere on the page, both
    # earlier in the document than the real KPI) -- anchoring on the
    # `class="lab"` wrapper this project's own docstring above already
    # documents makes the match specific to an actual KPI label.
    m = re.search(rf'class="lab">{re.escape(label)}</span><span class="val num"[^>]*>([\d.]+)<', html)
    if not m:
        return None
    n = js_number(m.group(1))
    return n if n == n else None  # noqa: PLR0124 - NOSONAR(python:S1764) -- portable NaN check, not a typo


class RefereeKpis:
    def __init__(
        self,
        fouls_per_game: float | None,
        red_cards_per_game: float | None,
        matches: int | None = None,
        yellow_cards_per_game: float | None = None,
        penalties_per_game: float | None = None,
        cards_per_foul: float | None = None,
        avg_total_cards: float | None = None,
    ) -> None:
        self.fouls_per_game = fouls_per_game
        self.red_cards_per_game = red_cards_per_game
        # All four from the same profile-page fetch as fouls_per_game/
        # red_cards_per_game above -- confirmed live, 5 more real KPIs
        # ("Matches", "YEL/g", "Pens/g", "Cards/foul", "Avg total cards")
        # were sitting on the same page, unused. Zero extra requests.
        self.matches = matches
        self.yellow_cards_per_game = yellow_cards_per_game
        self.penalties_per_game = penalties_per_game
        self.cards_per_foul = cards_per_foul
        self.avg_total_cards = avg_total_cards


async def get_referee_kpis(referee_name: str | None) -> RefereeKpis | None:
    if not referee_name:
        return None
    try:
        url = await _find_referee_url(referee_name)
    except Exception:  # noqa: BLE001 - mirrors TS's .catch(() => null)
        url = None
    if not url:
        return None

    try:
        html = await fetch_text(url)
    except Exception:  # noqa: BLE001 - mirrors TS's .catch(() => null)
        return None

    matches_raw = _extract_kpi(html, "Matches")
    return RefereeKpis(
        fouls_per_game=_extract_kpi(html, "Fouls/g"),
        red_cards_per_game=_extract_kpi(html, "RED/g"),
        matches=(int(matches_raw) if matches_raw is not None else None),
        yellow_cards_per_game=_extract_kpi(html, "YEL/g"),
        penalties_per_game=_extract_kpi(html, "Pens/g"),
        cards_per_foul=_extract_kpi(html, "Cards/foul"),
        avg_total_cards=_extract_kpi(html, "Avg total cards"),
    )


async def get_referee_fouls_per_game(referee_name: str | None) -> float | None:
    """Fouls per game -- the one referee figure neither worldfootball.net
    (penalties) nor football-data.co.uk (home/away card bias) carries.
    Best-effort: null if the referee isn't in refsradar's own coverage
    (27+ leagues, not exhaustive) or the page shape doesn't match."""
    kpis = await get_referee_kpis(referee_name)
    return kpis.fouls_per_game if kpis else None


async def get_referee_red_cards_per_game(referee_name: str | None) -> float | None:
    """Red cards per game -- a rate, distinct from Sofascore's own
    red_cards (a raw season total, not a per-game figure). Same profile
    page/fetch as get_referee_fouls_per_game; callers wanting both should
    prefer get_referee_kpis directly to avoid fetching the page twice."""
    kpis = await get_referee_kpis(referee_name)
    return kpis.red_cards_per_game if kpis else None
