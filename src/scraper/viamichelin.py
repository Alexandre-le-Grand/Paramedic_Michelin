"""
ViaMichelin : API officielle (GraphQL + vmrest) par defaut.
Option --visible : navigateur Playwright (legacy, lent).
"""
from __future__ import annotations

import json
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from config.settings import (
    BROWSER_CHANNEL,
    BROWSER_HEADLESS,
    BROWSER_SLOW_MO_MS,
    ROOT,
    SCRAPE_TIMEOUT_MS,
)
from src.extract import (
    extract_from_api_payload,
    extract_route_summary_from_page,
    is_plausible_route_km,
)
from src.models import RouteResult
from src.scraper.viamichelin_api import fetch_route_viamichelin

ITINERAIRES_URL = "https://www.viamichelin.fr/itineraires"
BROWSER_STATE = ROOT / "data" / "browser_state.json"


class ViaMichelinScraper:
    """Calcul d'itineraires ViaMichelin (API ou navigateur)."""

    def __init__(
        self,
        headless: bool | None = None,
        use_browser: bool = False,
    ) -> None:
        self._headless = BROWSER_HEADLESS if headless is None else headless
        self._use_browser = use_browser
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._captured: list[dict | list] = []

    def __enter__(self) -> ViaMichelinScraper:
        if self._use_browser:
            self._start_browser()
        else:
            print("ViaMichelin API (GraphQL + vmrest) — sans navigateur")
        return self

    def _start_browser(self) -> None:
        launch: dict[str, Any] = {
            "headless": self._headless,
            "slow_mo": BROWSER_SLOW_MO_MS,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if BROWSER_CHANNEL:
            launch["channel"] = BROWSER_CHANNEL

        context_opts: dict[str, Any] = {
            "locale": "fr-FR",
            "viewport": {"width": 1400, "height": 900},
        }
        if BROWSER_STATE.exists():
            context_opts["storage_state"] = str(BROWSER_STATE)

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(**launch)
        self._context = self._browser.new_context(**context_opts)
        self._page = self._context.new_page()
        self._page.set_default_timeout(SCRAPE_TIMEOUT_MS)
        self._page.on("response", self._on_response)
        mode = "arriere-plan" if self._headless else "fenetre visible"
        print(f"Navigateur ViaMichelin ({mode})…")
        self._page.goto(ITINERAIRES_URL, wait_until="domcontentloaded")

    def _on_response(self, response) -> None:
        url = response.url.lower()
        if response.status != 200 or ("vmrest" not in url and "iti.json" not in url):
            return
        try:
            text = response.text()
            if text.strip().startswith("{"):
                self._captured.append(json.loads(text))
            elif "(" in text:
                self._captured.append(json.loads(text[text.index("(") + 1 : text.rindex(")")]))
        except Exception:
            pass

    def fetch_route(self, depart: str, arrivee: str) -> RouteResult:
        if not self._use_browser:
            return fetch_route_viamichelin(depart, arrivee)
        return self._fetch_route_browser(depart, arrivee)

    def _fetch_route_browser(self, depart: str, arrivee: str) -> RouteResult:
        if not self._page:
            self._start_browser()
        page = self._page
        assert page is not None
        self._captured.clear()
        try:
            page.goto(ITINERAIRES_URL, wait_until="domcontentloaded")
            for fid, city in (("#departure", depart), ("#arrival", arrivee)):
                field = page.locator(fid)
                field.click(force=True)
                field.fill(f"{city}, France", force=True)
                page.wait_for_timeout(1500)
                field.press("ArrowDown")
                field.press("Enter")
                page.wait_for_timeout(500)
            page.locator("#arrival").press("Enter")
            page.wait_for_timeout(12000)
            body = page.inner_text("body")
        except Exception as exc:
            return RouteResult(
                depart=depart,
                arrivee=arrivee,
                distance_km=None,
                duree_minutes=None,
                source="viamichelin",
                statut="erreur",
                message_erreur=str(exc),
                raw_response=None,
            )

        distance_km, duree_minutes = None, None
        raw = None
        for payload in reversed(self._captured):
            km, mins = extract_from_api_payload(payload)
            if km is not None:
                distance_km, duree_minutes, raw = km, mins, payload
                break
        if not is_plausible_route_km(distance_km):
            distance_km, duree_minutes = extract_route_summary_from_page(body)

        if not is_plausible_route_km(distance_km):
            return RouteResult(
                depart=depart,
                arrivee=arrivee,
                distance_km=distance_km,
                duree_minutes=duree_minutes,
                source="viamichelin",
                statut="erreur",
                message_erreur="Itineraire non recupere dans le navigateur.",
                raw_response=raw,
            )
        return RouteResult(
            depart=depart,
            arrivee=arrivee,
            distance_km=distance_km,
            duree_minutes=duree_minutes,
            source="viamichelin",
            statut="ok",
            message_erreur=None,
            raw_response=raw,
        )

    def __exit__(self, *args: object) -> None:
        try:
            if self._context:
                BROWSER_STATE.parent.mkdir(parents=True, exist_ok=True)
                self._context.storage_state(path=str(BROWSER_STATE))
        except Exception:
            pass
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
