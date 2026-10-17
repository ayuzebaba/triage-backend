"""
BRISK Acknowledgement Module (closed-loop emergency response, step 4)
---------------------------------------------------------------------------
Adds "press 1 to acknowledge" to the clinical-contact emergency call.

How it works
  1. emergency_call.py puts a random one-time token in the call's TwiML URL
     (&ack=TOKEN) and saves the same token on the call's database row.
  2. When the contact answers, build_ack_twiml() produces the spoken message
     inside a <Gather>: the contact can press 1 at any time.
  3. Pressing a key makes Twilio POST to /twilio/ack?t=TOKEN. This module
     checks Twilio's signature, matches the token AND the call SID to one call
     row, then marks the activation acknowledged (via "keypress").

Safety rules
- build_ack_twiml() needs no database. If anything about it fails, main.py
  falls back to the original message, so the call itself never changes.
- /twilio/ack is signature-checked, token-checked and call-SID-checked.
- Idempotent: pressing 1 twice, or a second contact pressing 1 later, never
  double-records and never overwrites the first acknowledgement.
- Never raises. If the database is down the caller hears an honest message
  and the alert stays unacknowledged (the safe direction: later escalation
  would treat it as unanswered).
- "Acknowledged" means a person confirmed the alert, NOT that the patient has
  been helped. Staff record the outcome separately (step 7).
"""

import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import parse_qs

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool
from twilio.twiml.voice_response import VoiceResponse

try:
    from activations_db import _get_supabase, add_log
except Exception as _e:  # never let this stop the app
    print(f"[ack_flow] activations_db unavailable, acknowledgements disabled: {_e}")

    def _get_supabase():
        return None

    def add_log(*args, **kwargs):
        return {"status": "not_configured"}

router = APIRouter()

GATHER_TIMEOUT_SECONDS = 15   # silence allowed after the message, per round
MAX_WRONG_KEYS = 2            # re-prompts for a key other than 1
LOOKUP_ATTEMPTS = 3
LOOKUP_PAUSE_SECONDS = 0.5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")


def _ack_url(token: str, wrong: int = 0) -> str:
    url = f"{_base()}/twilio/ack?t={token}"
    if wrong:
        url += f"&w={wrong}"
    return url


# ── TwiML ──────────────────────────────────────────────────────────────────

def build_ack_twiml(severity: str, symptom: str, location: str, token: str, level: int = 1) -> str:
    """Spoken alert with 'press 1 to acknowledge'. Pure function, no database."""
    if not token:
        raise ValueError("ack token required")
    action = _ack_url(token)
    response = VoiceResponse()

    g1 = response.gather(input="dtmf", num_digits=1, timeout=GATHER_TIMEOUT_SECONDS,
                         action=action, method="POST")
    if level and level > 1:
        opening = ("This is a BRISK Triage System ESCALATED ALERT. "
                   "The previous contact did not acknowledge. ")
    else:
        opening = "This is a BRISK Triage System ALERT from Ayodele in Saskatoon to Dr Obayan in Nipawin. "
    g1.say(
        f"{opening}"
        f"A patient has reported an emergency severity of {severity} out of 10, "
        f"with the symptom: {symptom}. "
        f"Approximate patient location: {location}. This location is based on GPS and may be off "
        f"by a house or two, please confirm with the patient if possible. "
        f"Please respond immediately. "
        f"To acknowledge this alert, press 1 now.",
        voice="alice",
    )

    g2 = response.gather(input="dtmf", num_digits=1, timeout=GATHER_TIMEOUT_SECONDS,
                         action=action, method="POST")
    g2.say(
        f"Repeating: severity {severity} out of 10 emergency, symptom {symptom}, "
        f"approximate location {location}. Please respond immediately. "
        f"To acknowledge this alert, press 1 now.",
        voice="alice",
    )

    response.say("No acknowledgement was received. Goodbye.", voice="alice")
    return str(response)


def _say_and_hangup(text: str) -> str:
    response = VoiceResponse()
    response.say(text, voice="alice")
    response.hangup()
    return str(response)


def _reprompt_twiml(token: str, wrong: int) -> str:
    response = VoiceResponse()
    g = response.gather(input="dtmf", num_digits=1, timeout=GATHER_TIMEOUT_SECONDS,
                        action=_ack_url(token, wrong), method="POST")
    g.say("That was not 1. To acknowledge this alert, press 1 now.", voice="alice")
    response.say("No acknowledgement was received. Goodbye.", voice="alice")
    return str(response)


# ── signature ──────────────────────────────────────────────────────────────

def _signature_ok(signature: Optional[str], full_url: str, params: Dict[str, str]) -> bool:
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not token or not signature or not _base():
        return False
    try:
        from twilio.request_validator import RequestValidator
        return bool(RequestValidator(token).validate(full_url, params, signature))
    except Exception as e:
        print(f"[ack_flow] signature check failed to run: {e}")
        return False


# ── database ───────────────────────────────────────────────────────────────

def record_ack(token: str, call_sid: str) -> str:
    """
    Blocking (runs in a thread). Returns one of:
      "acknowledged"  this press recorded the acknowledgement
      "already"       the activation was already acknowledged / closed (still fine)
      "unknown"       token or call SID did not match a call
      "error"         database problem; nothing (or not everything) was recorded
    Never raises.
    """
    try:
        db = _get_supabase()
        if db is None:
            return "error"

        row = None
        for attempt in range(LOOKUP_ATTEMPTS):
            res = (
                db.table("triage_activation_calls")
                .select("id,activation_id,level,to_number,contact_name,call_sid,ack_at")
                .eq("ack_token", token)
                .limit(1)
                .execute()
            )
            row = res.data[0] if res.data else None
            if row:
                break
            if attempt < LOOKUP_ATTEMPTS - 1:
                time.sleep(LOOKUP_PAUSE_SECONDS)
        if not row or not call_sid or row.get("call_sid") != call_sid:
            return "unknown"

        now = _now_iso()
        who = row.get("contact_name") or row.get("to_number") or f"level {row.get('level')} contact"

        # 1) The activation first: this is the record that matters.
        upd = (
            db.table("triage_activations")
            .update({
                "status": "acknowledged",
                "acknowledged_at": now,
                "acknowledged_via": "keypress",
                "acknowledged_by": who,
                "updated_at": now,
            })
            .eq("id", row["activation_id"])
            .in_("status", ["active", "exhausted"])   # a late press after exhaustion still counts
            .execute()
        )
        first_press = bool(upd.data)

        # 2) Then this call's own ack time (only if not already set).
        try:
            (
                db.table("triage_activation_calls")
                .update({"ack_at": now})
                .eq("id", row["id"])
                .is_("ack_at", "null")
                .execute()
            )
        except Exception as e:
            print(f"[ack_flow] could not stamp ack_at on call row: {e}")

        if first_press:
            add_log(row["activation_id"], "acknowledged",
                    {"via": "keypress", "level": row.get("level"), "call_sid": call_sid})
            return "acknowledged"
        return "already"
    except Exception as e:
        print(f"[ack_flow] record_ack failed: {e}")
        return "error"


# ── endpoint ───────────────────────────────────────────────────────────────

def _xml(body: str, status: int = 200) -> Response:
    return Response(content=body, media_type="application/xml", status_code=status)


@router.post("/twilio/ack")
async def twilio_ack(request: Request):
    try:
        raw = (await request.body()).decode("utf-8", errors="replace")
        params = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
        qs = request.scope.get("query_string", b"").decode("utf-8", errors="replace")
        query = {k: v[0] for k, v in parse_qs(qs, keep_blank_values=True).items()}
    except Exception as e:
        print(f"[ack_flow] could not read request: {e}")
        return Response(status_code=400)

    full_url = f"{_base()}/twilio/ack" + (f"?{qs}" if qs else "")
    if not _signature_ok(request.headers.get("X-Twilio-Signature"), full_url, params):
        print("[ack_flow] rejected request with missing or invalid Twilio signature")
        return Response(status_code=403)

    token = query.get("t", "")
    digits = params.get("Digits", "")
    call_sid = params.get("CallSid", "")
    try:
        wrong = int(query.get("w", "0"))
    except ValueError:
        wrong = 0

    if not token:
        return _xml(_say_and_hangup("Sorry, this alert could not be matched. Goodbye."))

    if digits != "1":
        if wrong + 1 >= MAX_WRONG_KEYS:
            return _xml(_say_and_hangup("No acknowledgement was received. Goodbye."))
        return _xml(_reprompt_twiml(token, wrong + 1))

    outcome = await run_in_threadpool(record_ack, token, call_sid)
    print(f"[ack_flow] {call_sid[-6:] if call_sid else '??????'} press-1 -> {outcome}")

    if outcome in ("acknowledged", "already"):
        return _xml(_say_and_hangup("Acknowledged. Thank you. Please attend to the patient."))
    if outcome == "unknown":
        return _xml(_say_and_hangup("Sorry, this alert could not be matched. Please act on it now. Goodbye."))
    return _xml(_say_and_hangup(
        "We could not record your response. Please act on this alert now. Goodbye."))
