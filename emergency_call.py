"""
BRISK Emergency Call Module
----------------------------
Places automatic outbound voice calls when a patient's symptom severity
crosses the emergency threshold (9-10):
  1. To the clinical contact number (always, as before).
  2. To 911 directly, IN PARALLEL, as a backup channel -- NOT a replacement
     for the patient's own tel:911 tap-to-dial button, which remains
     faster and more accurate (real carrier E911 location handoff).

IMPORTANT SAFETY NOTE: the 911 call is gated behind ENABLE_911_AUTODIAL,
defaulting to OFF. This is a real, live call to actual emergency dispatch
-- it must be deliberately enabled, tested carefully and sparingly (per
Twilio's own guidance), and ideally coordinated with local authorities
and the PI/clinical team before any real-world use. It is NOT something
that should silently start working the moment this file deploys.

Requires these environment variables to be set (e.g. in Railway):
    TWILIO_ACCOUNT_SID
    TWILIO_AUTH_TOKEN
    TWILIO_PHONE_NUMBER          (the Twilio number calling FROM, e.g. +16722075007)
    CLINICAL_CONTACT_NUMBER      (the number to call TO, e.g. +13068804290)
    PUBLIC_BASE_URL              (your Railway backend's public URL, e.g.
                                  https://triage-backend-production.up.railway.app)
    ENABLE_911_AUTODIAL          ("true" to enable the parallel 911 call;
                                  any other value, or unset, keeps it OFF)

HONEST LIMITATION (confirmed via research, see conversation): since the
Twilio number isn't registered to one single fixed address (it can't be,
for a province-wide app -- patients could be in Saskatoon, Regina, or
Nipawin), this call will route through a national emergency relay center
first, not directly to local dispatch, and Twilio charges an additional
$75 fee for this per call. The location is conveyed VERBALLY (reverse-
geocoded address spoken aloud), not via any automatic E911 location
handoff -- there's no way to make Twilio's call carry real-time GPS data
the way a patient's own phone/carrier does automatically.
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

# Safety gate for the 911 parallel call -- defaults OFF. Must be explicitly
# set to the string "true" in Railway to activate. See module docstring.
ENABLE_911_AUTODIAL = os.environ.get("ENABLE_911_AUTODIAL", "").lower() == "true"

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Simple in-memory guard so the same patient session doesn't trigger
# multiple calls if severity is re-submitted. For production, replace
# this with a database-backed check (e.g. a "call_triggered" flag on
# the patient session record in Supabase/Postgres).
_already_called_sessions = set()


def trigger_emergency_call(session_id: str, severity: int, symptom: str,
                            location: str = "location unavailable") -> dict:
    """
    Places outbound call(s) if severity >= 9:
      - Always calls the clinical contact number.
      - ALSO calls 911 directly, in parallel, but ONLY if ENABLE_911_AUTODIAL
        is set to "true". Each call is independent -- a failure in one
        never blocks or cancels the other.

    Args:
        session_id: unique identifier for this patient's assessment session,
                     used to prevent duplicate calls for the same session.
        severity: the patient's reported/assigned severity (1-10).
        symptom: short description of the triggering symptom.
        location: patient's detected location, if available.

    Returns:
        dict with call status info for both calls attempted.
    """
    if severity < 9:
        return {"status": "skipped", "reason": "severity below threshold"}

    if session_id in _already_called_sessions:
        return {"status": "skipped", "reason": "call already placed for this session"}

    safe_symptom = quote(str(symptom))
    safe_location = quote(str(location))

    clinical_result = _place_clinical_contact_call(severity, safe_symptom, safe_location)
    call_911_result = None
    if ENABLE_911_AUTODIAL:
        call_911_result = _place_911_call(severity, safe_symptom, safe_location)

    _already_called_sessions.add(session_id)

    return {
        "status": "call_placed",
        "clinical_contact_call": clinical_result,
        "call_911": call_911_result if call_911_result else {"status": "disabled", "reason": "ENABLE_911_AUTODIAL not set to true"},
    }


def _place_clinical_contact_call(severity: int, safe_symptom: str, safe_location: str) -> dict:
    """Places the call to the clinical contact. Never raises -- caught and
    reported as an error status so a failure here doesn't prevent the 911
    call attempt (or vice versa)."""
    try:
        twiml_url = (
            f"{PUBLIC_BASE_URL}/emergency-call-twiml"
            f"?severity={severity}&symptom={safe_symptom}&location={safe_location}"
        )
        call = client.calls.create(
            to=CLINICAL_CONTACT_NUMBER,
            from_=TWILIO_PHONE_NUMBER,
            url=twiml_url,
        )
        return {"status": "placed", "call_sid": call.sid}
    except Exception as e:
        print(f"[emergency_call] Clinical contact call failed: {e}")
        return {"status": "error", "reason": str(e)}


def _place_911_call(severity: int, safe_symptom: str, safe_location: str) -> dict:
    """
    Places the parallel 911 call. Never raises -- caught and reported as
    an error status so a failure here never blocks or affects the
    clinical contact call, which must keep working regardless.
    """
    try:
        twiml_url = (
            f"{PUBLIC_BASE_URL}/emergency-call-911-twiml"
            f"?severity={severity}&symptom={safe_symptom}&location={safe_location}"
        )
        call = client.calls.create(
            to="911",
            from_=TWILIO_PHONE_NUMBER,
            url=twiml_url,
        )
        return {"status": "placed", "call_sid": call.sid}
    except Exception as e:
        print(f"[emergency_call] 911 call failed: {e}")
        return {"status": "error", "reason": str(e)}


def build_emergency_twiml(severity: str, symptom: str, location: str) -> str:
    """
    Builds the spoken message Twilio reads out when the CLINICAL CONTACT
    answers the call. Called by the /emergency-call-twiml endpoint.
    """
    response = VoiceResponse()
    response.say(
        f"This is a BRISK Triage System ALERT from Ayodele in Saskatoon to Dr Obayan in Nipawin. "
        f"A patient has reported an emergency severity of {severity} out of 10, "
        f"with the symptom: {symptom}. "
        f"Approximate patient location: {location}. This location is based on GPS and may be off "
        f"by a house or two, please confirm with the patient if possible. "
        f"Please respond immediately. "
        f"This message will now repeat.",
        voice="alice",
    )
    response.say(
        f"Repeating: severity {severity} out of 10 emergency, symptom {symptom}, "
        f"approximate location {location}. Please respond immediately.",
        voice="alice",
    )
    return str(response)


def build_911_twiml(severity: str, symptom: str, location: str) -> str:
    """
    Builds the spoken message read out when 911/emergency dispatch answers
    this PARALLEL call. Worded for a professional dispatcher, not a named
    clinical contact -- states this is an automated alert from a patient
    triage app, gives the reported symptom/severity, and the best-available
    (reverse-geocoded, approximate) patient location, with an explicit
    caveat about its accuracy since it is not a real E911 location handoff.
    """
    response = VoiceResponse()
    response.say(
        f"This is an automated emergency alert from the BRISK patient triage system in "
        f"Saskatchewan. A patient has reported a severity {severity} out of 10 emergency "
        f"symptom: {symptom}. "
        f"The approximate patient location, based on GPS, is: {location}. "
        f"This location may be off by a house or two and is not a verified dispatch location. "
        f"The patient has also been shown a direct 911 call button on their own device. "
        f"This message will now repeat.",
        voice="alice",
    )
    response.say(
        f"Repeating: automated BRISK triage alert, severity {severity} out of 10, "
        f"symptom {symptom}, approximate location {location}.",
        voice="alice",
    )
    return str(response)