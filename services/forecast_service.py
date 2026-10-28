"""
Price Forecast Service — STUB
------------------------------
Forecasting is not yet implemented. A minimum of 2 years of daily
historical price records is required to build a reliable model.

The market_prices_sample.csv file in this project contains only
representative sample rows (29 data rows) — far too few for
time-series forecasting.

When adequate data becomes available:
  1. Populate a time-series dataset with at least 730 daily price rows
     per crop/market combination.
  2. Replace the body of get_price_forecast() with an actual model
     (e.g. Prophet, ARIMA, or a simple linear extrapolation).
  3. Update DATASET_STATUS to reflect the new data source.
"""

from __future__ import annotations
import csv
import os

DATASET_STATUS = "No adequate historical dataset available for forecasting."

_DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "market_prices_sample.csv")


def _count_data_months() -> int:
    """
    Count the number of non-comment, non-header rows in
    market_prices_sample.csv as a rough proxy for data volume.
    Returns 0 if the file is missing or unreadable.
    """
    count = 0
    try:
        with open(_DATA_FILE, encoding="utf-8", newline="") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and not stripped.startswith("crop"):
                    count += 1
    except Exception:
        pass
    return count


def get_price_forecast(crop: str, market: str = None) -> dict:
    """
    Return a stub forecast response for the given crop and market.

    This function will ALWAYS return available=False until a proper
    historical dataset is loaded and a model is trained.

    Parameters
    ----------
    crop : str
        Crop name (e.g. 'tomato', 'paddy').
    market : str, optional
        Market/mandi name (e.g. 'Mysore', 'Bangalore').

    Returns
    -------
    dict:
        available             : False
        reason                : Human-readable explanation
        data_available_months : int — rows found in sample CSV
    """
    return {
        "available": False,
        "reason": (
            "Insufficient historical data for reliable forecasting. "
            "Minimum 2 years of daily price records required."
        ),
        "data_available_months": _count_data_months(),
    }
