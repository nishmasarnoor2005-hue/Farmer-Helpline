# Telephony Setup Guide

**Current status: BLOCKED — no Twilio credentials configured.**

The telephony layer is implemented with a mock adapter for local testing.
Real phone-call support requires a Twilio account and a purchased number.

---

## Required credentials

Add the following to your `.env` file (never commit real values):

```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
```

---

## Step-by-step Twilio setup

### 1. Create a Twilio account

Sign up at <https://www.twilio.com/try-twilio> (free trial available).

### 2. Buy a phone number

In the Twilio Console go to **Phone Numbers → Manage → Buy a number**.
Choose a number with Voice capability in your target region.

### 3. Install the Twilio Python package

```
pip install twilio
```

Add `twilio` to `requirements.txt`.

### 4. Set the inbound webhook

In the Twilio Console, open your phone number's configuration page.
Under **Voice & Fax → A call comes in**, set:

- Webhook: `https://<your-domain>/telephony/incoming`
- HTTP method: `POST`

### 5. Expose your local server for testing

`cloudflared.exe` is already present in the workspace root.

**Start a tunnel:**

```cmd
cloudflared.exe tunnel --url http://localhost:5000
```

Cloudflared will print a public `https://*.trycloudflare.com` URL.
Use that URL as the webhook in the Twilio Console instead of `<your-domain>`.

**Alternative — ngrok:**

```cmd
ngrok http 5000
```

### 6. Add credentials to `.env`

```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
```

Restart the Flask server after editing `.env`.

### 7. Switch to TwilioAdapter in app.py

Once credentials are confirmed, open `app.py` and replace the
`MockAdapter` references with `TwilioAdapter`:

```python
from services.telephony.twilio_adapter import TwilioAdapter
telephony_adapter = TwilioAdapter()
```

### 8. Verify a real call

1. Start the server: `python app.py`
2. Start the cloudflared tunnel.
3. Call your Twilio number from a mobile phone.
4. Check the server logs for `handle_incoming_call` output.
5. Confirm the caller hears the greeting and recording prompt.

---

## Environment variables summary

| Variable | Required | Description |
|---|---|---|
| `TWILIO_ACCOUNT_SID` | Yes | Found in Twilio Console dashboard |
| `TWILIO_AUTH_TOKEN` | Yes | Found in Twilio Console dashboard |
| `TWILIO_PHONE_NUMBER` | Yes | E.164 format, e.g. `+14155551234` |

---

## Current mock endpoints

These work right now without any credentials:

| Method | Path | Description |
|---|---|---|
| `GET` | `/telephony/status` | Reports provider and status |
| `POST` | `/telephony/incoming` | Starts a mock call session |
| `POST` | `/telephony/respond` | Sends a text message, gets echo response |

Test with curl (Windows CMD):

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

- [ ] Twilio account created
- [ ] Phone number purchased
- [ ] `TWILIO_ACCOUNT_SID` set in `.env`
- [ ] `TWILIO_AUTH_TOKEN` set in `.env`
- [ ] `TWILIO_PHONE_NUMBER` set in `.env`
- [ ] `twilio` package installed (`pip install twilio`)
- [ ] Webhook URL configured in Twilio Console
- [ ] Live call tested end-to-end
