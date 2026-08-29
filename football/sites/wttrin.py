"""wttr.in weather scraper. Ported from src/sites/wttrin.ts.

AccuWeather is hard-blocked (Akamai WAF), same class of block as fbref,
not something a normal browser render gets past. wttr.in is the
replacement: it has no dedicated /robots.txt at all -- every path,
including "/robots.txt" itself, is treated as a location query and 500s
with "location not found" -- so per RFC 9309 no crawling restriction
applies. It's also explicitly built for exactly this kind of plain-HTTP
programmatic access (its whole design is "curl wttr.in/City"), no API key
needed.

Only forecasts 3 days out, so this stays None for matches further away --
same inherent limitation any weather source would have, not specific to
wttr.in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from ..geo import country_utc_offset_hours
from ..http import fetch_json


@dataclass
class WttrWeatherDetail:
    description: str | None
    temp_c: float | None
    humidity_pct: float | None
    wind_speed_kmph: float | None
    precip_mm: float | None
    chance_of_rain_pct: float | None
    wind_gust_kmph: float | None
    cloud_cover_pct: float | None
    feels_like_c: float | None
    # True when venue_country resolved to a real UTC offset (geo.py's own
    # table, already used elsewhere for travel-time calculations) and the
    # hourly slot actually closest to true local kickoff time was picked.
    # False means the offset was unknown and this fell back to the old
    # "local midday" approximation instead.
    kickoff_hour_matched: bool = False


def _closest_hourly_slot(hourly: list[dict[str, Any]], target_hour: float) -> dict[str, Any] | None:
    def slot_hour(h: dict[str, Any]) -> int:
        return int(h.get("time") or "0") // 100

    return min(hourly, key=lambda h: min(abs(slot_hour(h) - target_hour), 24 - abs(slot_hour(h) - target_hour)))


async def _fetch_kickoff_weather(
    city: str, kickoff_utc: str | None, venue_country: str | None
) -> tuple[dict[str, Any] | None, bool]:
    """wttr.in returns each day's hourly breakdown in the location's own
    local time; kickoff_utc is UTC. geo.py already has a real (if
    DST-naive) per-country UTC-offset table, built for travel-time
    calculations -- reused here to convert kickoff to local time and pick
    the hourly slot actually closest to it, rather than always defaulting
    to local midday. Falls back to the midday approximation when
    venue_country isn't in that table (still 3-hour-slot data, just not
    matched to the real kickoff hour)."""
    if not kickoff_utc:
        return None, False
    kickoff_dt = datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00"))
    days_out = (kickoff_dt - datetime.now(tz=timezone.utc)).days
    if days_out < 0 or days_out > 2:
        return None, False

    try:
        data = await fetch_json(f"https://wttr.in/{quote(city)}?format=j1")
    except Exception:  # noqa: BLE001 - mirrors TS's .catch(() => null)
        return None, False

    offset_hours = country_utc_offset_hours(venue_country) if venue_country else None
    local_dt = kickoff_dt + timedelta(hours=offset_hours) if offset_hours is not None else kickoff_dt

    target_date = local_dt.date().isoformat()
    day = next((w for w in data.get("weather", []) if w.get("date") == target_date), None)
    if not day:
        # Local date can differ from the UTC date near midnight -- the UTC
        # date is still the best fallback guess at which day's forecast to use.
        day = next((w for w in data.get("weather", []) if w.get("date") == kickoff_dt.date().isoformat()), None)
    if not day:
        return None, False

    hourly = day.get("hourly") or []
    if not hourly:
        return None, False

    if offset_hours is not None:
        target_hour = local_dt.hour + local_dt.minute / 60
        return _closest_hourly_slot(hourly, target_hour), True

    midday = next((h for h in hourly if h.get("time") == "1200"), None)
    return (midday if midday else hourly[len(hourly) // 2]), False


async def get_wttr_weather_detail(
    city: str, kickoff_utc: str | None, venue_country: str | None = None
) -> WttrWeatherDetail | None:
    """Single fetch, both the existing display string and the structured
    detail fields (humidity/wind/precip -- present in the same j1 payload,
    just not previously surfaced) derive from it."""
    slot, kickoff_hour_matched = await _fetch_kickoff_weather(city, kickoff_utc, venue_country)
    if not slot:
        return None
    desc_list = slot.get("weatherDesc") or []
    return WttrWeatherDetail(
        description=desc_list[0]["value"] if desc_list else None,
        temp_c=(float(slot["tempC"]) if slot.get("tempC") is not None else None),
        humidity_pct=(float(slot["humidity"]) if slot.get("humidity") is not None else None),
        wind_speed_kmph=(float(slot["windspeedKmph"]) if slot.get("windspeedKmph") is not None else None),
        precip_mm=(float(slot["precipMM"]) if slot.get("precipMM") is not None else None),
        chance_of_rain_pct=(float(slot["chanceofrain"]) if slot.get("chanceofrain") is not None else None),
        wind_gust_kmph=(float(slot["WindGustKmph"]) if slot.get("WindGustKmph") is not None else None),
        cloud_cover_pct=(float(slot["cloudcover"]) if slot.get("cloudcover") is not None else None),
        feels_like_c=(float(slot["FeelsLikeC"]) if slot.get("FeelsLikeC") is not None else None),
        kickoff_hour_matched=kickoff_hour_matched,
    )


async def get_wttr_weather(city: str, kickoff_utc: str | None, venue_country: str | None = None) -> str | None:
    detail = await get_wttr_weather_detail(city, kickoff_utc, venue_country)
    if not detail or not detail.description:
        return None
    approximation = "" if detail.kickoff_hour_matched else " (same-day approximation, local midday)"
    return f"{detail.description}, {detail.temp_c}°C{approximation}"
