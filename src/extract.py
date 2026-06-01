"""Extraction distance/duree depuis reponses JSON ViaMichelin ou texte page."""
from __future__ import annotations

import re
from typing import Any


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


def extract_from_api_payload(data: dict | list) -> tuple[float | None, int | None]:
    """Cherche distance (m ou km) et duree (s ou min) dans le JSON vmrest."""
    best_dist_m: float | None = None
    best_time_s: float | None = None

    def walk(obj: Any) -> None:
        nonlocal best_dist_m, best_time_s
        if isinstance(obj, dict):
            for key, val in obj.items():
                kl = key.lower()
                if not isinstance(val, (dict, list)):
                    num = _parse_number(val)
                    if num is None:
                        continue
                    if any(x in kl for x in ("totaldist", "totaldistance", "distance")):
                        if num > 500:
                            best_dist_m = max(best_dist_m or 0, num)
                        elif num > 1 and (best_dist_m is None or num * 1000 > best_dist_m):
                            best_dist_m = num * 1000
                    if any(x in kl for x in ("totaltime", "duration", "traveltime")) and "toll" not in kl:
                        if num > 120:
                            best_time_s = max(best_time_s or 0, num)
                else:
                    walk(val)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)

    distance_km = round(best_dist_m / 1000, 1) if best_dist_m else None
    duree_min = int(round(best_time_s / 60)) if best_time_s else None
    return distance_km, duree_min


# En dessous: segments carte / zoom, pas la distance totale du trajet
MIN_ROUTE_KM = 80


def extract_km_from_page_text(text: str, min_km: float = MIN_ROUTE_KM) -> float | None:
    """Distance totale affichee (ignore les petits segments carte < min_km)."""
    matches = re.findall(r"(\d[\d\s\u00a0]*(?:[.,]\d+)?)\s*km", text, flags=re.I)
    values: list[float] = []
    for m in matches:
        n = _parse_number(m)
        if n is not None and n >= min_km:
            values.append(n)
    return max(values) if values else None


def is_plausible_route_km(distance_km: float | None) -> bool:
    return distance_km is not None and distance_km >= MIN_ROUTE_KM


def extract_duration_from_page_text(text: str) -> int | None:
    m = re.search(r"(\d+)\s*h(?:\s*(\d+))?\s*min", text, flags=re.I)
    if m:
        h = int(m.group(1))
        mins = int(m.group(2) or 0)
        return h * 60 + mins
    m2 = re.search(r"(\d+)\s*min", text, flags=re.I)
    if m2:
        return int(m2.group(1))
    return None