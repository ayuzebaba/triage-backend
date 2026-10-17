"""
BRISK Activations Database Module (closed-loop emergency response, step 1)
---------------------------------------------------------------------------
Reads/writes triage_activations, triage_activation_calls and
triage_activation_log in the shared scholaria-mvp Supabase project.

Same rules as triage_db.py:
- The Supabase client is created lazily (its own client, not triage_db's),
  so missing env vars or a missing package never crash startup.
- NOTHING here ever raises. A database problem must never stop the
  emergency call from being placed, so every function catches its own
  errors and returns a status dict instead.
"""

import os
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

_client = None


def _get_supabase():
    """
    Lazily creates this module's own Supabase client. Returns None (never
    raises) if the env vars are missing or the client can't be created, so
    importing this module can never crash the app.
    """
    global _client
    if _client is not None:
        return _client
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("[activations_db] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set -- activation records disabled")
        return None
    try:
        from supabase import create_client
        _client = create_client(url, key)
        return _client
    except Exception as e:
        print(f"[activations_db] could not create Supabase client: {e}")
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_unique_violation(e: Exception) -> bool:
    text = str(e).lower()
    return (
        getattr(e, "code", None) == "23505"
        or "23505" in text
        or "duplicate key" in text
        or "unique constraint" in text
    )


def create_activation(
    session_id: str,
    symptom: str,
    severity: Optional[int] = None,
    body_system: Optional[str] = None,
    patient_id: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    spoken_location: Optional[str] = None,
    location_region: Optional[str] = None,
    next_action_in_seconds: Optional[int] = None,
) -> dict:
    """
    Inserts one activation row.

    Returns one of:
      {"status": "created", "id": ...}
      {"status": "duplicate"}          -- this (session, symptom) already has an activation
      {"status": "not_configured"}     -- Supabase env vars missing
      {"status": "error", "reason": ...}
    The caller treats everything except "duplicate" as "go ahead and call".
    """
    db = _get_supabase()
    if db is None:
        return {"status": "not_configured", "reason": "Supabase env vars not set"}
    try:
        row = {
            "session_id": session_id,
            "symptom": symptom,
            "severity": severity,
            "body_system": body_system,
            "patient_id": patient_id,
            "latitude": latitude,
            "longitude": longitude,
            "spoken_location": spoken_location,
            "location_region": location_region,
        }
        if next_action_in_seconds is not None:
            # Safety net for the escalation engine (step 5): the activation is already
            # scheduled even if the server stops before the level-1 call is recorded.
            row["next_action_at"] = (datetime.now(timezone.utc) + timedelta(seconds=next_action_in_seconds)).isoformat()
        result = db.table("triage_activations").insert(row).execute()
        if not result.data:
            return {"status": "error", "reason": "insert returned no data"}
        return {"status": "created", "id": result.data[0]["id"]}
    except Exception as e:
        if _is_unique_violation(e):
            return {"status": "duplicate"}
        print(f"[activations_db] create_activation failed: {e}")
        return {"status": "error", "reason": str(e)}


def add_log(activation_id: str, event_type: str, detail: Optional[Dict[str, Any]] = None) -> dict:
    """Appends one row to the activation's history. Never raises."""
    db = _get_supabase()
    if db is None:
        return {"status": "not_configured"}
    try:
        db.table("triage_activation_log").insert({
            "activation_id": activation_id,
            "event_type": event_type,
            "detail": detail or {},
        }).execute()
        return {"status": "logged"}
    except Exception as e:
        print(f"[activations_db] add_log failed: {e}")
        return {"status": "error", "reason": str(e)}


def record_call(
    activation_id: str,
    to_number: str,
    level: int = 1,
    contact_name: Optional[str] = None,
    call_sid: Optional[str] = None,
    error: Optional[str] = None,
    ack_token: Optional[str] = None,
) -> dict:
    """
    Records one call attempt. If Twilio rejected the call (error set, no SID)
    the row is saved as 'failed' (terminal rank 4); otherwise 'initiated'.
    Never raises.
    """
    db = _get_supabase()
    if db is None:
        return {"status": "not_configured"}
    try:
        failed = error is not None and call_sid is None
        row = {
            "activation_id": activation_id,
            "level": level,
            "contact_name": contact_name,
            "to_number": to_number,
            "call_sid": call_sid,
            "status": "failed" if failed else "initiated",
            "status_rank": 4 if failed else 1,
            "placed_at": _now_iso(),
            "error": error,
            "ack_token": ack_token,
        }
        result = db.table("triage_activation_calls").insert(row).execute()
        return {"status": "recorded", "id": result.data[0]["id"] if result.data else None}
    except Exception as e:
        print(f"[activations_db] record_call failed: {e}")
        return {"status": "error", "reason": str(e)}


def link_session_to_patient(full_session_id: str, patient_id: str) -> dict:
    """
    When staff link a health card to a session, also attach the patient to
    that session's activations, so the audit record follows the patient.
    Never raises.
    """
    db = _get_supabase()
    if db is None:
        return {"status": "not_configured"}
    try:
        result = (
            db.table("triage_activations")
            .update({"patient_id": patient_id, "updated_at": _now_iso()})
            .eq("session_id", full_session_id)
            .execute()
        )
        return {"status": "linked", "rows_updated": len(result.data) if result.data else 0}
    except Exception as e:
        print(f"[activations_db] link_session_to_patient failed: {e}")
        return {"status": "error", "reason": str(e)}
