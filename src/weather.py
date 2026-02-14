"""Fetch NYC weather from the free NWS API (no API key needed)."""

import requests

NWS_HEADERS = {"User-Agent": "DailyNewsletter/1.0 (daily-newsletter)"}
FORECAST_URL = "https://api.weather.gov/gridpoints/OKX/33,35/forecast"
HOURLY_URL = "https://api.weather.gov/gridpoints/OKX/33,35/forecast/hourly"


def get_nyc_weather() -> dict:
    """Return current NYC weather with high/low and forecast summary."""
    try:
        hourly = requests.get(HOURLY_URL, headers=NWS_HEADERS, timeout=10).json()
        current = hourly["properties"]["periods"][0]

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

        return {
            "current_temp": current["temperature"],
            "unit": current["temperatureUnit"],
            "conditions": current["shortForecast"],
            "high": high,
            "low": low,
            "forecast": forecast,
        }
    except Exception as e:
        return {"error": str(e), "current_temp": "N/A", "conditions": "Unavailable", "high": "N/A", "low": "N/A", "forecast": "Weather data unavailable."}
