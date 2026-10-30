"""
tests/test_pcma_utils.py

Unit tests for voice/pcma_utils.py — PCMA/PCM audio conversion utilities.
"""

import audioop
import base64
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voice.pcma_utils import (
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    mp3_bytes_to_pcma_b64,
    pcm_bytes_to_wav,
    pcma_b64_to_pcm_bytes,
)


def _make_pcma_b64(num_samples: int = 160) -> str:
    """Generate a short burst of silent PCMA audio as base64."""
    silent_pcm = b"\x00\x00" * num_samples  # 16-bit silent PCM
    pcma_bytes = audioop.lin2alaw(silent_pcm, SAMPLE_WIDTH)
    return base64.b64encode(pcma_bytes).decode("ascii")


class TestPcmaB64ToPcmBytes:
    def test_returns_nonempty_bytes_for_valid_input(self):
        b64 = _make_pcma_b64()
        result = pcma_b64_to_pcm_bytes(b64)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_output_length_is_double_input(self):
        """alaw2lin expands each 8-bit sample to 16-bit (×2 bytes)."""
        num_samples = 160
        b64 = _make_pcma_b64(num_samples)
        pcma_raw = audioop.lin2alaw(b"\x00\x00" * num_samples, SAMPLE_WIDTH)
        result = pcma_b64_to_pcm_bytes(b64)
        assert len(result) == len(pcma_raw) * SAMPLE_WIDTH

    def test_invalid_base64_returns_empty_bytes(self):
        result = pcma_b64_to_pcm_bytes("!!!not-valid-base64!!!")
        assert result == b""

    def test_empty_string_returns_empty_bytes(self):
        result = pcma_b64_to_pcm_bytes("")
        assert result == b""


class TestPcmBytesToWav:
    def test_output_starts_with_riff(self):
        pcm = b"\x00\x00" * 160
        wav = pcm_bytes_to_wav(pcm)
        assert wav[:4] == b"RIFF"

    def test_output_contains_wave_marker(self):
        pcm = b"\x00\x00" * 160
        wav = pcm_bytes_to_wav(pcm)
        assert wav[8:12] == b"WAVE"

    def test_empty_pcm_still_produces_valid_wav(self):
        wav = pcm_bytes_to_wav(b"")
        assert wav[:4] == b"RIFF"
        assert len(wav) >= 44  # WAV header is 44 bytes minimum

    def test_custom_sample_rate_accepted(self):
        pcm = b"\x00\x00" * 160
        wav = pcm_bytes_to_wav(pcm, sample_rate=16000)
        assert wav[:4] == b"RIFF"


class TestMp3BytesToPcmaB64:
    def _minimal_mp3(self) -> bytes:
        """Try to import pydub and generate a tiny MP3 for testing."""
        try:
            from pydub import AudioSegment
            from pydub.generators import Sine
            tone = Sine(440).to_audio_segment(duration=200)  # 200 ms
            buf = __import__("io").BytesIO()
            tone.export(buf, format="mp3")
            return buf.getvalue()
        except Exception:
            return b""

    def test_returns_nonempty_base64_string(self):
        mp3_data = self._minimal_mp3()
        if not mp3_data:
            pytest.skip("pydub/ffmpeg not available — skipping MP3 conversion test")
        result = mp3_bytes_to_pcma_b64(mp3_data)
        assert isinstance(result, str)
        assert len(result) > 0
        # Must be valid base64
        decoded = base64.b64decode(result)
        assert len(decoded) > 0

    def test_invalid_mp3_returns_empty_string(self):
        result = mp3_bytes_to_pcma_b64(b"not-an-mp3")
        assert result == ""

    def test_empty_bytes_returns_empty_string(self):
        result = mp3_bytes_to_pcma_b64(b"")
        assert result == ""


class TestPcmaRoundtrip:
    def test_pcma_encode_decode_preserves_signal(self):
        """
        Encode a known PCM signal to PCMA and back.
        A-law compression is lossy so exact equality is not expected,
        but the decoded signal must be non-zero and non-empty.
        """
        # 160 samples of a simple square wave
        pcm = bytes([0x7F, 0x00] * 160)  # alternating high/low bytes
        pcma_bytes = audioop.lin2alaw(pcm, SAMPLE_WIDTH)
        b64 = base64.b64encode(pcma_bytes).decode("ascii")

        recovered = pcma_b64_to_pcm_bytes(b64)
        assert isinstance(recovered, bytes)
        assert len(recovered) > 0
        # At least some non-zero samples (signal was not silent)
        assert any(b != 0 for b in recovered)
