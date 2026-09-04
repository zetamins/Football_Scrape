import asyncio
from datetime import UTC, datetime, timedelta

from football.sites import wttrin
from football.sites.wttrin import (
    WttrWeatherDetail,
    _closest_hourly_slot,
    _fetch_kickoff_weather,
    get_wttr_weather,
    get_wttr_weather_detail,
)

# --- _closest_hourly_slot ------------------------------------------------------------------


def _hourly(*times):
    return [{"time": t} for t in times]


def test_closest_hourly_slot_picks_exact_match():
    hourly = _hourly("0000", "0300", "1200", "1800")
    assert _closest_hourly_slot(hourly, 12.0)["time"] == "1200"


def test_closest_hourly_slot_wraps_around_midnight():
    # 23:00 target should prefer the "0000" slot over "1800" -- only true
    # if the distance calc wraps modulo 24 instead of taking a raw diff.
    hourly = _hourly("1800", "0000")
    assert _closest_hourly_slot(hourly, 23.0)["time"] == "0000"


def test_closest_hourly_slot_treats_missing_time_as_midnight():
    hourly = [{}]
    assert _closest_hourly_slot(hourly, 0.0) == {}


# --- _fetch_kickoff_weather -----------------------------------------------------------------


def _kickoff_in(days: int, hours_from_now: float = 2) -> str:
    # Adding a relative offset (not replacing the hour) keeps kickoff
    # reliably in the future regardless of what time the test happens to
    # run at -- a fixed clock-hour risked landing in the past "today" and
    # tripping the function's own days_out<0 guard depending on wall time.
    dt = datetime.now(tz=UTC) + timedelta(days=days, hours=hours_from_now)
    return dt.isoformat()


def test_fetch_kickoff_weather_none_without_kickoff_utc():
    result = asyncio.run(_fetch_kickoff_weather("London", None, "England"))
    assert result == (None, False)


def test_fetch_kickoff_weather_none_when_too_far_out():
    result = asyncio.run(_fetch_kickoff_weather("London", _kickoff_in(5), "England"))
    assert result == (None, False)


def test_fetch_kickoff_weather_none_when_past():
    result = asyncio.run(_fetch_kickoff_weather("London", _kickoff_in(-1), "England"))
    assert result == (None, False)


def test_fetch_kickoff_weather_none_when_fetch_raises(monkeypatch):
    async def failing(_url):
        raise RuntimeError("boom")

    monkeypatch.setattr(wttrin, "fetch_json", failing)
    result = asyncio.run(_fetch_kickoff_weather("London", _kickoff_in(0), "England"))
    assert result == (None, False)


def _weather_payload(date: str, hourly: list[dict]) -> dict:
    return {"weather": [{"date": date, "hourly": hourly}]}


def test_fetch_kickoff_weather_matches_local_kickoff_hour_when_offset_known(monkeypatch):
    kickoff = _kickoff_in(0)
    kickoff_dt = datetime.fromisoformat(kickoff)
    target_date = kickoff_dt.date().isoformat()
    expected_slot_hour = f"{kickoff_dt.hour:02d}00"

    other_hour = "0000" if expected_slot_hour != "0000" else "1200"

    async def fake_fetch_json(_url):
        return _weather_payload(target_date, _hourly(other_hour, expected_slot_hour))

    monkeypatch.setattr(wttrin, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(wttrin, "country_utc_offset_hours", lambda _country: 0)
    slot, matched = asyncio.run(_fetch_kickoff_weather("London", kickoff, "England"))
    assert matched is True
    assert slot["time"] == expected_slot_hour


def test_fetch_kickoff_weather_falls_back_to_local_midday_without_offset(monkeypatch):
    kickoff = _kickoff_in(0)
    target_date = datetime.fromisoformat(kickoff).date().isoformat()

    async def fake_fetch_json(_url):
        return _weather_payload(target_date, _hourly("0900", "1200", "2100"))

    monkeypatch.setattr(wttrin, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(wttrin, "country_utc_offset_hours", lambda _country: None)
    slot, matched = asyncio.run(_fetch_kickoff_weather("London", kickoff, "Atlantis"))
    assert matched is False
    assert slot["time"] == "1200"


def test_fetch_kickoff_weather_none_without_matching_day(monkeypatch):
    kickoff = _kickoff_in(0)

    async def fake_fetch_json(_url):
        return {"weather": [{"date": "1999-01-01", "hourly": _hourly("1200")}]}

    monkeypatch.setattr(wttrin, "fetch_json", fake_fetch_json)
    result = asyncio.run(_fetch_kickoff_weather("London", kickoff, "England"))
    assert result == (None, False)


def test_fetch_kickoff_weather_none_without_hourly_data(monkeypatch):
    kickoff = _kickoff_in(0)
    target_date = datetime.fromisoformat(kickoff).date().isoformat()

    async def fake_fetch_json(_url):
        return _weather_payload(target_date, [])

    monkeypatch.setattr(wttrin, "fetch_json", fake_fetch_json)
    result = asyncio.run(_fetch_kickoff_weather("London", kickoff, "England"))
    assert result == (None, False)


# --- get_wttr_weather_detail / get_wttr_weather ------------------------------------------------


def _slot(**overrides):
    base = {
        "weatherDesc": [{"value": "Sunny"}],
        "tempC": "20",
        "humidity": "50",
        "windspeedKmph": "10",
        "precipMM": "0.0",
        "chanceofrain": "5",
        "WindGustKmph": "15",
        "cloudcover": "25",
        "FeelsLikeC": "19",
    }
    base.update(overrides)
    return base


def test_get_wttr_weather_detail_maps_all_fields(monkeypatch):
    async def fake_fetch(_city, _kickoff, _country):
        return _slot(), True

    monkeypatch.setattr(wttrin, "_fetch_kickoff_weather", fake_fetch)
    detail = asyncio.run(get_wttr_weather_detail("London", "2026-01-01T15:00:00", "England"))
    assert detail == WttrWeatherDetail(
        description="Sunny",
        temp_c=20.0,
        humidity_pct=50.0,
        wind_speed_kmph=10.0,
        precip_mm=0.0,
        chance_of_rain_pct=5.0,
        wind_gust_kmph=15.0,
        cloud_cover_pct=25.0,
        feels_like_c=19.0,
        kickoff_hour_matched=True,
    )


def test_get_wttr_weather_detail_none_without_slot(monkeypatch):
    async def fake_fetch(_city, _kickoff, _country):
        return None, False

    monkeypatch.setattr(wttrin, "_fetch_kickoff_weather", fake_fetch)
    assert asyncio.run(get_wttr_weather_detail("London", None, None)) is None


def test_get_wttr_weather_detail_handles_missing_optional_fields(monkeypatch):
    async def fake_fetch(_city, _kickoff, _country):
        return {"weatherDesc": []}, False

    monkeypatch.setattr(wttrin, "_fetch_kickoff_weather", fake_fetch)
    detail = asyncio.run(get_wttr_weather_detail("London", "2026-01-01T15:00:00", "England"))
    assert detail.description is None
    assert detail.temp_c is None


def test_get_wttr_weather_formats_string_with_kickoff_matched(monkeypatch):
    async def fake_detail(_city, _kickoff, _country):
        return WttrWeatherDetail(
            description="Sunny",
            temp_c=20.0,
            humidity_pct=None,
            wind_speed_kmph=None,
            precip_mm=None,
            chance_of_rain_pct=None,
            wind_gust_kmph=None,
            cloud_cover_pct=None,
            feels_like_c=None,
            kickoff_hour_matched=True,
        )

    monkeypatch.setattr(wttrin, "get_wttr_weather_detail", fake_detail)
    result = asyncio.run(get_wttr_weather("London", "2026-01-01T15:00:00", "England"))
    assert result == "Sunny, 20.0°C"


def test_get_wttr_weather_appends_approximation_note_when_not_matched(monkeypatch):
    async def fake_detail(_city, _kickoff, _country):
        return WttrWeatherDetail(
            description="Cloudy",
            temp_c=15.0,
            humidity_pct=None,
            wind_speed_kmph=None,
            precip_mm=None,
            chance_of_rain_pct=None,
            wind_gust_kmph=None,
            cloud_cover_pct=None,
            feels_like_c=None,
            kickoff_hour_matched=False,
        )

    monkeypatch.setattr(wttrin, "get_wttr_weather_detail", fake_detail)
    result = asyncio.run(get_wttr_weather("London", "2026-01-01T15:00:00", "England"))
    assert result == "Cloudy, 15.0°C (same-day approximation, local midday)"


def test_get_wttr_weather_none_without_detail(monkeypatch):
    async def fake_detail(_city, _kickoff, _country):
        return None

    monkeypatch.setattr(wttrin, "get_wttr_weather_detail", fake_detail)
    assert asyncio.run(get_wttr_weather("London", None, None)) is None


def test_get_wttr_weather_none_without_description(monkeypatch):
    async def fake_detail(_city, _kickoff, _country):
        return WttrWeatherDetail(
            description=None,
            temp_c=None,
            humidity_pct=None,
            wind_speed_kmph=None,
            precip_mm=None,
            chance_of_rain_pct=None,
            wind_gust_kmph=None,
            cloud_cover_pct=None,
            feels_like_c=None,
        )

    monkeypatch.setattr(wttrin, "get_wttr_weather_detail", fake_detail)
    assert asyncio.run(get_wttr_weather("London", None, None)) is None
