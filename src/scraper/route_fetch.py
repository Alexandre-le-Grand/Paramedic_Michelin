"""Chaine de calcul : ViaMichelin API -> OSRM -> navigateur (optionnel)."""
from __future__ import annotations

from dataclasses import replace

from src.models import RouteResult
from src.route_pair import RoutePair
from src.scraper.browser_fallback import BrowserFallbackPool
from src.scraper.osrm_api import fetch_route_osrm
from src.scraper.viamichelin_api import fetch_route_viamichelin, is_transient_api_error


def fetch_route_with_fallback(
    route: RoutePair,
    *,
    osrm_fallback: bool = False,
    browser_pool: BrowserFallbackPool | None = None,
) -> RouteResult:
    """ViaMichelin d'abord, puis OSRM si 503/429, puis navigateur si demande."""
    result = fetch_route_viamichelin(
        route.depart,
        route.arrivee,
        depart_departement=route.depart_departement,
        arrivee_departement=route.arrivee_departement,
        retry_max=1,
    )
    if result.statut == "ok":
        return result

    transient = is_transient_api_error(result.message_erreur)
    if not transient and result.statut == "erreur":
        return result

    if osrm_fallback:
        print(
            f"  -> Fallback OSRM ({route.depart} -> {route.arrivee}) "
            f"apres echec ViaMichelin..."
        )
        osrm = fetch_route_osrm(
            route.depart,
            route.arrivee,
            depart_departement=route.depart_departement,
            arrivee_departement=route.arrivee_departement,
        )
        if osrm.statut == "ok":
            return osrm
        if browser_pool is None:
            return osrm

    if browser_pool is None:
        return result

    print(
        f"  -> Fallback navigateur ({route.depart} -> {route.arrivee})..."
    )
    fallback = browser_pool.fetch_route(route)
    if fallback.statut != "ok":
        return result

    return replace(
        fallback,
        source="viamichelin-browser",
        depart_departement=fallback.depart_departement or route.depart_departement,
        arrivee_departement=fallback.arrivee_departement or route.arrivee_departement,
    )
