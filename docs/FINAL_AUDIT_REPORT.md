# Final Production-Readiness Audit Report
**Project:** Intelligent IVR-Based Farmer Helpline Using Speech Recognition and Generative AI  
**Date:** 2026-10-14  
**Auditor:** Kiro (read-only + one bug-fix pass)  
**Git HEAD after audit:** 337bd27

---

## Quick Summary Table

| Item | Value |
|---|---|
| Framework | **Flask 3.1.3** (not FastAPI) |
| WebSocket library | **flask-sock 0.7.0** + simple-websocket 1.1.0 |
| Server start command | `.venv\Scripts\python.exe app.py` |
| Port | **5000** (`host="0.0.0.0", port=5000`) |
| WebSocket route | `wss://.../integrations/voicelink/ws` (`@sock.route`) |
| Webhook route | `POST /integrations/voicelink/webhook` (`@app.route`) |
| Audio inbound format | base64-encoded G.711 A-law (PCMA), 8-bit, 8 kHz, mono |
| Audio outbound format | base64-encoded G.711 A-law (PCMA), 8-bit, 8 kHz, mono |
| PCMA conversion | `voice/pcma_utils.py` — pydub + audioop |
| Language detection | Whisper `info.language` on VoiceLink path; Gemini audio on browser path |
| Tests passing | **232 / 232** |
| Tests failing | **0** |
| Real call tested | **NO** — mocked tests only |
| VoiceLink account provisioned | **UNKNOWN** — requires user action |

---

## A. Framework

**Confirmed: Flask 3.1.3**

- `app.py` line 22: `from flask import Flask, ...`
- `app.py` line 26: `from flask_sock import Sock`
- `app.py` line 97: `sock = Sock(app)`
- Server start: `app.run(debug=False, host="0.0.0.0", port=5000)` at bottom of `app.py`
- No FastAPI, Starlette, or uvicorn anywhere in the codebase
- WebSocket routes use `@sock.route(...)` (flask-sock), NOT `@app.route(...)` — correct for WebSocket

**WebSocket implementation is correctly matched to Flask via flask-sock. ✅**

---

## B. VoiceLink Connection

### Routes
| Route | Type | Guard | Status |
|---|---|---|---|
| `/integrations/voicelink/ws` | `@sock.route` (WebSocket) | `VOICELINK_ENABLED=true` | ✅ Correct |
| `/integrations/voicelink/webhook` | `@app.route POST` (HTTP) | None (open) | ✅ Acceptable |

### Feature flag
- `app.py:1445`: `if not os.getenv("VOICELINK_ENABLED", "false").lower() == "true": ws.close(); return`
- When disabled, connection is immediately closed. ✅

### Event handling (voicelink_adapter.py)

| Event | Handled | Notes |
|---|---|---|
| `connected` | ✅ | Logs protocol/version |
| `start` | ✅ | Captures `stream_sid`, `call_sid`, creates DB session |
| `media` | ✅ | Accumulates PCMA chunks, runs VAD, triggers pipeline |
| `mark` | ✅ | Logged at DEBUG level |
| `clear` | ✅ | Flushes buffer |
| `transfer` | ✅ | Logged, no action (acceptable) |
| `stop` | ✅ | Ends DB session, breaks loop |

### Outbound events sent to VoiceLink

| Event | Method | Format | Status |
|---|---|---|---|
| `media` | `_send_media()` | `{event, streamSid, media: {payload: base64}}` | ✅ Matches spec |
| `mark` | `_send_mark()` | `{event, streamSid, mark: {name: str}}` | ✅ Matches spec |
| `clear` | `_send_clear()` | `{event, streamSid}` | ✅ Matches spec |

### Webhook authentication
- HMAC-SHA256 signature verification implemented when `VOICELINK_WEBHOOK_SECRET` is set
- Uses `hmac.new(secret, json.dumps(payload), sha256).hexdigest()` — **verified working** ✅
- Falls through safely (returns `ok: True`) when secret is empty
- **NOTE**: VoiceLink API spec does not document the exact signature header name or algorithm. The implementation uses `X-VoiceLink-Signature` header and SHA256 HMAC. **Confirm with VoiceLink support that this matches their actual webhook signature scheme before relying on it.**

### streamSid capture
- `_on_start()` reads `stream_sid` from `msg.get("streamSid", start.get("streamSid", ""))` ✅
- All outbound events correctly include `streamSid` ✅

---

## C. Audio and AI Pipeline

### Complete path: Inbound PCMA → Reply PCMA

```
VoiceLink → PCMA b64 chunks → _on_media() accumulates buffer
    → VAD triggers _run_pipeline() in background thread
    → Step 1: play wait audio (kn-IN-SapnaNeural "ಒಂದು ಕ್ಷಣ...")
    → Step 2: audioop.alaw2lin(raw_pcma, 2) → 16-bit PCM
    → Step 3: pcm_bytes_to_wav() → WAV file → Whisper.transcribe()
    → Language: Whisper info.language → clamped to SUPPORTED_CODES (default "kn")
    → Step 4: get_reply(transcript, detected_lang) → Gemini/OpenRouter text
    → Step 5: speak(reply, detected_lang) → Edge TTS → MP3 bytes
    → Step 6: mp3_bytes_to_pcma_b64(mp3_bytes) → base64 PCMA
    → _send_clear() + _send_media(pcma_b64) + _send_mark("reply_end")
    → VoiceLink plays audio to caller
```

### pcma_utils.py functions
| Function | Status | Notes |
|---|---|---|
| `mp3_bytes_to_pcma_b64(mp3_bytes)` | ✅ | pydub → 8kHz mono 16-bit → audioop.lin2alaw → b64 |
| `pcma_b64_to_pcm_bytes(b64)` | ✅ | b64 decode → audioop.alaw2lin → 16-bit PCM |
| `pcm_bytes_to_wav(pcm_bytes, sr=8000)` | ✅ | stdlib wave module, correct RIFF header |
| `SAMPLE_RATE = 8000` | ✅ | Matches VoiceLink 8 kHz spec |
| `CHANNELS = 1` | ✅ | Mono |
| `SAMPLE_WIDTH = 2` | ✅ | 16-bit |

### Whisper input
- WAV at 8000 Hz, 16-bit, mono
- **WARNING**: Whisper's native sample rate is **16 kHz**. Feeding 8 kHz audio will work (Whisper resamples internally) but may slightly reduce accuracy compared to 16 kHz input. This is unavoidable with VoiceLink's 8 kHz PCMA format.
- `word_timestamps=False`, `beam_size=5`, `vad_filter=True` ✅

### Language detection on VoiceLink path
- After this audit's fix: uses `info.language` from Whisper's transcription
- Clamped to `SUPPORTED_CODES` (kn, en, hi, ml, ta, te, mr, ur); defaults to "kn"
- **NOT using Gemini audio detection** — that requires the original WebM file (not available on the VoiceLink path where we receive PCMA). Whisper's language detection at 8 kHz is less accurate than Gemini on the browser path. This is a known limitation.
- Wait audio defaults to Kannada (`kn`) on first turn ✅

### VAD (silence detection)
- `audioop.rms(pcma_chunk, 1)` — RMS energy on 8-bit PCMA samples ✅
- Triggers after `VOICELINK_VAD_SILENCE_CHUNKS` (default 20) consecutive silent chunks
- Also triggers after `VOICELINK_MAX_BUFFER_CHUNKS` (default 200) total chunks
- At 8 kHz, ~160 bytes/chunk = 20ms per chunk → 20 silent chunks ≈ 400ms silence ✅
- Prevents double-processing: `_processing` flag blocks new pipeline while one runs ✅

### Multilingual support status
| Language | Code | Edge TTS Voice | Whisper | Tested (mocked) | Tested (real call) |
|---|---|---|---|---|---|
| Kannada | kn | kn-IN-SapnaNeural | ✅ | ✅ | ❌ Not tested |
| Hindi | hi | hi-IN-SwaraNeural | ✅ | ✅ | ❌ Not tested |
| Malayalam | ml | ml-IN-SobhanaNeural | ✅ | ✅ | ❌ Not tested |
| English | en | en-IN-NeerjaNeural | ✅ | ✅ | ❌ Not tested |
| Tamil | ta | ta-IN-PallaviNeural | ✅ | ✅ | ❌ Not tested |
| Telugu | te | te-IN-ShrutiNeural | ✅ | ✅ | ❌ Not tested |
| Marathi | mr | mr-IN-AarohiNeural | ✅ | ✅ | ❌ Not tested |
| Urdu | ur | ur-PK-UzmaNeural | ✅ | ✅ | ❌ Not tested |

**No language has been tested with a real telephone call. Do not claim multilingual support is production-verified.**

---

## D. Security

| Check | Result |
|---|---|
| `VOICELINK_ENABLED` guards WebSocket route | ✅ |
| `.env.example` has only placeholder values | ✅ — all `your_*` placeholders |
| No credentials hardcoded in any .py file | ✅ confirmed |
| `access_token` never logged | ✅ — voicelink_api.py logs key names only |
| Caller phone numbers not logged | ✅ — "callSid redacted" in webhook handler |
| Transcripts not logged | ✅ — only `len(transcript)` logged |
| Session cleanup on `stop` event | ✅ — `db.end_session()` called |
| Session cleanup on unexpected disconnect | ✅ — `finally: self._cleanup()` in handle_ws_connection |
| Exception in pipeline doesn't crash WebSocket loop | ✅ — pipeline runs in daemon thread, exceptions caught |
| DB errors are non-fatal | ✅ — all wrapped in try/except with warning log |
| Webhook HMAC verification | ✅ — when `VOICELINK_WEBHOOK_SECRET` is set |
| `_processing` flag prevents concurrent pipelines | ✅ |
| `audioop` deprecation warning | ⚠️ INFO — deprecated in Python 3.13, works on 3.12 |

---

## E. Testing

### Test results (run immediately before this report)
```
232 passed, 2 warnings in 66.63s
```
Warnings: `audioop` deprecation (Python 3.12 only warning, not an error).

### Test files and counts
| File | Tests | Coverage |
|---|---|---|
| test_auth.py | 7 | Admin login/logout/session |
| test_barge_in.py | 5 | WebSocket barge-in cancellation |
| test_database.py | 9 | SQLite schema, writes, injection safety |
| test_forecast.py | 12 | Price statistics |
| test_health.py | 13 | /health endpoint |
| test_intent.py | 11 | Intent classifier |
| test_location.py | 4 | Location extraction |
| test_market_schemes.py | 17 | Market CSV, scheme catalogue |
| test_openrouter_provider.py | 19 | OpenRouter adapter |
| test_pcma_utils.py | 11 | PCMA conversion functions |
| test_rate_limit.py | 2 | Rate limiting |
| test_realtime_config.py | 5 | VAD config endpoint |
| test_realtime_provider.py | 22 | Provider factory, ChunkedTTS |
| test_realtime_routes.py | 20 | /realtime/* routes |
| test_realtime_streaming.py | 6 | SSE streaming generator |
| test_telephony.py | 16 | Mock/Twilio adapter |
| test_voice_pipeline.py | 5 | /process_audio pipeline |
| test_voicelink_adapter.py | 11 | VoiceLink WebSocket adapter |
| test_voicelink_api.py | 14 | VoiceLink REST API client |
| test_weather.py | 4 | Weather service |

### What VoiceLink tests DO cover
- Connected/start/media/stop event handling
- Buffer accumulation and streamSid capture
- Invalid JSON does not crash handler
- Outbound media JSON format matches VoiceLink spec
- Webhook HMAC signature rejection
- Feature flag closes connection immediately
- PCMA roundtrip (encode + decode)
- API client: login, create bot, create routing, setup flow

### What VoiceLink tests do NOT cover
- Real VoiceLink server connection
- Actual PCMA audio from a real phone call
- Real Whisper transcription of telephone audio (8 kHz)
- Real Edge TTS → PCMA conversion at scale
- Multi-turn conversation continuity over VoiceLink
- Network interruption / reconnection
- Caller hang-up mid-pipeline
- Concurrent calls (two callers simultaneously)

---

## F. Issues Found

### BLOCKER (fixed in this audit)
| # | Issue | File | Fix Applied |
|---|---|---|---|
| 1 | Language hardcoded to `"en"` — reply and TTS always used English regardless of farmer's language | `voicelink_adapter.py:409,446` | ✅ Fixed — now uses `detected_lang` from Whisper |

### WARNING (not blocking but affects production quality)
| # | Issue | Severity | Notes |
|---|---|---|---|
| 2 | Whisper receives 8 kHz audio; its optimal input is 16 kHz | WARNING | VoiceLink only provides 8 kHz PCMA. Whisper resamples internally but accuracy may be lower than browser path. Cannot be fixed without VoiceLink providing 16 kHz option. |
| 3 | Language detection on VoiceLink path uses Whisper only (not Gemini audio detection) | WARNING | Gemini audio detection requires WebM; VoiceLink delivers PCMA. First-turn language may misdetect on short utterances. Default "kn" is appropriate for target audience. |
| 4 | Webhook signature algorithm not confirmed with VoiceLink | WARNING | Uses `X-VoiceLink-Signature` header + SHA256 HMAC. VoiceLink spec does not document their webhook signature scheme. Verify before relying on signature validation. |
| 5 | `setup_voicelink_bot()` uses `VOICELINK_PHONE_NUMBER` as `did_id` integer | WARNING | Phone number and DID ID are different values in VoiceLink. User must find their DID ID from `GET /reseller/did/purchased`, not use the phone number directly. |
| 6 | `get_call_details()` uses `/calls/{call_id}` endpoint | WARNING | VoiceLink spec shows this as `GET /call-log/details?call_id=...`. The URL path in the code is incorrect. Low impact (informational only). |

### INFO
| # | Issue | Notes |
|---|---|---|
| 7 | `audioop` deprecated in Python 3.13 | Works on 3.12. Plan migration to `pydub` or `scipy` before upgrading Python. |
| 8 | `pydub` requires `ffmpeg` for MP3 decoding | `ffmpeg` must be installed on the server. Already works locally. Document in VOICELINK_SETUP.md. |
| 9 | Wait audio is always Kannada on first turn | After language detection, subsequent turns use correct language. First turn is always Kannada "ಒಂದು ಕ್ಷಣ..." — acceptable for primary audience. |
| 10 | No rate limiting on `/integrations/voicelink/webhook` | VoiceLink is the only expected caller. Low risk but worth adding `@limiter.limit("60 per minute")`. |

---

## G. Next Steps for Real Call Test

Complete these steps in order:

1. **Fix `setup_voicelink_bot()`** — change `VOICELINK_PHONE_NUMBER` to `VOICELINK_DID_ID` (the integer DID ID, not the phone number string). Find your DID ID from the VoiceLink portal.

2. **Set `.env`:**
   ```
   VOICELINK_ENABLED=true
   VOICELINK_USERNAME=your_username
   VOICELINK_PASSWORD=your_password
   VOICELINK_DID_ID=<integer from portal>
   VOICELINK_BOT_WEBSOCKET_URL=wss://your-tunnel/integrations/voicelink/ws
   VOICELINK_BOT_WEBHOOK_URL=https://your-tunnel/integrations/voicelink/webhook
   VOICELINK_WEBHOOK_SECRET=choose-a-secret-and-set-in-portal-too
   ```

3. **Start server:**
   ```
   cd d:\Major_Project
   .venv\Scripts\python.exe app.py
   ```

4. **Start tunnel (second terminal):**
   ```
   cd d:\Major_Project
   .\cloudflared.exe tunnel --url http://localhost:5000
   ```

5. **Provision bot (one-time):**
   ```
   .venv\Scripts\python.exe -c "
   from dotenv import load_dotenv; load_dotenv(override=True)
   from services.voicelink_api import setup_voicelink_bot
   result = setup_voicelink_bot()
   print('Bot ID:', result['bot_id'])
   print('Routing ID:', result['routing_id'])
   "
   ```

6. **Make a test call** from any phone to your VoiceLink DID number.

7. **Verify in server logs:**
   - `VoiceLink WebSocket connection opened`
   - `VoiceLink: call started (stream_sid=... session=...)`
   - `VoiceLink: transcribed (len=N)`
   - `VoiceLink WebSocket connection closed`

8. **Verify in SQLite** — call session and interaction should appear:
   ```
   .venv\Scripts\python.exe -c "
   import sqlite3
   conn = sqlite3.connect('farmer_helpline.db')
   print(conn.execute('SELECT channel, language, status FROM call_sessions ORDER BY created_at DESC LIMIT 3').fetchall())
   "
   ```

9. **Confirm webhook signature** with VoiceLink support — ask for their exact signature header name and algorithm.

10. **Fix `get_call_details()`** endpoint URL to match VoiceLink spec (`GET /call-log/details?call_id=...`).

---

## H. Required Environment Variables (complete list)

```bash
# Core (existing)
GEMINI_API_KEY=...
FLASK_SECRET_KEY=...
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=...
OPENROUTER_API_KEY=...           # for free LLM via OpenRouter
OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free

# VoiceLink (new)
VOICELINK_ENABLED=true           # set to true to activate
VOICELINK_USERNAME=...
VOICELINK_PASSWORD=...
VOICELINK_DID_ID=<integer>       # DID ID from portal (NOT phone number)
VOICELINK_BOT_WEBSOCKET_URL=wss://...
VOICELINK_BOT_WEBHOOK_URL=https://...
VOICELINK_WEBHOOK_SECRET=...     # set same value in VoiceLink portal
VOICELINK_VAD_SILENCE_CHUNKS=20  # ~400ms silence at 8kHz
VOICELINK_VAD_ENERGY_THRESHOLD=200
VOICELINK_MAX_BUFFER_CHUNKS=200  # ~4 seconds max utterance
```
