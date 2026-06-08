"""Verifie que toutes les paires de villes du patron sont bien dans Mongo trajets."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import MONGO_URI, PARAMEDIC_DB, TRANSPORTS_COLLECTION
from pymongo import MongoClient
from src.db.mongo_repository import MongoRepository
from src.db.transports_repository import TransportsRepository


def canon_pair(a: str, b: str) -> tuple[str, str]:
    a, b = a.strip(), b.strip()
    return (a, b) if a <= b else (b, a)


def main() -> int:
    print("Chargement des paires depuis paramedic.transports...")
    trans_repo = TransportsRepository()
    expected = set(trans_repo.load_unique_routes())
    trans_repo.close()

    print("Chargement des documents depuis paramedic_michelin.trajets...")
    mongo_repo = MongoRepository()
    mongo_docs = list(
        mongo_repo.collection.find(
            {},
            projection={"depart": 1, "arrivee": 1, "statut": 1, "distance_km": 1},
        )
    )
    mongo_repo.close()

    mongo_pairs: set[tuple[str, str]] = set()
    bad_order: list[tuple[str, str]] = []
    empty_city: list[dict] = []
    not_canon: list[tuple[str, str]] = []
    statuts: dict[str, int] = {}

    for doc in mongo_docs:
        depart = (doc.get("depart") or "").strip()
        arrivee = (doc.get("arrivee") or "").strip()
        statut = doc.get("statut") or "?"
        statuts[statut] = statuts.get(statut, 0) + 1

        if not depart or not arrivee:
            empty_city.append(doc)
            continue
        if depart == arrivee:
            not_canon.append((depart, arrivee))
        pair = (depart, arrivee)
        canon = canon_pair(depart, arrivee)
        if pair != canon:
            bad_order.append(pair)
        mongo_pairs.add(pair)

    missing = expected - mongo_pairs
    extra = mongo_pairs - expected

    # Paires orientees du patron (pour info si ecart canon)
    client = MongoClient(MONGO_URI)
    trans = client[PARAMEDIC_DB][TRANSPORTS_COLLECTION]
    pipe_oriented = [
        {
            "$match": {
                "departure.city": {"$exists": True, "$type": "string", "$ne": ""},
                "arrival.city": {"$exists": True, "$type": "string", "$ne": ""},
                "$expr": {"$ne": ["$departure.city", "$arrival.city"]},
            }
        },
        {"$group": {"_id": {"d": "$departure.city", "a": "$arrival.city"}}},
    ]
    oriented_raw = {
        (d["_id"]["d"].strip(), d["_id"]["a"].strip())
        for d in trans.aggregate(pipe_oriented, allowDiskUse=True)
    }
    oriented_canon = {canon_pair(d, a) for d, a in oriented_raw}
    client.close()

    print()
    print("=== Comparaison ensembles (canonique) ===")
    print(f"Patron (paires uniques)     : {len(expected):,}")
    print(f"Mongo trajets (documents)   : {len(mongo_docs):,}")
    print(f"Mongo paires valides        : {len(mongo_pairs):,}")
    print(f"Manquantes dans Mongo       : {len(missing):,}")
    print(f"En trop dans Mongo          : {len(extra):,}")
    print()
    print("=== Statuts Mongo ===")
    for k in sorted(statuts):
        print(f"  {k}: {statuts[k]:,}")
    print()
    print("=== Qualite des villes dans Mongo ===")
    print(f"  Ville vide / manquante    : {len(empty_city):,}")
    print(f"  Meme ville depart=arrivee : {len(not_canon):,}")
    print(f"  Ordre non canonique       : {len(bad_order):,}")
    print(f"  (canon = min alphabet puis max)")
    print()
    print("=== Paires orientees patron ===")
    print(f"  Orientees uniques         : {len(oriented_raw):,}")
    print(f"  -> canoniques derivees    : {len(oriented_canon):,}")
    print(f"  (doit = {len(expected):,})")

    ok = (
        not missing
        and not extra
        and not empty_city
        and not not_canon
        and len(mongo_pairs) == len(expected)
    )

    if missing:
        print()
        print(f"--- Exemples MANQUANTS ({min(15, len(missing))} / {len(missing)}) ---")
        for p in sorted(missing)[:15]:
            print(f"  {p[0]} -> {p[1]}")

    if extra:
        print()
        print(f"--- Exemples EN TROP ({min(15, len(extra))} / {len(extra)}) ---")
        for p in sorted(extra)[:15]:
            print(f"  {p[0]} -> {p[1]}")

    if bad_order:
        print()
        print(f"--- Ordre non canonique ({min(10, len(bad_order))} exemples) ---")
        for p in sorted(bad_order)[:10]:
            c = canon_pair(p[0], p[1])
            print(f"  Mongo: {p[0]} -> {p[1]}  (attendu: {c[0]} -> {c[1]})")

    print()
    if ok:
        print("VERDICT : OK — toutes les paires de villes du patron sont presentes dans Mongo.")
        return 0
    print("VERDICT : ECART — voir details ci-dessus.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
