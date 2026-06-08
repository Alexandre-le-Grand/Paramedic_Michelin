"""Departements a preciser pour le geocodage ViaMichelin (homonymes)."""
from __future__ import annotations

# Valeurs demandees par le patron (donnees patron + ViaMichelin)
CITY_DEPARTMENT: dict[str, str] = {
    "Paris": "Département de Paris",
    "Marseille": "Bouches-du-Rhône",
}


def department_for_city(city: str) -> str | None:
    """Departement connu pour Paris / Marseille, sinon None."""
    if not city:
        return None
    return CITY_DEPARTMENT.get(city.strip())


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
