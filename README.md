# AI Farmer Helpline

A voice-based AI assistant for farmers in Karnataka and neighbouring states.
Farmers speak in Kannada (or English/Hindi/other regional languages) and receive
spoken answers about weather, crop market prices, and government schemes.

---

## AI Farmer Helpline — Setup and Usage

### Windows CMD Setup

1. **Clone the repo**
   ```cmd
   git clone <repo-url>
   cd Major_Project
   ```

2. **Create virtualenv**
   ```cmd
   python -m venv .venv
   ```

3. **Activate**
   ```cmd
   .venv\Scripts\activate
   ```

4. **Install deps**
   ```cmd
   pip install -r requirements.txt
   ```

5. **Copy .env**
   ```cmd
   copy .env.example .env
   ```

6. **Edit .env** — set `GEMINI_API_KEY` and generate `ADMIN_PASSWORD_HASH`

7. **Generate ADMIN_PASSWORD_HASH**
   ```cmd
   python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your_password'))"
   ```
   Paste the output into `.env` as the value of `ADMIN_PASSWORD_HASH`.

8. **Run app**
   ```cmd
   python app.py
   ```
   Open `http://127.0.0.1:5000` in a browser.

9. **Run tests**
   ```cmd
   python -m pytest tests\ -v
   ```

---

## Feature Status

| Feature | Status | Notes |
|---------|--------|-------|
| Voice pipeline (Whisper + Gemini + TTS) | Working | Whisper medium int8, Edge TTS |
| SQLite persistence | Working | `farmer_helpline.db` |
| Admin dashboard + login | Working | `/admin/login` |
| Rate limiting | Working | Flask-Limiter, configurable via `RATE_LIMIT_PROCESS` |
| Location extraction | Working | Geopy + Nominatim |
| Weather integration | Working | Open-Meteo (no API key required) |
| Market prices | Partial | Sample data only — no live mandi feed |
| Government schemes | Working | Manually curated catalogue |
| Intent classifier | Working | Rule-based only — no ML model |
| Price forecasting | Blocked | Insufficient historical data |
| Telephony (phone calls) | Blocked | Pending Twilio credentials |

---

## Known Limitations

- **Market prices** are sample historical data, not a live feed.
- **Price forecasting** is not implemented — no labeled historical dataset is available.
- **Phone number integration** requires a Twilio account and a verified phone number.
  See `docs/TELEPHONY_SETUP.md` for the setup checklist.
- **Whisper medium on CPU** has ~8–20 s latency per query. A GPU deployment
  (CUDA) reduces this to ~1–3 s.

---

## Architecture

```
app.py                  Flask app, routes, voice pipeline orchestration
backend/database.py     SQLite persistence (parameterised queries only)
services/
  assistant.py          Gemini conversation wrapper
  intent_service.py     Rule-based intent classifier
  location_extractor.py Geopy location extraction
  weather_service.py    Open-Meteo weather fetch
  market_service.py     CSV-backed market price lookup
  scheme_service.py     Government scheme catalogue
  telephony/
    mock_adapter.py     Mock telephony adapter (real Twilio pending)
voice/text_to_speech.py Edge TTS wrapper with gTTS fallback
frontend/
  login.py              AdminUser + verify_admin
  dashboard.py          Dashboard data helpers
templates/              Jinja2 HTML templates
static/                 CSS / JS
tests/                  pytest test suite (76 tests)
docs/                   Audit, reports, telephony setup notes
```

---

## Environment Variables

See `.env.example` for a full annotated list. Required at minimum:

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Google Gemini API key |
| `FLASK_SECRET_KEY` | Flask session signing key |
| `ADMIN_USERNAME` | Admin login username |
| `ADMIN_PASSWORD_HASH` | Werkzeug password hash |

---

## Security Notes

- All SQL queries use `?` parameterised placeholders.
- The `/cleanup_audio` route validates file paths against the audio directory
  to prevent path traversal.
- A startup warning is emitted when `FLASK_SECRET_KEY` is weak or default.
- Session cookies are `HttpOnly` and `SameSite=Lax`.
- Admin routes are protected with `@login_required`.
