"""OpenAI function-calling tool definitions and handlers for Mia.

Registers 7 tools on the LLM service:
  check_availability, book_appointment, lookup_booking,
  cancel_appointment, reschedule_appointment, transfer_to_human, end_call.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import EndFrame, TTSSpeakFrame
from pipecat.services.llm_service import FunctionCallParams

from server.integrations import calcom_client

if TYPE_CHECKING:
    from pipecat.pipeline.task import PipelineTask
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.services.tts_service import TTSService


# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------

check_availability_schema = FunctionSchema(
    name="check_availability",
    description=(
        "Check available appointment slots on a given date. "
        "Returns up to 5 open time slots."
    ),
    properties={
        "date": {
            "type": "string",
            "description": "The date to check, in YYYY-MM-DD format (e.g. 2025-06-15).",
        },
        "time_preference": {
            "type": "string",
            "description": "Optional preference: 'morning', 'afternoon', 'evening', or 'any'.",
            "enum": ["morning", "afternoon", "evening", "any"],
        },
    },
    required=["date"],
)

book_appointment_schema = FunctionSchema(
    name="book_appointment",
    description=(
        "Book a dental appointment after the caller has confirmed the details. "
        "Only call this after reading back details and receiving a 'yes'."
    ),
    properties={
        "full_name": {
            "type": "string",
            "description": "Caller's full name.",
        },
        "phone": {
            "type": "string",
            "description": "Caller's phone number.",
        },
        "email": {
            "type": "string",
            "description": "Caller's email address.",
        },
        "start_iso": {
            "type": "string",
            "description": "Selected slot start time in ISO 8601 format.",
        },
        "reason": {
            "type": "string",
            "description": "Reason for the dental visit.",
        },
    },
    required=["full_name", "phone", "email", "start_iso", "reason"],
)

lookup_booking_schema = FunctionSchema(
    name="lookup_booking",
    description=(
        "Look up upcoming bookings for a caller by name and phone or email."
    ),
    properties={
        "full_name": {
            "type": "string",
            "description": "Caller's full name.",
        },
        "phone": {
            "type": "string",
            "description": "Caller's phone number (optional if email provided).",
        },
        "email": {
            "type": "string",
            "description": "Caller's email (optional if phone provided).",
        },
    },
    required=["full_name"],
)

cancel_appointment_schema = FunctionSchema(
    name="cancel_appointment",
    description=(
        "Cancel an existing appointment. Only call after confirming with the caller."
    ),
    properties={
        "booking_uid": {
            "type": "string",
            "description": "The booking UID from lookup_booking.",
        },
        "reason": {
            "type": "string",
            "description": "Why the appointment is being cancelled.",
        },
    },
    required=["booking_uid", "reason"],
)

reschedule_appointment_schema = FunctionSchema(
    name="reschedule_appointment",
    description=(
        "Reschedule an existing appointment to a new time. "
        "Only call after confirming with the caller."
    ),
    properties={
        "booking_uid": {
            "type": "string",
            "description": "The booking UID from lookup_booking.",
        },
        "new_start_iso": {
            "type": "string",
            "description": "New slot start time in ISO 8601 format.",
        },
        "reason": {
            "type": "string",
            "description": "Why the appointment is being rescheduled.",
        },
    },
    required=["booking_uid", "new_start_iso", "reason"],
)

transfer_to_human_schema = FunctionSchema(
    name="transfer_to_human",
    description=(
        "Transfer the call to a human team member at the front desk. "
        "Use when the caller asks for a human, has a billing issue, "
        "asks about prices/insurance, reports an emergency, "
        "or you fail to understand them 3 times."
    ),
    properties={
        "reason": {
            "type": "string",
            "description": "Brief reason for the transfer.",
        },
    },
    required=["reason"],
)

end_call_schema = FunctionSchema(
    name="end_call",
    description=(
        "End the call after the conversation is complete. "
        "Only call this after saying goodbye."
    ),
    properties={
        "reason": {
            "type": "string",
            "description": "Brief reason for ending the call (e.g. 'conversation complete').",
        },
    },
    required=["reason"],
)

ALL_TOOLS = ToolsSchema(
    standard_tools=[
        check_availability_schema,
        book_appointment_schema,
        lookup_booking_schema,
        cancel_appointment_schema,
        reschedule_appointment_schema,
        transfer_to_human_schema,
        end_call_schema,
    ]
)


# ---------------------------------------------------------------------------
# Handler factory — binds the task and call_sid so handlers can push frames
# ---------------------------------------------------------------------------

def register_tools(
    llm: "OpenAILLMService",
    tts: "TTSService",
    task: "PipelineTask",
    call_sid_holder: dict[str, str | None],
) -> None:
    """Register all tool handlers on the LLM service.

    Args:
        llm: The OpenAI LLM service instance.
        tts: The TTS service (for interim speech while tools run).
        task: The pipeline task (for queuing EndFrame).
        call_sid_holder: Mutable dict with key "call_sid" holding the Twilio call SID (or None for WebRTC).
    """

    async def _handle_check_availability(params: FunctionCallParams):
        args = params.arguments
        logger.info(f"Tool: check_availability({args})")
        result = await calcom_client.check_availability(
            date=args["date"],
            time_preference=args.get("time_preference"),
        )
        await params.result_callback(result)

    async def _handle_book_appointment(params: FunctionCallParams):
        args = params.arguments
        logger.info(f"Tool: book_appointment({args})")
        result = await calcom_client.book_appointment(
            full_name=args["full_name"],
            phone=args["phone"],
            email=args["email"],
            start_iso=args["start_iso"],
            reason=args["reason"],
        )
        await params.result_callback(result)

    async def _handle_lookup_booking(params: FunctionCallParams):
        args = params.arguments
        logger.info(f"Tool: lookup_booking({args})")
        result = await calcom_client.lookup_booking(
            full_name=args["full_name"],
            phone=args.get("phone"),
            email=args.get("email"),
        )
        await params.result_callback(result)

    async def _handle_cancel_appointment(params: FunctionCallParams):
        args = params.arguments
        logger.info(f"Tool: cancel_appointment({args})")
        result = await calcom_client.cancel_appointment(
            booking_uid=args["booking_uid"],
            reason=args["reason"],
        )
        await params.result_callback(result)

    async def _handle_reschedule_appointment(params: FunctionCallParams):
        args = params.arguments
        logger.info(f"Tool: reschedule_appointment({args})")
        result = await calcom_client.reschedule_appointment(
            booking_uid=args["booking_uid"],
            new_start_iso=args["new_start_iso"],
            reason=args["reason"],
        )
        await params.result_callback(result)

    async def _handle_transfer_to_human(params: FunctionCallParams):
        args = params.arguments
        reason = args.get("reason", "Caller requested transfer")
        logger.info(f"Tool: transfer_to_human — {reason}")

        call_sid = call_sid_holder.get("call_sid")
        if call_sid:
            from server.integrations.twilio_client import transfer_call
            result = await transfer_call(call_sid, reason)
        else:
            # WebRTC / browser mode — can't actually transfer
            result = {
                "ok": True,
                "message": "Transfer requested (no active phone call to transfer in browser mode).",
            }
        await params.result_callback(result)

    async def _handle_end_call(params: FunctionCallParams):
        args = params.arguments
        reason = args.get("reason", "conversation complete")
        logger.info(f"Tool: end_call — {reason}")
        await params.result_callback({"ok": True, "message": "Ending call."})
        # Push EndFrame to gracefully shut down the pipeline
        await task.queue_frames([EndFrame()])

    # Register all handlers
    llm.register_function("check_availability", _handle_check_availability)
    llm.register_function("book_appointment", _handle_book_appointment)
    llm.register_function("lookup_booking", _handle_lookup_booking)
    llm.register_function("cancel_appointment", _handle_cancel_appointment)
    llm.register_function("reschedule_appointment", _handle_reschedule_appointment)
    llm.register_function("transfer_to_human", _handle_transfer_to_human)
    llm.register_function("end_call", _handle_end_call)

    # Interim speech while long-running tools execute
    @llm.event_handler("on_function_calls_started")
    async def _on_fc_started(service, function_calls):
        names = [fc.function_name for fc in function_calls]
        if any(n in names for n in ["check_availability", "lookup_booking"]):
            await tts.queue_frame(TTSSpeakFrame("Let me check on that for you."))
        elif "book_appointment" in names:
            await tts.queue_frame(TTSSpeakFrame("Just booking that in for you now."))
        elif "cancel_appointment" in names:
            await tts.queue_frame(TTSSpeakFrame("One moment while I cancel that."))
        elif "reschedule_appointment" in names:
            await tts.queue_frame(TTSSpeakFrame("Let me reschedule that for you."))
