"""Tests for weather source configuration."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import weather
from src.constants import NWS_LOCATION_LABEL, NWS_POINT_URL, NWS_STATIONS_URL, OPEN_METEO_FORECAST_URL


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_weather_fetch_uses_53rd_street_point():
    """Verify weather fetch resolves URLs from the 53rd Street NWS point."""
    forecast_url = "https://api.weather.gov/gridpoints/OKX/34,44/forecast"
    hourly_url = "https://api.weather.gov/gridpoints/OKX/34,44/forecast/hourly"
    calls = []
    target_date = weather.datetime.now(weather.NYC_TZ).date()
    if weather.datetime.now(weather.NYC_TZ).hour > max(weather.TARGET_HOURS):
        target_date = target_date + weather.timedelta(days=1)
    target_date_str = target_date.isoformat()

    def fake_get(url, **_kwargs):
        calls.append(url)
        if url == OPEN_METEO_FORECAST_URL:
            return _FakeResponse({
                "hourly": {
                    "time": [f"{target_date_str}T09:00"],
                    "temperature_2m_best_match": [70],
                    "temperature_2m_gfs_seamless": [74],
                    "apparent_temperature_best_match": [71],
                    "apparent_temperature_gfs_seamless": [75],
                    "precipitation_probability_best_match": [20],
                    "precipitation_probability_gfs_seamless": [30],
                    "relative_humidity_2m_best_match": [60],
                    "relative_humidity_2m_gfs_seamless": [70],
                    "weather_code_best_match": [2],
                    "weather_code_gfs_seamless": [3],
                    "wind_speed_10m_best_match": [8],
                    "wind_speed_10m_gfs_seamless": [12],
                    "wind_direction_10m_best_match": [180],
                    "wind_direction_10m_gfs_seamless": [180],
                },
                "daily": {
                    "time": [target_date_str],
                    "temperature_2m_max_best_match": [78],
                    "temperature_2m_max_gfs_seamless": [82],
                    "temperature_2m_min_best_match": [60],
                    "temperature_2m_min_gfs_seamless": [64],
                },
            })
        if url == NWS_POINT_URL:
            return _FakeResponse({"properties": {"forecast": forecast_url, "forecastHourly": hourly_url}})
        if url == NWS_STATIONS_URL:
            return _FakeResponse({
                "features": [{
                    "properties": {"stationIdentifier": "KNYC"}
                }]
            })
        if "observations/latest" in url:
            return _FakeResponse({
                "properties": {
                    "temperature": {"value": 12.2, "unitCode": "wmoUnit:degC"},
                    "textDescription": "Partly Cloudy",
                    "windSpeed": {"value": 4.0, "unitCode": "wmoUnit:m.s-1"},
                    "relativeHumidity": {"value": 55.0, "unitCode": "wmoUnit:percent"},
                }
            })
        if url == hourly_url:
            return _FakeResponse({
                "properties": {
                    "periods": [{
                        "startTime": "2026-05-10T06:00:00-04:00",
                        "temperature": 54,
                        "temperatureUnit": "F",
                        "shortForecast": "Areas Of Fog",
                        "windSpeed": "3 mph",
                        "windDirection": "S",
                        "relativeHumidity": {"value": 88},
                        "probabilityOfPrecipitation": {"value": 0},
                    }]
                }
            })
        if url == forecast_url:
            return _FakeResponse({
                "properties": {
                    "periods": [
                        {
                            "isDaytime": True,
                            "temperature": 77,
                            "detailedForecast": "Mostly cloudy, with a high near 77.",
                        },
                        {
                            "isDaytime": False,
                            "temperature": 52,
                            "detailedForecast": "Mostly cloudy.",
                        },
                    ]
                }
            })
        raise AssertionError(f"Unexpected URL: {url}")

    original_get = weather.requests.get
    try:
        weather.requests.get = fake_get
        result = weather.get_nyc_weather()
    finally:
        weather.requests.get = original_get

    assert calls[0] == OPEN_METEO_FORECAST_URL
    assert calls[1] == NWS_POINT_URL
    assert result["location"] == NWS_LOCATION_LABEL == "Manhattan, NYC"
    assert result["source"] == "National Weather Service"
    assert result["source_url"] == forecast_url
    assert result["forecast_source_count"] == 3
    assert result["high"] == 80
    assert result["low"] == 62
    assert result["hourly"][0]["temp"] == 72
    assert result["hourly"][0]["precip_chance"] == "25%"
    # Hero should use observation data (12.2°C = 54°F)
    assert result["current_temp"] == 54
    assert result["conditions"] == "Partly Cloudy"


if __name__ == "__main__":
    test_weather_fetch_uses_53rd_street_point()
    print("All tests passed!")
