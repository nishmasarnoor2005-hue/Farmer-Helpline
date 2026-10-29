import asyncio

from voice.speech_to_text import speech_to_text
from voice.language_detect import detect_language
from services.assistant import get_reply
from services.location_extractor import extract_location
from voice.text_to_speech import speak


def main():

    print("\n📞 AI Farmer Helpline Started")
    print("🙏 Namaskara / Vanakkam / Namaskaram / Namaste / Dev Borem Korum")
    print("🎙️ Please speak in your language...\n")

    # Step 1: Speech to text
    text, whisper_lang = speech_to_text()

    if not text:
        print("❌ No speech detected")
        return

    # Step 2: Language detection
    lang_map = {
        "kn": "Kannada",
        "hi": "Hindi",
        "ta": "Tamil",
        "te": "Telugu",
        "ml": "Malayalam",
        "mr": "Marathi",
        "en": "English"
    }

    # Extra script-based correction
    kannada_chars = [ch for ch in text if '\u0C80' <= ch <= '\u0CFF']
    telugu_chars = [ch for ch in text if '\u0C00' <= ch <= '\u0C7F']

    if len(kannada_chars) > len(telugu_chars):
        language = "Kannada"

    elif len(telugu_chars) > len(kannada_chars):
        language = "Telugu"

    else:
        language = lang_map.get(whisper_lang, detect_language(text))

    print(f"\n🌐 Detected Language: {language}")

    # Step 3: Location detection
    location_info = extract_location(text)

    if location_info:

        place = location_info["query"]
        address = location_info["address"]

        print(f"\n📍 Detected Place: {place}")
        print(f"📌 Address: {address}")

        # Reply in the same language spoken by the farmer

        if language == "Kannada":

            reply = (
                f"ನೀವು {place} ಜಿಲ್ಲೆಯಿಂದ ಮಾತನಾಡುತ್ತಿದ್ದೀರಿ ಎಂದು ನಾನು ಗುರುತಿಸಿದ್ದೇನೆ. "
                "ದಯವಿಟ್ಟು ನಿಮ್ಮ ಬೆಳೆ, ಹವಾಮಾನ ಅಥವಾ ಮಾರುಕಟ್ಟೆ ಬೆಲೆ ಕುರಿತು ಪ್ರಶ್ನೆಯನ್ನು ಕೇಳಿ."
            )

        elif language == "Hindi":

            reply = (
                f"मैंने पहचाना कि आप {place} से बात कर रहे हैं। "
                "कृपया अपनी फसल, मौसम या बाजार मूल्य के बारे में पूछिए।"
            )

        elif language == "Tamil":

            reply = (
                f"நீங்கள் {place} மாவட்டத்திலிருந்து பேசுகிறீர்கள் என்பதை நான் கண்டறிந்தேன். "
                "உங்கள் பயிர், வானிலை அல்லது சந்தை விலை பற்றி கேளுங்கள்."
            )

        elif language == "Telugu":

            reply = (
                f"మీరు {place} జిల్లా నుండి మాట్లాడుతున్నారని నేను గుర్తించాను. "
                "మీ పంట, వాతావరణం లేదా మార్కెట్ ధర గురించి అడగండి."
            )

        elif language == "Malayalam":

            reply = (
                f"നിങ്ങൾ {place} ജില്ലയിൽ നിന്ന് സംസാരിക്കുകയാണെന്ന് ഞാൻ തിരിച്ചറിഞ്ഞു. "
                "നിങ്ങളുടെ വിള, കാലാവസ്ഥ അല്ലെങ്കിൽ വിപണി വിലയെക്കുറിച്ച് ചോദിക്കൂ."
            )

        elif language == "Marathi":

            reply = (
                f"मी ओळखले की तुम्ही {place} जिल्ह्यातून बोलत आहात. "
                "कृपया तुमच्या पिकाबद्दल, हवामानाबद्दल किंवा बाजारभावाबद्दल विचारा."
            )

        elif language == "English":

            reply = (
                f"I identified that you are speaking from {place}. "
                "Please tell me your crop, weather, or market-price question."
            )

        elif language == "Konkani":

            reply = (
                f"हांव ओळखलं की तुमी {place} थांवून उलयता. "
                "तुमच्या पिक, हवामान वा बाजारभावा विशयी विचारा."
            )

        elif language == "Tulu":

            reply = (
                f"ಯಾನ್ ಗುರುತಿನಿ ನೀನು {place} ಜಿಲ್ಲೆದಿಂಡ ಪಾತೆರಂಡುಂಡು. "
                "ನಿನ್ನ ಬೆಳೆ, ಮಳೆ ಅಥವಾ ಮಾರುಕಟ್ಟೆ ಬೆಲೆ ಬಗ್ಗೆ ಕೇಳೆ."
            )

        else:

            reply = get_reply(text, language)

    else:

        reply = get_reply(text, language)

    print(f"\n🤖 AI Reply:\n{reply}")

    # Step 4: Voice reply
    asyncio.run(speak(reply, language))

    print("\n🔊 Reply audio generated successfully!")
    print("📁 Check farmer_reply.mp3 in D:\\Major_Project")


if __name__ == "__main__":
    main()