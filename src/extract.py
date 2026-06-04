"""Extraction distance/duree depuis JSON ViaMichelin (vmrest) ou page."""
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


def _seconds_to_minutes(seconds: float) -> int:
    return int(round(seconds / 60))


def _from_summary_dict(summary: dict[str, Any]) -> tuple[float | None, int | None]:
    dist_m = _parse_number(
        summary.get("totalDist")
        or summary.get("totalDistance")
        or summary.get("distance")
    )
    time_s = _parse_number(
        summary.get("totalTime")
        or summary.get("totalDuration")
        or summary.get("duration")
    )
    distance_km = _meters_to_km(dist_m) if dist_m and dist_m > 0 else None
    duree_min = _seconds_to_minutes(time_s) if time_s and time_s > 0 else None
    return distance_km, duree_min


def _extract_header_summaries(obj: Any) -> tuple[float | None, int | None]:
    """totalDist (m) et totalTime (s) dans header.summaries / summaryList."""
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
                    km, mins = _from_summary_dict(first)
                    if km is not None:
                        return km, mins
        for val in obj.values():
            km, mins = _extract_header_summaries(val)
            if km is not None:
                return km, mins
    elif isinstance(obj, list):
        for item in obj:
            km, mins = _extract_header_summaries(item)
            if km is not None:
                return km, mins
    return None, None


def _walk_totals(obj: Any) -> tuple[float | None, int | None]:
    """Parcours limite : uniquement totalDist / totalTime explicites."""
    best_dist_m: float | None = None
    best_time_s: float | None = None

    def walk(node: Any) -> None:
        nonlocal best_dist_m, best_time_s
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
                elif kl in ("totaltime", "totalduration") and num >= 60:
                    best_time_s = num
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(obj)
    distance_km = _meters_to_km(best_dist_m) if best_dist_m else None
    duree_min = _seconds_to_minutes(best_time_s) if best_time_s else None
    return distance_km, duree_min


def extract_from_api_payload(data: dict | list) -> tuple[float | None, int | None]:
    if isinstance(data, dict):
        itineraries = data.get("itineraryList") or data.get("itinerarylist")
        if isinstance(itineraries, list) and itineraries:
            km, mins = _extract_header_summaries(itineraries[0])
            if km is not None:
                return km, mins
    km, mins = _extract_header_summaries(data)
    if km is not None:
        return km, mins
    return _walk_totals(data)


def is_plausible_route_km(distance_km: float | None) -> bool:
    return (
        distance_km is not None
        and MIN_ROUTE_KM <= distance_km <= MAX_ROUTE_KM
    )


def extract_route_summary_from_page(text: str) -> tuple[float | None, int | None]:
    """Km + duree proches l'un de l'autre (panneau resume itineraire)."""
    patterns = [
        r"(\d[\d\s\u00a0]*(?:[.,]\d+)?)\s*km[^\d]{0,120}?(\d+)\s*h(?:\s*(\d+))?\s*min",
        r"(\d[\d\s\u00a0]*(?:[.,]\d+)?)\s*km[^\d]{0,120}?(\d+)\s*min\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.I | re.DOTALL)
        if not m:
            continue
        km = _parse_number(m.group(1))
        if m.lastindex and m.lastindex >= 3 and m.group(3) is not None:
            mins = int(m.group(2)) * 60 + int(m.group(3) or 0)
        else:
            mins = int(m.group(2))
        if is_plausible_route_km(km) and mins > 0:
            return km, mins
    return None, None
