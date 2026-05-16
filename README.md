# Bright Smiles Dental — Voice Agent (Mia)

Production-ready Pipecat voice agent that handles dental appointment booking,
cancellation, and rescheduling via phone (Twilio) or browser (WebRTC).

## Stack

| Layer     | Technology                     |
|-----------|--------------------------------|
| Framework | Pipecat (pipeline + transports)|
| STT       | Deepgram Nova-3               |
| LLM       | OpenAI GPT-4o                 |
| TTS       | ElevenLabs Turbo v2.5         |
| VAD       | Silero                        |
| Phone     | Twilio WebSocket media streams|
| Browser   | SmallWebRTC                   |
| Web       | FastAPI + Uvicorn             |
| Booking   | Cal.com API v2                |

## Quick Start

### 1. Install dependencies

```bash
# Requires Python 3.12+ and uv
uv sync
```

### 2. Configure credentials

```bash
cp .env.example .env
# Edit .env and fill in all API keys
```

**ElevenLabs voice**: Pick a warm, calm Australian female voice from the
[ElevenLabs Voice Library](https://elevenlabs.io/voice-library) and paste
the voice ID into `ELEVENLABS_VOICE_ID`. Recommended: search for
"Australian" → "Female" → select a natural, warm voice.

**Cal.com**: Create an event type in Cal.com for dental appointments and
set `CALCOM_EVENT_TYPE_ID` to its numeric ID.

### 3. Run locally (browser test)

```bash
uv run python -m server.server
```

Open **http://localhost:7860/** → click **Connect** → speak.

### 4. Run with Twilio (phone)

1. Expose your server with ngrok: `ngrok http 7860`
2. Set `PUBLIC_BASE_URL` in `.env` to the ngrok URL
3. In your Twilio console, set the incoming call webhook for your
   phone number to `https://<ngrok-url>/twilio/voice`
4. Restart the server and call your Twilio number

## Project Structure

```
server/
├── bot.py                  # Pipeline: VAD → STT → LLM(tools) → TTS
├── server.py               # FastAPI: /twilio/voice, /twilio/ws, /api/offer, /
├── tools/
│   └── __init__.py         # 7 function-calling tools
├── integrations/
│   ├── calcom_client.py    # Async httpx Cal.com v2 client
│   └── twilio_client.py    # Twilio REST wrapper for call transfer
├── prompts/
│   └── system_prompt.md    # Mia's persona + rules
├── __init__.py
```

## Tools

| Tool                    | Description                              |
|-------------------------|------------------------------------------|
| `check_availability`    | GET /v2/slots — returns up to 5 slots    |
| `book_appointment`      | POST /v2/bookings                        |
| `lookup_booking`        | GET /v2/bookings filtered by attendee    |
| `cancel_appointment`    | POST /v2/bookings/{uid}/cancel           |
| `reschedule_appointment`| POST /v2/bookings/{uid}/reschedule       |
| `transfer_to_human`     | Twilio REST: update call with Dial TwiML |
| `end_call`              | Push EndFrame to close the pipeline      |

## Smoke Test

```bash
uv run python -m server.server
# Open http://localhost:7860/
# Click Connect
# Say: "I'd like to book an appointment for Thursday at 2pm"
# Agent should ask for name → phone → email → reason → confirm → book
```

## DigitalOcean Deployment

See `deploy/` directory (to be added) or deploy manually:

```bash
# On your DO droplet:
git clone <repo> && cd bright-smiles-dental
cp .env.example .env  # fill in credentials
uv sync
uv run python -m server.server --host 0.0.0.0 --port 7860
```

Use a reverse proxy (Caddy/nginx) for HTTPS in production.
