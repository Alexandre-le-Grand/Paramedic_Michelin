"""
Paramedic Michelin — ViaMichelin + MongoDB.

Usage:
    run.cmd clean-mongo
    run.cmd seed-mongo
    run.cmd run --source mongo --osrm               # secours OSRM si vmrest 503
    run.cmd run --source mongo --browser            # tout via site web (headless)
    run.cmd clean-bad-mongo                         # effacer km navigateur douteux
    run.cmd test Paris Lyon
    run.cmd list-mongo
    run.cmd monitor
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from config.settings import (
        BROWSER_HEADLESS,
        SCRAPE_BROWSER_FALLBACK,
        SCRAPE_DELAY_SECONDS,
        SCRAPE_OSRM_FALLBACK,
        TRAJETS_SOURCE,
    )
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
from src.city_departments import department_for_city, geocode_search_query
from src.models import RouteResult
from src.route_pair import RoutePair
from src.route_pairs import dedupe_bidirectional
from src.scraper.browser_fallback import BrowserFallbackPool
from src.scraper.route_fetch import fetch_route_with_fallback
from src.scraper.viamichelin import ViaMichelinScraper
from src.scraper.viamichelin_api import (
    coords_from_hit,
    fetch_itinerary_graphql,
    fetch_itinerary_vmrest,
    fetch_route_viamichelin,
    is_transient_api_error,
    search_addresses,
)


def load_trajets(
    source: str,
    csv_path: Path,
    limit: int | None,
    *,
    mongo_repo: MongoRepository | None = None,
) -> list[tuple[str, str]]:
    if source == "mongo":
        repo = mongo_repo or MongoRepository()
        own_repo = mongo_repo is None
        try:
            pairs = repo.load_pending_pairs(limit=limit)
            print(
                f"Source MongoDB {repo.db.name}.{repo.collection.name} : "
                f"{len(pairs)} a calculer, {repo.count_ok()} deja ok, "
                f"{repo.count_pending()} en attente au total."
            )
            return pairs
        finally:
            if own_repo:
                repo.close()
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
        "source": result.source,
        "statut": result.statut,
        "message_erreur": result.message_erreur,
        "raw_response": result.raw_response,
        "depart_lat": result.depart_lat,
        "depart_lng": result.depart_lng,
        "depart_zip": result.depart_zip,
        "depart_departement": result.depart_departement,
        "depart_formatted_name": result.depart_formatted_name,
        "arrivee_lat": result.arrivee_lat,
        "arrivee_lng": result.arrivee_lng,
        "arrivee_zip": result.arrivee_zip,
        "arrivee_departement": result.arrivee_departement,
        "arrivee_formatted_name": result.arrivee_formatted_name,
        "scraped_at": datetime.now(timezone.utc),
    }


def _print_geo(
    label: str,
    lat: float | None,
    lng: float | None,
    zip_code: str | None,
    formatted_name: str | None = None,
    department: str | None = None,
) -> None:
    if formatted_name:
        print(f"  {label}: {formatted_name}")
    parts: list[str] = []
    if lat is not None and lng is not None:
        parts.append(f"lat={lat}, lng={lng}")
    if zip_code:
        parts.append(f"CP={zip_code}")
    if department:
        parts.append(f"dept={department}")
    if parts:
        print(f"  {label} (geo): {', '.join(parts)}")


def _print_result(depart: str, arrivee: str, result: RouteResult) -> dict:
    print(f"\nTrajet: {depart} -> {arrivee}")
    _print_geo(
        "Depart",
        result.depart_lat,
        result.depart_lng,
        result.depart_zip,
        result.depart_formatted_name,
        result.depart_departement,
    )
    _print_geo(
        "Arrivee",
        result.arrivee_lat,
        result.arrivee_lng,
        result.arrivee_zip,
        result.arrivee_formatted_name,
        result.arrivee_departement,
    )
    record = result_to_record(result)
    print(
        f"  -> {record.get('distance_km')} km | "
        f"source={record['source']} | statut={record['statut']}"
    )
    if result.statut == "erreur" and result.message_erreur:
        print(f"  -> {result.message_erreur}")
    return record


def _existing_ok_pairs(mongo_repo: MongoRepository) -> set[tuple[str, str]]:
    return mongo_repo.existing_ok_pairs()


def _filter_pending_trajets(
    trajets: list[tuple[str, str]], existing: set[tuple[str, str]]
) -> tuple[list[tuple[str, str]], int]:
    if not existing:
        return trajets, 0
    pending: list[tuple[str, str]] = []
    skipped = 0
    for pair in trajets:
        if pair in existing:
            skipped += 1
        else:
            pending.append(pair)
    return pending, skipped


def _resolve_workers(args: argparse.Namespace, use_browser: bool) -> int:
    from config.settings import SCRAPE_WORKERS

    if use_browser:
        return 1
    if getattr(args, "workers", None) is not None:
        return max(1, min(10, args.workers))
    return SCRAPE_WORKERS


def _persist_result(
    depart: str,
    arrivee: str,
    result: RouteResult,
    *,
    mongo_repo: MongoRepository,
    sql_repo: SqlRepository | None = None,
) -> bool:
    """Enregistre en MongoDB (upsert). Retourne False si pas de km valide."""
    _print_result(depart, arrivee, result)
    if result.statut != "ok" or result.distance_km is None:
        if is_transient_api_error(result.message_erreur):
            print(
                "  -> Non enregistre (serveur ViaMichelin sature) — "
                "relancer le run plus tard."
            )
        else:
            print("  -> Non enregistre (pas de km valide).")
        return False
    record = result_to_record(result)
    mongo_id = mongo_repo.upsert_trajet(record)
    if sql_repo is not None:
        sql_id = sql_repo.insert_trajet(record)
        print(f"  Enregistre: MongoDB id={mongo_id}, SQL id={sql_id}")
    else:
        print(f"  Enregistre: MongoDB id={mongo_id}")
    return True


def _run_parallel_api(
    routes: list[RoutePair],
    *,
    workers: int,
    mongo_repo: MongoRepository,
    sql_repo: SqlRepository | None = None,
    osrm_fallback: bool = False,
) -> None:
    db_lock = threading.Lock()
    total = len(routes)
    done = 0
    errors = 0
    osrm_ok = 0
    t0 = time.perf_counter()

    def _task(route: RoutePair) -> tuple[str, str, RouteResult]:
        result = fetch_route_with_fallback(
            route,
            osrm_fallback=osrm_fallback,
            browser_pool=None,
        )
        return route.depart, route.arrivee, result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_task, route) for route in routes]
        for future in as_completed(futures):
            depart, arrivee, result = future.result()
            with db_lock:
                _persist_result(
                    depart, arrivee, result,
                    mongo_repo=mongo_repo, sql_repo=sql_repo,
                )
                done += 1
                if result.statut == "erreur":
                    errors += 1
                if result.source == "osrm" and result.statut == "ok":
                    osrm_ok += 1

    elapsed = time.perf_counter() - t0
    msg = (
        f"\nParallele ({workers} workers) : {done} trajets en {elapsed:.1f}s "
        f"({done / elapsed:.2f}/s), {errors} erreur(s)."
    )
    if osrm_ok:
        msg += f" {osrm_ok} via OSRM (secours)."
    print(msg)


def cmd_run(args: argparse.Namespace) -> None:
    limit = args.limit if args.limit and args.limit > 0 else None
    mongo_repo = MongoRepository()
    mongo_repo.ping()
    sql_repo = SqlRepository() if getattr(args, "also_sql", False) else None

    if args.source == "mongo":
        routes = mongo_repo.load_pending_routes(limit=limit)
        print(
            f"Source MongoDB {mongo_repo.db.name}.{mongo_repo.collection.name} : "
            f"{len(routes)} a calculer, {mongo_repo.count_ok()} deja ok, "
            f"{mongo_repo.count_pending()} en attente au total."
        )
    else:
        pairs = load_trajets(
            args.source, Path(args.csv), limit=limit, mongo_repo=mongo_repo
        )
        routes = [RoutePair.from_cities(d, a) for d, a in pairs]

    if not routes:
        if args.source == "mongo":
            print(
                "Aucun trajet en attente dans MongoDB. "
                "Lancez : seed-mongo puis run --source mongo"
            )
        else:
            print("Aucun trajet a traiter.")
        mongo_repo.close()
        return

    use_browser = getattr(args, "browser", False) or args.visible
    osrm_fallback = getattr(args, "osrm", False) or SCRAPE_OSRM_FALLBACK
    browser_fallback = getattr(args, "browser_fallback", False) or SCRAPE_BROWSER_FALLBACK
    if use_browser:
        headless = not args.visible
        browser_fallback = False
        osrm_fallback = False
    else:
        headless = True

    workers = _resolve_workers(args, use_browser)
    if browser_fallback and workers > 1:
        print(
            f"Note : --browser-fallback impose le mode sequentiel "
            f"(Playwright incompatible avec {workers} workers)."
        )
        workers = 1
    mode_label = f"{workers} requete(s) en parallele" if workers > 1 else "sequentiel"
    dest = "MongoDB" + (" + SQL" if sql_repo else "")
    print(f"Calcul distances ({mode_label}) — {dest}")
    if osrm_fallback:
        print(
            "Secours OSRM : si ViaMichelin vmrest en 503, distance via "
            "router.project-osrm.org (geocodage ViaMichelin)."
        )
    if use_browser:
        nav_mode = "fenetre visible" if not headless else "headless"
        print(f"ViaMichelin navigateur ({nav_mode}) — site web uniquement, sans API vmrest.")
        if headless:
            print(
                "Note : Michelin bloque souvent le headless (Service unavailable). "
                "Si echec, essayez --visible ou attendez le retour de l'API."
            )
    elif browser_fallback:
        print(
            "Secours navigateur : sequentiel, apres OSRM si active (lent, peu fiable si vmrest HS)."
        )
        if not osrm_fallback:
            print(
                "Astuce : si vmrest est en 503, preferez --osrm plutot que --browser-fallback."
            )

    total_loaded = len(routes)
    if args.source != "mongo" and not getattr(args, "force", False):
        existing = _existing_ok_pairs(mongo_repo)
        pending = [r for r in routes if r.as_tuple() not in existing]
        skipped = total_loaded - len(pending)
        routes = pending
        if skipped:
            print(
                f"Reprise : {skipped} couple(s) deja en MongoDB (ok) — ignores "
                f"({len(routes)} restant(s) sur {total_loaded})."
            )
        if not routes:
            print("Rien a scraper : tous les couples ont deja leurs km en MongoDB.")
            mongo_repo.close()
            return
    elif getattr(args, "force", False) and total_loaded:
        print(f"Mode --force : re-scraping de {total_loaded} couple(s).")

    if not use_browser and workers > 1:
        print("ViaMichelin API (GraphQL SearchItinerary) — sans navigateur")
        _run_parallel_api(
            routes,
            workers=workers,
            mongo_repo=mongo_repo,
            sql_repo=sql_repo,
            osrm_fallback=osrm_fallback,
        )
    else:
        if use_browser and getattr(args, "workers", None) not in (None, 1):
            print("Note : --workers ignore en mode navigateur (sequentiel).")

        def _process_route(route: RoutePair, result: RouteResult) -> None:
            _persist_result(
                route.depart, route.arrivee, result,
                mongo_repo=mongo_repo, sql_repo=sql_repo,
            )

        if use_browser:
            with ViaMichelinScraper(headless=headless, use_browser=True) as scraper:
                for i, route in enumerate(routes):
                    _process_route(
                        route,
                        scraper.fetch_route(
                            route.depart,
                            route.arrivee,
                            depart_departement=route.depart_departement,
                            arrivee_departement=route.arrivee_departement,
                        ),
                    )
                    if i < len(routes) - 1 and SCRAPE_DELAY_SECONDS > 0:
                        time.sleep(SCRAPE_DELAY_SECONDS)
        elif osrm_fallback or browser_fallback:
            ctx = (
                BrowserFallbackPool(headless=True)
                if browser_fallback
                else nullcontext()
            )
            with ctx as bf_pool:
                bf = bf_pool if browser_fallback else None
                for i, route in enumerate(routes):
                    _process_route(
                        route,
                        fetch_route_with_fallback(
                            route,
                            osrm_fallback=osrm_fallback,
                            browser_pool=bf,
                        ),
                    )
                    if i < len(routes) - 1 and SCRAPE_DELAY_SECONDS > 0:
                        time.sleep(SCRAPE_DELAY_SECONDS)
        else:
            for i, route in enumerate(routes):
                _process_route(
                    route,
                    fetch_route_viamichelin(
                        route.depart,
                        route.arrivee,
                        depart_departement=route.depart_departement,
                        arrivee_departement=route.arrivee_departement,
                    ),
                )
                if i < len(routes) - 1 and SCRAPE_DELAY_SECONDS > 0:
                    time.sleep(SCRAPE_DELAY_SECONDS)

    mongo_repo.close()
    print("\nTermine.")


def cmd_clean_bad_mongo(args: argparse.Namespace) -> None:
    """Remet en pending les km douteux (navigateur / sans geocodage)."""
    repo = MongoRepository()
    repo.ping()
    before_ok = repo.count_ok()
    reset = repo.reset_suspect_trajets()
    print(
        f"MongoDB {repo.db.name}.{repo.collection.name} :\n"
        f"  {reset} trajet(s) douteux remis en pending (km effaces)\n"
        f"  Avant : {before_ok} ok — apres : {repo.count_ok()} ok, "
        f"{repo.count_pending()} en attente."
    )
    repo.close()
    print("\nRelancez : .\\run.cmd run --source mongo")


def cmd_clean_mongo(args: argparse.Namespace) -> None:
    repo = MongoRepository()
    repo.ping()
    before = repo.count_all()
    deleted = repo.clear_all()
    print(
        f"MongoDB {repo.db.name}.{repo.collection.name} : "
        f"{deleted} document(s) supprime(s) (avant : {before})."
    )
    repo.close()


def cmd_seed_mongo(args: argparse.Namespace) -> None:
    limit = args.limit if args.limit and args.limit > 0 else None
    routes = load_trajets("transports", Path("data/trajets.csv"), limit=limit)
    if not routes:
        print("Aucune paire a inscrire (transports vide ?).")
        return
    repo = MongoRepository()
    repo.ping()
    route_pairs = [RoutePair.from_cities(d, a) for d, a in routes]
    inserted, skipped_ok = repo.seed_pairs(route_pairs)
    patched = repo.apply_city_departments()
    print(
        f"MongoDB {repo.db.name}.{repo.collection.name} :\n"
        f"  {inserted} nouveau(x) trajet(s) inscrit(s) (statut pending)\n"
        f"  {skipped_ok} deja ok — non modifie(s)\n"
        f"  {patched} doc(s) avec dept Paris/Marseille renseigne(s)\n"
        f"  Total : {repo.count_all()} doc(s), {repo.count_ok()} ok, "
        f"{repo.count_pending()} en attente."
    )
    repo.close()
    print("\nEnsuite : .\\run.cmd run --source mongo")


def cmd_patch_departments(args: argparse.Namespace) -> None:
    """Renseigne depart_departement / arrivee_departement pour Paris et Marseille."""
    repo = MongoRepository()
    repo.ping()
    updated = repo.apply_city_departments()
    paris = repo.collection.count_documents(
        {"$or": [{"depart": "Paris"}, {"arrivee": "Paris"}]}
    )
    marseille = repo.collection.count_documents(
        {"$or": [{"depart": "Marseille"}, {"arrivee": "Marseille"}]}
    )
    with_dept = repo.collection.count_documents(
        {
            "$or": [
                {"depart": "Paris", "depart_departement": {"$nin": [None, ""]}},
                {"arrivee": "Paris", "arrivee_departement": {"$nin": [None, ""]}},
                {"depart": "Marseille", "depart_departement": {"$nin": [None, ""]}},
                {"arrivee": "Marseille", "arrivee_departement": {"$nin": [None, ""]}},
            ]
        }
    )
    print(
        f"Departements Paris/Marseille : {updated} doc(s) mis a jour.\n"
        f"  Trajets avec Paris : {paris}\n"
        f"  Trajets avec Marseille : {marseille}\n"
        f"  Avec dept renseigne (Paris ou Marseille) : {with_dept}"
    )
    repo.close()


def cmd_list_mongo(args: argparse.Namespace) -> None:
    repo = MongoRepository()
    for row in repo.list_trajets(limit=args.limit):
        print(row)
    repo.close()


def cmd_list_sql(args: argparse.Namespace) -> None:
    for row in SqlRepository().list_trajets(limit=args.limit):
        print(row)


def cmd_monitor(args: argparse.Namespace) -> None:
    """Test ViaMichelin en boucle (OK / DOWN / FAIL). Ctrl+C pour arreter."""
    depart = args.depart.strip()
    arrivee = args.arrivee.strip()
    interval = max(60, args.interval)
    log_path = None if getattr(args, "no_log", False) else Path(args.log)

    print(
        f"Surveillance ViaMichelin : {depart} -> {arrivee}\n"
        f"  Intervalle : {interval}s ({interval // 60} min)\n"
        f"  1 essai API par cycle (pas de retry — reponse rapide)\n"
        f"  Ctrl+C pour arreter"
    )
    if log_path:
        print(f"  Journal : {log_path.resolve()}")

    def emit(line: str) -> None:
        print(line, flush=True)
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    try:
        while True:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            t0 = time.perf_counter()
            result = fetch_route_viamichelin(
                depart,
                arrivee,
                depart_departement=department_for_city(depart),
                arrivee_departement=department_for_city(arrivee),
                retry_max=1,
            )
            elapsed = time.perf_counter() - t0

            if result.statut == "ok":
                emit(
                    f"[{ts}] OK   {depart} -> {arrivee} | "
                    f"{result.distance_km} km ({elapsed:.0f}s)"
                )
            elif is_transient_api_error(result.message_erreur):
                emit(
                    f"[{ts}] DOWN {depart} -> {arrivee} | "
                    f"serveur sature (503) ({elapsed:.0f}s)"
                )
            else:
                emit(
                    f"[{ts}] FAIL {depart} -> {arrivee} | "
                    f"{result.message_erreur} ({elapsed:.0f}s)"
                )

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nSurveillance arretee.")


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
    *,
    raw_response: dict | list | None,
) -> None:
    print(f"\n{'=' * 60}")
    print("ITINERAIRE")
    print(f"{'=' * 60}")
    print(f"  Distance : {distance_km} km" if distance_km is not None else "  Distance : (absente)")
    if raw_response:
        print("\n  Reponse itineraire (extrait) :")
        print(json.dumps(raw_response, indent=2, ensure_ascii=False)[:8000])


def _geo_from_search_hit(hit: dict) -> dict:
    address = hit.get("address") or {}
    loc = (hit.get("mapLocation") or {}).get("location") or {}
    return {
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
        "zip_code": address.get("zipCode"),
        "department": address.get("department"),
        "formatted_name": hit.get("formattedName"),
    }


def _build_test_payload(
    *,
    depart: str,
    arrivee: str,
    depart_hits: list[dict],
    arrivee_hits: list[dict],
    distance_km: float | None,
    raw_response: dict | list | None,
    include_raw: bool,
) -> dict:
    payload = {
        "depart_query": depart,
        "arrivee_query": arrivee,
        "depart_hits": [_format_hit_summary(h) for h in depart_hits],
        "arrivee_hits": [_format_hit_summary(h) for h in arrivee_hits],
        "depart_used": _format_hit_summary(depart_hits[0]),
        "arrivee_used": _format_hit_summary(arrivee_hits[0]),
        "itinerary": {
            "distance_km": distance_km,
        },
    }
    if include_raw and raw_response is not None:
        payload["itinerary"]["raw_response"] = raw_response
    return payload


def cmd_test(args: argparse.Namespace) -> None:
    from src.extract import extract_from_api_payload

    depart = args.depart.strip()
    arrivee = args.arrivee.strip()
    max_hits = max(1, args.hits)

    depart_query = geocode_search_query(depart, department_for_city(depart))
    arrivee_query = geocode_search_query(arrivee, department_for_city(arrivee))
    if depart_query != depart:
        print(f"Requete geocodage depart : {depart_query}")
    if arrivee_query != arrivee:
        print(f"Requete geocodage arrivee : {arrivee_query}")

    try:
        depart_hits = search_addresses(depart_query)[:max_hits]
        arrivee_hits = search_addresses(arrivee_query)[:max_hits]
    except ValueError as exc:
        print(f"Erreur geocodage : {exc}")
        sys.exit(1)

    depart_geo = _geo_from_search_hit(depart_hits[0])
    arrivee_geo = _geo_from_search_hit(arrivee_hits[0])
    lon1, lat1 = float(depart_geo["lng"]), float(depart_geo["lat"])
    lon2, lat2 = float(arrivee_geo["lng"]), float(arrivee_geo["lat"])

    try:
        raw_response = fetch_itinerary_graphql(
            depart_geo,
            arrivee_geo,
            depart=depart,
            arrivee=arrivee,
        )
        distance_km = extract_from_api_payload(raw_response)
        if distance_km is None:
            raw_response = fetch_itinerary_vmrest(lon1, lat1, lon2, lat2)
            distance_km = extract_from_api_payload(raw_response)
    except Exception as exc:
        print(f"Erreur itineraire : {exc}")
        sys.exit(1)

    if args.json or args.out:
        payload = _build_test_payload(
            depart=depart,
            arrivee=arrivee,
            depart_hits=depart_hits,
            arrivee_hits=arrivee_hits,
            distance_km=distance_km,
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
        choices=("csv", "transports", "mongo"),
        default=TRAJETS_SOURCE,
        help="mongo = trajets pending en MongoDB | transports = paramedic.transports | csv",
    )
    run_p.add_argument("--csv", default="data/trajets.csv")
    run_p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Nombre max de trajets (0 = tout). Utile avec --source transports.",
    )
    run_p.add_argument(
        "--browser",
        action="store_true",
        help="Tout via le site viamichelin.fr (headless, sans API vmrest directe).",
    )
    run_p.add_argument(
        "--visible",
        action="store_true",
        help="Comme --browser mais avec fenetre Edge visible.",
    )
    run_p.add_argument(
        "--osrm",
        action="store_true",
        help="Secours OSRM si ViaMichelin vmrest en 503 (geocodage ViaMichelin + router OSRM).",
    )
    run_p.add_argument(
        "--browser-fallback",
        action="store_true",
        help="Secours navigateur sequentiel si ViaMichelin en echec (lent ; preferez --osrm).",
    )
    run_p.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Requetes API en parallele (1-10, defaut SCRAPE_WORKERS=5). Ignore avec --browser.",
    )
    run_p.add_argument(
        "--force",
        action="store_true",
        help="Re-scraper meme si le couple existe deja en MongoDB (ok).",
    )
    run_p.add_argument(
        "--also-sql",
        action="store_true",
        help="Dupliquer aussi les resultats dans SQLite (defaut : MongoDB seul).",
    )
    run_p.set_defaults(func=cmd_run)

    clean_mongo_p = sub.add_parser(
        "clean-mongo",
        help="Vider la collection MongoDB des trajets calcules",
    )
    clean_mongo_p.set_defaults(func=cmd_clean_mongo)

    clean_bad_p = sub.add_parser(
        "clean-bad-mongo",
        help="Effacer les km douteux (navigateur) et remettre en pending",
    )
    clean_bad_p.set_defaults(func=cmd_clean_bad_mongo)

    seed_mongo_p = sub.add_parser(
        "seed-mongo",
        help="Inscrire les paires uniques (transports) en MongoDB (pending)",
    )
    seed_mongo_p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Nombre max de paires a inscrire (0 = tout).",
    )
    seed_mongo_p.set_defaults(func=cmd_seed_mongo)

    patch_dept_p = sub.add_parser(
        "patch-departments",
        help="Ajouter dept Paris/Marseille sur les trajets Mongo deja inscrits",
    )
    patch_dept_p.set_defaults(func=cmd_patch_departments)

    list_mongo_p = sub.add_parser("list-mongo", help="Afficher les trajets en MongoDB")
    list_mongo_p.add_argument("--limit", type=int, default=20)
    list_mongo_p.set_defaults(func=cmd_list_mongo)

    monitor_p = sub.add_parser(
        "monitor",
        help="Surveiller ViaMichelin en boucle (OK / DOWN toutes les N secondes)",
    )
    monitor_p.add_argument("--depart", default="Paris", help="Ville test depart")
    monitor_p.add_argument("--arrivee", default="Lyon", help="Ville test arrivee")
    monitor_p.add_argument(
        "--interval",
        type=int,
        default=600,
        metavar="SEC",
        help="Delai entre deux tests (defaut 600 = 10 min, min 60).",
    )
    monitor_p.add_argument(
        "--log",
        metavar="FICHIER",
        default="data/viamichelin_monitor.log",
        help="Fichier journal (defaut data/viamichelin_monitor.log).",
    )
    monitor_p.add_argument(
        "--no-log",
        action="store_true",
        help="N'ecrire que dans le terminal (pas de fichier).",
    )
    monitor_p.set_defaults(func=cmd_monitor)

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
        help="JSON sans raw_response vmrest (geocodage + km seulement).",
    )
    test_p.set_defaults(func=cmd_test)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
