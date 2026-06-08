"""Playwright : charger ViaMichelin et lister les appels reseau API."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

URL = "https://www.viamichelin.fr/itineraires?departure=Melun&arrival=Paris"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page()
    calls: list[tuple[int, str]] = []

    def on_resp(resp):
        u = resp.url
        if any(x in u for x in ("michelin", "graphql", "vmrest", "iti.json")):
            calls.append((resp.status, u))

    page.on("response", on_resp)
    try:
        page.goto(URL, wait_until="networkidle", timeout=90000)
    except Exception as exc:
        print("goto:", exc)
    page.wait_for_timeout(8000)

    title = page.title()
    print("title:", title)
    print("calls:", len(calls))
    for status, url in sorted(calls, key=lambda x: x[1]):
        print(f"  {status} {url[:150]}")

    vmrest = [c for c in calls if "vmrest" in c[1] or "iti.json" in c[1]]
    gql = [c for c in calls if "graphql" in c[1]]
    print(f"\nvmrest/iti: {len(vmrest)}")
    for c in vmrest:
        print(" ", c)
    print(f"graphql: {len(gql)}")
    for c in gql[:5]:
        print(" ", c)

    browser.close()
