"""Async httpx client for Cal.com API v2."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import httpx
from loguru import logger

CALCOM_TIMEOUT = 6.0  # seconds
CALCOM_API_VERSION = "2024-08-13"


def _headers() -> dict[str, str]:
    api_key = os.environ["CALCOM_API_KEY"]
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "cal-api-version": CALCOM_API_VERSION,
    }


def _base_url() -> str:
    return os.getenv("CALCOM_API_BASE", "https://api.cal.com/v2")


def _tz() -> str:
    return os.getenv("CALCOM_TIMEZONE", "Australia/Brisbane")


def _event_type_id() -> int:
    return int(os.environ["CALCOM_EVENT_TYPE_ID"])


async def check_availability(
    date: str, time_preference: str | None = None
) -> dict:
    """Get up to 5 open slots for a given date.

    Args:
        date: ISO date string, e.g. "2025-06-15".
        time_preference: Optional hint like "morning", "afternoon", "any".

    Returns:
        dict with ok=True and slots list, or ok=False and error.
    """
    try:
        # Build start / end for the full day
        start_dt = datetime.fromisoformat(date)
        end_dt = start_dt + timedelta(days=1)

        params = {
            "eventTypeId": _event_type_id(),
            "startTime": start_dt.strftime("%Y-%m-%dT00:00:00Z"),
            "endTime": end_dt.strftime("%Y-%m-%dT23:59:59Z"),
        }

        async with httpx.AsyncClient(timeout=CALCOM_TIMEOUT) as client:
            resp = await client.get(
                f"{_base_url()}/slots",
                headers=_headers(),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        # Parse the nested slots structure
        raw_slots = data.get("data", {})
        if isinstance(raw_slots, dict) and "slots" in raw_slots:
            raw_slots = raw_slots["slots"]

        all_slots: list[dict] = []
        if isinstance(raw_slots, dict):
            for day_key, day_slots in raw_slots.items():
                if isinstance(day_slots, list):
                    for slot in day_slots:
                        time_str = slot.get("time") or slot.get("start", "")
                        if time_str:
                            all_slots.append({"start": time_str})
        elif isinstance(raw_slots, list):
            for slot in raw_slots:
                time_str = slot.get("time") or slot.get("start", "")
                if time_str:
                    all_slots.append({"start": time_str})

        # Optional: filter by time preference
        if time_preference and time_preference.lower() != "any":
            filtered = []
            for s in all_slots:
                try:
                    hour = datetime.fromisoformat(
                        s["start"].replace("Z", "+00:00")
                    ).hour
                except Exception:
                    filtered.append(s)
                    continue
                if time_preference.lower() == "morning" and hour < 12:
                    filtered.append(s)
                elif time_preference.lower() == "afternoon" and 12 <= hour < 17:
                    filtered.append(s)
                elif time_preference.lower() == "evening" and hour >= 17:
                    filtered.append(s)
                else:
                    filtered.append(s)
            all_slots = filtered

        return {"ok": True, "slots": all_slots[:5]}

    except Exception as exc:
        logger.error(f"check_availability failed: {exc}")
        return {"ok": False, "error": str(exc)}


async def book_appointment(
    full_name: str,
    phone: str,
    email: str,
    start_iso: str,
    reason: str,
) -> dict:
    """Create a booking on Cal.com.

    Args:
        full_name: Attendee's full name.
        phone: Attendee's phone number.
        email: Attendee's email.
        start_iso: ISO 8601 start time.
        reason: Reason for the visit.

    Returns:
        dict with ok, booking_uid, message.
    """
    try:
        body = {
            "start": start_iso,
            "eventTypeId": _event_type_id(),
            "attendee": {
                "name": full_name,
                "email": email,
                "timeZone": _tz(),
                "phoneNumber": phone,
            },
            "bookingFieldsResponses": {
                "notes": reason,
            },
        }

        async with httpx.AsyncClient(timeout=CALCOM_TIMEOUT) as client:
            resp = await client.post(
                f"{_base_url()}/bookings",
                headers=_headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        booking = data.get("data", {})
        uid = booking.get("uid", "unknown")

        return {
            "ok": True,
            "booking_uid": uid,
            "message": f"Booking confirmed (ref: {uid}).",
        }

    except Exception as exc:
        logger.error(f"book_appointment failed: {exc}")
        return {"ok": False, "error": str(exc)}


async def lookup_booking(
    full_name: str,
    phone: str | None = None,
    email: str | None = None,
) -> dict:
    """Look up upcoming bookings by attendee info.

    Args:
        full_name: Name to search for.
        phone: Phone to match (optional).
        email: Email to match (optional).

    Returns:
        dict with ok and bookings list, or ok=False and error.
    """
    try:
        params: dict[str, str] = {"status": "upcoming"}
        if email:
            params["attendeeEmail"] = email

        async with httpx.AsyncClient(timeout=CALCOM_TIMEOUT) as client:
            resp = await client.get(
                f"{_base_url()}/bookings",
                headers=_headers(),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        bookings_raw = data.get("data", [])
        if isinstance(bookings_raw, dict):
            bookings_raw = bookings_raw.get("bookings", [])

        matches: list[dict] = []
        name_lower = full_name.lower()
        for b in bookings_raw:
            attendees = b.get("attendees", [])
            for att in attendees:
                att_name = (att.get("name") or "").lower()
                att_email = (att.get("email") or "").lower()
                att_phone = att.get("phoneNumber") or ""
                if name_lower in att_name:
                    matches.append(
                        {
                            "uid": b.get("uid"),
                            "title": b.get("title", ""),
                            "start": b.get("start", ""),
                            "end": b.get("end", ""),
                            "status": b.get("status", ""),
                        }
                    )
                    break
                if email and email.lower() == att_email:
                    matches.append(
                        {
                            "uid": b.get("uid"),
                            "title": b.get("title", ""),
                            "start": b.get("start", ""),
                            "end": b.get("end", ""),
                            "status": b.get("status", ""),
                        }
                    )
                    break
                if phone and phone in att_phone:
                    matches.append(
                        {
                            "uid": b.get("uid"),
                            "title": b.get("title", ""),
                            "start": b.get("start", ""),
                            "end": b.get("end", ""),
                            "status": b.get("status", ""),
                        }
                    )
                    break

        return {"ok": True, "bookings": matches}

    except Exception as exc:
        logger.error(f"lookup_booking failed: {exc}")
        return {"ok": False, "error": str(exc)}


async def cancel_appointment(booking_uid: str, reason: str) -> dict:
    """Cancel a booking by UID.

    Args:
        booking_uid: The Cal.com booking UID.
        reason: Cancellation reason.

    Returns:
        dict with ok and message.
    """
    try:
        body = {"cancellationReason": reason}

        async with httpx.AsyncClient(timeout=CALCOM_TIMEOUT) as client:
            resp = await client.post(
                f"{_base_url()}/bookings/{booking_uid}/cancel",
                headers=_headers(),
                json=body,
            )
            resp.raise_for_status()

        return {"ok": True, "message": f"Booking {booking_uid} cancelled."}

    except Exception as exc:
        logger.error(f"cancel_appointment failed: {exc}")
        return {"ok": False, "error": str(exc)}


async def reschedule_appointment(
    booking_uid: str, new_start_iso: str, reason: str
) -> dict:
    """Reschedule a booking to a new time.

    Args:
        booking_uid: The Cal.com booking UID.
        new_start_iso: New ISO 8601 start time.
        reason: Reason for rescheduling.

    Returns:
        dict with ok, new_booking_uid, and message.
    """
    try:
        body = {
            "start": new_start_iso,
            "rescheduleReason": reason,
        }

        async with httpx.AsyncClient(timeout=CALCOM_TIMEOUT) as client:
            resp = await client.post(
                f"{_base_url()}/bookings/{booking_uid}/reschedule",
                headers=_headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        new_booking = data.get("data", {})
        new_uid = new_booking.get("uid", booking_uid)

        return {
            "ok": True,
            "new_booking_uid": new_uid,
            "message": f"Booking rescheduled (new ref: {new_uid}).",
        }

    except Exception as exc:
        logger.error(f"reschedule_appointment failed: {exc}")
        return {"ok": False, "error": str(exc)}
