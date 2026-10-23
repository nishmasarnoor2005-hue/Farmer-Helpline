import os
import asyncio
import edge_tts

# =========================================================
# NEURAL VOICE MAP — one natural voice per language
# =========================================================

VOICE_MAP = {
    # Major languages
    "kn": "kn-IN-SapnaNeural",        # Kannada — female, natural
    "hi": "hi-IN-SwaraNeural",         # Hindi — female, natural
    "ml": "ml-IN-SobhanaNeural",       # Malayalam — female, natural
    "en": "en-IN-NeerjaNeural",        # English (Indian accent) — female

    # Minor languages
    "ta": "ta-IN-PallaviNeural",       # Tamil — female, natural
    "te": "te-IN-ShrutiNeural",        # Telugu — female, natural
    "mr": "mr-IN-AarohiNeural",        # Marathi — female, natural
    "ur": "ur-PK-UzmaNeural",          # Urdu — female, natural

    # Aliases (full language names)
    "kannada":   "kn-IN-SapnaNeural",
    "hindi":     "hi-IN-SwaraNeural",
    "malayalam": "ml-IN-SobhanaNeural",
    "english":   "en-IN-NeerjaNeural",
    "tamil":     "ta-IN-PallaviNeural",
    "telugu":    "te-IN-ShrutiNeural",
    "marathi":   "mr-IN-AarohiNeural",
    "urdu":      "ur-PK-UzmaNeural",
}

# Default fallback path (used when no output_path is provided)
_DEFAULT_OUTPUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "farmer_reply.mp3"
)


# =========================================================
# ASYNC CORE
# =========================================================

async def _synthesize(text: str, voice: str, output_path: str):
    """Generate speech using Edge TTS and save to file."""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


# =========================================================
# PUBLIC FUNCTION
# =========================================================

def speak(text: str, language: str = "en", output_path: str = None) -> str | None:
    """
    Convert text to speech using Edge TTS neural voices.

    Args:
        text:        The text to speak.
        language:    ISO language code (e.g. 'kn', 'hi') or full name.
        output_path: Where to save the MP3. Uses a default path if not given.
                     Pass a per-request unique path to avoid race conditions.

    Returns:
        Path to the saved MP3 file, or None on failure.
    """
    save_path = output_path or _DEFAULT_OUTPUT
    lang_key  = str(language).lower().strip()
    voice     = VOICE_MAP.get(lang_key, VOICE_MAP["en"])

    try:
        asyncio.run(_synthesize(text, voice, save_path))
        print(f"✅ Edge TTS saved: {os.path.basename(save_path)} ({voice})")
        return save_path

    except Exception as edge_error:
        print(f"❌ Edge TTS error: {edge_error}")

        # Fallback to gTTS
        try:
            from gtts import gTTS
            gtts_map = {
                "kn": "kn", "hi": "hi", "ml": "ml",
                "ta": "ta", "te": "te", "mr": "mr",
                "en": "en", "ur": "ur",
            }
            gtts_lang = gtts_map.get(lang_key, "en")
            gTTS(text=str(text), lang=gtts_lang, slow=False).save(save_path)
            print(f"⚠️  Fell back to gTTS ({gtts_lang})")
            return save_path

        except Exception as fallback_error:
            print(f"❌ gTTS fallback also failed: {fallback_error}")
            return None


if __name__ == "__main__":
    speak("ನಮಸ್ಕಾರ, ನಾನು ನಿಮ್ಮ AI ಕೃಷಿ ಸಹಾಯಕ.", "kn")
    print("Kannada test done.")
