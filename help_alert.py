"""
BRISK Help Alert (Release A: bystander alert; isolated module)
---------------------------------------------------------------------------
Lets someone with NO login tell us what they see and have a clinician phoned,
reusing the existing emergency call, escalation and press-1 flow.

Endpoints
  GET  /help-observations   active "what do you see" buttons (never raises)
  POST /help-alert          send an alert (codes, note, optional callback number)

Rules
- Kill switch: Railway variable ENABLE_HELP_ALERT must be "true" (default OFF).
- The SERVER decides severity from the button codes (highest wins); the page
  only sends codes.
- The callback number is stored on the case (triage_activations) only if the
  person ticked consent. It is never put in a URL; the call script looks it up
  with callback_speech(ack_token) when the receiver answers.
- Test alerts: send test_code equal to the Railway variable HELP_ALERT_TEST_CODE.
  They are tagged is_test and the symptom starts with "TEST:".
- Never raises out of an endpoint for a database problem; falls back to a
  built-in button list so an alert can still go out.
- Does not touch the patient path.
"""

import math
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

try:
    from activations_db import _get_supabase, add_log
except Exception as _e:  # never let this stop the app
    print(f"[help_alert] activations_db unavailable, help alert disabled: {_e}")

    def _get_supabase():
        return None

    def add_log(*args, **kwargs):
        return {"status": "not_configured"}

router = APIRouter()

NOTE_MAX = 300
LOCATION_MAX = 200

# Used only if the table cannot be read. Same codes as the seed SQL.
FALLBACK_OBSERVATIONS = {
    "unresponsive": ("Not responding or unconscious", 10, True, True),
    "not_breathing": ("Not breathing normally", 10, True, True),
    "choking": ("Choking", 10, True, True),
    "heavy_bleeding": ("Heavy bleeding that won't stop", 10, True, True),
    "seizure": ("Seizure or shaking", 9, True, True),
    "collapsed": ("Collapsed or fainted", 9, True, True),
    "chest_pain": ("Holding chest, in pain", 9, True, True),
    "stroke_signs": ("Face drooping, slurred speech, or one side weak", 9, True, True),
    "crash_injury": ("Crash, serious fall or injury", 9, True, True),
    "awake_talking": ("Awake and talking, can answer questions", 0, False, False),
    "other": ("Other", 9, False, True),
}

DEFAULT_TEMPLATE = "Caller's number is {number}. I repeat, {number}."
NO_NUMBER_TEXT = "No callback number was given."


def enabled() -> bool:
    return os.environ.get("ENABLE_HELP_ALERT", "").lower() == "true"


# ── settings ───────────────────────────────────────────────────────────────

def _setting(db, key: str, default):
    try:
        res = db.table("app_settings").select("value").eq("key", key).limit(1).execute()
        if res.data and res.data[0].get("value") not in (None, ""):
            return res.data[0]["value"]
    except Exception as e:
        print(f"[help_alert] setting {key} unreadable: {e}")
    return default


def _int_setting(db, key: str, default: int) -> int:
    try:
        return int(_setting(db, key, default))
    except Exception:
        return default


# ── observations ───────────────────────────────────────────────────────────

def load_observations(db) -> Dict[str, dict]:
    """code -> {label, severity, goes_to_911, auto_fire}. Built-in list on any problem."""
    try:
        if db is not None:
            res = (db.table("triage_observations")
                   .select("code,label,grp,severity,goes_to_911,auto_fire,sort_order")
                   .eq("active", True).order("sort_order").execute())
            if res.data:
                return {r["code"]: r for r in res.data}
    except Exception as e:
        print(f"[help_alert] observations unreadable, using built-in list: {e}")
    return {c: {"code": c, "label": v[0], "severity": v[1], "goes_to_911": v[2], "auto_fire": v[3]}
            for c, v in FALLBACK_OBSERVATIONS.items()}


@router.get("/help-observations")
def help_observations():
    try:
        obs = load_observations(_get_supabase())
        return {"enabled": enabled(),
                "observations": [{"code": o["code"], "label": o["label"], "grp": o.get("grp", "emergency")}
                                 for o in obs.values()]}
    except Exception as e:
        print(f"[help_alert] /help-observations failed: {e}")
        return {"enabled": False, "observations": []}


# ── helpers ────────────────────────────────────────────────────────────────

def normalize_phone(raw: Optional[str]) -> Optional[str]:
    """E.164 or None. Accepts 10-digit and 1+10-digit North American numbers."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+"):
        return "+" + digits if 8 <= len(digits) <= 15 else None
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return None


def spoken_number(e164: str) -> str:
    """'+13065551234' -> '3 0 6, 5 5 5, 1 2 3 4' so the voice reads digits one by one."""
    d = re.sub(r"\D", "", e164)
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    sp = lambda s: " ".join(s)
    if len(d) == 10:
        return f"{sp(d[:3])}, {sp(d[3:6])}, {sp(d[6:])}"
    return sp(d)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


_rate_lock = threading.Lock()
_rate: Dict[str, List[float]] = {}


def _rate_limited(ip: str, limit: int) -> bool:
    now = time.time()
    with _rate_lock:
        hits = [t for t in _rate.get(ip, []) if now - t < 3600]
        if len(hits) >= limit:
            _rate[ip] = hits
            return True
        hits.append(now)
        _rate[ip] = hits
        return False


def _distance_m(lat1, lng1, lat2, lng2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _find_open_nearby(db, lat, lng, window_min: int, dist_m: int) -> Optional[dict]:
    """An open (still 'active') alert created recently within dist_m, else None. Never raises."""
    if lat is None or lng is None:
        return None
    try:
        since = (datetime.now(timezone.utc) - timedelta(minutes=window_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = (db.table("triage_activations").select("id,latitude,longitude,session_id")
                .eq("status", "active").gte("created_at", since).execute()).data or []
        for r in rows:
            if r.get("latitude") is None or r.get("longitude") is None:
                continue
            if _distance_m(lat, lng, float(r["latitude"]), float(r["longitude"])) <= dist_m:
                return r
    except Exception as e:
        print(f"[help_alert] duplicate check failed (alert goes ahead): {e}")
    return None


# ── the alert ──────────────────────────────────────────────────────────────

class HelpAlertRequest(BaseModel):
    codes: List[str] = []
    note: Optional[str] = None
    callback_number: Optional[str] = None
    consent: bool = False
    location: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    session_id: Optional[str] = None
    test_code: Optional[str] = None


def _code(session_id: str) -> str:
    return session_id[-6:].upper()


@router.post("/help-alert")
def help_alert(payload: HelpAlertRequest, request: Request):
    # The page ALWAYS keeps its own 911 button, so every non-alert answer says show_911.
    if not enabled():
        return {"status": "unavailable", "show_911": True}
    try:
        db = _get_supabase()
        limit = _int_setting(db, "alert_limit_per_hour", 5) if db else 5
        if _rate_limited(_client_ip(request), limit):
            return {"status": "rate_limited", "show_911": True}

        obs = load_observations(db)
        codes = [c for c in dict.fromkeys(payload.codes or []) if c in obs][:12]
        note = (payload.note or "").strip()[:NOTE_MAX] or None
        if not codes and not note:
            return {"status": "nothing_to_send", "show_911": True}

        chosen = [obs[c] for c in codes]
        if codes and all(o.get("auto_fire") is False for o in chosen) and not note:
            return {"status": "no_alert", "show_911": False}   # e.g. only "awake and talking"
        if not codes and note:
            chosen = [obs["other"]] if "other" in obs else []
        severity = max([int(o.get("severity") or 0) for o in chosen] or [9])
        labels = [o["label"] for o in chosen]

        number = normalize_phone(payload.callback_number) if payload.consent else None
        number_ignored = bool(payload.callback_number) and number is None

        is_test = bool(os.environ.get("HELP_ALERT_TEST_CODE")) and payload.test_code == os.environ.get("HELP_ALERT_TEST_CODE")
        session_id = (payload.session_id or "").strip()[:64] or f"help-{secrets.token_hex(6)}"

        location = (payload.location or "").strip()[:LOCATION_MAX]
        if not location and payload.lat is not None and payload.lng is not None:
            try:
                from reverse_geocode import reverse_geocode
                location = reverse_geocode(payload.lat, payload.lng) or ""
            except Exception as e:
                print(f"[help_alert] reverse geocode failed: {e}")
        if not location:
            location = "location unavailable"

        if db is not None:
            near = _find_open_nearby(db, payload.lat, payload.lng,
                                     _int_setting(db, "dup_alert_window_minutes", 10),
                                     _int_setting(db, "dup_alert_distance_m", 300))
            if near:
                add_log(near["id"], "bystander_duplicate", {"codes": codes})
                return {"status": "duplicate", "show_911": True, "code": _code(str(near.get("session_id") or session_id))}

        symptom = ("TEST: " if is_test else "") + "Bystander report: " + (", ".join(labels) if labels else "other")
        extra = {"reported_via": "bystander", "observation_codes": ",".join(codes) or None, "note": note,
                 "callback_number": number, "callback_unverified": True, "is_test": is_test}

        from emergency_call import trigger_emergency_call   # lazy: reads Twilio settings
        result = trigger_emergency_call(session_id=session_id, severity=severity, symptom=symptom,
                                        location=location, body_system="bystander",
                                        lat=payload.lat, lng=payload.lng, extra=extra)
        # Only say "alerted" if a call really went out (or this same report was already alerted).
        placed = result.get("status") == "call_placed"
        repeat = result.get("status") == "skipped" and "already placed" in str(result.get("reason", ""))
        if not (placed or repeat):
            print(f"[help_alert] no call placed: {result}")
            return {"status": "not_called", "show_911": True}
        return {"status": "alerted", "show_911": True, "code": _code(session_id),
                "number_ignored": number_ignored, "call": result.get("status")}
    except Exception as e:
        print(f"[help_alert] /help-alert failed: {e}")
        return {"status": "error", "show_911": True}


# ── used by the call script (main.py /emergency-call-twiml) ────────────────

def callback_speech(ack_token: Optional[str]) -> str:
    """Spoken callback sentence for the call tied to ack_token, '' for non-bystander cases. Never raises."""
    try:
        if not ack_token:
            return ""
        db = _get_supabase()
        if db is None:
            return ""
        call = db.table("triage_activation_calls").select("activation_id").eq("ack_token", ack_token).limit(1).execute()
        if not call.data:
            return ""
        act = (db.table("triage_activations").select("reported_via,callback_number")
               .eq("id", call.data[0]["activation_id"]).limit(1).execute())
        if not act.data or act.data[0].get("reported_via") != "bystander":
            return ""
        number = act.data[0].get("callback_number")
        if not number:
            return NO_NUMBER_TEXT
        template = str(_setting(db, "voice_template", DEFAULT_TEMPLATE))
        return template.replace("{number}", spoken_number(number))
    except Exception as e:
        print(f"[help_alert] callback_speech failed: {e}")
        return ""