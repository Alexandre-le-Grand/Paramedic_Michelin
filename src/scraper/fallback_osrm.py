"""Secours: distance routiere via Nominatim + OSRM (si ViaMichelin echoue)."""
from __future__ import annotations

import time
from typing import Any

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "http://router.project-osrm.org/route/v1/driving/{coords}"


def geocode(city: str) -> tuple[float, float] | None:
    params = {"q": f"{city}, France", "format": "json", "limit": 1}
    headers = {"User-Agent": "Paramedic-Michelin/1.0 (projet etudiant)"}
    resp = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return None
    return float(data[0]["lon"]), float(data[0]["lat"])


def route_distance_km(depart: str, arrivee: str) -> dict[str, Any]:
    time.sleep(1)
    start = geocode(depart)
    end = geocode(arrivee)
    if not start or not end:
        raise ValueError(f"Geocodage impossible: {depart} -> {arrivee}")

    lon1, lat1 = start
    lon2, lat2 = end
    url = OSRM_URL.format(coords=f"{lon1},{lat1};{lon2},{lat2}")
    resp = requests.get(url, params={"overview": "false"}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise ValueError("OSRM: aucun itineraire")

    metres = payload["routes"][0]["distance"]
    seconds = payload["routes"][0]["duration"]
    return {
        "distance_km": round(metres / 1000, 1),
        "duree_minutes": int(round(seconds / 60)),
        "source": "osrm_fallback",
        "raw_response": payload,
    }