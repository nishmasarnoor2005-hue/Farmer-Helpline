"""
tests/test_health.py

Tests for the GET /health endpoint (FR-17).

Verified properties:
  - Returns HTTP 200.
  - Response JSON has exactly the expected keys.
  - No env-var values appear in the response body (value secrecy).
  - DB check is mocked so no real DB is needed.
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    """
    Return a Flask test client with heavy ML imports mocked out so the
    test suite runs without GPU/model files.
    """
    whisper_mock_patch = patch(
        "faster_whisper.WhisperModel",
        autospec=True,
    )
    genai_mock_patch = patch(
        "google.genai.Client",
        autospec=True,
    )

    with whisper_mock_patch, genai_mock_patch:
        if "app" in sys.modules:
            del sys.modules["app"]

        import app as flask_app  # noqa: PLC0415

        flask_app.app.config["TESTING"] = True
        flask_app.app.config["WTF_CSRF_ENABLED"] = False
        flask_app.app.config["RATELIMIT_ENABLED"] = False

        with flask_app.app.test_client() as c:
            yield c


# ---------------------------------------------------------------------------
# Helper: a fake sqlite3 connection that satisfies the health check
# ---------------------------------------------------------------------------


def _make_sqlite_mock():
    """Return a mock sqlite3 module whose connect() succeeds."""
    fake_conn = MagicMock()
    fake_conn.execute.return_value = MagicMock()
    fake_sqlite = MagicMock()
    fake_sqlite.connect.return_value = fake_conn
    return fake_sqlite


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHealthStatus:
    def test_returns_200(self, client):
        """GET /health must return HTTP 200."""
        with patch("sqlite3.connect", return_value=_make_sqlite_mock().connect()):
            resp = client.get("/health")
        assert resp.status_code == 200

    def test_response_is_json(self, client):
        """GET /health must respond with JSON content-type."""
        with patch("sqlite3.connect", return_value=_make_sqlite_mock().connect()):
            resp = client.get("/health")
        assert resp.is_json or resp.content_type.startswith("application/json")


class TestHealthKeys:
    EXPECTED_KEYS = {"status", "db", "gemini_key", "edge_tts", "whisper", "timestamp"}

    def test_has_exactly_expected_keys(self, client):
        """Response JSON must contain exactly the specified keys — no more, no less."""
        with patch("sqlite3.connect", return_value=_make_sqlite_mock().connect()):
            resp = client.get("/health")
        data = json.loads(resp.data)
        assert set(data.keys()) == self.EXPECTED_KEYS

    def test_status_is_ok(self, client):
        """The top-level 'status' field must be 'ok'."""
        with patch("sqlite3.connect", return_value=_make_sqlite_mock().connect()):
            resp = client.get("/health")
        data = json.loads(resp.data)
        assert data["status"] == "ok"

    def test_timestamp_ends_with_z(self, client):
        """Timestamp must be an ISO 8601 UTC string ending with 'Z'."""
        with patch("sqlite3.connect", return_value=_make_sqlite_mock().connect()):
            resp = client.get("/health")
        data = json.loads(resp.data)
        assert isinstance(data["timestamp"], str)
        assert data["timestamp"].endswith("Z")

    def test_whisper_value_is_valid(self, client):
        """whisper field must be either 'loaded' or 'error'."""
        with patch("sqlite3.connect", return_value=_make_sqlite_mock().connect()):
            resp = client.get("/health")
        data = json.loads(resp.data)
        assert data["whisper"] in ("loaded", "error")

    def test_db_value_is_valid(self, client):
        """db field must be either 'ok' or 'error'."""
        with patch("sqlite3.connect", return_value=_make_sqlite_mock().connect()):
            resp = client.get("/health")
        data = json.loads(resp.data)
        assert data["db"] in ("ok", "error")

    def test_gemini_key_value_is_valid(self, client):
        """gemini_key field must be either 'configured' or 'missing'."""
        with patch("sqlite3.connect", return_value=_make_sqlite_mock().connect()):
            resp = client.get("/health")
        data = json.loads(resp.data)
        assert data["gemini_key"] in ("configured", "missing")


class TestHealthDbMock:
    def test_db_ok_when_connection_succeeds(self, client):
        """When the DB query succeeds, db field must be 'ok'."""
        with patch("sqlite3.connect", return_value=_make_sqlite_mock().connect()):
            resp = client.get("/health")
        data = json.loads(resp.data)
        assert data["db"] == "ok"

    def test_db_error_when_connection_fails(self, client):
        """When the DB connection raises, db field must be 'error'."""
        with patch("sqlite3.connect", side_effect=Exception("DB unavailable")):
            resp = client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["db"] == "error"


class TestHealthSecrecy:
    def test_gemini_key_value_not_in_response(self, client):
        """The actual GEMINI_API_KEY value must never appear in the response body."""
        fake_key = "SUPER_SECRET_FAKE_KEY_abc123xyz"
        with patch.dict(os.environ, {"GEMINI_API_KEY": fake_key}):
            with patch("sqlite3.connect", return_value=_make_sqlite_mock().connect()):
                resp = client.get("/health")
        body = resp.data.decode("utf-8", errors="replace")
        assert fake_key not in body

    def test_gemini_key_configured_when_set(self, client):
        """gemini_key reports 'configured' when GEMINI_API_KEY is non-empty."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "any-non-empty-value"}):
            with patch("sqlite3.connect", return_value=_make_sqlite_mock().connect()):
                resp = client.get("/health")
        data = json.loads(resp.data)
        assert data["gemini_key"] == "configured"

    def test_gemini_key_missing_when_unset(self, client):
        """gemini_key reports 'missing' when GEMINI_API_KEY is absent or empty."""
        env_without_key = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        with patch.dict(os.environ, env_without_key, clear=True):
            with patch("sqlite3.connect", return_value=_make_sqlite_mock().connect()):
                resp = client.get("/health")
        data = json.loads(resp.data)
        assert data["gemini_key"] == "missing"
