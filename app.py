import os
import uuid
import re
import time
import threading
import secrets
import json
from datetime import datetime, timezone
from pathlib import Path

# NOTE: gevent monkey-patching is done in wsgi.py BEFORE this module is
# imported, so by the time we reach here ssl/socket are already patched.

# Load .env FIRST — before any other project imports read os.environ
from dotenv import load_dotenv
_ENV_FILE = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_ENV_FILE, override=True)

from flask import (
    Flask, render_template, request, jsonify,
    send_from_directory, session, redirect, url_for, flash,
    stream_with_context, Response,
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sock import Sock
from faster_whisper import WhisperModel
from google import genai
from google.genai import types
from dotenv import load_dotenv

from services.assistant import get_reply, reset_history
from services import location_extractor
from services import weather_service
from services import market_service

# =========================================================
# FASTER-WHISPER / AV COMPATIBILITY PATCH
# faster-whisper 1.2.1 calls av.open(..., metadata_errors="ignore")
# but av>=14 removed that keyword argument.
# Patch decode_audio to strip the unsupported kwarg at runtime.
# =========================================================
try:
    import av as _av
    import faster_whisper.audio as _fw_audio
    import inspect as _inspect

    _orig_decode_audio = _fw_audio.decode_audio

    def _patched_decode_audio(input_file, sampling_rate=16000, split_stereo=False):
        """Wrapper that calls av.open without metadata_errors on av>=14."""
        try:
            return _orig_decode_audio(input_file,
                                      sampling_rate=sampling_rate,
                                      split_stereo=split_stereo)
        except TypeError as _e:
            if "metadata_errors" not in str(_e):
                raise
            # av>=14: metadata_errors kwarg was removed — patch av.open directly
            _real_av_open = _av.open

            def _av_open_compat(file, *args, **kwargs):
                kwargs.pop("metadata_errors", None)
                return _real_av_open(file, *args, **kwargs)

            _av.open = _av_open_compat
            try:
                return _orig_decode_audio(input_file,
                                          sampling_rate=sampling_rate,
                                          split_stereo=split_stereo)
            finally:
                _av.open = _real_av_open  # restore after the call

    _fw_audio.decode_audio = _patched_decode_audio
    print("✅ faster-whisper/av compatibility patch applied")
except Exception as _patch_err:
    print(f"⚠️  Could not apply faster-whisper/av patch: {_patch_err}")

from services import scheme_service
from services.intent_service import classify_intent
from services.forecast_service import get_price_forecast, _MARKET_DATA as _FORECAST_DATA
from voice.text_to_speech import speak
from frontend.login import AdminUser, verify_admin
from frontend.dashboard import get_dashboard_data, get_interaction_history, service_health
import backend.database as db
from services.realtime.provider_factory import get_provider as _get_rt_provider

# .env already loaded at module top — no second call needed

# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-insecure-key-change-in-prod")

# Security: warn if running with a weak/default secret key outside debug mode
if not app.debug and app.secret_key in (None, "", "dev", "secret", "change-me", "dev-insecure-key-change-in-prod"):
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "SECURITY: Using default/weak secret key — set FLASK_SECRET_KEY in .env for production"
    )

# Upload size cap (10 MB)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

# Harden session cookie
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# =========================================================
# FLASK-LOGIN
# =========================================================

login_manager = LoginManager(app)
login_manager.login_view = "admin_login"


@login_manager.user_loader
def load_user(user_id: str):
    if user_id == "admin":
        return AdminUser()
    return None


# =========================================================
# RATE LIMITER
# =========================================================

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

# Initialise DB tables (preserves existing records)
db.init_db()

sock = Sock(app)

# =========================================================
# REAL-TIME VOICE — SESSION STORE
# Keys are short-lived opaque tokens (never logged).
# Each value is a dict with:
#   session_id  — internal UUID for DB logging
#   ip          — client IP at session creation time
#   created_at  — datetime (UTC)
#   expires_at  — datetime (UTC)
#   language_code — detected / set language for this session
#   cancelled   — bool, set True by /realtime/cancel
# =========================================================

_rt_sessions: dict = {}          # token → session_dict
_rt_sessions_lock = threading.Lock()

_REALTIME_SESSION_TTL = int(os.environ.get("REALTIME_SESSION_TTL_SECONDS", "300"))


def _rt_session_expiry_loop() -> None:
    """Background thread: evict expired realtime session tokens every 60 s."""
    import time as _time
    while True:
        _time.sleep(60)
        now = datetime.now(timezone.utc)
        with _rt_sessions_lock:
            expired = [tok for tok, info in _rt_sessions.items()
                       if info.get("expires_at", now) < now]
            for tok in expired:
                del _rt_sessions[tok]

if not app.config.get("TESTING", False):
    threading.Thread(
        target=_rt_session_expiry_loop,
        daemon=True,
        name="rt-session-expiry",
    ).start()

# =========================================================
# ABSOLUTE PATHS
# =========================================================

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
AUDIO_FOLDER  = os.path.join(BASE_DIR, "audio")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER,  exist_ok=True)

# =========================================================
# PRE-GENERATE "PLEASE WAIT" AUDIO — one per language
# These are played immediately when the farmer stops speaking
# so the conversation feels instant while Whisper processes.
# =========================================================

WAIT_MESSAGES = {
    "kn": "ಒಂದು ಕ್ಷಣ, ನಾನು ನೋಡುತ್ತೇನೆ.",           # Kannada: One moment, let me check.
    "hi": "एक पल, मैं देखता हूँ।",                    # Hindi
    "ml": "ഒരു നിമിഷം, ഞാൻ നോക്കട്ടെ.",              # Malayalam
    "en": "One moment, let me check.",                  # English
    "ta": "ஒரு நிமிடம், நான் பார்க்கிறேன்.",          # Tamil
    "te": "ఒక్క క్షణం, నేను చూస్తాను.",               # Telugu
    "mr": "एक क्षण, मी पाहतो.",                        # Marathi
    "ur": "ایک لمحہ، میں دیکھتا ہوں۔",               # Urdu
}

WAIT_AUDIO_DIR = os.path.join(BASE_DIR, "static", "wait_audio")
os.makedirs(WAIT_AUDIO_DIR, exist_ok=True)


def _generate_wait_audio():
    """Pre-generate wait audio files at startup. Runs in background thread."""
    from voice.text_to_speech import speak as _speak
    for lang_code, message in WAIT_MESSAGES.items():
        out_path = os.path.join(WAIT_AUDIO_DIR, f"wait_{lang_code}.mp3")
        if not os.path.exists(out_path):
            try:
                _speak(message, lang_code, output_path=out_path)
                print(f"   ✅ Wait audio generated: {lang_code}")
            except Exception as e:
                print(f"   ⚠️  Wait audio failed for {lang_code}: {e}")


# Generate wait audio in background so startup isn't delayed
if not app.config.get("TESTING", False):
    threading.Thread(target=_generate_wait_audio, daemon=True, name="wait-audio-gen").start()

# =========================================================
# WHISPER MODEL
# =========================================================

# Whisper is loaded lazily on first use to keep startup fast on Render.
# Model size is configurable via WHISPER_MODEL_SIZE env var.
# Render free tier: 512 MB RAM.  Approximate RAM per model:
#   tiny  ~200 MB  — fast, lower accuracy
#   base  ~290 MB  — good balance (default for Render)
#   small ~500 MB  — OOM on 512 MB free tier
# Set WHISPER_MODEL_SIZE=small in Render env only on paid (2 GB) plans.
_WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")

whisper_model = None
_whisper_lock = threading.Lock()


def _get_whisper():
    """Load Whisper model on first call (thread-safe lazy initialisation)."""
    global whisper_model
    if whisper_model is None:
        with _whisper_lock:
            if whisper_model is None:
                print(f"Loading Whisper {_WHISPER_MODEL_SIZE} model...")
                whisper_model = WhisperModel(
                    _WHISPER_MODEL_SIZE,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=2,  # 2 threads saves ~100 MB vs 4
                )
                print("Whisper model loaded!")
    return whisper_model

# =========================================================
# GEMINI CLIENT
# =========================================================

gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
GEMINI_MODEL  = "gemini-flash-lite-latest"

# =========================================================
# LANGUAGE MAPS
# =========================================================

# Name → ISO code  (what Gemini returns → what Whisper needs)
LANG_NAME_TO_CODE = {
    "kannada":   "kn",
    "english":   "en",
    "hindi":     "hi",
    "malayalam": "ml",
    "tamil":     "ta",
    "telugu":    "te",
    "marathi":   "mr",
    "urdu":      "ur",
}

SUPPORTED_CODES = set(LANG_NAME_TO_CODE.values())

LANG_CODE_TO_NAME = {
    "kn": "Kannada",
    "en": "English",
    "hi": "Hindi",
    "ml": "Malayalam",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "ur": "Urdu",
}

def get_language_name(code):
    return LANG_CODE_TO_NAME.get(code, "English")


# =========================================================
# CONCURRENCY GUARD — one lock per browser session
# Prevents a second /process_audio from hitting Whisper/Gemini
# while the first is still running.
# =========================================================

_session_locks: dict = {}      # session_id → threading.Lock
_locks_mutex = threading.Lock()  # guards _session_locks itself


def _get_session_lock(session_id: str) -> threading.Lock:
    """Return the per-session lock, creating it on first use."""
    with _locks_mutex:
        if session_id not in _session_locks:
            _session_locks[session_id] = threading.Lock()
        return _session_locks[session_id]


def _release_session_lock(session_id: str) -> None:
    """Release and remove the lock for a session."""
    with _locks_mutex:
        lock = _session_locks.pop(session_id, None)
    if lock:
        try:
            lock.release()
        except RuntimeError:
            pass  # already released


# =========================================================
# GEMINI RETRY HELPER
# Retries on transient 503 / timeout errors only.
# =========================================================

def _gemini_with_retry(fn, *args, max_retries: int = 2, **kwargs):
    """
    Call fn(*args, **kwargs).  On 503 / timeout / connection error,
    wait 1 s and retry up to max_retries times.
    Non-retryable errors (400, 401, 403, …) are re-raised immediately.
    """
    retryable_hints = ("503", "timeout", "unavailable", "connection")
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            msg = str(exc).lower()
            is_retryable = any(hint in msg for hint in retryable_hints)
            if not is_retryable:
                raise
            last_exc = exc
            if attempt < max_retries:
                print(f"   ⚠️  Gemini transient error (attempt {attempt + 1}): {exc} — retrying in 1 s")
                time.sleep(1)
    raise last_exc  # exhausted retries


# =========================================================
# SESSION LANGUAGE CACHE
# After the first turn we already know the farmer's language.
# Skip Gemini audio detection on subsequent turns of the same call.
# =========================================================
_session_language_cache: dict = {}   # call_session_id → language_code
_cache_mutex = threading.Lock()

def _get_cached_language(session_id: str):
    with _cache_mutex:
        return _session_language_cache.get(session_id)

def _cache_language(session_id: str, language_code: str):
    with _cache_mutex:
        _session_language_cache[session_id] = language_code

def _clear_language_cache(session_id: str):
    with _cache_mutex:
        _session_language_cache.pop(session_id, None)


# =========================================================
# STEP 1 — GEMINI DETECTS LANGUAGE FROM AUDIO DIRECTLY
# This is the key fix: we ask Gemini to listen to the raw audio
# instead of relying on Whisper's mis-transcribed text.
# =========================================================

def detect_language_from_audio(audio_path: str) -> str:
    """
    Upload the audio to Gemini and ask it to identify the spoken language.
    Returns an ISO language code (e.g. 'kn', 'hi').
    Falls back to 'kn' (Kannada) as the default for this app's audience.
    """
    try:
        print("   Uploading audio to Gemini for language detection...")

        # Upload the audio file
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        # Use inline audio data
        def _detect_call():
            return gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(
                        data=audio_bytes,
                        mime_type="audio/webm",
                    ),
                    (
                        "Listen to this audio carefully.\n"
                        "Identify ONLY the spoken language.\n"
                        "Reply with exactly ONE word from this list: "
                        "Kannada, English, Hindi, Malayalam, Tamil, Telugu, Marathi, Urdu\n"
                        "Do not say anything else. Just one word."
                    ),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=5,
                ),
            )

        response = _gemini_with_retry(_detect_call)

        detected = response.text.strip().lower().split()[0]
        code = LANG_NAME_TO_CODE.get(detected)

        if code:
            print(f"   ✅ Gemini audio detection: '{detected}' → {code}")
            return code
        else:
            print(f"   ⚠️  Gemini returned unexpected: '{detected}' — defaulting to kn")
            return "kn"

    except Exception as e:
        print(f"   ⚠️  Gemini audio detection failed: {e}")
        return "kn"   # Default to Kannada for this helpline's primary audience


# =========================================================
# STEP 2 — WHISPER TRANSCRIPTION WITH FORCED LANGUAGE
# Now that we know the language, Whisper transcribes correctly.
# =========================================================

# Noise gate — segments with no_speech_prob above this are discarded
NO_SPEECH_THRESHOLD = 0.6


def transcribe_with_language(audio_path: str, language_code: str) -> str:
    """
    Transcribe audio with the language forced.
    Filters out background noise using Whisper's no_speech_prob score.
    Returns clean transcribed text.
    """
    segments, _ = _get_whisper().transcribe(
        audio_path,
        beam_size=5,               # keep at 5 — beam_size=1 causes hallucinations on noisy audio
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=300,   # tighter — don't wait long for silence
            speech_pad_ms=100,             # less padding
            min_speech_duration_ms=100,    # ignore very short noise bursts
        ),
        condition_on_previous_text=False,
        language=language_code,
        temperature=0.0,
        no_speech_threshold=NO_SPEECH_THRESHOLD,
        compression_ratio_threshold=2.4,
        log_prob_threshold=-1.0,
        word_timestamps=False,             # skip alignment step — saves ~500ms
    )

    clean_parts = []
    for seg in segments:
        # Additional noise gate: skip segment if Whisper is not confident
        if seg.no_speech_prob > NO_SPEECH_THRESHOLD:
            print(f"   🔇 Skipping noisy segment (no_speech_prob={seg.no_speech_prob:.2f}): {seg.text[:30]}")
            continue
        clean_parts.append(seg.text.strip())

    return " ".join(clean_parts).strip()


# =========================================================
# HALLUCINATION CLEANER
# Whisper sometimes outputs repeated characters/syllables
# (e.g. ಲ್ಲ್ಲ್ಲ್ಲ್ಲ or lllll) when audio quality is poor.
# This removes them and sends the cleaned text to Gemini
# to reconstruct the intended meaning.
# =========================================================

def clean_hallucination(text: str, language_code: str) -> str:
    """
    Detect and clean Whisper hallucinations:
    - Repeated Unicode combining characters (virama clusters in Kannada etc.)
    - Repeated Latin characters
    - Then ask Gemini to reconstruct the intended sentence if needed.
    """

    # 1. Remove runs of 3+ identical characters (e.g. ್ಲ್ಲ್ಲ or lllll)
    cleaned = re.sub(r'(.)\1{2,}', r'\1\1', text)

    # 2. Remove runs of repeated Kannada/Indic syllable clusters
    #    Pattern: same consonant+virama repeating 3+ times
    cleaned = re.sub(r'([\u0C80-\u0CFF][\u0CCD]){3,}', '', cleaned)
    cleaned = re.sub(r'([\u0D00-\u0D7F][\u0D4D]){3,}', '', cleaned)  # Malayalam
    cleaned = re.sub(r'([\u0900-\u097F][\u094D]){3,}', '', cleaned)  # Hindi

    # 3. Collapse multiple spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # 4. If text changed significantly, ask Gemini to reconstruct meaning
    # Only do this if more than 40% was stripped AND text is very short
    # (avoids a slow Gemini call for minor cleanup)
    if len(cleaned) < len(text) * 0.6 and len(cleaned) < 30:
        lang_name = get_language_name(language_code)
        print(f"   🔧 Severe hallucination detected. Asking Gemini to reconstruct...")
        try:
            def _reconstruct_call():
                return gemini_client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=(
                        f"This is a noisy speech transcription in {lang_name} with repeated characters removed.\n"
                        f"Reconstruct the most likely intended sentence in {lang_name}.\n"
                        f"Reply with ONLY the corrected sentence, nothing else.\n\n"
                        f"Noisy text: {cleaned}"
                    ),
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        max_output_tokens=100,
                    ),
                )

            response = _gemini_with_retry(_reconstruct_call)
            reconstructed = response.text.strip()
            print(f"   ✅ Reconstructed: {reconstructed}")
            return reconstructed
        except Exception as e:
            print(f"   ⚠️  Reconstruction failed: {e}")
            return cleaned

    return cleaned


# =========================================================
# WEATHER KEYWORDS (triggers location + weather lookup)
# =========================================================

WEATHER_KEYWORDS = [
    "weather", "rain", "temperature", "forecast", "climate",
    "mausam", "barish", "garmi", "thand", "paani",
]

# =========================================================
# MARKET KEYWORDS (triggers market price lookup)
# =========================================================

MARKET_KEYWORDS = [
    "price", "market", "rate", "sell", "mandi", "selling",
    # Kannada
    "\u0bac\u0bc6\u0bb2\u0bc6",  # ಬೆಲೆ (price)
    "\u0cae\u0cbe\u0cb0\u0cc1\u0c95\u0c9f\u0ccd\u0c9f\u0cc6",  # ಮಾರುಕಟ್ಟೆ (market)
    # Hindi
    "\u0926\u093e\u092e",  # दाम (price)
    "\u092c\u093e\u091c\u093e\u0930",  # बाजार (market)
]

# =========================================================
# SCHEME KEYWORDS (triggers government scheme lookup)
# =========================================================

SCHEME_KEYWORDS = [
    "scheme", "yojana", "subsidy", "loan", "insurance",
    "pm kisan", "kisan", "pmfby", "fasal bima",
    # Kannada
    "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6",  # ಯೋಜನೆ (scheme)
    "\u0cb8\u0cbe\u0cb2",  # ಸಾಲ (loan)
    # Hindi
    "\u092f\u094b\u091c\u0928\u093e",  # योजना (scheme)
]




@app.route("/")
def home():
    return render_template(
        "index.html",
        realtime_enabled=os.getenv("REALTIME_VOICE_ENABLED", "false").lower() == "true",
    )


# =========================================================
# PROCESS FARMER VOICE
# =========================================================

@app.route("/process_audio", methods=["POST"])
@limiter.limit(lambda: os.environ.get("RATE_LIMIT_PROCESS", "10 per minute"))
def process_audio():

    request_id     = uuid.uuid4().hex
    input_path     = os.path.join(UPLOAD_FOLDER, f"farmer_voice_{request_id}.webm")
    audio_filename = f"farmer_reply_{request_id}.mp3"
    audio_dest     = os.path.join(AUDIO_FOLDER, audio_filename)
    print(f"\n📥 /process_audio called [{request_id[:8]}]")

    # We need the session-based ID early so we can acquire its lock.
    # Flask's `session` is only available inside a request context, which we
    # are already inside here, so this is safe.
    call_session_id = session.get("call_session_id")
    if not call_session_id:
        call_session_id = uuid.uuid4().hex
        session["call_session_id"] = call_session_id
        db.create_session(call_session_id, channel="browser")

    # -------------------------------------------------
    # CONCURRENCY GUARD — one in-flight request per session
    # -------------------------------------------------
    session_lock = _get_session_lock(call_session_id)
    lock_acquired = session_lock.acquire(blocking=False)
    if not lock_acquired:
        # Already processing — return a voice-friendly TTS 429
        error_msg = "Already processing — please wait"
        busy_audio = f"farmer_reply_busy_{request_id}.mp3"
        busy_dest  = os.path.join(AUDIO_FOLDER, busy_audio)
        try:
            speak(error_msg, "en", output_path=busy_dest)
        except Exception:
            pass
        resp = jsonify({
            "success":   False,
            "error":     error_msg,
            "audio_url": f"/audio/{busy_audio}" if os.path.exists(busy_dest) else None,
        })
        resp.status_code = 429
        return resp

    try:

        # -------------------------------------------------
        # RECEIVE AUDIO
        # -------------------------------------------------

        if "audio" not in request.files:
            return jsonify({"success": False, "error": "No audio received"})

        audio_file = request.files["audio"]

        if audio_file.filename == "":
            return jsonify({"success": False, "error": "Empty audio file"})

        audio_file.save(input_path)
        print(f"\n🎙️  Audio received [{request_id[:8]}]")

        # -------------------------------------------------
        # INPUT VALIDATION — size check
        # -------------------------------------------------
        file_size = os.path.getsize(input_path)

        if file_size < 5_000:
            err_msg = "Audio too short — please speak for at least 1 second"
            short_audio = f"farmer_reply_short_{request_id}.mp3"
            short_dest  = os.path.join(AUDIO_FOLDER, short_audio)
            try:
                speak(err_msg, "en", output_path=short_dest)
            except Exception:
                pass
            return jsonify({
                "success":   False,
                "error":     err_msg,
                "audio_url": f"/audio/{short_audio}" if os.path.exists(short_dest) else None,
            })

        if file_size > 6_000_000:
            err_msg = "Audio too long — please keep under 60 seconds"
            long_audio = f"farmer_reply_long_{request_id}.mp3"
            long_dest  = os.path.join(AUDIO_FOLDER, long_audio)
            try:
                speak(err_msg, "en", output_path=long_dest)
            except Exception:
                pass
            return jsonify({
                "success":   False,
                "error":     err_msg,
                "audio_url": f"/audio/{long_audio}" if os.path.exists(long_dest) else None,
            })

        # -------------------------------------------------
        # STEP 1+2 — Language detection + Whisper in PARALLEL
        #
        # On first turn: Gemini detects language from audio AND Whisper
        # transcribes with a best-guess language simultaneously. If Gemini
        # returns a different language, we re-transcribe (rare after first turn).
        # On subsequent turns: language is cached — skip Gemini entirely.
        # -------------------------------------------------

        t0 = time.perf_counter()

        language_override = session.get("language_override", "auto")
        cached_lang = _get_cached_language(call_session_id)

        if language_override and language_override != "auto":
            # Manual override — just transcribe directly
            language_code = language_override
            language_name = get_language_name(language_code)
            print(f"⏳ Steps 1+2: Language override {language_code} — transcribing...")
            text = transcribe_with_language(input_path, language_code)
            t1 = time.perf_counter()
            t2 = t1

        elif cached_lang:
            # Subsequent turn — language known, skip Gemini entirely
            language_code = cached_lang
            language_name = get_language_name(language_code)
            print(f"⏳ Steps 1+2: Cached lang={language_code} — transcribing (no Gemini detect)...")
            text = transcribe_with_language(input_path, language_code)
            t1 = time.perf_counter()
            t2 = t1

        else:
            # First turn — run Gemini detect AND Whisper in parallel threads
            print("⏳ Steps 1+2: First turn — Gemini detect + Whisper running in parallel...")
            gemini_lang_result  = [None]
            whisper_text_result = [None]

            def _gemini_detect():
                gemini_lang_result[0] = detect_language_from_audio(input_path)

            def _whisper_transcribe_auto():
                # Transcribe with Kannada as best-guess (most common language)
                whisper_text_result[0] = transcribe_with_language(input_path, "kn")

            t_gemini_thread  = threading.Thread(target=_gemini_detect,          daemon=True)
            t_whisper_thread = threading.Thread(target=_whisper_transcribe_auto, daemon=True)

            t_gemini_thread.start()
            t_whisper_thread.start()
            t_gemini_thread.join(timeout=15)
            t_whisper_thread.join(timeout=30)

            t1 = time.perf_counter()

            language_code = gemini_lang_result[0] or "kn"
            language_name = get_language_name(language_code)
            _cache_language(call_session_id, language_code)
            print(f"   Gemini detected: {language_code} ({language_name})")

            # If Gemini confirmed same language as our guess, use whisper result
            if language_code == "kn" and whisper_text_result[0]:
                text = whisper_text_result[0]
                print(f"   Using parallel Whisper result (lang matched)")
            else:
                # Language differs — re-transcribe with confirmed language
                print(f"   Re-transcribing with confirmed lang={language_code}...")
                text = transcribe_with_language(input_path, language_code)

            t2 = time.perf_counter()

        print(f"   Raw transcription: {text[:80] if text else 'EMPTY'}")
        print(f"   ⏱ Detect+STT total: {(t2-t0)*1000:.0f}ms")

        if not text:
            return jsonify({
                "success": False,
                "error": "No clear speech detected. Please speak closer to the microphone."
            })

        # Clean hallucinations (repeated characters from poor audio)
        text = clean_hallucination(text, language_code)
        print(f"   Clean text: {text[:80]}")

        # -------------------------------------------------
        # INTENT CLASSIFICATION (rule-based)
        # -------------------------------------------------

        intent_result = classify_intent(text, language_code)
        detected_intent = intent_result["intent"]
        intent_method   = intent_result["method"]   # always 'rule_based'
        print(f"   Intent: {detected_intent} (confidence={intent_result['confidence']:.1f}, method={intent_method})")

        # -------------------------------------------------
        # GET AI REPLY (with optional context data)
        # Intent classifier drives routing; keyword lists serve as fallback.
        # -------------------------------------------------

        text_lower = text.lower()
        context_data = None

        # Weather lookup: intent OR keyword match
        if detected_intent == "weather" or any(kw in text_lower for kw in WEATHER_KEYWORDS):
            print("⏳ Weather keyword detected — looking up location & weather...")
            try:
                loc = location_extractor.extract_location(text)
                if loc:
                    print(f"   Location found: {loc.get('address')}")
                    weather_result = weather_service.get_weather(loc)
                    if weather_result:
                        context_data = {"weather": weather_result}
                        print(f"   Weather: {weather_result.get('temperature')}°C, {weather_result.get('description')}")
                    else:
                        print("   ⚠️  Weather fetch returned None — proceeding without weather context")
                else:
                    print("   ⚠️  No location found in transcript — proceeding without weather context")
            except Exception as weather_err:
                print(f"   ⚠️  Weather lookup error (non-fatal): {weather_err}")

        # Market price lookup: intent OR keyword match
        if detected_intent == "market_price" or any(kw in text_lower for kw in MARKET_KEYWORDS):
            print("⏳ Market keyword detected — searching market prices...")
            try:
                market_results = market_service.search_market_prices(text_lower)
                if market_results:
                    if context_data is None:
                        context_data = {}
                    context_data["market_data"] = market_results
                    print(f"   Market data: {len(market_results)} crop(s) found")
                else:
                    print("   ⚠️  No matching market data found for query")
            except Exception as market_err:
                print(f"   ⚠️  Market lookup error (non-fatal): {market_err}")

            # Price forecast (historical statistics) — extract crop from text
            try:
                known_crops = list({row["crop"] for row in _FORECAST_DATA})
                matched_crop = next(
                    (c for c in known_crops if c in text_lower), None
                )
                if matched_crop:
                    forecast_result = get_price_forecast(matched_crop)
                    if context_data is None:
                        context_data = {}
                    context_data["price_forecast"] = forecast_result
                    print(f"   Forecast data: available={forecast_result.get('available')} crop={matched_crop}")
            except Exception as forecast_err:
                print(f"   ⚠️  Forecast lookup error (non-fatal): {forecast_err}")

        # Government scheme lookup: intent OR keyword match
        if detected_intent == "government_scheme" or any(kw in text_lower for kw in SCHEME_KEYWORDS):
            print("⏳ Scheme keyword detected — searching government schemes...")
            try:
                scheme_results = scheme_service.search_schemes(text_lower)
                if scheme_results:
                    if context_data is None:
                        context_data = {}
                    context_data["scheme_data"] = scheme_results
                    print(f"   Scheme data: {len(scheme_results)} scheme(s) found")
                else:
                    print("   ⚠️  No matching schemes found for query")
            except Exception as scheme_err:
                print(f"   ⚠️  Scheme lookup error (non-fatal): {scheme_err}")

        print("⏳ Step 3: Getting AI reply (Gemini)...")
        print("⏳ Step 3: Getting AI reply (Gemini)...")
        reply_status = "success"
        error_cat = None
        try:
            reply = _gemini_with_retry(get_reply, text, language_code, context_data)
        except Exception as e:
            print(f"   Assistant Error: {e}")
            reply = "Sorry farmer, I could not process your question. Please try again."
            reply_status = "error"
            error_cat = "gemini_reply"

        print(f"   Reply: {reply[:80]}")

        t3 = time.perf_counter()

        # -------------------------------------------------
        # TEXT TO SPEECH
        # -------------------------------------------------

        print("⏳ Step 4: Generating voice (Edge TTS)...")
        result = speak(reply, language_code, output_path=audio_dest)

        t4 = time.perf_counter()

        if not result or not os.path.exists(audio_dest):
            return jsonify({"success": False, "error": "AI voice file was not created"})

        print("✅ Done.\n")

        # -------------------------------------------------
        # LOG INTERACTION TO DB (non-fatal)
        # -------------------------------------------------
        try:
            db.log_interaction(
                session_id=call_session_id,
                language=language_code,
                transcript=text,
                intent=detected_intent,
                assistant_response=reply,
                status=reply_status,
                latency_dict={
                    "total_latency_ms":   int((t4 - t0) * 1000),
                    "gemini_detect_ms":   int((t1 - t0) * 1000),
                    "whisper_ms":         int((t2 - t1) * 1000),
                    "gemini_reply_ms":    int((t3 - t2) * 1000),
                    "tts_ms":             int((t4 - t3) * 1000),
                },
                error_category=error_cat,
            )
        except Exception as db_err:
            print(f"⚠️  DB log_interaction error (non-fatal): {db_err}")

        return jsonify({
            "success":       True,
            "text":          text,
            "language":      language_name,
            "language_code": language_code,
            "reply":         reply,
            "audio_url":     f"/audio/{audio_filename}",
            "request_id":    request_id,
        })

    except Exception as e:
        import traceback as _tb
        print(f"\n❌ SERVER ERROR in /process_audio: {type(e).__name__}: {e}")
        print(_tb.format_exc())
        # Always return JSON — never let Flask return an HTML 500 page
        try:
            return jsonify({"success": False, "error": "Server error — please try again"}), 500
        except Exception:
            from flask import Response as _Response
            return _Response('{"success":false,"error":"Server error"}',
                             status=500, mimetype="application/json")

    finally:
        # Release the per-session concurrency lock (only if we acquired it)
        if lock_acquired:
            _release_session_lock(call_session_id)
        # Always clean up the uploaded audio
        if os.path.exists(input_path):
            try:
                os.remove(input_path)
            except Exception:
                pass


# =========================================================
# SET LANGUAGE OVERRIDE (FR-18)
# =========================================================

_VALID_LANGUAGE_OVERRIDES = {"kn", "hi", "ml", "en", "auto"}


@app.route("/set_language", methods=["POST"])
def set_language():
    """
    Accept a language override from the browser.
    Body: {"language": "kn"|"hi"|"ml"|"en"|"auto"}
    Stores in session so /process_audio skips Gemini language detection.
    """
    data = request.get_json(silent=True) or {}
    lang = data.get("language", "")

    if lang not in _VALID_LANGUAGE_OVERRIDES:
        return jsonify({"success": False, "error": f"Invalid language: {lang}"}), 400

    session["language_override"] = lang
    return jsonify({"success": True, "language": lang})


# =========================================================
# CLEANUP AUDIO AFTER PLAYBACK
# =========================================================

@app.route("/cleanup_audio", methods=["POST"])
def cleanup_audio():
    data     = request.get_json(silent=True) or {}
    filename = data.get("filename", "")
    # Prevent path traversal: use only the basename and verify the resolved
    # path stays inside AUDIO_FOLDER before deleting.
    safe_name = os.path.basename(filename)
    if safe_name.startswith("farmer_reply_") and safe_name.endswith(".mp3"):
        candidate = os.path.realpath(os.path.join(AUDIO_FOLDER, safe_name))
        allowed   = os.path.realpath(AUDIO_FOLDER)
        if candidate.startswith(allowed + os.sep) or candidate == allowed:
            try:
                os.remove(candidate)
            except Exception:
                pass
    return jsonify({"success": True})


# =========================================================
# RESET CALL
# =========================================================

@app.route("/reset_call", methods=["POST"])
def reset_call():
    reset_history()
    new_session_id = uuid.uuid4().hex
    # Clear language cache for the old session
    old_session_id = session.get("call_session_id")
    if old_session_id:
        _clear_language_cache(old_session_id)
    session["call_session_id"] = new_session_id
    db.create_session(new_session_id, channel="browser")
    return jsonify({"success": True})


# =========================================================
# SERVE AUDIO
# =========================================================

@app.route("/audio/<filename>")
def get_audio(filename):
    return send_from_directory(AUDIO_FOLDER, filename)


@app.route("/wait_audio/<lang>")
def get_wait_audio(lang):
    """Serve the pre-generated 'please wait' audio for a given language."""
    # Clamp to supported languages — default to English
    safe_lang = lang if lang in WAIT_MESSAGES else "en"
    filename   = f"wait_{safe_lang}.mp3"
    wait_path  = os.path.join(WAIT_AUDIO_DIR, filename)

    if os.path.exists(wait_path):
        return send_from_directory(WAIT_AUDIO_DIR, filename)

    # File not ready yet (still generating) — return English fallback
    en_path = os.path.join(WAIT_AUDIO_DIR, "wait_en.mp3")
    if os.path.exists(en_path):
        return send_from_directory(WAIT_AUDIO_DIR, "wait_en.mp3")

    return jsonify({"error": "wait audio not ready"}), 404


# =========================================================
# ADMIN AUTHENTICATION & DASHBOARD
# =========================================================

@app.route("/admin/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def admin_login():
    if current_user.is_authenticated:
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = verify_admin(username, password)
        if user:
            login_user(user)
            return redirect(url_for("admin_dashboard"))
        flash("Invalid credentials")
        # Return 401 so tests can assert the status code on failure
        return render_template("admin/login.html"), 401

    return render_template("admin/login.html")


@app.route("/admin/logout", methods=["POST"])
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for("admin_login"))


@app.route("/admin/dashboard")
@login_required
def admin_dashboard():
    page = request.args.get("page", 1, type=int)
    metrics = get_dashboard_data()
    history = get_interaction_history(page=page, per_page=20)
    health = service_health()
    return render_template(
        "admin/dashboard.html",
        metrics=metrics,
        history=history,
        health=health,
    )


# =========================================================
# HEALTH ENDPOINT (FR-17)
# =========================================================

@app.route("/debug/whisper_test", methods=["GET"])
def debug_whisper_test():
    """
    Quick test endpoint — runs the full pipeline steps without audio.
    Returns detailed error info so we can see what's failing on Render.
    NOT for production use — returns internal error details.
    """
    import traceback as _tb
    results = {}

    # Test 1: av import and av.open signature
    try:
        import av
        results["av_version"] = str(av.__version__)
        # Check if metadata_errors is supported
        import inspect
        try:
            sig = str(inspect.signature(av.open))
            results["av_open_sig"] = sig[:200]
        except Exception:
            results["av_open_sig"] = "cannot inspect (C extension)"
        results["av"] = "ok"
    except Exception as e:
        results["av"] = f"FAIL: {e}"

    # Test 2: faster-whisper patch
    try:
        import faster_whisper.audio as _fwa
        results["fw_decode_audio"] = str(_fwa.decode_audio)[:100]
        results["fw_patch"] = "ok"
    except Exception as e:
        results["fw_patch"] = f"FAIL: {e}"

    # Test 3: Whisper model load (lazy)
    try:
        wm = _get_whisper()
        results["whisper"] = f"loaded: {type(wm).__name__}"
    except Exception as e:
        results["whisper"] = f"FAIL: {e}\n{_tb.format_exc()}"

    # Test 4: Edge TTS
    try:
        import asyncio, edge_tts, tempfile, os as _os
        async def _tts_test():
            comm = edge_tts.Communicate("test", "en-IN-NeerjaNeural")
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                p = f.name
            await comm.save(p)
            sz = _os.path.getsize(p)
            _os.unlink(p)
            return sz
        loop = asyncio.new_event_loop()
        try:
            sz = loop.run_until_complete(_tts_test())
            results["edge_tts"] = f"ok, {sz} bytes"
        finally:
            loop.close()
    except Exception as e:
        results["edge_tts"] = f"FAIL: {e}\n{_tb.format_exc()[-500:]}"

    # Test 5: Gemini key
    results["gemini_key"] = "configured" if os.getenv("GEMINI_API_KEY") else "MISSING"

    # Test 6: UPLOAD_FOLDER writable
    try:
        test_path = os.path.join(UPLOAD_FOLDER, "_test.tmp")
        with open(test_path, "w") as f:
            f.write("test")
        os.remove(test_path)
        results["upload_folder"] = "writable"
    except Exception as e:
        results["upload_folder"] = f"FAIL: {e}"

    return jsonify(results)


@app.route("/health", methods=["GET"])
def health():
    """
    System health check.
    Returns component status without exposing env values, stack traces,
    or internal paths.
    """
    # --- DB check ---
    try:
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(str(db.DB_PATH))
        conn.execute("SELECT 1 FROM call_sessions")
        conn.close()
        db_status = "ok"
    except Exception:
        db_status = "error"

    # --- Gemini key check (presence only, never the value) ---
    gemini_key_status = (
        "configured"
        if os.environ.get("GEMINI_API_KEY", "").strip()
        else "missing"
    )

    # --- Edge TTS check ---
    try:
        import edge_tts as _edge_tts  # noqa: F401
        edge_tts_status = "ok"
    except Exception:
        edge_tts_status = "error"

    # --- Whisper check ---
    whisper_status = "loaded" if whisper_model is not None else "not_loaded_yet"

    return jsonify({
        "status":     "ok",
        "db":         db_status,
        "gemini_key": gemini_key_status,
        "edge_tts":   edge_tts_status,
        "whisper":    whisper_status,
        "timestamp":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
    })


# =========================================================
# TELEPHONY ROUTES
# TELEPHONY_PROVIDER env var controls which adapter is used:
#   "twilio"  → TwilioAdapter (requires SID + token; phone number optional)
#   anything else (default) → MockAdapter
# See docs/TELEPHONY_SETUP.md
# =========================================================

# In-process session store keyed by session_id / CallSid.
_telephony_sessions: dict = {}


def _get_telephony_provider() -> str:
    """Return the configured telephony provider name (lowercase)."""
    return os.environ.get("TELEPHONY_PROVIDER", "mock").strip().lower()


@app.route("/telephony/status", methods=["GET"])
def telephony_status():
    """Report telephony provider status (no auth required)."""
    provider = _get_telephony_provider()
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    phone_number = os.environ.get("TWILIO_PHONE_NUMBER", "")

    if provider == "twilio":
        status = "ready" if (account_sid and phone_number) else "awaiting_phone_number"
    else:
        status = "active"

    return jsonify({
        "provider": provider,
        "account_sid_configured": bool(account_sid),
        "phone_number_configured": bool(phone_number),
        "status": status,
    })


@app.route("/telephony/incoming", methods=["POST"])
def telephony_incoming():
    """
    Handle an incoming call.

    When TELEPHONY_PROVIDER=twilio:
      - Validates X-Twilio-Signature; returns 403 on failure.
      - Returns TwiML (Content-Type: text/xml).

    Otherwise (mock):
      - Accepts optional JSON body; returns JSON session_id.
    """
    provider = _get_telephony_provider()

    if provider == "twilio":
        from services.telephony.twilio_adapter import TwilioAdapter  # noqa: PLC0415

        adapter = TwilioAdapter()
        signature = request.headers.get("X-Twilio-Signature", "")
        if not adapter.verify_webhook(request.url, request.form.to_dict(), signature):
            return ("Forbidden — invalid Twilio signature", 403)

        call_data = request.form.to_dict()
        twiml = adapter.handle_incoming_call(call_data)
        call_sid = call_data.get("CallSid", "unknown")
        _telephony_sessions[call_sid] = adapter
        return app.response_class(twiml, status=200, mimetype="text/xml")

    else:
        from services.telephony.mock_adapter import MockAdapter  # noqa: PLC0415

        call_data = request.get_json(silent=True) or {}
        adapter = MockAdapter()
        session_id = adapter.handle_incoming_call(call_data)
        _telephony_sessions[session_id] = adapter
        return jsonify({
            "session_id": session_id,
            "status": "active",
            "message": "Mock call started",
        })


@app.route("/telephony/respond", methods=["POST"])
def telephony_respond():
    """
    Handle a recording callback (Twilio) or a text message (mock).

    When TELEPHONY_PROVIDER=twilio:
      - Validates X-Twilio-Signature; returns 403 on failure.
      - Expects RecordingUrl and CallSid in the POST form.
      - Runs the voice pipeline and returns TwiML.

    Otherwise (mock):
      - Request body: {"session_id": str, "message": str}
      - Returns JSON echo response.
    """
    provider = _get_telephony_provider()

    if provider == "twilio":
        from services.telephony.twilio_adapter import TwilioAdapter  # noqa: PLC0415

        signature = request.headers.get("X-Twilio-Signature", "")
        form_params = request.form.to_dict()

        # Re-use a cached adapter instance if available, else create a new one.
        call_sid = form_params.get("CallSid", "unknown")
        adapter = _telephony_sessions.get(call_sid)
        if adapter is None or not isinstance(adapter, TwilioAdapter):
            adapter = TwilioAdapter()
            _telephony_sessions[call_sid] = adapter

        if not adapter.verify_webhook(request.url, form_params, signature):
            return ("Forbidden — invalid Twilio signature", 403)

        recording_url = form_params.get("RecordingUrl", "")
        twiml = adapter.process_recording(call_sid, recording_url, call_sid)
        return app.response_class(twiml, status=200, mimetype="text/xml")

    else:
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id", "")
        message = data.get("message", "")

        if session_id not in _telephony_sessions:
            return jsonify({"error": "Unknown session_id"}), 400

        return jsonify({
            "session_id": session_id,
            "response": f"Mock response: {message}",
            "note": "Real audio pipeline pending telephony integration",
        })


# =========================================================
# REAL-TIME VOICE ROUTES (FEAT-002)
# Feature-flagged behind REALTIME_VOICE_ENABLED=true.
# All token values are treated as secrets — never logged.
# =========================================================

def _validate_rt_token(req):
    """
    Read the X-Session-Token header, validate it against _rt_sessions.

    Returns (token, session_info) on success.
    Aborts with HTTP 401 if the token is missing, unknown, or expired.
    Never logs the token value.
    """
    from flask import abort
    token = req.headers.get("X-Session-Token", "")
    if not token:
        abort(401, description="Missing X-Session-Token header")

    with _rt_sessions_lock:
        info = _rt_sessions.get(token)

    if not info:
        abort(401, description="Invalid or expired session token")

    if info.get("expires_at", datetime.now(timezone.utc)) < datetime.now(timezone.utc):
        with _rt_sessions_lock:
            _rt_sessions.pop(token, None)
        abort(401, description="Session token has expired")

    return token, info


@app.route("/realtime/session", methods=["POST"])
@limiter.limit("5 per minute")
def realtime_create_session():
    """
    Create a short-lived realtime voice session token.

    Returns 503 when REALTIME_VOICE_ENABLED != 'true'.
    Returns 200 with {session_id, expires_in, capabilities} when enabled.
    Token value is NEVER logged.
    """
    enabled = os.environ.get("REALTIME_VOICE_ENABLED", "false").strip().lower()
    if enabled != "true":
        return jsonify({
            "error":      "realtime_disabled",
            "legacy_url": "/process_audio",
        }), 503

    token      = secrets.token_urlsafe(32)
    session_id = uuid.uuid4().hex
    now        = datetime.now(timezone.utc)
    expires_at = now.__class__.fromtimestamp(
        now.timestamp() + _REALTIME_SESSION_TTL, tz=timezone.utc
    )
    client_ip = request.remote_addr or "unknown"

    with _rt_sessions_lock:
        _rt_sessions[token] = {
            "session_id":    session_id,
            "ip":            client_ip,
            "created_at":    now,
            "expires_at":    expires_at,
            "language_code": "kn",
            "cancelled":     False,
        }

    # Create a DB session record (non-fatal)
    try:
        db.create_session(session_id, channel="realtime")
    except Exception as _db_err:
        print(f"⚠️  realtime_create_session: DB record failed (non-fatal): {_db_err}")

    return jsonify({
        "session_id":  session_id,
        "token":       token,
        "expires_in":  _REALTIME_SESSION_TTL,
        "capabilities": {
            "provider":    os.environ.get("REALTIME_PROVIDER", "chunked_tts"),
            "streaming":   False,
            "barge_in":    True,
        },
    }), 200


@app.route("/realtime/audio", methods=["POST"])
def realtime_audio():
    """
    Accept audio bytes and stream back SSE events via the provider pipeline.

    Requires X-Session-Token header.
    Expects multipart form with an 'audio' field.
    Returns text/event-stream.
    """
    token, session_info = _validate_rt_token(request)
    session_id    = session_info["session_id"]
    language_code = session_info.get("language_code", "kn")

    if "audio" not in request.files:
        return jsonify({"error": "No audio field in request"}), 400

    audio_bytes = request.files["audio"].read()

    # Log to DB with status='processing' (non-fatal)
    interaction_id = uuid.uuid4().hex
    try:
        db.log_interaction(
            session_id=session_id,
            language=language_code,
            transcript="",
            intent="realtime",
            assistant_response="",
            status="processing",
            latency_dict={},
            interaction_id=interaction_id,
        )
    except Exception:
        pass

    provider = _get_rt_provider()
    if provider is None:
        return jsonify({"error": "realtime_disabled", "legacy_url": "/process_audio"}), 503

    def _sse_generator():
        final_status = "success"
        chunk_count = 0
        _MAX_AUDIO_CHUNKS = 50
        try:
            for event_dict in provider.process_audio_stream(
                audio_bytes, session_id, language_code
            ):
                # Also honour a cancel set via /realtime/cancel endpoint
                with _rt_sessions_lock:
                    cancelled = _rt_sessions.get(token, {}).get("cancelled", False)
                if cancelled:
                    provider.cancel_response(session_id)
                    yield "data: " + json.dumps({
                        "type": "error", "data": "cancelled", "turn_id": ""
                    }) + "\n\n"
                    final_status = "interrupted"
                    return

                # Audio buffer bound: cap at 50 audio_chunks per turn
                if event_dict.get("type") == "audio_chunk":
                    chunk_count += 1
                    if chunk_count > _MAX_AUDIO_CHUNKS:
                        provider.cancel_response(session_id)
                        yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                        return

                # Update language cache after transcription
                if event_dict.get("type") == "transcript":
                    detected_lang = event_dict.get("language_code")
                    if detected_lang:
                        with _rt_sessions_lock:
                            if token in _rt_sessions:
                                _rt_sessions[token]["language_code"] = detected_lang

                if event_dict.get("type") == "error":
                    final_status = "interrupted" if event_dict.get("data") == "cancelled" else "error"

                yield "data: " + json.dumps(event_dict) + "\n\n"

                if event_dict.get("type") == "done":
                    return

        except Exception as exc:
            final_status = "error"
            yield "data: " + json.dumps(
                {"type": "error", "data": str(exc), "turn_id": ""}
            ) + "\n\n"
        finally:
            # Update DB status (non-fatal)
            try:
                db.update_interaction_status(interaction_id, final_status)
            except Exception:
                pass

    return Response(
        stream_with_context(_sse_generator()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/realtime/cancel", methods=["POST"])
def realtime_cancel():
    """Cancel the active provider response for the current session."""
    token, session_info = _validate_rt_token(request)
    session_id = session_info["session_id"]

    with _rt_sessions_lock:
        if token in _rt_sessions:
            _rt_sessions[token]["cancelled"] = True

    provider = _get_rt_provider()
    if provider is not None:
        try:
            provider.cancel_response(session_id)
        except Exception:
            pass

    return jsonify({"cancelled": True}), 200


@app.route("/realtime/session", methods=["DELETE"])
def realtime_end_session():
    """End a realtime session, removing it from the token store."""
    token, session_info = _validate_rt_token(request)
    session_id = session_info["session_id"]

    with _rt_sessions_lock:
        _rt_sessions.pop(token, None)

    try:
        db.end_session(session_id)
    except Exception:
        pass

    return jsonify({"ended": True}), 200


@app.route("/realtime/config", methods=["GET"])
def realtime_config():
    """Return VAD and audio configuration from env vars. No secrets exposed."""
    from services.realtime.provider_factory import get_provider
    provider = get_provider()
    if provider is not None:
        from services.realtime.chunked_tts_provider import ChunkedTTSProvider
        from services.realtime.openai_realtime_provider import OpenAIRealtimeProvider
        if isinstance(provider, OpenAIRealtimeProvider):
            provider_name = "openai_realtime"
        else:
            provider_name = "chunked_tts"
    else:
        provider_name = "none"
    return jsonify({
        "vad_threshold":        float(os.getenv("REALTIME_VAD_THRESHOLD", "0.5")),
        "min_speech_ms":        int(os.getenv("REALTIME_VAD_MIN_SPEECH_MS", "250")),
        "min_silence_ms":       int(os.getenv("REALTIME_VAD_MIN_SILENCE_MS", "400")),
        "pre_speech_pad_ms":    int(os.getenv("REALTIME_VAD_PRE_SPEECH_PAD_MS", "100")),
        "barge_in_debounce_ms": int(os.getenv("REALTIME_BARGE_IN_DEBOUNCE_MS", "180")),
        "barge_in_cooldown_ms": int(os.getenv("REALTIME_BARGE_IN_COOLDOWN_MS", "300")),
        "provider":             provider_name,
        "streaming_honest":     False,
    })


# =========================================================
# VOICELINK WEBSOCKET BOT ROUTES (FEAT-003)
# Feature-flagged behind VOICELINK_ENABLED=true.
# VoiceLink connects TO this endpoint when a call arrives.
# Protocol: base64-encoded PCMA audio, JSON control messages.
# =========================================================

@sock.route("/integrations/voicelink/ws")
def voicelink_ws(ws):
    """WebSocket endpoint for VoiceLink bot connections.
    VoiceLink connects here when a call arrives on the configured DID.
    Protocol: base64-encoded PCMA audio, JSON control messages.
    """
    if not os.getenv("VOICELINK_ENABLED", "false").lower() == "true":
        ws.close()
        return
    from services.telephony.voicelink_adapter import VoiceLinkAdapter  # noqa: PLC0415
    adapter = VoiceLinkAdapter()
    adapter.handle_ws_connection(ws)


@app.route("/integrations/voicelink/webhook", methods=["POST"])
def voicelink_webhook():
    """Receives lifecycle events from VoiceLink (call.initiated, call.answered,
    call.ended, call.completed)."""
    payload = request.get_json(silent=True) or {}
    signature = request.headers.get("X-VoiceLink-Signature", "")
    secret = os.getenv("VOICELINK_WEBHOOK_SECRET", "")
    # Log event type only — never log full payload (may contain caller numbers)
    event_type = payload.get("event", "unknown")
    print(f"VoiceLink webhook: {event_type}")
    from services.telephony.voicelink_adapter import VoiceLinkAdapter  # noqa: PLC0415
    result = VoiceLinkAdapter.process_webhook(payload, signature, secret)
    return jsonify({"received": True, "event": event_type})


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("📞 AI FARMER HELPLINE SERVER STARTED")
    print("=" * 60)
    print("\n🌐 Open this in your browser:")
    print("http://127.0.0.1:5000")
    print("\n🎙️  Browser microphone interface ready.\n")

    app.run(
        debug=False,
        host="0.0.0.0",
        port=5000
    )
