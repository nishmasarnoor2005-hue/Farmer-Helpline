import os
import asyncio
import sounddevice as sd
import soundfile as sf
from faster_whisper import WhisperModel

from services.assistant import get_reply
from voice.text_to_speech import speak


# =========================================================
# SETTINGS
# =========================================================

AUDIO_FILE = "temp_call.wav"

# Your working microphone device
MIC_DEVICE = 9

# Your working microphone sample rate
SAMPLE_RATE = 48000

# Whisper model
MODEL_SIZE = "large-v3"


# =========================================================
# LOAD WHISPER MODEL
# =========================================================

print("Loading Whisper model...")

model = WhisperModel(
    MODEL_SIZE,
    device="cpu",
    compute_type="int8"
)

print("Whisper model loaded successfully!")


# =========================================================
# RECORD VOICE UNTIL SILENCE
# =========================================================

def record_voice():

    print("\n🎙️ Speak now...")
    print("The system will automatically stop after you stop speaking.")
    print("🗣️ Hearing your voice...")

    audio_parts = []

    block_duration = 0.1
    block_size = int(SAMPLE_RATE * block_duration)

    silence_threshold = 0.015
    silence_seconds_needed = 1.5

    silence_blocks_needed = int(
        silence_seconds_needed / block_duration
    )

    silence_count = 0
    voice_started = False

    try:

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=MIC_DEVICE,
            blocksize=block_size
        ) as stream:

            while True:

                audio_block, overflowed = stream.read(block_size)

                audio_parts.append(audio_block.copy())

                volume = abs(audio_block).mean()

                # Detect when farmer starts speaking
                if volume > silence_threshold:

                    voice_started = True
                    silence_count = 0

                # After voice starts, count silence
                elif voice_started:

                    silence_count += 1

                # Stop after enough silence
                if (
                    voice_started
                    and silence_count >= silence_blocks_needed
                ):

                    print("🤫 You stopped speaking.")
                    break

        # Check whether anything was recorded
        if not voice_started:

            print("⚠️ No voice detected.")

            return False

        # Combine all audio blocks
        audio = sf.blocks

        import numpy as np

        recorded_audio = np.concatenate(
            audio_parts,
            axis=0
        )

        # Save recording
        sf.write(
            AUDIO_FILE,
            recorded_audio,
            SAMPLE_RATE
        )

        print("✅ Recording completed.")

        return True

    except Exception as e:

        print("❌ Microphone Error:", e)

        return False


# =========================================================
# SPEECH TO TEXT
# CURRENT TEST MODE: KANNADA
# =========================================================

def speech_to_text():

    try:

        print("⏳ Understanding your speech...")

        segments, info = model.transcribe(
            AUDIO_FILE,
            language="kn",
            task="transcribe",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            temperature=0.0
        )

        text = ""

        for segment in segments:

            text += segment.text

        text = text.strip()

        print("\n🔍 Whisper language:")
        print(info.language)

        return text, "kn"

    except Exception as e:

        print("❌ Whisper Error:", e)

        return "", "unknown"


# =========================================================
# CHECK IF CALL SHOULD END
# =========================================================

def should_end_call(text):

    text_lower = text.lower()

    end_words = [
        "goodbye",
        "bye",
        "stop call",
        "end call",
        "hang up",
        "exit",
        "quit",
        "ಕಾಲ್ ನಿಲ್ಲಿಸಿ",
        "ಕರೆ ನಿಲ್ಲಿಸಿ",
        "ನಿಲ್ಲಿಸಿ"
    ]

    for word in end_words:

        if word in text_lower:

            return True

    return False


# =========================================================
# MAIN PROGRAM
# =========================================================

def main():

    print("\n" + "=" * 60)
    print("📞 AI-BASED MULTILINGUAL FARMER HELPLINE")
    print("=" * 60)

    print("\n🌾 Call connected!")
    print("🎙️ Speak naturally.")
    print("⚡ The system responds when you stop speaking.")
    print("📞 Say goodbye to end the call.")

    while True:

        # =================================================
        # RECORD FARMER VOICE
        # =================================================

        success = record_voice()

        if not success:

            print("🎙️ Please speak again.")

            continue


        # =================================================
        # SPEECH TO TEXT
        # =================================================

        text, language_code = speech_to_text()


        # =================================================
        # CHECK EMPTY TEXT
        # =================================================

        if text == "":

            print("\n⚠️ I could not understand clearly.")
            print("🎙️ Please speak again.")

            continue


        # =================================================
        # DISPLAY FARMER SPEECH
        # =================================================

        print("\n📝 Farmer said:")
        print(text)

        print("\n🌐 Detected language:")
        print(language_code)


        # =================================================
        # CHECK IF CALL ENDS
        # =================================================

        if should_end_call(text):

            print("\n📞 Call ended.")

            break


        # =================================================
        # GET AI RESPONSE
        # =================================================

        print("\n🤖 AI is thinking...")

        try:

            reply = get_reply(
                text,
                language_code
            )

        except Exception as e:

            print("❌ AI Error:", e)

            reply = (
                "ಕ್ಷಮಿಸಿ ರೈತರೇ. ನಿಮ್ಮ ಪ್ರಶ್ನೆಯನ್ನು ಸರಿಯಾಗಿ "
                "ಅರ್ಥಮಾಡಿಕೊಳ್ಳಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಮತ್ತೆ ಹೇಳಿ."
            )


        # =================================================
        # DISPLAY AI RESPONSE
        # =================================================

        print("\n🤖 AI Reply:")
        print(reply)


        # =================================================
        # SPEAK AI RESPONSE
        # =================================================

        print("\n🔊 Speaking...")

        try:

            result = speak(
                reply,
                language_code
            )

            if asyncio.iscoroutine(result):

                asyncio.run(result)

            print("✅ Response completed.")

        except Exception as e:

            print("❌ Voice Error:", e)


        # =================================================
        # DELETE TEMPORARY AUDIO
        # =================================================

        if os.path.exists(AUDIO_FILE):

            try:

                os.remove(AUDIO_FILE)

            except Exception:

                pass


        print("\n" + "-" * 60)
        print("🎙️ Ready for your next question...")


    # =====================================================
    # CLEANUP
    # =====================================================

    if os.path.exists(AUDIO_FILE):

        try:

            os.remove(AUDIO_FILE)

        except Exception:

            pass


    print("\n🌾 Farmer Helpline disconnected.")
    print("🙏 Thank you.")


# =========================================================
# START PROGRAM
# =========================================================

if __name__ == "__main__":

    main()