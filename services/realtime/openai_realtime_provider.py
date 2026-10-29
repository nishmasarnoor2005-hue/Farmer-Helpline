"""
services/realtime/openai_realtime_provider.py

OpenAIRealtimeProvider — stub for the OpenAI Realtime API.

Status: BLOCKED_PENDING_CREDENTIALS
---------------------------------------
The OpenAI Realtime API provides true full-duplex, low-latency speech-to-speech
conversation over WebRTC or WebSocket. It supports:
  - Server-side voice activity detection (VAD)
  - Barge-in / interruption handling
  - Streaming audio input and output
  - Function/tool calling during the conversation

This provider is intentionally left as a stub until valid credentials are
provisioned. All methods that perform actual work raise NotImplementedError
with the message "BLOCKED_PENDING_CREDENTIALS" so the application continues
to route through ChunkedTTSProvider at runtime.

To activate this provider:
  1. Obtain an OPENAI_API_KEY with Realtime API entitlement from platform.openai.com.
  2. Set OPENAI_API_KEY in the .env file.
  3. Implement the WebRTC/WebSocket session management in this class following
     the official documentation at:
     https://platform.openai.com/docs/guides/realtime
  4. Implement get_provider() routing in provider_factory.py (already wired).

Do NOT add OPENAI_API_KEY to version control or any committed file.
"""

from __future__ import annotations

import os
from typing import Generator

from services.realtime.base_provider import RealtimeProvider


class OpenAIRealtimeProvider(RealtimeProvider):
    """
    Stub adapter for the OpenAI Realtime API.

    ``is_available()`` returns True only when ``OPENAI_API_KEY`` is set in the
    environment. All other methods raise ``NotImplementedError`` until the full
    WebRTC/WebSocket implementation is added.

    Status: BLOCKED_PENDING_CREDENTIALS
    """

    def is_available(self) -> bool:
        """
        Return True if OPENAI_API_KEY is present in the environment.

        Does not validate the key against the API — only checks that a non-empty
        value has been configured.
        """
        return bool(os.getenv("OPENAI_API_KEY", "").strip())

    def process_audio_stream(
        self,
        audio_bytes: bytes,
        session_id: str,
        language_code: str,
    ) -> Generator[dict, None, None]:
        """
        Not implemented.

        Raises:
            NotImplementedError: Always, until FEAT-004 implements this method.
        """
        raise NotImplementedError("BLOCKED_PENDING_CREDENTIALS")
        yield  # Make this a generator function (unreachable, satisfies type checker)

    def cancel_response(self, session_id: str) -> None:
        """
        Not implemented.

        Raises:
            NotImplementedError: Always, until FEAT-004 implements this method.
        """
        raise NotImplementedError("BLOCKED_PENDING_CREDENTIALS")
