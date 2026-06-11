"""Departements a preciser pour le geocodage ViaMichelin (homonymes)."""
from __future__ import annotations

# Valeurs demandees par le patron (donnees patron + ViaMichelin)
CITY_DEPARTMENT: dict[str, str] = {
    "Paris": "Département de Paris",
    "Marseille": "Bouches-du-Rhône",
}

HUB_CITIES = frozenset(CITY_DEPARTMENT)

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


def is_plausible_hub_department(city: str, raw_department: str | None) -> bool:
    """Ecarte les libelles parasites dans les transports (ex. Logan County)."""
    raw = (raw_department or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if "county" in low or low in {"none", "null"}:
        return False
    if city == "Paris":
        return (
            raw in _DEPARTMENT_ALIASES
            or raw.endswith("de Paris")
            or raw in {
                "Seine-Saint-Denis",
                "Hauts-de-Seine",
                "Val-de-Marne",
                "Essonne",
                "Yvelines",
                "Seine-et-Marne",
                "Val-d'Oise",
            }
        )
    if city == "Marseille":
        return "rh" in low or raw in _DEPARTMENT_ALIASES
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
