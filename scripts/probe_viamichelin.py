"""Diagnostic ViaMichelin : endpoints, codes HTTP, latence (sans retry)."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GQL_URL = "https://bff.viamichelin.com/graphql"
VMREST_AUTH = "JSBS20110216111214120400892678"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": "https://www.viamichelin.fr",
    "Referer": "https://www.viamichelin.fr/",
}
GQL_BODY = json.loads(
    (ROOT / "data" / "viamichelin_search_address_full.json").read_text(encoding="utf-8")
)


def probe_get(url: str, label: str) -> dict:
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read(500)
            return {
                "label": label,
                "ok": True,
                "code": resp.status,
                "ms": round((time.perf_counter() - t0) * 1000),
                "snippet": body[:120].decode("utf-8", errors="replace"),
            }
    except urllib.error.HTTPError as exc:
        snippet = exc.read(300).decode("utf-8", errors="replace") if exc.fp else ""
        return {
            "label": label,
            "ok": False,
            "code": exc.code,
            "ms": round((time.perf_counter() - t0) * 1000),
            "snippet": snippet,
            "headers": dict(exc.headers.items()) if exc.headers else {},
        }
    except Exception as exc:
        return {
            "label": label,
            "ok": False,
            "code": None,
            "ms": round((time.perf_counter() - t0) * 1000),
            "snippet": str(exc),
        }


def probe_gql(city: str) -> dict:
    body = {
        "operationName": GQL_BODY["operationName"],
        "query": GQL_BODY["query"],
        "variables": {"query": city, "proximity": {"lng": 2.35, "lat": 46.6}},
    }
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(
            GQL_URL,
            data=json.dumps(body).encode(),
            headers={**HEADERS, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            items = (data.get("data") or {}).get("searchAddress") or []
            hit = items[0] if items else None
            loc = (hit or {}).get("mapLocation", {}).get("location", {})
            return {
                "label": f"GraphQL geocode '{city}'",
                "ok": bool(items),
                "code": resp.status,
                "ms": round((time.perf_counter() - t0) * 1000),
                "snippet": f"{hit.get('formattedName') if hit else 'vide'} lat={loc.get('lat')} lng={loc.get('lng')}",
            }
    except urllib.error.HTTPError as exc:
        snippet = exc.read(300).decode("utf-8", errors="replace")
        return {
            "label": f"GraphQL geocode '{city}'",
            "ok": False,
            "code": exc.code,
            "ms": round((time.perf_counter() - t0) * 1000),
            "snippet": snippet,
            "headers": dict(exc.headers.items()) if exc.headers else {},
        }
    except Exception as exc:
        return {
            "label": f"GraphQL geocode '{city}'",
            "ok": False,
            "code": None,
            "ms": round((time.perf_counter() - t0) * 1000),
            "snippet": str(exc),
        }


def probe_vmrest(lon1: float, lat1: float, lon2: float, lat2: float) -> dict:
    step_list = f"1:e:{lon1}:{lat1};1:e:{lon2}:{lat2};"
    params = {
        "distUnit": "m",
        "itit": "0",
        "veht": "0",
        "stepList": step_list,
        "data": "header",
        "lg": "fra",
        "authKey": VMREST_AUTH,
        "callback": "cb",
        "avoidTolls": "false",
    }
    url = (
        "https://vmrest.viamichelin.com/apir/10/iti.json/fra/header?"
        + urllib.parse.urlencode(params)
    )
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read(400).decode("utf-8", errors="replace")
            return {
                "label": "vmrest itineraire Paris->Lyon",
                "ok": "header" in text or "totalDist" in text,
                "code": resp.status,
                "ms": round((time.perf_counter() - t0) * 1000),
                "snippet": text[:150],
            }
    except urllib.error.HTTPError as exc:
        snippet = exc.read(300).decode("utf-8", errors="replace")
        return {
            "label": "vmrest itineraire Paris->Lyon",
            "ok": False,
            "code": exc.code,
            "ms": round((time.perf_counter() - t0) * 1000),
            "snippet": snippet,
            "headers": dict(exc.headers.items()) if exc.headers else {},
        }
    except Exception as exc:
        return {
            "label": "vmrest itineraire Paris->Lyon",
            "ok": False,
            "code": None,
            "ms": round((time.perf_counter() - t0) * 1000),
            "snippet": str(exc),
        }


def print_result(r: dict) -> None:
    status = "OK" if r.get("ok") else "FAIL"
    code = r.get("code") if r.get("code") is not None else "—"
    print(f"[{status}] {r['label']}")
    print(f"       HTTP {code}  {r['ms']} ms")
    print(f"       {r['snippet'][:200]}")
    hdrs = r.get("headers") or {}
    for k in ("server", "x-cache", "cf-ray", "retry-after", "date"):
        if k in hdrs:
            print(f"       {k}: {hdrs[k]}")
    print()


def main() -> int:
    print("=== Probe ViaMichelin", time.strftime("%Y-%m-%d %H:%M:%S"), "===\n")

    for url, label in [
        ("https://www.viamichelin.fr/", "Site www.viamichelin.fr"),
        ("https://bff.viamichelin.com/", "Host bff.viamichelin.com"),
        ("https://vmrest.viamichelin.com/", "Host vmrest.viamichelin.com"),
    ]:
        print_result(probe_get(url, label))

    gql = probe_gql("Paris")
    print_result(gql)

    if gql.get("ok"):
        # coords Paris centre approx from last gql - re-fetch Lyon
        gql2 = probe_gql("Lyon")
        print_result(gql2)
        # use known coords if gql fails partially
        paris = (2.3522, 48.8566)
        lyon = (4.8357, 45.7640)
        print_result(probe_vmrest(paris[0], paris[1], lyon[0], lyon[1]))

    print("=== 3 appels GraphQL consecutifs (charge legere) ===")
    ok = 0
    for i in range(3):
        r = probe_gql(f"Test{i} Melun")
        print_result(r)
        if r.get("ok"):
            ok += 1
        time.sleep(1)
    print(f"Succes: {ok}/3\n")

    print("=== Via fetch_route_viamichelin (module projet) ===")
    from src.scraper.viamichelin_api import fetch_route_viamichelin

    t0 = time.perf_counter()
    result = fetch_route_viamichelin("Melun", "Paris")
    ms = round((time.perf_counter() - t0) * 1000)
    print(f"statut={result.statut} km={result.distance_km} ({ms} ms)")
    if result.message_erreur:
        print(f"erreur: {result.message_erreur[:300]}")

    return 0 if result.statut == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
