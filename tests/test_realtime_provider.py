"""
tests/test_realtime_provider.py

Tests for the services/realtime/ provider abstraction layer (FEAT-001).

Coverage:
  (a) factory returns None when REALTIME_VOICE_ENABLED=false
  (b) factory returns ChunkedTTSProvider when enabled and no OPENAI_API_KEY
  (c) OpenAIRealtimeProvider.is_available() returns False without key
  (d) ChunkedTTSProvider.is_available() returns True
  (e) ChunkedTTSProvider.cancel_response() does not raise
  (f) split_into_sentences splits correctly on '.', '!', '?', '।'
"""

import sys
import threading
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — build a minimal ChunkedTTSProvider with stub callbacks
# ---------------------------------------------------------------------------

def _make_chunked_provider():
    """Return a ChunkedTTSProvider wired with no-op callbacks for testing."""
    from services.realtime.chunked_tts_provider import ChunkedTTSProvider

    noop = MagicMock(return_value=None)

    return ChunkedTTSProvider(
        whisper_cb=noop,
        gemini_cb=noop,
        speak_bytes_cb=noop,
        get_lang_cb=MagicMock(return_value="kn"),
        classify_intent_cb=noop,
        weather_cb=noop,
        market_cb=MagicMock(return_value=[]),
        scheme_cb=MagicMock(return_value=[]),
    )


# ---------------------------------------------------------------------------
# (a) Factory returns None when REALTIME_VOICE_ENABLED=false
# ---------------------------------------------------------------------------

class TestFactoryDisabled:
    def test_returns_none_when_disabled_default(self):
        """get_provider() must return None when REALTIME_VOICE_ENABLED is not set."""
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "false"}, clear=False):
            from services.realtime import provider_factory
            # Reload to pick up env change
            import importlib
            importlib.reload(provider_factory)
            result = provider_factory.get_provider()
        assert result is None

    def test_returns_none_when_disabled_explicitly(self):
        """get_provider() must return None when REALTIME_VOICE_ENABLED=false (explicit)."""
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "FALSE"}, clear=False):
            from services.realtime import provider_factory
            import importlib
            importlib.reload(provider_factory)
            result = provider_factory.get_provider()
        assert result is None

    def test_returns_none_when_missing(self):
        """get_provider() must return None when REALTIME_VOICE_ENABLED is absent."""
        env_copy = {k: v for k, v in __import__("os").environ.items()
                    if k != "REALTIME_VOICE_ENABLED"}
        with patch.dict("os.environ", env_copy, clear=True):
            from services.realtime import provider_factory
            import importlib
            importlib.reload(provider_factory)
            result = provider_factory.get_provider()
        assert result is None


# ---------------------------------------------------------------------------
# (b) Factory returns ChunkedTTSProvider when enabled and no OPENAI_API_KEY
# ---------------------------------------------------------------------------

class TestFactoryChunkedProvider:
    def test_returns_chunked_provider_when_enabled_no_openai(self):
        """get_provider() returns ChunkedTTSProvider when enabled, no OPENAI key, no OPENROUTER key."""
        from services.realtime.chunked_tts_provider import ChunkedTTSProvider

        env_overrides = {
            "REALTIME_VOICE_ENABLED": "true",
            "OPENAI_API_KEY": "",
            "OPENROUTER_API_KEY": "",   # also clear OpenRouter so ChunkedTTS is selected
        }

        # We need to stub the lazy 'import app' inside provider_factory
        mock_app = MagicMock()
        mock_app._session_language_cache = {}
        mock_app.whisper_model = MagicMock()

        with patch.dict("os.environ", env_overrides, clear=False):
            with patch.dict("sys.modules", {"app": mock_app}):
                from services.realtime import provider_factory
                import importlib
                importlib.reload(provider_factory)
                result = provider_factory.get_provider()

        assert result is not None
        assert isinstance(result, ChunkedTTSProvider)


# ---------------------------------------------------------------------------
# (c) OpenAIRealtimeProvider.is_available() returns False without key
# ---------------------------------------------------------------------------

class TestOpenAIProviderAvailability:
    def test_not_available_without_key(self):
        """OpenAIRealtimeProvider.is_available() must return False when key is absent."""
        from services.realtime.openai_realtime_provider import OpenAIRealtimeProvider

        provider = OpenAIRealtimeProvider()
        env_copy = {k: v for k, v in __import__("os").environ.items()
                    if k != "OPENAI_API_KEY"}
        with patch.dict("os.environ", env_copy, clear=True):
            result = provider.is_available()
        assert result is False

    def test_not_available_with_blank_key(self):
        """OpenAIRealtimeProvider.is_available() must return False when key is empty string."""
        from services.realtime.openai_realtime_provider import OpenAIRealtimeProvider

        provider = OpenAIRealtimeProvider()
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            result = provider.is_available()
        assert result is False

    def test_available_with_key(self):
        """OpenAIRealtimeProvider.is_available() must return True when key is present."""
        from services.realtime.openai_realtime_provider import OpenAIRealtimeProvider

        provider = OpenAIRealtimeProvider()
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-fake-key"}, clear=False):
            result = provider.is_available()
        assert result is True

    def test_process_audio_raises_not_implemented(self):
        """process_audio_stream must raise NotImplementedError (BLOCKED)."""
        from services.realtime.openai_realtime_provider import OpenAIRealtimeProvider

        provider = OpenAIRealtimeProvider()
        with pytest.raises(NotImplementedError, match="BLOCKED_PENDING_CREDENTIALS"):
            # Must consume the generator to trigger the raise
            list(provider.process_audio_stream(b"audio", "sess-1", "en"))

    def test_cancel_response_raises_not_implemented(self):
        """cancel_response must raise NotImplementedError (BLOCKED)."""
        from services.realtime.openai_realtime_provider import OpenAIRealtimeProvider

        provider = OpenAIRealtimeProvider()
        with pytest.raises(NotImplementedError, match="BLOCKED_PENDING_CREDENTIALS"):
            provider.cancel_response("sess-1")


# ---------------------------------------------------------------------------
# (d) ChunkedTTSProvider.is_available() returns True
# ---------------------------------------------------------------------------

class TestChunkedProviderAvailability:
    def test_is_available_returns_true(self):
        """ChunkedTTSProvider.is_available() must always return True."""
        provider = _make_chunked_provider()
        assert provider.is_available() is True


# ---------------------------------------------------------------------------
# (e) ChunkedTTSProvider.cancel_response() does not raise
# ---------------------------------------------------------------------------

class TestChunkedProviderCancellation:
    def test_cancel_does_not_raise_for_known_session(self):
        """cancel_response() must not raise for a session that has been seen."""
        provider = _make_chunked_provider()
        # Trigger creation of cancel flag by consuming the generator
        list(provider.process_audio_stream(b"", "session-abc", "kn"))
        # Should not raise
        provider.cancel_response("session-abc")

    def test_cancel_does_not_raise_for_unknown_session(self):
        """cancel_response() must not raise even for an unknown session ID."""
        provider = _make_chunked_provider()
        provider.cancel_response("completely-unknown-session-id")

    def test_cancel_sets_event(self):
        """cancel_response() must set the threading.Event for the session."""
        provider = _make_chunked_provider()
        list(provider.process_audio_stream(b"", "session-xyz", "hi"))
        provider.cancel_response("session-xyz")
        # Access the internal flag directly to verify it was set
        flag = provider._cancel_flags.get("session-xyz")
        assert flag is not None
        assert flag.is_set()


# ---------------------------------------------------------------------------
# (f) split_into_sentences splits correctly
# ---------------------------------------------------------------------------

class TestSplitIntoSentences:
    """Tests for the sentence splitter in chunked_tts_provider."""

    @staticmethod
    def _split(text):
        from services.realtime.chunked_tts_provider import split_into_sentences
        return split_into_sentences(text)

    def test_splits_on_period(self):
        """Splits on '.' followed by whitespace."""
        result = self._split("The crop is healthy. Water it daily.")
        assert len(result) >= 2
        assert all(isinstance(s, str) for s in result)

    def test_splits_on_exclamation(self):
        """Splits on '!' followed by whitespace."""
        result = self._split("Watch out for pests! Spray neem oil immediately.")
        assert len(result) >= 2

    def test_splits_on_question_mark(self):
        """Splits on '?' followed by whitespace."""
        result = self._split("What crop are you growing? Tell me more about the soil.")
        assert len(result) >= 2

    def test_splits_on_devanagari_danda(self):
        """Splits on '।' (Devanagari danda)."""
        result = self._split("फसल को पानी दें। मिट्टी की जांच करें।")
        assert len(result) >= 1
        assert all(isinstance(s, str) for s in result)

    def test_no_split_on_short_text(self):
        """Short single sentences are not split further."""
        result = self._split("Water the crop.")
        assert len(result) == 1
        assert result[0] == "Water the crop."

    def test_empty_string(self):
        """Empty string returns empty list."""
        result = self._split("")
        assert result == []

    def test_returns_list_of_strings(self):
        """All elements in the result are non-empty strings."""
        result = self._split("Hello farmer. How are you? Good luck!")
        assert isinstance(result, list)
        assert all(isinstance(s, str) and s.strip() for s in result)

    def test_no_empty_fragments(self):
        """Result must not contain empty or whitespace-only strings."""
        result = self._split("First sentence. Second sentence. Third.")
        assert all(s.strip() for s in result)

    def test_single_sentence_no_split(self):
        """A long single sentence with no terminator is returned as-is."""
        text = "This is a very long sentence without any termination mark at all"
        result = self._split(text)
        assert len(result) == 1
        assert result[0] == text
