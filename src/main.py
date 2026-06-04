"""
Paramedic Michelin — ViaMichelin + SQL + MongoDB.

Usage:
    run.cmd run --limit 10
    run.cmd test Paris Lyon
    run.cmd list-sql
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from config.settings import BROWSER_HEADLESS, SCRAPE_DELAY_SECONDS, TRAJETS_SOURCE
except ModuleNotFoundError as exc:
    if exc.name in ("dotenv", "python_dotenv"):
        print(
            "Dependances absentes pour ce Python.\n"
            "  Utilisez :  run.cmd run --limit 10\n"
            "  Ou :        .venv\\Scripts\\python.exe src\\main.py run --limit 10"
        )
        sys.exit(1)
    raise
from src.db.mongo_repository import MongoRepository
from src.db.sql_repository import SqlRepository
from src.db.transports_repository import TransportsRepository
from src.models import RouteResult
from src.route_pairs import dedupe_bidirectional
from src.scraper.viamichelin import ViaMichelinScraper
from src.scraper.viamichelin_api import (
    coords_from_hit,
    fetch_itinerary_vmrest,
    fetch_route_viamichelin,
    search_addresses,
)


def load_trajets(source: str, csv_path: Path, limit: int | None) -> list[tuple[str, str]]:
    if source == "transports":
        repo = TransportsRepository()
        try:
            total = repo.count_documents()
            if total == 0:
                print(
                    "La collection paramedic.transports est vide.\n"
                    "  1. docker compose up -d\n"
                    "  2. .\\scripts\\restore-transports.ps1\n"
                    "Ou utilisez --source csv pour data/trajets.csv"
                )
                return []
            routes = repo.load_unique_routes(limit=limit)
            print(
                f"Source MongoDB paramedic.transports : "
                f"{total} transports, {len(routes)} paires uniques a scraper "
                f"(aller-retour fusionnes : ex. Paris-Bordeaux = Bordeaux-Paris)."
            )
            return routes
        finally:
            repo.close()
    return load_trajets_csv(csv_path, limit=limit)


def load_trajets_csv(path: Path, limit: int | None = None) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            depart = (row.get("depart") or row.get("departure") or "").strip()
            arrivee = (row.get("arrivee") or row.get("arrival") or "").strip()
            if depart and arrivee:
                rows.append((depart, arrivee))
    routes, skipped = dedupe_bidirectional(rows)
    if skipped:
        print(
            f"CSV : {skipped} ligne(s) ignoree(s) (meme trajet que l'inverse deja present)."
        )
    if limit is not None and limit > 0:
        return routes[:limit]
    return routes


def result_to_record(result: RouteResult) -> dict:
    return {
        "depart": result.depart,
        "arrivee": result.arrivee,
        "distance_km": result.distance_km,
        "duree_minutes": result.duree_minutes,
        "source": result.source,
        "statut": result.statut,
        "message_erreur": result.message_erreur,
        "raw_response": result.raw_response,
        "depart_lat": result.depart_lat,
        "depart_lng": result.depart_lng,
        "depart_zip": result.depart_zip,
        "arrivee_lat": result.arrivee_lat,
        "arrivee_lng": result.arrivee_lng,
        "arrivee_zip": result.arrivee_zip,
        "scraped_at": datetime.now(timezone.utc),
    }


def _print_geo(label: str, lat: float | None, lng: float | None, zip_code: str | None) -> None:
    parts: list[str] = []
    if lat is not None and lng is not None:
        parts.append(f"lat={lat}, lng={lng}")
    if zip_code:
        parts.append(f"CP={zip_code}")
    if parts:
        print(f"  {label}: {', '.join(parts)}")


def _print_result(depart: str, arrivee: str, result: RouteResult) -> dict:
    print(f"\nTrajet: {depart} -> {arrivee}")
    _print_geo("Depart", result.depart_lat, result.depart_lng, result.depart_zip)
    _print_geo("Arrivee", result.arrivee_lat, result.arrivee_lng, result.arrivee_zip)
    record = result_to_record(result)
    print(
        f"  -> {record.get('distance_km')} km, "
        f"{record.get('duree_minutes')} min | "
        f"source={record['source']} | statut={record['statut']}"
    )
    if result.statut == "erreur" and result.message_erreur:
        print(f"  -> {result.message_erreur}")
    return record


def _resolve_workers(args: argparse.Namespace, use_browser: bool) -> int:
    from config.settings import SCRAPE_WORKERS

    if use_browser:
        return 1
    if getattr(args, "workers", None) is not None:
        return max(1, min(10, args.workers))
    return SCRAPE_WORKERS


def _run_parallel_api(
    trajets: list[tuple[str, str]],
    *,
    avoid_tolls: bool,
    workers: int,
    sql_repo: SqlRepository,
    mongo_repo: MongoRepository,
) -> None:
    db_lock = threading.Lock()
    total = len(trajets)
    done = 0
    errors = 0
    t0 = time.perf_counter()

    def _task(pair: tuple[str, str]) -> tuple[str, str, RouteResult]:
        depart, arrivee = pair
        result = fetch_route_viamichelin(
            depart, arrivee, avoid_tolls=avoid_tolls
        )
        return depart, arrivee, result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_task, pair) for pair in trajets]
        for future in as_completed(futures):
            depart, arrivee, result = future.result()
            with db_lock:
                record = _print_result(depart, arrivee, result)
                sql_id = sql_repo.insert_trajet(record)
                mongo_id = mongo_repo.insert_trajet(record)
                print(f"  Enregistre: SQL id={sql_id}, MongoDB id={mongo_id}")
                done += 1
                if result.statut == "erreur":
                    errors += 1

    elapsed = time.perf_counter() - t0
    print(
        f"\nParallele ({workers} workers) : {done} trajets en {elapsed:.1f}s "
        f"({done / elapsed:.2f}/s), {errors} erreur(s)."
    )


def cmd_run(args: argparse.Namespace) -> None:
    limit = args.limit if args.limit and args.limit > 0 else None
    trajets = load_trajets(args.source, Path(args.csv), limit=limit)
    if not trajets:
        print("Aucun trajet a traiter.")
        return

    use_browser = args.visible
    if use_browser:
        headless = BROWSER_HEADLESS if not args.visible else False
    else:
        headless = True

    from config.settings import VIAMICHELIN_AVOID_TOLLS

    avoid_tolls = False if args.avec_peages else VIAMICHELIN_AVOID_TOLLS
    workers = _resolve_workers(args, use_browser)
    peages_label = "sans peages" if avoid_tolls else "avec peages (trajet normal)"
    mode_label = f"{workers} requete(s) en parallele" if workers > 1 else "sequentiel"
    print(f"Calcul ViaMichelin ({peages_label}, {mode_label}) — SQL + MongoDB")
    sql_repo = SqlRepository()
    mongo_repo = MongoRepository()
    mongo_repo.ping()

    if not use_browser and workers > 1:
        print("ViaMichelin API (GraphQL + vmrest) — sans navigateur")
        _run_parallel_api(
            trajets,
            avoid_tolls=avoid_tolls,
            workers=workers,
            sql_repo=sql_repo,
            mongo_repo=mongo_repo,
        )
    else:
        if use_browser and getattr(args, "workers", None) not in (None, 1):
            print("Note : --workers ignore en mode --visible (navigateur sequentiel).")
        with ViaMichelinScraper(
            headless=headless,
            use_browser=use_browser,
            avoid_tolls=avoid_tolls,
        ) as scraper:
            for i, (depart, arrivee) in enumerate(trajets):
                result = scraper.fetch_route(depart, arrivee)
                record = _print_result(depart, arrivee, result)
                sql_id = sql_repo.insert_trajet(record)
                mongo_id = mongo_repo.insert_trajet(record)
                print(f"  Enregistre: SQL id={sql_id}, MongoDB id={mongo_id}")
                if i < len(trajets) - 1 and SCRAPE_DELAY_SECONDS > 0:
                    time.sleep(SCRAPE_DELAY_SECONDS)

    mongo_repo.close()
    print("\nTermine.")


def cmd_list_sql(args: argparse.Namespace) -> None:
    for row in SqlRepository().list_trajets(limit=args.limit):
        print(row)


def _format_hit_summary(hit: dict) -> dict:
    address = hit.get("address") or {}
    loc = (hit.get("mapLocation") or {}).get("location") or {}
    return {
        "score": hit.get("score"),
        "formattedName": hit.get("formattedName"),
        "contextualizedName": hit.get("contextualizedName"),
        "entityType": hit.get("entityType"),
        "city": address.get("city"),
        "department": address.get("department"),
        "region": address.get("region"),
        "country": (address.get("country") or {}).get("code"),
        "zipCode": address.get("zipCode"),
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
        "geometryId": (hit.get("mapLocation") or {}).get("geometryId"),
    }


def _print_geocode_section(label: str, query: str, hits: list[dict], used_index: int) -> None:
    print(f"\n{'=' * 60}")
    print(f"{label} : \"{query}\"")
    print(f"{'=' * 60}")
    for i, hit in enumerate(hits, start=1):
        summary = _format_hit_summary(hit)
        marker = "  <-- utilise pour l'itineraire" if i - 1 == used_index else ""
        print(f"\n[{i}] score={summary['score']} | {summary['formattedName']} ({summary['entityType']}){marker}")
        if summary.get("contextualizedName"):
            print(f"    Contexte : {summary['contextualizedName']}")
        parts = [p for p in (summary.get("city"), summary.get("department"), summary.get("region")) if p]
        if parts:
            print(f"    Localite : {', '.join(parts)}")
        if summary.get("zipCode"):
            print(f"    CP       : {summary['zipCode']}")
        if summary.get("country"):
            print(f"    Pays     : {summary['country']}")
        if summary.get("lat") is not None and summary.get("lng") is not None:
            print(f"    Lat/Lng  : {summary['lat']}, {summary['lng']}")
        if summary.get("geometryId"):
            print(f"    Geometry : {summary['geometryId']}")


def _print_itinerary_section(
    distance_km: float | None,
    duree_minutes: int | None,
    *,
    avoid_tolls: bool,
    raw_response: dict | list | None,
) -> None:
    print(f"\n{'=' * 60}")
    print("ITINERAIRE")
    print(f"{'=' * 60}")
    peages = "sans peages" if avoid_tolls else "avec peages (trajet normal)"
    print(f"  Option   : {peages}")
    print(f"  Distance : {distance_km} km" if distance_km is not None else "  Distance : (absente)")
    if duree_minutes is not None:
        h, m = divmod(duree_minutes, 60)
        duree_label = f"{duree_minutes} min"
        if h:
            duree_label += f" ({h}h{m:02d})"
        print(f"  Duree    : {duree_label}")
    else:
        print("  Duree    : (absente)")
    if raw_response:
        print("\n  Reponse vmrest (extrait header/summary) :")
        print(json.dumps(raw_response, indent=2, ensure_ascii=False)[:8000])


def _build_test_payload(
    *,
    depart: str,
    arrivee: str,
    avoid_tolls: bool,
    depart_hits: list[dict],
    arrivee_hits: list[dict],
    distance_km: float | None,
    duree_minutes: int | None,
    raw_response: dict | list | None,
    include_raw: bool,
) -> dict:
    payload = {
        "depart_query": depart,
        "arrivee_query": arrivee,
        "avoid_tolls": avoid_tolls,
        "depart_hits": [_format_hit_summary(h) for h in depart_hits],
        "arrivee_hits": [_format_hit_summary(h) for h in arrivee_hits],
        "depart_used": _format_hit_summary(depart_hits[0]),
        "arrivee_used": _format_hit_summary(arrivee_hits[0]),
        "itinerary": {
            "distance_km": distance_km,
            "duree_minutes": duree_minutes,
        },
    }
    if include_raw and raw_response is not None:
        payload["itinerary"]["raw_response"] = raw_response
    return payload


def cmd_test(args: argparse.Namespace) -> None:
    from config.settings import VIAMICHELIN_AVOID_TOLLS
    from src.extract import extract_from_api_payload

    depart = args.depart.strip()
    arrivee = args.arrivee.strip()
    avoid_tolls = False if args.avec_peages else VIAMICHELIN_AVOID_TOLLS
    max_hits = max(1, args.hits)

    try:
        depart_hits = search_addresses(depart)[:max_hits]
        arrivee_hits = search_addresses(arrivee)[:max_hits]
    except ValueError as exc:
        print(f"Erreur geocodage : {exc}")
        sys.exit(1)

    lon1, lat1 = coords_from_hit(depart_hits[0])
    lon2, lat2 = coords_from_hit(arrivee_hits[0])

    try:
        raw_response = fetch_itinerary_vmrest(
            lon1, lat1, lon2, lat2, avoid_tolls=avoid_tolls
        )
        distance_km, duree_minutes = extract_from_api_payload(raw_response)
    except Exception as exc:
        print(f"Erreur itineraire : {exc}")
        sys.exit(1)

    if args.json or args.out:
        payload = _build_test_payload(
            depart=depart,
            arrivee=arrivee,
            avoid_tolls=avoid_tolls,
            depart_hits=depart_hits,
            arrivee_hits=arrivee_hits,
            distance_km=distance_km,
            duree_minutes=duree_minutes,
            raw_response=raw_response,
            include_raw=not args.compact,
        )
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text + "\n", encoding="utf-8")
            print(f"JSON ecrit : {out_path.resolve()}")
        if args.json or not args.out:
            print(text)
        return

    print("ViaMichelin — test (aucune ecriture en base)")
    _print_geocode_section("DEPART", depart, depart_hits, used_index=0)
    _print_geocode_section("ARRIVEE", arrivee, arrivee_hits, used_index=0)
    _print_itinerary_section(
        distance_km,
        duree_minutes,
        avoid_tolls=avoid_tolls,
        raw_response=raw_response,
    )
    print("\n(JSON : --json ou --out data/test_trajet.json)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ViaMichelin -> SQLite + MongoDB"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Calculer les trajets (CSV ou base transports)")
    run_p.add_argument(
        "--source",
        choices=("csv", "transports"),
        default=TRAJETS_SOURCE,
        help="transports = paramedic.transports (defaut) | csv = data/trajets.csv",
    )
    run_p.add_argument("--csv", default="data/trajets.csv")
    run_p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Nombre max de trajets (0 = tout). Utile avec --source transports.",
    )
    run_p.add_argument(
        "--visible",
        action="store_true",
        help="Utiliser le navigateur Edge (lent ; defaut = API ViaMichelin)",
    )
    run_p.add_argument(
        "--avec-peages",
        action="store_true",
        help="Itineraire normal (autoroutes a peage). Defaut : sans peages.",
    )
    run_p.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Requetes API en parallele (1-10, defaut SCRAPE_WORKERS=5). Ignore avec --visible.",
    )
    run_p.set_defaults(func=cmd_run)

    list_p = sub.add_parser("list-sql", help="Afficher les trajets en SQL")
    list_p.add_argument("--limit", type=int, default=20)
    list_p.set_defaults(func=cmd_list_sql)

    test_p = sub.add_parser(
        "test",
        help="Tester un trajet (geocodage + itineraire, sans enregistrement)",
    )
    test_p.add_argument("depart", help="Ville ou adresse de depart")
    test_p.add_argument("arrivee", help="Ville ou adresse d'arrivee")
    test_p.add_argument(
        "--avec-peages",
        action="store_true",
        help="Itineraire normal (autoroutes a peage). Defaut : sans peages.",
    )
    test_p.add_argument(
        "--hits",
        type=int,
        default=5,
        metavar="N",
        help="Nombre de resultats geocodage affiches par point (defaut 5).",
    )
    test_p.add_argument(
        "--json",
        action="store_true",
        help="Afficher le JSON dans le terminal.",
    )
    test_p.add_argument(
        "--out",
        metavar="FICHIER",
        help="Ecrire le JSON dans un fichier (ex. data/test_trajet.json).",
    )
    test_p.add_argument(
        "--compact",
        action="store_true",
        help="JSON sans raw_response vmrest (geocodage + km/min seulement).",
    )
    test_p.set_defaults(func=cmd_test)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
