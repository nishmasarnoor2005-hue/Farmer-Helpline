"""
Tests for M5: market price service and government scheme catalogue.
"""

import json
import pytest
import sys
import os
from unittest.mock import MagicMock, patch

import requests as _requests_module

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.market_service import (
    load_market_data,
    get_market_price,
    search_market_prices,
    fetch_live_prices,
)
from services.scheme_service import load_schemes, search_schemes, format_scheme_response


# =========================================================
# HELPERS
# =========================================================

def _make_agmarknet_response(commodity: str = "Tomato", state: str = "Karnataka") -> dict:
    """Return a minimal AGMARKNET-style JSON payload."""
    return {
        "records": [
            {
                "Commodity": commodity,
                "Market": "Kolar",
                "District": "Kolar",
                "State": state,
                "Min Price": "800",
                "Max Price": "1200",
                "Modal Price": "1000",
                "unit": "Quintal",
                "Arrival Date": "2024-01-15",
            }
        ]
    }


# =========================================================
# MARKET SERVICE TESTS
# =========================================================

class TestMarketService:

    def test_csv_loads_non_empty_list(self):
        """CSV should load and return a list with at least one record."""
        data = load_market_data()
        assert isinstance(data, list)
        assert len(data) > 0, "market_prices_sample.csv must contain at least one data row"

    def test_get_market_price_paddy_has_required_fields(self):
        """get_market_price('paddy') must return a dict with data_date and source_url."""
        result = get_market_price("paddy")
        assert isinstance(result, dict), "Expected a dict"
        assert result.get("available") is not False, f"Expected data but got: {result}"
        assert "data_date" in result, "Result must contain 'data_date'"
        assert "source_url" in result, "Result must contain 'source_url'"
        assert result["data_date"] is not None, "data_date must not be None"
        assert result["source_url"] is not None, "source_url must not be None"

    def test_get_market_price_unknown_crop_returns_unavailable(self):
        """get_market_price for an unknown crop returns {available: False, reason: ...}."""
        result = get_market_price("unknown_crop_xyz")
        assert isinstance(result, dict), "Expected a dict"
        assert result.get("available") is False, "Expected available=False for unknown crop"
        assert "reason" in result, "Expected a 'reason' key in the response"

    def test_get_market_price_with_district(self):
        """Passing a district filters results to that district."""
        result = get_market_price("paddy", district="Mysore")
        # Either found in that district or falls back
        assert isinstance(result, dict)
        if result.get("available") is not False:
            assert "data_date" in result
            assert "source_url" in result

    def test_search_market_prices_returns_list(self):
        """search_market_prices returns a list."""
        results = search_market_prices("paddy")
        assert isinstance(results, list)

    def test_search_market_prices_known_crop(self):
        """search_market_prices('paddy') returns at least one result."""
        results = search_market_prices("paddy")
        assert len(results) > 0, "Expected at least one result for 'paddy'"

    def test_search_market_prices_each_has_date_and_url(self):
        """All results from search_market_prices must have data_date and source_url."""
        results = search_market_prices("ragi")
        for r in results:
            assert "data_date" in r, f"Missing data_date in result: {r}"
            assert "source_url" in r, f"Missing source_url in result: {r}"

    def test_search_market_prices_unknown_returns_empty(self):
        """search_market_prices for a non-existent crop returns empty list."""
        results = search_market_prices("unknown_crop_xyz_99")
        assert results == []

    def test_get_market_price_is_live_false(self):
        """is_live must be False — this is historical data, not live prices."""
        # Patch fetch_live_prices to always return [] so CSV path is exercised
        with patch("services.market_service.fetch_live_prices", return_value=[]):
            result = get_market_price("tomato")
        if result.get("available") is not False:
            assert result.get("is_live") is False, "is_live must be False for sample data"


# =========================================================
# LIVE API TESTS (fetch_live_prices)
# =========================================================

class TestFetchLivePrices:

    def test_returns_is_live_true_on_200(self):
        """fetch_live_prices returns list with is_live=True when API succeeds."""
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = _make_agmarknet_response("Tomato", "Karnataka")

        with patch("services.market_service.requests.get", return_value=fake_response):
            results = fetch_live_prices("Tomato", "Karnataka")

        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0]["is_live"] is True
        assert results[0]["crop"] == "Tomato"
        assert results[0]["market"] == "Kolar"
        assert results[0]["modal_price"] == "1000"

    def test_returns_empty_list_on_timeout(self):
        """fetch_live_prices returns [] when requests.get raises Timeout."""
        with patch(
            "services.market_service.requests.get",
            side_effect=_requests_module.Timeout("timed out"),
        ):
            results = fetch_live_prices("Tomato", "Karnataka")

        assert results == []

    def test_returns_empty_list_on_http_error(self):
        """fetch_live_prices returns [] on a non-200 HTTP error."""
        fake_response = MagicMock()
        fake_response.raise_for_status.side_effect = _requests_module.HTTPError("403")

        with patch("services.market_service.requests.get", return_value=fake_response):
            results = fetch_live_prices("Tomato", "Karnataka")

        assert results == []

    def test_returns_empty_list_on_empty_records(self):
        """fetch_live_prices returns [] when API returns empty records list."""
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {"records": []}

        with patch("services.market_service.requests.get", return_value=fake_response):
            results = fetch_live_prices("Tomato", "Karnataka")

        assert results == []

    def test_get_market_price_uses_live_when_available(self):
        """get_market_price returns is_live=True when fetch_live_prices returns data."""
        live_data = [{
            "crop": "Tomato",
            "market": "Kolar",
            "district": "Kolar",
            "state": "Karnataka",
            "min_price": "800",
            "max_price": "1200",
            "modal_price": "1000",
            "unit": "Quintal",
            "data_date": "2024-01-15",
            "source_url": "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070",
            "is_live": True,
        }]

        with patch("services.market_service.fetch_live_prices", return_value=live_data):
            result = get_market_price("Tomato", state="Karnataka")

        assert result["is_live"] is True
        assert result["crop"] == "Tomato"

    def test_get_market_price_falls_back_to_csv_when_live_empty(self):
        """get_market_price falls back to CSV when fetch_live_prices returns []."""
        with patch("services.market_service.fetch_live_prices", return_value=[]):
            result = get_market_price("paddy", state="Karnataka")

        # CSV has paddy data; should find it with is_live=False
        assert isinstance(result, dict)
        if result.get("available") is not False:
            assert result.get("is_live") is False


# =========================================================
# SCHEME SERVICE TESTS
# =========================================================

class TestSchemeService:

    def test_schemes_load_non_empty(self):
        """schemes.json should load and return at least one scheme."""
        schemes = load_schemes()
        assert isinstance(schemes, list)
        assert len(schemes) > 0, "schemes.json must contain at least one scheme"

    def test_search_schemes_insurance_returns_pmfby(self):
        """Searching for 'insurance' must return at least one result containing PMFBY."""
        results = search_schemes("insurance")
        assert len(results) >= 1, "Expected at least one result for 'insurance'"
        ids_and_names = [
            (s.get("id", "").lower(), s.get("name", "").lower())
            for s in results
        ]
        pmfby_found = any(
            "pmfby" in scheme_id or "pmfby" in name or "fasal bima" in name
            for scheme_id, name in ids_and_names
        )
        assert pmfby_found, f"Expected PMFBY in results for 'insurance', got: {[s.get('name') for s in results]}"

    def test_search_schemes_returns_at_most_3(self):
        """search_schemes should return at most 3 results."""
        results = search_schemes("farmer")
        assert len(results) <= 3

    def test_search_schemes_state_filter(self):
        """State filter should restrict results to matching or All India schemes."""
        results = search_schemes("scheme", state="Karnataka")
        for s in results:
            applicable = [st.lower() for st in s.get("applicable_states", [])]
            assert "all india" in applicable or "karnataka" in applicable, (
                f"Scheme '{s.get('name')}' not applicable to Karnataka"
            )

    def test_format_scheme_response_includes_official_url(self):
        """format_scheme_response must include the official_url in the output."""
        schemes = load_schemes()
        assert len(schemes) > 0, "Need at least one scheme to test formatting"
        scheme = schemes[0]
        response = format_scheme_response(scheme, language_code="en")
        assert isinstance(response, str)
        official_url = scheme.get("official_url", "")
        assert official_url in response, (
            f"official_url '{official_url}' not found in formatted response: {response[:200]}"
        )

    def test_format_scheme_response_includes_verified_date(self):
        """format_scheme_response must include the source_verified_date."""
        schemes = load_schemes()
        scheme = schemes[0]
        response = format_scheme_response(scheme, language_code="en")
        verified_date = scheme.get("source_verified_date", "")
        assert verified_date in response, (
            f"source_verified_date '{verified_date}' not found in response: {response[:200]}"
        )

    def test_search_schemes_pm_kisan(self):
        """Searching 'pm kisan' returns the PM-KISAN scheme."""
        results = search_schemes("pm kisan")
        assert len(results) >= 1
        names = [s.get("name", "").lower() for s in results]
        assert any("kisan" in n for n in names), f"Expected PM-KISAN in results, got: {names}"

    def test_search_schemes_no_match_returns_empty(self):
        """Searching for a nonsense term returns an empty list."""
        results = search_schemes("zzznomatch_xyzabc_scheme")
        assert results == []
