"""
ViaMichelin : API GraphQL SearchItinerary par defaut (vmrest en secours).
Navigateur Playwright : --visible (tout) ou --browser-fallback (secours).
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from config.settings import (
    BROWSER_CHANNEL,
    BROWSER_HEADLESS,
    BROWSER_SLOW_MO_MS,
    ROOT,
    SCRAPE_TIMEOUT_MS,
)
from src.city_departments import department_for_city, geocode_search_query
from src.extract import (
    extract_from_api_payload,
    extract_km_from_page_text,
    is_plausible_road_km_between,
    is_plausible_route_km,
    min_road_km_from_coords,
)
from src.models import RouteResult
from src.scraper.viamichelin_api import (
    build_vmrest_url,
    fetch_route_viamichelin,
    geocode_from_query,
    parse_vmrest_response,
)

ITINERAIRES_URL = "https://www.viamichelin.fr/itineraires"
HOME_URL = "https://www.viamichelin.fr/"
BROWSER_STATE = ROOT / "data" / "browser_state.json"
_BROWSER_VMREST_WAIT_MS = 25_000
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
)
_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = { runtime: {} };
"""
_COOKIE_SELECTORS = (
    "#didomi-notice-agree-button",
    'button:has-text("Tout accepter")',
    'button:has-text("Accepter et fermer")',
    'button:has-text("Accepter")',
)
_VMREST_HEADERS = {
    "Referer": "https://www.viamichelin.fr/",
    "Origin": "https://www.viamichelin.fr",
}


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
        self._page_km: float | None = None
        self._session_ready = False

    def __enter__(self) -> ViaMichelinScraper:
        if self._use_browser:
            self._start_browser()
        else:
            print("ViaMichelin API (GraphQL SearchItinerary) — sans navigateur")
        return self

    def _start_browser(self) -> None:
        launch: dict[str, Any] = {
            "headless": self._headless,
            "slow_mo": BROWSER_SLOW_MO_MS,
            "args": ["--disable-blink-features=AutomationControlled"],
            "ignore_default_args": ["--enable-automation"],
        }
        if BROWSER_CHANNEL:
            launch["channel"] = BROWSER_CHANNEL

        context_opts: dict[str, Any] = {
            "locale": "fr-FR",
            "viewport": {"width": 1400, "height": 900},
            "user_agent": _BROWSER_USER_AGENT,
        }
        if BROWSER_STATE.exists():
            context_opts["storage_state"] = str(BROWSER_STATE)

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(**launch)
        self._context = self._browser.new_context(**context_opts)
        self._context.add_init_script(_STEALTH_INIT_SCRIPT)
        self._page = self._context.new_page()
        self._page.set_default_timeout(SCRAPE_TIMEOUT_MS)
        self._page.on("response", self._on_response)
        mode = "arriere-plan" if self._headless else "fenetre visible"
        print(f"Navigateur ViaMichelin ({mode})…")
        self._warmup_session(self._page)

    @staticmethod
    def _is_vmrest_response(response) -> bool:
        url = response.url.lower()
        return "vmrest" in url or "iti.json" in url

    def _append_vmrest_text(self, text: str) -> None:
        try:
            self._captured.append(parse_vmrest_response(text))
        except Exception:
            pass

    def _on_response(self, response) -> None:
        if response.status != 200:
            return
        url = response.url.lower()
        try:
            if self._is_vmrest_response(response):
                self._append_vmrest_text(response.text())
                return
            if "graphql" in url and response.request.method == "POST":
                body = response.json()
                if extract_from_api_payload(body) is not None:
                    self._captured.append(body)
        except Exception:
            pass

    def _dismiss_cookie_banner(self, page: Page) -> None:
        for selector in _COOKIE_SELECTORS:
            try:
                page.locator(selector).first.click(timeout=2000)
                page.wait_for_timeout(400)
                return
            except Exception:
                continue

    def _warmup_session(self, page: Page) -> None:
        """Accueil + cookies — evite le 403 sur /itineraires (anti-bot)."""
        if self._session_ready:
            return
        page.goto(HOME_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        self._dismiss_cookie_banner(page)
        self._session_ready = True

    def _fetch_vmrest_via_context(
        self,
        lon1: float,
        lat1: float,
        lon2: float,
        lat2: float,
    ) -> dict[str, Any] | None:
        """vmrest via session navigateur (memes cookies que le site)."""
        if not self._context:
            return None
        try:
            resp = self._context.request.get(
                build_vmrest_url(lon1, lat1, lon2, lat2),
                headers=_VMREST_HEADERS,
            )
            if resp.status != 200:
                return None
            return parse_vmrest_response(resp.text())
        except Exception:
            return None

    def fetch_route(
        self,
        depart: str,
        arrivee: str,
        *,
        depart_departement: str | None = None,
        arrivee_departement: str | None = None,
    ) -> RouteResult:
        if not self._use_browser:
            return fetch_route_viamichelin(
                depart,
                arrivee,
                depart_departement=depart_departement,
                arrivee_departement=arrivee_departement,
            )
        return self.fetch_route_browser(
            depart,
            arrivee,
            depart_departement=depart_departement,
            arrivee_departement=arrivee_departement,
        )

    def fetch_route_browser(
        self,
        depart: str,
        arrivee: str,
        *,
        depart_departement: str | None = None,
        arrivee_departement: str | None = None,
    ) -> RouteResult:
        if not self._page:
            self._start_browser()
        page = self._page
        assert page is not None

        base = RouteResult(
            depart=depart,
            arrivee=arrivee,
            distance_km=None,
            source="viamichelin-browser",
            statut="erreur",
            message_erreur=None,
            raw_response=None,
            depart_departement=depart_departement,
            arrivee_departement=arrivee_departement,
        )

        try:
            depart_geo = geocode_from_query(
                geocode_search_query(depart, depart_departement),
                retry_max=1,
            )
            arrivee_geo = geocode_from_query(
                geocode_search_query(arrivee, arrivee_departement),
                retry_max=1,
            )
        except Exception as exc:
            return _with_geo(
                base,
                message_erreur=f"Geocodage API avant navigateur : {exc}",
            )

        depart_label = _browser_label(depart, depart_geo, depart_departement)
        arrivee_label = _browser_label(arrivee, arrivee_geo, arrivee_departement)

        self._captured.clear()
        self._page_km = None
        min_km = min_road_km_from_coords(
            depart_geo.get("lat"),
            depart_geo.get("lng"),
            arrivee_geo.get("lat"),
            arrivee_geo.get("lng"),
        )
        try:
            print(f"  Navigateur : {depart_label} -> {arrivee_label}")
            self._load_route_in_browser(page, depart_label, arrivee_label)
            self._wait_for_vmrest(
                page,
                min_km=min_km,
                lat1=depart_geo.get("lat"),
                lon1=depart_geo.get("lng"),
                lat2=arrivee_geo.get("lat"),
                lon2=arrivee_geo.get("lng"),
            )
            if not self._captured:
                payload = self._fetch_vmrest_via_context(
                    float(depart_geo["lng"]),
                    float(depart_geo["lat"]),
                    float(arrivee_geo["lng"]),
                    float(arrivee_geo["lat"]),
                )
                if payload:
                    self._captured.append(payload)
        except Exception as exc:
            return _with_geo(
                base,
                depart_geo=depart_geo,
                arrivee_geo=arrivee_geo,
                message_erreur=str(exc),
            )

        distance_km = None
        raw = None
        for payload in reversed(self._captured):
            km = extract_from_api_payload(payload)
            if km is not None:
                distance_km, raw = km, payload
                break

        if not is_plausible_route_km(distance_km) and self._page_km is not None:
            distance_km = self._page_km

        if not is_plausible_route_km(distance_km) and not self._page_blocked(page):
            page_km = extract_km_from_page_text(
                page.inner_text("body"),
                min_km=min_km,
            )
            if is_plausible_road_km_between(
                page_km,
                depart_geo.get("lat"),
                depart_geo.get("lng"),
                arrivee_geo.get("lat"),
                arrivee_geo.get("lng"),
            ):
                distance_km = page_km

        if not is_plausible_road_km_between(
            distance_km,
            depart_geo.get("lat"),
            depart_geo.get("lng"),
            arrivee_geo.get("lat"),
            arrivee_geo.get("lng"),
        ):
            if self._page_blocked(page):
                msg = (
                    "Site bloque le navigateur automatise (Service unavailable) — "
                    "essayez --visible, un VPN systeme, ou l'API/--osrm."
                )
            else:
                msg = (
                    "Distance non capturee (vmrest/GraphQL/page) — "
                    "vmrest souvent HS ou anti-bot headless."
                )
            return _with_geo(
                base,
                depart_geo=depart_geo,
                arrivee_geo=arrivee_geo,
                message_erreur=msg,
                raw_response=raw,
            )

        return _with_geo(
            base,
            depart_geo=depart_geo,
            arrivee_geo=arrivee_geo,
            distance_km=distance_km,
            statut="ok",
            message_erreur=None,
            raw_response=raw,
        )

    def _vmrest_wait_ms(self) -> int:
        return 45_000 if not self._headless else _BROWSER_VMREST_WAIT_MS

    def _wait_for_vmrest(
        self,
        page: Page,
        *,
        min_km: float | None = None,
        lat1: float | None = None,
        lon1: float | None = None,
        lat2: float | None = None,
        lon2: float | None = None,
    ) -> None:
        """Attend vmrest/GraphQL ou km visibles sur la page resultats."""
        if self._captured:
            return
        deadline = self._vmrest_wait_ms()
        step = 1000
        waited = 0
        while waited < deadline and not self._captured:
            if not self._page_blocked(page) and self._page_on_results(page):
                page_km = extract_km_from_page_text(
                    page.inner_text("body"),
                    min_km=min_km,
                )
                if is_plausible_road_km_between(page_km, lat1, lon1, lat2, lon2):
                    self._page_km = page_km
                    return
            page.wait_for_timeout(step)
            waited += step

    def _load_route_in_browser(
        self, page: Page, depart_label: str, arrivee_label: str
    ) -> None:
        """Formulaire (comme une recherche manuelle) puis URL resultats."""
        self._warmup_session(page)
        page.goto(ITINERAIRES_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        if self._find_input(page, is_departure=True) is not None:
            self._fill_and_submit_form(page, depart_label, arrivee_label)
            try:
                page.wait_for_url("**/itineraires/resultats**", timeout=35_000)
            except Exception:
                pass
            page.wait_for_timeout(2000)
            if self._captured or self._page_on_results(page):
                return

        resultats_url = (
            f"{ITINERAIRES_URL}/resultats?"
            + urllib.parse.urlencode(
                {"departure": depart_label, "arrival": arrivee_label}
            )
        )
        page.goto(resultats_url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

    @staticmethod
    def _page_on_results(page: Page) -> bool:
        return "/resultats" in page.url

    @staticmethod
    def _page_blocked(page: Page) -> bool:
        title = (page.title() or "").lower()
        return "unavailable" in title or "indisponible" in title

    def _pick_autocomplete(self, page: Page, field, label: str) -> None:
        """Selectionne la suggestion qui correspond le mieux au libelle."""
        needle = label.split(",")[0].strip().lower()
        options = page.locator('[role="option"]')
        try:
            count = options.count()
        except Exception:
            count = 0
        for i in range(min(count, 10)):
            opt = options.nth(i)
            try:
                if not opt.is_visible(timeout=500):
                    continue
                text = (opt.inner_text(timeout=1000) or "").lower()
                if needle in text or text.startswith(needle[:4]):
                    opt.click()
                    page.wait_for_timeout(500)
                    return
            except Exception:
                continue
        if count > 0:
            try:
                options.first.click(timeout=2000)
                page.wait_for_timeout(500)
                return
            except Exception:
                pass
        field.press("ArrowDown")
        page.wait_for_timeout(200)
        field.press("Enter")
        page.wait_for_timeout(400)

    def _click_calculate(self, page: Page, arrivee_field) -> None:
        for selector in (
            'button:has-text("Calculer")',
            'button:has-text("calculer")',
            'a:has-text("Calculer")',
            'button[type="submit"]',
        ):
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=1500):
                    btn.click()
                    page.wait_for_timeout(500)
                    return
            except Exception:
                continue
        arrivee_field.press("Enter")

    def _fill_and_submit_form(
        self, page: Page, depart_label: str, arrivee_label: str
    ) -> None:
        depart_field = self._find_input(page, is_departure=True)
        arrivee_field = self._find_input(page, is_departure=False)
        if depart_field is None or arrivee_field is None:
            raise ValueError("Champs depart/arrivee introuvables sur viamichelin.fr")

        for field, label in ((depart_field, depart_label), (arrivee_field, arrivee_label)):
            field.click(force=True)
            field.fill("", force=True)
            field.fill(label, force=True)
            page.wait_for_timeout(1500)
            self._pick_autocomplete(page, field, label)

        self._click_calculate(page, arrivee_field)
        page.wait_for_timeout(3000)

    def _find_input(self, page: Page, *, is_departure: bool):
        ordered = (
            ("#departure", 'input[id*="departure" i]', 'input[placeholder*="part" i]')
            if is_departure
            else ("#arrival", 'input[id*="arrival" i]', 'input[placeholder*="rriv" i]')
        )
        for selector in ordered:
            loc = page.locator(selector).first
            try:
                if loc.count() > 0 and loc.is_visible(timeout=3000):
                    return loc
            except Exception:
                continue
        return None

    def __exit__(self, exc_type, *args: object) -> None:
        if exc_type is not KeyboardInterrupt and self._context:
            try:
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


def _browser_label(
    city: str,
    geo: dict[str, Any],
    department: str | None,
) -> str:
    """Libelle pour le site : ville + departement si homonyme possible."""
    name = (geo.get("formatted_name") or city).strip()
    dept = (
        geo.get("department") or department or department_for_city(city) or ""
    ).strip()
    if dept and dept.lower() not in name.lower():
        if name.lower() == city.strip().lower() or len(name) < 30:
            return f"{name}, {dept}"
    return name or geocode_search_query(city, department)


def _with_geo(
    base: RouteResult,
    *,
    depart_geo: dict[str, Any] | None = None,
    arrivee_geo: dict[str, Any] | None = None,
    distance_km: float | None = None,
    statut: str | None = None,
    message_erreur: str | None = None,
    raw_response: dict | list | None = None,
) -> RouteResult:
    dep_dept = base.depart_departement
    arr_dept = base.arrivee_departement
    if depart_geo:
        dep_dept = depart_geo.get("department") or dep_dept
    if arrivee_geo:
        arr_dept = arrivee_geo.get("department") or arr_dept
    return RouteResult(
        depart=base.depart,
        arrivee=base.arrivee,
        distance_km=distance_km if distance_km is not None else base.distance_km,
        source=base.source,
        statut=statut or base.statut,
        message_erreur=message_erreur,
        raw_response=raw_response,
        depart_lat=(depart_geo or {}).get("lat"),
        depart_lng=(depart_geo or {}).get("lng"),
        depart_zip=(depart_geo or {}).get("zip_code"),
        depart_departement=dep_dept,
        depart_formatted_name=(depart_geo or {}).get("formatted_name"),
        arrivee_lat=(arrivee_geo or {}).get("lat"),
        arrivee_lng=(arrivee_geo or {}).get("lng"),
        arrivee_zip=(arrivee_geo or {}).get("zip_code"),
        arrivee_departement=arr_dept,
        arrivee_formatted_name=(arrivee_geo or {}).get("formatted_name"),
    )
