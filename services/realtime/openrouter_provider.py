"""
services/realtime/openrouter_provider.py

OpenRouterProvider — uses OpenRouter's OpenAI-compatible chat completions API
with free models for LLM inference, keeping the existing Whisper STT and
Edge TTS pipeline unchanged.

What this provides vs. ChunkedTTSProvider
-----------------------------------------
- LLM inference is handled by OpenRouter free models instead of Gemini.
- Supports streaming token output (stream=True) from OpenRouter, so the
  first sentence can be synthesised and queued while the rest is still
  generating — reducing perceived latency.
- Exact same STT (Whisper), TTS (Edge TTS / gTTS), and agricultural
  context injection as ChunkedTTSProvider.

What this does NOT provide
--------------------------
- True real-time audio streaming — Whisper still requires a complete audio file.
- Sub-500 ms end-to-end latency — network + Whisper + TTS remain the bottleneck.
- OpenAI Realtime WebRTC — OpenRouter is a text/chat completion proxy only.

Free model note
---------------
Free models on OpenRouter (model IDs ending in ":free") have variable
availability and may return 503 when busy. This provider never silently
switches to a paid model — it returns an error event instead.

Required env var: OPENROUTER_API_KEY
Optional env var: OPENROUTER_MODEL (default: nvidia/nemotron-3-ultra-550b-a55b:free)
"""

from __future__ import annotations

import base64
import logging
import os
import re
import tempfile
import threading
import uuid
from typing import Callable, Generator

from services.realtime.base_provider import RealtimeProvider
from services.realtime.chunked_tts_provider import split_into_sentences

logger = logging.getLogger(__name__)

# Safe default free model — user can override via OPENROUTER_MODEL
_DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"

# OpenRouter uses an OpenAI-compatible base URL
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# HTTP timeouts
_CONNECT_TIMEOUT = 10   # seconds to establish connection
_READ_TIMEOUT    = 60   # seconds to wait for first token


def _build_system_prompt(language_code: str) -> str:
    """Return a farming-domain system prompt in the given language."""
    language_names = {
        "kn": "Kannada", "hi": "Hindi", "ml": "Malayalam",
        "en": "English", "ta": "Tamil", "te": "Telugu",
        "mr": "Marathi", "ur": "Urdu",
    }
    lang_name = language_names.get(language_code, "English")
    return (
        "You are an AI agricultural helpline assistant for Indian farmers. "
        "Help with crop diseases, fertilizers, irrigation, weather advice, "
        "government schemes, and market prices. "
        f"Always reply in {lang_name}. Keep answers short (2-4 sentences). "
        "Be warm and practical. Never invent prices, scheme details, or weather values. "
        "If you don't know something, say so and suggest the farmer contact their "
        "local agricultural extension officer."
    )


class OpenRouterProvider(RealtimeProvider):
    """
    LLM inference via OpenRouter free models with chunked sentence TTS.

    Construction: inject the same callbacks as ChunkedTTSProvider so the
    provider_factory can swap providers transparently.
    """

    def __init__(
        self,
        whisper_cb: Callable,
        speak_bytes_cb: Callable,
        get_lang_cb: Callable,
        classify_intent_cb: Callable,
        weather_cb: Callable,
        market_cb: Callable,
        scheme_cb: Callable,
    ) -> None:
        self._whisper_cb         = whisper_cb
        self._speak_bytes_cb     = speak_bytes_cb
        self._get_lang_cb        = get_lang_cb
        self._classify_intent_cb = classify_intent_cb
        self._weather_cb         = weather_cb
        self._market_cb          = market_cb
        self._scheme_cb          = scheme_cb

        self._cancel_flags: dict[str, threading.Event] = {}
        self._flags_lock = threading.Lock()

        # Resolve model once at construction — validates it ends in :free
        raw_model = os.getenv("OPENROUTER_MODEL", _DEFAULT_MODEL).strip()
        if not raw_model.endswith(":free") and ":free" not in raw_model:
            logger.warning(
                "OPENROUTER_MODEL '%s' does not end in ':free' — "
                "this may incur charges. Refusing to use it; "
                "falling back to default free model.", raw_model
            )
            raw_model = _DEFAULT_MODEL
        self._model = raw_model

        logger.info("OpenRouterProvider initialised. model=%s", self._model)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_cancel_flag(self, session_id: str) -> threading.Event:
        with self._flags_lock:
            if session_id not in self._cancel_flags:
                self._cancel_flags[session_id] = threading.Event()
            return self._cancel_flags[session_id]

    def _make_openai_client(self):
        """Create an openai.OpenAI client pointed at OpenRouter."""
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai package not installed. "
                "Run: .venv\\Scripts\\pip install openai"
            ) from exc

        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. "
                "Add it to .env to use OpenRouter."
            )

        return OpenAI(
            base_url=_OPENROUTER_BASE_URL,
            api_key=api_key,
            timeout=_READ_TIMEOUT,
        )

    def _build_messages(
        self,
        transcript: str,
        language_code: str,
        context_data: dict | None,
    ) -> list[dict]:
        """Build the messages list for the chat completions API."""
        system = _build_system_prompt(language_code)

        # Inject verified context so the model never invents facts
        context_parts = []
        if context_data:
            if "weather" in context_data:
                w = context_data["weather"]
                context_parts.append(
                    f"[VERIFIED WEATHER — use ONLY this, do not invent values]\n"
                    f"Location: {w.get('location')}, "
                    f"Temp: {w.get('temperature')}°C, "
                    f"Condition: {w.get('description')}, "
                    f"Humidity: {w.get('humidity')}%"
                )
            if "market_data" in context_data:
                items = context_data["market_data"][:3]  # top 3
                rows = [
                    f"  {i.get('crop','?')} at {i.get('market','?')}: "
                    f"₹{i.get('modal_price','?')}/q ({i.get('data_date','?')})"
                    for i in items
                ]
                context_parts.append(
                    "[VERIFIED MARKET DATA — sample historical, not live]\n"
                    + "\n".join(rows)
                )
            if "scheme_data" in context_data:
                schemes = context_data["scheme_data"][:2]
                names = [s.get("name", "?") for s in schemes]
                context_parts.append(
                    "[VERIFIED SCHEMES]\n" + "; ".join(names)
                )

        if context_parts:
            system += "\n\n" + "\n\n".join(context_parts)

        return [
            {"role": "system", "content": system},
            {"role": "user",   "content": transcript},
        ]

    def _get_reply_streaming(
        self,
        transcript: str,
        language_code: str,
        context_data: dict | None,
        flag: threading.Event,
    ) -> Generator[str, None, None]:
        """
        Call OpenRouter with stream=True, yield text chunks as they arrive.
        Raises RuntimeError on API errors. Checks cancellation flag per chunk.
        """
        client = self._make_openai_client()
        messages = self._build_messages(transcript, language_code, context_data)

        stream = client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=True,
            max_tokens=300,
            temperature=0.4,
            extra_headers={
                "HTTP-Referer": "https://farmer-helpline.local",
                "X-Title": "AI Farmer Helpline",
            },
        )

        for chunk in stream:
            if flag.is_set():
                stream.close()
                return
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    # ------------------------------------------------------------------
    # RealtimeProvider interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if OPENROUTER_API_KEY is set and openai package installed."""
        if not os.getenv("OPENROUTER_API_KEY", "").strip():
            return False
        try:
            import openai  # noqa: F401
            return True
        except ImportError:
            return False

    def process_audio_stream(
        self,
        audio_bytes: bytes,
        session_id: str,
        language_code: str,
    ) -> Generator[dict, None, None]:
        """
        STT (Whisper) → LLM (OpenRouter streaming) → TTS (Edge TTS chunked).

        Streaming behaviour:
        - Tokens arrive from OpenRouter incrementally.
        - We buffer tokens until a sentence boundary is detected.
        - Each complete sentence is immediately sent to Edge TTS and yielded
          as an audio_chunk — so the farmer hears the first sentence while
          the rest is still being generated.
        - This is NOT true audio streaming (Whisper blocks until complete).
          It reduces perceived LLM+TTS latency by pipelining sentence synthesis.
        """
        turn_id = uuid.uuid4().hex
        flag = self._get_cancel_flag(session_id)
        # Only clear the flag if it wasn't pre-set before this turn started.
        # A pre-set flag means cancel_response() was called before the turn began.
        if not flag.is_set():
            flag.clear()  # Reset from previous turn

        tmp_path = None
        try:
            # --------------------------------------------------------
            # 1. Save audio to temp file for Whisper
            # --------------------------------------------------------
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            if flag.is_set():
                yield {"type": "error", "data": "cancelled", "turn_id": turn_id, "interrupted": True}
                return

            # --------------------------------------------------------
            # 2. Language: use cache or supplied code
            # --------------------------------------------------------
            cached_lang = self._get_lang_cb(session_id)
            effective_lang = cached_lang if cached_lang else language_code

            # --------------------------------------------------------
            # 3. Whisper STT
            # --------------------------------------------------------
            try:
                transcript_text, whisper_lang = self._whisper_cb(tmp_path)
                if whisper_lang:
                    effective_lang = whisper_lang
            except Exception as exc:
                yield {"type": "error", "data": f"transcription_failed: {exc}", "turn_id": turn_id}
                return

            if not transcript_text or not transcript_text.strip():
                yield {"type": "error", "data": "empty_transcript", "turn_id": turn_id}
                return

            yield {
                "type": "transcript",
                "data": transcript_text,
                "turn_id": turn_id,
                "language_code": effective_lang,
            }

            if flag.is_set():
                yield {"type": "error", "data": "cancelled", "turn_id": turn_id, "interrupted": True}
                return

            # --------------------------------------------------------
            # 4. Intent + context lookups
            # --------------------------------------------------------
            text_lower = transcript_text.lower()
            context_data = None

            try:
                intent_result = self._classify_intent_cb(transcript_text, effective_lang)
                detected_intent = (
                    intent_result.get("intent", "unknown")
                    if isinstance(intent_result, dict)
                    else str(intent_result)
                )
            except Exception:
                detected_intent = "unknown"

            if detected_intent == "weather" or any(
                kw in text_lower for kw in ("weather", "rain", "temperature")
            ):
                try:
                    wr = self._weather_cb(transcript_text)
                    if wr:
                        context_data = {"weather": wr}
                except Exception:
                    pass

            if detected_intent == "market_price" or any(
                kw in text_lower for kw in ("price", "market", "rate", "mandi")
            ):
                try:
                    mr = self._market_cb(transcript_text, None)
                    if mr:
                        context_data = context_data or {}
                        context_data["market_data"] = mr
                except Exception:
                    pass

            if detected_intent == "government_scheme" or any(
                kw in text_lower for kw in ("scheme", "yojana", "subsidy")
            ):
                try:
                    sr = self._scheme_cb(text_lower)
                    if sr:
                        context_data = context_data or {}
                        context_data["scheme_data"] = sr
                except Exception:
                    pass

            # --------------------------------------------------------
            # 5. OpenRouter LLM — streaming tokens, batched into sentences
            # --------------------------------------------------------
            if flag.is_set():
                yield {"type": "error", "data": "cancelled", "turn_id": turn_id, "interrupted": True}
                return

            sentence_buffer = ""
            # Sentence boundary pattern (same as split_into_sentences)
            boundary_re = re.compile(r'([.!?।|])\s')
            chunk_count = 0

            try:
                for token in self._get_reply_streaming(
                    transcript_text, effective_lang, context_data, flag
                ):
                    if flag.is_set():
                        yield {"type": "error", "data": "cancelled", "turn_id": turn_id, "interrupted": True}
                        return

                    sentence_buffer += token

                    # Check if we have a complete sentence
                    match = boundary_re.search(sentence_buffer)
                    if match:
                        # Extract everything up to and including the boundary
                        end_idx = match.end()
                        sentence = sentence_buffer[:end_idx].strip()
                        sentence_buffer = sentence_buffer[end_idx:].strip()

                        if len(sentence) >= 10:  # Skip trivial fragments
                            if flag.is_set():
                                yield {"type": "error", "data": "cancelled", "turn_id": turn_id, "interrupted": True}
                                return

                            audio_b = self._speak_bytes_cb(sentence, effective_lang)
                            if audio_b:
                                yield {
                                    "type":    "audio_chunk",
                                    "data":    base64.b64encode(audio_b).decode("ascii"),
                                    "turn_id": turn_id,
                                }
                                chunk_count += 1
                                if chunk_count >= 50:  # safety limit
                                    break

            except RuntimeError as api_err:
                # Translate API errors into error events
                err_msg = str(api_err)
                logger.error("OpenRouter API error: %s", err_msg)

                # Map to user-friendly messages without leaking internals
                if "OPENROUTER_API_KEY" in err_msg or "api_key" in err_msg.lower():
                    data = "OpenRouter API key not configured"
                elif "402" in err_msg or "insufficient" in err_msg.lower():
                    data = "OpenRouter account has insufficient credits"
                elif "503" in err_msg or "unavailable" in err_msg.lower():
                    data = "OpenRouter model temporarily unavailable — try again shortly"
                elif "429" in err_msg or "rate" in err_msg.lower():
                    data = "Rate limit reached — please wait a moment"
                elif "paid" in err_msg.lower() or ":free" not in self._model:
                    data = "Refusing to use a non-free model"
                else:
                    data = "LLM service error — please try again"

                yield {"type": "error", "data": data, "turn_id": turn_id}
                return
            except Exception as exc:
                logger.error("OpenRouter unexpected error: %s", exc, exc_info=True)
                yield {"type": "error", "data": "llm_failed", "turn_id": turn_id}
                return

            # --------------------------------------------------------
            # 6. Synthesise any remaining buffer text
            # --------------------------------------------------------
            if sentence_buffer.strip() and not flag.is_set():
                remaining = sentence_buffer.strip()
                if len(remaining) >= 5:
                    audio_b = self._speak_bytes_cb(remaining, effective_lang)
                    if audio_b:
                        yield {
                            "type":    "audio_chunk",
                            "data":    base64.b64encode(audio_b).decode("ascii"),
                            "turn_id": turn_id,
                        }

            # --------------------------------------------------------
            # 7. Done
            # --------------------------------------------------------
            yield {"type": "done", "data": None, "turn_id": turn_id}

        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def cancel_response(self, session_id: str) -> None:
        """Set cancellation flag for the given session."""
        with self._flags_lock:
            if session_id in self._cancel_flags:
                self._cancel_flags[session_id].set()
            else:
                flag = threading.Event()
                flag.set()
                self._cancel_flags[session_id] = flag
