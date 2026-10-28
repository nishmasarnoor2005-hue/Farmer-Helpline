"""
Tests for FR-12: price statistics from historical sample data.
"""

import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.forecast_service import get_price_forecast, DATASET_STATUS


class TestDatasetStatus:
    def test_dataset_status_is_non_empty_string(self):
        """DATASET_STATUS must be a non-empty string."""
        assert isinstance(DATASET_STATUS, str)
        assert len(DATASET_STATUS) > 0


class TestGetPriceForecast:

    def test_known_crop_returns_available_true(self):
        """A crop with ≥3 rows in the CSV must return available=True."""
        result = get_price_forecast("tomato")
        assert isinstance(result, dict)
        assert result["available"] is True

    def test_known_crop_has_required_keys(self):
        """Result for a known crop must contain all specified keys."""
        result = get_price_forecast("paddy")
        assert result["available"] is True
        required_keys = [
            "available", "crop", "market", "mean_price", "min_price",
            "max_price", "price_unit", "data_points", "date_range_start",
            "date_range_end", "disclaimer", "method", "is_live",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_known_crop_price_unit(self):
        """price_unit must be 'INR per quintal'."""
        result = get_price_forecast("ragi")
        assert result["available"] is True
        assert result["price_unit"] == "INR per quintal"

    def test_known_crop_mean_between_min_and_max(self):
        """mean_price must be between min_price and max_price."""
        result = get_price_forecast("maize")
        assert result["available"] is True
        assert result["min_price"] <= result["mean_price"] <= result["max_price"]

    def test_known_crop_data_points_ge_3(self):
        """data_points must be at least 3 for an available result."""
        result = get_price_forecast("groundnut")
        assert result["available"] is True
        assert result["data_points"] >= 3

    def test_unknown_crop_returns_available_false(self):
        """An unknown crop must return available=False."""
        result = get_price_forecast("unknowncrop_xyz_999")
        assert isinstance(result, dict)
        assert result["available"] is False
        assert "reason" in result

    def test_disclaimer_present_when_available(self):
        """disclaimer must be present and non-empty when available=True."""
        result = get_price_forecast("coffee")
        assert result["available"] is True
        assert "disclaimer" in result
        assert len(result["disclaimer"]) > 0

    def test_is_live_always_false_known_crop(self):
        """is_live must be False for a known crop."""
        result = get_price_forecast("paddy")
        assert result["available"] is True
        assert result["is_live"] is False

    def test_is_live_not_present_or_false_unknown_crop(self):
        """is_live must not be True for an unknown crop (key absent is acceptable)."""
        result = get_price_forecast("unknowncrop_xyz_999")
        # Either key is absent or it is False — it must never be True
        assert result.get("is_live", False) is False

    def test_method_is_historical_statistics(self):
        """method must be 'historical_statistics' when available=True."""
        result = get_price_forecast("sugarcane")
        assert result["available"] is True
        assert result["method"] == "historical_statistics"

    def test_market_filter_reduces_data_points(self):
        """Filtering by a valid market returns fewer data_points than no filter."""
        all_markets = get_price_forecast("paddy")
        specific_market = get_price_forecast("paddy", market="Mysore")
        assert all_markets["available"] is True
        if specific_market["available"] is True:
            assert specific_market["data_points"] <= all_markets["data_points"]

    def test_market_filter_no_match_returns_unavailable(self):
        """Filtering by a market with no data returns available=False."""
        result = get_price_forecast("coffee", market="NonExistentMarketXYZ")
        assert result["available"] is False
