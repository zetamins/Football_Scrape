"""Static country coordinates/timezones for a rough country-to-country
travel estimate. Ported from src/geo.ts.

No live geocoding service is used -- Nominatim, Photon, and geocode.maps.co
all disallow their search endpoints in robots.txt. This table is shipped
data, not scraped at request time. Deliberately not exhaustive -- covers
nations that actually show up as team/venue countries across the sources
this tool uses. Unlisted countries just leave the distance null rather than
guessing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ._jsmath import js_round, js_round_to

_COUNTRY_COORDS: dict[str, tuple[float, float]] = {
    "England": (51.5072, -0.1276),
    "Scotland": (55.9533, -3.1883),
    "Wales": (51.4816, -3.1791),
    "Northern Ireland": (54.5973, -5.9301),
    "Ireland": (53.3498, -6.2603),
    "Spain": (40.4168, -3.7038),
    "Portugal": (38.7223, -9.1393),
    "France": (48.8566, 2.3522),
    "Germany": (52.52, 13.405),
    "Italy": (41.9028, 12.4964),
    "Netherlands": (52.3676, 4.9041),
    "Belgium": (50.8503, 4.3517),
    "Switzerland": (46.948, 7.4474),
    "Austria": (48.2082, 16.3738),
    "Poland": (52.2297, 21.0122),
    "Czech Republic": (50.0755, 14.4378),
    "Turkey": (39.9334, 32.8597),
    "Greece": (37.9838, 23.7275),
    "Croatia": (45.815, 15.9819),
    "Serbia": (44.7866, 20.4489),
    "Ukraine": (50.4501, 30.5234),
    "Russia": (55.7558, 37.6173),
    "Denmark": (55.6761, 12.5683),
    "Sweden": (59.3293, 18.0686),
    "Norway": (59.9139, 10.7522),
    "Finland": (60.1699, 24.9384),
    "Romania": (44.4268, 26.1025),
    "Hungary": (47.4979, 19.0402),
    "Slovakia": (48.1486, 17.1077),
    "Slovenia": (46.0569, 14.5058),
    "Bulgaria": (42.6977, 23.3219),
    "Bosnia and Herzegovina": (43.8563, 18.4131),
    "Cyprus": (35.1856, 33.3823),
    "Israel": (31.7683, 35.2137),
    "Qatar": (25.2854, 51.531),
    "Saudi Arabia": (24.7136, 46.6753),
    "United Arab Emirates": (24.4539, 54.3773),
    "Egypt": (30.0444, 31.2357),
    "Morocco": (33.9716, -6.8498),
    "Algeria": (36.7538, 3.0588),
    "Tunisia": (36.8065, 10.1815),
    "Nigeria": (9.0765, 7.3986),
    "Senegal": (14.7167, -17.4677),
    "Ghana": (5.6037, -0.187),
    "South Africa": (-25.7461, 28.1881),
    "USA": (38.9072, -77.0369),
    "United States of America": (38.9072, -77.0369),
    "Canada": (45.4215, -75.6972),
    "Mexico": (19.4326, -99.1332),
    "Brazil": (-15.8267, -47.9218),
    "Argentina": (-34.6037, -58.3816),
    "Uruguay": (-34.9011, -56.1645),
    "Paraguay": (-25.2637, -57.5759),
    "Chile": (-33.4489, -70.6693),
    "Colombia": (4.711, -74.0721),
    "Peru": (-12.0464, -77.0428),
    "Ecuador": (-0.1807, -78.4678),
    "Bolivia": (-16.5, -68.15),
    "Venezuela": (10.4806, -66.9036),
    "Japan": (35.6762, 139.6503),
    "South Korea": (37.5665, 126.978),
    "China": (39.9042, 116.4074),
    "People's Republic of China": (39.9042, 116.4074),
    "India": (28.6139, 77.209),
    "Australia": (-35.2809, 149.13),
    "New Zealand": (-41.2865, 174.7762),
    "Iran": (35.6892, 51.389),
    "Iraq": (33.3152, 44.3661),
    "Jordan": (31.9539, 35.9106),
}

# Standard-time UTC offset in hours -- real published offsets, not derived.
# Deliberately ignores daylight saving: which countries observe DST and
# exactly when it flips varies by hemisphere and by year, and getting that
# wrong would be worse than a clearly-labeled standard-time approximation.
# Countries spanning multiple zones (Russia, USA) use the zone of the
# coordinate already listed above (Moscow, Washington DC).
_COUNTRY_UTC_OFFSET: dict[str, float] = {
    "England": 0, "Scotland": 0, "Wales": 0, "Northern Ireland": 0, "Ireland": 0,
    "Spain": 1, "Portugal": 0, "France": 1, "Germany": 1, "Italy": 1, "Netherlands": 1,
    "Belgium": 1, "Switzerland": 1, "Austria": 1, "Poland": 1, "Czech Republic": 1,
    "Turkey": 3, "Greece": 2, "Croatia": 1, "Serbia": 1, "Ukraine": 2, "Russia": 3,
    "Denmark": 1, "Sweden": 1, "Norway": 1, "Finland": 2, "Romania": 2, "Hungary": 1,
    "Slovakia": 1, "Slovenia": 1, "Bulgaria": 2, "Bosnia and Herzegovina": 1,
    "Cyprus": 2, "Israel": 2, "Qatar": 3, "Saudi Arabia": 3, "United Arab Emirates": 4,
    "Egypt": 2, "Morocco": 0, "Algeria": 1, "Tunisia": 1, "Nigeria": 1, "Senegal": 0,
    "Ghana": 0, "South Africa": 2, "USA": -5, "United States of America": -5,
    "Canada": -5, "Mexico": -6, "Brazil": -3, "Argentina": -3, "Uruguay": -3,
    "Paraguay": -4, "Chile": -4, "Colombia": -5, "Peru": -5, "Ecuador": -5, "Bolivia": -4,
    "Venezuela": -4, "Japan": 9, "South Korea": 9, "China": 8,
    "People's Republic of China": 8, "India": 5.5, "Australia": 10,
    "New Zealand": 12, "Iran": 3.5, "Iraq": 3, "Jordan": 3,
}


def _normalize_country(name: str) -> str:
    return name.strip()


def country_utc_offset_hours(country: str) -> float | None:
    """Standard-time UTC offset for one country, or None if it isn't in
    the static table above -- same DST-ignoring caveat as that table."""
    return _COUNTRY_UTC_OFFSET.get(_normalize_country(country))


def country_timezone_diff_hours(country_a: str, country_b: str) -> float | None:
    """Absolute standard-time difference in hours, or None if either
    country isn't in the static table."""
    a = _COUNTRY_UTC_OFFSET.get(_normalize_country(country_a))
    b = _COUNTRY_UTC_OFFSET.get(_normalize_country(country_b))
    if a is None or b is None:
        return None
    return js_round_to(abs(a - b), 1)


@dataclass(frozen=True)
class Coord:
    lat: float
    lon: float


def haversine_km(a: Coord, b: Coord) -> int:
    """Haversine great-circle distance in km between two lat/lon points.
    Public (not just country_distance_km's own internal helper) since
    insights.py's compute_travel_info also uses it directly, for exact
    venue-to-venue distance when both teams' own venue coordinates are
    available -- see that function's own docstring."""
    r = 6371
    d_lat = math.radians(b.lat - a.lat)
    d_lon = math.radians(b.lon - a.lon)
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return js_round(r * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h)))


def country_distance_km(country_a: str, country_b: str) -> int | None:
    """Rough country-to-country distance in km, or None if either country
    isn't in the static table."""
    a = _COUNTRY_COORDS.get(_normalize_country(country_a))
    b = _COUNTRY_COORDS.get(_normalize_country(country_b))
    if a is None or b is None:
        return None
    return haversine_km(Coord(*a), Coord(*b))


def travel_time_hours(distance_km: float) -> float:
    """Door-to-door travel time estimate from a distance already computed
    via country_distance_km -- same "rough order of magnitude" framing, not
    a precise itinerary. Below 200km assumes ground transport (~80km/h
    average including stops). At/above that, assumes air travel at ~850km/h
    cruise speed plus a fixed 2-hour overhead for check-in/taxi/takeoff/
    landing/disembarking -- a standard door-to-door flight-time rule of
    thumb, not a figure fabricated for this project."""
    if distance_km < 200:
        return js_round_to(distance_km / 80, 1)
    return js_round_to(distance_km / 850 + 2, 1)
