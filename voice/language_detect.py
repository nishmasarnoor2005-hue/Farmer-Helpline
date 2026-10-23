# NOTE: This file is NOT used by the Flask app (app.py).
# Language detection is handled by Whisper + Gemini directly in app.py.
# This file is kept for reference only.
#
# If you want to use it, import detect_language() from here.

from langdetect import detect, DetectorFactory

DetectorFactory.seed = 0


def detect_language(text):
    if not text or not text.strip():
        return "Unknown"

    # Detect English words reliably for simple greetings
    english_words = {
        "hello", "hi", "hey", "farmer", "farmers",
        "good", "morning", "afternoon", "evening",
        "help", "please", "thank", "you", "welcome"
    }

    words = set(text.lower().split())

    if words and words.issubset(english_words):
        return "English"

    try:
        lang = detect(text)

        languages = {
            "kn": "Kannada",
            "ta": "Tamil",
            "ml": "Malayalam",
            "te": "Telugu",
            "hi": "Hindi",
            "en": "English"
        }

        return languages.get(lang, "Unknown")

    except Exception:
        return "Unknown"


if __name__ == "__main__":
    test_sentences = [
        "ನಮಸ್ಕಾರ ರೈತರೇ",
        "வணக்கம் விவசாயிகளே",
        "നമസ്കാരം കർഷകരേ",
        "నమస్కారం రైతులారా",
        "नमस्ते किसान भाइयों",
        "Hello farmers"
    ]

    for sentence in test_sentences:
        print(f"Text: {sentence} | Detected: {detect_language(sentence)}")
