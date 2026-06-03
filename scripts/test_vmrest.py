import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.extract import extract_from_api_payload

AUTH_KEY = "JSBS20110216111214120400892678"
GQL_BODY = json.loads((ROOT / "data" / "debug_gql_request.txt").read_text())


def search_city(city: str) -> tuple[float, float]:
    body = {
        "operationName": GQL_BODY["operationName"],
        "query": GQL_BODY["query"],
        "variables": {"query": city, "proximity": {"lng": 2.35, "lat": 46.6}},
    }
    req = urllib.request.Request(
        "https://bff.viamichelin.com/graphql",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://www.viamichelin.fr",
            "Referer": "https://www.viamichelin.fr/",
        },
    )
    data = json.loads(urllib.request.urlopen(req, timeout=30).read())
    loc = data["data"]["searchAddress"][0]["mapLocation"]["location"]
    return float(loc["lng"]), float(loc["lat"])


def fetch_itinerary(lon1: float, lat1: float, lon2: float, lat2: float) -> dict:
    step_list = f"1:e:{lon1}:{lat1};1:e:{lon2}:{lat2};"
    params = {
        "distUnit": "m",
        "itit": "0",
        "veht": "0",
        "stepList": step_list,
        "data": "header",
        "lg": "fra",
        "authKey": AUTH_KEY,
        "callback": "cb",
    }
    url = (
        "https://vmrest.viamichelin.com/apir/10/iti.json/fra/header?"
        + urllib.parse.urlencode(params)
    )
    text = urllib.request.urlopen(
        urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.viamichelin.fr/",
            },
        ),
        timeout=30,
    ).read().decode()

    if text.strip().startswith("{"):
        return json.loads(text)

    match = re.search(r"cb\((\{.*\})\)", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    start = text.find('{"header"')
    if start >= 0:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : i + 1])
    raise ValueError(f"Reponse vmrest illisible: {text[:200]}")


if __name__ == "__main__":
    lon1, lat1 = search_city("Paris")
    lon2, lat2 = search_city("Lyon")
    print("coords", lon1, lat1, "->", lon2, lat2)
    payload = fetch_itinerary(lon1, lat1, lon2, lat2)
    print("extract", extract_from_api_payload(payload))
