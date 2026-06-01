"""
Scraping ViaMichelin via Playwright (Edge, fenetre optionnelle).
Une seule session navigateur pour tous les trajets du CSV.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Iterator

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from config.settings import (
    BROWSER_CHANNEL,
    BROWSER_HEADLESS,
    BROWSER_SLOW_MO_MS,
    ROOT,
    SCRAPE_TIMEOUT_MS,
)
from src.extract import (
    extract_duration_from_page_text,
    extract_from_api_payload,
    extract_km_from_page_text,
    is_plausible_route_km,
)
from src.models import RouteResult

ITINERAIRES_URL = "https://www.viamichelin.fr/itineraires"
BROWSER_STATE = ROOT / "data" / "browser_state.json"


def _parse_jsonp(text: str) -> dict | list:
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    if "(" in text and ")" in text:
        return json.loads(text[text.index("(") + 1 : text.rindex(")")])
    return json.loads(text)


def _dismiss_didomi(page: Page) -> None:
    """Ferme le bandeau cookies Didomi qui bloque les clics."""
    for selector in (
        "#didomi-notice-agree-button",
        "button#didomi-notice-agree-button",
    ):
        btn = page.locator(selector)
        if btn.count():
            try:
                btn.click(force=True, timeout=3000)
            except Exception:
                pass

    for label in ("Accepter & Fermer", "Tout accepter", "Accepter"):
        btn = page.get_by_role("button", name=re.compile(label, re.I))
        if btn.count():
            try:
                btn.first.click(force=True, timeout=2000)
            except Exception:
                pass

    try:
        page.wait_for_selector("#didomi-popup", state="hidden", timeout=8000)
    except Exception:
        page.evaluate(
            """() => {
                for (const id of ['didomi-popup', 'didomi-host']) {
                    const el = document.getElementById(id);
                    if (el) el.remove();
                }
            }"""
        )

    page.wait_for_timeout(500)


def _fill_city(page: Page, field_id: str, city: str) -> None:
    """Remplit depart ou arrival ; selection au clavier (evite le popup cookies)."""
    _dismiss_didomi(page)
    label = f"{city}, France" if ", France" not in city else city
    field = page.locator(field_id)
    field.click(force=True)
    field.fill("", force=True)
    field.fill(label, force=True)
    page.wait_for_timeout(2500)
    _dismiss_didomi(page)
    page.keyboard.press("ArrowDown")
    page.wait_for_timeout(300)
    page.keyboard.press("Enter")
    page.wait_for_timeout(1000)


def _trigger_route_calculation(page: Page) -> None:
    """Lance le calcul (Enter suffit souvent ; pas de bouton 'Rechercher' sur la page)."""
    _dismiss_didomi(page)
    page.locator("#arrival").press("Enter")
    page.wait_for_timeout(1500)

    for selector in (
        "button.btn-filled-primary",
        "button[type='submit']",
        "form button[type='button']",
    ):
        btn = page.locator(selector)
        if btn.count() > 0:
            try:
                btn.first.click(force=True, timeout=3000)
                page.wait_for_timeout(1000)
                return
            except Exception:
                pass

    for pattern in (r"Rechercher", r"itin", r"Calculer"):
        btn = page.get_by_role("button", name=re.compile(pattern, re.I))
        if btn.count() > 0:
            try:
                btn.first.click(force=True, timeout=3000)
                return
            except Exception:
                pass


def _read_km_from_page(page: Page) -> float | None:
    """Lit la distance sur la page — prend le plus grand km plausible (total trajet)."""
    candidates: list[float] = []
    try:
        loc = page.get_by_text(re.compile(r"\d{2,4}[\s\u00a0.,]?\d*\s*km", re.I))
        for i in range(min(loc.count(), 15)):
            km = extract_km_from_page_text(loc.nth(i).inner_text(timeout=2000))
            if is_plausible_route_km(km) and km is not None:
                candidates.append(km)
    except Exception:
        pass
    body_km = extract_km_from_page_text(page.inner_text("body"))
    if is_plausible_route_km(body_km) and body_km is not None:
        candidates.append(body_km)
    return max(candidates) if candidates else None


def _wait_for_route_data(
    page: Page,
    captured: list[dict | list],
    timeout_s: int = 120,
) -> tuple[str, float | None]:
    """Attend vmrest ou distance affichee sur la page."""
    deadline = time.time() + timeout_s
    body_text = ""
    km_found: float | None = None
    while time.time() < deadline:
        if captured:
            body_text = page.inner_text("body")
            km_found = _read_km_from_page(page)
            if is_plausible_route_km(km_found):
                return body_text, km_found
        body_text = page.inner_text("body")
        km_found = _read_km_from_page(page)
        if is_plausible_route_km(km_found):
            return body_text, km_found
        page.wait_for_timeout(2000)
    return body_text or page.inner_text("body"), km_found


class ViaMichelinScraper:
    """Session navigateur reutilisee pour plusieurs trajets."""

    def __init__(self, headless: bool | None = None) -> None:
        self._headless = BROWSER_HEADLESS if headless is None else headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._captured: list[dict | list] = []

    def __enter__(self) -> ViaMichelinScraper:
        launch: dict[str, Any] = {
            "headless": self._headless,
            "slow_mo": BROWSER_SLOW_MO_MS,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        }
        if BROWSER_CHANNEL:
            launch["channel"] = BROWSER_CHANNEL

        context_opts: dict[str, Any] = {
            "locale": "fr-FR",
            "viewport": {"width": 1400, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
            ),
        }
        if BROWSER_STATE.exists():
            context_opts["storage_state"] = str(BROWSER_STATE)

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(**launch)
        self._context = self._browser.new_context(**context_opts)
        self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(SCRAPE_TIMEOUT_MS)
        self._page.on("response", self._on_response)

        mode = "arriere-plan" if self._headless else "fenetre visible"
        print(f"Navigateur ({mode}) — session pour tous les trajets…")
        self._page.goto(ITINERAIRES_URL, wait_until="domcontentloaded")
        _dismiss_didomi(self._page)
        self._page.wait_for_function(
            "() => { const el = document.querySelector('#departure'); return el && !el.disabled; }",
            timeout=30000,
        )
        return self

    def _on_response(self, response) -> None:
        if "vmrest" not in response.url or response.status != 200:
            return
        try:
            self._captured.append(_parse_jsonp(response.text()))
        except Exception:
            pass

    def _is_alive(self) -> bool:
        try:
            return self._page is not None and not self._page.is_closed()
        except Exception:
            return False

    def _restart_session(self) -> None:
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
        self.__enter__()

    def fetch_route(self, depart: str, arrivee: str) -> RouteResult:
        if not self._is_alive():
            print("  [ViaMichelin] Reconnexion Edge…")
            self._restart_session()

        page = self._page
        assert page is not None

        self._captured.clear()
        body_text = ""

        try:
            page.goto(ITINERAIRES_URL, wait_until="domcontentloaded")
            _dismiss_didomi(page)
            _fill_city(page, "#departure", depart)
            _fill_city(page, "#arrival", arrivee)
            _trigger_route_calculation(page)
            print("  [ViaMichelin] Calcul en cours, lecture des km…")
            body_text, km_hint = _wait_for_route_data(page, self._captured, timeout_s=120)
            if km_hint is not None and not self._captured:
                self._captured.append({"page_km_hint": km_hint})

        except Exception as exc:
            msg = str(exc)
            if "closed" in msg.lower() and not body_text:
                print("  [ViaMichelin] Fenetre fermee — nouvel essai…")
                try:
                    self._restart_session()
                    return self.fetch_route(depart, arrivee)
                except Exception as exc2:
                    msg = str(exc2)
            return RouteResult(
                depart=depart,
                arrivee=arrivee,
                distance_km=None,
                duree_minutes=None,
                source="viamichelin",
                statut="erreur",
                message_erreur=msg,
                raw_response=None,
            )

        return _build_result(depart, arrivee, self._captured, body_text)

    def __exit__(self, *args: object) -> None:
        if self._context:
            BROWSER_STATE.parent.mkdir(parents=True, exist_ok=True)
            self._context.storage_state(path=str(BROWSER_STATE))
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()


def _build_result(
    depart: str,
    arrivee: str,
    captured: list[dict | list],
    body_text: str,
) -> RouteResult:
    distance_km: float | None = None
    duree_minutes: int | None = None
    raw: dict | list | None = None

    for payload in captured:
        if isinstance(payload, dict) and "page_km_hint" in payload:
            distance_km = float(payload["page_km_hint"])
            raw = payload
            continue
        km, mins = extract_from_api_payload(payload)
        if km:
            distance_km = km
        if mins:
            duree_minutes = mins
        raw = payload

    if distance_km is None and body_text:
        distance_km = extract_km_from_page_text(body_text)
        if duree_minutes is None:
            duree_minutes = extract_duration_from_page_text(body_text)

    if not is_plausible_route_km(distance_km):
        return RouteResult(
            depart=depart,
            arrivee=arrivee,
            distance_km=distance_km,
            duree_minutes=duree_minutes,
            source="viamichelin",
            statut="erreur",
            message_erreur="Itineraire non recupere — laissez Edge finir le calcul.",
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


def fetch_route(depart: str, arrivee: str) -> RouteResult:
    """Un seul trajet (ouvre et ferme Edge). Preferer ViaMichelinScraper en batch."""
    with ViaMichelinScraper() as scraper:
        return scraper.fetch_route(depart, arrivee)


def fetch_routes(trajets: list[tuple[str, str]]) -> Iterator[RouteResult]:
    """Tous les trajets dans la meme fenetre Edge."""
    with ViaMichelinScraper() as scraper:
        for depart, arrivee in trajets:
            yield scraper.fetch_route(depart, arrivee)
