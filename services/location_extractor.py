import re
import logging

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable

logger = logging.getLogger(__name__)

# Module-level geocoder instance (shared, not recreated per call)
geolocator = Nominatim(user_agent="farmer_helpline_v1", timeout=5)

# Words to ignore when scanning tokens
STOP_WORDS = {
    "i", "am", "from", "speaking", "talking", "hello", "calling",
    "ನಾನು", "ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ", "ಮಾತಾಡುತ್ತಿದ್ದೇನೆ", "ಇದ್ದೇನೆ",
    "मैं", "से", "बात", "कर", "रहा", "रही", "हूँ",
}


def _clean_kannada_word(word: str) -> str:
    """Strip common Kannada location-case suffixes."""
    endings = [
        "ದಿಂದ", "ನಿಂದ", "ಇಂದ", "ದಿಂದಲೇ", "ನಿಂದಲೇ",
        "ಊರಿಂದ", "ಊರಿನಿಂದ", "ೂರಿನಿಂದ",
    ]
    for end in endings:
        if word.endswith(end):
            word = word[: -len(end)]
    return word.strip()


def _generate_candidates(word: str) -> list:
    """Return spelling variants for a word (handles common OCR/Kannada forms)."""
    candidates = [word]
    special_map = {
        "ಚಿಕ್ಕಮಗಳೂರ": "ಚಿಕ್ಕಮಗಳೂರು",
        "ಮಂಗಳೂರ":      "ಮಂಗಳೂರು",
        "ಬೆಂಗಳೂರ":     "ಬೆಂಗಳೂರು",
        "ಮೈಸೂರ":       "ಮೈಸೂರು",
    }
    if word in special_map:
        candidates.append(special_map[word])
    return candidates


def _geocode_safely(query: str) -> object:
    """
    Call geolocator.geocode() with full exception handling.
    Returns a geopy Location on success, None on any failure.
    """
    try:
        return geolocator.geocode(query, exactly_one=True, timeout=5)
    except GeocoderTimedOut:
        logger.warning("Geocoder timed out for query: %s", query)
        return None
    except GeocoderUnavailable:
        logger.warning("Geocoder unavailable for query: %s", query)
        return None
    except Exception as exc:
        logger.error("Geocoder unexpected error for query '%s': %s", query, exc)
        return None


def extract_location(text: str):
    """
    Extract the first recognisable place name from farmer speech.

    Returns a dict with keys: query, address, latitude, longitude
    or None if no location is found or the geocoder fails.
    """
    if not text:
        return None

    # Normalise: keep only letters + spaces (Latin and major Indic scripts)
    cleaned = re.sub(r"[^A-Za-zಀ-೿ऀ-ॿ\u0D00-\u0D7F ]", " ", text)

    # Common verbatim Kannada substitutions
    cleaned = cleaned.replace("ಚಿಕ್ಕಮಗಳೂರಿನಿಂದ", "ಚಿಕ್ಕಮಗಳೂರು")
    cleaned = cleaned.replace("ಮಂಡ್ಯದಿಂದ",        "ಮಂಡ್ಯ")
    cleaned = cleaned.replace("ಮಂಗಳೂರಿನಿಂದ",      "ಮಂಗಳೂರು")
    cleaned = cleaned.replace("ಬೆಂಗಳೂರುದಿಂದ",     "ಬೆಂಗಳೂರು")

    words = cleaned.split()
    processed = []
    for w in words:
        w = _clean_kannada_word(w)
        if w and w.lower() not in STOP_WORDS and len(w) >= 3:
            processed.append(w)

    # Try each token (and its spelling variants) against the geocoder
    for w in processed:
        for candidate in _generate_candidates(w):
            location = _geocode_safely(candidate + ", India")
            if location:
                return {
                    "query":     candidate,
                    "address":   location.address,
                    "latitude":  location.latitude,
                    "longitude": location.longitude,
                }

    # Final fallback: try the entire cleaned text as a sentence
    location = _geocode_safely(text + ", Karnataka, India")
    if location:
        return {
            "query":     text,
            "address":   location.address,
            "latitude":  location.latitude,
            "longitude": location.longitude,
        }

    return None


if __name__ == "__main__":
    tests = [
        "ನಾನು ಚಿಕ್ಕಮಗಳೂರಿನಿಂದ ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ",
        "ನಾನು ಮಂಡ್ಯದಿಂದ ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ",
        "I am speaking from Udupi",
        "मैं चिकमगलूर से बात कर रहा हूँ",
        "I am calling from Mumbai",
    ]
    for t in tests:
        print("\nInput:", t)
        print("Output:", extract_location(t))
