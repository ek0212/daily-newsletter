"""Fetch NYC weather from the free NWS API (no API key needed)."""

import logging
import requests

logger = logging.getLogger(__name__)

NWS_HEADERS = {"User-Agent": "DailyNewsletter/1.0 (daily-newsletter)"}
FORECAST_URL = "https://api.weather.gov/gridpoints/OKX/33,35/forecast"
HOURLY_URL = "https://api.weather.gov/gridpoints/OKX/33,35/forecast/hourly"


def get_nyc_weather() -> dict:
    """Return current NYC weather with high/low and forecast summary."""
    try:
        logger.debug("Fetching hourly forecast from %s", HOURLY_URL)
        hourly = requests.get(HOURLY_URL, headers=NWS_HEADERS, timeout=10).json()
        current = hourly["properties"]["periods"][0]

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

        logger.info("NYC weather fetched: %s°%s, %s, H:%s/L:%s",
                    current["temperature"], current["temperatureUnit"],
                    current["shortForecast"], high, low)
        return {
            "current_temp": current["temperature"],
            "unit": current["temperatureUnit"],
            "conditions": current["shortForecast"],
            "high": high,
            "low": low,
            "forecast": forecast,
        }
    except Exception as e:
        logger.error("Weather API failed: %s", e, exc_info=True)
        return {"error": str(e), "current_temp": "N/A", "conditions": "Unavailable", "high": "N/A", "low": "N/A", "forecast": "Weather data unavailable."}
