"""
voice/text_to_speech.py

Text-to-speech using Edge TTS neural voices.

On Render (gunicorn + gevent + Python 3.14) gevent monkey-patches asyncio
so deeply that asyncio.new_event_loop() raises RuntimeError even inside
ThreadPoolExecutor threads. The only reliable escape is a subprocess.

speak() spawns tts_worker.py as a separate Python process — completely
outside gevent's reach — and falls back to gTTS if that fails.
"""

import os
import subprocess
import sys

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

# Path to the subprocess worker script
_WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_worker.py")

# Python executable to use for the subprocess (same venv as current process)
_PYTHON = sys.executable


# =========================================================
# INTERNAL: gTTS fallback (synchronous, no asyncio)
# =========================================================

def _gtts_speak(text: str, lang_key: str, save_path: str) -> bool:
    """Try gTTS as a fallback. Returns True on success."""
    gtts_map = {
        "kn": "kn", "hi": "hi", "ml": "ml",
        "ta": "ta", "te": "te", "mr": "mr",
        "en": "en", "ur": "ur",
    }
    try:
        from gtts import gTTS
        gtts_lang = gtts_map.get(lang_key, "en")
        gTTS(text=str(text), lang=gtts_lang, slow=False).save(save_path)
        print(f"⚠️  gTTS fallback used ({gtts_lang})")
        return True
    except Exception as e:
        print(f"❌ gTTS fallback failed: {e}")
        return False


# =========================================================
# PUBLIC: speak()
# =========================================================

def speak(text: str, language: str = "en", output_path: str = None) -> str | None:
    """
    Convert text to speech.

    Tries Edge TTS via subprocess (avoids gevent asyncio conflict),
    falls back to gTTS if subprocess fails.

    Args:
        text:        Text to speak.
        language:    ISO language code or full name.
        output_path: Output MP3 path. Auto-generated if not given.

    Returns:
        Path to saved MP3, or None on total failure.
    """
    save_path = output_path or _DEFAULT_OUTPUT
    lang_key  = str(language).lower().strip()
    voice     = VOICE_MAP.get(lang_key, VOICE_MAP["en"])

    # --- Attempt 1: Edge TTS via subprocess ---
    try:
        result = subprocess.run(
            [_PYTHON, _WORKER_SCRIPT, voice, save_path, text],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and os.path.exists(save_path) and os.path.getsize(save_path) > 100:
            print(f"✅ Edge TTS saved: {os.path.basename(save_path)} ({voice})")
            return save_path
        else:
            err = result.stderr.strip()[:200] if result.stderr else "empty output"
            print(f"❌ Edge TTS subprocess failed (rc={result.returncode}): {err}")
    except subprocess.TimeoutExpired:
        print("❌ Edge TTS subprocess timed out")
    except Exception as e:
        print(f"❌ Edge TTS subprocess error: {e}")

    # --- Attempt 2: gTTS fallback ---
    if _gtts_speak(text, lang_key, save_path):
        return save_path

    return None


# =========================================================
# PUBLIC: speak_to_bytes()
# =========================================================

def speak_to_bytes(text: str, language_code: str) -> bytes:
    """
    Synthesise speech and return raw MP3 bytes.
    Uses speak() internally with a temp file.

    Returns:
        Raw MP3 bytes.

    Raises:
        RuntimeError: if both Edge TTS and gTTS fail.
    """
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
