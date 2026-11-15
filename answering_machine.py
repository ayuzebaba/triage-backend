"""
BRISK Voicemail Detection Module (closed-loop emergency response, step 9)
---------------------------------------------------------------------------
Twilio can tell whether an emergency call was answered by a PERSON or by a
voicemail / answering machine. "Completed" alone does not say that: a call that
rings out to voicemail is also "completed". This module records the answer on
the call's row (triage_activation_calls.answered_by) so staff see it.

How it works (asynchronous detection, so the call itself is NOT delayed):
  - emergency_call.py asks Twilio to run machine detection in parallel.
  - A few seconds into the call, Twilio posts the result to POST /twilio/amd.
  - This module checks Twilio's signature and stores it:
        human                               -> 'human'
        machine_start / machine_end_beep /
        machine_end_silence / machine_end_other -> 'machine'
        fax                                 -> 'fax'
        unknown                             -> 'unknown'
    The raw Twilio value is also kept in the activity log.

Safety rules
- It only RECORDS information. It never changes whether or when a contact is
  called, and never marks anything acknowledged. Escalation is unchanged.
- Every request is signature-checked. Never raises. Database trouble returns 200.
- Needs one new column (see add_answered_by_column.sql). If the column is not
  there yet, the update fails quietly and the call is unaffected.
"""

import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import parse_qs

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

try:
    from activations_db import _get_supabase, add_log
except Exception as _e:  # never let this stop the app
    print(f"[answering_machine] activations_db unavailable, detection disabled: {_e}")

    def _get_supabase():
        return None

    def add_log(*args, **kwargs):
        return {"status": "not_configured"}

router = APIRouter()

LOOKUP_ATTEMPTS = 4
LOOKUP_PAUSE_SECONDS = 0.6


def classify(answered_by: Optional[str]) -> str:
    v = (answered_by or "").strip().lower()
    if v == "human":
        return "human"
    if v.startswith("machine"):
        return "machine"
    if v == "fax":
        return "fax"
    return "unknown"


def _callback_url() -> str:
    return f"{os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')}/twilio/amd"


def _signature_ok(signature: Optional[str], params: Dict[str, str]) -> bool:
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not token or not signature or not os.environ.get("PUBLIC_BASE_URL"):
        return False
    try:
        from twilio.request_validator import RequestValidator
        return bool(RequestValidator(token).validate(_callback_url(), params, signature))
    except Exception as e:
        print(f"[answering_machine] signature check failed to run: {e}")
        return False


def apply_result(call_sid: str, answered_by: str) -> dict:
    """Blocking (runs in a thread). Never raises."""
    try:
        db = _get_supabase()
        if db is None:
            return {"result": "not_configured"}
        row = None
        for attempt in range(LOOKUP_ATTEMPTS):
            res = (
                db.table("triage_activation_calls")
                .select("id,activation_id,level")
                .eq("call_sid", call_sid)
                .limit(1)
                .execute()
            )
            row = res.data[0] if res.data else None
            if row:
                break
            if attempt < LOOKUP_ATTEMPTS - 1:
                time.sleep(LOOKUP_PAUSE_SECONDS)
        if not row:
            return {"result": "unknown_call"}

        kind = classify(answered_by)
        (
            db.table("triage_activation_calls")
            .update({"answered_by": kind})
            .eq("id", row["id"])
            .execute()
        )
        add_log(row["activation_id"], "call_status",
                {"level": row.get("level"), "answered_by": answered_by, "kind": kind})
        return {"result": "recorded", "kind": kind}
    except Exception as e:
        print(f"[answering_machine] apply_result failed (is the answered_by column added?): {e}")
        return {"result": "error"}


@router.post("/twilio/amd")
async def twilio_amd(request: Request):
    try:
        raw = (await request.body()).decode("utf-8", errors="replace")
        params = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
    except Exception as e:
        print(f"[answering_machine] could not read request: {e}")
        return Response(status_code=400)

    if not _signature_ok(request.headers.get("X-Twilio-Signature"), params):
        print("[answering_machine] rejected request with missing or invalid Twilio signature")
        return Response(status_code=403)

    call_sid = params.get("CallSid")
    answered_by = params.get("AnsweredBy")
    if not call_sid or not answered_by:
        return Response(status_code=200)

    outcome = await run_in_threadpool(apply_result, call_sid, answered_by)
    print(f"[answering_machine] {call_sid[-6:]} {answered_by} -> {outcome.get('result')}")
    return Response(status_code=200)

