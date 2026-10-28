# Voice Pipeline Latency Report

## Hardware Context

- **Platform:** Windows, CPU-only
- **Whisper quantization:** `int8`
- **Whisper CPU threads:** `4`
- **TTS engine:** Edge TTS (async, network-dependent)

---

## Instrumented Stages

The `/process_audio` route captures four consecutive timestamps using
`time.perf_counter()`:

| Variable | Stage start | Stage end | Measures |
|----------|-------------|-----------|---------|
| `t0` | Request entry | — | baseline |
| `t1` | after `detect_language_from_audio` | `t1 - t0 = gemini_detect_ms` | Gemini language detection (audio upload + inference) |
| `t2` | after `transcribe_with_language` | `t2 - t1 = whisper_ms` | Whisper medium transcription |
| `t3` | after `get_reply` | `t3 - t2 = gemini_reply_ms` | Gemini conversational reply |
| `t4` | after `speak` | `t4 - t3 = tts_ms` | Edge TTS synthesis |

All four deltas are written to the `interactions` table in `latency_ms`
(JSON column) on every successful request.

---

## Measurements

> **Measurements require a live audio test run — values below are from code inspection only.**

The numbers in the table are order-of-magnitude estimates derived from
known benchmarks for each component.  They are **not** measured from this
deployment.

| Stage | Estimated range (CPU, int8) |
|-------|-----------------------------|
| Gemini language detect (`gemini_detect_ms`) | 800 ms – 3 000 ms (network round-trip + upload) |
| Whisper medium transcription (`whisper_ms`) | **8 000 ms – 20 000 ms** (dominant bottleneck) |
| Gemini reply (`gemini_reply_ms`) | 1 000 ms – 4 000 ms |
| Edge TTS synthesis (`tts_ms`) | 500 ms – 2 000 ms |
| **Total end-to-end** | **~10 s – 30 s** |

---

## Dominant Bottleneck

**Whisper `medium` on CPU with `int8` quantization.**

The medium model (~1.5 GB) processes audio at approximately real-time speed
on a 4-thread CPU, meaning a 10-second audio clip takes 8–20 seconds to
transcribe.  All other stages are secondary.

---

## Recommendations

### Keep the medium model (current configuration)

The medium model provides the best accuracy-to-size trade-off for
multilingual Indic languages (Kannada, Hindi, Tamil, etc.).  Downgrading to
`small` or `base` noticeably degrades Kannada transcription quality.

### GPU path (if a CUDA GPU is available)

Change two parameters in `app.py` when running on a machine with an NVIDIA
GPU:

```python
whisper_model = WhisperModel(
    "medium",
    device="cuda",          # was "cpu"
    compute_type="float16", # was "int8"
    cpu_threads=4,
)
```

Expected `whisper_ms` with GPU: **800 ms – 2 000 ms** — a 5–10× improvement.

No other code changes are required; the rest of the pipeline is
network-bound (Gemini API) or I/O-bound (Edge TTS) and does not benefit
from GPU acceleration.

### Further optimisations (if GPU is not available)

| Option | Trade-off |
|--------|-----------|
| Use `small` model | Faster (~3–8 s) but lower Indic accuracy |
| Increase `cpu_threads` (8+) | Modest gain on multi-core machines |
| Cache TTS output for repeated phrases | Eliminates TTS latency for common replies |
| Stream Gemini reply | Perceived latency drops but pipeline complexity increases |

---

## Per-request Logging

Every request writes timing data to the SQLite `interactions` table:

```json
{
  "total_latency_ms": 14250,
  "gemini_detect_ms": 1200,
  "whisper_ms": 10800,
  "gemini_reply_ms": 1700,
  "tts_ms": 550
}
```

Query actual measurements with:

```sql
SELECT
    AVG(json_extract(latency_ms, '$.whisper_ms'))       AS avg_whisper_ms,
    AVG(json_extract(latency_ms, '$.gemini_detect_ms')) AS avg_detect_ms,
    AVG(json_extract(latency_ms, '$.gemini_reply_ms'))  AS avg_reply_ms,
    AVG(json_extract(latency_ms, '$.tts_ms'))           AS avg_tts_ms,
    AVG(json_extract(latency_ms, '$.total_latency_ms')) AS avg_total_ms
FROM interactions
WHERE latency_ms IS NOT NULL;
```
