"""
BRISK Walk-In Clinic Search Module
-----------------------------------
Searches for nearby walk-in clinics using Geoapify's Places API.

REPLACES the earlier OpenStreetMap Overpass-based approach entirely. Overpass
went through three rounds of fixes (CORS block calling it from the browser,
then a 406 from a User-Agent policy change, then unreliable timeouts even
server-side with a multi-server fallback) and was still not dependably
working. Geoapify is a proper commercial API -- same underlying OSM data
source in part, but with actual uptime/reliability, a real free tier
(3,000 requests/day, no credit card required), and a stable single
endpoint instead of a patchwork of public mirrors of varying quality.

Requires this environment variable (e.g. in Railway):
    GEOAPIFY_API_KEY
"""

import os
import math
from typing import Optional
import httpx

PLACES_URL = "https://api.geoapify.com/v2/places"

# healthcare.clinic_or_praxis covers general practice / walk-in clinic type
# places in Geoapify's category system -- this is the closest match to
# "walk-in clinic" without also pulling in hospitals (handled separately
# by the hardcoded ER list) or pharmacies.
CATEGORY = "healthcare.clinic_or_praxis"


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


def _extract_phone(properties: dict) -> Optional[str]:
    """
    Geoapify's structured fields don't always include phone directly --
    it's often only present in the raw OSM tags passed through under
    datasource.raw. Check a few likely locations rather than assuming
    one fixed path, so a clinic with a phone number doesn't get
    incorrectly shown as "no phone listed" just because of field naming.
    """
    for key in ("contact_phone", "phone"):
        if properties.get(key):
            return properties[key]
    raw = (properties.get("datasource") or {}).get("raw") or {}
    for key in ("phone", "contact:phone"):
        if raw.get(key):
            return raw[key]
    return None


def find_nearby_walkin_clinics(lat: float, lng: float) -> dict:
    """
    Returns {"status": "success", "clinics": [...]} on success, or a clear
    error status otherwise. Never raises -- the caller (main.py) always gets
    a usable dict back, so a missing API key or a Geoapify outage can't
    crash or hang the request; it returns an error status the frontend
    already knows how to display gracefully.
    """
    api_key = os.environ.get("GEOAPIFY_API_KEY")
    if not api_key:
        return {"status": "error", "reason": "GEOAPIFY_API_KEY not set"}

    params = {
        "categories": CATEGORY,
        "filter": f"circle:{lng},{lat},25000",
        "bias": f"proximity:{lng},{lat}",
        "limit": 5,
        "apiKey": api_key,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.get(PLACES_URL, params=params)
            res.raise_for_status()
            data = res.json()

        features = data.get("features", [])
        if not features:
            return {"status": "no_results"}

        clinics = []
        for feature in features:
            props = feature.get("properties", {})
            clinic_lat = props.get("lat")
            clinic_lng = props.get("lon")
            if clinic_lat is None or clinic_lng is None:
                continue
            clinics.append({
                "id": props.get("place_id"),
                "name": props.get("name") or "Walk-in Clinic (name not listed)",
                "address": props.get("formatted"),
                "phone": _extract_phone(props),
                "distance": round(_distance_km(lat, lng, clinic_lat, clinic_lng), 1),
            })

        clinics.sort(key=lambda c: c["distance"])

        if not clinics:
            return {"status": "no_results"}
        return {"status": "success", "clinics": clinics}

    except httpx.TimeoutException:
        return {"status": "error", "reason": "Geoapify API timed out"}
    except Exception as e:
        print(f"[walkin_clinics] find_nearby_walkin_clinics failed: {e}")
        return {"status": "error", "reason": str(e)}