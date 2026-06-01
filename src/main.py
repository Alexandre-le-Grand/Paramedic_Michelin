"""Point d entree: scrape ViaMichelin puis enregistre en SQL + MongoDB."""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import SCRAPE_DELAY_SECONDS
from src.db.mongo_repository import MongoRepository
from src.db.sql_repository import SqlRepository
from src.extract import is_plausible_route_km
from src.scraper.fallback_osrm import route_distance_km as osrm_route
from src.scraper.viamichelin import RouteResult, fetch_route


def load_trajets_csv(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            depart = (row.get("depart") or row.get("departure") or "").strip()
            arrivee = (row.get("arrivee") or row.get("arrival") or "").strip()
            if depart and arrivee:
                rows.append((depart, arrivee))
    return rows


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
        "scraped_at": datetime.now(timezone.utc),
    }


def process_trajet(depart: str, arrivee: str, use_fallback: bool) -> dict:
    print(f"Trajet: {depart} -> {arrivee}")
    try:
        result = fetch_route(depart, arrivee)
    except Exception as exc:
        result = RouteResult(
            depart=depart,
            arrivee=arrivee,
            distance_km=None,
            duree_minutes=None,
            source="viamichelin",
            statut="erreur",
            message_erreur=str(exc),
            raw_response=None,
        )

    needs_fallback = result.statut != "ok" or not is_plausible_route_km(
        result.distance_km
    )
    if needs_fallback and use_fallback:
        print("  -> repli OSRM (distance fiable, proche ViaMichelin)")
        try:
            fb = osrm_route(depart, arrivee)
            result = RouteResult(
                depart=depart,
                arrivee=arrivee,
                distance_km=fb["distance_km"],
                duree_minutes=fb["duree_minutes"],
                source=fb["source"],
                statut="ok",
                message_erreur=result.message_erreur,
                raw_response=fb.get("raw_response"),
            )
        except Exception as exc2:
            result.message_erreur = f"{result.message_erreur}; OSRM: {exc2}"
            result.statut = "erreur"

    record = result_to_record(result)
    print(
        f"  -> {record.get('distance_km')} km, "
        f"{record.get('duree_minutes')} min, source={record['source']}, statut={record['statut']}"
    )
    return record


def cmd_run(args: argparse.Namespace) -> None:
    trajets = load_trajets_csv(Path(args.csv))
    if not trajets:
        print("Aucun trajet dans le CSV.")
        return

    sql_repo = SqlRepository()
    mongo_repo = MongoRepository()
    mongo_repo.ping()
    print("MongoDB: connecte")

    for i, (depart, arrivee) in enumerate(trajets):
        record = process_trajet(depart, arrivee, use_fallback=not args.no_fallback)
        sql_id = sql_repo.insert_trajet(record)
        mongo_id = mongo_repo.insert_trajet(record)
        print(f"  SQL id={sql_id}, MongoDB id={mongo_id}")
        if i < len(trajets) - 1:
            time.sleep(SCRAPE_DELAY_SECONDS)

    mongo_repo.close()
    print("Termine.")


def cmd_list_sql(_: argparse.Namespace) -> None:
    rows = SqlRepository().list_trajets()
    for row in rows:
        print(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Paramedic Michelin - scrape + SQL + MongoDB")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Scraper les trajets du CSV")
    run_p.add_argument("--csv", default="data/trajets.csv", help="Fichier CSV depart,arrivee")
    run_p.add_argument(
        "--no-fallback",
        action="store_true",
        help="Ne pas utiliser OSRM si ViaMichelin echoue",
    )
    run_p.set_defaults(func=cmd_run)

    list_p = sub.add_parser("list-sql", help="Afficher les trajets en base SQL")
    list_p.set_defaults(func=cmd_list_sql)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()