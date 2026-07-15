"""
BRISK Database Module
----------------------
Writes to triage_registration and triage_events in the shared
scholaria-mvp Supabase project, using the service_role key.

The service_role key is used deliberately, not the anon key:
- It's the only way the backend can write to these tables at all,
  since Row Level Security on both tables has zero permissive
  policies for anon/authenticated roles (see triage_schema.sql).
- This keeps the key itself, and everything it can touch (patient
  allergies, medications, health card numbers), entirely out of
  the browser — the frontend never talks to Supabase directly,
  only to this FastAPI backend.

Requires these environment variables (e.g. in Railway):
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY

IMPORTANT: these are read lazily (inside a function), NOT at module
load time. Reading them at the top of the file with os.environ[...]
would crash the entire app on import the moment main.py starts —
including the already-working Twilio 911 call and ER routing — if
these two variables aren't set in Railway yet. This exact bug was
caught before deploying (see conversation), so it's fixed defensively
here instead of just documented as a setup requirement.
"""

import os
from typing import Optional, Dict, Any
from supabase import create_client, Client

_supabase_client: Optional[Client] = None


def _get_supabase() -> Optional[Client]:
    """
    Lazily creates the Supabase client on first real use. Returns None
    (never raises) if SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY aren't set —
    callers check for None and return a clear error status instead of
    the whole app crashing on startup.
    """
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("[triage_db] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — triage_db features disabled")
        return None

    _supabase_client = create_client(url, key)
    return _supabase_client


def log_event(
    session_id: str,
    event_type: str,
    patient_id: Optional[str] = None,
    body_system: Optional[str] = None,
    symptom: Optional[str] = None,
    severity: Optional[int] = None,
    location_region: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    Insert one row into triage_events. Never raises — a logging
    failure must never break the patient's actual triage flow, so
    any error here is caught and returned as a status dict instead
    of propagating up and interrupting a 911 call, ER routing, etc.
    """
    db = _get_supabase()
    if db is None:
        return {"status": "not_configured", "reason": "Supabase env vars not set"}
    try:
        row = {
            "session_id": session_id,
            "event_type": event_type,
            "patient_id": patient_id,
            "body_system": body_system,
            "symptom": symptom,
            "severity": severity,
            "location_region": location_region,
            "metadata": metadata or {},
        }
        result = db.table("triage_events").insert(row).execute()
        return {"status": "logged", "id": result.data[0]["id"] if result.data else None}
    except Exception as e:
        # Logging is best-effort. A failed log write should never
        # block or crash the actual patient-facing flow.
        print(f"[triage_db] log_event failed: {e}")
        return {"status": "error", "reason": str(e)}


def create_registration(fields: Dict[str, Any]) -> dict:
    """
    Insert one row into triage_registration. All fields are optional
    per the requirements doc — only whatever the patient actually
    filled in gets passed here; missing fields default to NULL.
    """
    db = _get_supabase()
    if db is None:
        return {"status": "not_configured", "reason": "Supabase env vars not set"}
    try:
        result = db.table("triage_registration").insert(fields).execute()
        if not result.data:
            return {"status": "error", "reason": "insert returned no data"}
        return {"status": "created", "id": result.data[0]["id"]}
    except Exception as e:
        print(f"[triage_db] create_registration failed: {e}")
        return {"status": "error", "reason": str(e)}


def get_registration(patient_id: str) -> dict:
    """
    Fetch one patient's registration by id — used to look up their
    saved family_doctor_phone_number at the Below-5 routing step.
    """
    db = _get_supabase()
    if db is None:
        return {"status": "not_configured", "reason": "Supabase env vars not set"}
    try:
        result = db.table("triage_registration").select("*").eq("id", patient_id).limit(1).execute()
        if not result.data:
            return {"status": "not_found"}
        return {"status": "found", "data": result.data[0]}
    except Exception as e:
        print(f"[triage_db] get_registration failed: {e}")
        return {"status": "error", "reason": str(e)}


def find_or_create_by_health_card(health_card_number: str, extra_fields: Optional[Dict[str, Any]] = None) -> dict:
    """
    The real cross-device identity anchor. Given a health card number:
    - If a triage_registration already has it, return that existing row's id
      (so a patient logging in from a new device links to their same record,
      not a duplicate).
    - Otherwise, create a new triage_registration with it.

    This is what makes the health card + OTP login (and the nurse's
    QR-code linking) actually work as a real identity, rather than the
    localStorage-only approach this replaces.
    """
    db = _get_supabase()
    if db is None:
        return {"status": "not_configured", "reason": "Supabase env vars not set"}
    try:
        existing = (
            db.table("triage_registration")
            .select("id")
            .eq("sk_health_card_number", health_card_number)
            .limit(1)
            .execute()
        )
        if existing.data:
            return {"status": "found", "id": existing.data[0]["id"]}

        fields = {"sk_health_card_number": health_card_number}
        if extra_fields:
            fields.update({k: v for k, v in extra_fields.items() if v is not None})
        result = db.table("triage_registration").insert(fields).execute()
        if not result.data:
            return {"status": "error", "reason": "insert returned no data"}
        return {"status": "created", "id": result.data[0]["id"]}
    except Exception as e:
        print(f"[triage_db] find_or_create_by_health_card failed: {e}")
        return {"status": "error", "reason": str(e)}


def get_events_by_session_prefix(session_prefix: str) -> dict:
    """
    Staff-facing lookup: given the short code a patient shows/scans at
    the hospital (the first 8 characters of their session_id), find that
    session's already-logged events — symptoms, severity, timestamps —
    so the nurse can review what happened before linking a health card.

    Uses a prefix match since the QR encodes the full session_id, but the
    on-screen fallback code is deliberately shortened for manual entry.
    """
    db = _get_supabase()
    if db is None:
        return {"status": "not_configured", "reason": "Supabase env vars not set"}
    try:
        result = (
            db.table("triage_events")
            .select("*")
            .like("session_id", f"{session_prefix}%")
            .order("created_at", desc=False)
            .execute()
        )
        if not result.data:
            return {"status": "not_found"}
        return {"status": "found", "events": result.data, "full_session_id": result.data[0]["session_id"]}
    except Exception as e:
        print(f"[triage_db] get_events_by_session_prefix failed: {e}")
        return {"status": "error", "reason": str(e)}


def link_session_to_patient(full_session_id: str, patient_id: str) -> dict:
    """
    Retroactively attaches a patient_id to every triage_events row for a
    given session — called after the nurse enters a health card number
    for a patient who used the app anonymously, then showed up in person.
    """
    db = _get_supabase()
    if db is None:
        return {"status": "not_configured", "reason": "Supabase env vars not set"}
    try:
        result = (
            db.table("triage_events")
            .update({"patient_id": patient_id})
            .eq("session_id", full_session_id)
            .execute()
        )
        return {"status": "linked", "rows_updated": len(result.data) if result.data else 0}
    except Exception as e:
        print(f"[triage_db] link_session_to_patient failed: {e}")
        return {"status": "error", "reason": str(e)}