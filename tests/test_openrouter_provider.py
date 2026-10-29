"""
tests/test_openrouter_provider.py

Mocked unit and integration tests for OpenRouterProvider.

All tests are offline — no real API calls are made.
The openai package is mocked throughout.
"""

from __future__ import annotations

import base64
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_callbacks(reply_text="Test reply. Second sentence."):
    """Return minimal stub callbacks for OpenRouterProvider construction."""
    def whisper_cb(path):
        return "What is the weather today?", "en"

    def speak_bytes_cb(text, lang):
        return b"\xff\xfb\x00" * 10  # tiny fake MP3

    def get_lang_cb(sid):
        return "en"

    def classify_intent_cb(text, lang):
        return {"intent": "weather", "confidence": 0.9}

    def weather_cb(loc):
        return {"location": "Bengaluru", "temperature": 28, "description": "Clear", "humidity": 60}

    def market_cb(crop, loc=None):
        return []

    def scheme_cb(query):
        return []

    return dict(
        whisper_cb=whisper_cb,
        speak_bytes_cb=speak_bytes_cb,
        get_lang_cb=get_lang_cb,
        classify_intent_cb=classify_intent_cb,
        weather_cb=weather_cb,
        market_cb=market_cb,
        scheme_cb=scheme_cb,
    )


def _make_stream_chunks(text: str):
    """Return a list of fake OpenAI streaming delta chunks for *text*."""
    chunks = []
    for char in text:
        delta = SimpleNamespace(content=char)
        choice = SimpleNamespace(delta=delta)
        chunks.append(SimpleNamespace(choices=[choice]))
    # Final chunk with no content
    delta_end = SimpleNamespace(content=None)
    choice_end = SimpleNamespace(delta=delta_end)
    chunks.append(SimpleNamespace(choices=[choice_end]))
    return chunks


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------

class TestIsAvailable:

    def test_false_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        from services.realtime.openrouter_provider import OpenRouterProvider
        p = OpenRouterProvider(**_make_callbacks())
        assert p.is_available() is False

    def test_false_when_openai_not_installed(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
        with patch.dict(sys.modules, {"openai": None}):
            from services.realtime.openrouter_provider import OpenRouterProvider
            p = OpenRouterProvider(**_make_callbacks())
            assert p.is_available() is False

    def test_true_when_key_set_and_openai_installed(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
        from services.realtime.openrouter_provider import OpenRouterProvider
        p = OpenRouterProvider(**_make_callbacks())
        assert p.is_available() is True


# ---------------------------------------------------------------------------
# Free-model guard
# ---------------------------------------------------------------------------

class TestFreeModelGuard:

    def test_refuses_paid_model(self, monkeypatch, caplog):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4o")  # no :free
        import logging
        from services.realtime.openrouter_provider import OpenRouterProvider, _DEFAULT_MODEL
        with caplog.at_level(logging.WARNING, logger="services.realtime.openrouter_provider"):
            p = OpenRouterProvider(**_make_callbacks())
        # Should have fallen back to the default free model
        assert p._model == _DEFAULT_MODEL
        assert "Refusing" in caplog.text or "not end in ':free'" in caplog.text

    def test_accepts_free_model(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        monkeypatch.setenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
        from services.realtime.openrouter_provider import OpenRouterProvider
        p = OpenRouterProvider(**_make_callbacks())
        assert p._model == "nvidia/nemotron-3-ultra-550b-a55b:free"


# ---------------------------------------------------------------------------
# process_audio_stream() — normal flow
# ---------------------------------------------------------------------------

class TestProcessAudioStream:

    def _stream(self, monkeypatch, reply="Hello farmer. Stay safe."):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        monkeypatch.setenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")

        from services.realtime.openrouter_provider import OpenRouterProvider

        fake_chunks = _make_stream_chunks(reply)

        mock_openai_cls = MagicMock()
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = iter(fake_chunks)

        with patch("services.realtime.openrouter_provider.OpenRouterProvider._make_openai_client",
                   return_value=mock_client):
            p = OpenRouterProvider(**_make_callbacks())
            events = list(p.process_audio_stream(b"\x00" * 100, "sess1", "en"))

        return events

    def test_yields_transcript_first(self, monkeypatch):
        events = self._stream(monkeypatch)
        assert events[0]["type"] == "transcript"
        assert events[0]["data"] == "What is the weather today?"

    def test_yields_audio_chunks(self, monkeypatch):
        events = self._stream(monkeypatch)
        audio_events = [e for e in events if e["type"] == "audio_chunk"]
        assert len(audio_events) >= 1

    def test_audio_chunks_are_base64(self, monkeypatch):
        events = self._stream(monkeypatch)
        for e in events:
            if e["type"] == "audio_chunk":
                # Should be decodable base64
                decoded = base64.b64decode(e["data"])
                assert len(decoded) > 0

    def test_yields_done_last(self, monkeypatch):
        events = self._stream(monkeypatch)
        assert events[-1]["type"] == "done"

    def test_all_events_have_turn_id(self, monkeypatch):
        events = self._stream(monkeypatch)
        turn_ids = {e.get("turn_id") for e in events}
        assert len(turn_ids) == 1
        assert None not in turn_ids


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

class TestCancellation:

    def test_cancel_before_stream_yields_error(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        monkeypatch.setenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
        from services.realtime.openrouter_provider import OpenRouterProvider
        p = OpenRouterProvider(**_make_callbacks())

        # Pre-cancel the session
        p.cancel_response("sess_cancel")

        # The flag is set — stream should exit early with error
        events = list(p.process_audio_stream(b"\x00" * 100, "sess_cancel", "en"))
        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) >= 1
        cancelled = [e for e in error_events if e["data"] == "cancelled"]
        assert len(cancelled) >= 1
        assert cancelled[0].get("interrupted") is True

    def test_cancel_sets_flag(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        monkeypatch.setenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
        from services.realtime.openrouter_provider import OpenRouterProvider
        p = OpenRouterProvider(**_make_callbacks())
        p.cancel_response("sess_flag")
        flag = p._get_cancel_flag("sess_flag")
        assert flag.is_set()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:

    def test_missing_api_key_raises_runtime_error_as_event(self, monkeypatch):
        """Provider should yield an error event, not raise, when key is missing."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
        from services.realtime.openrouter_provider import OpenRouterProvider
        p = OpenRouterProvider(**_make_callbacks())
        events = list(p.process_audio_stream(b"\x00" * 100, "sess_nokey", "en"))
        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) >= 1
        assert "key" in error_events[0]["data"].lower() or "transcript" in events[0]["type"]

    def test_503_yields_friendly_error(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        monkeypatch.setenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
        from services.realtime.openrouter_provider import OpenRouterProvider

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError(
            "503 Service Unavailable: model unavailable"
        )

        cbs = _make_callbacks()
        p = OpenRouterProvider(**cbs)

        with patch.object(p, "_make_openai_client", return_value=mock_client):
            events = list(p.process_audio_stream(b"\x00" * 100, "sess_503", "en"))

        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) >= 1
        assert "unavailable" in error_events[0]["data"].lower()

    def test_rate_limit_429_yields_friendly_error(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        monkeypatch.setenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
        from services.realtime.openrouter_provider import OpenRouterProvider

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError(
            "429 rate limit exceeded"
        )

        p = OpenRouterProvider(**_make_callbacks())
        with patch.object(p, "_make_openai_client", return_value=mock_client):
            events = list(p.process_audio_stream(b"\x00" * 100, "sess_429", "en"))

        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) >= 1
        assert "rate" in error_events[0]["data"].lower() or "limit" in error_events[0]["data"].lower()

    def test_no_api_key_in_error_events(self, monkeypatch):
        """Error events must never leak the API key value."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-super-secret-key")
        monkeypatch.setenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
        from services.realtime.openrouter_provider import OpenRouterProvider

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("503 error")

        p = OpenRouterProvider(**_make_callbacks())
        with patch.object(p, "_make_openai_client", return_value=mock_client):
            events = list(p.process_audio_stream(b"\x00" * 100, "sess_leak", "en"))

        for e in events:
            assert "sk-or-super-secret-key" not in str(e)


# ---------------------------------------------------------------------------
# Provider factory routing
# ---------------------------------------------------------------------------

class TestProviderFactoryRouting:

    def test_factory_returns_openrouter_when_key_set(self, monkeypatch):
        monkeypatch.setenv("REALTIME_VOICE_ENABLED", "true")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        monkeypatch.setenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        mock_app = MagicMock()
        mock_app._session_language_cache = {}
        mock_app.whisper_model = MagicMock()

        with patch.dict(sys.modules, {"app": mock_app,
                                       "services.assistant": MagicMock(),
                                       "voice.text_to_speech": MagicMock(),
                                       "services.intent_service": MagicMock()}):
            from services.realtime import provider_factory
            import importlib
            importlib.reload(provider_factory)
            provider = provider_factory.get_provider()
            from services.realtime.openrouter_provider import OpenRouterProvider
            assert isinstance(provider, OpenRouterProvider)

    def test_factory_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.setenv("REALTIME_VOICE_ENABLED", "false")
        from services.realtime.provider_factory import get_provider
        assert get_provider() is None

    def test_factory_prefers_openai_over_openrouter(self, monkeypatch):
        monkeypatch.setenv("REALTIME_VOICE_ENABLED", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        from services.realtime.provider_factory import get_provider
        from services.realtime.openai_realtime_provider import OpenAIRealtimeProvider
        provider = get_provider()
        assert isinstance(provider, OpenAIRealtimeProvider)
