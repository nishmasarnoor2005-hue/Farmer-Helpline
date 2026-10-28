"""
services/telephony/base_adapter.py

Abstract base class for telephony adapters.
All concrete adapters (MockAdapter, TwilioAdapter, etc.) must implement
these four methods.
"""

from abc import ABC, abstractmethod


class TelephonyAdapter(ABC):
    """Base interface for telephony integrations."""

    @abstractmethod
    def handle_incoming_call(self, call_data: dict) -> str:
        """
        Handle an incoming call event.

        Args:
            call_data: Provider-specific call metadata.

        Returns:
            session_id: A unique string identifying this call session.
        """

    @abstractmethod
    def stream_audio_input(self, session_id: str, audio_bytes: bytes) -> None:
        """
        Receive a chunk of audio from the caller.

        Args:
            session_id: The session returned by handle_incoming_call.
            audio_bytes: Raw audio bytes from the telephony provider.
        """

    @abstractmethod
    def play_audio_response(self, session_id: str, audio_path: str) -> None:
        """
        Play a pre-generated audio file back to the caller.

        Args:
            session_id: The session returned by handle_incoming_call.
            audio_path: Filesystem path to the .mp3 / .wav response file.
        """

    @abstractmethod
    def end_call(self, session_id: str) -> None:
        """
        Terminate the call and clean up resources.

        Args:
            session_id: The session returned by handle_incoming_call.
        """
