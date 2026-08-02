"""Fetch NYC weather from the free NWS API (no API key needed)."""

import logging
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from src.constants import (
    HEAT_INDEX_HUMIDITY_THRESHOLD,
    HEAT_INDEX_TEMP_THRESHOLD,
    HTTP_TIMEOUT_DEFAULT,
    NWS_FORECAST_URL,
    NWS_HOURLY_URL,
    NWS_LOCATION_LABEL,
    NWS_POINT_URL,
    NWS_STATIONS_URL,
    NWS_POINT_LATITUDE,
    NWS_POINT_LONGITUDE,
    OPEN_METEO_FORECAST_URL,
    OPEN_METEO_MODELS,
    TARGET_HOURS,
    USER_AGENT,
    WIND_CHILL_TEMP_THRESHOLD,
    WIND_CHILL_WIND_THRESHOLD,
)

logger = logging.getLogger(__name__)

NWS_HEADERS = {"User-Agent": f"{USER_AGENT} (daily-newsletter)"}
FORECAST_URL = NWS_FORECAST_URL
HOURLY_URL = NWS_HOURLY_URL
OPEN_METEO_HOURLY_FIELDS = [
    "temperature_2m",
    "apparent_temperature",
    "precipitation_probability",
    "relative_humidity_2m",
    "weather_code",
    "wind_speed_10m",
    "wind_direction_10m",
]
OPEN_METEO_DAILY_FIELDS = ["temperature_2m_max", "temperature_2m_min"]

# NYC local time, including daylight saving time.
NYC_TZ = ZoneInfo("America/New_York")


def _fetch_json(url: str) -> dict:
    response = requests.get(url, headers=NWS_HEADERS, timeout=HTTP_TIMEOUT_DEFAULT)
    response.raise_for_status()
    return response.json()


def _fetch_open_meteo_json() -> dict:
    response = requests.get(
        OPEN_METEO_FORECAST_URL,
        params={
            "latitude": NWS_POINT_LATITUDE,
            "longitude": NWS_POINT_LONGITUDE,
            "timezone": "America/New_York",
            "forecast_days": 2,
            "hourly": ",".join(OPEN_METEO_HOURLY_FIELDS),
            "daily": ",".join(OPEN_METEO_DAILY_FIELDS),
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "models": ",".join(OPEN_METEO_MODELS),
        },
        headers=NWS_HEADERS,
        timeout=HTTP_TIMEOUT_DEFAULT,
    )
    response.raise_for_status()
    return response.json()


def _forecast_urls() -> tuple[str, str]:
    """Resolve NWS forecast URLs from the configured 53rd Street point."""
    try:
        point = _fetch_json(NWS_POINT_URL)
        properties = point["properties"]
        return properties["forecast"], properties["forecastHourly"]
    except Exception as e:
        logger.warning("NWS point lookup failed for %s: %s; using fallback grid URLs", NWS_LOCATION_LABEL, e)
        return FORECAST_URL, HOURLY_URL


def _fetch_current_observation() -> dict | None:
    """Fetch the latest observation from the nearest NWS weather station.

    Returns actual measured conditions (temperature, sky, wind, humidity)
    rather than forecast data. This matches what apps like Apple Weather show.
    """
    try:
        stations = _fetch_json(NWS_STATIONS_URL)
        features = stations.get("features", [])
        if not features:
            return None
        station_id = features[0]["properties"]["stationIdentifier"]
        obs_url = f"https://api.weather.gov/stations/{station_id}/observations/latest"
        obs = _fetch_json(obs_url)
        props = obs["properties"]

        temp_c = props.get("temperature", {}).get("value")
        if temp_c is None:
            return None
        temp_f = round(temp_c * 9 / 5 + 32)

        conditions = props.get("textDescription", "")

        wind_ms = props.get("windSpeed", {}).get("value")
        wind_mph = round(wind_ms * 2.237) if wind_ms is not None else 0

        humidity = props.get("relativeHumidity", {}).get("value")
        if humidity is not None:
            humidity = round(humidity)

        logger.info("NWS observation from %s: %d°F, %s", station_id, temp_f, conditions)
        return {
            "temp": temp_f,
            "conditions": conditions,
            "wind_mph": wind_mph,
            "humidity": humidity,
        }
    except Exception as e:
        logger.warning("NWS observation fetch failed: %s", e)
        return None


def _calc_feels_like(temp_f: int, wind_speed_str: str, humidity) -> int:
    """Calculate feels-like temperature using wind chill or heat index.

    Wind chill: valid for temp <= 50°F and wind >= 3 mph (NWS formula).
    Heat index: valid for temp >= 80°F and humidity >= 40%.
    Otherwise returns the actual temperature.
    """
    import re
    # Extract numeric wind speed (e.g. "15 mph" -> 15, "10 to 20 mph" -> 15)
    wind_nums = re.findall(r'\d+', wind_speed_str)
    if wind_nums:
        wind_mph = sum(int(n) for n in wind_nums) / len(wind_nums)
    else:
        wind_mph = 0

    t = float(temp_f)
    if t <= WIND_CHILL_TEMP_THRESHOLD and wind_mph >= WIND_CHILL_WIND_THRESHOLD:
        # NWS wind chill formula
        wc = 35.74 + 0.6215 * t - 35.75 * (wind_mph ** 0.16) + 0.4275 * t * (wind_mph ** 0.16)
        return round(wc)
    elif t >= HEAT_INDEX_TEMP_THRESHOLD and humidity is not None and humidity >= HEAT_INDEX_HUMIDITY_THRESHOLD:
        # Simplified heat index (Rothfusz regression)
        h = float(humidity)
        hi = (-42.379 + 2.04901523 * t + 10.14333127 * h
              - 0.22475541 * t * h - 0.00683783 * t * t
              - 0.05481717 * h * h + 0.00122874 * t * t * h
              + 0.00085282 * t * h * h - 0.00000199 * t * t * h * h)
        return round(hi)
    return round(t)


def _mean(values: list[float | int | None]) -> float | None:
    """Average numeric values while ignoring missing model fields."""
    clean = [float(v) for v in values if isinstance(v, int | float)]
    return sum(clean) / len(clean) if clean else None


def _mode_int(values: list[float | int | None]) -> int | None:
    """Return most common integer-like model value."""
    clean = [round(float(v)) for v in values if isinstance(v, int | float)]
    if not clean:
        return None
    return Counter(clean).most_common(1)[0][0]


def _wind_direction_label(degrees: float | int | None) -> str:
    """Convert wind degrees to a compact compass label."""
    if not isinstance(degrees, int | float):
        return ""
    labels = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return labels[round(float(degrees) / 45) % 8]


def _weather_code_label(code: int | None) -> str:
    """Map WMO weather codes to compact email labels."""
    if code in {0}:
        return "Clear"
    if code in {1, 2}:
        return "Partly Cloudy"
    if code in {3}:
        return "Cloudy"
    if code in {45, 48}:
        return "Fog"
    if code in {51, 53, 55, 56, 57}:
        return "Drizzle"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "Rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "Snow"
    if code in {95, 96, 99}:
        return "Thunderstorms"
    return "Mixed"


def _model_values(payload: dict, section: str, field: str, index: int) -> list[float | int | None]:
    """Collect one field across configured Open-Meteo models."""
    data = payload.get(section, {})
    values = []
    for model in OPEN_METEO_MODELS:
        key = f"{field}_{model}"
        series = data.get(key)
        if isinstance(series, list) and index < len(series):
            values.append(series[index])
    return values


def _consensus_source_count(payload: dict, section: str, field: str, index: int) -> int:
    """Return count of models that supplied one field."""
    return len([v for v in _model_values(payload, section, field, index) if isinstance(v, int | float)])


def _fetch_consensus_forecast() -> dict | None:
    """Fetch averaged forecast fields across public weather models."""
    try:
        return _fetch_open_meteo_json()
    except Exception as e:
        logger.warning("Open-Meteo model consensus failed: %s", e)
        return None


def _parse_consensus_hourly(payload: dict) -> list[dict]:
    """Build target-hour rows from averaged Open-Meteo model data."""
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return []

    now_local = datetime.now(NYC_TZ)
    target_date = now_local.date()
    if now_local.hour > max(TARGET_HOURS):
        target_date = target_date + timedelta(days=1)

    rows = []
    matched = set()
    for idx, raw_time in enumerate(times):
        try:
            start = datetime.fromisoformat(raw_time).replace(tzinfo=NYC_TZ)
        except ValueError:
            continue
        if start.date() != target_date or start.hour not in TARGET_HOURS or start.hour in matched:
            continue
        matched.add(start.hour)

        temp = _mean(_model_values(payload, "hourly", "temperature_2m", idx))
        feels = _mean(_model_values(payload, "hourly", "apparent_temperature", idx))
        precip = _mean(_model_values(payload, "hourly", "precipitation_probability", idx))
        humidity = _mean(_model_values(payload, "hourly", "relative_humidity_2m", idx))
        wind = _mean(_model_values(payload, "hourly", "wind_speed_10m", idx))
        wind_dir = _mean(_model_values(payload, "hourly", "wind_direction_10m", idx))
        code = _mode_int(_model_values(payload, "hourly", "weather_code", idx))

        if temp is None:
            continue

        rows.append({
            "label": start.strftime("%-I%p").lower(),
            "hour": start.hour,
            "temp": round(temp),
            "feels_like": round(feels if feels is not None else temp),
            "conditions": _weather_code_label(code),
            "wind": f"{round(wind) if wind is not None else 0} mph {_wind_direction_label(wind_dir)}".strip(),
            "humidity": f"{round(humidity)}%" if humidity is not None else "N/A",
            "precip_chance": f"{round(precip)}%" if precip is not None else "N/A",
            "source_count": _consensus_source_count(payload, "hourly", "temperature_2m", idx),
        })

    rows.sort(key=lambda x: x["hour"])
    return rows


def _consensus_daily_range(payload: dict) -> tuple[int | None, int | None, int]:
    """Return high, low, and model count from Open-Meteo daily consensus."""
    daily = payload.get("daily", {})
    if not daily.get("time"):
        return None, None, 0
    high = _mean(_model_values(payload, "daily", "temperature_2m_max", 0))
    low = _mean(_model_values(payload, "daily", "temperature_2m_min", 0))
    count = _consensus_source_count(payload, "daily", "temperature_2m_max", 0)
    return (
        round(high) if high is not None else None,
        round(low) if low is not None else None,
        count,
    )


def _parse_hourly_periods(periods: list) -> list[dict]:
    """Extract weather data for TARGET_HOURS in NYC local time from NWS hourly periods."""
    now_local = datetime.now(NYC_TZ)
    target_date = now_local.date()

    # If all target hours have passed today, use tomorrow
    if now_local.hour > max(TARGET_HOURS):
        target_date = target_date + timedelta(days=1)

    hourly_data = []
    matched = set()

    for p in periods:
        start = datetime.fromisoformat(p["startTime"]).astimezone(NYC_TZ)
        if start.date() != target_date or start.hour not in TARGET_HOURS or start.hour in matched:
            continue
        matched.add(start.hour)

        wind_speed_str = p.get("windSpeed", "")
        wind_dir = p.get("windDirection", "")
        humidity = p.get("relativeHumidity", {}).get("value")
        precip_chance = p.get("probabilityOfPrecipitation", {}).get("value") or 0
        temp = p["temperature"]

        # Calculate feels-like (wind chill for cold, heat index for hot)
        feels_like = _calc_feels_like(temp, wind_speed_str, humidity)

        hourly_data.append({
            "label": start.strftime("%-I%p").lower(),  # e.g. "7am"
            "hour": start.hour,
            "temp": temp,
            "feels_like": feels_like,
            "conditions": p["shortForecast"],
            "wind": f"{wind_speed_str} {wind_dir}".strip(),
            "humidity": f"{humidity}%" if humidity is not None else "N/A",
            "precip_chance": f"{precip_chance}%",
        })

    hourly_data.sort(key=lambda x: x["hour"])
    return hourly_data


def get_nyc_weather() -> dict:
    """Return current NYC weather with high/low, forecast, and hourly breakdown."""
    try:
        consensus = _fetch_consensus_forecast()
        forecast_url, hourly_url = _forecast_urls()

        logger.debug("Fetching hourly forecast for %s from %s", NWS_LOCATION_LABEL, hourly_url)
        hourly = _fetch_json(hourly_url)
        hourly_periods = hourly["properties"]["periods"]
        current = hourly_periods[0]

        logger.debug("Fetching daily forecast for %s from %s", NWS_LOCATION_LABEL, forecast_url)
        daily = _fetch_json(forecast_url)
        periods = daily["properties"]["periods"]

        today = periods[0]
        tonight = periods[1]

        if today["isDaytime"]:
            high, low = today["temperature"], tonight["temperature"]
            forecast = today["detailedForecast"]
        else:
            high = periods[1]["temperature"]
            low = today["temperature"]
            forecast = today["detailedForecast"]

        hourly_breakdown = _parse_hourly_periods(hourly_periods)
        consensus_model_count = 0
        if consensus:
            consensus_hourly = _parse_consensus_hourly(consensus)
            consensus_high, consensus_low, consensus_model_count = _consensus_daily_range(consensus)
            if consensus_hourly:
                hourly_breakdown = consensus_hourly
            if consensus_high is not None:
                high = consensus_high
            if consensus_low is not None:
                low = consensus_low

        # Use real-time observation for the hero (matches Apple Weather better)
        obs = _fetch_current_observation()
        if obs:
            current_temp = obs["temp"]
            conditions = obs["conditions"]
            current_feels_like = _calc_feels_like(
                current_temp, f"{obs['wind_mph']} mph", obs["humidity"],
            )
        else:
            # Fallback to first forecast period if observation unavailable
            current_temp = current["temperature"]
            conditions = current["shortForecast"]
            current_wind = current.get("windSpeed", "")
            current_humidity = current.get("relativeHumidity", {}).get("value")
            current_feels_like = _calc_feels_like(current_temp, current_wind, current_humidity)

        logger.info("%s weather fetched: %s°F (feels %s°), %s, H:%s/L:%s, %d hourly slots",
                    NWS_LOCATION_LABEL,
                    current_temp,
                    current_feels_like,
                    conditions, high, low, len(hourly_breakdown))
        return {
            "location": NWS_LOCATION_LABEL,
            "source": "National Weather Service",
            "source_url": forecast_url,
            "current_temp": current_temp,
            "unit": "F",
            "conditions": conditions,
            "high": high,
            "low": low,
            "feels_like": current_feels_like,
            "forecast": forecast,
            "hourly": hourly_breakdown,
            "forecast_source": "Open-Meteo model consensus + National Weather Service",
            "forecast_source_count": consensus_model_count + 1 if consensus_model_count else 1,
            "forecast_source_url": OPEN_METEO_FORECAST_URL if consensus_model_count else forecast_url,
        }
    except Exception as e:
        logger.error("Weather API failed: %s", e, exc_info=True)
        return {"error": str(e), "location": NWS_LOCATION_LABEL, "current_temp": "N/A", "conditions": "Unavailable", "high": "N/A", "low": "N/A", "forecast": "Weather data unavailable.", "hourly": []}
