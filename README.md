# 🌾 AI Farmer Helpline

An AI-powered multilingual voice helpline for Indian farmers. Farmers speak in their regional language and receive spoken advice on crops, pests, fertilizers, weather, and government schemes — all in the same language.

---

## 🗣️ Supported Languages

| Language | Code | Priority |
|----------|------|----------|
| Kannada | `kn` | Major |
| Hindi | `hi` | Major |
| Malayalam | `ml` | Major |
| English | `en` | Major |
| Tamil | `ta` | Minor |
| Telugu | `te` | Minor |
| Marathi | `mr` | Minor |
| Urdu | `ur` | Minor |

---

## 🏗️ How It Works

```
Farmer speaks (browser mic)
        ↓
Gemini identifies language from audio
        ↓
Whisper transcribes with confirmed language (forced)
        ↓
Gemini generates farming advice in farmer's language
        ↓
Edge TTS speaks the reply back in a natural Indian voice
        ↓
Farmer hears the answer
```

---

## ⚙️ Tech Stack

| Component | Technology |
|-----------|-----------|
| Web server | Flask |
| Speech-to-text | faster-whisper (medium model) |
| Language detection | Google Gemini (audio) |
| AI assistant | Google Gemini |
| Text-to-speech | Edge TTS (Microsoft neural voices) |
| Frontend | HTML + JavaScript (single page) |
| Public tunnel | Cloudflare Tunnel |

---

## 🚀 Setup & Run

### 1. Clone the repository
```bash
git clone https://github.com/nishmasarnoor2005-hue/Farmer-Helpline.git
cd Farmer-Helpline
```

### 2. Create a virtual environment
```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac/Linux
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Add your Gemini API key
Create a `.env` file in the project root:
```
GEMINI_API_KEY=your_api_key_here
```
Get a free API key at [aistudio.google.com](https://aistudio.google.com/apikey)

### 5. Run the server
```bash
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

---

## 📱 Access on Phone (optional)

To access from your phone over the internet, use Cloudflare Tunnel:

```bash
# Download cloudflared and run:
./cloudflared.exe tunnel --url http://localhost:5000
```

Open the generated `https://...trycloudflare.com` URL on your phone.

---

## 📁 Project Structure

```
├── app.py                   # Main Flask server
├── services/
│   ├── assistant.py         # Gemini AI reply logic
│   ├── weather_service.py   # Open-Meteo weather API
│   └── location_extractor.py
├── voice/
│   ├── text_to_speech.py    # Edge TTS neural voices
│   └── speech_to_text.py    # Standalone mic test script
├── templates/
│   └── index.html           # Phone-call style UI
├── backend/
│   └── database.py          # SQLite schema (for future use)
├── requirements.txt
└── .env                     # API keys (not committed)
```

---

## 🔑 Requirements

- Python 3.10+
- Google Gemini API key (free tier works)
- Internet connection (for Gemini + Edge TTS)

---

## 📋 Features

- ✅ Speaks and replies in 8 Indian languages
- ✅ Auto-detects language from voice (no selection needed)
- ✅ Natural neural voices (Microsoft Edge TTS)
- ✅ Auto-listen loop — continuous conversation without button pressing
- ✅ Noise filtering — ignores background noise
- ✅ Hallucination cleaner — fixes garbled transcriptions
- ✅ Conversation memory — AI remembers context within a call
- ✅ Mobile friendly via Cloudflare Tunnel

---

## 📄 License

MIT License — free to use and modify.
