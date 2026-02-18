"""Fetch NYC weather from the free NWS API (no API key needed)."""

import logging
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

NWS_HEADERS = {"User-Agent": "DailyNewsletter/1.0 (daily-newsletter)"}
FORECAST_URL = "https://api.weather.gov/gridpoints/OKX/33,35/forecast"
HOURLY_URL = "https://api.weather.gov/gridpoints/OKX/33,35/forecast/hourly"

# EST timezone (UTC-5)
EST = timezone(timedelta(hours=-5))

# Hours (EST) to include in the hourly breakdown
TARGET_HOURS = [7, 9, 15, 17, 19]


def _parse_hourly_periods(periods: list) -> list[dict]:
    """Extract weather data for TARGET_HOURS (EST) from NWS hourly periods."""
    now_est = datetime.now(EST)
    target_date = now_est.date()

    # If all target hours have passed today, use tomorrow
    if now_est.hour > max(TARGET_HOURS):
        target_date = target_date + timedelta(days=1)

    hourly_data = []
    matched = set()

    for p in periods:
        start = datetime.fromisoformat(p["startTime"]).astimezone(EST)
        if start.date() != target_date or start.hour not in TARGET_HOURS or start.hour in matched:
            continue
        matched.add(start.hour)

        wind_speed = p.get("windSpeed", "")
        wind_dir = p.get("windDirection", "")
        humidity = p.get("relativeHumidity", {}).get("value")
        precip_chance = p.get("probabilityOfPrecipitation", {}).get("value") or 0

        hourly_data.append({
            "label": start.strftime("%-I%p").lower(),  # e.g. "7am"
            "hour": start.hour,
            "temp": p["temperature"],
            "conditions": p["shortForecast"],
            "wind": f"{wind_speed} {wind_dir}".strip(),
            "humidity": f"{humidity}%" if humidity is not None else "N/A",
            "precip_chance": f"{precip_chance}%",
        })

    hourly_data.sort(key=lambda x: x["hour"])
    return hourly_data


def get_nyc_weather() -> dict:
    """Return current NYC weather with high/low, forecast, and hourly breakdown."""
    try:
        logger.debug("Fetching hourly forecast from %s", HOURLY_URL)
        hourly = requests.get(HOURLY_URL, headers=NWS_HEADERS, timeout=10).json()
        hourly_periods = hourly["properties"]["periods"]
        current = hourly_periods[0]

        logger.debug("Fetching daily forecast from %s", FORECAST_URL)
        daily = requests.get(FORECAST_URL, headers=NWS_HEADERS, timeout=10).json()
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
        logger.info("NYC weather fetched: %s°%s, %s, H:%s/L:%s, %d hourly slots",
                    current["temperature"], current["temperatureUnit"],
                    current["shortForecast"], high, low, len(hourly_breakdown))
        return {
            "current_temp": current["temperature"],
            "unit": current["temperatureUnit"],
            "conditions": current["shortForecast"],
            "high": high,
            "low": low,
            "forecast": forecast,
            "hourly": hourly_breakdown,
        }
    except Exception as e:
        logger.error("Weather API failed: %s", e, exc_info=True)
        return {"error": str(e), "current_temp": "N/A", "conditions": "Unavailable", "high": "N/A", "low": "N/A", "forecast": "Weather data unavailable.", "hourly": []}
