"""
voice/text_to_speech.py

Text-to-speech using Edge TTS neural voices with gTTS fallback.
Runs under gunicorn gthread worker (no gevent) on Render.
"""

import asyncio
import os

# =========================================================
# NEURAL VOICE MAP
# =========================================================

VOICE_MAP = {
    "kn": "kn-IN-SapnaNeural",
    "hi": "hi-IN-SwaraNeural",
    "ml": "ml-IN-SobhanaNeural",
    "en": "en-IN-NeerjaNeural",
    "ta": "ta-IN-PallaviNeural",
    "te": "te-IN-ShrutiNeural",
    "mr": "mr-IN-AarohiNeural",
    "ur": "ur-PK-UzmaNeural",
    "kannada":   "kn-IN-SapnaNeural",
    "hindi":     "hi-IN-SwaraNeural",
    "malayalam": "ml-IN-SobhanaNeural",
    "english":   "en-IN-NeerjaNeural",
    "tamil":     "ta-IN-PallaviNeural",
    "telugu":    "te-IN-ShrutiNeural",
    "marathi":   "mr-IN-AarohiNeural",
    "urdu":      "ur-PK-UzmaNeural",
}

_DEFAULT_OUTPUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "farmer_reply.mp3"
)


async def _synthesize(text: str, voice: str, output_path: str):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def speak(text: str, language: str = "en", output_path: str = None) -> str | None:
    """Convert text to speech. Returns path to MP3 or None on failure."""
    save_path = output_path or _DEFAULT_OUTPUT
    lang_key  = str(language).lower().strip()
    voice     = VOICE_MAP.get(lang_key, VOICE_MAP["en"])

    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_synthesize(text, voice, save_path))
        finally:
            loop.close()
        print(f"✅ Edge TTS saved: {os.path.basename(save_path)} ({voice})")
        return save_path

    except Exception as edge_error:
        print(f"❌ Edge TTS error: {edge_error}")
        try:
            from gtts import gTTS
            gtts_map = {"kn":"kn","hi":"hi","ml":"ml","ta":"ta",
                        "te":"te","mr":"mr","en":"en","ur":"ur"}
            gTTS(text=str(text), lang=gtts_map.get(lang_key,"en"), slow=False).save(save_path)
            print(f"⚠️  Fell back to gTTS ({lang_key})")
            return save_path
        except Exception as fallback_error:
            print(f"❌ gTTS fallback failed: {fallback_error}")
            return None


def speak_to_bytes(text: str, language_code: str) -> bytes:
    """Synthesise speech and return raw MP3 bytes."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        result = speak(text, language_code, output_path=tmp_path)
        if result and os.path.exists(tmp_path):
            with open(tmp_path, "rb") as f:
                audio_bytes = f.read()
            if audio_bytes:
                return audio_bytes
        raise RuntimeError(f"speak() produced no audio for language={language_code}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


if __name__ == "__main__":
    speak("ನಮಸ್ಕಾರ, ನಾನು ನಿಮ್ಮ AI ಕೃಷಿ ಸಹಾಯಕ.", "kn")
    print("Kannada test done.")
