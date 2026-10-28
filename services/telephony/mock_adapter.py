"""
services/telephony/mock_adapter.py

In-memory mock telephony adapter for testing and local development.
No external services are contacted; all state lives in a dict.
"""

import uuid

from .base_adapter import TelephonyAdapter


class MockAdapter(TelephonyAdapter):
    """
    Simulated telephony adapter.

    Stores all call state in self._calls so tests can inspect it directly
    via get_call().
    """

    def __init__(self):
        # {session_id: {status, call_data, audio_inputs, responses, ended}}
        self._calls: dict = {}

    # ------------------------------------------------------------------
    # TelephonyAdapter interface
    # ------------------------------------------------------------------

    def handle_incoming_call(self, call_data: dict) -> str:
        """Create a new mock call session and return its session_id."""
        session_id = str(uuid.uuid4())
        self._calls[session_id] = {
            "status": "active",
            "call_data": call_data,
            "audio_inputs": [],   # list of int (byte lengths received)
            "responses": [],      # list of str (audio_paths played)
            "ended": False,
        }
        return session_id

    def stream_audio_input(self, session_id: str, audio_bytes: bytes) -> None:
        """Record the byte-length of an incoming audio chunk."""
        if session_id not in self._calls:
            raise KeyError(f"Unknown session_id: {session_id}")
        self._calls[session_id]["audio_inputs"].append(len(audio_bytes))

    def play_audio_response(self, session_id: str, audio_path: str) -> None:
        """Record that an audio file was played to the caller."""
        if session_id not in self._calls:
            raise KeyError(f"Unknown session_id: {session_id}")
        self._calls[session_id]["responses"].append(audio_path)

    def end_call(self, session_id: str) -> None:
        """Mark the call as ended."""
        if session_id not in self._calls:
            raise KeyError(f"Unknown session_id: {session_id}")
        self._calls[session_id]["status"] = "ended"
        self._calls[session_id]["ended"] = True

    # ------------------------------------------------------------------
    # Test-helper (not part of the abstract interface)
    # ------------------------------------------------------------------

    def get_call(self, session_id: str) -> dict:
        """Return the full call state dict for a session (useful in tests)."""
        return self._calls[session_id]
