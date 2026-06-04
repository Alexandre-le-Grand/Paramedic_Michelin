"""ViaMichelin : geocodage GraphQL + itineraire vmrest (sans navigateur)."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from config.settings import VIAMICHELIN_AVOID_TOLLS
from src.extract import extract_from_api_payload
from src.models import RouteResult

ROOT = Path(__file__).resolve().parents[2]
SEARCH_TEMPLATE = json.loads(
    (ROOT / "data" / "viamichelin_search_address.json").read_text(encoding="utf-8")
)
SEARCH_FULL_TEMPLATE = json.loads(
    (ROOT / "data" / "debug_gql_request.txt").read_text(encoding="utf-8")
)
GQL_URL = "https://bff.viamichelin.com/graphql"
VMREST_AUTH_KEY = "JSBS20110216111214120400892678"
PROXIMITY_FR = {"lng": 2.35, "lat": 46.6}
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Origin": "https://www.viamichelin.fr",
    "Referer": "https://www.viamichelin.fr/",
}


def _post_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={**_HTTP_HEADERS, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _get_text(url: str) -> str:
    req = urllib.request.Request(url, headers=_HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode()


def search_addresses(query: str) -> list[dict[str, Any]]:
    """Geocodage GraphQL complet (adresse, CP, lat/lng, etc.)."""
    body = {
        "operationName": SEARCH_FULL_TEMPLATE["operationName"],
        "query": SEARCH_FULL_TEMPLATE["query"],
        "variables": {"query": query.strip(), "proximity": PROXIMITY_FR},
    }
    data = _post_json(GQL_URL, body)
    items = (data.get("data") or {}).get("searchAddress") or []
    if not items:
        raise ValueError(f"Lieu introuvable sur ViaMichelin : {query}")
    return items


def search_city(city: str) -> tuple[float, float]:
    query = city.split(",")[0].strip()
    body = {
        "operationName": SEARCH_TEMPLATE["operationName"],
        "query": SEARCH_TEMPLATE["query"],
        "variables": {"query": query, "proximity": PROXIMITY_FR},
    }
    data = _post_json(GQL_URL, body)
    items = (data.get("data") or {}).get("searchAddress") or []
    if not items:
        raise ValueError(f"Ville introuvable sur ViaMichelin : {city}")
    loc = items[0]["mapLocation"]["location"]
    return float(loc["lng"]), float(loc["lat"])


def coords_from_hit(hit: dict[str, Any]) -> tuple[float, float]:
    loc = hit["mapLocation"]["location"]
    return float(loc["lng"]), float(loc["lat"])


def geocode_from_query(query: str) -> dict[str, Any]:
    """Premier resultat geocodage : lat, lng, zip_code."""
    hit = search_addresses(query)[0]
    address = hit.get("address") or {}
    loc = (hit.get("mapLocation") or {}).get("location") or {}
    return {
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
        "zip_code": address.get("zipCode"),
    }


def _parse_vmrest_jsonp(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{"):
        payload = json.loads(stripped)
        if "error" in payload:
            raise ValueError(str(payload["error"]))
        return payload

    match = re.search(r"cb\((\{.*\})\)", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    start = text.find('{"header"')
    if start >= 0:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : i + 1])

    raise ValueError(f"Reponse vmrest illisible : {text[:120]}")


def fetch_itinerary_vmrest(
    lon1: float,
    lat1: float,
    lon2: float,
    lat2: float,
    *,
    avoid_tolls: bool | None = None,
) -> dict[str, Any]:
    step_list = f"1:e:{lon1}:{lat1};1:e:{lon2}:{lat2};"
    avoid = VIAMICHELIN_AVOID_TOLLS if avoid_tolls is None else avoid_tolls
    params = {
        "distUnit": "m",
        "itit": "0",
        "veht": "0",
        "stepList": step_list,
        "data": "header",
        "lg": "fra",
        "authKey": VMREST_AUTH_KEY,
        "callback": "cb",
        "avoidTolls": "true" if avoid else "false",
    }
    url = (
        "https://vmrest.viamichelin.com/apir/10/iti.json/fra/header?"
        + urllib.parse.urlencode(params)
    )
    return _parse_vmrest_jsonp(_get_text(url))


def fetch_route_viamichelin(
    depart: str, arrivee: str, *, avoid_tolls: bool | None = None
) -> RouteResult:
    try:
        depart_geo = geocode_from_query(depart)
        arrivee_geo = geocode_from_query(arrivee)
        lon1, lat1 = float(depart_geo["lng"]), float(depart_geo["lat"])
        lon2, lat2 = float(arrivee_geo["lng"]), float(arrivee_geo["lat"])
        payload = fetch_itinerary_vmrest(
            lon1, lat1, lon2, lat2, avoid_tolls=avoid_tolls
        )
        distance_km, duree_minutes = extract_from_api_payload(payload)
        if distance_km is None:
            raise ValueError("Distance absente dans la reponse vmrest")

        return RouteResult(
            depart=depart,
            arrivee=arrivee,
            distance_km=distance_km,
            duree_minutes=duree_minutes,
            source="viamichelin",
            statut="ok",
            message_erreur=None,
            raw_response=payload,
            depart_lat=depart_geo.get("lat"),
            depart_lng=depart_geo.get("lng"),
            depart_zip=depart_geo.get("zip_code"),
            arrivee_lat=arrivee_geo.get("lat"),
            arrivee_lng=arrivee_geo.get("lng"),
            arrivee_zip=arrivee_geo.get("zip_code"),
        )
    except Exception as exc:
        return RouteResult(
            depart=depart,
            arrivee=arrivee,
            distance_km=None,
            duree_minutes=None,
            source="viamichelin",
            statut="erreur",
            message_erreur=str(exc),
            raw_response=None,
        )
