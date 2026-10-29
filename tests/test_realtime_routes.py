"""
tests/test_realtime_routes.py

Tests for FEAT-002 realtime voice routes:
  (a) POST /realtime/session with REALTIME_VOICE_ENABLED=false  → 503
  (b) POST /realtime/session with enabled=true                  → 200 + session_id
  (c) POST /realtime/audio without X-Session-Token              → 401
  (d) POST /realtime/audio with valid token                     → text/event-stream
  (e) POST /realtime/cancel                                     → 200
  (f) DELETE /realtime/session                                  → 200
  (g) GET /realtime/config                                      → 200 + expected keys
"""

import io
import json
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app_module():
    """
    Import app with Whisper and Gemini mocked out.
    Sets REALTIME_VOICE_ENABLED=true so provider_factory returns a real provider.
    """
    env_overrides = {
        "REALTIME_VOICE_ENABLED": "true",
        "OPENAI_API_KEY": "",
    }

    whisper_patch = patch("faster_whisper.WhisperModel", autospec=True)
    genai_patch   = patch("google.genai.Client", autospec=True)

    with whisper_patch, genai_patch:
        # Remove cached modules so patches take effect cleanly
        for mod in list(sys.modules.keys()):
            if mod in ("app",) or mod.startswith("services.realtime"):
                del sys.modules[mod]

        with patch.dict("os.environ", env_overrides, clear=False):
            import app as flask_app  # noqa: PLC0415

        flask_app.app.config["TESTING"]   = True
        flask_app.app.config["SECRET_KEY"] = "rt-test-secret"

        # Bypass all rate limits in tests — flask-limiter 3.x ignores
        # RATELIMIT_ENABLED; using a request_filter is the correct approach.
        @flask_app.limiter.request_filter
        def _no_limits_in_tests():  # noqa: ANN202
            return True

        yield flask_app


@pytest.fixture(scope="module")
def client(app_module):
    with app_module.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Helper — create a valid session token via the API
# ---------------------------------------------------------------------------

def _create_session(client, app_module):
    """POST /realtime/session and return (token, session_id)."""
    with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "true"}, clear=False):
        # Temporarily force the app module env check
        orig = app_module.os.environ.get("REALTIME_VOICE_ENABLED", "false")
        resp = client.post("/realtime/session")
    data = resp.get_json()
    return data.get("token"), data.get("session_id")


# ---------------------------------------------------------------------------
# (a) POST /realtime/session disabled → 503
# ---------------------------------------------------------------------------

class TestRealtimeSessionDisabled:
    def test_returns_503_when_disabled(self, client):
        """POST /realtime/session must return 503 when REALTIME_VOICE_ENABLED=false."""
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "false"}, clear=False):
            resp = client.post("/realtime/session")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["error"] == "realtime_disabled"
        assert "legacy_url" in data

    def test_legacy_url_points_to_process_audio(self, client):
        """503 response must include legacy_url=/process_audio."""
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "false"}, clear=False):
            resp = client.post("/realtime/session")
        data = resp.get_json()
        assert data["legacy_url"] == "/process_audio"


# ---------------------------------------------------------------------------
# (b) POST /realtime/session enabled → 200 + session_id
# ---------------------------------------------------------------------------

class TestRealtimeSessionEnabled:
    def test_returns_200_with_session_id(self, client):
        """POST /realtime/session must return 200 with session_id when enabled."""
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "true"}, clear=False):
            resp = client.post("/realtime/session")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "session_id" in data
        assert isinstance(data["session_id"], str)
        assert len(data["session_id"]) > 0

    def test_returns_token(self, client):
        """Response must include a non-empty token."""
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "true"}, clear=False):
            resp = client.post("/realtime/session")
        data = resp.get_json()
        assert "token" in data
        assert isinstance(data["token"], str)
        assert len(data["token"]) > 10

    def test_returns_capabilities(self, client):
        """Response must include capabilities dict with expected keys."""
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "true"}, clear=False):
            resp = client.post("/realtime/session")
        data = resp.get_json()
        assert "capabilities" in data
        caps = data["capabilities"]
        assert "provider" in caps
        assert "streaming" in caps
        assert "barge_in" in caps

    def test_returns_expires_in(self, client):
        """Response must include expires_in integer."""
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "true"}, clear=False):
            resp = client.post("/realtime/session")
        data = resp.get_json()
        assert "expires_in" in data
        assert isinstance(data["expires_in"], int)


# ---------------------------------------------------------------------------
# (c) POST /realtime/audio without X-Session-Token → 401
# ---------------------------------------------------------------------------

class TestRealtimeAudioNoToken:
    def test_returns_401_without_token(self, client):
        """POST /realtime/audio without X-Session-Token must return 401."""
        resp = client.post("/realtime/audio")
        assert resp.status_code == 401

    def test_returns_401_with_wrong_token(self, client):
        """POST /realtime/audio with an invalid token must return 401."""
        resp = client.post(
            "/realtime/audio",
            headers={"X-Session-Token": "totally-invalid-token-xyz"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# (d) POST /realtime/audio with valid token → text/event-stream
# ---------------------------------------------------------------------------

class TestRealtimeAudioStream:
    def test_returns_event_stream_content_type(self, client, app_module):
        """POST /realtime/audio must return text/event-stream with a valid token."""
        # Create session
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "true"}, clear=False):
            sess_resp = client.post("/realtime/session")
        sess_data  = sess_resp.get_json()
        token      = sess_data["token"]

        # Build a minimal audio stub
        audio_data = b"\x00" * 100

        # Mock the provider so we don't actually call Whisper/Gemini
        mock_provider = MagicMock()
        mock_provider.process_audio_stream.return_value = iter([
            {"type": "transcript", "data": "test", "turn_id": "t1"},
            {"type": "done",       "data": None,   "turn_id": "t1"},
        ])
        mock_provider.cancel_response = MagicMock()

        with patch.object(app_module, "_get_rt_provider", return_value=mock_provider):
            resp = client.post(
                "/realtime/audio",
                headers={"X-Session-Token": token},
                data={"audio": (io.BytesIO(audio_data), "audio.webm")},
                content_type="multipart/form-data",
            )

        assert "text/event-stream" in resp.content_type

    def test_sse_contains_events(self, client, app_module):
        """SSE stream must contain at least one 'data:' line."""
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "true"}, clear=False):
            sess_resp = client.post("/realtime/session")
        sess_data = sess_resp.get_json()
        token     = sess_data["token"]

        mock_provider = MagicMock()
        mock_provider.process_audio_stream.return_value = iter([
            {"type": "transcript", "data": "hello",  "turn_id": "t2"},
            {"type": "done",       "data": None,      "turn_id": "t2"},
        ])
        mock_provider.cancel_response = MagicMock()

        with patch.object(app_module, "_get_rt_provider", return_value=mock_provider):
            resp = client.post(
                "/realtime/audio",
                headers={"X-Session-Token": token},
                data={"audio": (io.BytesIO(b"\x00" * 100), "audio.webm")},
                content_type="multipart/form-data",
            )

        body = resp.data.decode("utf-8")
        assert "data:" in body


# ---------------------------------------------------------------------------
# (e) POST /realtime/cancel → 200
# ---------------------------------------------------------------------------

class TestRealtimeCancel:
    def test_returns_200_with_valid_token(self, client, app_module):
        """POST /realtime/cancel must return 200 {cancelled: true}."""
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "true"}, clear=False):
            sess_resp = client.post("/realtime/session")
        token = sess_resp.get_json()["token"]

        mock_provider = MagicMock()
        with patch.object(app_module, "_get_rt_provider", return_value=mock_provider):
            resp = client.post(
                "/realtime/cancel",
                headers={"X-Session-Token": token},
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["cancelled"] is True

    def test_returns_401_without_token(self, client):
        """POST /realtime/cancel without token must return 401."""
        resp = client.post("/realtime/cancel")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# (f) DELETE /realtime/session → 200
# ---------------------------------------------------------------------------

class TestRealtimeDeleteSession:
    def test_returns_200_with_valid_token(self, client):
        """DELETE /realtime/session must return 200 {ended: true}."""
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "true"}, clear=False):
            sess_resp = client.post("/realtime/session")
        token = sess_resp.get_json()["token"]

        resp = client.delete(
            "/realtime/session",
            headers={"X-Session-Token": token},
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ended"] is True

    def test_token_removed_after_delete(self, client):
        """After DELETE /realtime/session the token should no longer be valid."""
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "true"}, clear=False):
            sess_resp = client.post("/realtime/session")
        token = sess_resp.get_json()["token"]

        client.delete("/realtime/session", headers={"X-Session-Token": token})

        # A subsequent call with the same token should return 401
        resp = client.post("/realtime/cancel", headers={"X-Session-Token": token})
        assert resp.status_code == 401

    def test_returns_401_without_token(self, client):
        """DELETE /realtime/session without token must return 401."""
        resp = client.delete("/realtime/session")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# (g) GET /realtime/config → 200 + all expected keys
# ---------------------------------------------------------------------------

class TestRealtimeConfig:
    _REQUIRED_KEYS = {
        "vad_threshold",
        "min_speech_ms",
        "min_silence_ms",
        "barge_in_debounce_ms",
        "barge_in_cooldown_ms",
        "provider",
        "streaming_honest",
    }

    def test_returns_200(self, client):
        """GET /realtime/config must return 200."""
        resp = client.get("/realtime/config")
        assert resp.status_code == 200

    def test_contains_all_required_keys(self, client):
        """Response must contain all required config keys."""
        resp = client.get("/realtime/config")
        data = resp.get_json()
        for key in self._REQUIRED_KEYS:
            assert key in data, f"Missing key: {key}"

    def test_streaming_honest_is_false(self, client):
        """streaming_honest must be False (we do not support true streaming)."""
        resp = client.get("/realtime/config")
        data = resp.get_json()
        assert data["streaming_honest"] is False

    def test_vad_threshold_is_float(self, client):
        """vad_threshold must be a float."""
        resp = client.get("/realtime/config")
        data = resp.get_json()
        assert isinstance(data["vad_threshold"], float)

    def test_int_fields(self, client):
        """min_speech_ms, min_silence_ms, barge_in_debounce_ms, barge_in_cooldown_ms must be ints."""
        resp = client.get("/realtime/config")
        data = resp.get_json()
        for key in ("min_speech_ms", "min_silence_ms", "barge_in_debounce_ms", "barge_in_cooldown_ms"):
            assert isinstance(data[key], int), f"{key} should be int, got {type(data[key])}"
