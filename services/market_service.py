"""
Market price service — reads local CSV of historical AGMARKNET data.

Data source: d:/Major_Project/data/market_prices_sample.csv
Note: This is historical sample data based on AGMARKNET published ranges.
      For live prices visit https://agmarknet.gov.in
"""

# AGMARKNET live API: blocked pending registration at data.gov.in
# Register at: https://data.gov.in/user/register
# Set DATA_GOV_IN_API_KEY in .env once registered
# Falls back to CSV data until then

import csv
import os

# =========================================================
# CSV PATH
# =========================================================

_CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "market_prices_sample.csv")

_NOTE = "Historical sample data — for live prices visit agmarknet.gov.in"


# =========================================================
# LOAD AT MODULE LEVEL
# =========================================================

def load_market_data() -> list:
    """
    Read the market_prices_sample.csv and return a list of dicts.
    Skips comment lines (starting with '#').
    Returns empty list if file is missing.
    """
    records = []
    if not os.path.exists(_CSV_PATH):
        return records

    with open(_CSV_PATH, newline="", encoding="utf-8") as fh:
        for line in fh:
            # Skip header comment lines
            if line.strip().startswith("#"):
                continue
            # Feed non-comment lines to csv.DictReader via an iterator trick
            # We collect clean lines and parse them together below.
            break  # exit the manual loop; will use DictReader properly next

    # Re-open and collect clean (non-comment) lines
    clean_lines = []
    with open(_CSV_PATH, newline="", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip().startswith("#"):
                clean_lines.append(line)

    if not clean_lines:
        return records

    reader = csv.DictReader(clean_lines)
    for row in reader:
        records.append(dict(row))

    return records


# Load once at module import
_MARKET_DATA: list = load_market_data()


# =========================================================
# PUBLIC API
# =========================================================

def get_market_price(crop: str, district: str = None, state: str = "Karnataka") -> dict:
    """
    Return price info for a crop, optionally filtered by district and state.

    Returns a dict with:
        crop, market, district, state, min_price, max_price, modal_price,
        unit, data_date, source_url, is_live, note

    Returns {available: False, reason: '...'} if no matching record found.
    """
    crop_lower = crop.strip().lower()
    state_lower = state.strip().lower()

    matches = [
        r for r in _MARKET_DATA
        if r.get("crop", "").lower() == crop_lower
        and r.get("state", "").lower() == state_lower
    ]

    if district:
        district_lower = district.strip().lower()
        district_matches = [
            r for r in matches
            if r.get("district", "").lower() == district_lower
        ]
        if district_matches:
            matches = district_matches

    if not matches:
        location = district if district else state
        return {
            "available": False,
            "reason": f"No data found for {crop} in {location}",
        }

    # Return the first (most recent available) match with all required fields
    r = matches[0]
    return {
        "crop":        r.get("crop"),
        "market":      r.get("market"),
        "district":    r.get("district"),
        "state":       r.get("state"),
        "min_price":   r.get("min_price"),
        "max_price":   r.get("max_price"),
        "modal_price": r.get("modal_price"),
        "unit":        r.get("unit"),
        "data_date":   r.get("date"),
        "source_url":  r.get("source_url"),
        "is_live":     False,
        "note":        _NOTE,
    }


def search_market_prices(query: str) -> list:
    """
    Case-insensitive keyword search on crop name.

    Returns a list of price dicts (with data_date and source_url)
    for all matching records. Returns empty list if none found.
    """
    query_lower = query.strip().lower()
    results = []
    seen_crops = set()

    for r in _MARKET_DATA:
        crop_name = r.get("crop", "").lower()
        if query_lower in crop_name and crop_name not in seen_crops:
            seen_crops.add(crop_name)
            results.append({
                "crop":        r.get("crop"),
                "market":      r.get("market"),
                "district":    r.get("district"),
                "state":       r.get("state"),
                "min_price":   r.get("min_price"),
                "max_price":   r.get("max_price"),
                "modal_price": r.get("modal_price"),
                "unit":        r.get("unit"),
                "data_date":   r.get("date"),
                "source_url":  r.get("source_url"),
                "is_live":     False,
                "note":        _NOTE,
            })

    return results
