# Baseline Audit — AI Farmer Helpline
**Date**: M0 audit pass  
**Workspace**: `d:\Major_Project`  
**Python venv**: `d:\Major_Project\.venv\Scripts\python.exe`

---

## 1. Working Components

| Component | File | Evidence |
|-----------|------|----------|
| Flask web server | `app.py` | Fully implemented; renders `templates/index.html`, serves `/process_audio`, `/audio/<filename>`, `/cleanup_audio`, `/reset_call` |
| Voice pipeline (Flask path) | `app.py` | Gemini audio-based language detection → Whisper forced-language transcription → Gemini AI reply → Edge TTS → MP3 served via `/audio/` |
| Gemini AI assistant | `services/assistant.py` | Uses `google-genai` SDK with rolling conversation history (MAX_HISTORY=6 turns), multi-language fallback responses, `reset_history()` |
| Edge TTS (primary) | `voice/text_to_speech.py` | `speak()` uses `edge_tts` with a per-request `output_path` parameter; falls back to gTTS on failure; supports 8 language codes + full-name aliases |
| gTTS (fallback) | `voice/text_to_speech.py` | Fallback inside `speak()` if Edge TTS fails |
| Weather service | `services/weather_service.py` | Calls Open-Meteo API (no key required); returns `{temperature, wind}` for lat/lon |
| Phone-call UI | `templates/index.html` | Full JS state machine: start call → record → send → display reply → play audio → auto-listen loop; waveform animation; language badge |
| Per-request audio | `app.py` | UUIDs per request (`farmer_reply_{uuid}.mp3`); `/cleanup_audio` deletes file after browser playback |
| Conversation memory | `services/assistant.py` | Rolling `_history` list of last 6 turns, injected into every Gemini prompt |
| Hallucination cleaner | `app.py` | Regex strips repeated Unicode clusters (Kannada virama etc.); Gemini reconstructs badly-corrupted text |
| Noise gate | `app.py` | `no_speech_threshold=0.6`, `log_prob_threshold=-0.8`, `compression_ratio_threshold=2.0` on Whisper segments |
| Language detection | `app.py` | Gemini receives raw WebM audio bytes and returns one word from a fixed list; maps to ISO code |
| Cloudflare tunnel support | `cloudflared.exe` present | Binary exists; used manually for mobile access over internet |
| SQLite schema (farmers) | `database/farmer.db` | `backend/database.py` creates `farmers` table on import (0 rows) |
| SQLite schema (helpline) | `farmer_helpline.db` | Two tables: `farmers` (0 rows) + `queries` (0 rows) — correct design, unpopulated |
| CSV seed data | `farmers.csv` | 4 data rows; columns: Name, Mobile, Location, Language, Crop |
| Backup working extractor | `backup_working/services/location_extractor.py` | Full geopy Nominatim implementation with Kannada suffix cleaning, stop-words, typo map |
| Standalone mic test | `voice/speech_to_text.py` | Works independently; 8-second fixed-duration recording with Whisper `base` model |
| language_detect module | `voice/language_detect.py` | `langdetect`-based wrapper; functional but unused by main pipeline |
| Streamlit WebRTC stub | `webrtc_call_app.py` | Receives audio frames and prints shape; no AI processing |
| Streamlit local demo | `local_call_app.py` | mic → STT → location → weather → hardcoded multilingual reply → TTS; functional if location extractor is fixed |
| Terminal call loop | `continuous_call.py` | sounddevice mic → Whisper large-v3 → `get_reply()` → `speak()`; mostly functional (see bugs) |

---

## 2. Broken / Empty / Incomplete Components

| Component | File | Problem |
|-----------|------|---------|
| **Location extractor (active)** | `services/location_extractor.py` | **NameError at runtime**: calls `geolocator.geocode()` but never imports `geopy` or defines `geolocator`. The working implementation is in `backup_working/services/location_extractor.py`. |
| **Login page** | `frontend/login.py` | **Empty file** (0 bytes). No Streamlit or Flask login UI exists. |
| **Dashboard** | `frontend/dashboard.py` | **Empty file** (0 bytes). No admin or farmer dashboard implemented. |
| **Database writes** | `app.py`, all entry points | Neither `farmer_helpline.db` nor `database/farmer.db` are ever written to. `INSERT` statements are absent from all code paths. Conversation logs are not persisted. |
| **continuous_call.py audio bug** | `continuous_call.py` | Line `audio = sf.blocks` assigns the `soundfile.blocks` function object, not any audio data. This variable is never used (recording works via `audio_parts`), but it is dead/confusing code. |
| **continuous_call.py language lock** | `continuous_call.py` | `language="kn"` is hardcoded in the `model.transcribe()` call — only Kannada is transcribed regardless of what the farmer speaks. |
| **Whisper model size inconsistency** | Multiple | `app.py` uses `"medium"`, `continuous_call.py` uses `"large-v3"`, `voice/speech_to_text.py` uses `"base"`. No single consistent choice. |
| **Gemini model name questionable** | `app.py`, `services/assistant.py` | Both reference `"gemini-3.5-flash"`. As of audit date this model ID is unverified; the current production name is `"gemini-1.5-flash"` or `"gemini-2.0-flash"`. Will fail if the model name is wrong. |
| **weather/location not wired to Flask UI** | `app.py` | Weather and location services exist (`weather_service.py`, `location_extractor.py`) but are never called from `app.py`. The main web UI never provides location-aware weather advice. |
| **`local_call_app.py` — language passed wrong to speak()** | `local_call_app.py` | Calls `speak(reply, "English")` with a full name string, but the reply language is `lang` (ISO code). If the farmer speaks Kannada, the reply is generated in Kannada but TTS is called as "English". |
| **asyncio.run double-nesting risk** | `app.py` | `speak()` is synchronous (returns `str | None`); the `if asyncio.iscoroutine(result): asyncio.run(result)` guard is dead code, but calling `asyncio.run()` from inside an existing event loop (e.g., if served by an async server) would raise a RuntimeError. |
| **requirements.txt stale** | `requirements.txt` | Declared: `flask, faster-whisper, google-genai, edge-tts, gTTS, python-dotenv, sounddevice, soundfile, geopy, langdetect, streamlit, streamlit-webrtc, pandas, requests`. Missing from declared but needed: none critical now. However `google-genai` package name may need to be `google-generativeai` depending on SDK version. `streamlit-webrtc` requires `av` which is not listed. |
| **Stray root files** | project root | `cd`, `1`, `python_files_short.txt`, `tree.txt`, `voice.wav`, `converted_audio.wav`, `farmer_voice.wav`, `tts_test.mp3`, `farmer_reply.mp3`, `farmer_response.mp3` are leftover development artifacts. |
| **No authentication** | entire app | No login, session tokens, or rate limiting on any endpoint. |
| **No rate limiting** | `app.py` | `/process_audio` has no request rate limit — unlimited Gemini API calls possible. |

---

## 3. Database Schema (As-Found)

### `farmer_helpline.db` (root-level)

```sql
CREATE TABLE farmers (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT,
    mobile   TEXT,
    location TEXT,
    language TEXT,
    crop     TEXT
);

CREATE TABLE queries (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    question  TEXT,
    response  TEXT,
    date_time TEXT
);
```

**Row counts**: `farmers` — 0 rows, `queries` — 0 rows  
**Status**: Schema is correct and ready for use. Never written to.

---

### `database/farmer.db` (created by `backend/database.py`)

```sql
CREATE TABLE farmers (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT,
    phone    TEXT,
    state    TEXT,
    district TEXT,
    language TEXT
);
```

**Row counts**: `farmers` — 0 rows  
**Status**: Created on `import backend.database`. Schema differs from `farmer_helpline.db` (uses `phone` instead of `mobile`, no `crop`, no `queries` table). Never written to.

---

## 4. Environment Variables Referenced

Only **one** environment variable is used across the entire codebase:

| Variable Name | Files That Reference It | Purpose |
|--------------|------------------------|---------|
| `GEMINI_API_KEY` | `app.py`, `services/assistant.py` | Google Gemini API authentication |

Both files call `load_dotenv()` and then `os.getenv("GEMINI_API_KEY")`. The `.env` file exists and contains this key. No other environment variables are referenced anywhere in the project code.

---

## 5. Known Bugs

1. **`services/location_extractor.py` — `NameError: geolocator`**  
   Missing `from geopy.geocoders import Nominatim` and `geolocator = Nominatim(...)`. Crashes on any call to `extract_location()`. Fix: replace with the backup at `backup_working/services/location_extractor.py`.

2. **`services/assistant.py` — unverified Gemini model ID**  
   `MODEL = "gemini-3.5-flash"` — this model name does not match any known released Gemini model. Likely should be `"gemini-1.5-flash"` or `"gemini-2.0-flash"`. Will raise an API error at runtime.

3. **`app.py` — same Gemini model issue**  
   `GEMINI_MODEL = "gemini-3.5-flash"` — same problem as above.

4. **`continuous_call.py` — dead assignment `audio = sf.blocks`**  
   `sf.blocks` is a soundfile function object. This line has no effect because recording uses `audio_parts` list directly, but it is misleading dead code.

5. **`continuous_call.py` — Kannada-only transcription**  
   `language="kn"` hardcoded in `model.transcribe()`. Non-Kannada speech will be incorrectly transcribed.

6. **`local_call_app.py` — TTS language mismatch**  
   `speak(reply, "English")` is hardcoded on the last line, regardless of the detected `lang` variable. Farmers speaking in non-English languages get correct text but English voice output.

7. **Race condition on audio (historical, now fixed)**  
   Older versions overwrote a single `farmer_reply.mp3`. Current `app.py` uses UUIDs per request — this is now fixed in the Flask app. Still present in `local_call_app.py` and `continuous_call.py`.

8. **No database persistence**  
   Zero `INSERT` statements exist across the codebase. All conversation data is lost on restart.

---

## 6. farmers.csv

- **Path**: `d:\Major_Project\farmers.csv`
- **Total lines**: 5 (1 header + 4 data rows)
- **Columns**: `Name`, `Mobile`, `Location`, `Language`, `Crop`
- **Sample rows**:
  - Ramesh, 9876543210, Mysore, Kannada, Tomato
  - rishma, 9480547092, manglore, Malayalam, wheat
  - Rishma, 9480547092, manglore, Malayalam, onion *(duplicate mobile, different crop)*
  - nidha, 8245075648, Mudigere, Kannada, carrot
- **Notes**: Duplicate entry for "rishma/Rishma" (same mobile number, different case, different crop). No validation exists.

---

## 7. Voice Pipeline Data Flow

### Primary Path: Flask app (`app.py`)

```
1. Browser (index.html)
   └── getUserMedia() → microphone access granted
   └── MediaRecorder() → audio/webm chunks collected
   └── On stop → Blob assembled → POST /process_audio (multipart)

2. Flask /process_audio
   ├── Save WebM to uploads/farmer_voice_{uuid}.webm
   │
   ├── STEP 1 — Language Detection (Gemini)
   │   ├── Read raw audio bytes from .webm file
   │   ├── Send to Gemini as inline audio Part (mime: audio/webm)
   │   ├── Prompt: "Reply with ONE word: Kannada/English/Hindi/..."
   │   ├── Parse response → map to ISO code (kn/en/hi/...)
   │   └── Fallback: "kn" (Kannada) if detection fails
   │
   ├── STEP 2 — Transcription (faster-whisper medium model)
   │   ├── WhisperModel.transcribe(path, language=<forced ISO code>)
   │   ├── VAD filter enabled (min_silence=400ms, pad=200ms)
   │   ├── Noise gate: skip segments with no_speech_prob > 0.6
   │   ├── Hallucination cleaner: regex strip repeated chars
   │   └── If heavily corrupted → Gemini reconstructs sentence
   │
   ├── STEP 3 — AI Reply (services/assistant.py → Gemini)
   │   ├── Build prompt: SYSTEM_PROMPT + last 6 turns + farmer text
   │   ├── Call Gemini (gemini-3.5-flash*) temperature=0.4, max_tokens=300
   │   ├── Save turn to rolling _history list
   │   └── Fallback: language-specific "sorry, try again" message
   │
   ├── STEP 4 — Text-to-Speech (voice/text_to_speech.py)
   │   ├── speak(reply, language_code, output_path=audio/farmer_reply_{uuid}.mp3)
   │   ├── VOICE_MAP[lang] → Edge TTS neural voice name
   │   ├── edge_tts.Communicate(text, voice).save(path) [async, wrapped in asyncio.run]
   │   └── Fallback: gTTS if Edge TTS fails
   │
   ├── Delete uploads/farmer_voice_{uuid}.webm (finally block)
   └── Return JSON: {success, text, language, language_code, reply, audio_url}

3. Browser receives JSON
   ├── Display farmer text bubble (blue)
   ├── Display AI reply bubble (green)
   ├── new Audio("/audio/farmer_reply_{uuid}.mp3?t=<timestamp>").play()
   ├── On audio.onended → POST /cleanup_audio {filename} → server deletes MP3
   └── If auto-listen ON → setTimeout 600ms → startRecording() again
```

*Note: `gemini-3.5-flash` model name is unverified — likely a bug.*

### Secondary Path: Streamlit local demo (`local_call_app.py`)

```
Button click → speech_to_text() [voice/speech_to_text.py, standalone]
    → extract_location(text) [services/location_extractor.py — BROKEN]
    → get_weather(lat, lon) [services/weather_service.py]
    → Hardcoded multilingual template reply (no Gemini call)
    → speak(reply, "English") [WRONG — always English voice]
    → st.audio("farmer_reply.mp3")
```

### Tertiary Path: Terminal loop (`continuous_call.py`)

```
sounddevice InputStream (device=9, 48kHz)
    → VAD via volume threshold (0.015 RMS)
    → sf.write(temp_call.wav)
    → WhisperModel.transcribe(wav, language="kn") [HARDCODED Kannada]
    → get_reply(text, "kn") [services/assistant.py]
    → speak(reply, language_code) [voice/text_to_speech.py]
    → os.remove(temp_call.wav)
    → loop (until goodbye keywords detected)
```

---

## 8. Summary: Milestone Readiness

| Feature | Status |
|---------|--------|
| Flask server running | ✅ Working |
| Voice STT (Whisper) | ✅ Working (medium model, CPU int8) |
| Language detection (Gemini audio) | ✅ Implemented — pending Gemini model name fix |
| AI reply (Gemini) | ✅ Implemented — pending Gemini model name fix |
| Edge TTS with fallback | ✅ Working |
| Per-request audio (no race condition) | ✅ Fixed in app.py |
| Conversation history | ✅ Rolling 6-turn history |
| SQLite schema | ✅ Exists, 0 rows |
| Database writes | ❌ No INSERT calls anywhere |
| Authentication / login | ❌ Empty files |
| Dashboard | ❌ Empty files |
| Rate limiting | ❌ Not implemented |
| Location extractor (active) | ❌ NameError — broken |
| Weather in Flask UI | ❌ Not wired |
| Market price data | ❌ Not implemented |
| Government schemes catalogue | ❌ Not implemented |
| Telephony adapter | ❌ Not implemented |
| Test suite | ❌ Only a trivial `test_app.py` (Streamlit hello-world) |
