import os
import uuid
import re
import time

from flask import Flask, render_template, request, jsonify, send_from_directory, session
from faster_whisper import WhisperModel
from google import genai
from google.genai import types
from dotenv import load_dotenv

from services.assistant import get_reply, reset_history
from voice.text_to_speech import speak
import backend.database as db

load_dotenv()

# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-insecure-key-change-in-prod")

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
        response = gemini_client.models.generate_content(
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
            response = gemini_client.models.generate_content(
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
            reconstructed = response.text.strip()
            print(f"   ✅ Reconstructed: {reconstructed}")
            return reconstructed
        except Exception as e:
            print(f"   ⚠️  Reconstruction failed: {e}")
            return cleaned

    return cleaned


# =========================================================
# HOME PAGE
# =========================================================

@app.route("/")
def home():
    return render_template("index.html")


# =========================================================
# PROCESS FARMER VOICE
# =========================================================

@app.route("/process_audio", methods=["POST"])
def process_audio():

    request_id     = uuid.uuid4().hex
    input_path     = os.path.join(UPLOAD_FOLDER, f"farmer_voice_{request_id}.webm")
    audio_filename = f"farmer_reply_{request_id}.mp3"
    audio_dest     = os.path.join(AUDIO_FOLDER, audio_filename)

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

        # Retrieve (or lazily create) the DB session for this call
        call_session_id = session.get("call_session_id")
        if not call_session_id:
            call_session_id = uuid.uuid4().hex
            session["call_session_id"] = call_session_id
            db.create_session(call_session_id, channel="browser")

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
        # GET AI REPLY
        # -------------------------------------------------

        print("⏳ Step 3: Getting AI reply (Gemini)...")
        reply_status = "success"
        error_cat = None
        try:
            reply = get_reply(text, language_code)
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
                intent="unknown",
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
    if filename.startswith("farmer_reply_") and filename.endswith(".mp3"):
        path = os.path.join(AUDIO_FOLDER, filename)
        try:
            os.remove(path)
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
