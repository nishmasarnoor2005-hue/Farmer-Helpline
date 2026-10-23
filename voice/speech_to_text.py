# NOTE: This file is NOT used by the Flask app (app.py).
# It is a standalone microphone recording + transcription script
# for local testing only. Run directly: python voice/speech_to_text.py
#
# The Flask app uses faster-whisper directly inside app.py.

import sounddevice as sd
import soundfile as sf
from faster_whisper import WhisperModel


def speech_to_text():
    # Model is loaded inside the function — NOT at module level —
    # to avoid loading a second Whisper model if this file is ever imported.
    print("Loading Whisper base model (standalone test)...")
    model = WhisperModel("base", device="cpu", compute_type="int8")
    print("Whisper model loaded!")

    print("\nSpeak clearly for 8 seconds...")
    input("Press Enter when you are ready: ")

    samplerate = 16000
    duration   = 8

    try:
        audio = sd.rec(
            int(duration * samplerate),
            samplerate=samplerate,
            channels=1,
            dtype="float32"
        )
        sd.wait()

        sf.write("temp.wav", audio, samplerate)

        segments, info = model.transcribe(
            "temp.wav",
            beam_size=3,
            vad_filter=True
        )

        text = " ".join(
            segment.text.strip() for segment in segments
        ).strip()

        print("\nRecognized text:")
        print(text if text else "No speech recognized")

        print("\nDetected language:")
        print(info.language)

        return text, info.language

    except Exception as error:
        print("Speech recognition error:", error)
        return "", "unknown"


if __name__ == "__main__":
    speech_to_text()
