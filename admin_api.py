"""
BRISK Admin API (Release 0a, Phase 1: settings)
---------------------------------------------------------------------------
Lets the admin view and change app settings (phone numbers, message wording,
alert limits) without a code change or redeploy, and lets patient screens read
the PUBLIC settings.

Endpoints
  GET  /public-settings               no sign-in; only rows marked is_public
  GET  /admin/check                   verifies the admin code
  GET  /admin/settings                all settings (admin code)
  PUT  /admin/settings/{key}          change one existing setting (admin code)
  GET  /admin/settings-history        recent changes (admin code)

Sign-in: header  X-Admin-Access-Code  must equal the Railway variable
ADMIN_ACCESS_CODE (a DIFFERENT code from STAFF_ACCESS_CODE). If the variable is
not set, every admin endpoint refuses. Wrong codes are rate limited.

Safety rules
- Isolated module: if it fails to load, the rest of the app still starts.
- Kill switch: Railway variable ENABLE_ADMIN = "false".
- Only keys listed in SPECS can be changed, each with its own validation.
  Settings cannot hold secrets; secrets and kill switches stay in Railway.
- Every change writes a row to app_settings_history (old value, new value).
- /public-settings never raises: on any problem it returns empty settings so
  screens use their safe defaults (911 / 811), never a personal number.
- This module does not touch calls, escalation, or triage logic.
"""

import os
import re
import time
import hmac
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

try:
    from activations_db import _get_supabase
except Exception as _e:  # never let this stop the app
    print(f"[admin_api] activations_db unavailable, admin disabled: {_e}")

    def _get_supabase():
        return None

router = APIRouter()

TABLE = "app_settings"
HISTORY = "app_settings_history"
COLS = "key,value,description,is_public,updated_by,updated_at"
ALLOWED_PLACEHOLDERS = {"number", "symptom", "location", "site", "time"}
PUBLIC_CACHE_SECONDS = 60


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
class ValidationError(ValueError):
    pass


def _clean_text(value: str, max_len: int) -> str:
    v = re.sub(r"[\x00-\x1f\x7f]", " ", value or "").strip()
    v = re.sub(r"\s+", " ", v)
    if len(v) > max_len:
        raise ValidationError(f"Too long (maximum {max_len} characters).")
    return v


def v_phone_or_empty(value: str) -> str:
    """Empty (use 911/811 only), a short code like 811/988, or a phone number."""
    raw = (value or "").strip()
    if raw == "":
        return ""
    digits_plus = re.sub(r"[\s\-\.\(\)]", "", raw)
    if not re.fullmatch(r"\+?[0-9]{3,15}", digits_plus):
        raise ValidationError("Use digits only, for example +13065551234 or 988.")
    if digits_plus.startswith("+"):
        return digits_plus
    if len(digits_plus) == 10:
        return "+1" + digits_plus
    if len(digits_plus) == 11 and digits_plus.startswith("1"):
        return "+" + digits_plus
    if len(digits_plus) <= 4:   # short codes such as 811, 988
        return digits_plus
    raise ValidationError("Enter a 10-digit number, a number starting with +, or a short code.")


def make_text(max_len: int, required=(), allowed_placeholders=ALLOWED_PLACEHOLDERS, allow_empty=False):
    def check(value: str) -> str:
        v = _clean_text(value, max_len)
        if not v and not allow_empty:
            raise ValidationError("This cannot be empty.")
        found = set(re.findall(r"\{([^{}]*)\}", v))
        bad = found - set(allowed_placeholders)
        if bad:
            raise ValidationError("Unknown placeholder: {" + sorted(bad)[0] + "}. Allowed: "
                                  + ", ".join("{" + p + "}" for p in sorted(allowed_placeholders)))
        stripped = re.sub(r"\{[^{}]*\}", "", v)
        if "{" in stripped or "}" in stripped:
            raise ValidationError("Unmatched curly brace.")
        for req in required:
            if "{" + req + "}" not in v:
                raise ValidationError("Must include {" + req + "}.")
        return v
    return check


def make_int(lo: int, hi: int):
    def check(value: str) -> str:
        v = (value or "").strip()
        if not re.fullmatch(r"[0-9]{1,6}", v):
            raise ValidationError(f"Enter a whole number between {lo} and {hi}.")
        n = int(v)
        if n < lo or n > hi:
            raise ValidationError(f"Enter a whole number between {lo} and {hi}.")
        return str(n)
    return check


# Only these keys can be changed. Each maps to its validator.
SPECS = {
    "crisis_line_number":           v_phone_or_empty,
    "callback_consent_text":        make_text(300, allowed_placeholders=set()),
    "voice_template":               make_text(300, required=("number",)),
    "text_template":                make_text(300, required=("number",)),
    "voicemail_template":           make_text(300, required=("number",)),
    "queue_alert_template":         make_text(300),
    "dup_alert_window_minutes":     make_int(1, 120),
    "dup_alert_distance_m":         make_int(50, 5000),
    "alert_limit_per_hour":         make_int(1, 100),
    "min_minutes_between_contacts": make_int(1, 240),
}


def validate_setting(key: str, value: Any) -> str:
    if key not in SPECS:
        raise ValidationError("Unknown setting.")
    if not isinstance(value, str):
        raise ValidationError("Value must be text.")
    return SPECS[key](value)


# ---------------------------------------------------------------------------
# Sign-in and rate limiting (in memory; resets when the server restarts)
# ---------------------------------------------------------------------------
_fail_lock = threading.Lock()
_fails_by_ip: Dict[str, list] = {}
_fails_all: list = []
FAIL_WINDOW = 15 * 60
FAIL_LIMIT_PER_IP = 8
FAIL_LIMIT_ALL = 40


def _enabled() -> bool:
    return os.environ.get("ENABLE_ADMIN", "true").lower() != "false"


def _client_ip(request: Optional[Request]) -> str:
    if request is None:
        return "unknown"
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _prune(lst: list, now: float) -> list:
    return [t for t in lst if now - t < FAIL_WINDOW]


def _too_many_fails(ip: str) -> bool:
    now = time.time()
    with _fail_lock:
        _fails_by_ip[ip] = _prune(_fails_by_ip.get(ip, []), now)
        _fails_all[:] = _prune(_fails_all, now)
        return len(_fails_by_ip[ip]) >= FAIL_LIMIT_PER_IP or len(_fails_all) >= FAIL_LIMIT_ALL


def _record_fail(ip: str) -> None:
    now = time.time()
    with _fail_lock:
        _fails_by_ip.setdefault(ip, []).append(now)
        _fails_all.append(now)


def _require_admin(request: Optional[Request], code: Optional[str]) -> None:
    if not _enabled():
        raise HTTPException(status_code=503, detail="Admin is switched off.")
    expected = os.environ.get("ADMIN_ACCESS_CODE", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin is not configured.")
    ip = _client_ip(request)
    if _too_many_fails(ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    if not code or not hmac.compare_digest(code.encode(), expected.encode()):
        _record_fail(ip)
        raise HTTPException(status_code=403, detail="Invalid admin code.")


# ---------------------------------------------------------------------------
# Public settings (cached)
# ---------------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache: Dict[str, Any] = {"at": 0.0, "data": None}


def _clear_cache() -> None:
    with _cache_lock:
        _cache["at"] = 0.0
        _cache["data"] = None


def _load_public() -> Optional[Dict[str, str]]:
    db = _get_supabase()
    if db is None:
        return None
    res = db.table(TABLE).select("key,value").eq("is_public", True).execute()
    return {r["key"]: (r.get("value") or "") for r in (res.data or [])}


@router.get("/public-settings")
def public_settings():
    """Never raises. Empty settings tell screens to use their safe defaults."""
    try:
        now = time.time()
        with _cache_lock:
            if _cache["data"] is not None and now - _cache["at"] < PUBLIC_CACHE_SECONDS:
                data = _cache["data"]
            else:
                data = None
        if data is None:
            data = _load_public()
            if data is not None:
                with _cache_lock:
                    _cache["data"] = data
                    _cache["at"] = time.time()
        if data is None:
            return JSONResponse({"settings": {}, "source": "fallback"}, headers={"Cache-Control": "no-store"})
        return JSONResponse({"settings": data, "source": "database"},
                            headers={"Cache-Control": f"public, max-age={PUBLIC_CACHE_SECONDS // 2}"})
    except Exception as e:
        print(f"[admin_api] public settings failed, using fallback: {e}")
        return JSONResponse({"settings": {}, "source": "fallback"}, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------
class SettingBody(BaseModel):
    value: str


def _db_or_503():
    db = _get_supabase()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not configured.")
    return db


@router.get("/admin/check")
def admin_check(request: Request, x_admin_access_code: Optional[str] = Header(default=None)):
    _require_admin(request, x_admin_access_code)
    return {"ok": True}


@router.get("/admin/settings")
def admin_list_settings(request: Request, x_admin_access_code: Optional[str] = Header(default=None)):
    _require_admin(request, x_admin_access_code)
    db = _db_or_503()
    try:
        rows = db.table(TABLE).select(COLS).order("key").execute().data or []
    except Exception as e:
        print(f"[admin_api] list settings failed: {e}")
        raise HTTPException(status_code=500, detail="Could not load settings.")
    known = {r["key"] for r in rows}
    for r in rows:
        r["editable"] = r["key"] in SPECS
    missing = sorted(set(SPECS) - known)
    return {"settings": rows, "missing_keys": missing}


@router.put("/admin/settings/{key}")
def admin_update_setting(key: str, body: SettingBody, request: Request,
                         x_admin_access_code: Optional[str] = Header(default=None)):
    _require_admin(request, x_admin_access_code)
    try:
        new_value = validate_setting(key, body.value)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db = _db_or_503()
    try:
        cur = db.table(TABLE).select("key,value").eq("key", key).limit(1).execute().data or []
        if not cur:
            raise HTTPException(status_code=404, detail="Setting row not found. Run the settings SQL first.")
        old_value = cur[0].get("value") or ""
        if old_value == new_value:
            return {"ok": True, "changed": False, "value": new_value}
        now = datetime.now(timezone.utc).isoformat()
        db.table(TABLE).update({"value": new_value, "updated_by": "admin", "updated_at": now}).eq("key", key).execute()
        try:
            db.table(HISTORY).insert({"key": key, "old_value": old_value, "new_value": new_value,
                                      "changed_by": "admin", "changed_at": now}).execute()
        except Exception as e:  # the change is saved; report the history problem in the log
            print(f"[admin_api] history write failed for {key}: {e}")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[admin_api] update failed for {key}: {e}")
        raise HTTPException(status_code=500, detail="Could not save the setting.")
    _clear_cache()
    return {"ok": True, "changed": True, "value": new_value}


@router.get("/admin/settings-history")
def admin_history(request: Request, limit: int = Query(50, ge=1, le=200),
                  x_admin_access_code: Optional[str] = Header(default=None)):
    _require_admin(request, x_admin_access_code)
    db = _db_or_503()
    try:
        rows = (db.table(HISTORY).select("key,old_value,new_value,changed_by,changed_at")
                .order("changed_at", desc=True).limit(limit).execute().data or [])
    except Exception as e:
        print(f"[admin_api] history failed: {e}")
        raise HTTPException(status_code=500, detail="Could not load history.")
    return {"history": rows}