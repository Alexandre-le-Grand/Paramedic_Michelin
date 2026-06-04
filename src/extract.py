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


def extract_from_api_payload(data: dict | list) -> float | None:
    if isinstance(data, dict):
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


def extract_km_from_page_text(text: str) -> float | None:
    """Km depuis le panneau resume itineraire (navigateur)."""
    patterns = [
        r"(\d[\d\s\u00a0]*(?:[.,]\d+)?)\s*km",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.I | re.DOTALL)
        if not m:
            continue
        km = _parse_number(m.group(1))
        if is_plausible_route_km(km):
            return km
    return None
