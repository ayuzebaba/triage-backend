"""
BRISK Call Status Module (closed-loop emergency response, step 3)
---------------------------------------------------------------------------
Twilio posts call progress events (ringing, answered, completed, ...) to
POST /twilio/call-status. This module records them on the matching row in
triage_activation_calls and appends a line to triage_activation_log.

Safety rules:
- Isolated: it only touches triage_activation_calls / triage_activation_log
  AFTER the call has been placed. It cannot stop or delay an emergency call.
- Every request is checked with Twilio's signature (X-Twilio-Signature), so
  nobody can forge a status update.
- A status only moves FORWARD (queued 0 -> initiated 1 -> ringing 2 ->
  in-progress 3 -> terminal 4). Late or duplicate events change nothing.
- Never raises: a database problem returns 200 and is printed to the log.
- "answered" is NOT "acknowledged". Acknowledgement (press 1) is step 4.
"""

import os
from urllib.parse import parse_qs
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

try:
    from activations_db import _get_supabase, add_log
except Exception as _e:  # never let this stop the app
    print(f"[call_status] activations_db unavailable, status updates disabled: {_e}")

    def _get_supabase():
        return None

    def add_log(*args, **kwargs):
        return {"status": "not_configured"}

router = APIRouter()

STATUS_RANK: Dict[str, int] = {
    "queued": 0,
    "initiated": 1,
    "ringing": 2,
    "in-progress": 3,
    "completed": 4,
    "busy": 4,
    "no-answer": 4,
    "failed": 4,
    "canceled": 4,
}

# Twilio can post "initiated"/"ringing" within milliseconds of the call being
# created, before the backend has saved the call row. Look a few times.
LOOKUP_ATTEMPTS = 4
LOOKUP_PAUSE_SECONDS = 0.6


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _callback_url() -> str:
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    return f"{base}/twilio/call-status"


def _signature_ok(signature: Optional[str], params: Dict[str, str]) -> bool:
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not token or not signature or not os.environ.get("PUBLIC_BASE_URL"):
        return False
    try:
        from twilio.request_validator import RequestValidator
        return bool(RequestValidator(token).validate(_callback_url(), params, signature))
    except Exception as e:
        print(f"[call_status] signature check failed to run: {e}")
        return False


def _find_call(db, call_sid: str) -> Optional[dict]:
    res = (
        db.table("triage_activation_calls")
        .select("id,activation_id,level,status,status_rank")
        .eq("call_sid", call_sid)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def apply_status(call_sid: str, status: str, params: Dict[str, str]) -> dict:
    """
    Blocking function (runs in a thread). Returns a small result dict:
      {"result": "updated"|"ignored"|"unknown_call"|"not_configured"|"error"}
    Never raises.
    """
    try:
        rank = STATUS_RANK.get(status)
        if rank is None:
            return {"result": "ignored", "reason": f"unrecognised status {status!r}"}
        db = _get_supabase()
        if db is None:
            return {"result": "not_configured"}

        row = None
        for attempt in range(LOOKUP_ATTEMPTS):
            row = _find_call(db, call_sid)
            if row:
                break
            if attempt < LOOKUP_ATTEMPTS - 1:
                import time
                time.sleep(LOOKUP_PAUSE_SECONDS)
        if not row:
            return {"result": "unknown_call"}

        now = _now_iso()
        patch = {"status": status, "status_rank": rank}
        if status == "in-progress":
            patch["answered_at"] = now
        if rank == 4:
            patch["ended_at"] = now

        # Conditional update: only if the stored rank is lower. Makes late and
        # duplicate events harmless even if two arrive at the same moment.
        res = (
            db.table("triage_activation_calls")
            .update(patch)
            .eq("id", row["id"])
            .lt("status_rank", rank)
            .execute()
        )
        if not res.data:
            return {"result": "ignored", "reason": "not newer than stored status"}

        detail = {"call_sid": call_sid, "level": row.get("level"), "status": status}
        duration = params.get("CallDuration")
        if duration:
            detail["duration_seconds"] = duration
        add_log(row["activation_id"], "call_status", detail)
        return {"result": "updated"}
    except Exception as e:
        print(f"[call_status] apply_status failed: {e}")
        return {"result": "error"}


@router.post("/twilio/call-status")
async def twilio_call_status(request: Request):
    try:
        raw = (await request.body()).decode("utf-8", errors="replace")
        params = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
    except Exception as e:
        print(f"[call_status] could not read request: {e}")
        return Response(status_code=400)

    if not _signature_ok(request.headers.get("X-Twilio-Signature"), params):
        print("[call_status] rejected request with missing or invalid Twilio signature")
        return Response(status_code=403)

    call_sid = params.get("CallSid")
    status = params.get("CallStatus")
    if not call_sid or not status:
        return Response(status_code=200)

    outcome = await run_in_threadpool(apply_status, call_sid, status, params)
    print(f"[call_status] {call_sid[-6:]} {status} -> {outcome.get('result')}")
    return Response(status_code=200)
