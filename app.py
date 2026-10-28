import os
import uuid
import re
import time
import threading

from flask import (
    Flask, render_template, request, jsonify,
    send_from_directory, session, redirect, url_for, flash,
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from faster_whisper import WhisperModel
from google import genai
from google.genai import types
from dotenv import load_dotenv

from services.assistant import get_reply, reset_history
from services import location_extractor
from services import weather_service
from services import market_service
from services import scheme_service
from services.intent_service import classify_intent
from services.forecast_service import get_price_forecast, _MARKET_DATA as _FORECAST_DATA
from voice.text_to_speech import speak
from frontend.login import AdminUser, verify_admin
from frontend.dashboard import get_dashboard_data, get_interaction_history, service_health
import backend.database as db

load_dotenv()

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

# =========================================================
# ABSOLUTE PATHS
# =========================================================

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
AUDIO_FOLDER  = os.path.join(BASE_DIR, "audio")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER,  exist_ok=True)

# =========================================================
# WHISPER MODEL
# =========================================================

print("Loading Whisper medium model...")
whisper_model = WhisperModel(
    "medium",
    device="cpu",
    compute_type="int8",
    cpu_threads=4
)
print("Whisper model loaded!")

# =========================================================
# GEMINI CLIENT
# =========================================================

gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
GEMINI_MODEL  = "gemini-3.5-flash"

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
    segments, _ = whisper_model.transcribe(
        audio_path,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=400,
            speech_pad_ms=200,
        ),
        condition_on_previous_text=False,
        language=language_code,   # FORCED — no guessing
        temperature=0.0,
        no_speech_threshold=NO_SPEECH_THRESHOLD,   # noise gate
        compression_ratio_threshold=2.0,            # filter hallucinations
        log_prob_threshold=-0.8,                    # filter low-confidence output
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
    if len(cleaned) < len(text) * 0.7:
        lang_name = get_language_name(language_code)
        print(f"   🔧 Hallucination detected. Asking Gemini to reconstruct...")
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
    return render_template("index.html")


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
        # STEP 1 — Gemini identifies language from audio
        # -------------------------------------------------

        t0 = time.perf_counter()

        print("⏳ Step 1: Detecting language from audio (Gemini)...")
        language_code = detect_language_from_audio(input_path)
        language_name = get_language_name(language_code)
        print(f"   Language confirmed: {language_code} ({language_name})")

        t1 = time.perf_counter()

        # -------------------------------------------------
        # STEP 2 — Whisper transcribes with forced language + noise gate
        # -------------------------------------------------

        print(f"⏳ Step 2: Transcribing as {language_name} (Whisper)...")
        text = transcribe_with_language(input_path, language_code)
        print(f"   Raw transcription: {text[:80]}")

        t2 = time.perf_counter()

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
        print(f"\n❌ SERVER ERROR: {e}")
        return jsonify({"success": False, "error": str(e)})

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
    session["call_session_id"] = new_session_id
    db.create_session(new_session_id, channel="browser")
    return jsonify({"success": True})


# =========================================================
# SERVE AUDIO
# =========================================================

@app.route("/audio/<filename>")
def get_audio(filename):
    return send_from_directory(AUDIO_FOLDER, filename)


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

@app.route("/health", methods=["GET"])
def health():
    """
    System health check.
    Returns component status without exposing env values, stack traces,
    or internal paths.
    """
    from datetime import datetime as _datetime

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
    whisper_status = "loaded" if whisper_model is not None else "error"

    return jsonify({
        "status":     "ok",
        "db":         db_status,
        "gemini_key": gemini_key_status,
        "edge_tts":   edge_tts_status,
        "whisper":    whisper_status,
        "timestamp":  _datetime.utcnow().isoformat() + "Z",
    })


# =========================================================
# TELEPHONY ROUTES (Mock adapter — real Twilio pending credentials)
# See docs/TELEPHONY_SETUP.md
# =========================================================

@app.route("/telephony/status", methods=["GET"])
def telephony_status():
    """Report telephony provider status (no auth required)."""
    return jsonify({
        "provider": "mock",
        "status": "active",
        "note": (
            "Real telephony pending Twilio credentials — "
            "see docs/TELEPHONY_SETUP.md"
        ),
    })


@app.route("/telephony/incoming", methods=["POST"])
def telephony_incoming():
    """
    Start a new mock call session.

    Accepts optional JSON body with caller metadata.
    Returns the session_id for subsequent /telephony/respond calls.
    """
    from services.telephony.mock_adapter import MockAdapter

    call_data = request.get_json(silent=True) or {}
    adapter = MockAdapter()
    session_id = adapter.handle_incoming_call(call_data)

    # Store the adapter in app context keyed by session_id so /respond can use it.
    # We use a simple module-level dict as a lightweight in-process store.
    _telephony_sessions[session_id] = adapter

    return jsonify({
        "session_id": session_id,
        "status": "active",
        "message": "Mock call started",
    })


@app.route("/telephony/respond", methods=["POST"])
def telephony_respond():
    """
    Send a text message into a mock call session and receive an echo response.

    Request body: {"session_id": str, "message": str}
    """
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


# In-process session store for mock telephony adapter instances.
# Keyed by session_id; populated by /telephony/incoming.
_telephony_sessions: dict = {}


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
