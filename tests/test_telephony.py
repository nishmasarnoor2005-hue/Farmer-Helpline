"""
tests/test_telephony.py

Tests for M7 telephony adapter:
  - MockAdapter unit tests (handle_incoming_call, stream_audio_input,
    play_audio_response, end_call)
  - Flask route tests (/telephony/status, /telephony/incoming)
"""

import sys
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# MockAdapter unit tests — no Flask needed
# ---------------------------------------------------------------------------

class TestMockAdapterUnit:
    """Unit tests for MockAdapter that exercise the in-memory state."""

    @pytest.fixture(autouse=True)
    def adapter(self):
        from services.telephony.mock_adapter import MockAdapter
        self.adapter = MockAdapter()

    def test_handle_incoming_call_returns_nonempty_session_id(self):
        """handle_incoming_call must return a non-empty string session_id."""
        sid = self.adapter.handle_incoming_call({"caller": "+919876543210"})
        assert isinstance(sid, str)
        assert len(sid) > 0

    def test_handle_incoming_call_creates_active_session(self):
        """New session status must be 'active'."""
        sid = self.adapter.handle_incoming_call({})
        call = self.adapter.get_call(sid)
        assert call["status"] == "active"

    def test_stream_audio_input_appends_byte_length(self):
        """stream_audio_input must append the byte-length of each chunk."""
        sid = self.adapter.handle_incoming_call({})
        self.adapter.stream_audio_input(sid, b"\x00" * 100)
        self.adapter.stream_audio_input(sid, b"\xff" * 250)
        call = self.adapter.get_call(sid)
        assert call["audio_inputs"] == [100, 250]

    def test_stream_audio_input_correct_session(self):
        """stream_audio_input must update only the target session."""
        sid1 = self.adapter.handle_incoming_call({})
        sid2 = self.adapter.handle_incoming_call({})
        self.adapter.stream_audio_input(sid1, b"x" * 42)
        assert self.adapter.get_call(sid1)["audio_inputs"] == [42]
        assert self.adapter.get_call(sid2)["audio_inputs"] == []

    def test_play_audio_response_stores_path(self):
        """play_audio_response must append the audio_path to the session."""
        sid = self.adapter.handle_incoming_call({})
        self.adapter.play_audio_response(sid, "/audio/reply.mp3")
        call = self.adapter.get_call(sid)
        assert call["responses"] == ["/audio/reply.mp3"]

    def test_play_audio_response_multiple_paths(self):
        """Multiple play_audio_response calls must all be recorded."""
        sid = self.adapter.handle_incoming_call({})
        self.adapter.play_audio_response(sid, "/audio/r1.mp3")
        self.adapter.play_audio_response(sid, "/audio/r2.mp3")
        assert self.adapter.get_call(sid)["responses"] == ["/audio/r1.mp3", "/audio/r2.mp3"]

    def test_end_call_sets_status_ended(self):
        """end_call must set status to 'ended'."""
        sid = self.adapter.handle_incoming_call({})
        assert self.adapter.get_call(sid)["status"] == "active"
        self.adapter.end_call(sid)
        assert self.adapter.get_call(sid)["status"] == "ended"

    def test_end_call_sets_ended_flag(self):
        """end_call must also set the 'ended' boolean flag."""
        sid = self.adapter.handle_incoming_call({})
        self.adapter.end_call(sid)
        assert self.adapter.get_call(sid)["ended"] is True


# ---------------------------------------------------------------------------
# Flask route tests — mock out heavy ML imports
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """
    Return a Flask test client with Whisper and Gemini mocked out.
    """
    whisper_patch = patch("faster_whisper.WhisperModel", autospec=True)
    genai_patch = patch("google.genai.Client", autospec=True)

    with whisper_patch, genai_patch:
        if "app" in sys.modules:
            del sys.modules["app"]

        import app as flask_app  # noqa: PLC0415

        flask_app.app.config["TESTING"] = True
        flask_app.app.config["RATELIMIT_ENABLED"] = False

        with flask_app.app.test_client() as c:
            yield c


class TestTelephonyRoutes:
    """Integration tests for /telephony/* routes."""

    def test_status_returns_200(self, client):
        """GET /telephony/status must return HTTP 200."""
        resp = client.get("/telephony/status")
        assert resp.status_code == 200

    def test_status_provider_is_mock(self, client):
        """GET /telephony/status must report provider='mock'."""
        resp = client.get("/telephony/status")
        data = resp.get_json()
        assert data is not None
        assert data["provider"] == "mock"

    def test_status_has_status_field(self, client):
        """GET /telephony/status must include a 'status' key."""
        resp = client.get("/telephony/status")
        data = resp.get_json()
        assert "status" in data

    def test_incoming_returns_session_id(self, client):
        """POST /telephony/incoming must return a non-empty session_id."""
        resp = client.post("/telephony/incoming", json={"caller": "+919876543210"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "session_id" in data
        assert len(data["session_id"]) > 0

    def test_incoming_returns_active_status(self, client):
        """POST /telephony/incoming must return status='active'."""
        resp = client.post("/telephony/incoming", json={})
        data = resp.get_json()
        assert data["status"] == "active"

    def test_respond_echoes_message(self, client):
        """POST /telephony/respond must echo back the message."""
        # First create a session
        incoming = client.post("/telephony/incoming", json={}).get_json()
        sid = incoming["session_id"]

        resp = client.post(
            "/telephony/respond",
            json={"session_id": sid, "message": "What is the price of tomato?"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["session_id"] == sid
        assert "What is the price of tomato?" in data["response"]

    def test_respond_missing_session_returns_error(self, client):
        """POST /telephony/respond with unknown session_id must return 400."""
        resp = client.post(
            "/telephony/respond",
            json={"session_id": "nonexistent-id", "message": "hello"},
        )
        assert resp.status_code == 400
