"""Expansion des trajets Paris / Marseille par departement."""
from __future__ import annotations

from src.city_departments import HUB_CITIES, department_for_city, normalize_hub_department
from src.route_pair import RoutePair


def canonical_route_pair(
    dep: str,
    arr: str,
    dep_dept: str | None,
    arr_dept: str | None,
) -> RoutePair | None:
    """Oriente depart/arrivee (ordre alphabetique) et conserve les dept des hubs."""
    dep = dep.strip()
    arr = arr.strip()
    if not dep or not arr or dep == arr:
        return None
    dep_dept = (dep_dept or "").strip() or None
    arr_dept = (arr_dept or "").strip() or None
    if dep <= arr:
        return RoutePair(
            dep,
            arr,
            depart_departement=normalize_hub_department(dep, dep_dept),
            arrivee_departement=normalize_hub_department(arr, arr_dept),
        )
    return RoutePair(
        arr,
        dep,
        depart_departement=normalize_hub_department(arr, arr_dept),
        arrivee_departement=normalize_hub_department(dep, dep_dept),
    )


def expand_hub_routes(
    routes: list[RoutePair],
    hub_departments: dict[str, set[str]],
    routes_to_city: dict[str, list[RoutePair]] | None = None,
) -> list[RoutePair]:
    """
    Duplique les trajets impliquant Paris/Marseille pour chaque departement du hub.

    Si Paris est en lien avec Bordeaux, on ajoute aussi tous les departs (ville+dept)
  presents dans les transports vers Bordeaux (regle patron).
    """
    routes_to_city = routes_to_city or {}
    out: dict[tuple, RoutePair] = {}

    def add(route: RoutePair | None) -> None:
        if route is None:
            return
        out[route.mongo_key()] = route

    for route in routes:
        add(route)
        hubs_in_pair: list[tuple[str, str]] = []
        if route.depart in HUB_CITIES:
            hubs_in_pair.append(("depart", route.depart))
        if route.arrivee in HUB_CITIES:
            hubs_in_pair.append(("arrivee", route.arrivee))

        for side, hub in hubs_in_pair:
            depts = hub_departments.get(hub) or set()
            default = department_for_city(hub)
            if default:
                depts = set(depts) | {default}
            if not depts:
                continue
            other = route.arrivee if side == "depart" else route.depart
            normalized_depts: set[str] = set()
            for raw_dept in depts:
                dept = normalize_hub_department(hub, raw_dept)
                if dept:
                    normalized_depts.add(dept)
            for dept in sorted(normalized_depts):
                if side == "depart":
                    add(
                        RoutePair(
                            hub,
                            other,
                            depart_departement=dept,
                            arrivee_departement=route.arrivee_departement,
                        )
                    )
                else:
                    add(
                        RoutePair(
                            other,
                            hub,
                            depart_departement=route.depart_departement,
                            arrivee_departement=dept,
                        )
                    )

            for extra in routes_to_city.get(other, []):
                add(extra)

    return sorted(out.values(), key=lambda r: r.mongo_key())
