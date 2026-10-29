import time
import sounddevice as sd
import soundfile as sf
from faster_whisper import WhisperModel

AUDIO_FILE = "temp_input.wav"

# Load multilingual Whisper model
model = WhisperModel(
    "large-v3",
    device="cpu",
    compute_type="int8"
)

def speech_to_text():

    print("🎙️ Get ready...")
    time.sleep(2)

    print("🟢 Start speaking now!")
    print("⏳ Recording for 12 seconds...\n")

    samplerate = 16000
    duration = 12

    # Record audio
    audio = sd.rec(
        int(duration * samplerate),
        samplerate=samplerate,
        channels=1,
        dtype="float32"
    )

    sd.wait()

    # Save audio
    sf.write(AUDIO_FILE, audio, samplerate)

    # Transcribe
    segments, info = model.transcribe(
        AUDIO_FILE,
        beam_size=5,
        vad_filter=True
    )

    text = " ".join(segment.text for segment in segments).strip()

    print("📝 Recognized Text:")
    print(text)

    print("\n🌐 Whisper Detected Language:")
    print(info.language)

    return text, info.language


if __name__ == "__main__":
    speech_to_text()