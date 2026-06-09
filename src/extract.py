"""Extraction distance (km) depuis JSON ViaMichelin (vmrest) ou page."""
from __future__ import annotations

import re
from typing import Any

MIN_ROUTE_KM = 0.5
MAX_ROUTE_KM = 2000.0


def _parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace("\xa0", "").replace(" ", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _meters_to_km(meters: float) -> float:
    return round(meters / 1000, 1)


def _distance_from_summary(summary: dict[str, Any]) -> float | None:
    dist_m = _parse_number(
        summary.get("totalDist")
        or summary.get("totalDistance")
        or summary.get("distance")
    )
    if dist_m and dist_m > 0:
        return _meters_to_km(dist_m)
    return None


def _extract_header_distance(obj: Any) -> float | None:
    """totalDist (m) dans header.summaries / summaryList."""
    if isinstance(obj, dict):
        header = obj.get("header") or obj.get("Header")
        if isinstance(header, dict):
            summaries = (
                header.get("summaryList")
                or header.get("summarylist")
                or header.get("summaries")
                or header.get("Summaries")
            )
            if isinstance(summaries, list) and summaries:
                first = summaries[0]
                if isinstance(first, dict):
                    km = _distance_from_summary(first)
                    if km is not None:
                        return km
        for val in obj.values():
            km = _extract_header_distance(val)
            if km is not None:
                return km
    elif isinstance(obj, list):
        for item in obj:
            km = _extract_header_distance(item)
            if km is not None:
                return km
    return None


def _walk_distance(obj: Any) -> float | None:
    """Parcours limite : uniquement totalDist / totalDistance explicites."""
    best_dist_m: float | None = None

    def walk(node: Any) -> None:
        nonlocal best_dist_m
        if isinstance(node, dict):
            for key, val in node.items():
                kl = key.lower()
                if isinstance(val, (dict, list)):
                    walk(val)
                    continue
                num = _parse_number(val)
                if num is None:
                    continue
                if kl in ("totaldist", "totaldistance"):
                    if num > 500:
                        best_dist_m = num
                    elif num >= 1:
                        best_dist_m = num * 1000
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(obj)
    return _meters_to_km(best_dist_m) if best_dist_m else None


def _km_from_route_distance(rd: dict[str, Any]) -> float | None:
    value = _parse_number(rd.get("value"))
    if value is None or value <= 0:
        return None
    unit = (rd.get("unit") or "").upper()
    if unit in ("KILOMETER", "KM", "KILOMETRE", "KILOMÈTRE"):
        return round(value, 1)
    if unit in ("METER", "M", "METRE", "MÈTRE"):
        return _meters_to_km(value)
    if value > 500:
        return _meters_to_km(value)
    return round(value, 1)


def _extract_search_itinerary_distance(data: dict[str, Any]) -> float | None:
    """Distance depuis GraphQL searchItinerary (remplace vmrest quand HS)."""
    node = data.get("searchItinerary") or data.get("data", {}).get("searchItinerary")
    if not isinstance(node, dict):
        return None
    if node.get("__typename") == "SearchItineraryNotFoundResult":
        return None
    routes = node.get("routes")
    if not isinstance(routes, list) or not routes:
        return None
    rd = routes[0].get("routeDistance")
    if isinstance(rd, dict):
        return _km_from_route_distance(rd)
    return None


def extract_from_api_payload(data: dict | list) -> float | None:
    if isinstance(data, dict):
        km = _extract_search_itinerary_distance(data)
        if km is not None:
            return km
        itineraries = data.get("itineraryList") or data.get("itinerarylist")
        if isinstance(itineraries, list) and itineraries:
            km = _extract_header_distance(itineraries[0])
            if km is not None:
                return km
    km = _extract_header_distance(data)
    if km is not None:
        return km
    return _walk_distance(data)


def is_plausible_route_km(distance_km: float | None) -> bool:
    return (
        distance_km is not None
        and MIN_ROUTE_KM <= distance_km <= MAX_ROUTE_KM
    )


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Distance a vol d'oiseau (km)."""
    from math import asin, cos, radians, sin, sqrt

    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(
        dlon / 2
    ) ** 2
    return 2 * r * asin(sqrt(a))


def min_road_km_from_coords(
    lat1: float | None,
    lon1: float | None,
    lat2: float | None,
    lon2: float | None,
    *,
    factor: float = 0.75,
) -> float | None:
    """Km routier minimum plausible entre deux points geocodes."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    straight = haversine_km(float(lat1), float(lon1), float(lat2), float(lon2))
    return round(straight * factor, 1)


def max_road_km_from_coords(
    lat1: float | None,
    lon1: float | None,
    lat2: float | None,
    lon2: float | None,
    *,
    factor: float = 2.2,
) -> float | None:
    """Km routier maximum plausible (evite les '20 km' fantomes sur la page)."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    straight = haversine_km(float(lat1), float(lon1), float(lat2), float(lon2))
    return round(max(straight * factor, MIN_ROUTE_KM * 2), 1)


def is_plausible_road_km_between(
    distance_km: float | None,
    lat1: float | None,
    lon1: float | None,
    lat2: float | None,
    lon2: float | None,
) -> bool:
    if not is_plausible_route_km(distance_km):
        return False
    min_km = min_road_km_from_coords(lat1, lon1, lat2, lon2)
    max_km = max_road_km_from_coords(lat1, lon1, lat2, lon2)
    if min_km is not None and distance_km < min_km:
        return False
    if max_km is not None and distance_km > max_km:
        return False
    return True


def extract_km_from_page_text(
    text: str,
    *,
    min_km: float | None = None,
) -> float | None:
    """Km depuis la page resultats — prend le plus grand >= min_km si fourni."""
    candidates: list[float] = []
    for m in re.finditer(r"(\d[\d\s\u00a0]*(?:[.,]\d+)?)\s*km", text, flags=re.I):
        km = _parse_number(m.group(1))
        if is_plausible_route_km(km):
            candidates.append(km)
    if not candidates:
        return None
    if min_km is not None:
        valid = [km for km in candidates if km >= min_km]
        return max(valid) if valid else None
    return max(candidates)
