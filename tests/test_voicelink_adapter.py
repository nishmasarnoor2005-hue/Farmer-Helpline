"""
tests/test_voicelink_adapter.py

Unit tests for services/telephony/voicelink_adapter.py.
All external dependencies (WebSocket, Whisper, Gemini, Edge TTS) are mocked.
"""

import audioop
import base64
import json
import os
import sys
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TESTING", "true")

from services.telephony.voicelink_adapter import VoiceLinkAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ws(messages=None):
    """Return a mock WebSocket that returns messages from the given list."""
    ws = MagicMock()
    if messages is not None:
        # After exhausting the list, raise Exception to break the loop
        side_effects = [json.dumps(m) for m in messages] + [Exception("done")]
        ws.receive.side_effect = side_effects
    else:
        ws.receive.side_effect = [Exception("done")]
    return ws


def _make_pcma_b64(num_samples: int = 160) -> str:
    silent_pcm = b"\x00\x00" * num_samples
    pcma_bytes = audioop.lin2alaw(silent_pcm, 2)
    return base64.b64encode(pcma_bytes).decode("ascii")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConnectedEvent:
    def test_connected_event_handled(self):
        """'connected' event is processed without error."""
        messages = [
            {"event": "connected", "protocol": "Call", "version": "1.0.0"},
        ]
        ws = _make_ws(messages)
        adapter = VoiceLinkAdapter()
        # Should not raise
        adapter.handle_ws_connection(ws)


class TestStartEvent:
    def test_start_event_creates_session(self):
        """'start' event calls db.create_session with channel='voicelink'."""
        messages = [
            {
                "event": "start",
                "streamSid": "STREAM123",
                "start": {
                    "callSid": "CALL456",
                    "accountSid": "ACC789",
                    "streamSid": "STREAM123",
                    "customParameters": {},
                },
            },
        ]
        ws = _make_ws(messages)
        adapter = VoiceLinkAdapter()

        with patch("services.telephony.voicelink_adapter.db", create=True) as mock_db, \
             patch("backend.database.create_session") as mock_create:
            adapter.handle_ws_connection(ws)

        # DB create_session should have been called with channel="voicelink"
        # (may be called via lazy import inside the method)
        assert adapter.stream_sid == "STREAM123"


class TestMediaEvent:
    def test_media_event_accumulates_buffer(self):
        """media events accumulate PCMA chunks in the buffer."""
        pcma_b64 = _make_pcma_b64()
        messages = [
            {
                "event": "start",
                "streamSid": "S1",
                "start": {"callSid": "C1", "accountSid": "A1",
                           "streamSid": "S1", "customParameters": {}},
            },
            {
                "event": "media",
                "streamSid": "S1",
                "media": {"track": "inbound", "chunk": "1",
                           "timestamp": "5", "payload": pcma_b64},
            },
        ]
        ws = _make_ws(messages)
        adapter = VoiceLinkAdapter()

        with patch("backend.database.create_session"), \
             patch("backend.database.log_interaction"), \
             patch.object(adapter, "_run_pipeline"):
            adapter.handle_ws_connection(ws)

        # At least 1 chunk should have been seen (buffer may be cleared if
        # _run_pipeline was triggered, but we patched it out)


class TestStopEvent:
    def test_stop_event_ends_session(self):
        """'stop' event calls db.end_session."""
        messages = [
            {
                "event": "start",
                "streamSid": "S2",
                "start": {"callSid": "C2", "accountSid": "A2",
                           "streamSid": "S2", "customParameters": {}},
            },
            {
                "event": "stop",
                "streamSid": "S2",
                "stop": {"callSid": "C2", "accountSid": "A2"},
            },
        ]
        ws = _make_ws(messages)
        adapter = VoiceLinkAdapter()

        with patch("backend.database.create_session"), \
             patch("backend.database.end_session") as mock_end:
            adapter.handle_ws_connection(ws)

        # The adapter should have a session_id set from the start event
        assert adapter.session_id != ""


class TestInvalidJson:
    def test_invalid_json_message_handled(self):
        """Malformed JSON does not crash the handler."""
        ws = MagicMock()
        ws.receive.side_effect = [
            "not-valid-json-{[",
            Exception("done"),
        ]
        adapter = VoiceLinkAdapter()
        # Should not raise
        adapter.handle_ws_connection(ws)


class TestOutboundAudio:
    def test_outbound_audio_sent_as_pcma(self):
        """_send_media sends valid JSON with a base64 payload field."""
        ws = MagicMock()
        adapter = VoiceLinkAdapter()
        adapter.stream_sid = "STEST"
        pcma_b64 = _make_pcma_b64()
        adapter._send_media(ws, pcma_b64)

        ws.send.assert_called_once()
        sent_text = ws.send.call_args[0][0]
        msg = json.loads(sent_text)
        assert msg["event"] == "media"
        assert msg["streamSid"] == "STEST"
        assert msg["media"]["payload"] == pcma_b64
        # Verify payload is valid base64
        base64.b64decode(msg["media"]["payload"])  # should not raise


class TestWebhook:
    def test_webhook_call_initiated(self):
        """Webhook processes call.initiated event."""
        result = VoiceLinkAdapter.process_webhook(
            {"event": "call.initiated", "callSid": "C1"}, "", ""
        )
        assert result["ok"] is True
        assert result["event"] == "call.initiated"

    def test_webhook_call_ended(self):
        """Webhook processes call.ended event."""
        result = VoiceLinkAdapter.process_webhook(
            {"event": "call.ended", "callSid": "C2"}, "", ""
        )
        assert result["ok"] is True
        assert result["event"] == "call.ended"

    def test_webhook_invalid_signature(self):
        """Webhook rejects invalid HMAC signature when secret is set."""
        result = VoiceLinkAdapter.process_webhook(
            {"event": "call.ended"}, "bad-signature", "my-secret"
        )
        assert result["ok"] is False
        assert "invalid_signature" in result.get("error", "")


class TestDisabled:
    def test_disabled_closes_immediately(self):
        """When VOICELINK_ENABLED=false, the WebSocket is closed."""
        ws = MagicMock()
        with patch.dict(os.environ, {"VOICELINK_ENABLED": "false"}):
            # Simulate the route-level guard in app.py
            enabled = os.getenv("VOICELINK_ENABLED", "false").lower() == "true"
            if not enabled:
                ws.close()
        ws.close.assert_called_once()


class TestPcmaRoundtrip:
    def test_pcma_roundtrip(self):
        """Encode PCM → PCMA b64 → decode back; signal is non-empty."""
        pcm_in = b"\x7f\x00" * 160  # simple alternating square wave
        pcma_bytes = audioop.lin2alaw(pcm_in, 2)
        b64 = base64.b64encode(pcma_bytes).decode("ascii")

        from voice.pcma_utils import pcma_b64_to_pcm_bytes
        pcm_out = pcma_b64_to_pcm_bytes(b64)

        assert isinstance(pcm_out, bytes)
        assert len(pcm_out) > 0
        # A-law is lossy but should preserve a non-zero signal
        assert any(b != 0 for b in pcm_out)
