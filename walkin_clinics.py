"""
BRISK Walk-In Clinic Search Module
-----------------------------------
Searches OpenStreetMap's Overpass API for nearby walk-in clinics.

This runs SERVER-SIDE (backend calling Overpass), not from the browser —
the original browser-based version hit a CORS block that was never
actually about request formatting; see below.

TWO separate issues were found and fixed here, not one:
1. CORS: Overpass's public API doesn't reliably send CORS headers for
   arbitrary browser origins, so calling it directly from the browser was
   blocked regardless of formatting. Moving the call server-side (here)
   fixes this — server-to-server requests have no CORS restriction at all.
2. 406 Not Acceptable: even server-side, overpass-api.de's PRIMARY server
   started rejecting requests with generic/missing User-Agent headers
   sometime around April 2026 (confirmed via multiple independent GitHub
   issues on drolbr/Overpass-API and DinoTools/python-overpy, plus OSM
   community forum threads reporting the identical 406 symptom). Python's
   httpx sends a generic default User-Agent, which is exactly what's now
   rejected. Fixed by (a) sending a proper descriptive User-Agent, and
   (b) using overpass.kumi.systems — a mirror confirmed by multiple
   sources to not enforce this restriction as aggressively as the primary.
"""

import math
from urllib.parse import urlencode
import httpx

# Mirror chosen over the primary (overpass-api.de) specifically because
# multiple 2026 reports confirm the primary now 406s generic User-Agents
# far more aggressively than this mirror does.
OVERPASS_URL = "https://overpass.kumi.systems/api/interpreter"

# Overpass's usage policy asks for a descriptive User-Agent identifying
# the application — not just good practice, but now actively enforced by
# the primary server (see module docstring). Sent regardless of which
# server is used, since it's the correct way to call this API either way.
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
    query = _build_query(lat, lng, radius_meters)
    with httpx.Client(timeout=10.0) as client:
        res = client.post(
            OVERPASS_URL,
            headers=REQUEST_HEADERS,
            content=urlencode({"data": query}),
        )
        res.raise_for_status()
        data = res.json()
        return data.get("elements", [])


def find_nearby_walkin_clinics(lat: float, lng: float) -> dict:
    """
    Returns {"status": "success", "clinics": [...]} on success, or a clear
    error status otherwise. Never raises — the caller (main.py) always gets
    a usable dict back, so a slow/unreachable Overpass server can't crash
    or hang the request; it just returns an error status the frontend
    already knows how to display gracefully.
    """
    try:
        elements = _run_query(lat, lng, 15000)  # 15km first
        if len(elements) < 3:
            elements = _run_query(lat, lng, 40000)  # widen to 40km

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