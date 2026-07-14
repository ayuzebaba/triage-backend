"""
BRISK Emergency Call Module
----------------------------
Places an automatic outbound voice call to the clinical contact number
when a patient's symptom severity crosses the emergency threshold (9-10).

Requires these environment variables to be set (e.g. in Railway):
    TWILIO_ACCOUNT_SID
    TWILIO_AUTH_TOKEN
    TWILIO_PHONE_NUMBER          (the Twilio number calling FROM, e.g. +16722075007)
    CLINICAL_CONTACT_NUMBER      (the number to call TO, e.g. +13068804290)
    PUBLIC_BASE_URL              (your Railway backend's public URL, e.g.
                                  https://triage-backend-production.up.railway.app)
"""

import os
from urllib.parse import quote
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

# --- Twilio client setup -----------------------------------------------
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_PHONE_NUMBER = os.environ["TWILIO_PHONE_NUMBER"]
CLINICAL_CONTACT_NUMBER = os.environ["CLINICAL_CONTACT_NUMBER"]
PUBLIC_BASE_URL = os.environ["PUBLIC_BASE_URL"]

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Simple in-memory guard so the same patient session doesn't trigger
# multiple calls if severity is re-submitted. For production, replace
# this with a database-backed check (e.g. a "call_triggered" flag on
# the patient session record in Supabase/Postgres).
_already_called_sessions = set()


def trigger_emergency_call(session_id: str, severity: int, symptom: str,
                            location: str = "location unavailable") -> dict:
    """
    Places an outbound call to the clinical contact if severity >= 9.

    Args:
        session_id: unique identifier for this patient's assessment session,
                     used to prevent duplicate calls for the same session.
        severity: the patient's reported/assigned severity (1-10).
        symptom: short description of the triggering symptom.
        location: patient's detected location, if available.

    Returns:
        dict with call status info, or a "skipped" reason.
    """
    if severity < 9:
        return {"status": "skipped", "reason": "severity below threshold"}

    if session_id in _already_called_sessions:
        return {"status": "skipped", "reason": "call already placed for this session"}

    # Build the TwiML callback URL with the details as query params.
    # Twilio will fetch this URL when the call connects, to know what to say.
    # IMPORTANT: symptom/location often contain spaces, parentheses, etc.
    # Twilio rejects the whole request with "Url is not a valid URL" if these
    # aren't percent-encoded first.
    safe_symptom = quote(str(symptom))
    safe_location = quote(str(location))
    twiml_url = (
        f"{PUBLIC_BASE_URL}/emergency-call-twiml"
        f"?severity={severity}&symptom={safe_symptom}&location={safe_location}"
    )

    call = client.calls.create(
        to=CLINICAL_CONTACT_NUMBER,
        from_=TWILIO_PHONE_NUMBER,
        url=twiml_url,
    )

    _already_called_sessions.add(session_id)

    return {"status": "call_placed", "call_sid": call.sid}


def build_emergency_twiml(severity: str, symptom: str, location: str) -> str:
    """
    Builds the spoken message Twilio reads out when the clinical contact
    answers the call. Called by the /emergency-call-twiml endpoint.
    """
    response = VoiceResponse()
    response.say(
        f"This is an automated alert from the BRISK Triage System. "
        f"A patient has reported an emergency severity of {severity} out of 10, "
        f"with the symptom: {symptom}. "
        f"Patient location: {location}. "
        f"Please respond immediately. "
        f"This message will now repeat.",
        voice="alice",
    )
    # Repeat once more in case the person picks up mid-message
    response.say(
        f"Repeating: severity {severity} out of 10 emergency, symptom {symptom}, "
        f"location {location}. Please respond immediately.",
        voice="alice",
    )
    return str(response)