from geopy.geocoders import Nominatim
import re

geolocator = Nominatim(user_agent="farmer_ivr")

# Words to ignore
STOP_WORDS = {
    "i", "am", "from", "speaking", "talking", "hello", "calling",
    "ನಾನು", "ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ", "ಮಾತಾಡುತ್ತಿದ್ದೇನೆ", "ಇದ್ದೇನೆ",
    "मैं", "से", "बात", "कर", "रहा", "रही", "हूँ"
}


def clean_kannada_word(word):
    # Remove common Kannada location endings
    endings = [
        "ದಿಂದ", "ನಿಂದ", "ಇಂದ", "ದಿಂದಲೇ", "ನಿಂದಲೇ",
        "ಊರಿಂದ", "ಊರಿನಿಂದ", "ೂರಿನಿಂದ"
    ]

    for end in endings:
        if word.endswith(end):
            word = word[:-len(end)]

    return word.strip()

def generate_candidates(word):
    candidates = [word]

    # Direct Kannada corrections
    special_map = {
        "ಚಿಕ್ಕಮಗಳೂರ": "ಚಿಕ್ಕಮಗಳೂರು",
        "ಮಂಗಳೂರ": "ಮಂಗಳೂರು",
        "ಬೆಂಗಳೂರ": "ಬೆಂಗಳೂರು",
        "ಮೈಸೂರ": "ಮೈಸೂರು"
    }

    if word in special_map:
        candidates.append(special_map[word])

    return candidates

def extract_location(text):

    cleaned = re.sub(r"[^A-Za-zಀ-೿ऀ-ॿ ]", " ", text)
    # Quick Kannada fixes
    cleaned = cleaned.replace("ಚಿಕ್ಕಮಗಳೂರಿನಿಂದ", "ಚಿಕ್ಕಮಗಳೂರು")
    cleaned = cleaned.replace("ಮಂಡ್ಯದಿಂದ", "ಮಂಡ್ಯ")
    cleaned = cleaned.replace("ಮಂಗಳೂರಿನಿಂದ", "ಮಂಗಳೂರು")
    cleaned = cleaned.replace("ಬೆಂಗಳೂರುದಿಂದ", "ಬೆಂಗಳೂರು")
    words = cleaned.split()

    processed = []

    for w in words:
        w = clean_kannada_word(w)

        if w and w.lower() not in STOP_WORDS and len(w) >= 3:
            processed.append(w)

    for w in processed:

        for candidate in generate_candidates(w):

            try:
                location = geolocator.geocode(
                    candidate + ", India",
                    exactly_one=True,
                    timeout=10
                )

                if location:
                    return {
                        "query": candidate,
                        "address": location.address,
                        "latitude": location.latitude,
                        "longitude": location.longitude
                    }

            except Exception:
                continue

    return None


if __name__ == "__main__":

    tests = [
        "ನಾನು ಚಿಕ್ಕಮಗಳೂರಿನಿಂದ ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ",
        "ನಾನು ಮಂಡ್ಯದಿಂದ ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ",
        "I am speaking from Udupi",
        "मैं चिकमगलूर से बात कर रहा हूँ",
        "I am calling from Mumbai",
        "Hanv Goa vochon uloita"
    ]

    for t in tests:
        print("\nInput:", t)
        result = extract_location(t)
        print("Output:", result)