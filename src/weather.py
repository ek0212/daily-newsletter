"""Fetch NYC weather from the free NWS API (no API key needed)."""

import logging
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
    TARGET_HOURS,
    USER_AGENT,
    WIND_CHILL_TEMP_THRESHOLD,
    WIND_CHILL_WIND_THRESHOLD,
)

logger = logging.getLogger(__name__)

NWS_HEADERS = {"User-Agent": f"{USER_AGENT} (daily-newsletter)"}
FORECAST_URL = NWS_FORECAST_URL
HOURLY_URL = NWS_HOURLY_URL

# NYC local time, including daylight saving time.
NYC_TZ = ZoneInfo("America/New_York")


def _fetch_json(url: str) -> dict:
    response = requests.get(url, headers=NWS_HEADERS, timeout=HTTP_TIMEOUT_DEFAULT)
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

        # Compute current feels-like temperature
        current_wind = current.get("windSpeed", "")
        current_humidity = current.get("relativeHumidity", {}).get("value")
        current_feels_like = _calc_feels_like(current["temperature"], current_wind, current_humidity)

        logger.info("%s weather fetched: %s°%s (feels %s°), %s, H:%s/L:%s, %d hourly slots",
                    NWS_LOCATION_LABEL,
                    current["temperature"], current["temperatureUnit"],
                    current_feels_like,
                    current["shortForecast"], high, low, len(hourly_breakdown))
        return {
            "location": NWS_LOCATION_LABEL,
            "source": "National Weather Service",
            "source_url": forecast_url,
            "current_temp": current["temperature"],
            "unit": current["temperatureUnit"],
            "conditions": current["shortForecast"],
            "high": high,
            "low": low,
            "feels_like": current_feels_like,
            "forecast": forecast,
            "hourly": hourly_breakdown,
        }
    except Exception as e:
        logger.error("Weather API failed: %s", e, exc_info=True)
        return {"error": str(e), "location": NWS_LOCATION_LABEL, "current_temp": "N/A", "conditions": "Unavailable", "high": "N/A", "low": "N/A", "forecast": "Weather data unavailable.", "hourly": []}
