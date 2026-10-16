"""
BRISK Reports API (staff-facing, read-only)
---------------------------------------------------------------------------
GET /staff/reports/summary?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD
Header: X-Staff-Access-Code: <STAFF_ACCESS_CODE>

Returns TOTALS ONLY for emergency activations (severity 9-10) in the chosen
date range. No patient ids, names, coordinates or addresses ever leave this
module: only the columns listed in ACT_COLS / CALL_COLS are read.

Safety rules (same spirit as activations_db.py):
- Read-only. Nothing here writes to the database.
- Own lazy Supabase client; missing env vars or package never crash startup.
- Never raises out of the endpoint: a database problem returns
  {"status": "error"} so the page can show a message.
- Isolated: it shares no state with the emergency-call code path.

Dates are interpreted in Saskatchewan time (CST, UTC-6, no daylight saving).
"""

import os
import hmac
from datetime import datetime, date, timedelta, timezone
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Header, HTTPException, Query

router = APIRouter()

SK_TZ = timezone(timedelta(hours=-6))  # Saskatchewan: CST all year
MAX_DAYS = 366
PAGE = 1000

ACT_COLS = "id,triggered_at,symptom,body_system,severity,status,acknowledged_at"
CALL_COLS = "activation_id,level,status"

_client = None


def _get_supabase():
    global _client
    if _client is not None:
        return _client
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("[reports_api] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set -- reports disabled")
        return None
    try:
        from supabase import create_client
        _client = create_client(url, key)
        return _client
    except Exception as e:
        print(f"[reports_api] could not create Supabase client: {e}")
        return None


def _check_staff_access(code: Optional[str]):
    expected = os.environ.get("STAFF_ACCESS_CODE", "")
    if not expected or not code or not hmac.compare_digest(code.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Invalid staff access code")


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        v = value.replace("Z", "+00:00")
        # Postgres can return 6-digit microseconds or fewer; fromisoformat handles both on 3.11+,
        # normalise for older versions.
        if "." in v:
            head, tail = v.split(".", 1)
            frac = ""
            rest = ""
            for i, ch in enumerate(tail):
                if ch.isdigit():
                    frac += ch
                else:
                    rest = tail[i:]
                    break
            v = f"{head}.{frac[:6].ljust(6, '0')}{rest}"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _fetch_all(build_query) -> List[Dict[str, Any]]:
    """Pages through a query PAGE rows at a time (Supabase caps one response)."""
    rows: List[Dict[str, Any]] = []
    start = 0
    while True:
        res = build_query().range(start, start + PAGE - 1).execute()
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        start += PAGE


def _fetch_calls(client, activation_ids: List[str]) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    for i in range(0, len(activation_ids), 100):
        chunk = activation_ids[i:i + 100]
        calls.extend(_fetch_all(
            lambda chunk=chunk: client.table("triage_activation_calls")
            .select(CALL_COLS).in_("activation_id", chunk).order("created_at")
        ))
    return calls


def _count_list(counter: Dict[Any, int], key_name: str, limit: Optional[int] = None):
    items = sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
    if limit:
        items = items[:limit]
    return [{key_name: k, "count": v} for k, v in items]


def build_summary(acts: List[Dict[str, Any]], calls: List[Dict[str, Any]],
                  d_from: date, d_to: date) -> Dict[str, Any]:
    """Pure function: turns raw rows into the report. Easy to test."""
    by_day: Dict[str, int] = {}
    cur = d_from
    while cur <= d_to:
        by_day[cur.isoformat()] = 0
        cur += timedelta(days=1)

    by_system: Dict[str, int] = {}
    by_sev: Dict[int, int] = {}
    by_symptom: Dict[str, int] = {}
    by_hour = [0] * 24
    acknowledged = 0
    unanswered = 0
    still_open = 0
    ack_seconds: List[float] = []

    for a in acts:
        t = _parse_ts(a.get("triggered_at"))
        if t is not None:
            local = t.astimezone(SK_TZ)
            k = local.date().isoformat()
            if k in by_day:
                by_day[k] += 1
            by_hour[local.hour] += 1
        by_system[(a.get("body_system") or "unknown")] = by_system.get((a.get("body_system") or "unknown"), 0) + 1
        sev = a.get("severity")
        if isinstance(sev, int):
            by_sev[sev] = by_sev.get(sev, 0) + 1
        sym = a.get("symptom") or "unknown"
        by_symptom[sym] = by_symptom.get(sym, 0) + 1

        status = a.get("status")
        ack_at = _parse_ts(a.get("acknowledged_at"))
        if ack_at is not None:
            acknowledged += 1
            if t is not None:
                secs = (ack_at - t).total_seconds()
                if secs >= 0:
                    ack_seconds.append(secs)
        elif status in ("exhausted", "closed"):
            unanswered += 1
        elif status == "active":
            still_open += 1

    call_status: Dict[str, int] = {}
    escalated_ids = set()
    for c in calls:
        s = c.get("status") or "unknown"
        call_status[s] = call_status.get(s, 0) + 1
        lvl = c.get("level")
        if isinstance(lvl, int) and lvl > 1 and c.get("activation_id"):
            escalated_ids.add(c["activation_id"])

    total = len(acts)
    median_ack = None
    if ack_seconds:
        s = sorted(ack_seconds)
        mid = len(s) // 2
        median_ack = s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2

    return {
        "status": "ok",
        "range": {"from": d_from.isoformat(), "to": d_to.isoformat(),
                  "days": (d_to - d_from).days + 1, "timezone": "America/Regina (CST, UTC-6)"},
        "totals": {
            "emergencies": total,
            "calls_placed": len(calls),
            "acknowledged": acknowledged,
            "acknowledged_pct": round(100 * acknowledged / total) if total else None,
            "median_ack_seconds": round(median_ack) if median_ack is not None else None,
            "escalated": len(escalated_ids),
            "unanswered": unanswered,
            "still_open": still_open,
        },
        "by_day": [{"date": k, "count": v} for k, v in by_day.items()],
        "by_hour": by_hour,
        "by_body_system": _count_list(by_system, "label"),
        "by_severity": _count_list(by_sev, "severity"),
        "by_symptom": _count_list(by_symptom, "label", 8),
        "call_outcomes": _count_list(call_status, "status"),
    }


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


@router.get("/staff/reports/summary")
def staff_reports_summary(
    from_date: str = Query(..., description="YYYY-MM-DD"),
    to_date: str = Query(..., description="YYYY-MM-DD"),
    x_staff_access_code: Optional[str] = Header(default=None),
):
    _check_staff_access(x_staff_access_code)

    try:
        d_from, d_to = _parse_date(from_date), _parse_date(to_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must look like 2026-10-31")
    if d_to < d_from:
        raise HTTPException(status_code=400, detail="'To' date is before 'From' date")
    if (d_to - d_from).days + 1 > MAX_DAYS:
        raise HTTPException(status_code=400, detail=f"Please pick a range of {MAX_DAYS} days or fewer")

    client = _get_supabase()
    if client is None:
        return {"status": "not_configured"}

    start_utc = datetime(d_from.year, d_from.month, d_from.day, tzinfo=SK_TZ).astimezone(timezone.utc)
    end_local = datetime(d_to.year, d_to.month, d_to.day, tzinfo=SK_TZ) + timedelta(days=1)
    end_utc = end_local.astimezone(timezone.utc)

    try:
        acts = _fetch_all(
            lambda: client.table("triage_activations").select(ACT_COLS)
            .gte("triggered_at", start_utc.isoformat())
            .lt("triggered_at", end_utc.isoformat())
            .order("triggered_at")
        )
        calls = _fetch_calls(client, [a["id"] for a in acts if a.get("id")])
        return build_summary(acts, calls, d_from, d_to)
    except Exception as e:
        print(f"[reports_api] query failed: {e}")
        return {"status": "error"}
