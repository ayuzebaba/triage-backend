"""
BRISK Reverse Geocoding Module
-------------------------------
Converts patient coordinates (lat/lng) into a real street address, using
the same Geoapify API key already set up for walk-in clinic search.

WHY THIS EXISTS: the automated emergency call previously only spoke a vague
"Saskatoon area" description. The app already has the patient's exact GPS
coordinates (same accuracy Google Maps would show) — this module converts
those coordinates into an actual readable address so the emergency call
can speak something genuinely useful ("103 Hospital Drive, Saskatoon")
instead of just naming a city.

HONEST LIMITATION: this is NOT the same as real E911 location handoff.
Twilio's phone call to 911/the clinical contact has no automatic channel
for live GPS data the way a patient's own phone/carrier does — this
reverse-geocoded address is spoken aloud in the call, read by whoever
answers, not transmitted as structured dispatch data.

Requires this environment variable (e.g. in Railway):
    GEOAPIFY_API_KEY
"""

import os
import httpx

REVERSE_GEOCODE_URL = "https://api.geoapify.com/v1/geocode/reverse"


def reverse_geocode(lat: float, lng: float) -> str:
    """
    Returns a real, human-readable address for the given coordinates, or
    a coordinate-only fallback string if the lookup fails for any reason.
    NEVER raises — a failed geocode should never block the emergency call
    itself from going out; it just falls back to raw coordinates, which
    are still genuinely useful spoken aloud, just less specific.
    """
    api_key = os.environ.get("GEOAPIFY_API_KEY")
    fallback = f"coordinates {lat:.4f}, {lng:.4f}"

    if not api_key:
        return fallback

    try:
        with httpx.Client(timeout=6.0) as client:
            res = client.get(REVERSE_GEOCODE_URL, params={
                "lat": lat,
                "lon": lng,
                "apiKey": api_key,
            })
            res.raise_for_status()
            data = res.json()

        features = data.get("features", [])
        if not features:
            return fallback

        formatted = features[0].get("properties", {}).get("formatted")
        return formatted if formatted else fallback

    except Exception as e:
        print(f"[reverse_geocode] failed: {e}")
        return fallback