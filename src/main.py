"""
Paramedic Michelin — scraping ViaMichelin + SQL + MongoDB.

Usage:
    python src/main.py run
    python src/main.py list-sql
"""
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

from config.settings import BROWSER_HEADLESS, SCRAPE_DELAY_SECONDS
from src.db.mongo_repository import MongoRepository
from src.db.sql_repository import SqlRepository
from src.db.transports_repository import TransportsRepository
from src.models import RouteResult
from src.scraper.viamichelin import ViaMichelinScraper


def load_trajets(source: str, csv_path: Path, limit: int | None) -> list[tuple[str, str]]:
    if source == "transports":
        repo = TransportsRepository()
        try:
            total = repo.count_documents()
            routes = repo.load_unique_routes(limit=limit)
            print(
                f"Source MongoDB paramedic.transports : "
                f"{total} transports, {len(routes)} paires uniques a scraper."
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
    if limit is not None and limit > 0:
        return rows[:limit]
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


def _print_result(depart: str, arrivee: str, result: RouteResult) -> dict:
    print(f"\nTrajet: {depart} -> {arrivee}")
    record = result_to_record(result)
    print(
        f"  -> {record.get('distance_km')} km, "
        f"{record.get('duree_minutes')} min | "
        f"source={record['source']} | statut={record['statut']}"
    )
    if result.statut == "erreur" and result.message_erreur:
        print(f"  -> {result.message_erreur}")
    return record


def cmd_run(args: argparse.Namespace) -> None:
    limit = args.limit if args.limit and args.limit > 0 else None
    trajets = load_trajets(args.source, Path(args.csv), limit=limit)
    if not trajets:
        print("Aucun trajet a traiter.")
        return

    headless = BROWSER_HEADLESS if not args.visible else False
    mode = "sans fenetre" if headless else "fenetre visible"
    print(f"Scraping ViaMichelin ({mode}) — SQL + MongoDB")
    sql_repo = SqlRepository()
    mongo_repo = MongoRepository()
    mongo_repo.ping()

    with ViaMichelinScraper(headless=headless) as scraper:
        for i, (depart, arrivee) in enumerate(trajets):
            result = scraper.fetch_route(depart, arrivee)
            record = _print_result(depart, arrivee, result)
            sql_id = sql_repo.insert_trajet(record)
            mongo_id = mongo_repo.insert_trajet(record)
            print(f"  Enregistre: SQL id={sql_id}, MongoDB id={mongo_id}")
            if i < len(trajets) - 1:
                print(f"  Pause {SCRAPE_DELAY_SECONDS}s…")
                time.sleep(SCRAPE_DELAY_SECONDS)

    mongo_repo.close()
    print("\nTermine.")


def cmd_list_sql(args: argparse.Namespace) -> None:
    for row in SqlRepository().list_trajets(limit=args.limit):
        print(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scraping ViaMichelin -> SQLite + MongoDB"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Scraper les trajets (CSV ou base transports)")
    run_p.add_argument(
        "--source",
        choices=("csv", "transports"),
        default="csv",
        help="csv = data/trajets.csv | transports = paramedic.transports (MongoDB)",
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
        help="Ouvrir Edge a l'ecran (debug ; sinon headless via .env)",
    )
    run_p.set_defaults(func=cmd_run)

    list_p = sub.add_parser("list-sql", help="Afficher les trajets en SQL")
    list_p.add_argument("--limit", type=int, default=20)
    list_p.set_defaults(func=cmd_list_sql)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
