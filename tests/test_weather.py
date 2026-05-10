"""Tests for weather source configuration."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import weather
from src.constants import NWS_LOCATION_LABEL, NWS_POINT_URL


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_weather_fetch_uses_53rd_street_point():
    forecast_url = "https://api.weather.gov/gridpoints/OKX/34,44/forecast"
    hourly_url = "https://api.weather.gov/gridpoints/OKX/34,44/forecast/hourly"
    calls = []

    def fake_get(url, **_kwargs):
        calls.append(url)
        if url == NWS_POINT_URL:
            return _FakeResponse({"properties": {"forecast": forecast_url, "forecastHourly": hourly_url}})
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

    assert calls[0] == NWS_POINT_URL
    assert result["location"] == NWS_LOCATION_LABEL == "53rd Street, NYC"
    assert result["source"] == "National Weather Service"
    assert result["source_url"] == forecast_url


if __name__ == "__main__":
    test_weather_fetch_uses_53rd_street_point()
    print("All tests passed!")
