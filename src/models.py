"""Modeles partages."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RouteResult:
    depart: str
    arrivee: str
    distance_km: float | None
    source: str
    statut: str
    message_erreur: str | None
    raw_response: dict | list | None
    depart_lat: float | None = None
    depart_lng: float | None = None
    depart_zip: str | None = None
    depart_departement: str | None = None
    depart_formatted_name: str | None = None
    arrivee_lat: float | None = None
    arrivee_lng: float | None = None
    arrivee_zip: str | None = None
    arrivee_departement: str | None = None
    arrivee_formatted_name: str | None = None
