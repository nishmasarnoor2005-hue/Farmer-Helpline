import streamlit as st
import pandas as pd
import os
import sqlite3
from datetime import datetime
import io
import requests
from streamlit_mic_recorder import mic_recorder
import speech_recognition as sr
from deep_translator import GoogleTranslator
from gtts import gTTS


# =====================================
# Page Configuration
# =====================================

st.set_page_config(
    page_title="Intelligent IVR-Based Farmer Helpline",
    page_icon="🌾",
    layout="wide"
)


# =====================================
# Database
# =====================================

conn = sqlite3.connect(
    "farmer_helpline.db",
    check_same_thread=False
)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS farmers(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    mobile TEXT,
    location TEXT,
    language TEXT,
    crop TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS queries(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT,
    response TEXT,
    date_time TEXT
)
""")

conn.commit()


# =====================================
# Title
# =====================================

st.title("🌾 Intelligent IVR-Based Farmer Helpline")

st.write(
    "AI-based multilingual farmer assistance system using Speech Recognition and Generative AI."
)


# =====================================
# Farmer Registration
# =====================================

st.subheader("👨‍🌾 Farmer Registration Module")

with st.form("registration"):

    name = st.text_input("👨‍🌾 Farmer Name")

    mobile = st.text_input("📱 Mobile Number")

    location = st.text_input("📍 Village / Location")

    language = st.selectbox(
        "🗣 Preferred Language",
        [
            "Kannada",
            "Telugu",
            "Tamil",
            "Malayalam",
            "Hindi",
            "English"
        ]
    )

    crop = st.text_input("🌱 Main Crop")

    register = st.form_submit_button("Register Farmer")


if register:

    if name and mobile and location and crop:

        farmer = pd.DataFrame(
            {
                "Name":[name],
                "Mobile":[mobile],
                "Location":[location],
                "Language":[language],
                "Crop":[crop]
            }
        )

        if os.path.exists("farmers.csv"):

            old = pd.read_csv("farmers.csv")

            farmer = pd.concat(
                [old, farmer],
                ignore_index=True
            )

        farmer.to_csv(
            "farmers.csv",
            index=False
        )

        cursor.execute(
            """
            INSERT INTO farmers
            (name,mobile,location,language,crop)

            VALUES (?,?,?,?,?)
            """,
            (
                name,
                mobile,
                location,
                language,
                crop
            )
        )

        conn.commit()

        st.success("✅ Farmer Registered Successfully!")

        st.dataframe(farmer)

    else:

        st.warning("Please fill all details.")


# =====================================
# Voice Module
# =====================================

st.divider()

st.subheader("🎤 Ask Your Farming Question")

st.write("Record your farming problem using voice.")

audio = mic_recorder(
    start_prompt="🎤 Start Recording",
    stop_prompt="⏹ Stop Recording",
    key="voice"
)

if audio:

    st.success("✅ Voice Recorded Successfully!")

    st.audio(
        audio["bytes"],
        format="audio/wav"
    )

    try:

        st.info("Converting voice into text...")
        
        with open("voice.wav", "wb") as f:
            f.write(audio["bytes"])
        
        recognizer = sr.Recognizer()

        with sr.AudioFile("voice.wav") as source:

            voice = recognizer.record(source)

        text = recognizer.recognize_google(
            voice,
            language="en-IN"
        )

        st.success("📝 Your Question")

        st.write(text)

        question = text.lower()
        # =====================================
        # AI Farming Assistant
        # =====================================

        st.divider()

        st.subheader("🤖 AI Farming Assistant")

        if "yellow" in question or "leaf" in question:

            response = """
🌱 Possible reasons:

• Nitrogen deficiency
• Excess water
• Pest or disease attack

✅ Recommended actions:

• Check soil moisture
• Apply balanced fertilizer
• Inspect leaves for pests
"""

        elif "pest" in question or "insect" in question:

            response = """
🐛 Pest Control Advice

• Inspect crops regularly
• Remove infected leaves
• Use suitable organic pesticides
"""

        elif "water" in question or "irrigation" in question:

            response = """
💧 Irrigation Advice

• Avoid overwatering
• Maintain proper soil moisture
• Use drip irrigation
"""

        elif "fertilizer" in question:

            response = """
🌿 Fertilizer Advice

• Perform soil testing
• Use balanced NPK fertilizer
• Avoid excessive chemicals
"""

        else:

            response = """
🌾 General Farming Advice

• Monitor crop health regularly
• Maintain irrigation
• Use quality seeds
"""

        language_code = {
            "Kannada": "kn",
            "Telugu": "te",
            "Tamil": "ta",
            "Malayalam": "ml",
            "Hindi": "hi",
            "English": "en"
        }

        selected_language = language_code[language]

        if selected_language == "en":

            translated_response = response

        else:

            translated_response = GoogleTranslator(
                source="en",
                target=selected_language
            ).translate(response)

        st.success("AI Recommendation")

        st.write(translated_response)

        cursor.execute(
            """
            INSERT INTO queries
            (question,response,date_time)

            VALUES (?,?,?)
            """,
            (
                text,
                translated_response,
                datetime.now().strftime("%d-%m-%Y %H:%M")
            )
        )

        conn.commit()

        # =====================================
        # Text To Speech
        # =====================================

        st.divider()

        st.subheader("🔊 AI Voice Response")

        tts = gTTS(
            text=translated_response,
            lang=selected_language
        )

        tts.save("farmer_response.mp3")

        st.audio("farmer_response.mp3")

    except Exception as e:

        st.error(f"Error: {e}")
# =====================================
# Weather Information Module
# =====================================

st.divider()

st.subheader("🌦 Weather Information")

city = st.text_input(
    "📍 Enter Village / City Name"
)

API_KEY = "b938ffa4fdada0d8a9e6e636c44f8b80"

if st.button("🌦 Get Weather", key="weather_btn"):

    if city:

        url = (
            f"https://api.openweathermap.org/data/2.5/weather?"
            f"q={city}&appid={API_KEY}&units=metric"
        )

        result = requests.get(url)

        data = result.json()

        if data.get("cod") == 200:

            temp = data["main"]["temp"]
            humidity = data["main"]["humidity"]
            condition = data["weather"][0]["description"]

            st.success("✅ Weather Details")

            st.write(f"🌡 Temperature: {temp} °C")
            st.write(f"💧 Humidity: {humidity}%")
            st.write(f"☁ Condition: {condition}")

            st.subheader("🌱 Farming Advice")

            if temp > 35:

                st.info(
                    "🔥 High temperature. Increase irrigation."
                )

            elif "rain" in condition.lower():

                st.info(
                    "🌧 Rain expected. Avoid extra watering."
                )

            else:

                st.info(
                    "🌾 Weather is suitable for farming."
                )

        else:

            st.error("❌ Location not found")

    else:

        st.warning("Please enter a city or village name.")


# =====================================
# Crop Market Price Module
# =====================================

st.divider()

st.subheader("💰 Crop Market Price Information")

crop_prices = {

    "Tomato": {
        "price": 35,
        "market": "Mysore APMC"
    },

    "Potato": {
        "price": 28,
        "market": "Mysore APMC"
    },

    "Rice": {
        "price": 45,
        "market": "Mandya Market"
    },

    "Onion": {
        "price": 32,
        "market": "Mysore APMC"
    },

    "Sugarcane": {
        "price": 380,
        "market": "Hassan Market"
    },

    "Maize": {
        "price": 24,
        "market": "Chikkamagaluru Market"
    }

}

selected_crop = st.selectbox(
    "🌱 Select Crop",
    list(crop_prices.keys())
)

if st.button(
    "💰 Check Market Price",
    key="market_btn"
):

    price_data = crop_prices[selected_crop]

    price = price_data["price"]
    market = price_data["market"]

    st.success("✅ Current Market Information")

    st.write(f"🌱 Crop: {selected_crop}")
    st.write(f"💰 Price: ₹{price}/kg")
    st.write(f"📍 Market: {market}")

    st.subheader("🤖 AI Selling Advice")

    if price >= 35:

        st.info("""
✅ Price is good.

Recommendation:

• Consider selling now.
• Compare nearby markets.
• Avoid unnecessary storage.
""")

    elif price >= 25:

        st.info("""
⚠ Average price.

Recommendation:

• Wait for a few days.
• Sell partially if needed.
• Monitor daily prices.
""")

    else:

        st.info("""
❌ Low market price.

Recommendation:

• Store the crop if possible.
• Wait for a better price.
• Explore alternative markets.
""")


# =====================================
# Farmer Query History
# =====================================

st.divider()

st.subheader("📜 Farmer Query History")

if st.button(
    "View Previous Queries",
    key="history_btn"
):

    history = pd.read_sql_query(
        "SELECT * FROM queries",
        conn
    )

    if len(history) > 0:

        st.dataframe(history)

    else:

        st.info("No previous queries found.")
# =====================================
# Close Database Connection
# =====================================

conn.close()
        