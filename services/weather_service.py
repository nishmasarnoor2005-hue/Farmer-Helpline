"""
Weather service — fetches current weather from Open-Meteo (no API key required).

Public API:
    get_weather(location: dict) -> dict | None

    'location' is the dict returned by location_extractor.extract_location():
        {"latitude": float, "longitude": float, "address": str, ...}

Returns a dict with keys:
    location      – human-readable name (from input address)
    temperature   – °C (float)
    description   – plain-text condition (e.g. "Clear sky")
    humidity      – relative humidity % (int) — from hourly, current hour

Returns None on any failure (timeout, bad response, unknown location).
"""

import logging
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# WMO Weather Interpretation Code → human-readable description
# https://open-meteo.com/en/docs#weathervariables
# ---------------------------------------------------------------------------
WMO_CODES = {
    0:  "Clear sky",
    1:  "Mainly clear",
    2:  "Partly cloudy",
    3:  "Overcast",
    45: "Foggy",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}

_BASE_URL = "https://api.open-meteo.com/v1/forecast"


def get_weather(location: dict) -> dict | None:
    """
    Fetch current weather for the coordinates in *location*.

    Parameters
    ----------
    location : dict
        Must contain 'latitude' (float) and 'longitude' (float).
        Optionally 'address' (str) for the human-readable name.

    Returns
    -------
    dict or None
        Keys: location, temperature, description, humidity
        Returns None on any error.
    """
    if not location:
        return None

    lat = location.get("latitude")
    lon = location.get("longitude")
    if lat is None or lon is None:
        logger.warning("get_weather: missing latitude/longitude in location dict")
        return None

    params = {
        "latitude":       lat,
        "longitude":      lon,
        "current_weather": "true",
        "hourly":         "relativehumidity_2m",
        "timezone":       "auto",
        "forecast_days":  1,
    }

    try:
        resp = requests.get(_BASE_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        logger.warning("get_weather: request timed out for lat=%s lon=%s", lat, lon)
        return None
    except requests.exceptions.RequestException as exc:
        logger.error("get_weather: HTTP error: %s", exc)
        return None
    except ValueError as exc:
        logger.error("get_weather: JSON decode error: %s", exc)
        return None

    current = data.get("current_weather", {})
    temperature = current.get("temperature")
    wmo_code    = current.get("weathercode")
    description = WMO_CODES.get(wmo_code, f"Weather code {wmo_code}")

    # Humidity: pick the value for the current UTC hour from the hourly array
    humidity = None
    try:
        hourly_times = data.get("hourly", {}).get("time", [])
        hourly_hum   = data.get("hourly", {}).get("relativehumidity_2m", [])
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")
        if now_str in hourly_times:
            idx      = hourly_times.index(now_str)
            humidity = hourly_hum[idx]
        elif hourly_hum:
            humidity = hourly_hum[0]    # fallback: first available hour
    except Exception as exc:
        logger.warning("get_weather: could not extract humidity: %s", exc)

    address = location.get("address") or location.get("query") or f"{lat},{lon}"

    return {
        "location":    address,
        "temperature": temperature,
        "description": description,
        "humidity":    humidity,
    }


if __name__ == "__main__":
    # Quick smoke test — Bengaluru
    sample_loc = {
        "query":     "Bengaluru",
        "address":   "Bengaluru, Karnataka, India",
        "latitude":  12.9716,
        "longitude": 77.5946,
    }
    result = get_weather(sample_loc)
    print(result)
