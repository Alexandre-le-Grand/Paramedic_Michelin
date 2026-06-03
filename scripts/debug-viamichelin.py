"""Test vmrest direct avec coords GraphQL."""
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.extract import extract_from_api_payload
from src.scraper.viamichelin import ITINERAIRES_URL, _dismiss_didomi
from playwright.sync_api import sync_playwright

GQL_URL = "https://bff.viamichelin.com/graphql"
PROXIMITY = {"lng": 2.3522, "lat": 46.6034}  # centre FR
AUTH_KEY = "JSBS20110216111214120400892678"

SEARCH_QUERY = Path(ROOT / "data" / "debug_gql_request.txt").read_text(encoding="utf-8")
SEARCH_BODY = json.loads(SEARCH_QUERY)


def search_city(page, city: str) -> tuple[float, float]:
    body = {
        "operationName": "SearchAddress",
        "query": SEARCH_BODY["query"],
        "variables": {"query": city, "proximity": PROXIMITY},
    }
    result = page.evaluate(
        """async ({url, body}) => {
            const r = await fetch(url, {
                method: 'POST',
                headers: {'content-type': 'application/json'},
                body: JSON.stringify(body),
                credentials: 'include'
            });
            return r.json();
        }""",
        {"url": GQL_URL, "body": body},
    )
    items = (result.get("data") or {}).get("searchAddress") or []
    if not items:
        raise ValueError(f"Pas de resultat pour {city}")
    loc = items[0]["mapLocation"]["location"]
    return float(loc["lng"]), float(loc["lat"])


def fetch_itinerary(lon1, lat1, lon2, lat2) -> dict:
    step_list = f"1:e:{lon1}:{lat1};1:e:{lon2}:{lat2};"
    params = {
        "distUnit": "m",
        "itit": "0",
        "veht": "0",
        "stepList": step_list,
        "avoidExpressWays": "false",
        "avoidTolls": "false",
        "data": "header",
        "lg": "fra",
        "authKey": AUTH_KEY,
        "callback": "cb",
    }
    url = (
        "https://vmrest.viamichelin.com/apir/10/iti.json/fra/header?"
        + urllib.parse.urlencode(params)
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    text = urllib.request.urlopen(req, timeout=30).read().decode()
    if text.startswith("cb("):
        text = text[3:-1]
    return json.loads(text)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page()
    page.goto(ITINERAIRES_URL)
    _dismiss_didomi(page)
    lon1, lat1 = search_city(page, "Paris")
    lon2, lat2 = search_city(page, "Lyon")
    print("coords", lon1, lat1, lon2, lat2)
    data = fetch_itinerary(lon1, lat1, lon2, lat2)
    km, mins = extract_from_api_payload(data)
    print("result", km, mins)
    (ROOT / "data" / "debug_vmrest.json").write_text(
        json.dumps(data, indent=2)[:200000], encoding="utf-8"
    )
    browser.close()
