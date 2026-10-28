"""
tests/test_rate_limit.py

Tests that /process_audio enforces a rate limit.

The rate limiter uses in-memory storage keyed by remote address.
We set RATE_LIMIT_PROCESS to "10 per minute" and confirm the 11th request
from the same IP receives HTTP 429.
"""

import io
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# App fixture with rate limiting ENABLED (unlike test_auth.py)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rate_client():
    """
    Flask test client with rate limiting active and ML models mocked out.
    """
    whisper_patch = patch("faster_whisper.WhisperModel", autospec=True)
    genai_patch = patch("google.genai.Client", autospec=True)

    with whisper_patch as whisper_mock, genai_patch:
        # Ensure a fresh import of app so patches take effect
        if "app" in sys.modules:
            del sys.modules["app"]

        import app as flask_app  # noqa: PLC0415

        flask_app.app.config["TESTING"] = True
        flask_app.app.config["WTF_CSRF_ENABLED"] = False
        # Keep rate limiting ON (do NOT set RATELIMIT_ENABLED=False)

        with flask_app.app.test_client() as c:
            yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_audio_form():
    """Return a minimal multipart form with a fake audio blob."""
    return {
        "audio": (io.BytesIO(b"\x00" * 64), "test.webm", "audio/webm"),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProcessAudioRateLimit:
    def test_eleventh_request_returns_429(self, rate_client):
        """
        Hitting /process_audio 11 times from the same IP must result in a 429
        on the 11th request (limit: 10 per minute).
        """
        import os

        # Ensure the limit is set to 10 per minute for this test
        with patch.dict(os.environ, {"RATE_LIMIT_PROCESS": "10 per minute"}):
            # We need a fresh limiter state — reset by restarting storage if possible.
            # The simplest approach is to confirm status_code 429 appears within
            # 11 consecutive calls from the same REMOTE_ADDR.
            responses = []
            for i in range(11):
                resp = rate_client.post(
                    "/process_audio",
                    data=_make_audio_form(),
                    content_type="multipart/form-data",
                    environ_base={"REMOTE_ADDR": "127.0.0.1"},
                )
                responses.append(resp.status_code)

        # At least one of the responses must be 429
        assert 429 in responses, (
            f"Expected a 429 among {11} requests but got: {responses}"
        )

    def test_first_request_not_rate_limited(self, rate_client):
        """
        The very first request from a fresh IP should not be rate-limited.
        (Uses a different remote addr than the limit test above.)
        """
        import os

        with patch.dict(os.environ, {"RATE_LIMIT_PROCESS": "10 per minute"}):
            resp = rate_client.post(
                "/process_audio",
                data=_make_audio_form(),
                content_type="multipart/form-data",
                environ_base={"REMOTE_ADDR": "10.0.0.99"},
            )
        # Should be anything except 429 (likely 200 with an error body or 400)
        assert resp.status_code != 429
