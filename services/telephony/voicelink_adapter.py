"""
services/telephony/voicelink_adapter.py

VoiceLinkAdapter — WebSocket bot adapter for VoiceLink India telephony.

Protocol (confirmed from official API spec):
- VoiceLink connects TO our WebSocket endpoint (we expose wss://)
- Audio format: base64-encoded G.711 A-law (PCMA), 8-bit, 8 kHz, mono
- Inbound events: connected, start, media, mark, clear, transfer, stop
- Outbound events: media, mark, clear, stop

Event schemas (inbound from VoiceLink):
  connected:  {"event": "connected", "protocol": "Call", "version": "1.0.0"}
  start:      {"event": "start", "sequenceNumber": "1", "start": {"callSid": "...",
               "accountSid": "...", "streamSid": "...", "customParameters": {...}},
               "streamSid": "..."}
  media:      {"event": "media", "sequenceNumber": "2", "media": {"track": "inbound",
               "chunk": "1", "timestamp": "5", "payload": "<base64-pcma>"},
               "streamSid": "..."}
  mark:       {"event": "mark", "sequenceNumber": "3", "mark": {"name": "..."},
               "streamSid": "..."}
  clear:      {"event": "clear", "streamSid": "..."}
  stop:       {"event": "stop", "sequenceNumber": "10",
               "stop": {"accountSid": "...", "callSid": "..."}, "streamSid": "..."}

Event schemas (outbound from us to VoiceLink):
  media:      {"event": "media", "streamSid": "...", "media": {"payload": "<base64-pcma>"}}
  mark:       {"event": "mark", "streamSid": "...", "mark": {"name": "<label>"}}
  clear:      {"event": "clear", "streamSid": "..."}
  stop:       {"event": "stop", "streamSid": "..."}
"""

import json
import logging
import os
import threading
import uuid

logger = logging.getLogger(__name__)

# VAD / buffering config from environment
VAD_SILENCE_CHUNKS = int(os.getenv("VOICELINK_VAD_SILENCE_CHUNKS", "20"))
VAD_ENERGY_THRESHOLD = int(os.getenv("VOICELINK_VAD_ENERGY_THRESHOLD", "200"))
MAX_BUFFER_CHUNKS = int(os.getenv("VOICELINK_MAX_BUFFER_CHUNKS", "200"))

# Wait audio directory (pre-generated MP3s per language)
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WAIT_AUDIO_DIR = os.path.join(_BASE_DIR, "static", "wait_audio")


def _load_wait_audio_pcma(lang: str = "en") -> str:
    """
    Load the pre-generated wait-audio MP3 for `lang` and convert it to
    base64-encoded PCMA.  Returns empty string if unavailable.
    """
    from voice.pcma_utils import mp3_bytes_to_pcma_b64  # lazy

    path = os.path.join(WAIT_AUDIO_DIR, f"wait_{lang}.mp3")
    fallback = os.path.join(WAIT_AUDIO_DIR, "wait_en.mp3")

    for candidate in (path, fallback):
        if os.path.exists(candidate):
            try:
                with open(candidate, "rb") as fh:
                    return mp3_bytes_to_pcma_b64(fh.read())
            except Exception as exc:
                logger.warning("Failed to load wait audio %s: %s", candidate, exc)
    return ""


class VoiceLinkAdapter:
    """
    Manages one WebSocket connection from VoiceLink.

    Lifecycle
    ---------
    1. VoiceLink opens a WebSocket to /integrations/voicelink/ws
    2. VoiceLink sends "connected" then "start"
    3. VoiceLink streams "media" events (PCMA chunks)
    4. Adapter detects silence / buffer-full → runs STT+AI+TTS pipeline
    5. Adapter sends "media" events with PCMA response audio
    6. VoiceLink sends "stop" → adapter cleans up
    """

    def __init__(self):
        self.stream_sid: str = ""
        self.call_sid: str = ""
        self.session_id: str = ""
        self._pcma_buffer: list = []          # list of bytes (decoded PCMA per chunk)
        self._silence_counter: int = 0
        self._processing: bool = False        # True while STT+AI+TTS pipeline runs
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public: WebSocket handler (called from the Flask route)
    # ------------------------------------------------------------------

    def handle_ws_connection(self, ws) -> None:
        """
        Main WebSocket loop.  Reads JSON messages from VoiceLink and
        dispatches to the appropriate handler until the connection closes
        or a "stop" event arrives.
        """
        logger.info("VoiceLink WebSocket connection opened")
        try:
            while True:
                try:
                    raw = ws.receive()
                except Exception:
                    # Connection closed by remote side
                    break

                if raw is None:
                    break

                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("VoiceLink: received non-JSON message (ignored)")
                    continue

                event = msg.get("event", "")

                if event == "connected":
                    self._on_connected(ws, msg)
                elif event == "start":
                    self._on_start(ws, msg)
                elif event == "media":
                    self._on_media(ws, msg)
                elif event == "mark":
                    self._on_mark(ws, msg)
                elif event == "clear":
                    self._on_clear(ws, msg)
                elif event == "transfer":
                    self._on_transfer(ws, msg)
                elif event == "stop":
                    self._on_stop(ws, msg)
                    break
                else:
                    logger.debug("VoiceLink: unknown event '%s' (ignored)", event)

        except Exception as exc:
            logger.error("VoiceLink WebSocket error: %s", exc)
        finally:
            self._cleanup()
            logger.info("VoiceLink WebSocket connection closed (stream_sid=%s)",
                        self.stream_sid or "<none>")

    # ------------------------------------------------------------------
    # Public: Webhook processor (called from the Flask route)
    # ------------------------------------------------------------------

    @staticmethod
    def process_webhook(payload: dict, signature: str, secret: str) -> dict:
        """
        Validate and process a VoiceLink lifecycle webhook event.

        Signature verification is performed when `secret` is non-empty.
        Returns a dict with 'ok' key.
        """
        if secret:
            import hmac
            import hashlib
            expected = hmac.new(
                secret.encode(),
                json.dumps(payload, separators=(",", ":")).encode(),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, signature):
                logger.warning("VoiceLink webhook: invalid signature")
                return {"ok": False, "error": "invalid_signature"}

        event_type = payload.get("event", "unknown")
        # Log event type only — never log full payload (may contain caller numbers)
        logger.info("VoiceLink webhook: event=%s", event_type)

        if event_type == "call.initiated":
            pass  # Nothing to do server-side at this stage
        elif event_type == "call.answered":
            pass  # WebSocket will be established shortly
        elif event_type in ("call.ended", "call.completed"):
            call_id = payload.get("callSid") or payload.get("call_sid", "")
            if call_id:
                logger.info("VoiceLink webhook: call ended (callSid redacted)")

        return {"ok": True, "event": event_type}

    # ------------------------------------------------------------------
    # Outbound helpers
    # ------------------------------------------------------------------

    def _send_media(self, ws, pcma_b64: str) -> None:
        """Send a media event with PCMA audio back to VoiceLink."""
        if not pcma_b64:
            return
        msg = {
            "event": "media",
            "streamSid": self.stream_sid,
            "media": {"payload": pcma_b64},
        }
        try:
            ws.send(json.dumps(msg))
        except Exception as exc:
            logger.warning("VoiceLink: failed to send media: %s", exc)

    def _send_mark(self, ws, label: str) -> None:
        """Send a mark event."""
        msg = {
            "event": "mark",
            "streamSid": self.stream_sid,
            "mark": {"name": label},
        }
        try:
            ws.send(json.dumps(msg))
        except Exception as exc:
            logger.warning("VoiceLink: failed to send mark: %s", exc)

    def _send_clear(self, ws) -> None:
        """Send a clear event to flush the caller's audio queue."""
        msg = {"event": "clear", "streamSid": self.stream_sid}
        try:
            ws.send(json.dumps(msg))
        except Exception as exc:
            logger.warning("VoiceLink: failed to send clear: %s", exc)

    # ------------------------------------------------------------------
    # Inbound event handlers
    # ------------------------------------------------------------------

    def _on_connected(self, ws, msg: dict) -> None:
        logger.info("VoiceLink: connected (protocol=%s version=%s)",
                    msg.get("protocol", "?"), msg.get("version", "?"))

    def _on_start(self, ws, msg: dict) -> None:
        start = msg.get("start", {})
        self.stream_sid = msg.get("streamSid", start.get("streamSid", ""))
        self.call_sid = start.get("callSid", "")
        # Use a safe internal ID — never log call_sid
        self.session_id = uuid.uuid4().hex
        logger.info("VoiceLink: call started (stream_sid=%s session=%s)",
                    self.stream_sid, self.session_id)

        # Create DB session
        try:
            import backend.database as db  # lazy
            db.create_session(self.session_id, channel="voicelink")
        except Exception as exc:
            logger.warning("VoiceLink: DB create_session failed (non-fatal): %s", exc)

    def _on_media(self, ws, msg: dict) -> None:
        media = msg.get("media", {})
        if media.get("track", "inbound") != "inbound":
            return  # Ignore outbound echoes

        payload_b64 = media.get("payload", "")
        if not payload_b64:
            return

        # Decode PCMA chunk → raw PCMA bytes
        import base64 as _b64
        try:
            pcma_chunk = _b64.b64decode(payload_b64)
        except Exception:
            logger.debug("VoiceLink: invalid base64 in media chunk (ignored)")
            return

        should_process = False
        buffer_snapshot = []

        with self._lock:
            if self._processing:
                return  # Drop incoming audio while pipeline is running

            self._pcma_buffer.append(pcma_chunk)

            # Voice activity detection: energy-based silence detection
            try:
                import audioop
                rms = audioop.rms(pcma_chunk, 1)  # PCMA is 8-bit (width=1)
            except Exception:
                rms = VAD_ENERGY_THRESHOLD + 1  # assume speech if audioop fails

            if rms < VAD_ENERGY_THRESHOLD:
                self._silence_counter += 1
            else:
                self._silence_counter = 0

            should_process = (
                self._silence_counter >= VAD_SILENCE_CHUNKS
                or len(self._pcma_buffer) >= MAX_BUFFER_CHUNKS
            )

            if should_process and self._pcma_buffer:
                buffer_snapshot = list(self._pcma_buffer)
                self._pcma_buffer.clear()
                self._silence_counter = 0
                self._processing = True

        if should_process and buffer_snapshot:
            # Run pipeline in a background thread so we don't block the WS loop
            t = threading.Thread(
                target=self._run_pipeline,
                args=(ws, buffer_snapshot),
                daemon=True,
            )
            t.start()

    def _on_mark(self, ws, msg: dict) -> None:
        mark_name = msg.get("mark", {}).get("name", "")
        logger.debug("VoiceLink: mark received: %s", mark_name)

    def _on_clear(self, ws, msg: dict) -> None:
        with self._lock:
            self._pcma_buffer.clear()
            self._silence_counter = 0
        logger.debug("VoiceLink: clear received — buffer flushed")

    def _on_transfer(self, ws, msg: dict) -> None:
        logger.info("VoiceLink: transfer event received")

    def _on_stop(self, ws, msg: dict) -> None:
        logger.info("VoiceLink: stop event (stream_sid=%s)", self.stream_sid)
        try:
            import backend.database as db  # lazy
            if self.session_id:
                db.end_session(self.session_id)
        except Exception as exc:
            logger.warning("VoiceLink: DB end_session failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Audio pipeline
    # ------------------------------------------------------------------

    def _run_pipeline(self, ws, pcma_chunks: list) -> None:
        """
        Full audio pipeline:
        1. Send wait audio immediately (so the caller hears a response)
        2. Decode PCMA → WAV
        3. Whisper STT
        4. Gemini/OpenRouter AI reply
        5. Edge TTS → MP3 → PCMA
        6. Send PCMA audio back to VoiceLink
        """
        reply = "Sorry, I could not process your question. Please try again."
        transcript = ""
        reply_audio_path = None

        try:
            # Step 1: Send wait audio immediately (Kannada default, corrected after STT)
            wait_pcma = _load_wait_audio_pcma(lang="kn")
            if wait_pcma:
                self._send_mark(ws, "wait_start")
                self._send_media(ws, wait_pcma)
                self._send_mark(ws, "wait_end")

            # Step 2: Decode PCMA buffer → WAV bytes
            import audioop
            from voice.pcma_utils import pcm_bytes_to_wav  # lazy

            raw_pcma = b"".join(pcma_chunks)
            try:
                pcm_bytes = audioop.alaw2lin(raw_pcma, 2)
            except Exception as exc:
                logger.error("VoiceLink: PCMA decode failed: %s", exc)
                return

            wav_bytes = pcm_bytes_to_wav(pcm_bytes, sample_rate=8000)

            # Step 3: Whisper STT — write WAV to temp file
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(wav_bytes)
                tmp_path = tmp.name

            detected_lang = "kn"  # default for this helpline's audience
            try:
                from faster_whisper import WhisperModel  # lazy
                # Re-use the app-level Whisper model if available via import,
                # fall back to loading a new instance if not (e.g. during tests)
                try:
                    from app import whisper_model as _whisper
                except ImportError:
                    _whisper = WhisperModel("small", device="cpu", compute_type="int8")

                segments, info = _whisper.transcribe(
                    tmp_path,
                    beam_size=5,
                    vad_filter=True,
                    condition_on_previous_text=False,
                    language=None,  # auto-detect on first turn
                    temperature=0.0,
                )
                transcript = " ".join(s.text.strip() for s in segments).strip()
                # Use Whisper's detected language as a best-guess; Gemini
                # language detection from audio bytes is not feasible here
                # because we have raw PCMA not the original WebM.
                if info and info.language:
                    from app import SUPPORTED_CODES
                    detected_lang = info.language if info.language in SUPPORTED_CODES else "kn"
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

            if not transcript:
                logger.debug("VoiceLink: empty transcript — no response sent")
                return

            logger.info("VoiceLink: transcribed (len=%d)", len(transcript))

            # Step 4: AI reply — use detected language
            try:
                from services.assistant import get_reply  # lazy
                reply = get_reply(transcript, detected_lang, None)
            except Exception as exc:
                logger.error("VoiceLink: AI reply failed: %s", exc)

            # Step 5: Edge TTS → MP3 — use detected language
            try:
                from voice.text_to_speech import speak  # lazy
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
                    reply_audio_path = tf.name
                speak(reply, detected_lang, output_path=reply_audio_path)
            except Exception as exc:
                logger.error("VoiceLink: TTS failed: %s", exc)

            # Step 6: Convert MP3 → PCMA b64 → send
            if reply_audio_path and os.path.exists(reply_audio_path):
                try:
                    from voice.pcma_utils import mp3_bytes_to_pcma_b64  # lazy
                    with open(reply_audio_path, "rb") as fh:
                        reply_pcma_b64 = mp3_bytes_to_pcma_b64(fh.read())
                    if reply_pcma_b64:
                        self._send_clear(ws)  # flush wait audio
                        self._send_media(ws, reply_pcma_b64)
                        self._send_mark(ws, "reply_end")
                except Exception as exc:
                    logger.error("VoiceLink: MP3-to-PCMA conversion failed: %s", exc)
                finally:
                    try:
                        os.unlink(reply_audio_path)
                    except Exception:
                        pass

            # Log interaction
            try:
                import backend.database as db  # lazy
                if self.session_id:
                    db.log_interaction(
                        session_id=self.session_id,
                        language=detected_lang,
                        transcript=transcript,
                        intent="voicelink",
                        assistant_response=reply,
                        status="success",
                        latency_dict={},
                    )
            except Exception as exc:
                logger.warning("VoiceLink: DB log failed (non-fatal): %s", exc)

        except Exception as exc:
            logger.error("VoiceLink pipeline error: %s", exc)
        finally:
            with self._lock:
                self._processing = False

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self) -> None:
        with self._lock:
            self._pcma_buffer.clear()
            self._silence_counter = 0
