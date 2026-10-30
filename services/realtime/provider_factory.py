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

3. If OPENROUTER_API_KEY is set (non-empty) and openai package is installed,
   return OpenRouterProvider — uses free OpenRouter models for LLM inference
   with existing Whisper STT and Edge TTS.

4. Otherwise return ChunkedTTSProvider with all service callbacks injected
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

import logging
import os

from services.realtime.base_provider import RealtimeProvider

_log = logging.getLogger(__name__)


def _build_callbacks():
    """
    Build and return all service callbacks needed by any provider.
    Kept in one place so both OpenRouterProvider and ChunkedTTSProvider
    receive the same injected dependencies.
    """
    import app as _app  # noqa: PLC0415 — intentional lazy import

    from services.assistant import get_reply as _gemini_cb_raw      # noqa: PLC0415
    from voice.text_to_speech import speak as _speak_raw             # noqa: PLC0415
    from services.intent_service import classify_intent as _intent_cb # noqa: PLC0415
    from services import weather_service as _ws                       # noqa: PLC0415
    from services import market_service as _ms                        # noqa: PLC0415
    from services import scheme_service as _ss                        # noqa: PLC0415

    def whisper_cb(audio_path: str):
        segments, info = _app._get_whisper().transcribe(
            audio_path, beam_size=3, vad_filter=True,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text, info.language

    def gemini_cb(text: str, language: str, context_data):
        return _gemini_cb_raw(text, language, context_data)

    def speak_bytes_cb(text: str, language: str):
        import tempfile, os as _os  # noqa: E401
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

    def get_lang_cb(session_id: str) -> str:
        return _app._session_language_cache.get(session_id, "kn")

    def weather_cb(location: str):
        try:
            return _ws.get_weather(location)
        except Exception:
            return None

    def market_cb(crop: str, location=None):
        try:
            return _ms.get_market_prices(crop, location)
        except Exception:
            return []

    def scheme_cb(query: str):
        try:
            return _ss.get_schemes(query)
        except Exception:
            return []

    return dict(
        whisper_cb=whisper_cb,
        gemini_cb=gemini_cb,
        speak_bytes_cb=speak_bytes_cb,
        get_lang_cb=get_lang_cb,
        classify_intent_cb=_intent_cb,
        weather_cb=weather_cb,
        market_cb=market_cb,
        scheme_cb=scheme_cb,
    )


def get_provider() -> "RealtimeProvider | None":
    """
    Return the configured RealtimeProvider, or None if real-time mode is disabled.

    Never raises — all import/construction errors are caught and logged; on
    failure the function returns None so the legacy pipeline handles the request.
    """
    enabled = os.getenv("REALTIME_VOICE_ENABLED", "false").strip().lower()
    if enabled != "true":
        return None

    try:
        # ------------------------------------------------------------------
        # 1. OpenAI Realtime (BLOCKED_PENDING_CREDENTIALS)
        # ------------------------------------------------------------------
        if os.getenv("OPENAI_API_KEY", "").strip():
            from services.realtime.openai_realtime_provider import OpenAIRealtimeProvider
            return OpenAIRealtimeProvider()

        # ------------------------------------------------------------------
        # Build shared callbacks (used by both OpenRouter and ChunkedTTS)
        # ------------------------------------------------------------------
        cbs = _build_callbacks()

        # ------------------------------------------------------------------
        # 2. OpenRouter — free models, preferred when OPENROUTER_API_KEY is set
        # ------------------------------------------------------------------
        if os.getenv("OPENROUTER_API_KEY", "").strip():
            try:
                import openai  # noqa: F401 — availability check only
                from services.realtime.openrouter_provider import OpenRouterProvider
                provider = OpenRouterProvider(
                    whisper_cb=cbs["whisper_cb"],
                    speak_bytes_cb=cbs["speak_bytes_cb"],
                    get_lang_cb=cbs["get_lang_cb"],
                    classify_intent_cb=cbs["classify_intent_cb"],
                    weather_cb=cbs["weather_cb"],
                    market_cb=cbs["market_cb"],
                    scheme_cb=cbs["scheme_cb"],
                )
                if provider.is_available():
                    _log.info(
                        "provider_factory: using OpenRouterProvider (model=%s)",
                        os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"),
                    )
                    return provider
            except Exception as exc:
                _log.warning(
                    "provider_factory: OpenRouter unavailable (%s), "
                    "falling back to ChunkedTTS", exc
                )

        # ------------------------------------------------------------------
        # 3. ChunkedTTSProvider — always available, uses Gemini for LLM
        # ------------------------------------------------------------------
        from services.realtime.chunked_tts_provider import ChunkedTTSProvider
        return ChunkedTTSProvider(
            whisper_cb=cbs["whisper_cb"],
            gemini_cb=cbs["gemini_cb"],
            speak_bytes_cb=cbs["speak_bytes_cb"],
            get_lang_cb=cbs["get_lang_cb"],
            classify_intent_cb=cbs["classify_intent_cb"],
            weather_cb=cbs["weather_cb"],
            market_cb=cbs["market_cb"],
            scheme_cb=cbs["scheme_cb"],
        )

    except Exception as exc:  # pragma: no cover
        _log.error(
            "provider_factory: failed to construct provider: %s", exc, exc_info=True
        )
        return None
