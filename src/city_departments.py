"""Departements a preciser pour le geocodage ViaMichelin (homonymes)."""
from __future__ import annotations

# Valeurs demandees par le patron (donnees patron + ViaMichelin)
CITY_DEPARTMENT: dict[str, str] = {
    "Paris": "Département de Paris",
    "Marseille": "Bouches-du-Rhône",
}

HUB_CITIES = frozenset(CITY_DEPARTMENT)

# Dept Paris/Marseille acceptes par ViaMichelin (autres = No route found).
_ROUTABLE_PARIS_DEPARTMENTS = frozenset(
    {
        "Département de Paris",
        "Hauts-de-Seine",
        "Val-de-Marne",
    }
)
_ROUTABLE_MARSEILLE_DEPARTMENTS = frozenset({"Bouches-du-Rhône"})

# Libelles transports patron -> requete ViaMichelin
_DEPARTMENT_ALIASES: dict[str, str] = {
    "Paris": "Département de Paris",
    "75": "Département de Paris",
    "Département de Paris": "Département de Paris",
    "Arrondissement de Paris": "Département de Paris",
    "Marseille": "Bouches-du-Rhône",
    "13": "Bouches-du-Rhône",
    "Bouches-du-Rhône": "Bouches-du-Rhône",
    "Bouches-du-Rhone": "Bouches-du-Rhône",
    "Bouches du Rhône": "Bouches-du-Rhône",
}


def department_for_city(city: str) -> str | None:
    """Departement connu pour Paris / Marseille, sinon None."""
    if not city:
        return None
    return CITY_DEPARTMENT.get(city.strip())


def routable_hub_departments(city: str) -> frozenset[str]:
    if city == "Paris":
        return _ROUTABLE_PARIS_DEPARTMENTS
    if city == "Marseille":
        return _ROUTABLE_MARSEILLE_DEPARTMENTS
    return frozenset()


def is_plausible_hub_department(city: str, raw_department: str | None) -> bool:
    """Ecarte les libelles parasites et les dept hub non geocodables."""
    raw = (raw_department or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if "county" in low or low in {"none", "null"}:
        return False
    if city in HUB_CITIES:
        normalized = _DEPARTMENT_ALIASES.get(raw, raw)
        return normalized in routable_hub_departments(city)
    return True


def is_scrapable_route(
    depart: str,
    arrivee: str,
    depart_departement: str | None = None,
    arrivee_departement: str | None = None,
) -> bool:
    """False si un dept Paris/Marseille ne peut pas etre geocode (ex. Paris + Seine-Saint-Denis)."""
    if arrivee in HUB_CITIES and (arrivee_departement or "").strip():
        dept = normalize_hub_department(arrivee, arrivee_departement)
        if dept and dept not in routable_hub_departments(arrivee):
            return False
    if depart in HUB_CITIES and (depart_departement or "").strip():
        dept = normalize_hub_department(depart, depart_departement)
        if dept and dept not in routable_hub_departments(depart):
            return False
    return True


def normalize_hub_department(city: str, raw_department: str | None) -> str | None:
    """Departement geocodage pour Paris/Marseille ; None pour les autres villes."""
    city = city.strip()
    if city not in HUB_CITIES:
        return None
    raw = (raw_department or "").strip()
    if raw and is_plausible_hub_department(city, raw):
        return _DEPARTMENT_ALIASES.get(raw, raw)
    return department_for_city(city)


def geocode_search_query(city: str, department: str | None = None) -> str:
    """
    Requete ViaMichelin : ville seule, sauf Paris/Marseille ou dept fourni.
    Ex. Paris -> 'Paris, Département de Paris'
    """
    city = city.strip()
    dept = (department or department_for_city(city) or "").strip()
    if dept:
        return f"{city}, {dept}"
    return city
