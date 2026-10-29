"""
tests/test_realtime_config.py

Tests for M5 — GET /realtime/config endpoint.

(a) test_config_returns_200          — endpoint returns HTTP 200
(b) test_config_has_required_keys    — all required keys present in JSON
(c) test_config_safe_defaults        — correct defaults when env vars not set
(d) test_config_reads_env_vars       — honours REALTIME_VAD_THRESHOLD override
(e) test_streaming_honest_is_false   — streaming_honest is always False
"""

import sys
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixture — import app once per module with Whisper / Gemini mocked out
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app_module():
    whisper_patch = patch("faster_whisper.WhisperModel", autospec=True)
    genai_patch   = patch("google.genai.Client", autospec=True)

    with whisper_patch, genai_patch:
        for mod in list(sys.modules.keys()):
            if mod in ("app",) or mod.startswith("services.realtime"):
                del sys.modules[mod]

        import app as flask_app  # noqa: PLC0415

    flask_app.app.config["TESTING"]    = True
    flask_app.app.config["SECRET_KEY"] = "config-test-secret"

    @flask_app.limiter.request_filter
    def _no_limits():  # noqa: ANN202
        return True

    yield flask_app


@pytest.fixture(scope="module")
def client(app_module):
    with app_module.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Required keys that must appear in every /realtime/config response
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {
    "vad_threshold",
    "min_speech_ms",
    "min_silence_ms",
    "pre_speech_pad_ms",
    "barge_in_debounce_ms",
    "barge_in_cooldown_ms",
    "provider",
    "streaming_honest",
}


# ---------------------------------------------------------------------------
# (a) test_config_returns_200
# ---------------------------------------------------------------------------

def test_config_returns_200(client):
    """GET /realtime/config must return HTTP 200."""
    resp = client.get("/realtime/config")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# (b) test_config_has_required_keys
# ---------------------------------------------------------------------------

def test_config_has_required_keys(client):
    """Response JSON must contain all required config keys."""
    resp = client.get("/realtime/config")
    data = resp.get_json()
    for key in _REQUIRED_KEYS:
        assert key in data, f"Missing required key: {key}"


# ---------------------------------------------------------------------------
# (c) test_config_safe_defaults
# ---------------------------------------------------------------------------

def test_config_safe_defaults(client):
    """When env vars are absent the endpoint must return documented defaults."""
    env_clear = {
        "REALTIME_VAD_THRESHOLD":         "",
        "REALTIME_VAD_MIN_SPEECH_MS":     "",
        "REALTIME_VAD_MIN_SILENCE_MS":    "",
        "REALTIME_VAD_PRE_SPEECH_PAD_MS": "",
        "REALTIME_BARGE_IN_DEBOUNCE_MS":  "",
        "REALTIME_BARGE_IN_COOLDOWN_MS":  "",
    }
    # We can't truly unset env vars with patch.dict, so instead we patch
    # os.getenv inside the app module to return the default for missing keys.
    import os as _os

    original_getenv = _os.getenv

    def _mock_getenv(key, default=None):
        if key in env_clear:
            return default  # pretend the var is unset — return the default
        return original_getenv(key, default)

    with patch("os.getenv", side_effect=_mock_getenv):
        resp = client.get("/realtime/config")

    data = resp.get_json()
    assert data["vad_threshold"]        == 0.5,  f"Expected 0.5, got {data['vad_threshold']}"
    assert data["min_speech_ms"]        == 250,  f"Expected 250, got {data['min_speech_ms']}"
    assert data["min_silence_ms"]       == 400,  f"Expected 400, got {data['min_silence_ms']}"
    assert data["pre_speech_pad_ms"]    == 100,  f"Expected 100, got {data['pre_speech_pad_ms']}"
    assert data["barge_in_debounce_ms"] == 180,  f"Expected 180, got {data['barge_in_debounce_ms']}"
    assert data["barge_in_cooldown_ms"] == 300,  f"Expected 300, got {data['barge_in_cooldown_ms']}"


# ---------------------------------------------------------------------------
# (d) test_config_reads_env_vars
# ---------------------------------------------------------------------------

def test_config_reads_env_vars(client):
    """Patching REALTIME_VAD_THRESHOLD=0.7 must be reflected in the response."""
    with patch.dict("os.environ", {"REALTIME_VAD_THRESHOLD": "0.7"}, clear=False):
        resp = client.get("/realtime/config")
    data = resp.get_json()
    assert data["vad_threshold"] == pytest.approx(0.7), (
        f"Expected vad_threshold=0.7, got {data['vad_threshold']}"
    )


# ---------------------------------------------------------------------------
# (e) test_streaming_honest_is_false
# ---------------------------------------------------------------------------

def test_streaming_honest_is_false(client):
    """streaming_honest must always be False — this provider does not stream."""
    resp = client.get("/realtime/config")
    data = resp.get_json()
    assert data["streaming_honest"] is False
