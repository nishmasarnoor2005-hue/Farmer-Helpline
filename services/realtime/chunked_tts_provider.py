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
        Placeholder generator.

        This stub yields a single ``done`` event. The full implementation
        (sentence-chunked STT → Gemini → per-sentence Edge TTS) is added in
        FEAT-002/003, which build on this scaffolding.

        Callers must handle ``type == "done"`` as end-of-turn.
        """
        # Reset the cancel flag for this new turn
        flag = self._get_cancel_flag(session_id)
        flag.clear()

        yield {"type": "done", "data": None, "turn_id": ""}

    def cancel_response(self, session_id: str) -> None:
        """
        Signal cancellation for the given session.

        Safe to call even if no response is in progress or the session is unknown.
        Sets the threading.Event so any in-progress process_audio_stream() loop
        can check ``flag.is_set()`` and exit early.
        """
        flag = self._get_cancel_flag(session_id)
        flag.set()
