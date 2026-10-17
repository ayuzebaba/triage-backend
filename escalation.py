"""
BRISK Escalation Engine (closed-loop emergency response, step 5)
---------------------------------------------------------------------------
If nobody presses 1 on the first call, call the next contact. If nobody
acknowledges at the last level, mark the emergency 'exhausted' so staff see it
flagged (report page now, Activations tab in step 7).

How it works
- emergency_call.py saves each activation with a safety 'next_action_at' and,
  once the level-1 call is placed, moves it to  now + ack window + pause.
- A background thread wakes every few seconds and looks for activations that
  are still 'active' and due. It CLAIMS one with a conditional database update
  (so two workers can never both act on the same emergency), re-checks it is
  still unacknowledged, then calls the next contact or marks it exhausted.
- Level 1 is always the CLINICAL_CONTACT_NUMBER Railway variable (unchanged).
  Levels 2, 3, ... come from the table triage_escalation_contacts (active rows).
  The table's level-1 row, if present, only supplies the timing for level 1.

Safety rules
- Never raises out of the thread. Any problem is printed and retried on the next
  wake-up (a claim lease expires after 60 seconds).
- At-least-once: if the server dies right after placing a call but before saving
  it, the same level may be called again. A duplicate call is better than a
  missed one.
- Acknowledged (or closed) activations are never touched.
- Kill switch: Railway variable ENABLE_ESCALATION = "false".
- The thread's regular database reads also keep the Supabase free project from
  pausing from inactivity while the backend is running.
"""

import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from urllib.parse import quote

try:
    from activations_db import _get_supabase, add_log, record_call
except Exception as _e:  # never let this stop the app
    print(f"[escalation] activations_db unavailable, escalation disabled: {_e}")

    def _get_supabase():
        return None

    def add_log(*args, **kwargs):
        return {"status": "not_configured"}

    def record_call(*args, **kwargs):
        return {"status": "not_configured"}

TICK_SECONDS = 5
LEASE_SECONDS = 60
DEFAULT_ACK_WINDOW = 45
DEFAULT_PAUSE = 20
SAFETY_DELAY_SECONDS = 120   # next_action_at set when the activation is created
FAILED_CALL_RETRY_SECONDS = 5  # move on quickly when Twilio refused a call
BATCH = 5

_started = False
_last_error = {"text": None, "at": 0.0}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def enabled() -> bool:
    return os.environ.get("ENABLE_ESCALATION", "true").lower() != "false"


def initial_safety_seconds() -> Optional[int]:
    """Used by emergency_call.py when it creates an activation."""
    return SAFETY_DELAY_SECONDS if enabled() else None


def _log_error(prefix: str, e: Exception):
    """Print repeating errors at most once a minute so the logs stay readable."""
    text = f"{prefix}: {e}"
    t = time.time()
    if text != _last_error["text"] or t - _last_error["at"] > 60:
        print(f"[escalation] {text}")
        _last_error["text"], _last_error["at"] = text, t


# ── contacts ───────────────────────────────────────────────────────────────

def load_contacts(db) -> Dict[int, dict]:
    """Active rows from triage_escalation_contacts, keyed by level. {} on any problem."""
    try:
        res = (
            db.table("triage_escalation_contacts")
            .select("level,name,phone_e164,ack_window_seconds,pause_after_seconds")
            .eq("active", True)
            .order("level")
            .execute()
        )
        return {int(r["level"]): r for r in (res.data or [])}
    except Exception as e:
        _log_error("could not read contacts", e)
        return {}


def _timing(contacts: Dict[int, dict], level: int):
    c = contacts.get(level) or {}
    return (c.get("ack_window_seconds") or DEFAULT_ACK_WINDOW,
            c.get("pause_after_seconds") if c.get("pause_after_seconds") is not None else DEFAULT_PAUSE)


# ── scheduling (called by emergency_call.py after the level-1 call) ────────

def schedule_after_call(activation_id: str, level: int, placed_ok: bool = True) -> dict:
    """Sets when this activation should next be looked at. Never raises."""
    try:
        if not enabled():
            return {"status": "disabled"}
        db = _get_supabase()
        if db is None:
            return {"status": "not_configured"}
        if placed_ok:
            window, pause = _timing(load_contacts(db), level)
            delay = window + pause
        else:
            delay = FAILED_CALL_RETRY_SECONDS
        (
            db.table("triage_activations")
            .update({"next_action_at": _ts(_now() + timedelta(seconds=delay)), "claimed_until": None})
            .eq("id", activation_id)
            .eq("status", "active")
            .execute()
        )
        return {"status": "scheduled", "delay_seconds": delay}
    except Exception as e:
        print(f"[escalation] schedule_after_call failed: {e}")
        return {"status": "error"}


# ── the engine ─────────────────────────────────────────────────────────────

def _claim(db, activation_id: str, now: datetime) -> bool:
    """Atomic: succeeds for exactly one caller while the row is due and unclaimed."""
    res = (
        db.table("triage_activations")
        .update({"claimed_until": _ts(now + timedelta(seconds=LEASE_SECONDS))})
        .eq("id", activation_id)
        .eq("status", "active")
        .lte("next_action_at", _ts(now))
        .or_(f"claimed_until.is.null,claimed_until.lt.{_ts(now)}")
        .execute()
    )
    return bool(res.data)


def _mark_exhausted(db, act: dict, now: datetime):
    res = (
        db.table("triage_activations")
        .update({"status": "exhausted", "exhausted_at": _ts(now), "next_action_at": None,
                 "claimed_until": None, "updated_at": _ts(now)})
        .eq("id", act["id"])
        .eq("status", "active")
        .execute()
    )
    if res.data:
        add_log(act["id"], "exhausted", {"levels_tried": act.get("current_level")})
        print(f"[escalation] activation {str(act['id'])[:8]} exhausted: nobody acknowledged")


def _escalate_one(db, activation_id: str, now: datetime):
    res = (
        db.table("triage_activations")
        .select("id,status,current_level,severity,symptom,spoken_location")
        .eq("id", activation_id)
        .limit(1)
        .execute()
    )
    act = res.data[0] if res.data else None
    if not act or act.get("status") != "active":
        return  # acknowledged or closed in the meantime: nothing to do

    contacts = load_contacts(db)
    current = int(act.get("current_level") or 1)
    next_levels = sorted(l for l in contacts if l > current)
    if not next_levels:
        _mark_exhausted(db, act, now)
        return

    level = next_levels[0]
    contact = contacts[level]

    from emergency_call import _place_clinical_contact_call  # lazy: reads Twilio settings
    token = secrets.token_urlsafe(16)
    result = _place_clinical_contact_call(
        act.get("severity") or 10,
        quote(str(act.get("symptom") or "unknown symptom")),
        quote(str(act.get("spoken_location") or "location unavailable")),
        token,
        to_number=contact["phone_e164"],
        level=level,
    )
    placed = result.get("status") == "placed"

    record_call(
        activation_id,
        to_number=contact["phone_e164"],
        level=level,
        contact_name=contact.get("name"),
        call_sid=result.get("call_sid"),
        error=None if placed else result.get("reason"),
        ack_token=token if placed else None,
    )
    add_log(activation_id, "escalated" if placed else "escalation_call_failed",
            {"level": level, "contact": contact.get("name"), "result": result})

    window, pause = _timing(contacts, level)
    delay = (window + pause) if placed else FAILED_CALL_RETRY_SECONDS
    (
        db.table("triage_activations")
        .update({"current_level": level, "next_action_at": _ts(_now() + timedelta(seconds=delay)),
                 "claimed_until": None, "updated_at": _ts(_now())})
        .eq("id", activation_id)
        .eq("status", "active")
        .execute()
    )
    print(f"[escalation] activation {str(activation_id)[:8]} -> level {level} ({'placed' if placed else 'FAILED'})")


def tick() -> int:
    """One pass. Returns how many activations were processed. Never raises."""
    try:
        db = _get_supabase()
        if db is None:
            return 0
        now = _now()
        due = (
            db.table("triage_activations")
            .select("id")
            .eq("status", "active")
            .lte("next_action_at", _ts(now))
            .limit(BATCH)
            .execute()
        ).data or []
        done = 0
        for row in due:
            try:
                if not _claim(db, row["id"], now):
                    continue  # another worker has it, or it is not due after all
                _escalate_one(db, row["id"], now)
                done += 1
            except Exception as e:
                _log_error(f"activation {str(row.get('id'))[:8]} failed (will retry)", e)
        return done
    except Exception as e:
        _log_error("tick failed", e)
        return 0


def _loop():
    while True:
        tick()
        time.sleep(TICK_SECONDS)


def start_engine() -> bool:
    """Starts the background thread once. Safe to call more than once."""
    global _started
    if _started:
        return False
    if not enabled():
        print("[escalation] disabled by ENABLE_ESCALATION=false")
        return False
    _started = True
    threading.Thread(target=_loop, name="brisk-escalation", daemon=True).start()
    print(f"[escalation] engine started (checks every {TICK_SECONDS}s)")
    return True
