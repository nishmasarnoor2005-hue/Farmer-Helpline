"""
tests/test_barge_in.py

Python-side tests for M6 barge-in state machine:
  (a) test_cancel_sets_flag            — cancel_response sets the threading.Event
  (b) test_generator_exits_early_on_cancel — process_audio_stream exits early when
                                             cancelled before it starts
  (c) test_db_status_interrupted       — /realtime/audio SSE route records
                                         status="interrupted" in DB when provider
                                         yields a cancelled event
  (d) test_cancel_route_returns_200    — POST /realtime/cancel returns 200
                                         {"cancelled": true}
  (e) test_two_sessions_independent    — cancelling session1 does not set session2's flag
"""

from __future__ import annotations

import io
import json
import sys
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# (a) test_cancel_sets_flag
# ---------------------------------------------------------------------------

class TestCancelSetsFlag:
    def test_cancel_sets_flag(self):
        """cancel_response('sess1') must set the threading.Event for 'sess1'."""
        with patch("faster_whisper.WhisperModel"), \
             patch("google.genai.Client"):
            from services.realtime.chunked_tts_provider import ChunkedTTSProvider

        provider = ChunkedTTSProvider(
            whisper_cb=MagicMock(),
            gemini_cb=MagicMock(),
            speak_bytes_cb=MagicMock(),
            get_lang_cb=MagicMock(return_value="kn"),
            classify_intent_cb=MagicMock(return_value={"intent": "unknown"}),
            weather_cb=MagicMock(return_value=None),
            market_cb=MagicMock(return_value=[]),
            scheme_cb=MagicMock(return_value=[]),
        )

        provider.cancel_response("sess1")

        assert "sess1" in provider._cancel_flags
        assert provider._cancel_flags["sess1"].is_set()


# ---------------------------------------------------------------------------
# (b) test_generator_exits_early_on_cancel
# ---------------------------------------------------------------------------

class TestGeneratorExitsEarlyOnCancel:
    def test_first_event_is_cancelled(self):
        """
        When cancel_response is called BEFORE process_audio_stream, the generator
        must yield exactly one event of type 'error' with data='cancelled'.
        """
        with patch("faster_whisper.WhisperModel"), \
             patch("google.genai.Client"):
            from services.realtime.chunked_tts_provider import ChunkedTTSProvider

        provider = ChunkedTTSProvider(
            whisper_cb=MagicMock(return_value=("hello", "kn")),
            gemini_cb=MagicMock(return_value="Some reply"),
            speak_bytes_cb=MagicMock(return_value=b"\xff\xfb\x00" * 10),
            get_lang_cb=MagicMock(return_value="kn"),
            classify_intent_cb=MagicMock(return_value={"intent": "unknown"}),
            weather_cb=MagicMock(return_value=None),
            market_cb=MagicMock(return_value=[]),
            scheme_cb=MagicMock(return_value=[]),
        )

        session_id = "sess_early_cancel"
        provider.cancel_response(session_id)

        events = list(provider.process_audio_stream(b"\x00" * 100, session_id, "kn"))

        assert len(events) >= 1
        first = events[0]
        assert first["type"] == "error"
        assert first["data"] == "cancelled"


# ---------------------------------------------------------------------------
# (c) test_db_status_interrupted
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app_module_barge_in():
    """
    Import app with Whisper and Gemini mocked out for the barge-in tests.
    """
    env_overrides = {
        "REALTIME_VOICE_ENABLED": "true",
        "OPENAI_API_KEY": "",
    }

    whisper_patch = patch("faster_whisper.WhisperModel", autospec=True)
    genai_patch   = patch("google.genai.Client", autospec=True)

    with whisper_patch, genai_patch:
        for mod in list(sys.modules.keys()):
            if mod in ("app",) or mod.startswith("services.realtime"):
                del sys.modules[mod]

        with patch.dict("os.environ", env_overrides, clear=False):
            import app as flask_app  # noqa: PLC0415

        flask_app.app.config["TESTING"]    = True
        flask_app.app.config["SECRET_KEY"] = "barge-in-test-secret"

        @flask_app.limiter.request_filter
        def _no_limits():  # noqa: ANN202
            return True

        yield flask_app


@pytest.fixture(scope="module")
def client_barge_in(app_module_barge_in):
    with app_module_barge_in.app.test_client() as c:
        yield c


class TestDbStatusInterrupted:
    def test_interrupted_status_written_to_db(self, client_barge_in, app_module_barge_in):
        """
        When the provider yields a cancelled event, the SSE generator must call
        db.log_interaction with status='interrupted'.
        """
        # Create a valid session
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "true"}, clear=False):
            sess_resp = client_barge_in.post("/realtime/session")
        token = sess_resp.get_json()["token"]

        # Mock provider that yields a cancelled event immediately
        mock_provider = MagicMock()
        mock_provider.process_audio_stream.return_value = iter([
            {"type": "error", "data": "cancelled", "turn_id": "t99", "interrupted": True},
        ])
        mock_provider.cancel_response = MagicMock()

        # Capture db.log_interaction calls
        logged_statuses = []

        original_log = None

        def capturing_log(**kwargs):
            logged_statuses.append(kwargs.get("status"))

        with patch.object(app_module_barge_in, "_get_rt_provider", return_value=mock_provider):
            with patch.object(app_module_barge_in.db, "log_interaction", side_effect=capturing_log):
                resp = client_barge_in.post(
                    "/realtime/audio",
                    headers={"X-Session-Token": token},
                    data={"audio": (io.BytesIO(b"\x00" * 100), "audio.webm")},
                    content_type="multipart/form-data",
                )
                # Consume the entire response so the generator runs to completion
                _ = resp.data

        # The finally-block log_interaction should have status="interrupted"
        assert "interrupted" in logged_statuses, (
            f"Expected 'interrupted' in logged statuses, got: {logged_statuses}"
        )


# ---------------------------------------------------------------------------
# (d) test_cancel_route_returns_200
# ---------------------------------------------------------------------------

class TestCancelRouteReturns200:
    def test_cancel_route_returns_200(self, client_barge_in, app_module_barge_in):
        """POST /realtime/cancel with valid token must return 200 {'cancelled': true}."""
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "true"}, clear=False):
            sess_resp = client_barge_in.post("/realtime/session")
        token = sess_resp.get_json()["token"]

        mock_provider = MagicMock()
        mock_provider.cancel_response = MagicMock()

        with patch.object(app_module_barge_in, "_get_rt_provider", return_value=mock_provider):
            resp = client_barge_in.post(
                "/realtime/cancel",
                headers={"X-Session-Token": token},
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["cancelled"] is True


# ---------------------------------------------------------------------------
# (e) test_two_sessions_independent
# ---------------------------------------------------------------------------

class TestTwoSessionsIndependent:
    def test_cancel_session1_does_not_affect_session2(self):
        """
        Cancelling session1 must not set the cancel flag for session2.
        """
        # Use patch without autospec to avoid conflict with already-mocked modules
        with patch("faster_whisper.WhisperModel"), \
             patch("google.genai.Client"):
            from services.realtime.chunked_tts_provider import ChunkedTTSProvider

        provider = ChunkedTTSProvider(
            whisper_cb=MagicMock(),
            gemini_cb=MagicMock(),
            speak_bytes_cb=MagicMock(),
            get_lang_cb=MagicMock(return_value="kn"),
            classify_intent_cb=MagicMock(return_value={"intent": "unknown"}),
            weather_cb=MagicMock(return_value=None),
            market_cb=MagicMock(return_value=[]),
            scheme_cb=MagicMock(return_value=[]),
        )

        # Pre-create session2 flag (as would happen when a stream starts)
        _ = provider._get_cancel_flag("session2")

        # Cancel only session1
        provider.cancel_response("session1")

        # session1 must be set
        assert provider._cancel_flags["session1"].is_set()

        # session2 must NOT be set
        assert not provider._cancel_flags["session2"].is_set(), (
            "Cancelling session1 must not affect session2"
        )
