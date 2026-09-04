"""StadiumDB scraper. Ported from src/sites/stadiumdb.ts.

Plain fetch works throughout -- robots.txt only disallows /lay-gfx/, no
AI-bot blocks. No sitemap or search endpoint exists on the site, so team
name -> stadium page resolution goes through the same per-country listing
pages a human visitor would browse: /stadiums (country code index, cached
once) -> /stadiums/{code} (every stadium in that country with its club(s)
and capacity, one page, no pagination even for England's 125 entries) ->
/stadiums/{code}/{slug} (the actual capacity/inauguration/renovation
facts). Three requests total per lookup, only the first ever repeated
across runs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..data_dir import data_dir
from ..http import fetch_text
from ..team_aliases import known_aliases_for
from ..team_name_match import normalize_for_match as _normalize, strip_diacritics
from ..types import VenueDetails


@dataclass
class _CountryEntry:
    code: str
    name: str


_COUNTRY_LINK_RE = re.compile(r'<a href="https://stadiumdb\.com/stadiums/([a-z]{3})"[^>]*>([^<]+)')


async def _build_country_index() -> list[_CountryEntry]:
    html = await fetch_text("https://stadiumdb.com/stadiums")
    return [_CountryEntry(code=m.group(1), name=m.group(2).strip()) for m in _COUNTRY_LINK_RE.finditer(html)]


async def _load_country_index() -> list[_CountryEntry]:
    seed_path = data_dir() / "stadiumdb-countries.json"
    try:
        raw = json.loads(seed_path.read_text(encoding="utf-8"))
        return [_CountryEntry(code=e["code"], name=e["name"]) for e in raw]
    except (FileNotFoundError, json.JSONDecodeError):
        entries = await _build_country_index()
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_text(json.dumps([{"code": e.code, "name": e.name} for e in entries]), encoding="utf-8")
        return entries


# Handles the handful of naming mismatches seen against other sources'
# venueCountry values ("USA" vs StadiumDB's "United States of America",
# etc) on top of plain substring matching.
_COUNTRY_ALIASES: dict[str, str] = {
    "usa": "united states of america",
    "united states": "united states of america",
    "korea republic": "south korea",
    "uae": "united arab emirates",
}


def _resolve_country_code(entries: list[_CountryEntry], country_name: str) -> str | None:
    target = _COUNTRY_ALIASES.get(_normalize(country_name), _normalize(country_name))
    exact = next((e for e in entries if _normalize(e.name) == target), None)
    if exact:
        return exact.code
    partial = next(
        (e for e in entries if target in _normalize(e.name) or _normalize(e.name) in target), None
    )
    return partial.code if partial else None


@dataclass
class _StadiumRow:
    url: str
    stadium_name: str
    city: str
    clubs: list[str]
    capacity: int | None


_ROW_RE = re.compile(
    r'<a href="(https://stadiumdb\.com/stadiums/[a-z]{3}/[a-z0-9_]+)" class="nu-reward">([^<]+)</a>\s*'
    r"</td>\s*<td>\s*([^<]*?)\s*</td>\s*<td>\s*([^<]*?)\s*</td>\s*"
    r'<td class="figure">\s*([\d\s]*?)\s*</td>'
)


def _parse_country_page(html: str) -> list[_StadiumRow]:
    rows: list[_StadiumRow] = []
    for m in _ROW_RE.finditer(html):
        capacity_digits = re.sub(r"\s", "", m.group(5))
        # "-" means "no club plays here" (motor speedways, athletics
        # venues, etc, since StadiumDB isn't football-only) -- must be
        # dropped before matching, not just filtered for emptiness, since
        # normalize("-") is "" and "" substring-matches everything.
        clubs = [c.strip() for c in m.group(4).split(",") if c.strip() and c.strip() != "-"]
        rows.append(
            _StadiumRow(
                url=m.group(1),
                stadium_name=m.group(2).strip(),
                city=m.group(3).strip(),
                clubs=clubs,
                capacity=int(capacity_digits) if capacity_digits else None,
            )
        )
    return rows


def _find_club_row(rows: list[_StadiumRow], team_name: str) -> _StadiumRow | None:
    # Try the searched name and every known alias (team_aliases.py) --
    # e.g. StadiumDB lists Royale Union Saint-Gilloise as "Royale Union
    # SG", which shares no substring with "saint gilloise" at all (a
    # different abbreviation of the same name), confirmed live.
    # known_aliases_for() returns just [normalize(team_name)] for any
    # team not in the table, so this is a no-op for most lookups.
    #
    # Exact matching is tried across EVERY variant before any variant
    # falls back to fuzzy matching -- confirmed live this matters: PSG's
    # canonical "paris saint germain" fuzzy-matches an unrelated 7,151-
    # capacity amateur ground listed simply as "Paris", which would have
    # been returned before the "psg" alias ever got a chance at its own
    # exact match against StadiumDB's real "PSG" row (47,929 capacity,
    # the actual Parc des Princes).
    targets = known_aliases_for(team_name)
    for target in targets:
        exact = next((r for r in rows if any(_normalize(c) == target for c in r.clubs)), None)
        if exact:
            return exact

    for target in targets:

        def fuzzy_ok(c: str, target: str = target) -> bool:
            # Guard against degenerate substring matches: a normalized
            # club name shorter than 4 chars ("PSG", "AEK") is too easy
            # to false-positive against an unrelated multi-word team name.
            return len(c) >= 4 and (c in target or target in c)

        candidates = [r for r in rows if any(fuzzy_ok(_normalize(c)) for c in r.clubs)]
        if not candidates:
            continue
        if len(candidates) == 1:
            return candidates[0]
        # StadiumDB genuinely lists several distinct German clubs' rows
        # with the identical bare club name "Borussia" (Dortmund,
        # Mönchengladbach, Neunkirchen...) -- confirmed live -- so a
        # club-name match alone can't disambiguate. The row's own city is
        # a second, reliable signal (it's still there even when the club
        # name is truncated); among city matches, prefer the largest
        # capacity (the senior/main ground over a reserve or lower-league
        # one, same convention as "prefer shortest slug" elsewhere).
        city_matches = [r for r in candidates if _normalize(r.city) and (_normalize(r.city) in target or target in _normalize(r.city))]
        pool = city_matches or candidates
        return max(pool, key=lambda r: r.capacity or 0)
    return None


_STADIUM_TABLE_RE = re.compile(r'<table class="stadium-info">([\s\S]*?)</table>')


def _parse_stadium_page(html: str) -> dict[str, object]:
    table_m = _STADIUM_TABLE_RE.search(html)
    table = table_m.group(1) if table_m else ""

    def field(label: str) -> str | None:
        m = re.search(rf"<th>\s*{label}\s*</th>\s*<td>\s*([^<]*?)\s*</td>", table, re.IGNORECASE)
        return m.group(1).strip() if m else None

    capacity_str = field("Capacity")
    opened_str = field("Inauguration")
    opened_digits = re.search(r"\d{4}", opened_str) if opened_str else None
    return {
        "capacity": int(re.sub(r"\s", "", capacity_str)) if capacity_str and re.sub(r"\s", "", capacity_str) else None,
        "opened": int(opened_digits.group(0)) if opened_digits else None,
        "renovated": field("Renovations"),
        "city": field("City"),
        "address": field("Address"),
        "architect": field("Design"),
        "record_attendance": field("Record attendance"),
    }


async def get_stadium_db_venue_details(team_name: str, venue_country: str | None) -> VenueDetails | None:
    """Resolves by CLUB name (the country listing page has a "Clubs"
    column), not by venue name -- more reliable, since sponsor-naming
    differences between sources ("Etihad Stadium" vs "City of Manchester
    Stadium", "Hill Dickinson Stadium" vs "Everton Stadium") would break a
    venue-name match far more often than a club-name match. Needs the
    searched team's own country (from the merged match's venue_country) to
    pick which per-country page to search -- returns None without it, or if
    that country isn't in StadiumDB's index, or if no row's club list
    matches."""
    if not venue_country:
        return None
    countries = await _load_country_index()
    code = _resolve_country_code(countries, venue_country)
    if not code:
        return None

    country_html = await fetch_text(f"https://stadiumdb.com/stadiums/{code}")
    rows = _parse_country_page(country_html)
    row = _find_club_row(rows, team_name)
    if not row:
        return None

    detail_html = await fetch_text(row.url)
    parsed = _parse_stadium_page(detail_html)

    return VenueDetails(
        stadium_name=row.stadium_name,
        capacity=parsed["capacity"] or row.capacity,
        opened=parsed["opened"],
        renovated=parsed["renovated"],
        clubs=row.clubs,
        source_url=row.url,
        city=parsed["city"] or row.city or None,
        address=parsed["address"],
        architect=parsed["architect"],
        record_attendance=parsed["record_attendance"],
    )
