"""
tests/test_location.py

Unit tests for services/location_extractor.py.
The geopy geocoder is mocked so no real network calls are made.
"""

from unittest.mock import MagicMock, patch

import pytest

import services.location_extractor as loc_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_geopy_location(address="Bengaluru, Karnataka, India", lat=12.9716, lon=77.5946):
    """Return a minimal mock that looks like a geopy Location object."""
    location = MagicMock()
    location.address   = address
    location.latitude  = lat
    location.longitude = lon
    return location


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExtractLocation:
    def test_valid_indian_location_returns_dict(self):
        """A recognisable place name should return a dict with the required keys."""
        mock_location = _make_geopy_location(
            address="Bengaluru, Karnataka, India",
            lat=12.9716,
            lon=77.5946,
        )
        with patch.object(loc_mod.geolocator, "geocode", return_value=mock_location):
            result = loc_mod.extract_location("I am calling from Bengaluru")

        assert result is not None
        assert "latitude"  in result
        assert "longitude" in result
        assert "address"   in result
        assert result["latitude"]  == 12.9716
        assert result["longitude"] == 77.5946

    def test_empty_string_returns_none(self):
        """An empty input string should return None without calling the geocoder."""
        with patch.object(loc_mod.geolocator, "geocode") as mock_geocode:
            result = loc_mod.extract_location("")

        assert result is None
        mock_geocode.assert_not_called()

    def test_geocoder_timeout_returns_none(self):
        """A GeocoderTimedOut exception must be swallowed and return None."""
        from geopy.exc import GeocoderTimedOut

        with patch.object(loc_mod.geolocator, "geocode", side_effect=GeocoderTimedOut()):
            result = loc_mod.extract_location("I am calling from Mumbai")

        assert result is None

    def test_geocoder_unavailable_returns_none(self):
        """A GeocoderUnavailable exception must be swallowed and return None."""
        from geopy.exc import GeocoderUnavailable

        with patch.object(loc_mod.geolocator, "geocode", side_effect=GeocoderUnavailable()):
            result = loc_mod.extract_location("I am calling from Delhi")

        assert result is None
