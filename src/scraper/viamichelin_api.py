"""ViaMichelin : geocodage GraphQL + itineraire GraphQL SearchItinerary (vmrest en secours)."""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from config.settings import (
    GRAPHQL_DIR,
    SCRAPE_API_CONCURRENCY,
    SCRAPE_RETRY_BASE_SECONDS,
    SCRAPE_RETRY_MAX,
)
from src.city_departments import geocode_search_query
from src.extract import extract_from_api_payload
from src.models import RouteResult

SEARCH_TEMPLATE = json.loads(
    (GRAPHQL_DIR / "viamichelin_search_address.json").read_text(encoding="utf-8")
)
SEARCH_FULL_TEMPLATE = json.loads(
    (GRAPHQL_DIR / "viamichelin_search_address_full.json").read_text(encoding="utf-8")
)
ITINERARY_TEMPLATE = json.loads(
    (GRAPHQL_DIR / "viamichelin_search_itinerary.json").read_text(encoding="utf-8")
)
GQL_URL = "https://bff.viamichelin.com/graphql"
VMREST_AUTH_KEY = "JSBS20110216111214120400892678"
PROXIMITY_FR = {"lng": 2.35, "lat": 46.6}
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Origin": "https://www.viamichelin.fr",
    "Referer": "https://www.viamichelin.fr/",
}
_RETRYABLE_HTTP = frozenset({429, 502, 503, 504})
_API_SEMAPHORE = threading.Semaphore(SCRAPE_API_CONCURRENCY)


def _fetch_bytes(
    req: urllib.request.Request,
    *,
    timeout: int = 30,
    retry_max: int | None = None,
) -> bytes:
    attempts = max(1, retry_max if retry_max is not None else SCRAPE_RETRY_MAX)
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            with _API_SEMAPHORE:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read()
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code not in _RETRYABLE_HTTP or attempt >= attempts - 1:
                raise
            wait = SCRAPE_RETRY_BASE_SECONDS * (2**attempt)
            print(
                f"  ViaMichelin HTTP {exc.code} — nouvel essai dans {wait:.0f}s "
                f"({attempt + 2}/{attempts})..."
            )
            time.sleep(wait)
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt >= attempts - 1:
                raise
            wait = SCRAPE_RETRY_BASE_SECONDS * (2**attempt)
            print(
                f"  ViaMichelin reseau — nouvel essai dans {wait:.0f}s "
                f"({attempt + 2}/{attempts})..."
            )
            time.sleep(wait)
    if last_exc:
        raise last_exc
    raise RuntimeError("fetch_bytes: echec inattendu")


def _post_json(
    url: str, body: dict[str, Any], *, retry_max: int | None = None
) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={**_HTTP_HEADERS, "Content-Type": "application/json"},
    )
    return json.loads(_fetch_bytes(req, retry_max=retry_max).decode())


def _get_text(url: str, *, retry_max: int | None = None) -> str:
    req = urllib.request.Request(url, headers=_HTTP_HEADERS)
    return _fetch_bytes(req, retry_max=retry_max).decode()


def search_addresses(
    query: str, *, retry_max: int | None = None
) -> list[dict[str, Any]]:
    """Geocodage GraphQL complet (adresse, CP, lat/lng, etc.)."""
    body = {
        "operationName": SEARCH_FULL_TEMPLATE["operationName"],
        "query": SEARCH_FULL_TEMPLATE["query"],
        "variables": {"query": query.strip(), "proximity": PROXIMITY_FR},
    }
    data = _post_json(GQL_URL, body, retry_max=retry_max)
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


def _geocode_hit_score(query: str, hit: dict[str, Any]) -> int:
    """Score plus haut = meilleur (commune, pas POI type Lidl)."""
    needle = query.split(",")[0].strip().lower()
    addr = hit.get("address") or {}
    city = (addr.get("city") or "").strip().lower()
    name = (hit.get("formattedName") or "").strip().lower()
    entity = (hit.get("entityType") or "").upper()
    score = 0
    if entity == "CITY":
        score += 30
    if any(token in name for token in ("lidl", "leclerc", "carrefour", "intermarche")):
        score -= 80
    if needle == city or name.startswith(needle):
        score += 50
    elif city and needle.startswith(city):
        score += 40
    elif needle in name:
        score += 15
    return score


def _pick_geocode_hit(query: str, hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Prefere une commune (CITY) dont le nom correspond a la requete."""
    return max(hits, key=lambda h: _geocode_hit_score(query, h))


def geocode_from_query(query: str, *, retry_max: int | None = None) -> dict[str, Any]:
    """Meilleur resultat geocodage : lat, lng, zip_code, department, formattedName."""
    hits = search_addresses(query, retry_max=retry_max)
    hit = _pick_geocode_hit(query, hits)
    base = query.split(",")[0].strip()
    if (hit.get("entityType") or "").upper() != "CITY" and "-" in base:
        lowered = base.lower()
        if any(token in lowered for token in ("-sur-", "-sous-", "-en-")):
            short = base.split("-")[0].strip()
            if len(short) >= 4 and short.lower() != base.lower():
                hits_short = search_addresses(short, retry_max=retry_max)
                hit_short = _pick_geocode_hit(short, hits_short)
                if _geocode_hit_score(short, hit_short) >= _geocode_hit_score(
                    query, hit
                ):
                    hit = hit_short
    address = hit.get("address") or {}
    loc = (hit.get("mapLocation") or {}).get("location") or {}
    return {
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
        "zip_code": address.get("zipCode"),
        "department": address.get("department"),
        "formatted_name": hit.get("formattedName"),
    }


def parse_vmrest_response(text: str) -> dict[str, Any]:
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


def build_vmrest_url(lon1: float, lat1: float, lon2: float, lat2: float) -> str:
    """URL vmrest itineraire (coords WGS84)."""
    step_list = f"1:e:{lon1}:{lat1};1:e:{lon2}:{lat2};"
    params = {
        "distUnit": "m",
        "itit": "0",
        "veht": "0",
        "stepList": step_list,
        "data": "header",
        "lg": "fra",
        "authKey": VMREST_AUTH_KEY,
        "callback": "cb",
        "avoidTolls": "false",
    }
    return (
        "https://vmrest.viamichelin.com/apir/10/iti.json/fra/header?"
        + urllib.parse.urlencode(params)
    )


def fetch_itinerary_vmrest(
    lon1: float,
    lat1: float,
    lon2: float,
    lat2: float,
    *,
    retry_max: int | None = None,
) -> dict[str, Any]:
    return parse_vmrest_response(
        _get_text(build_vmrest_url(lon1, lat1, lon2, lat2), retry_max=retry_max)
    )


def _itinerary_label(city: str, geo: dict[str, Any]) -> str:
    return (geo.get("formatted_name") or city).strip() or city


def fetch_itinerary_graphql(
    depart_geo: dict[str, Any],
    arrivee_geo: dict[str, Any],
    *,
    depart: str,
    arrivee: str,
    retry_max: int | None = None,
) -> dict[str, Any]:
    """Itineraire via GraphQL SearchItinerary (API actuelle du site web)."""
    lon1, lat1 = float(depart_geo["lng"]), float(depart_geo["lat"])
    lon2, lat2 = float(arrivee_geo["lng"]), float(arrivee_geo["lat"])
    body = {
        "operationName": ITINERARY_TEMPLATE["operationName"],
        "query": ITINERARY_TEMPLATE["query"],
        "variables": {
            "input": {
                "departureName": _itinerary_label(depart, depart_geo),
                "arrivalName": _itinerary_label(arrivee, arrivee_geo),
                "mode": "CAR",
                "traffic": "NONE",
                "distanceSystem": "METRIC",
                "device": "DESKTOP",
                "coordinates": [
                    {"lat": lat1, "lng": lon1},
                    {"lat": lat2, "lng": lon2},
                ],
            }
        },
    }
    data = _post_json(GQL_URL, body, retry_max=retry_max)
    if data.get("errors"):
        raise ValueError(data["errors"][0].get("message", str(data["errors"])))
    result = (data.get("data") or {}).get("searchItinerary") or {}
    if result.get("__typename") == "SearchItineraryNotFoundResult":
        raise ValueError(result.get("message") or "Itineraire introuvable")
    return {"searchItinerary": result}


def is_transient_api_error(message: str | None) -> bool:
    """503/429 etc. — ne pas figer en base, retenter au prochain run."""
    if not message:
        return False
    msg = message.lower()
    return any(
        token in msg
        for token in (
            "503",
            "502",
            "504",
            "429",
            "service unavailable",
            "at capacity",
            "too many requests",
        )
    )


def fetch_route_viamichelin(
    depart: str,
    arrivee: str,
    *,
    depart_departement: str | None = None,
    arrivee_departement: str | None = None,
    retry_max: int | None = None,
) -> RouteResult:
    try:
        depart_geo = geocode_from_query(
            geocode_search_query(depart, depart_departement),
            retry_max=retry_max,
        )
        arrivee_geo = geocode_from_query(
            geocode_search_query(arrivee, arrivee_departement),
            retry_max=retry_max,
        )
        payload: dict[str, Any] | None = None
        distance_km: float | None = None
        gql_error: str | None = None
        try:
            payload = fetch_itinerary_graphql(
                depart_geo,
                arrivee_geo,
                depart=depart,
                arrivee=arrivee,
                retry_max=retry_max,
            )
            distance_km = extract_from_api_payload(payload)
        except Exception as exc:
            gql_error = str(exc)
            if not is_transient_api_error(gql_error):
                raise

        if distance_km is None:
            lon1, lat1 = float(depart_geo["lng"]), float(depart_geo["lat"])
            lon2, lat2 = float(arrivee_geo["lng"]), float(arrivee_geo["lat"])
            try:
                payload = fetch_itinerary_vmrest(
                    lon1, lat1, lon2, lat2, retry_max=retry_max
                )
                distance_km = extract_from_api_payload(payload)
            except Exception as vm_exc:
                if gql_error and is_transient_api_error(str(vm_exc)):
                    raise ValueError(
                        f"GraphQL et vmrest indisponibles : {gql_error}"
                    ) from vm_exc
                if gql_error:
                    raise ValueError(gql_error) from vm_exc
                raise

        if distance_km is None:
            raise ValueError(
                gql_error or "Distance absente dans la reponse ViaMichelin"
            )

        return RouteResult(
            depart=depart,
            arrivee=arrivee,
            distance_km=distance_km,
            source="viamichelin",
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
            source="viamichelin",
            statut="erreur",
            message_erreur=str(exc),
            raw_response=None,
        )
