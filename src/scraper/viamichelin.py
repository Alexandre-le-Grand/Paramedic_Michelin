"""Scraping ViaMichelin avec Playwright (Microsoft Edge recommande)."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Page, sync_playwright

from config.settings import BROWSER_CHANNEL, HEADLESS
from src.extract import (
    MIN_ROUTE_KM,
    extract_duration_from_page_text,
    extract_from_api_payload,
    extract_km_from_page_text,
    is_plausible_route_km,
)


@dataclass
class RouteResult:
    depart: str
    arrivee: str
    distance_km: float | None
    duree_minutes: int | None
    source: str
    statut: str
    message_erreur: str | None
    raw_response: dict | list | None


URL = "https://www.viamichelin.fr/itineraires"


def _parse_jsonp(text: str) -> dict | list:
    text = text.strip()
    if "(" in text and text.endswith(")"):
        text = text[text.index("(") + 1 : -1]
    return json.loads(text)


def _accept_cookies(page: Page) -> None:
    btn = page.locator("#didomi-notice-agree-button")
    if btn.count():
        btn.click(force=True, timeout=5000)
    try:
        page.wait_for_selector("#didomi-popup", state="hidden", timeout=20000)
    except Exception:
        pass
    page.locator("#departure").wait_for(state="visible", timeout=20000)
    page.wait_for_function(
        "() => { const el = document.querySelector('#departure'); return el && !el.disabled; }",
        timeout=20000,
    )


def _fill_place(page: Page, selector: str, value: str) -> None:
    field = page.locator(selector)
    field.click(force=True)
    field.fill(value, force=True)
    page.wait_for_timeout(2500)
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    page.wait_for_timeout(1000)


def fetch_route(depart: str, arrivee: str) -> RouteResult:
    captured: list[dict | list] = []

    def on_response(response) -> None:
        if "vmrest" not in response.url or response.status != 200:
            return
        try:
            body = response.text()
            if body and ("iti" in response.url or "route" in response.url):
                captured.append(_parse_jsonp(body))
        except Exception:
            pass

    launch_kwargs: dict[str, Any] = {
        "headless": HEADLESS,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if BROWSER_CHANNEL:
        launch_kwargs["channel"] = BROWSER_CHANNEL

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            locale="fr-FR",
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
            ),
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()
        page.on("response", on_response)

        page.goto(URL, wait_until="domcontentloaded", timeout=120000)
        _accept_cookies(page)
        _fill_place(page, "#departure", depart)
        _fill_place(page, "#arrival", arrivee)

        page.get_by_role("button", name=re.compile("Rechercher", re.I)).first.click(
            force=True
        )
        page.wait_for_load_state("networkidle", timeout=120000)

        body_text = page.inner_text("body")
        deadline = time.time() + 60
        route_ready = False
        while time.time() < deadline and not route_ready:
            for payload in captured:
                km, _ = extract_from_api_payload(payload)
                if is_plausible_route_km(km):
                    route_ready = True
                    break
            if not route_ready:
                body_text = page.inner_text("body")
                if is_plausible_route_km(extract_km_from_page_text(body_text)):
                    route_ready = True
            if not route_ready:
                page.wait_for_timeout(2000)

        browser.close()

    distance_km: float | None = None
    duree_minutes: int | None = None
    raw: dict | list | None = None

    for payload in captured:
        km, mins = extract_from_api_payload(payload)
        if km:
            distance_km = km
        if mins:
            duree_minutes = mins
        raw = payload

    if distance_km is None:
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
            message_erreur=(
                f"Distance incoherente ({distance_km} km) : "
                f"itineraire non charge (attendu >= {MIN_ROUTE_KM} km). "
                "Essayez HEADLESS=false dans .env ou le repli OSRM."
            ),
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