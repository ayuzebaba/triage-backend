"""
BRISK Walk-In Clinic Search Module
-----------------------------------
Searches OpenStreetMap's Overpass API for nearby walk-in clinics.

This runs SERVER-SIDE (backend calling Overpass), not from the browser —
the original browser-based version hit a CORS block that was never
actually about request formatting; see below.

THREE separate issues were found and fixed here, cumulatively:
1. CORS: Overpass's public API doesn't reliably send CORS headers for
   arbitrary browser origins, so calling it directly from the browser was
   blocked regardless of formatting. Moving the call server-side (here)
   fixes this — server-to-server requests have no CORS restriction at all.
2. 406 Not Acceptable: even server-side, overpass-api.de's PRIMARY server
   started rejecting requests with generic/missing User-Agent headers
   sometime around April 2026 (confirmed via multiple independent GitHub
   issues on drolbr/Overpass-API and DinoTools/python-overpy, plus OSM
   community forum threads reporting the identical 406 symptom). Fixed by
   sending a proper descriptive User-Agent.
3. Timeouts: even with the User-Agent fix, a single mirror server
   (overpass.kumi.systems) still timed out in testing — public Overpass
   instances are individually unreliable (slow, temporarily overloaded, or
   down). Fixed by trying multiple servers in sequence with a moderate
   per-server timeout, so one slow/down server only costs a few seconds
   before falling through to the next, rather than being a single point
   of failure.
"""

import math
from urllib.parse import urlencode
import httpx

# Multiple public Overpass instances, tried in order. Public Overpass
# servers are individually known to be unreliable (slow, temporarily down,
# or newly enforcing stricter policies — as already seen twice: a CORS
# gap on the primary, then a 406 on the primary, then a timeout on this
# first mirror). Trying several in sequence, rather than betting entirely
# on one, is the actual fix — no single public instance can be assumed
# to always respond quickly.
OVERPASS_SERVERS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

# Overpass's usage policy asks for a descriptive User-Agent identifying
# the application — not just good practice, but now actively enforced by
# at least one server (see module docstring). Sent to every server tried.
REQUEST_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "BRISK-Triage-System/1.0 (Brisk Innovation; Saskatchewan patient triage app)",
    "Accept": "application/json",
}


def _distance_km(lat1, lng1, lat2, lng2):
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _build_query(lat, lng, radius_meters):
    return f"""
    [out:json][timeout:9];
    (
      node["amenity"="clinic"](around:{radius_meters},{lat},{lng});
      node["amenity"="doctors"](around:{radius_meters},{lat},{lng});
      way["amenity"="clinic"](around:{radius_meters},{lat},{lng});
      way["amenity"="doctors"](around:{radius_meters},{lat},{lng});
    );
    out center 20;
    """


def _run_query(lat, lng, radius_meters):
    """
    Tries each Overpass server in order, giving each a moderate 8-second
    timeout. Moving to the next server immediately on any failure (timeout,
    non-2xx status, connection error) means a single slow/down server
    delays the response by only ~8s, not the full budget — and as long as
    ANY of the 3 servers responds, the search succeeds.
    """
    query = _build_query(lat, lng, radius_meters)
    body = urlencode({"data": query})
    last_error = None

    for server_url in OVERPASS_SERVERS:
        try:
            with httpx.Client(timeout=8.0) as client:
                res = client.post(server_url, headers=REQUEST_HEADERS, content=body)
                res.raise_for_status()
                data = res.json()
                return data.get("elements", [])
        except Exception as e:
            print(f"[walkin_clinics] {server_url} failed: {e}")
            last_error = e
            continue

    # All servers failed — raise the last error so the caller's except
    # block can format a clear message rather than silently returning [].
    raise last_error if last_error else RuntimeError("All Overpass servers failed")


def find_nearby_walkin_clinics(lat: float, lng: float) -> dict:
    """
    Returns {"status": "success", "clinics": [...]} on success, or a clear
    error status otherwise. Never raises — the caller (main.py) always gets
    a usable dict back, so a slow/unreachable Overpass server can't crash
    or hang the request; it just returns an error status the frontend
    already knows how to display gracefully.

    Uses a SINGLE query at a wider radius (25km) rather than two sequential
    calls (15km, then 40km if too few results) — the original two-call
    approach could add up to 40 seconds worst-case against a slower mirror,
    which is exactly what caused the timeout seen in testing. One call at
    a slightly wider radius is both simpler and faster in the common case.
    """
    try:
        elements = _run_query(lat, lng, 25000)  # single 25km radius

        clinics = []
        for el in elements:
            clinic_lat = el.get("lat") or (el.get("center") or {}).get("lat")
            clinic_lng = el.get("lon") or (el.get("center") or {}).get("lon")
            if clinic_lat is None or clinic_lng is None:
                continue
            tags = el.get("tags", {})
            address_parts = [tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:city")]
            address = " ".join(p for p in address_parts if p) or None
            clinics.append({
                "id": el.get("id"),
                "name": tags.get("name") or "Walk-in Clinic (name not listed)",
                "address": address,
                "phone": tags.get("phone") or tags.get("contact:phone"),
                "distance": round(_distance_km(lat, lng, clinic_lat, clinic_lng), 1),
            })

        clinics.sort(key=lambda c: c["distance"])
        clinics = clinics[:5]  # doc says "between 3 and 5"

        if not clinics:
            return {"status": "no_results"}
        return {"status": "success", "clinics": clinics}

    except httpx.TimeoutException:
        return {"status": "error", "reason": "Overpass API timed out"}
    except Exception as e:
        print(f"[walkin_clinics] find_nearby_walkin_clinics failed: {e}")
        return {"status": "error", "reason": str(e)}