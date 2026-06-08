"""Paire de trajet avec metadonnees optionnelles."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.city_departments import department_for_city


@dataclass(frozen=True)
class RoutePair:
    depart: str
    arrivee: str
    depart_departement: str | None = None
    arrivee_departement: str | None = None

    @classmethod
    def from_cities(cls, depart: str, arrivee: str) -> RoutePair:
        return cls(
            depart=depart.strip(),
            arrivee=arrivee.strip(),
            depart_departement=department_for_city(depart),
            arrivee_departement=department_for_city(arrivee),
        )

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> RoutePair:
        depart = (data.get("depart") or "").strip()
        arrivee = (data.get("arrivee") or "").strip()
        dep_dept = data.get("depart_departement") or department_for_city(depart)
        arr_dept = data.get("arrivee_departement") or department_for_city(arrivee)
        return cls(
            depart=depart,
            arrivee=arrivee,
            depart_departement=dep_dept,
            arrivee_departement=arr_dept,
        )

    def as_tuple(self) -> tuple[str, str]:
        return self.depart, self.arrivee
