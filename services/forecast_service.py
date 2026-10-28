"""
Price Forecast Service — Historical Statistics
-----------------------------------------------
Provides statistical summaries from historical sample data loaded from
market_prices_sample.csv. This is NOT a trained forecasting model.

When adequate data becomes available (2+ years of daily records per
crop/market combination), replace the statistics logic with an actual
time-series model (e.g. Prophet, ARIMA).
"""

from __future__ import annotations
import csv
import os
import statistics

DATASET_STATUS = (
    "Historical sample data: ~29 rows, Karnataka markets, 2023-2024. "
    "Statistical summary only — not a trained forecasting model."
)

_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "market_prices_sample.csv"
)

# ---------------------------------------------------------------------------
# Load CSV at import time
# ---------------------------------------------------------------------------

def _load_csv() -> list[dict]:
    """Load market_prices_sample.csv and return a list of row dicts.

    Skips comment lines (starting with #) and the header row.
    Normalises crop/commodity name to lowercase stripped.
    Returns an empty list if the file is missing or unreadable.
    """
    rows: list[dict] = []
    try:
        with open(_DATA_FILE, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(
                (line for line in fh if not line.strip().startswith("#"))
            )
            for row in reader:
                # Normalise the crop column (CSV header is 'crop')
                row["crop"] = row.get("crop", "").strip().lower()
                row["market"] = row.get("market", "").strip()
                rows.append(row)
    except Exception:
        pass
    return rows


_MARKET_DATA: list[dict] = _load_csv()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_price_forecast(crop: str, market: str | None = None) -> dict:
    """Return historical price statistics for a given crop and optional market.

    Parameters
    ----------
    crop : str
        Crop name (case-insensitive, partial match).
    market : str, optional
        Market/mandi name (case-insensitive, exact match).

    Returns
    -------
    dict
        If enough data is found (≥3 rows):
            available, crop, market, mean_price, min_price, max_price,
            price_unit, data_points, date_range_start, date_range_end,
            disclaimer, method, is_live
        Otherwise:
            available=False, reason
    """
    crop_norm = crop.strip().lower()
    market_norm = market.strip().lower() if market else None

    # Filter by crop (partial, case-insensitive)
    matched = [
        row for row in _MARKET_DATA
        if crop_norm in row["crop"] or row["crop"] in crop_norm
    ]

    # Further filter by market if specified
    if market_norm:
        matched = [
            row for row in matched
            if row["market"].lower() == market_norm
        ]

    if len(matched) < 3:
        return {
            "available": False,
            "reason": "Insufficient historical data for this crop/market combination",
        }

    # Parse modal prices (skip rows with invalid/missing values)
    modal_prices: list[float] = []
    for row in matched:
        try:
            modal_prices.append(float(row["modal_price"]))
        except (ValueError, KeyError):
            pass

    if len(modal_prices) < 3:
        return {
            "available": False,
            "reason": "Insufficient historical data for this crop/market combination",
        }

    mean_price = round(statistics.mean(modal_prices), 2)
    min_price  = round(min(modal_prices), 2)
    max_price  = round(max(modal_prices), 2)
    std_price  = round(statistics.stdev(modal_prices) if len(modal_prices) > 1 else 0.0, 2)  # noqa: F841 (available for callers)

    # Date range
    dates = sorted(
        row["date"].strip() for row in matched if row.get("date", "").strip()
    )
    date_range_start = dates[0] if dates else "N/A"
    date_range_end   = dates[-1] if dates else "N/A"

    return {
        "available":        True,
        "crop":             crop,
        "market":           market if market else "all markets in sample",
        "mean_price":       mean_price,
        "min_price":        min_price,
        "max_price":        max_price,
        "price_unit":       "INR per quintal",
        "data_points":      len(modal_prices),
        "date_range_start": date_range_start,
        "date_range_end":   date_range_end,
        "disclaimer": (
            "This is a statistical summary of historical sample data, "
            "NOT a price forecast. Do not use for financial decisions."
        ),
        "method":  "historical_statistics",
        "is_live": False,
    }
