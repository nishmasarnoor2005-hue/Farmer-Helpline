# Telephony Setup Guide

## Current Status

- ✅ TWILIO_ACCOUNT_SID configured
- ✅ TWILIO_AUTH_TOKEN configured
- ⏳ TWILIO_PHONE_NUMBER: NOT YET PURCHASED

The server starts and the `/telephony/*` routes are active.  
Real inbound calls require purchasing a phone number (step 1 below).

---

## Next Steps to Enable Live Calls

### 1. Purchase an Indian phone number

Go to: <https://console.twilio.com/us1/develop/phone-numbers/search>  
Search for India (+91). Purchase a number that supports Voice.  
Copy the number in E.164 format (e.g. `+918XXXXXXXXX`).

### 2. Set the phone number in `.env`

```
TWILIO_PHONE_NUMBER=+918XXXXXXXXX
TELEPHONY_PROVIDER=twilio
```

Restart the Flask server after editing `.env`.

### 3. Set the webhook URL

In Twilio Console → Phone Numbers → Your Number → Configure:

- **Voice webhook**: `https://{your-cloudflare-url}/telephony/incoming`
- **Method**: POST
- **Recording status callback**: `https://{your-cloudflare-url}/telephony/respond`

### 4. Start the Cloudflare tunnel

```cmd
cloudflared.exe tunnel --url http://localhost:5000
```

Cloudflared will print a public `https://*.trycloudflare.com` URL.  
Use that URL as the webhook in the Twilio Console.

### 5. Test

Call your purchased number. You should hear the Kannada greeting:  
*"ನಮಸ್ಕಾರ, ನೀವು AI ಕೃಷಿ ಸಹಾಯವಾಣಿಗೆ ಕರೆ ಮಾಡಿದ್ದೀರಿ. ದಯವಿಟ್ಟು ನಿಮ್ಮ ಸಮಸ್ಯೆಯನ್ನು ಹೇಳಿ."*

---

## Environment variables

| Variable              | Required | Description                                       |
|-----------------------|----------|---------------------------------------------------|
| `TWILIO_ACCOUNT_SID`  | Yes      | Found in Twilio Console dashboard                 |
| `TWILIO_AUTH_TOKEN`   | Yes      | Found in Twilio Console dashboard                 |
| `TWILIO_PHONE_NUMBER` | Yes*     | E.164 format, e.g. `+918XXXXXXXXX`. *Required for inbound calls |
| `TELEPHONY_PROVIDER`  | No       | Set to `twilio` to activate TwilioAdapter (default: `mock`) |

---

## How the adapter works

```
Caller dials number
    │
    ▼
Twilio → POST /telephony/incoming
    │  (X-Twilio-Signature verified)
    ▼
TwilioAdapter.handle_incoming_call()
    │  Returns TwiML: <Say> greeting + <Record>
    ▼
Caller speaks their question
    │
    ▼
Twilio → POST /telephony/respond  (with RecordingUrl)
    │  (X-Twilio-Signature verified)
    ▼
TwilioAdapter.process_recording()
    ├─ Download WAV from Twilio
    ├─ Transcribe with faster-whisper
    ├─ Get AI reply via services.assistant.get_reply()
    ├─ Generate TTS via voice.text_to_speech.speak()
    └─ Return TwiML: <Say> reply + <Record> (loop)
```

**Note on audio playback**: TTS audio is saved locally but cannot be served
directly to Twilio without a public URL. Until a public static file server is
configured, the AI reply is delivered via Twilio's `<Say>` verb instead of
`<Play>`. This works fully but uses Twilio's built-in TTS voice rather than
the Edge TTS voice.

---

## Local / mock mode

Without `TELEPHONY_PROVIDER=twilio` the server uses MockAdapter, which works
entirely without Twilio credentials.

```cmd
curl http://localhost:5000/telephony/status

curl -X POST http://localhost:5000/telephony/incoming ^
     -H "Content-Type: application/json" ^
     -d "{\"caller\": \"+919876543210\"}"

curl -X POST http://localhost:5000/telephony/respond ^
     -H "Content-Type: application/json" ^
     -d "{\"session_id\": \"<id-from-above>\", \"message\": \"wheat price today\"}"
```

---

## Blocking items

- [x] Twilio account SID configured
- [x] Twilio auth token configured
- [x] `twilio` Python package installed (v9.12.0)
- [x] TwilioAdapter implemented with webhook verification
- [x] `/telephony/incoming` and `/telephony/respond` routes updated
- [ ] **TWILIO_PHONE_NUMBER purchased** ← next action
- [ ] `TELEPHONY_PROVIDER=twilio` set in `.env`
- [ ] Webhook URL configured in Twilio Console
- [ ] Live call tested end-to-end
