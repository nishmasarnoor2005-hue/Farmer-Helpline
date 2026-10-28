"""
Government scheme catalogue service.

Data source: d:/Major_Project/data/schemes.json
All scheme data sourced from official .gov.in pages.
"""

import json
import os

# =========================================================
# JSON PATH
# =========================================================

_JSON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "schemes.json")


# =========================================================
# LOAD
# =========================================================

def load_schemes() -> list:
    """
    Read data/schemes.json and return a list of scheme dicts.
    Returns empty list if file is missing or invalid.
    """
    if not os.path.exists(_JSON_PATH):
        return []
    try:
        with open(_JSON_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []


# =========================================================
# SEARCH
# =========================================================

def search_schemes(query: str, state: str = None) -> list:
    """
    Return up to 3 schemes whose name, eligibility, or benefits contain
    the query keyword (case-insensitive).

    Optionally filter by state: matches schemes applicable to that state
    or to 'All India'.
    """
    query_lower = query.strip().lower()
    all_schemes = load_schemes()

    scored = []
    for scheme in all_schemes:
        # State filter
        if state:
            applicable = [s.lower() for s in scheme.get("applicable_states", [])]
            if state.lower() not in applicable and "all india" not in applicable:
                continue

        # Keyword match — score by number of fields that match
        score = 0
        search_fields = [
            scheme.get("name", ""),
            scheme.get("eligibility", ""),
            scheme.get("benefits", ""),
            scheme.get("id", ""),
        ]
        for field in search_fields:
            if query_lower in field.lower():
                score += 1

        if score > 0:
            scored.append((score, scheme))

    # Sort by score descending, return top 3
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:3]]


# =========================================================
# FORMAT FOR VOICE
# =========================================================

def format_scheme_response(scheme: dict, language_code: str = "en") -> str:
    """
    Return a voice-friendly 2-3 sentence summary of a scheme.
    Always includes source_verified_date and official_url.
    language_code is accepted for future localisation but output is English
    (Gemini will translate in the main assistant prompt).
    """
    name             = scheme.get("name", "Unknown scheme")
    benefits         = scheme.get("benefits", "Refer to official source for benefit details.")
    application      = scheme.get("application_method", "Contact your local agriculture office.")
    official_url     = scheme.get("official_url", "")
    verified_date    = scheme.get("source_verified_date", "")

    summary = (
        f"{name}: {benefits} "
        f"To apply: {application} "
        f"Official source: {official_url} (verified {verified_date})."
    )
    return summary
