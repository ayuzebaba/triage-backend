"""
BRISK Staff Activations API (closed-loop emergency response, step 7)
---------------------------------------------------------------------------
For clinic staff: see emergencies that need attention, take ownership, and
record the outcome.

  GET  /staff/activations?view=open|closed|all   list (needs-attention first)
  GET  /staff/activations/{id}                    one activation + calls + timeline
  POST /staff/activations/{id}/acknowledge        "I'm handling this"  (staff name required)
  POST /staff/activations/{id}/close              record the outcome   (staff name + outcome required)

Header on every request:  X-Staff-Access-Code: <STAFF_ACCESS_CODE>

Rules
- Acknowledged is NOT the same as helped: a person has taken ownership. Closing
  records what actually happened (disposition) and who recorded it.
- Closing stops escalation: a closed activation is never called again.
- Every action is logged (triage_activation_log) with the staff name.
- Patient identity is never returned: only a yes/no "health card linked" flag,
  the short session code staff already use on the Staff page, and the spoken
  location (staff need it to act).
- Never raises out of an endpoint: a database problem returns {"status": "error"}.
- Own lazy Supabase client via activations_db, same as the other modules.
"""

import os
import hmac
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

try:
    from activations_db import _get_supabase, add_log
except Exception as _e:  # never let this stop the app
    print(f"[staff_activations] activations_db unavailable, staff tab disabled: {_e}")

    def _get_supabase():
        return None

    def add_log(*args, **kwargs):
        return {"status": "not_configured"}

router = APIRouter()

DISPOSITIONS = {
    "patient_contacted": "Patient contacted",
    "ems_dispatched": "EMS dispatched",
    "referred_to_er": "Referred to ER",
    "false_alarm": "False alarm",
    "unable_to_reach": "Unable to reach patient",
    "other": "Other",
}
OPEN_STATUSES = ["active", "acknowledged", "exhausted"]
PRIORITY = {"exhausted": 0, "active": 1, "acknowledged": 2, "closed": 3}
LIST_COLS = ("id,session_id,triggered_at,symptom,severity,body_system,status,current_level,"
             "spoken_location,patient_id,acknowledged_at,acknowledged_via,acknowledged_by,"
             "exhausted_at,closed_at,disposition,disposition_by,notes")
CALL_COLS = "activation_id,level,contact_name,status,placed_at,answered_at,ended_at,ack_at"
SAFE_DETAIL_KEYS = ("level", "status", "contact", "via", "by", "duration_seconds", "disposition", "levels_tried")
PAGE = 1000


def _check_staff_access(code: Optional[str]):
    expected = os.environ.get("STAFF_ACCESS_CODE", "")
    if not expected or not code or not hmac.compare_digest(code.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Invalid staff access code")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask_who(value: Optional[str]) -> Optional[str]:
    """Level-1 acknowledgements store the phone number; show only the last 4 digits."""
    if value and re.fullmatch(r"\+?\d{7,15}", value):
        return f"phone ending {value[-4:]}"
    return value


def _clean_activation(a: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": a.get("id"),
        "session_code": (a.get("session_id") or "")[:8].upper(),
        "triggered_at": a.get("triggered_at"),
        "symptom": a.get("symptom"),
        "severity": a.get("severity"),
        "body_system": a.get("body_system"),
        "status": a.get("status"),
        "current_level": a.get("current_level"),
        "location": a.get("spoken_location"),
        "health_card_linked": bool(a.get("patient_id")),
        "acknowledged_at": a.get("acknowledged_at"),
        "acknowledged_via": a.get("acknowledged_via"),
        "acknowledged_by": _mask_who(a.get("acknowledged_by")),
        "exhausted_at": a.get("exhausted_at"),
        "closed_at": a.get("closed_at"),
        "disposition": a.get("disposition"),
        "disposition_label": DISPOSITIONS.get(a.get("disposition") or ""),
        "disposition_by": a.get("disposition_by"),
        "notes": a.get("notes"),
    }


def _clean_call(c: Dict[str, Any]) -> Dict[str, Any]:
    return {k: c.get(k) for k in ("activation_id", "level", "contact_name", "status",
                                  "placed_at", "answered_at", "ended_at", "ack_at")}


def _fetch_all(build_query) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    start = 0
    while True:
        batch = build_query().range(start, start + PAGE - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        start += PAGE


def _valid_id(activation_id: str) -> str:
    try:
        return str(uuid.UUID(activation_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")


def _clean_name(name: str) -> str:
    n = (name or "").strip()
    if len(n) < 2 or len(n) > 60:
        raise HTTPException(status_code=400, detail="Please enter your name (2 to 60 characters)")
    return n


# ── list ───────────────────────────────────────────────────────────────────

@router.get("/staff/activations")
def list_activations(
    view: str = Query("open"),
    limit: int = Query(100, ge=1, le=300),
    x_staff_access_code: Optional[str] = Header(default=None),
):
    _check_staff_access(x_staff_access_code)
    if view not in ("open", "closed", "all"):
        raise HTTPException(status_code=400, detail="view must be open, closed or all")
    db = _get_supabase()
    if db is None:
        return {"status": "not_configured"}
    try:
        def q():
            b = db.table("triage_activations").select(LIST_COLS)
            if view == "open":
                b = b.in_("status", OPEN_STATUSES)
            elif view == "closed":
                b = b.eq("status", "closed")
            return b.order("triggered_at", desc=True)

        rows = q().limit(limit).execute().data or []
        ids = [r["id"] for r in rows if r.get("id")]
        calls: List[Dict[str, Any]] = []
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            calls.extend(_fetch_all(
                lambda chunk=chunk: db.table("triage_activation_calls")
                .select(CALL_COLS).in_("activation_id", chunk).order("level")
            ))
        by_act: Dict[str, List[Dict[str, Any]]] = {}
        for c in calls:
            by_act.setdefault(c["activation_id"], []).append(_clean_call(c))

        items = []
        for r in rows:
            item = _clean_activation(r)
            item["calls"] = by_act.get(r["id"], [])
            items.append(item)
        # needs-attention first, newest first within each group (stable sort keeps newest-first order)
        items.sort(key=lambda it: PRIORITY.get(it["status"], 9))
        counts = {s: sum(1 for it in items if it["status"] == s) for s in PRIORITY}
        return {"status": "ok", "view": view, "counts": counts, "activations": items}
    except Exception as e:
        print(f"[staff_activations] list failed: {e}")
        return {"status": "error"}


# ── detail ─────────────────────────────────────────────────────────────────

@router.get("/staff/activations/{activation_id}")
def activation_detail(activation_id: str, x_staff_access_code: Optional[str] = Header(default=None)):
    _check_staff_access(x_staff_access_code)
    activation_id = _valid_id(activation_id)
    db = _get_supabase()
    if db is None:
        return {"status": "not_configured"}
    try:
        res = db.table("triage_activations").select(LIST_COLS).eq("id", activation_id).limit(1).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Not found")
        calls = (db.table("triage_activation_calls").select(CALL_COLS)
                 .eq("activation_id", activation_id).order("level").execute().data or [])
        events = (db.table("triage_activation_log").select("event_type,detail,created_at")
                  .eq("activation_id", activation_id).order("created_at").execute().data or [])
        timeline = []
        for ev in events:
            detail = ev.get("detail") or {}
            timeline.append({
                "event": ev.get("event_type"),
                "at": ev.get("created_at"),
                "detail": {k: detail[k] for k in SAFE_DETAIL_KEYS if k in detail},
            })
        return {"status": "ok", "activation": _clean_activation(res.data[0]),
                "calls": [_clean_call(c) for c in calls], "timeline": timeline}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[staff_activations] detail failed: {e}")
        return {"status": "error"}


# ── actions ────────────────────────────────────────────────────────────────

class AcknowledgeBody(BaseModel):
    staff_name: str


class CloseBody(BaseModel):
    staff_name: str
    disposition: str
    notes: Optional[str] = None


def _current_status(db, activation_id: str) -> Optional[str]:
    res = db.table("triage_activations").select("status").eq("id", activation_id).limit(1).execute()
    return res.data[0]["status"] if res.data else None


@router.post("/staff/activations/{activation_id}/acknowledge")
def staff_acknowledge(activation_id: str, body: AcknowledgeBody,
                      x_staff_access_code: Optional[str] = Header(default=None)):
    _check_staff_access(x_staff_access_code)
    activation_id = _valid_id(activation_id)
    name = _clean_name(body.staff_name)
    db = _get_supabase()
    if db is None:
        return {"status": "not_configured"}
    try:
        now = _now_iso()
        res = (
            db.table("triage_activations")
            .update({"status": "acknowledged", "acknowledged_at": now, "acknowledged_via": "staff",
                     "acknowledged_by": name, "next_action_at": None, "claimed_until": None,
                     "updated_at": now})
            .eq("id", activation_id)
            .in_("status", ["active", "exhausted"])
            .execute()
        )
        if res.data:
            add_log(activation_id, "acknowledged", {"via": "staff", "by": name})
            return {"status": "ok"}
        current = _current_status(db, activation_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Not found")
        return {"status": "unchanged", "current": current}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[staff_activations] acknowledge failed: {e}")
        return {"status": "error"}


@router.post("/staff/activations/{activation_id}/close")
def staff_close(activation_id: str, body: CloseBody,
                x_staff_access_code: Optional[str] = Header(default=None)):
    _check_staff_access(x_staff_access_code)
    activation_id = _valid_id(activation_id)
    name = _clean_name(body.staff_name)
    if body.disposition not in DISPOSITIONS:
        raise HTTPException(status_code=400, detail="Please choose an outcome")
    notes = (body.notes or "").strip() or None
    if notes and len(notes) > 1000:
        raise HTTPException(status_code=400, detail="Notes are too long (1000 characters maximum)")
    db = _get_supabase()
    if db is None:
        return {"status": "not_configured"}
    try:
        now = _now_iso()
        res = (
            db.table("triage_activations")
            .update({"status": "closed", "closed_at": now, "disposition": body.disposition,
                     "disposition_by": name, "notes": notes, "next_action_at": None,
                     "claimed_until": None, "updated_at": now})
            .eq("id", activation_id)
            .in_("status", OPEN_STATUSES)
            .execute()
        )
        if res.data:
            add_log(activation_id, "closed", {"by": name, "disposition": body.disposition})
            return {"status": "ok"}
        current = _current_status(db, activation_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Not found")
        return {"status": "unchanged", "current": current}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[staff_activations] close failed: {e}")
        return {"status": "error"}
