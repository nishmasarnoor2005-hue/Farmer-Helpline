"""
voice/pcma_utils.py

Audio conversion utilities for VoiceLink India WebSocket bot integration.
Handles conversion between MP3, G.711 A-law (PCMA), and raw PCM.

PCMA spec:
  - G.711 A-law encoding
  - 8-bit samples
  - 8 kHz sample rate
  - Mono (1 channel)
  - base64-encoded for WebSocket transport
"""

import audioop
import base64
import io
import logging
import struct
import wave

logger = logging.getLogger(__name__)

SAMPLE_RATE = 8000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit


def mp3_bytes_to_pcma_b64(mp3_bytes: bytes) -> str:
    """
    Convert MP3 audio bytes to G.711 A-law (PCMA) base64 string.

    Pipeline: MP3 → PCM 16-bit (via pydub) → resample to 8 kHz → audioop.lin2alaw → base64

    Args:
        mp3_bytes: Raw MP3 file bytes.

    Returns:
        Base64-encoded PCMA string, or empty string on failure.
    """
    try:
        from pydub import AudioSegment  # lazy import — pydub is optional

        # Decode MP3
        audio = AudioSegment.from_file(io.BytesIO(mp3_bytes), format="mp3")

        # Normalise: mono, 8 kHz, 16-bit
        audio = audio.set_channels(CHANNELS)
        audio = audio.set_frame_rate(SAMPLE_RATE)
        audio = audio.set_sample_width(SAMPLE_WIDTH)

        pcm_bytes = audio.raw_data

        # Convert 16-bit linear PCM → G.711 A-law
        pcma_bytes = audioop.lin2alaw(pcm_bytes, SAMPLE_WIDTH)

        return base64.b64encode(pcma_bytes).decode("ascii")

    except Exception as exc:  # pragma: no cover
        logger.error("mp3_bytes_to_pcma_b64 failed: %s", exc)
        return ""


def pcma_b64_to_pcm_bytes(b64_data: str) -> bytes:
    """
    Convert base64-encoded PCMA to 16-bit linear PCM at 8 kHz.

    Pipeline: base64 decode → audioop.alaw2lin → raw PCM bytes (8 kHz, 16-bit, mono)

    Args:
        b64_data: Base64-encoded G.711 A-law audio string.

    Returns:
        Raw PCM bytes (8 kHz, 16-bit, mono), or empty bytes on failure.
    """
    try:
        pcma_bytes = base64.b64decode(b64_data)
        pcm_bytes = audioop.alaw2lin(pcma_bytes, SAMPLE_WIDTH)
        return pcm_bytes
    except Exception as exc:
        logger.error("pcma_b64_to_pcm_bytes failed: %s", exc)
        return b""


def pcm_bytes_to_wav(pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """
    Wrap raw 16-bit mono PCM bytes in a standard WAV container.

    Useful for feeding raw PCM to Whisper or other WAV-expecting consumers.

    Args:
        pcm_bytes: Raw 16-bit linear PCM samples.
        sample_rate: Sample rate in Hz (default 8000).

    Returns:
        Complete WAV file bytes starting with b'RIFF'.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()
