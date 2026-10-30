# VoiceLink India WebSocket Bot Setup Guide

This document explains how to connect the AI Farmer Helpline to VoiceLink India
using the WebSocket Bots feature.

## Prerequisites

1. **VoiceLink India account** with a purchased DID (phone number)
2. **Cloudflared** or **ngrok** installed to expose your local server
3. Python virtual environment set up (`d:\Major_Project\.venv`)
4. All environment variables configured (see section below)

## Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```env
VOICELINK_ENABLED=true
VOICELINK_USERNAME=your_voicelink_username
VOICELINK_PASSWORD=your_voicelink_password
VOICELINK_WEBHOOK_SECRET=your_webhook_signature_secret
VOICELINK_PHONE_NUMBER=your_did_id_number
VOICELINK_BOT_WEBSOCKET_URL=wss://your-tunnel-url/integrations/voicelink/ws
VOICELINK_BOT_WEBHOOK_URL=https://your-tunnel-url/integrations/voicelink/webhook
VOICELINK_VAD_SILENCE_CHUNKS=20
VOICELINK_VAD_ENERGY_THRESHOLD=200
VOICELINK_MAX_BUFFER_CHUNKS=200
```

## Step 1 — Start the Local Server

Open a Command Prompt (CMD) in `d:\Major_Project`:

```cmd
.venv\Scripts\python.exe app.py
```

The server starts on `http://localhost:5000`.

## Step 2 — Expose with Cloudflared (Recommended)

In a second CMD window:

```cmd
.\cloudflared.exe tunnel --url http://localhost:5000
```

Copy the generated `https://xxxx.trycloudflare.com` URL.

**Or with ngrok:**

```cmd
ngrok http 5000
```

Copy the `https://xxxx.ngrok-free.app` URL.

## Step 3 — Configure Environment Variables

Edit `.env`:

```env
VOICELINK_BOT_WEBSOCKET_URL=wss://xxxx.trycloudflare.com/integrations/voicelink/ws
VOICELINK_BOT_WEBHOOK_URL=https://xxxx.trycloudflare.com/integrations/voicelink/webhook
```

Note: Change `https://` to `wss://` for the WebSocket URL.

## Step 4 — Provision the VoiceLink Bot

Run the provisioning script once:

```cmd
.venv\Scripts\python.exe -c "
from services.voicelink_api import setup_voicelink_bot
result = setup_voicelink_bot()
print('Bot ID:', result['bot_id'])
print('Routing ID:', result['routing_id'])
"
```

This will:
1. Log into VoiceLink with your credentials
2. Create a WebSocket bot pointing at your tunnel URL
3. Configure call routing for your DID to use the bot

## Step 5 — Test Sequence

### Local Mock Test

```cmd
.venv\Scripts\python.exe -m pytest tests\test_voicelink_adapter.py tests\test_voicelink_api.py tests\test_pcma_utils.py -v
```

### Tunnel Test (WebSocket connectivity)

With the server running and tunnel active:

```cmd
.venv\Scripts\python.exe -c "
import websocket
ws = websocket.create_connection('wss://your-tunnel/integrations/voicelink/ws')
print('Connected:', ws)
ws.close()
"
```

### Real Call Test

1. Ensure `VOICELINK_ENABLED=true` in `.env`
2. Restart the server
3. Call your VoiceLink DID phone number
4. Watch the server console for WebSocket events

## WebSocket Event Flow

```
VoiceLink → Our Server                Our Server → VoiceLink
─────────────────────────────────────────────────────────────
connected ─────────────────────────►
start ──────────────────────────────►  (create DB session)
media (PCMA chunk 1) ───────────────►
media (PCMA chunk 2) ───────────────►
...                                     ◄─── media (wait audio PCMA)
media (PCMA chunk N) ───────────────►
[silence detected / buffer full]        ◄─── clear
                                        ◄─── media (reply PCMA)
                                        ◄─── mark (reply_end)
stop ───────────────────────────────►  (end DB session)
```

## Audio Format

| Parameter   | Value          |
|-------------|----------------|
| Codec       | G.711 A-law    |
| Sample rate | 8,000 Hz       |
| Bit depth   | 8-bit          |
| Channels    | Mono (1)       |
| Transport   | Base64 encoded |

## Limitations

- **Whisper CPU latency**: ~6–10 seconds per turn on CPU. The wait audio
  ("One moment, let me check") is played immediately so the caller hears
  a response while Whisper processes the audio.
- **No true real-time streaming**: The pipeline processes complete utterances,
  not streaming audio frames.
- **Language detection**: Defaults to English on the VoiceLink channel.
  Language auto-detection (Gemini-based) can be added as an enhancement.

## Rollback

To disable VoiceLink integration without code changes:

```env
VOICELINK_ENABLED=false
```

Restart the server. VoiceLink WebSocket connections will be closed immediately.
All other routes and the browser voice mode continue to function normally.
