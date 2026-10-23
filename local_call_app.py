import streamlit as st
import asyncio

from voice.speech_to_text import speech_to_text
from services.location_extractor import extract_location
from services.weather_service import get_weather
from voice.text_to_speech import speak

# ---------------------------------------------------
# Page settings
# ---------------------------------------------------
st.set_page_config(
    page_title="AI Farmer Helpline",
    page_icon="🌾",
    layout="centered"
)

# ---------------------------------------------------
# Header
# ---------------------------------------------------
st.markdown(
    """
    # 🌾 AI-Based Multilingual Farmer Helpline

    📞 **Local Call Demo**

    Speak in **Kannada, Hindi, Tamil, Telugu, Malayalam, Marathi, Konkani, or Tulu**.
    """
)

st.info("🙏 Namaskara | Namaste | Vanakkam | Namaskaram | Dev Borem Korum")

st.markdown("---")

# ---------------------------------------------------
# Call button
# ---------------------------------------------------
if st.button("📞 Start Call"):

    st.warning("🎙️ Listening... Please speak now.")

    # Speech to text
    text, lang = speech_to_text()

    st.success(f"📝 You said: {text}")
    st.write(f"🌐 Language: {lang}")

    # Location detection
    location = extract_location(text)

    if location:

        place = location["query"]

        st.write(f"📍 Place: {place}")
        st.write(f"📌 Address: {location['address']}")

        # Real-time weather
        weather = get_weather(
            location["latitude"],
            location["longitude"]
        )

        temp = weather["temperature"]
        wind = weather["wind"]

        st.success(f"🌤️ Current temperature: {temp}°C")
        st.success(f"💨 Wind speed: {wind} km/h")

        # ---------------------------------------------------
        # Reply in same language
        # ---------------------------------------------------
        if lang == "kn":
            reply = (
                f"ನೀವು {place} ನಿಂದ ಮಾತನಾಡುತ್ತಿದ್ದೀರಿ. "
                f"ಪ್ರಸ್ತುತ ತಾಪಮಾನ {temp} ಡಿಗ್ರಿ ಸೆಲ್ಸಿಯಸ್ ಮತ್ತು ಗಾಳಿಯ ವೇಗ {wind} ಕಿಲೋಮೀಟರ್ ಪ್ರತಿ ಗಂಟೆ ಇದೆ. "
                "ದಯವಿಟ್ಟು ನಿಮ್ಮ ಬೆಳೆ ಹೆಸರನ್ನು ಹೇಳಿ, ಉದಾಹರಣೆಗೆ ಅಕ್ಕಿ, ರಾಗಿ, ಮೆಕ್ಕೆಜೋಳ, ತೆಂಗು, ಅಡಿಕೆ, ಕಾಫಿ ಅಥವಾ ತರಕಾರಿ."
            )

        elif lang == "hi":
            reply = (
                f"आप {place} से बात कर रहे हैं। "
                f"वर्तमान तापमान {temp} डिग्री सेल्सियस और हवा की गति {wind} किलोमीटर प्रति घंटा है। "
                "कृपया अपनी फसल का नाम बताइए, जैसे धान, रागी, मक्का, नारियल, सुपारी, कॉफी या सब्जियाँ।"
            )

        elif lang == "ta":
            reply = (
                f"நீங்கள் {place} இலிருந்து பேசுகிறீர்கள். "
                f"தற்போதைய வெப்பநிலை {temp} டிகிரி செல்சியஸ் மற்றும் காற்றின் வேகம் {wind} கிலோமீட்டர் ஒரு மணி நேரம். "
                "தயவுசெய்து உங்கள் பயிரின் பெயரை சொல்லுங்கள், உதாரணமாக நெல், ராகி, மக்காச்சோளம், தேங்காய், பாக்கு, காப்பி அல்லது காய்கறிகள்."
            )

        elif lang == "te":
            reply = (
                f"మీరు {place} నుండి మాట్లాడుతున్నారు. "
                f"ప్రస్తుతం ఉష్ణోగ్రత {temp} డిగ్రీ సెల్సియస్ మరియు గాలి వేగం {wind} కిలోమీటర్లు గంటకు ఉంది. "
                "దయచేసి మీ పంట పేరు చెప్పండి, ఉదాహరణకు వరి, రాగి, మొక్కజొన్న, కొబ్బరి, పొగాకు, కాఫీ లేదా కూరగాయలు."
            )

        elif lang == "ml":
            reply = (
                f"നിങ്ങൾ {place}യിൽ നിന്ന് സംസാരിക്കുന്നു. "
                f"നിലവിലെ താപനില {temp} ഡിഗ്രി സെൽഷ്യസും കാറ്റിന്റെ വേഗം {wind} കിലോമീറ്റർ മണിക്കൂറിലും ആണ്. "
                "ദയവായി നിങ്ങളുടെ വിളയുടെ പേര് പറയൂ, ഉദാഹരണത്തിന് നെല്ല്, റാഗി, മക്കച്ചോലം, തെങ്ങ്, അടയ്ക്ക, കാപ്പി അല്ലെങ്കിൽ പച്ചക്കറികൾ."
            )

        elif lang == "mr":
            reply = (
                f"तुम्ही {place} येथून बोलत आहात. "
                f"सध्याचे तापमान {temp} डिग्री सेल्सियस आणि वाऱ्याचा वेग {wind} किलोमीटर प्रति तास आहे. "
                "कृपया तुमच्या पिकाचे नाव सांगा, जसे भात, रागी, मका, नारळ, सुपारी, कॉफी किंवा भाजीपाला."
            )

        else:
            reply = (
                f"You are speaking from {place}. "
                f"The current temperature is {temp} degree Celsius and wind speed is {wind} kilometer per hour. "
                "Please tell me your crop name such as paddy, ragi, maize, coconut, arecanut, coffee, or vegetables so I can provide suitable advice."
            )

    else:
        reply = (
            "I could not identify your location. Please tell your village or district clearly."
        )

    # ---------------------------------------------------
    # Show AI reply
    # ---------------------------------------------------
    st.markdown("### 🤖 AI Reply")
    st.write(reply)

    # ---------------------------------------------------
    # Voice reply
    # ---------------------------------------------------
    try:
        asyncio.run(speak(reply, "English"))
        st.audio("farmer_reply.mp3")
    except Exception as e:
        st.error(f"Voice generation failed: {e}")

# ---------------------------------------------------
# Footer
# ---------------------------------------------------
st.markdown("---")
st.caption(
    "🎓 Final Year Project | Department of Computer Science & Engineering | AI Voice Farmer Helpline System"
)