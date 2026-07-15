"""
BRISK Walk-In Clinic Search Module
-----------------------------------
Searches OpenStreetMap's Overpass API for nearby walk-in clinics.

This runs SERVER-SIDE (backend calling Overpass), not from the browser.
The original implementation had the browser call Overpass directly, which
failed in production: Overpass's public API does not reliably send CORS
headers for arbitrary browser origins, so every request was blocked
regardless of how correctly it was formatted. Server-to-server requests
have no CORS restriction at all — only browser-to-server does — so moving
this call here is the actual fix, not a smaller patch to the request format.
"""

import math
from urllib.parse import urlencode
import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


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
            headers={"Content-Type": "application/x-www-form-urlencoded"},
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