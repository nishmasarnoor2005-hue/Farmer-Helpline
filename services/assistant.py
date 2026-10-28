import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

# =========================================================
# LOAD API KEY
# =========================================================

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# =========================================================
# MODEL
# =========================================================

MODEL = "gemini-3.5-flash"

# =========================================================
# LANGUAGE NAMES
# =========================================================

LANGUAGE_NAMES = {
    "kn": "Kannada",
    "en": "English",
    "hi": "Hindi",
    "ml": "Malayalam",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "ur": "Urdu",
}

# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """You are an AI agricultural helpline assistant for Indian farmers.
Your role is to help farmers with:
- Crop diseases, pests, and treatments
- Fertilizer and pesticide recommendations
- Irrigation and water management
- Soil health and preparation
- Weather-based farming advice
- Crop selection for their region and season
- Market prices and selling advice
- Government schemes and subsidies for farmers

Rules you must follow:
1. Always reply in the SAME language the farmer used. If they spoke in Kannada, reply in Kannada. If Hindi, reply in Hindi. Never switch languages.
2. Keep replies short, clear, and practical — 2 to 4 sentences maximum. Farmers need actionable advice, not long essays.
3. Use simple, everyday language. Avoid technical jargon unless you explain it immediately.
4. Be warm and respectful. Address the farmer appropriately for their language.
5. If the farmer's question is unclear, ask one simple clarifying question.
6. Never respond in English if the farmer spoke in another language.
7. Do not add greetings or sign-offs. Just answer the question directly."""

# =========================================================
# ROLLING CONVERSATION HISTORY
# =========================================================

_history = []
MAX_HISTORY = 6  # Keep last 6 turns (3 farmer + 3 AI)


def _build_prompt(farmer_text: str, language_code: str, context_data: dict | None = None) -> str:
    """Build the full prompt with conversation history and optional context data."""

    language_name = LANGUAGE_NAMES.get(language_code, "English")

    history_text = ""
    if _history:
        history_text = "\n\nPrevious conversation:\n"
        for turn in _history[-MAX_HISTORY:]:
            history_text += f"Farmer: {turn['farmer']}\nAssistant: {turn['reply']}\n"

    # Inject verified weather context so Gemini never invents values
    weather_block = ""
    if context_data and context_data.get("weather"):
        w = context_data["weather"]
        weather_block = (
            "\n\n[WEATHER CONTEXT — use ONLY this data, do NOT invent or estimate values]\n"
            f"Location: {w.get('location')}\n"
            f"Temp: {w.get('temperature')}°C\n"
            f"Condition: {w.get('description')}\n"
            f"Humidity: {w.get('humidity')}%"
        )

    prompt = (
        f"{SYSTEM_PROMPT}"
        f"{weather_block}"
        f"{history_text}"
        f"\nFarmer's language: {language_name} (code: {language_code})"
        f"\nFarmer says: {farmer_text}"
        f"\nAssistant ({language_name}):"
    )

    return prompt


# =========================================================
# MAIN REPLY FUNCTION
# =========================================================

def get_reply(text: str, language: str, context_data: dict | None = None) -> str:
    """
    Get an AI-generated reply from Gemini for the farmer's query.

    Args:
        text: Transcribed text of what the farmer said.
        language: ISO language code detected by Whisper (e.g. 'kn', 'hi').
        context_data: Optional dict with extra context (e.g. {'weather': {...}}).
                      When provided, the data is injected into the prompt so
                      Gemini uses real values rather than inventing them.

    Returns:
        A reply string in the farmer's language.
    """

    global _history

    try:
        prompt = _build_prompt(text, language, context_data)

        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.4,        # Factual but slightly natural
                max_output_tokens=300,  # Keep replies concise
                top_p=0.9,
            ),
        )

        reply = response.text.strip()

        # Save to rolling history
        _history.append({"farmer": text, "reply": reply})
        if len(_history) > MAX_HISTORY:
            _history = _history[-MAX_HISTORY:]

        return reply

    except Exception as e:
        print(f"Gemini API error: {e}")

        # Graceful fallback in the farmer's language
        fallbacks = {
            "kn": "ಕ್ಷಮಿಸಿ, ತಾಂತ್ರಿಕ ತೊಂದರೆಯಾಗಿದೆ. ದಯವಿಟ್ಟು ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
            "hi": "माफ करें, तकनीकी समस्या आई है। कृपया फिर से प्रयास करें।",
            "ml": "ക്ഷമിക്കണം, സാങ്കേതിക പ്രശ്നമുണ്ട്. ദയവായി വീണ്ടും ശ്രമിക്കൂ.",
            "ta": "மன்னிக்கவும், தொழில்நுட்ப சிக்கல் உள்ளது. மீண்டும் முயற்சிக்கவும்.",
            "te": "క్షమించండి, సాంకేతిక సమస్య వచ్చింది. దయచేసి మళ్ళీ ప్రయత్నించండి.",
            "mr": "माफ करा, तांत्रिक समस्या आली आहे. कृपया पुन्हा प्रयत्न करा.",
            "ur": "معاف کریں، ایک تکنیکی مسئلہ پیش آیا۔ براہ کرم دوبارہ کوشش کریں۔",
            "en": "Sorry, a technical issue occurred. Please try again.",
        }
        return fallbacks.get(language, fallbacks["en"])


# =========================================================
# RESET CONVERSATION HISTORY
# =========================================================

def reset_history():
    """Clear conversation history. Call this when a new call session starts."""
    global _history
    _history = []
