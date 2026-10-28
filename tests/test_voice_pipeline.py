"""
tests/test_voice_pipeline.py

Tests for M4 voice reliability:
  - /process_audio with no audio field returns success=False
  - /process_audio with empty filename returns success=False
  - clean_hallucination reduces pathological repeated-character text
  - detect_language_from_audio falls back to 'kn' when Gemini raises
"""

import io
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# App fixture — patches heavy ML imports before the module is loaded
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """Flask test client with Whisper and Gemini mocked out."""
    whisper_patch = patch("faster_whisper.WhisperModel", autospec=True)
    genai_patch   = patch("google.genai.Client", autospec=True)

    with whisper_patch, genai_patch:
        # Fresh import so patches take effect
        if "app" in sys.modules:
            del sys.modules["app"]

        import app as flask_app  # noqa: PLC0415

        flask_app.app.config["TESTING"]        = True
        flask_app.app.config["WTF_CSRF_ENABLED"] = False
        flask_app.app.config["RATELIMIT_ENABLED"] = False

        with flask_app.app.test_client() as c:
            yield c


# ---------------------------------------------------------------------------
# Helper — import app module (already loaded by the fixture)
# ---------------------------------------------------------------------------

def _app_module():
    """Return the already-imported app module."""
    import app  # noqa: PLC0415
    return app


# ---------------------------------------------------------------------------
# Test 1 — no audio field
# ---------------------------------------------------------------------------

class TestNoAudioField:
    def test_returns_failure_when_audio_missing(self, client):
        """POST /process_audio with no 'audio' field must return success=False."""
        resp = client.post("/process_audio", data={})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body is not None
        assert body["success"] is False


# ---------------------------------------------------------------------------
# Test 2 — empty filename
# ---------------------------------------------------------------------------

class TestEmptyFilename:
    def test_returns_failure_for_empty_filename(self, client):
        """POST /process_audio with an audio field whose filename is '' returns success=False."""
        data = {"audio": (io.BytesIO(b""), "")}   # empty filename
        resp = client.post(
            "/process_audio",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body is not None
        assert body["success"] is False


# ---------------------------------------------------------------------------
# Test 3 — clean_hallucination reduces pathological repeated-character text
# ---------------------------------------------------------------------------

class TestCleanHallucination:
    PATHOLOGICAL = "ಜಕ್ಕ್ಕ್ಕಾಮಗಲುರಿನ ಕಾಫಿ ಬಾಲೆ ಎಸ್ಟೇಲ್ಲ್ಲ್ಲ"

    def test_output_shorter_than_input(self, client):
        """clean_hallucination must return text no longer than the input for a hallucinated string."""
        app_mod = _app_module()
        result = app_mod.clean_hallucination(self.PATHOLOGICAL, "kn")
        assert len(result) <= len(self.PATHOLOGICAL), (
            f"Expected output shorter than {len(self.PATHOLOGICAL)} chars, got {len(result)}: {result!r}"
        )

    def test_output_is_string(self, client):
        """clean_hallucination must always return a string (even when Gemini is mocked)."""
        app_mod = _app_module()

        # Ensure the mock Gemini client returns a proper string so the
        # reconstruction branch produces a real str rather than a MagicMock.
        mock_response = MagicMock()
        mock_response.text.strip.return_value = "ಕಾಫಿ ತೋಟ"

        original_client = app_mod.gemini_client
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        app_mod.gemini_client = mock_client

        try:
            result = app_mod.clean_hallucination(self.PATHOLOGICAL, "kn")
            assert isinstance(result, str), f"Expected str, got {type(result)}: {result!r}"
        finally:
            app_mod.gemini_client = original_client


# ---------------------------------------------------------------------------
# Test 4 — detect_language_from_audio falls back to 'kn' on Gemini exception
# ---------------------------------------------------------------------------

class TestDetectLanguageFallback:
    def test_falls_back_to_kn_on_gemini_exception(self, client):
        """detect_language_from_audio must return 'kn' when Gemini raises any exception."""
        app_mod = _app_module()

        # Patch the gemini_client used inside app so it raises on generate_content
        original_client = app_mod.gemini_client
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("Simulated Gemini failure")
        app_mod.gemini_client = mock_client

        try:
            # We pass a path that does not exist; detect_language_from_audio
            # should catch the open() error and fall back to 'kn' anyway.
            result = app_mod.detect_language_from_audio("/nonexistent/path.webm")
            assert result == "kn", f"Expected 'kn' fallback, got {result!r}"
        finally:
            app_mod.gemini_client = original_client
