"""
services/realtime/provider_factory.py

Factory function that selects and constructs the appropriate RealtimeProvider
based on environment configuration.

Selection logic
---------------
1. If REALTIME_VOICE_ENABLED != "true" (case-insensitive), return None.
   The caller (app.py route) must fall back to the legacy pipeline.

2. If OPENAI_API_KEY is set (non-empty), return OpenAIRealtimeProvider.
   Note: currently BLOCKED_PENDING_CREDENTIALS — is_available() returns True
   but all operational methods raise NotImplementedError.

3. Otherwise return ChunkedTTSProvider with all service callbacks injected
   from the existing service modules (lazy imports to avoid circular imports).

Lazy imports
------------
All service module imports happen inside get_provider(), not at module level.
This prevents circular-import errors when app.py imports provider_factory and
provider_factory would otherwise import app.py-level singletons (whisper_model,
gemini_client, etc.).  The factory is called at request time, by which point all
modules are fully loaded.
"""

from __future__ import annotations

import os

from services.realtime.base_provider import RealtimeProvider


def get_provider() -> "RealtimeProvider | None":
    """
    Return the configured RealtimeProvider, or None if real-time mode is disabled.

    Returns:
        A RealtimeProvider instance if REALTIME_VOICE_ENABLED=true, else None.

    Never raises — all import/construction errors are caught and logged; on
    failure the function returns None so the legacy pipeline handles the request.
    """
    enabled = os.getenv("REALTIME_VOICE_ENABLED", "false").strip().lower()
    if enabled != "true":
        return None

    try:
        # --- OpenAI Realtime (BLOCKED_PENDING_CREDENTIALS) ---
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if openai_key:
            from services.realtime.openai_realtime_provider import OpenAIRealtimeProvider
            return OpenAIRealtimeProvider()

        # --- Chunked TTS (existing pipeline, always available) ---
        from services.realtime.chunked_tts_provider import ChunkedTTSProvider

        # Lazy-import existing service modules to avoid circular imports
        import app as _app  # noqa: PLC0415 — intentional lazy import

        def _whisper_cb(audio_path: str):
            """Transcribe audio file using the app's shared Whisper model."""
            segments, info = _app.whisper_model.transcribe(
                audio_path,
                beam_size=3,
                vad_filter=True,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text, info.language

        from services.assistant import get_reply as _gemini_cb_raw  # noqa: PLC0415
        from voice.text_to_speech import speak as _speak_raw  # noqa: PLC0415
        from services.intent_service import classify_intent as _intent_cb  # noqa: PLC0415
        from services import weather_service as _ws  # noqa: PLC0415
        from services import market_service as _ms  # noqa: PLC0415
        from services import scheme_service as _ss  # noqa: PLC0415

        def _speak_bytes_cb(text: str, language: str) -> bytes | None:
            """
            Synthesise speech and return raw MP3 bytes.
            Uses a temporary file since Edge TTS saves to disk.
            """
            import tempfile, os as _os  # noqa: PLC0415, E401
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                result = _speak_raw(text, language, output_path=tmp_path)
                if result and _os.path.exists(tmp_path):
                    with open(tmp_path, "rb") as f:
                        return f.read()
                return None
            finally:
                try:
                    _os.unlink(tmp_path)
                except OSError:
                    pass

        def _get_lang_cb(session_id: str) -> str:
            """Return cached language for session, defaulting to 'kn'."""
            return _app._session_language_cache.get(session_id, "kn")

        def _weather_cb(location: str) -> dict | None:
            try:
                return _ws.get_weather(location)
            except Exception:
                return None

        def _market_cb(crop: str, location: str | None = None) -> list:
            try:
                return _ms.get_market_prices(crop, location)
            except Exception:
                return []

        def _scheme_cb(query: str) -> list:
            try:
                return _ss.get_schemes(query)
            except Exception:
                return []

        return ChunkedTTSProvider(
            whisper_cb=_whisper_cb,
            gemini_cb=_gemini_cb_raw,
            speak_bytes_cb=_speak_bytes_cb,
            get_lang_cb=_get_lang_cb,
            classify_intent_cb=_intent_cb,
            weather_cb=_weather_cb,
            market_cb=_market_cb,
            scheme_cb=_scheme_cb,
        )

    except Exception as exc:  # pragma: no cover — import errors at startup
        import logging
        logging.getLogger(__name__).error(
            "provider_factory: failed to construct provider: %s", exc, exc_info=True
        )
        return None
