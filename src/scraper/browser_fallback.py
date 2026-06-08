"""Secours navigateur (1 instance partagee) — optionnel apres OSRM."""
from __future__ import annotations

import threading

from src.route_pair import RoutePair
from src.scraper.viamichelin import ViaMichelinScraper


class BrowserFallbackPool:
    """Navigateur headless — thread du worker uniquement (Playwright sync)."""

    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._local = threading.local()
        self._scrapers: list[ViaMichelinScraper] = []
        self._scrapers_lock = threading.Lock()

    def _scraper_for_thread(self) -> ViaMichelinScraper:
        scraper = getattr(self._local, "scraper", None)
        if scraper is None:
            scraper = ViaMichelinScraper(
                headless=self._headless,
                use_browser=True,
            )
            scraper.__enter__()
            self._local.scraper = scraper
            with self._scrapers_lock:
                self._scrapers.append(scraper)
        return scraper

    def fetch_route(self, route: RoutePair):
        return self._scraper_for_thread().fetch_route_browser(
                route.depart,
                route.arrivee,
                depart_departement=route.depart_departement,
                arrivee_departement=route.arrivee_departement,
            )

    def close(self) -> None:
        with self._scrapers_lock:
            scrapers = list(self._scrapers)
            self._scrapers.clear()
        for scraper in scrapers:
            try:
                scraper.__exit__(None, None, None)
            except Exception:
                pass

    def __enter__(self) -> BrowserFallbackPool:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
