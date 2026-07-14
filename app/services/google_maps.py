"""Google Maps integration helpers for FreightFlow Nexus.

The API key is read from Flask config / environment. Backend calls fail closed
with a clear reason so the demo still works when internet/API billing is off.
"""
from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

from flask import current_app


def _api_key() -> str:
    return (current_app.config.get("GOOGLE_MAPS_API_KEY") or "").strip()


def has_google_maps_key() -> bool:
    return bool(_api_key())


def geocode_address(address: str, city: str = "", country: str = "South Africa") -> dict:
    """Validate and geocode a South African address using Google Geocoding API."""
    key = _api_key()
    if not key:
        return {"ok": False, "reason": "Google Maps API key is not configured."}

    query = ", ".join([x for x in [address, city, country] if x])
    params = urlencode({"address": query, "components": "country:ZA", "key": key})
    url = f"https://maps.googleapis.com/maps/api/geocode/json?{params}"
    try:
        with urlopen(url, timeout=8) as res:
            payload = json.loads(res.read().decode("utf-8"))
    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ok": False, "reason": f"Google geocoding unavailable: {exc}"}

    if payload.get("status") != "OK" or not payload.get("results"):
        return {"ok": False, "reason": f"Address not validated by Google Maps ({payload.get('status', 'UNKNOWN')})."}

    result = payload["results"][0]
    loc = result.get("geometry", {}).get("location", {})
    return {
        "ok": True,
        "formatted_address": result.get("formatted_address", query),
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
        "place_id": result.get("place_id"),
    }


def route_distance_km(origin: str, destination: str) -> dict:
    """Return road distance and ETA using Google Distance Matrix API."""
    key = _api_key()
    if not key:
        return {"ok": False, "reason": "Google Maps API key is not configured."}

    params = urlencode({"origins": origin, "destinations": destination, "units": "metric", "key": key})
    url = f"https://maps.googleapis.com/maps/api/distancematrix/json?{params}"
    try:
        with urlopen(url, timeout=8) as res:
            payload = json.loads(res.read().decode("utf-8"))
    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ok": False, "reason": f"Google distance matrix unavailable: {exc}"}

    if payload.get("status") != "OK":
        return {"ok": False, "reason": f"Google route validation failed ({payload.get('status', 'UNKNOWN')})."}
    rows = payload.get("rows") or []
    elements = rows[0].get("elements") if rows else []
    elem = elements[0] if elements else {}
    if elem.get("status") != "OK":
        return {"ok": False, "reason": f"Route not found by Google Maps ({elem.get('status', 'UNKNOWN')})."}

    metres = elem["distance"]["value"]
    seconds = elem["duration"]["value"]
    return {
        "ok": True,
        "distance_km": round(metres / 1000, 1),
        "duration_minutes": round(seconds / 60),
        "distance_text": elem["distance"].get("text"),
        "duration_text": elem["duration"].get("text"),
    }
