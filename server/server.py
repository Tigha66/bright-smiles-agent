"""FastAPI server for Bright Smiles Dental voice agent.

Endpoints:
  GET  /              → Redirect to WebRTC test UI
  POST /api/offer     → SmallWebRTC SDP offer (browser test)
  POST /twilio/voice  → TwiML webhook for incoming Twilio calls
  GET  /twilio/ws     → WebSocket endpoint for Twilio media streams
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from loguru import logger

# Load .env BEFORE any pipecat / service imports so keys are available
load_dotenv(override=True)

from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import IceServer, SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from server.bot import run_bot

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

pcs_map: dict[str, SmallWebRTCConnection] = {}
ice_servers = [IceServer(urls="stun:stun.l.google.com:19302")]


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    coros = [pc.disconnect() for pc in pcs_map.values()]
    await asyncio.gather(*coros)
    pcs_map.clear()


app = FastAPI(title="Bright Smiles Dental Agent", lifespan=lifespan)

# Mount the SmallWebRTC prebuilt frontend
try:
    from pipecat_ai_small_webrtc_prebuilt.frontend import SmallWebRTCPrebuiltUI
    app.mount("/client", SmallWebRTCPrebuiltUI)
except ImportError:
    logger.warning(
        "pipecat-ai-small-webrtc-prebuilt not installed — "
        "browser test UI will not be available"
    )


# ---------------------------------------------------------------------------
# Routes: Home
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/client/")


# ---------------------------------------------------------------------------
# Routes: SmallWebRTC (browser test)
# ---------------------------------------------------------------------------

async def _run_webrtc_bot(connection: SmallWebRTCConnection):
    """Launch the pipeline with a SmallWebRTC transport."""
    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    )
    await run_bot(transport, handle_sigint=False, call_sid=None)


@app.post("/api/offer")
async def webrtc_offer(request: dict, background_tasks: BackgroundTasks):
    pc_id = request.get("pc_id")

    if pc_id and pc_id in pcs_map:
        connection = pcs_map[pc_id]
        logger.info(f"Reusing WebRTC connection: {pc_id}")
        await connection.renegotiate(
            sdp=request["sdp"],
            type=request["type"],
            restart_pc=request.get("restart_pc", False),
        )
    else:
        connection = SmallWebRTCConnection(ice_servers)
        await connection.initialize(sdp=request["sdp"], type=request["type"])

        @connection.event_handler("closed")
        async def handle_closed(conn: SmallWebRTCConnection):
            logger.info(f"WebRTC connection closed: {conn.pc_id}")
            pcs_map.pop(conn.pc_id, None)

        background_tasks.add_task(_run_webrtc_bot, connection)

    answer = connection.get_answer()
    pcs_map[answer["pc_id"]] = connection
    return answer


# ---------------------------------------------------------------------------
# Routes: Twilio
# ---------------------------------------------------------------------------

@app.api_route("/twilio/voice", methods=["GET", "POST"])
async def twilio_voice(request: Request):
    """Return TwiML that opens a WebSocket media stream to /twilio/ws."""
    host = request.headers.get("host", "localhost")
    # Prefer PUBLIC_BASE_URL if set, otherwise construct from host
    public_base = os.getenv("PUBLIC_BASE_URL", "")
    if public_base:
        # Strip trailing slash, convert http(s) to ws(s)
        ws_base = public_base.rstrip("/").replace("https://", "wss://").replace("http://", "ws://")
    else:
        scheme = "wss" if request.url.scheme == "https" else "ws"
        ws_base = f"{scheme}://{host}"

    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Connect><Stream url="{ws_base}/twilio/ws" /></Connect>'
        "</Response>"
    )
    return Response(content=twiml, media_type="application/xml")


@app.websocket("/twilio/ws")
async def twilio_websocket(websocket: WebSocket):
    """Handle Twilio media stream WebSocket connection."""
    await websocket.accept()
    logger.info("Twilio WebSocket connected")

    # Read the first two Twilio messages to get stream/call SIDs
    stream_sid: str | None = None
    call_sid: str | None = None

    start_data = {}
    try:
        async for raw in websocket.iter_text():
            msg = json.loads(raw)
            if msg.get("event") == "connected":
                logger.debug("Twilio: connected event")
                continue
            if msg.get("event") == "start":
                start_data = msg.get("start", {})
                stream_sid = start_data.get("streamSid")
                call_sid = start_data.get("callSid")
                logger.info(f"Twilio stream started: stream={stream_sid}, call={call_sid}")
                break
    except Exception as exc:
        logger.error(f"Error reading Twilio start messages: {exc}")
        return

    if not stream_sid:
        logger.error("No streamSid received from Twilio")
        return

    # Build the Twilio transport
    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
    )

    params = FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        add_wav_header=False,
        serializer=serializer,
    )

    transport = FastAPIWebsocketTransport(websocket=websocket, params=params)

    await run_bot(transport, handle_sigint=False, call_sid=call_sid)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Bright Smiles Dental Agent Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "7860")), help="Port")
    args = parser.parse_args()

    logger.info(f"Starting server on {args.host}:{args.port}")
    uvicorn.run(
        "server.server:app",
        host=args.host,
        port=args.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
