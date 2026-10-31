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
        # Use new_event_loop (not asyncio.run) to avoid conflicts with
        # gevent's monkey-patched event loop under gunicorn GeventWebSocketWorker
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_synthesize(text, voice, save_path))
        finally:
            loop.close()
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


def speak_to_bytes(text: str, language_code: str) -> bytes:
    """
    Synthesise speech and return the raw MP3 bytes.

    Uses asyncio.new_event_loop() (not asyncio.run()) to avoid event-loop
    nesting when called from a Flask route that may already be inside an
    async context.  A named temp file is used because Edge TTS requires a
    file path rather than an in-memory stream.

    Falls back to gTTS if Edge TTS fails.

    Args:
        text:          The text to synthesise.
        language_code: ISO-639-1 language code (e.g. 'kn', 'hi', 'en').

    Returns:
        Raw MP3 bytes.  Never returns None or empty bytes on success.

    Raises:
        RuntimeError: if both Edge TTS and gTTS fail.
    """
    import tempfile

    lang_key = str(language_code).lower().strip()
    voice    = VOICE_MAP.get(lang_key, VOICE_MAP["en"])

    # Use a NamedTemporaryFile with delete=False so we can reliably read it
    # after the async save and delete it in the finally block.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        # Use a fresh event loop to avoid nesting asyncio.run() calls.
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_synthesize(text, voice, tmp_path))
        finally:
            loop.close()

        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()

        if audio_bytes:
            return audio_bytes

        raise RuntimeError("Edge TTS produced an empty file")

    except Exception as edge_error:
        print(f"⚠️  speak_to_bytes: Edge TTS error ({edge_error}); falling back to gTTS")
        try:
            import io as _io
            from gtts import gTTS
            gtts_map = {
                "kn": "kn", "hi": "hi", "ml": "ml",
                "ta": "ta", "te": "te", "mr": "mr",
                "en": "en", "ur": "ur",
            }
            gtts_lang = gtts_map.get(lang_key, "en")
            buf = _io.BytesIO()
            gTTS(text=str(text), lang=gtts_lang, slow=False).write_to_fp(buf)
            audio_bytes = buf.getvalue()
            if audio_bytes:
                return audio_bytes
            raise RuntimeError("gTTS produced empty bytes")
        except Exception as gtts_error:
            raise RuntimeError(
                f"speak_to_bytes: both Edge TTS and gTTS failed. "
                f"Edge TTS: {edge_error}; gTTS: {gtts_error}"
            ) from gtts_error

    finally:
        if tmp_path:
            try:
                import os as _os
                _os.unlink(tmp_path)
            except OSError:
                pass


if __name__ == "__main__":
    speak("ನಮಸ್ಕಾರ, ನಾನು ನಿಮ್ಮ AI ಕೃಷಿ ಸಹಾಯಕ.", "kn")
    print("Kannada test done.")
