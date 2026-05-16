"""Twilio REST wrapper for live call transfer."""

from __future__ import annotations

import os

from loguru import logger

try:
    from twilio.rest import Client as TwilioClient
except ModuleNotFoundError:
    TwilioClient = None  # type: ignore[misc, assignment]


def _get_client() -> "TwilioClient":
    if TwilioClient is None:
        raise RuntimeError("twilio package is not installed")
    return TwilioClient(
        os.environ["TWILIO_ACCOUNT_SID"],
        os.environ["TWILIO_AUTH_TOKEN"],
    )


async def transfer_call(call_sid: str, reason: str) -> dict:
    """Transfer the live Twilio call to TRANSFER_TARGET_NUMBER.

    Updates the call with TwiML that <Dial>s the target number.

    Args:
        call_sid: The active Twilio Call SID.
        reason: Why the transfer is happening (for logging).

    Returns:
        dict with ok and message.
    """
    target = os.getenv("TRANSFER_TARGET_NUMBER", "")
    if not target:
        logger.warning("TRANSFER_TARGET_NUMBER not set — cannot transfer")
        return {"ok": False, "error": "Transfer number not configured."}

    if not call_sid:
        logger.warning("No call_sid provided — cannot transfer")
        return {"ok": False, "error": "No active call to transfer."}

    try:
        client = _get_client()
        twiml = (
            f'<Response>'
            f'<Say voice="Polly.Nicole">Please hold while I transfer you.</Say>'
            f'<Dial>{target}</Dial>'
            f'</Response>'
        )
        client.calls(call_sid).update(twiml=twiml)
        logger.info(f"Call {call_sid} transferred to {target} — reason: {reason}")
        return {"ok": True, "message": f"Transferring to {target}."}

    except Exception as exc:
        logger.error(f"transfer_call failed: {exc}")
        return {"ok": False, "error": str(exc)}
