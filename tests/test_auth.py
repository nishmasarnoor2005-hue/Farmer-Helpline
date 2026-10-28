"""
tests/test_auth.py

Tests for admin authentication routes:
  - Anonymous access to /admin/dashboard redirects to login.
  - Wrong credentials return 401/200 with error message (no redirect).
  - Correct credentials redirect to dashboard.
  - Logout clears the session.
"""

import os
import sys
from unittest.mock import patch

import pytest
from werkzeug.security import generate_password_hash

# ---------------------------------------------------------------------------
# App fixture — creates a test client with a patched Whisper loader so the
# heavy model is never loaded during testing.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    """
    Return a Flask test client.
    Heavy ML imports (WhisperModel, genai) are mocked out so the test suite
    runs without GPU/model files.
    """
    # Patch WhisperModel before app is imported so __init__ doesn't block
    whisper_mock_patch = patch(
        "faster_whisper.WhisperModel",
        autospec=True,
    )
    genai_mock_patch = patch(
        "google.genai.Client",
        autospec=True,
    )

    with whisper_mock_patch, genai_mock_patch:
        # Re-import fresh so patches take effect
        if "app" in sys.modules:
            del sys.modules["app"]

        import app as flask_app  # noqa: PLC0415

        flask_app.app.config["TESTING"] = True
        flask_app.app.config["WTF_CSRF_ENABLED"] = False
        flask_app.app.config["RATELIMIT_ENABLED"] = False  # disable rate limits in tests

        with flask_app.app.test_client() as c:
            yield c


# ---------------------------------------------------------------------------
# Helper: env vars for a valid admin account
# ---------------------------------------------------------------------------

VALID_USERNAME = "testadmin"
VALID_PASSWORD = "s3cur3P@ss!"
VALID_HASH = generate_password_hash(VALID_PASSWORD)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnonymousRedirect:
    def test_dashboard_redirects_to_login(self, client):
        """Unauthenticated GET /admin/dashboard must redirect to /admin/login."""
        resp = client.get("/admin/dashboard", follow_redirects=False)
        assert resp.status_code in (301, 302)
        location = resp.headers.get("Location", "")
        assert "admin/login" in location


class TestLoginFailure:
    def test_wrong_credentials_no_redirect(self, client):
        """POST /admin/login with bad credentials must NOT redirect (200 or 401)."""
        with patch.dict(os.environ, {"ADMIN_USERNAME": VALID_USERNAME, "ADMIN_PASSWORD_HASH": VALID_HASH}):
            resp = client.post(
                "/admin/login",
                data={"username": "wrong", "password": "wrong"},
                follow_redirects=False,
            )
        # Must not redirect
        assert resp.status_code in (200, 401)

    def test_wrong_credentials_shows_generic_error(self, client):
        """Error message must appear in the response body on failed login."""
        with patch.dict(os.environ, {"ADMIN_USERNAME": VALID_USERNAME, "ADMIN_PASSWORD_HASH": VALID_HASH}):
            resp = client.post(
                "/admin/login",
                data={"username": "wrong", "password": "badpassword"},
                follow_redirects=False,
            )
        body = resp.data.decode("utf-8", errors="replace")
        # Generic message — must not reveal which field failed
        assert "Invalid credentials" in body

    def test_missing_env_vars_fails_login(self, client):
        """Login must fail gracefully when env vars are not configured."""
        env = {}
        # Remove relevant keys if present
        env.pop("ADMIN_USERNAME", None)
        env.pop("ADMIN_PASSWORD_HASH", None)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADMIN_USERNAME", None)
            os.environ.pop("ADMIN_PASSWORD_HASH", None)
            resp = client.post(
                "/admin/login",
                data={"username": VALID_USERNAME, "password": VALID_PASSWORD},
                follow_redirects=False,
            )
        assert resp.status_code in (200, 401)


class TestLoginSuccess:
    def test_correct_credentials_redirect_to_dashboard(self, client):
        """Valid credentials must redirect to /admin/dashboard."""
        with patch.dict(os.environ, {"ADMIN_USERNAME": VALID_USERNAME, "ADMIN_PASSWORD_HASH": VALID_HASH}):
            resp = client.post(
                "/admin/login",
                data={"username": VALID_USERNAME, "password": VALID_PASSWORD},
                follow_redirects=False,
            )
        assert resp.status_code in (301, 302)
        location = resp.headers.get("Location", "")
        assert "admin/dashboard" in location

    def test_authenticated_can_access_dashboard(self, client):
        """After login, /admin/dashboard should return 200."""
        with patch.dict(os.environ, {"ADMIN_USERNAME": VALID_USERNAME, "ADMIN_PASSWORD_HASH": VALID_HASH}):
            # Login first
            client.post(
                "/admin/login",
                data={"username": VALID_USERNAME, "password": VALID_PASSWORD},
                follow_redirects=True,
            )
            resp = client.get("/admin/dashboard")
        assert resp.status_code == 200


class TestLogout:
    def test_logout_clears_session(self, client):
        """After logout, /admin/dashboard must redirect to login again."""
        with patch.dict(os.environ, {"ADMIN_USERNAME": VALID_USERNAME, "ADMIN_PASSWORD_HASH": VALID_HASH}):
            # Login
            client.post(
                "/admin/login",
                data={"username": VALID_USERNAME, "password": VALID_PASSWORD},
                follow_redirects=True,
            )
            # Confirm we're in
            resp = client.get("/admin/dashboard")
            assert resp.status_code == 200

            # Logout
            client.post("/admin/logout", follow_redirects=True)

            # Must be redirected away from dashboard now
            resp = client.get("/admin/dashboard", follow_redirects=False)
        assert resp.status_code in (301, 302)
        location = resp.headers.get("Location", "")
        assert "admin/login" in location
