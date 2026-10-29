"""
services/realtime/chunked_tts_provider.py

ChunkedTTSProvider — a quasi-real-time provider that uses the existing
Whisper/Gemini/Edge TTS pipeline but delivers TTS audio sentence-by-sentence
to reduce perceived first-audio latency.

This provider does NOT require any new API credentials. It wires together the
existing callbacks passed at construction time.

Streaming status
----------------
  STT:   NOT streaming — faster-whisper requires a complete audio file.
  LLM:   NOT streaming — Gemini generate_content returns a full reply.
  TTS:   CHUNKED — text is split into sentences; each sentence is synthesised
         independently so the browser receives the first audio chunk while
         later sentences are still being generated.
  Gap:   True audio streaming requires either a streaming STT/LLM/TTS provider
         or a switch to OpenAI Realtime (FEAT-004, BLOCKED_PENDING_CREDENTIALS).
"""

from __future__ import annotations

import re
import threading
from typing import Generator, Callable

from services.realtime.base_provider import RealtimeProvider


# ---------------------------------------------------------------------------
# Sentence splitter
# ---------------------------------------------------------------------------

# Sentence-ending punctuation including Devanagari danda (।) and Kannada pipe (|)
_SENTENCE_END_RE = re.compile(
    r'(?<=[.!?।|])\s+'          # Western + Indic sentence terminators followed by space
    r'|(?<=[.!?।|])$'            # or at end of string
)

_MIN_SENTENCE_CHARS = 10        # Merge fragments shorter than this into the next sentence


def split_into_sentences(text: str) -> list[str]:
    """
    Split *text* into a list of sentences suitable for chunked TTS synthesis.

    Splitting rules:
    - Splits on  '.', '!', '?', '।' (Devanagari danda), '|' (Kannada pipe)
      when followed by whitespace or at end-of-string.
    - Merges any resulting fragment shorter than _MIN_SENTENCE_CHARS characters
      into the following sentence (or the previous one if it is the last fragment)
      to avoid generating many tiny TTS requests.
    - Always returns at least one element (the original text if no split is found).

    Args:
        text: Any non-empty string.

    Returns:
        A list of sentence strings with leading/trailing whitespace stripped.
    """
    if not text or not text.strip():
        return [text] if text else []

    raw = [s.strip() for s in _SENTENCE_END_RE.split(text) if s and s.strip()]
    if not raw:
        return [text.strip()]

    # Merge short fragments forward
    merged: list[str] = []
    carry = ""
    for fragment in raw:
        combined = (carry + " " + fragment).strip() if carry else fragment
        if len(combined) < _MIN_SENTENCE_CHARS:
            carry = combined
        else:
            merged.append(combined)
            carry = ""

    # Any remaining carry is appended to the last sentence or becomes its own
    if carry:
        if merged:
            merged[-1] = (merged[-1] + " " + carry).strip()
        else:
            merged.append(carry)

    return merged if merged else [text.strip()]


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class ChunkedTTSProvider(RealtimeProvider):
    """
    Quasi-real-time provider built on the existing Whisper/Gemini/Edge TTS pipeline.

    Construction
    ------------
    All service dependencies are injected as callbacks so this module has no
    direct imports from the Flask app and avoids circular-import issues.

    Callback signatures
    -------------------
    whisper_cb(audio_path: str) -> tuple[str, str]
        Transcribe audio file; returns (text, language_code).

    gemini_cb(text: str, language: str, context_data: dict | None) -> str
        Get a Gemini reply for the farmer's text.

    speak_bytes_cb(text: str, language: str) -> bytes | None
        Synthesise speech; return raw audio bytes (MP3) or None on failure.

    get_lang_cb(session_id: str) -> str
        Return the cached language code for this session (default "kn").

    classify_intent_cb(text: str) -> str
        Classify the intent of the farmer's utterance.

    weather_cb(location: str) -> dict | None
        Fetch weather data for a location.

    market_cb(crop: str, location: str | None) -> list[dict]
        Fetch market price data.

    scheme_cb(query: str) -> list[dict]
        Fetch relevant government scheme data.
    """

    def __init__(
        self,
        whisper_cb: Callable,
        gemini_cb: Callable,
        speak_bytes_cb: Callable,
        get_lang_cb: Callable,
        classify_intent_cb: Callable,
        weather_cb: Callable,
        market_cb: Callable,
        scheme_cb: Callable,
    ) -> None:
        self._whisper_cb = whisper_cb
        self._gemini_cb = gemini_cb
        self._speak_bytes_cb = speak_bytes_cb
        self._get_lang_cb = get_lang_cb
        self._classify_intent_cb = classify_intent_cb
        self._weather_cb = weather_cb
        self._market_cb = market_cb
        self._scheme_cb = scheme_cb

        # Per-session cancellation flags
        self._cancel_flags: dict[str, threading.Event] = {}
        self._flags_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_cancel_flag(self, session_id: str) -> threading.Event:
        """Return (creating if needed) the cancellation Event for a session."""
        with self._flags_lock:
            if session_id not in self._cancel_flags:
                self._cancel_flags[session_id] = threading.Event()
            return self._cancel_flags[session_id]

    # ------------------------------------------------------------------
    # RealtimeProvider interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Always True — uses existing pipeline, no extra credentials needed."""
        return True

    def process_audio_stream(
        self,
        audio_bytes: bytes,
        session_id: str,
        language_code: str,
    ) -> Generator[dict, None, None]:
        """
        Sentence-chunked STT → Gemini → per-sentence Edge TTS streaming pipeline.

        Flow
        ----
        1. Reset cancellation flag for this new turn.
        2. Write audio_bytes to a temp file for Whisper.
        3. Check cancel → detect language (cached) → transcribe with Whisper.
        4. Yield a ``transcript`` event.
        5. Check cancel → classify intent → look up services → call Gemini.
        6. Split reply into sentences.
        7. For each sentence: check cancel → synthesise TTS bytes → yield
           ``audio_chunk`` event with base64-encoded audio.
        8. Yield ``done``.
        9. Clean up temp file in finally block.

        On cancellation at any checkpoint, yields ``{"type":"error","data":
        "cancelled","turn_id":turn_id}`` and returns.

        Callers must handle ``type == "done"`` as end-of-turn and discard any
        chunk whose ``turn_id`` does not match the expected value.
        """
        import base64
        import os
        import tempfile
        import uuid as _uuid

        # Assign a unique turn_id for this invocation so callers can discard
        # stale chunks from previously cancelled turns.
        turn_id = _uuid.uuid4().hex

        # Prepare the cancel flag for this new turn.
        # If cancel_response() was called before this turn started (pre-cancel),
        # the flag is already set — honour that cancellation immediately.
        flag = self._get_cancel_flag(session_id)
        pre_cancelled = flag.is_set()
        if not pre_cancelled:
            flag.clear()  # Reset from any previous turn's cancellation

        tmp_path = None
        try:
            # ------------------------------------------------------------------
            # 1. Persist audio bytes to a temporary file for Whisper
            # ------------------------------------------------------------------
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            # ------------------------------------------------------------------
            # 2. Check cancel before expensive STT
            # ------------------------------------------------------------------
            if flag.is_set():
                yield {"type": "error", "data": "cancelled", "turn_id": turn_id, "interrupted": True}
                return

            # ------------------------------------------------------------------
            # 3. Language detection — use cached value or fall back to
            #    the language_code argument supplied by the caller
            # ------------------------------------------------------------------
            cached_lang = self._get_lang_cb(session_id)
            effective_lang = cached_lang if cached_lang else language_code

            # ------------------------------------------------------------------
            # 4. Whisper transcription
            # ------------------------------------------------------------------
            try:
                transcript_text, _ = self._whisper_cb(tmp_path)
            except Exception as exc:
                yield {"type": "error", "data": f"transcription_failed: {exc}", "turn_id": turn_id}
                return

            if not transcript_text or not transcript_text.strip():
                yield {"type": "error", "data": "empty_transcript", "turn_id": turn_id}
                return

            # ------------------------------------------------------------------
            # 5. Yield transcript event
            # ------------------------------------------------------------------
            yield {"type": "transcript", "data": transcript_text, "turn_id": turn_id}

            # ------------------------------------------------------------------
            # 6. Check cancel before LLM call
            # ------------------------------------------------------------------
            if flag.is_set():
                yield {"type": "error", "data": "cancelled", "turn_id": turn_id, "interrupted": True}
                return

            # ------------------------------------------------------------------
            # 7. Intent classification + optional service lookups
            # ------------------------------------------------------------------
            text_lower = transcript_text.lower()
            context_data = None

            try:
                intent_result = self._classify_intent_cb(transcript_text, effective_lang)
                detected_intent = (
                    intent_result.get("intent", "unknown")
                    if isinstance(intent_result, dict)
                    else str(intent_result)
                )
            except Exception:
                detected_intent = "unknown"

            # Weather lookup
            if detected_intent == "weather" or any(
                kw in text_lower for kw in ("weather", "rain", "temperature", "forecast")
            ):
                try:
                    weather_result = self._weather_cb(transcript_text)
                    if weather_result:
                        context_data = {"weather": weather_result}
                except Exception:
                    pass

            # Market price lookup
            if detected_intent == "market_price" or any(
                kw in text_lower for kw in ("price", "market", "rate", "mandi")
            ):
                try:
                    market_result = self._market_cb(transcript_text, None)
                    if market_result:
                        context_data = context_data or {}
                        context_data["market_data"] = market_result
                except Exception:
                    pass

            # Scheme lookup
            if detected_intent == "government_scheme" or any(
                kw in text_lower for kw in ("scheme", "yojana", "subsidy", "loan")
            ):
                try:
                    scheme_result = self._scheme_cb(text_lower)
                    if scheme_result:
                        context_data = context_data or {}
                        context_data["scheme_data"] = scheme_result
                except Exception:
                    pass

            # ------------------------------------------------------------------
            # 8. Gemini reply
            # ------------------------------------------------------------------
            if flag.is_set():
                yield {"type": "error", "data": "cancelled", "turn_id": turn_id, "interrupted": True}
                return

            try:
                reply_text = self._gemini_cb(transcript_text, effective_lang, context_data)
            except Exception as exc:
                yield {"type": "error", "data": f"llm_failed: {exc}", "turn_id": turn_id}
                return

            if not reply_text or not str(reply_text).strip():
                yield {"type": "error", "data": "empty_reply", "turn_id": turn_id}
                return

            # ------------------------------------------------------------------
            # 9. Split reply into sentences for chunked TTS
            # ------------------------------------------------------------------
            sentences = split_into_sentences(str(reply_text))

            # ------------------------------------------------------------------
            # 10. Per-sentence TTS synthesis → yield audio_chunk events
            # ------------------------------------------------------------------
            for sentence in sentences:
                if flag.is_set():
                    yield {"type": "error", "data": "cancelled", "turn_id": turn_id, "interrupted": True}
                    return

                if not sentence.strip():
                    continue

                try:
                    audio_bytes_chunk = self._speak_bytes_cb(sentence, effective_lang)
                except Exception as exc:
                    yield {"type": "error", "data": f"tts_failed: {exc}", "turn_id": turn_id}
                    return

                if audio_bytes_chunk:
                    encoded = base64.b64encode(audio_bytes_chunk).decode("ascii")
                    yield {
                        "type":    "audio_chunk",
                        "data":    encoded,
                        "turn_id": turn_id,
                    }

            # ------------------------------------------------------------------
            # 11. Done
            # ------------------------------------------------------------------
            yield {"type": "done", "data": None, "turn_id": turn_id}

        finally:
            # Always clean up the temp audio file
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def cancel_response(self, session_id: str) -> None:
        """
        Signal cancellation for the given session.

        Safe to call even if no response is in progress or the session is unknown.
        Sets the threading.Event so any in-progress process_audio_stream() loop
        can check ``flag.is_set()`` and exit early.

        If the session has not started yet, creates a pre-set flag so that any
        subsequent process_audio_stream() call exits immediately.
        """
        with self._flags_lock:
            if session_id in self._cancel_flags:
                self._cancel_flags[session_id].set()
            else:
                # Create and immediately set the flag for sessions that haven't started yet
                flag = threading.Event()
                flag.set()
                self._cancel_flags[session_id] = flag
