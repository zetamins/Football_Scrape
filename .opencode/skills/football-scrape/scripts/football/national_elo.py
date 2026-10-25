"""Opponent-adjusted national-team Elo ratings from World Football Elo
Ratings (eloratings.net), read from a committed seed cache
(data/national-elo.json) -- no network at report time.

Why this exists: elo.py's own rating assumes every past opponent was exactly
average, so it cannot tell a win over Gibraltar from a win over Spain (it
rated Slovenia below North Macedonia). eloratings.net ratings are
cross-calibrated across the whole national-team network. When both teams
are national sides in this table, orchestrate uses these instead.

Refresh with `python -m football.national_elo` (two plain GETs to
eloratings.net: World.tsv + en.teams.tsv). Ratings are as of the refresh
date; the cache records it.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from .data_dir import data_dir, seed_path

_SOURCE = "eloratings.net"
_BASE_URL = "https://www.eloratings.net"
_FETCH_TIMEOUT_S = 30

# Spellings used by Sofascore/Fotmob/etc. that differ from eloratings.net's
# English names. Keys and values are already in normalised form.
_NAME_ALIASES = {
    "turkiye": "turkey",
    "cote d ivoire": "ivory coast",
    "bosnia herzegovina": "bosnia and herzegovina",
    "congo republic": "congo",
    "republic of congo": "congo",
    "czech republic": "czechia",
    "cabo verde": "cape verde",
    "republic of ireland": "ireland",
    "korea republic": "south korea",
    "usa": "united states",
    "united states of america": "united states",
}


def _normalize(name: str) -> str:
    stripped = "".join(c for c in unicodedata.normalize("NFKD", name or "") if not unicodedata.combining(c))
    spelled = stripped.lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", spelled)).strip()


def canonical_name(name: str) -> str:
    """Normalised, alias-resolved spelling of a country/national-team name
    (so "Côte d'Ivoire" == "Ivory Coast", "Congo Republic" == "Congo")."""
    key = _normalize(name)
    return _NAME_ALIASES.get(key, key)


def _cache_path() -> Path:
    return seed_path("national-elo.json")


@lru_cache(maxsize=1)
def _load() -> tuple[str | None, dict[str, float]]:
    try:
        raw = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, {}
    ratings = {_normalize(k): float(v) for k, v in (raw.get("ratings") or {}).items()}
    return raw.get("as_of"), ratings


def lookup_national_elo(team_name: str | None) -> tuple[float, str] | None:
    """(rating, as_of) for a national team, by exact normalised name (plus the
    alias table above). Deliberately no substring matching -- "Congo" would
    swallow "DR Congo", "Niger" would swallow "Nigeria". Clubs, women's and
    youth sides don't match and return None."""
    if not team_name:
        return None
    as_of, ratings = _load()
    key = canonical_name(team_name)
    if key not in ratings or as_of is None:
        return None
    return ratings[key], as_of


def parse_tables(world_tsv: str, teams_tsv: str) -> dict[str, int]:
    """World.tsv: col 3 = team code, col 4 = rating. en.teams.tsv: code ->
    primary English name (first name column)."""
    names = {}
    for line in teams_tsv.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            names[parts[0]] = parts[1].strip()
    ratings = {}
    for line in world_tsv.splitlines():
        cols = line.split("\t")
        if len(cols) < 4 or not cols[3].strip().isdigit():
            continue
        ratings[names.get(cols[2], cols[2])] = int(cols[3])
    return ratings


def _get(path: str) -> str:
    req = urllib.request.Request(f"{_BASE_URL}/{path}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as resp:  # noqa: S310 -- fixed https URL
        return resp.read().decode("utf-8")


def refresh() -> int:
    """Download and rewrite the seed cache. Returns the number of teams."""
    ratings = parse_tables(_get("World.tsv"), _get("en.teams.tsv"))
    if len(ratings) < 100:
        raise RuntimeError(f"eloratings.net returned only {len(ratings)} teams; refusing to overwrite the cache")
    payload = {"source": _SOURCE, "as_of": datetime.now(UTC).date().isoformat(), "ratings": ratings}
    _cache_path().write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    _load.cache_clear()
    return len(ratings)


if __name__ == "__main__":
    print(f"wrote {refresh()} national-team ratings to {_cache_path()}")
