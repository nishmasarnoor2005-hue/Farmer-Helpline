import asyncio
import edge_tts
import os

VOICE_MAP = {
    "Kannada": "kn-IN-SapnaNeural",
    "Tamil": "ta-IN-PallaviNeural",
    "Telugu": "te-IN-ShrutiNeural",
    "Malayalam": "ml-IN-SobhanaNeural",
    "Hindi": "hi-IN-SwaraNeural",
    "Marathi": "mr-IN-AarohiNeural",
    "English": "en-IN-NeerjaNeural"
}

OUTPUT_FILE = "farmer_reply.mp3"


async def speak(text, language):
    voice = VOICE_MAP.get(language, "en-IN-NeerjaNeural")

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice
    )

    await communicate.save(OUTPUT_FILE)

    print(f"🔊 Voice reply saved as {OUTPUT_FILE}")

    # Auto play on Windows
    os.startfile(OUTPUT_FILE)


if __name__ == "__main__":
    asyncio.run(
        speak(
            "ನಮಸ್ಕಾರ ರೈತರೆ, ನಿಮ್ಮ ಧ್ವನಿ ಯಶಸ್ವಿಯಾಗಿ ಗುರುತಿಸಲಾಗಿದೆ.",
            "Kannada"
        )
    )