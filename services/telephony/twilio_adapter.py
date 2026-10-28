# STATUS: BLOCKED_PENDING_CREDENTIALS — requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER in .env

"""
services/telephony/twilio_adapter.py

Twilio telephony adapter.

THIS ADAPTER IS NOT OPERATIONAL until the following environment variables
are present and a real inbound call has been tested:
  - TWILIO_ACCOUNT_SID
  - TWILIO_AUTH_TOKEN
  - TWILIO_PHONE_NUMBER

See docs/TELEPHONY_SETUP.md for setup instructions.
"""

import logging
import os

try:
    from twilio.twiml.voice_response import VoiceResponse
    from twilio.request_validator import RequestValidator
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

from .base_adapter import TelephonyAdapter

logger = logging.getLogger(__name__)


class TwilioAdapter(TelephonyAdapter):
    """
    Twilio-backed telephony adapter.

    Raises RuntimeError on __init__ if the twilio package is not installed.
    All methods are stubbed until credentials are configured and a live
    test call has been verified.
    """

    def __init__(self):
        if not TWILIO_AVAILABLE:
            raise RuntimeError(
                "twilio package is not installed. "
                "Run: pip install twilio  (after credentials are confirmed). "
                "See docs/TELEPHONY_SETUP.md."
            )

        self._account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        self._auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        self._phone_number = os.environ.get("TWILIO_PHONE_NUMBER")

        missing = [
            k for k, v in {
                "TWILIO_ACCOUNT_SID": self._account_sid,
                "TWILIO_AUTH_TOKEN": self._auth_token,
                "TWILIO_PHONE_NUMBER": self._phone_number,
            }.items()
            if not v
        ]
        if missing:
            raise RuntimeError(
                f"Missing Twilio credentials in .env: {', '.join(missing)}. "
                "See docs/TELEPHONY_SETUP.md."
            )

        self._validator = RequestValidator(self._auth_token)
        logger.info("TwilioAdapter initialised (credentials loaded, awaiting live test).")

    # ------------------------------------------------------------------
    # TelephonyAdapter interface
    # ------------------------------------------------------------------

    def handle_incoming_call(self, call_data: dict) -> str:
        """
        Return TwiML XML that greets the caller and starts recording.

        call_data is expected to contain Twilio's POST parameters
        (CallSid, From, To, etc.).
        """
        call_sid = call_data.get("CallSid", "unknown")
        logger.info("handle_incoming_call: CallSid=%s", call_sid)

        if TWILIO_AVAILABLE:
            vr = VoiceResponse()
            vr.say(
                "Welcome to the AI Farmer Helpline. Please speak your question after the beep.",
                language="en-IN",
            )
            vr.record(
                action="/telephony/recording_complete",
                method="POST",
                max_length=60,
                play_beep=True,
                transcribe=False,
            )
            return str(vr)
        else:
            # Fallback string builder (twilio not installed)
            return (
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<Response>"
                '<Say language="en-IN">Welcome to the AI Farmer Helpline. '
                "Please speak your question after the beep.</Say>"
                '<Record action="/telephony/recording_complete" method="POST" '
                'maxLength="60" playBeep="true" transcribe="false"/>'
                "</Response>"
            )

    def stream_audio_input(self, session_id: str, audio_bytes: bytes) -> None:
        """Stub — streaming audio from Twilio requires Media Streams setup."""
        logger.info(
            "stream_audio_input stub: session=%s, bytes=%d (pending Media Streams config)",
            session_id,
            len(audio_bytes),
        )

    def play_audio_response(self, session_id: str, audio_path: str) -> None:
        """Stub — playing audio back requires Twilio <Play> verb and a public URL."""
        logger.info(
            "play_audio_response stub: session=%s, path=%s (pending public URL config)",
            session_id,
            audio_path,
        )

    def end_call(self, session_id: str) -> None:
        """Stub — ending a Twilio call requires a REST API call to update the call resource."""
        logger.info(
            "end_call stub: session=%s (pending Twilio REST integration)",
            session_id,
        )
