"""Modeles partages."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RouteResult:
    depart: str
    arrivee: str
    distance_km: float | None
    duree_minutes: int | None
    source: str
    statut: str
    message_erreur: str | None
    raw_response: dict | list | None
