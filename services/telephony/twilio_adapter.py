# STATUS: CREDENTIALS_CONFIGURED — awaiting TWILIO_PHONE_NUMBER purchase
"""
services/telephony/twilio_adapter.py

Twilio telephony adapter.

Credentials TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are configured.
TWILIO_PHONE_NUMBER must be purchased at https://console.twilio.com
before inbound calls can be received.

See docs/TELEPHONY_SETUP.md for complete setup instructions.
"""

import logging
import os
import pathlib

import requests
from twilio.twiml.voice_response import VoiceResponse, Record, Play
from twilio.request_validator import RequestValidator

from .base_adapter import TelephonyAdapter

logger = logging.getLogger(__name__)

# Directory where downloaded Twilio recordings are stored
_UPLOADS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "uploads"


class TwilioAdapter(TelephonyAdapter):
    """
    Twilio telephony adapter.

    Raises RuntimeError on __init__ only when TWILIO_ACCOUNT_SID or
    TWILIO_AUTH_TOKEN are missing.  TWILIO_PHONE_NUMBER is optional at init
    time — a warning is logged instead so the server remains startable while
    the number is being purchased.
    """

    def __init__(self):
        self._account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
        self._auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
        self._phone_number = os.environ.get("TWILIO_PHONE_NUMBER", "").strip()

        missing_required = [
            k for k, v in {
                "TWILIO_ACCOUNT_SID": self._account_sid,
                "TWILIO_AUTH_TOKEN": self._auth_token,
            }.items()
            if not v
        ]
        if missing_required:
            raise RuntimeError(
                f"Missing required Twilio credentials in .env: "
                f"{', '.join(missing_required)}. "
                "See docs/TELEPHONY_SETUP.md."
            )

        if not self._phone_number:
            logger.warning(
                "TWILIO_PHONE_NUMBER is not set. Inbound calls cannot be received "
                "until a number is purchased at https://console.twilio.com. "
                "See docs/TELEPHONY_SETUP.md."
            )

        self._validator = RequestValidator(self._auth_token)
        logger.info(
            "TwilioAdapter initialised. SID=%s phone_number=%s",
            self._account_sid[:8] + "…",
            self._phone_number or "NOT SET",
        )

    # ------------------------------------------------------------------
    # Webhook signature verification
    # ------------------------------------------------------------------

    def verify_webhook(self, url: str, post_params: dict, signature: str) -> bool:
        """
        Validate an incoming Twilio webhook request.

        Args:
            url:         Full request URL (e.g. https://yourdomain/telephony/incoming).
            post_params: POST form parameters as a plain dict.
            signature:   Value of the X-Twilio-Signature header.

        Returns:
            True if the signature is valid, False otherwise.
        """
        try:
            result = self._validator.validate(url, post_params, signature)
            if not result:
                logger.warning("Twilio webhook signature validation FAILED for URL: %s", url)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("verify_webhook exception: %s", exc)
            return False

    # ------------------------------------------------------------------
    # TelephonyAdapter interface
    # ------------------------------------------------------------------

    def handle_incoming_call(self, call_data: dict) -> str:
        """
        Build TwiML that greets the caller in Kannada and starts recording.

        Args:
            call_data: Twilio POST form parameters (CallSid, From, To, …).

        Returns:
            TwiML XML string.
        """
        call_sid = call_data.get("CallSid", "unknown")
        logger.info("handle_incoming_call: CallSid=%s From=%s", call_sid, call_data.get("From"))

        response = VoiceResponse()
        response.say(
            "ನಮಸ್ಕಾರ, ನೀವು AI ಕೃಷಿ ಸಹಾಯವಾಣಿಗೆ ಕರೆ ಮಾಡಿದ್ದೀರಿ. "
            "ದಯವಿಟ್ಟು ನಿಮ್ಮ ಸಮಸ್ಯೆಯನ್ನು ಹೇಳಿ.",
            voice="woman",
            language="kn-IN",
        )
        response.record(
            max_length=30,
            play_beep=True,
            action="/telephony/respond",
            method="POST",
            timeout=5,
        )
        return str(response)

    def process_recording(
        self, call_sid: str, recording_url: str, session_id: str
    ) -> str:
        """
        Download a Twilio recording, run it through the voice pipeline, and
        return TwiML that speaks the AI reply back to the caller.

        The pipeline: download → transcribe → get_reply → speak (TTS).
        Because the TTS file is local and Twilio needs a public URL, <Say>
        is used to deliver the reply instead of <Play>.

        Args:
            call_sid:      Twilio CallSid.
            recording_url: RecordingUrl from Twilio POST params (without .wav).
            session_id:    Session identifier for conversation history.

        Returns:
            TwiML XML string.
        """
        response = VoiceResponse()

        try:
            # ----------------------------------------------------------------
            # 1. Download the WAV recording
            # ----------------------------------------------------------------
            _UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            wav_path = _UPLOADS_DIR / f"twilio_{call_sid}.wav"
            wav_url = recording_url.rstrip("/") + ".wav"

            logger.info("Downloading recording: %s → %s", wav_url, wav_path)
            dl_resp = requests.get(
                wav_url,
                auth=(self._account_sid, self._auth_token),
                timeout=30,
            )
            dl_resp.raise_for_status()
            wav_path.write_bytes(dl_resp.content)
            logger.info("Recording saved: %s (%d bytes)", wav_path, len(dl_resp.content))

            # ----------------------------------------------------------------
            # 2. Transcribe
            # ----------------------------------------------------------------
            from voice.speech_to_text import speech_to_text as _stt_module  # noqa: F401
            # The standalone speech_to_text.py doesn't expose a file-based
            # transcribe function; the Flask app uses faster-whisper directly.
            # We call faster-whisper here the same way app.py does.
            from faster_whisper import WhisperModel  # noqa: PLC0415

            logger.info("Transcribing %s …", wav_path)
            _wm = WhisperModel("base", device="cpu", compute_type="int8")
            segments, _info = _wm.transcribe(
                str(wav_path), beam_size=3, vad_filter=True
            )
            transcription = " ".join(s.text.strip() for s in segments).strip()
            detected_lang = _info.language or "kn"
            logger.info("Transcription: %r (lang=%s)", transcription, detected_lang)

            if not transcription:
                raise ValueError("Empty transcription — no speech detected")

            # ----------------------------------------------------------------
            # 3. Get AI reply
            # ----------------------------------------------------------------
            from services.assistant import get_reply  # noqa: PLC0415

            reply_text = get_reply(transcription, detected_lang)
            logger.info("AI reply: %r", reply_text[:120])

            # ----------------------------------------------------------------
            # 4. TTS (generate audio; cannot serve local file to Twilio, so
            #    use <Say> to deliver the reply text directly)
            # ----------------------------------------------------------------
            from voice.text_to_speech import speak  # noqa: PLC0415

            tts_path = str(_UPLOADS_DIR / f"twilio_{call_sid}_reply.mp3")
            speak(reply_text, language=detected_lang, output_path=tts_path)
            logger.info("TTS saved to %s (not served — using <Say> instead)", tts_path)

            # ----------------------------------------------------------------
            # 5. Build TwiML response using <Say>
            # ----------------------------------------------------------------
            response.say(reply_text, voice="woman", language="kn-IN")
            response.record(
                max_length=30,
                play_beep=True,
                action="/telephony/respond",
                method="POST",
                timeout=5,
            )

        except Exception as exc:  # noqa: BLE001
            logger.error("process_recording pipeline error: %s", exc, exc_info=True)
            response = VoiceResponse()
            response.say(
                "ಕ್ಷಮಿಸಿ, ತಾಂತ್ರಿಕ ತೊಂದರೆ ಉಂಟಾಗಿದೆ. ದಯವಿಟ್ಟು ಮತ್ತೊಮ್ಮೆ ಪ್ರಯತ್ನಿಸಿ.",
                voice="woman",
                language="kn-IN",
            )

        return str(response)

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
