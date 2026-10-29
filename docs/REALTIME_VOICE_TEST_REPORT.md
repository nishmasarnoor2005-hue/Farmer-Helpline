# Real-Time Voice Test Report

## Test Run Summary
- Date: 2026-10-29
- Total tests: 177
- Passed: 177
- Failed: 0
- Test command: `d:\Major_Project\.venv\Scripts\python.exe -m pytest tests\ -q --tb=no`

## Provider Capability Matrix
| Provider | Available | Streaming | True Real-Time |
|---|---|---|---|
| ChunkedTTS (Whisper+Gemini+EdgeTTS) | Yes | Chunked (sentence-by-sentence) | No |
| OpenAI Realtime API | BLOCKED_PENDING_CREDENTIALS | True full-duplex | Yes |

## VAD Notes
- Primary: @ricky0123/vad-web (Silero VAD, loaded from CDN)
- Fallback: SimpleSilenceDetector (AnalyserNode + RMS, in realtime_voice.js)
- Config served from GET /realtime/config

## Barge-In Verified States
- ASSISTANT_SPEAKING -> INTERRUPTING -> LISTENING (via VAD + 180ms debounce)
- Cooldown: 300ms after barge-in, VAD ignored
- Echo protection: only triggered in ASSISTANT_SPEAKING state
- Python-side: cancel_response() sets threading.Event flag; generator exits early

## Security Checklist
- [x] Token never logged
- [x] Rate limit on /realtime/session: 5/min/IP
- [x] X-Session-Token validated on audio, cancel, DELETE routes
- [x] No API keys in JS/HTML
- [x] speak_to_bytes temp file deleted in finally block
- [x] Max 50 audio_chunks per turn
- [x] Session expiry thread (60s interval, guarded by TESTING)

## Known Limitations
- Whisper requires complete audio file before transcription (no streaming STT)
- Gemini requires complete reply before returning (no streaming LLM)
- EdgeTTS generates complete MP3 per sentence (chunked TTS gives latency reduction, not true streaming)
- OpenAI Realtime API (true full-duplex) is BLOCKED_PENDING_CREDENTIALS

## Legacy Mode Verification
- REALTIME_VOICE_ENABLED=false (default): /process_audio works exactly as before
- All existing tests pass with feature flag disabled
