"""
tests/test_realtime_streaming.py

Tests for M4 — Full Chunked TTS Streaming.

Coverage:
  (a) test_split_sentences_english       — 3-sentence English text splits into 3 items
  (b) test_split_sentences_short         — single short string returns [text]
  (c) test_split_sentences_indic         — Devanagari text splits or returns [text] for short chars
  (d) test_stream_yields_transcript_then_done — first event is transcript, last is done
  (e) test_cancel_stops_stream           — pre-set cancel flag produces error/cancelled first
  (f) test_speak_to_bytes_returns_bytes  — speak_to_bytes returns non-empty bytes
"""

import sys
import threading
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider(
    whisper_cb=None,
    gemini_cb=None,
    speak_bytes_cb=None,
    get_lang_cb=None,
):
    """
    Construct a ChunkedTTSProvider with the given callbacks (or safe no-op stubs).
    Matches the existing constructor signature:
        ChunkedTTSProvider(whisper_cb, gemini_cb, speak_bytes_cb, get_lang_cb,
                           classify_intent_cb, weather_cb, market_cb, scheme_cb)
    """
    from services.realtime.chunked_tts_provider import ChunkedTTSProvider

    return ChunkedTTSProvider(
        whisper_cb=whisper_cb or MagicMock(return_value=("", "en")),
        gemini_cb=gemini_cb or MagicMock(return_value=""),
        speak_bytes_cb=speak_bytes_cb or MagicMock(return_value=b""),
        get_lang_cb=get_lang_cb or MagicMock(return_value="en"),
        classify_intent_cb=MagicMock(return_value={"intent": "general", "confidence": 1.0}),
        weather_cb=MagicMock(return_value=None),
        market_cb=MagicMock(return_value=[]),
        scheme_cb=MagicMock(return_value=[]),
    )


# ---------------------------------------------------------------------------
# (a) test_split_sentences_english
# ---------------------------------------------------------------------------

class TestSplitSentencesEnglish:
    def test_three_sentences(self):
        """
        Three well-spaced English sentences (each >= 10 chars) should split
        into exactly 3 items.
        """
        from services.realtime.chunked_tts_provider import split_into_sentences

        result = split_into_sentences(
            "The rain will come tomorrow. How should I protect my crops? Use a tarpaulin cover."
        )
        # Each part must be a non-empty string
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(s, str) and s.strip() for s in result)


# ---------------------------------------------------------------------------
# (b) test_split_sentences_short
# ---------------------------------------------------------------------------

class TestSplitSentencesShort:
    def test_short_returns_original(self):
        """split_into_sentences('Hi') must return ['Hi'] (below min-length threshold)."""
        from services.realtime.chunked_tts_provider import split_into_sentences

        result = split_into_sentences("Hi")
        # The splitter either returns the original text or merges it with adjacent
        # fragments; in any case we must get exactly one element.
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0] == "Hi"


# ---------------------------------------------------------------------------
# (c) test_split_sentences_indic
# ---------------------------------------------------------------------------

class TestSplitSentencesIndic:
    def test_devanagari_danda(self):
        """
        'नमस्ते। कैसे हो? ठीक है।' should return multiple items when each
        resulting fragment is >= 10 chars, or a single-element list if all
        fragments are too short (splitter contract: returns [text] on no valid splits).
        """
        from services.realtime.chunked_tts_provider import split_into_sentences

        text = "नमस्ते। कैसे हो? ठीक है।"
        result = split_into_sentences(text)

        # The result must be a non-empty list of strings
        assert isinstance(result, list)
        assert len(result) >= 1
        assert all(isinstance(s, str) for s in result)
        # All returned fragments should be non-empty
        assert all(s.strip() for s in result)


# ---------------------------------------------------------------------------
# (d) test_stream_yields_transcript_then_done
# ---------------------------------------------------------------------------

class TestStreamYieldsTranscriptThenDone:
    def test_first_transcript_last_done(self):
        """
        With mock callbacks that return a non-empty transcript and reply,
        process_audio_stream must yield:
          - first event: type == 'transcript'
          - last event:  type == 'done'
        """
        # Whisper returns (text, lang_info)
        mock_whisper = MagicMock(return_value=("Test query", "en"))
        # Gemini returns a two-sentence reply
        mock_gemini = MagicMock(return_value="First sentence. Second sentence.")
        # TTS returns small fake MP3 bytes
        mock_tts = MagicMock(return_value=b"\xff\xfb\x90\x00" * 16)
        # Language cache returns "en"
        mock_lang = MagicMock(return_value="en")

        provider = _make_provider(
            whisper_cb=mock_whisper,
            gemini_cb=mock_gemini,
            speak_bytes_cb=mock_tts,
            get_lang_cb=mock_lang,
        )

        events = list(provider.process_audio_stream(
            audio_bytes=b"\x00" * 1024,
            session_id="test-session-d",
            language_code="en",
        ))

        assert len(events) >= 2, f"Expected at least 2 events, got: {events}"
        assert events[0]["type"] == "transcript", f"First event: {events[0]}"
        assert events[-1]["type"] == "done", f"Last event: {events[-1]}"

        # Verify transcript data
        assert events[0]["data"] == "Test query"

        # Verify all events share the same turn_id
        turn_ids = {e.get("turn_id") for e in events}
        assert len(turn_ids) == 1, f"Multiple turn_ids found: {turn_ids}"


# ---------------------------------------------------------------------------
# (e) test_cancel_stops_stream
# ---------------------------------------------------------------------------

class TestCancelStopsStream:
    def test_cancel_during_stream_yields_error_cancelled(self):
        """
        Calling cancel_response() from within a callback (simulating a concurrent
        cancel) must cause the stream to yield type='error' with data='cancelled'
        and stop early.
        """
        provider = _make_provider()
        session_id = "test-session-e"

        # The whisper callback cancels the session mid-way so that the next
        # flag check (after the transcript yield) fires.
        def _whisper_that_cancels(audio_path):
            # Cancel after transcription so the cancel check on re-entry fires
            provider.cancel_response(session_id)
            return ("Some transcribed text here", "en")

        # Replace whisker callback with cancelling version
        provider._whisper_cb = _whisper_that_cancels
        provider._get_lang_cb = MagicMock(return_value="en")

        events = list(provider.process_audio_stream(
            audio_bytes=b"\x00" * 100,
            session_id=session_id,
            language_code="en",
        ))

        # Stream must contain an error event with data='cancelled'
        error_events = [e for e in events if e["type"] == "error" and e["data"] == "cancelled"]
        assert len(error_events) >= 1, (
            f"Expected at least one cancelled error event; got: {events}"
        )


# ---------------------------------------------------------------------------
# (f) test_speak_to_bytes_returns_bytes
# ---------------------------------------------------------------------------

class TestSpeakToBytesReturnBytes:
    def test_returns_bytes_with_mock_edge_tts(self):
        """
        speak_to_bytes('Hello', 'en') with a mocked edge_tts.Communicate must
        return bytes with len > 0.
        """
        import tempfile
        import os

        # We mock edge_tts.Communicate so that its save() writes fake bytes to
        # the temp file that speak_to_bytes creates internally.
        fake_mp3 = b"\xff\xfb\x90\x00" * 32  # 128 bytes of fake MP3

        async def _fake_save(path):
            with open(path, "wb") as f:
                f.write(fake_mp3)

        mock_communicate_instance = MagicMock()
        mock_communicate_instance.save = _fake_save
        mock_communicate_cls = MagicMock(return_value=mock_communicate_instance)

        with patch("edge_tts.Communicate", mock_communicate_cls):
            from voice.text_to_speech import speak_to_bytes
            result = speak_to_bytes("Hello", "en")

        assert isinstance(result, bytes), f"Expected bytes, got {type(result)}"
        assert len(result) > 0, "Expected non-empty bytes"
