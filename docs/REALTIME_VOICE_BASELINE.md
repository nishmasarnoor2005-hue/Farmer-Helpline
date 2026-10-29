# Real-Time Voice Upgrade — Baseline Audit

**Project:** AI Farmer Helpline  
**Audit Date:** 2025  
**Auditor:** Kiro coding agent (FEAT-001)

---

## 1. Project Overview

- **Framework:** Flask (Python 3.12), vanilla JS frontend, Windows-only deployment
- **Entry point:** `app.py` (Flask app served directly via `.venv\Scripts\python.exe app.py`)
- **Frontend:** `templates/index.html` + `static/js/` (no build step)
- **Database:** SQLite at `d:\Major_Project\farmer_helpline.db`

---

## 2. Provider Assessment

### 2.1 Speech-to-Text — faster-whisper (local)

| Property | Detail |
|---|---|
| Model | `WhisperModel("small", device="cpu", compute_type="int8")` loaded once at startup in `app.py` |
| Input | Requires a **complete saved audio file** (WebM/WAV) on disk |
| Streaming | **None.** `model.transcribe()` runs on the complete file and returns when finished. No partial transcript events. |
| Latency | 3–8 seconds CPU transcription per utterance |
| Language | Auto-detected from audio; session-cached in `_session_language_cache` |
| Gap | Cannot stream partial transcripts. Full STT upgrade requires an external streaming STT API (e.g., Deepgram, Google Speech V2 streaming, AssemblyAI). |

### 2.2 Language Model — Google Gemini (`gemini-flash-lite-latest`)

| Property | Detail |
|---|---|
| Client | `genai.Client(api_key=GEMINI_API_KEY)` in `services/assistant.py` |
| Call | `client.models.generate_content(...)` — returns **complete reply** |
| Streaming | `generate_content_stream()` is available in the SDK but **not currently used** |
| Gap | Partial text streaming is achievable by switching to `generate_content_stream()` — this is planned for FEAT-003. The current pipeline waits for the full reply before TTS begins. |

### 2.3 Text-to-Speech — Microsoft Edge TTS

| Property | Detail |
|---|---|
| Library | `edge-tts` async library, called via `asyncio.run()` in `voice/text_to_speech.py` |
| Output | Saves a **complete MP3 file** per utterance (per-request UUID path in `audio/`) |
| Streaming | Edge TTS can stream audio chunks via `communicate.stream()` but the current `speak()` function uses `communicate.save()` — saves whole file first |
| Chunked TTS | **Achievable** by splitting text at sentence boundaries and calling Edge TTS per sentence — produces lower first-audio latency without requiring a different provider |
| Gap | True audio streaming (byte-level) would require a different TTS API or use of `communicate.stream()`. Sentence-chunked TTS is a pragmatic improvement within existing constraints. |
| Fallback | gTTS (Google Text-to-Speech) used if Edge TTS fails |

### 2.4 OpenAI Realtime API

| Property | Detail |
|---|---|
| Status | **BLOCKED_PENDING_CREDENTIALS** |
| Description | OpenAI Realtime API provides true full-duplex speech-to-speech over WebRTC/WebSocket with low latency, barge-in support, and server-side VAD |
| Requirement | Valid `OPENAI_API_KEY` with Realtime API access entitlement |
| Current state | No `OPENAI_API_KEY` is set in `.env.example` or the environment |
| Plan | `OpenAIRealtimeProvider` stub created in `services/realtime/openai_realtime_provider.py`; methods raise `NotImplementedError('BLOCKED_PENDING_CREDENTIALS')` until credentials are provisioned |

---

## 3. Streaming Gaps

| Capability | Current State | Gap | Path Forward |
|---|---|---|---|
| Streaming STT | ❌ None — full file required | Full latency before any transcript | External streaming STT API or Whisper streaming mode |
| Streaming LLM text | ❌ Full reply waited | First-token latency = full generation time | Switch to `generate_content_stream()` (FEAT-003) |
| Streaming / chunked TTS | ❌ Full MP3 per call | All TTS audio buffered before playback | Sentence-chunked Edge TTS (FEAT-002/003) |
| True full-duplex | ❌ BLOCKED | Requires OpenAI Realtime or equivalent | Awaiting credentials (FEAT-004) |
| Barge-in | ❌ None | Assistant cannot be interrupted mid-speech | VAD + state machine (FEAT-002) |
| WebRTC transport | ❌ Not implemented | Browser uses HTTP file upload | FEAT-003/004 |

---

## 4. Existing Environment Variables (from `.env.example`)

Names only — never values:

- `GEMINI_API_KEY`
- `FLASK_SECRET_KEY`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD_HASH`
- `FLASK_DEBUG`
- `RATE_LIMIT_PROCESS`
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER`
- `TELEPHONY_PROVIDER`
- `DATA_GOV_IN_API_KEY`

---

## 5. Existing Routes (must be preserved)

- `POST /process_audio` — main voice processing pipeline
- `POST /reset_call` — reset conversation history
- `GET /cleanup_audio` — delete per-session audio files
- `POST /set_language` — explicit language override
- `GET/POST /admin/login`, `/admin/logout`, `/admin/dashboard`
- `GET /health` — health check
- `GET/POST /telephony/*` — Twilio/mock IVR routes

---

## 6. Existing Voice Pipeline

```
Browser (mic) → WebM upload → /process_audio
  → faster-whisper STT (complete file, 3–8s)
  → Gemini language detection (first request only, cached)
  → Gemini get_reply() (complete response)
  → Edge TTS speak() → MP3 saved to audio/
  → JSON response with audio_url
  → Browser plays MP3
```

No streaming. No barge-in. No WebRTC.

---

## 7. Existing Architecture Patterns

- Rate limiting via `flask_limiter` (`@limiter.limit()`)
- Per-session locks: `_session_locks` dict + `_locks_mutex`
- DB calls non-fatal: wrapped in `try/except`, log warning
- Gemini calls wrapped in `_gemini_with_retry()`
- Language cached in `_session_language_cache` dict
- Audio files: per-request UUIDs in `audio/`, cleaned by `/cleanup_audio`
- Background threads: `threading.Thread(daemon=True)`
- asyncio: `asyncio.run()` used inside sync Flask routes; must use `asyncio.new_event_loop()` in helpers to avoid nesting

---

## 8. Baseline Test Count

**119 passed, 0 failed** (measured against `tests/` directory, pytest 9.2.0)

Test files:
- `tests/test_auth.py`
- `tests/test_database.py`
- `tests/test_voice_pipeline.py`
- Additional test files for existing features

---

## 9. Feature Flag

The real-time voice mode will be gated by `REALTIME_VOICE_ENABLED=false` (default).  
The existing Whisper/Gemini/Edge TTS pipeline remains active and unmodified when the flag is false.

---

## 10. Known Limitations / Honest Assessment

1. **No true streaming** is available with the current provider set. The "chunked TTS" approach described in FEAT-002 reduces perceived latency but is not true streaming.
2. **OpenAI Realtime** is the only provider assessed that supports genuine full-duplex speech conversation — it is blocked pending credentials.
3. **Silero VAD** will run in the browser (WebAssembly/ONNX) or backend depending on final architecture — see FEAT-002.
4. **PSTN calls** via Twilio remain separate from the browser WebRTC flow; the mock telephony adapter is preserved.
5. **Windows-only** deployment constraint means Linux-specific asyncio behavior differences must not be assumed.
