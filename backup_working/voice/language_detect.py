from langdetect import detect


def detect_language(text):
    text_lower = text.lower()

    # Tulu keywords
    tulu_keywords = [
        "yenna",
        "malpini",
        "undu",
        "barpini",
        "daiji",
        "tulu"
    ]

    # Konkani keywords
    konkani_keywords = [
        "hanv",
        "tuka",
        "kitem",
        "koso",
        "asa",
        "goen",
        "konkani"
    ]

    if any(word in text_lower for word in tulu_keywords):
        return "Tulu"

    if any(word in text_lower for word in konkani_keywords):
        return "Konkani"

    try:
        lang = detect(text)

        languages = {
            "en": "English",
            "kn": "Kannada",
            "hi": "Hindi",
            "ta": "Tamil",
            "te": "Telugu",
            "ml": "Malayalam",
            "mr": "Marathi"
        }

        return languages.get(lang, "Unknown")

    except Exception:
        return "Unknown"