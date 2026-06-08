"""OSRM — secours distance routiere (geocodage ViaMichelin + route OSRM)."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from config.settings import OSRM_BASE_URL
from src.city_departments import geocode_search_query
from src.extract import _meters_to_km, is_plausible_route_km
from src.models import RouteResult
from src.scraper.viamichelin_api import geocode_from_query

_HTTP_HEADERS = {
    "User-Agent": "Paramedic-Michelin/1.0",
    "Accept": "application/json",
}


def fetch_route_osrm(
    depart: str,
    arrivee: str,
    *,
    depart_departement: str | None = None,
    arrivee_departement: str | None = None,
) -> RouteResult:
    """Distance routiere via OSRM (coords depuis geocodage GraphQL ViaMichelin)."""
    try:
        depart_geo = geocode_from_query(
            geocode_search_query(depart, depart_departement),
            retry_max=1,
        )
        arrivee_geo = geocode_from_query(
            geocode_search_query(arrivee, arrivee_departement),
            retry_max=1,
        )
        lon1, lat1 = float(depart_geo["lng"]), float(depart_geo["lat"])
        lon2, lat2 = float(arrivee_geo["lng"]), float(arrivee_geo["lat"])

        path = f"/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
        params = urllib.parse.urlencode({"overview": "false", "steps": "false"})
        url = f"{OSRM_BASE_URL.rstrip('/')}{path}?{params}"
        req = urllib.request.Request(url, headers=_HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())

        routes = payload.get("routes") or []
        if not routes:
            code = payload.get("code", "NoRoute")
            raise ValueError(f"OSRM sans itineraire ({code})")

        dist_m = routes[0].get("distance")
        if dist_m is None:
            raise ValueError("OSRM : distance absente")
        distance_km = _meters_to_km(float(dist_m))
        if not is_plausible_route_km(distance_km):
            raise ValueError(f"OSRM : distance improbable ({distance_km} km)")

        return RouteResult(
            depart=depart,
            arrivee=arrivee,
            distance_km=distance_km,
            source="osrm",
            statut="ok",
            message_erreur=None,
            raw_response=payload,
            depart_lat=depart_geo.get("lat"),
            depart_lng=depart_geo.get("lng"),
            depart_zip=depart_geo.get("zip_code"),
            depart_departement=depart_geo.get("department") or depart_departement,
            depart_formatted_name=depart_geo.get("formatted_name"),
            arrivee_lat=arrivee_geo.get("lat"),
            arrivee_lng=arrivee_geo.get("lng"),
            arrivee_zip=arrivee_geo.get("zip_code"),
            arrivee_departement=arrivee_geo.get("department") or arrivee_departement,
            arrivee_formatted_name=arrivee_geo.get("formatted_name"),
        )
    except Exception as exc:
        return RouteResult(
            depart=depart,
            arrivee=arrivee,
            distance_km=None,
            source="osrm",
            statut="erreur",
            message_erreur=str(exc),
            raw_response=None,
            depart_departement=depart_departement,
            arrivee_departement=arrivee_departement,
        )
