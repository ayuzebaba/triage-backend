"""
BRISK Patient Login Module
---------------------------
Health card number + OTP login, using Twilio Verify — the same
product (not a custom SMS system) already used successfully for
EkitiGov's phone-based login.

This does NOT replace registration. It's how a patient proves they
are the SAME person across devices/visits: they enter their health
card number, get a 6-digit code via SMS to their phone, and entering
it correctly confirms identity — then find_or_create_by_health_card()
either finds their existing triage_registration or creates one.

Requires these environment variables (e.g. in Railway):
    TWILIO_ACCOUNT_SID          (same account already used for the
                                  emergency call feature)
    TWILIO_AUTH_TOKEN
    TWILIO_VERIFY_SERVICE_SID   (starts with "VA..." — a NEW Verify
                                  Service, separate from the one used
                                  for EkitiGov, since these are
                                  different applications. Create one
                                  at console.twilio.com -> Verify ->
                                  Services -> Create new.)

IMPORTANT: these are read lazily (inside a function), NOT at module
load time. Reading them with os.environ[...] at the top of the file
would crash the entire app on import the moment main.py starts --
including the already-working Twilio 911 call and ER routing -- if
TWILIO_VERIFY_SERVICE_SID isn't set in Railway yet (which it isn't,
since this is a brand new feature). Fixed defensively here instead
of just documented as a setup requirement.
"""

import os
from typing import Optional
from twilio.rest import Client

_twilio_client: Optional[Client] = None
_verify_service_sid: Optional[str] = None


def _get_verify_client():
    """
    Lazily creates the Twilio client and reads the Verify Service SID on
    first real use. Returns (None, None) -- never raises -- if any of the
    3 required env vars aren't set, so callers can return a clear error
    status instead of crashing the whole app on startup.
    """
    global _twilio_client, _verify_service_sid
    if _twilio_client is not None and _verify_service_sid is not None:
        return _twilio_client, _verify_service_sid

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    verify_sid = os.environ.get("TWILIO_VERIFY_SERVICE_SID")

    if not account_sid or not auth_token or not verify_sid:
        print("[patient_login] Twilio Verify env vars not fully set -- patient login disabled")
        return None, None

    _twilio_client = Client(account_sid, auth_token)
    _verify_service_sid = verify_sid
    return _twilio_client, _verify_service_sid


def send_otp(phone_number: str) -> dict:
    """
    Sends a 6-digit OTP to the given phone number via Twilio Verify.
    phone_number must be in E.164 format (e.g. +13068804290).
    """
    client, verify_sid = _get_verify_client()
    if client is None:
        return {"status": "not_configured", "reason": "Twilio Verify env vars not set"}
    try:
        verification = client.verify.v2.services(verify_sid).verifications.create(
            to=phone_number, channel="sms"
        )
        return {"status": "sent", "verification_status": verification.status}
    except Exception as e:
        print(f"[patient_login] send_otp failed: {e}")
        return {"status": "error", "reason": str(e)}


def check_otp(phone_number: str, code: str) -> dict:
    """
    Verifies the OTP the patient typed in against Twilio Verify.
    Returns {"status": "approved"} only on a genuine match.
    """
    client, verify_sid = _get_verify_client()
    if client is None:
        return {"status": "not_configured", "reason": "Twilio Verify env vars not set"}
    try:
        check = client.verify.v2.services(verify_sid).verification_checks.create(
            to=phone_number, code=code
        )
        if check.status == "approved":
            return {"status": "approved"}
        return {"status": "denied", "verification_status": check.status}
    except Exception as e:
        print(f"[patient_login] check_otp failed: {e}")
        return {"status": "error", "reason": str(e)}