"""
voice/tts_worker.py

Standalone Edge TTS subprocess worker.
Called by speak() via subprocess.run() to escape gevent's event loop patching.

Usage (internal — called by text_to_speech.py):
    python tts_worker.py <voice> <output_path> <text>

Exits 0 on success, 1 on failure.
"""

import sys
import asyncio


async def _run(voice: str, output_path: str, text: str) -> None:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: tts_worker.py <voice> <output_path> <text>", file=sys.stderr)
        sys.exit(1)

    voice       = sys.argv[1]
    output_path = sys.argv[2]
    text        = " ".join(sys.argv[3:])   # rejoin in case text has spaces

    try:
        asyncio.run(_run(voice, output_path, text))
        sys.exit(0)
    except Exception as e:
        print(f"TTS error: {e}", file=sys.stderr)
        sys.exit(1)
