"""
tests/test_weather.py

Unit tests for services/weather_service.py.
requests.get is mocked so no real network calls are made.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

import services.weather_service as wx_mod


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

# Minimal Open-Meteo response with a known UTC time slot
def _make_open_meteo_response(temperature=28.5, weathercode=1, humidity=65):
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")
    return {
        "current_weather": {
            "temperature": temperature,
            "weathercode":  weathercode,
            "windspeed":    10.0,
        },
        "hourly": {
            "time":                 [now_str],
            "relativehumidity_2m":  [humidity],
        },
    }


def _mock_response(payload: dict, status_code: int = 200):
    """Build a mock requests.Response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status.return_value = None
    return mock_resp


SAMPLE_LOCATION = {
    "query":     "Bengaluru",
    "address":   "Bengaluru, Karnataka, India",
    "latitude":  12.9716,
    "longitude": 77.5946,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetWeather:
    def test_valid_response_returns_dict_with_required_keys(self):
        """A well-formed Open-Meteo response should produce a dict with all four keys."""
        payload = _make_open_meteo_response(temperature=29.0, weathercode=0, humidity=70)
        with patch("requests.get", return_value=_mock_response(payload)):
            result = wx_mod.get_weather(SAMPLE_LOCATION)

        assert result is not None
        for key in ("temperature", "description", "humidity", "location"):
            assert key in result, f"Expected key '{key}' missing from result"
        assert result["temperature"] == 29.0
        assert result["humidity"]    == 70
        assert result["description"] == "Clear sky"   # WMO code 0

    def test_request_timeout_returns_none(self):
        """A requests.Timeout should be caught and return None."""
        with patch("requests.get", side_effect=requests.exceptions.Timeout()):
            result = wx_mod.get_weather(SAMPLE_LOCATION)

        assert result is None

    def test_http_error_returns_none(self):
        """An HTTP error (e.g. 500) should be caught and return None."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        with patch("requests.get", return_value=mock_resp):
            result = wx_mod.get_weather(SAMPLE_LOCATION)

        assert result is None

    def test_missing_latitude_returns_none(self):
        """A location dict without a 'latitude' key should return None immediately."""
        bad_location = {
            "query":     "Unknown",
            "address":   "Unknown Place",
            # 'latitude' deliberately omitted
            "longitude": 77.5946,
        }
        with patch("requests.get") as mock_get:
            result = wx_mod.get_weather(bad_location)

        assert result is None
        mock_get.assert_not_called()
