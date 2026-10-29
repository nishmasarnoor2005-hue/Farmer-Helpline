"""
services/realtime/base_provider.py

Abstract base class for all real-time (or quasi-real-time) voice providers.

Every concrete provider must implement:
  - is_available()        — whether the provider can be used right now
  - process_audio_stream()— accepts raw audio bytes, yields structured dicts
  - cancel_response()     — cancels an active provider response for a session

Yielded dicts from process_audio_stream() must always include:
  {
    "type":    str,   # "transcript" | "text" | "audio" | "done" | "error"
    "data":    Any,   # payload appropriate to the type
    "turn_id": str,   # opaque string; consumer discards chunks with stale IDs
  }
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generator


class RealtimeProvider(ABC):
    """Abstract base class for real-time voice provider adapters."""

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @abstractmethod
    def is_available(self) -> bool:
        """
        Return True if this provider is configured and ready to handle requests.

        Implementations should check that required API keys and dependencies are
        present without making any network calls.
        """

    # ------------------------------------------------------------------
    # Audio processing
    # ------------------------------------------------------------------

    @abstractmethod
    def process_audio_stream(
        self,
        audio_bytes: bytes,
        session_id: str,
        language_code: str,
    ) -> Generator[dict, None, None]:
        """
        Process audio and yield structured response events.

        Args:
            audio_bytes:   Raw audio bytes (WebM, WAV, or PCM depending on provider).
            session_id:    Opaque per-browser-session identifier used for state
                           isolation and cancellation.
            language_code: BCP-47 / ISO-639-1 language code detected for this session
                           (e.g. "kn", "hi", "en").

        Yields:
            Dicts with at minimum the keys ``type``, ``data``, and ``turn_id``.

            Known ``type`` values:
              "transcript" — partial or final STT text; ``data`` is a str
              "text"       — partial or final LLM reply text; ``data`` is a str
              "audio"      — TTS audio chunk; ``data`` is bytes (MP3/PCM)
              "done"       — turn complete; ``data`` is None
              "error"      — non-fatal error; ``data`` is an error message str

        Callers must discard any yielded dict whose ``turn_id`` does not match the
        current expected turn ID (stale chunk from a cancelled response).
        """

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    @abstractmethod
    def cancel_response(self, session_id: str) -> None:
        """
        Cancel the active provider response for the given session.

        Must be safe to call even if no response is currently active.
        Implementations should:
          1. Signal any in-progress generation to stop.
          2. Clear queued audio/text buffers for this session.
          3. NOT raise if session_id is unknown.
        """
