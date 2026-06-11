"""Persistance MongoDB — documents flexibles + reponse brute du scraping."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient, UpdateOne
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from config.settings import MONGO_COLLECTION, MONGO_DB, MONGO_URI
from src.city_departments import CITY_DEPARTMENT, is_scrapable_route
from src.route_pair import RoutePair

_PENDING_QUERY = {
    "$and": [
        {"$nor": [{"statut": "ok", "distance_km": {"$ne": None}}]},
        {"statut": {"$ne": "ignore"}},
    ],
}

# Dept bruts patron pour Paris qui echouent systematiquement sur ViaMichelin.
_PARIS_NON_ROUTABLE_RAW = (
    "Seine-Saint-Denis",
    "Essonne",
    "Yvelines",
    "Seine-et-Marne",
    "Val-d'Oise",
)


class MongoRepository:
    def __init__(
        self,
        uri: str | None = None,
        db_name: str | None = None,
        collection_name: str | None = None,
    ) -> None:
        self.client = MongoClient(uri or MONGO_URI, serverSelectionTimeoutMS=5000)
        self.db = self.client[db_name or MONGO_DB]
        self.collection: Collection = self.db[collection_name or MONGO_COLLECTION]
        self._ensure_indexes()

    def _backfill_dept_index_fields(self) -> int:
        """Champs vides pour l'index unique (anciens docs sans departements)."""
        updated = 0
        for field in ("depart_departement", "arrivee_departement"):
            result = self.collection.update_many(
                {field: {"$exists": False}},
                {"$set": {field: ""}},
            )
            updated += int(result.modified_count)
            result = self.collection.update_many(
                {field: None},
                {"$set": {field: ""}},
            )
            updated += int(result.modified_count)
        return updated

    def _ensure_indexes(self) -> None:
        self.collection.create_index([("scraped_at", -1)])
        self.collection.create_index([("statut", 1)])
        self._backfill_dept_index_fields()
        for old_name in ("uniq_depart_arrivee",):
            try:
                self.collection.drop_index(old_name)
            except Exception:
                pass
        try:
            self.collection.create_index(
                [
                    ("depart", 1),
                    ("arrivee", 1),
                    ("depart_departement", 1),
                    ("arrivee_departement", 1),
                ],
                unique=True,
                name="uniq_depart_arrivee_dept",
            )
        except DuplicateKeyError:
            removed = self.dedupe_pairs()
            if removed:
                print(f"MongoDB : {removed} doublon(s) supprime(s) avant index unique.")
            self.collection.create_index(
                [
                    ("depart", 1),
                    ("arrivee", 1),
                    ("depart_departement", 1),
                    ("arrivee_departement", 1),
                ],
                unique=True,
                name="uniq_depart_arrivee_dept",
            )

    def dedupe_pairs(self) -> int:
        """Garde le meilleur doc par couple (ok+km prioritaire, sinon plus recent)."""
        removed = 0
        pipeline = [
            {
                "$group": {
                    "_id": {
                        "depart": "$depart",
                        "arrivee": "$arrivee",
                        "depart_departement": {
                            "$ifNull": ["$depart_departement", ""]
                        },
                        "arrivee_departement": {
                            "$ifNull": ["$arrivee_departement", ""]
                        },
                    },
                    "docs": {"$push": {"_id": "$_id", "doc": "$$ROOT"}},
                    "n": {"$sum": 1},
                }
            },
            {"$match": {"n": {"$gt": 1}}},
        ]

        def _rank(doc: dict) -> tuple:
            ok = doc.get("statut") == "ok" and doc.get("distance_km") is not None
            scraped = doc.get("scraped_at")
            return (ok, scraped or datetime.min.replace(tzinfo=timezone.utc))

        for group in self.collection.aggregate(pipeline, allowDiskUse=True):
            docs = [item["doc"] for item in group["docs"]]
            keep = max(docs, key=_rank)
            for doc in docs:
                if doc["_id"] != keep["_id"]:
                    self.collection.delete_one({"_id": doc["_id"]})
                    removed += 1
        return removed

    def ping(self) -> bool:
        self.client.admin.command("ping")
        return True

    def count_all(self) -> int:
        return self.collection.count_documents({})

    def count_ok(self) -> int:
        return self.collection.count_documents(
            {"statut": "ok", "distance_km": {"$ne": None}}
        )

    def count_pending(self) -> int:
        return self.collection.count_documents(_PENDING_QUERY)

    def count_ignored(self) -> int:
        return self.collection.count_documents({"statut": "ignore"})

    def mark_unscrapable_hub_routes(self) -> int:
        """Marque ignore les trajets Paris/Marseille avec dept non geocodable."""
        result = self.collection.update_many(
            {
                "statut": {"$nin": ["ok", "ignore"]},
                "$or": [
                    {
                        "arrivee": "Paris",
                        "arrivee_departement": {"$in": list(_PARIS_NON_ROUTABLE_RAW)},
                    },
                    {
                        "depart": "Paris",
                        "depart_departement": {"$in": list(_PARIS_NON_ROUTABLE_RAW)},
                    },
                ],
            },
            {
                "$set": {
                    "statut": "ignore",
                    "message_erreur": (
                        "Dept hub non geocodable ViaMichelin "
                        "(ex. Paris + Seine-Saint-Denis)"
                    ),
                },
            },
        )
        return int(result.modified_count)

    def clear_all(self) -> int:
        result = self.collection.delete_many({})
        return int(result.deleted_count)

    def existing_ok_pairs(self) -> set[tuple[str, str, str, str]]:
        """Trajets deja calcules avec succes (cle inclut les departements)."""
        pairs: set[tuple[str, str, str, str]] = set()
        cursor = self.collection.find(
            {"statut": "ok", "distance_km": {"$ne": None}},
            projection={
                "depart": 1,
                "arrivee": 1,
                "depart_departement": 1,
                "arrivee_departement": 1,
                "_id": 0,
            },
        )
        for doc in cursor:
            pair = RoutePair.from_mapping(doc)
            if pair.depart and pair.arrivee:
                pairs.add(pair.mongo_key())
        return pairs

    def load_pending_pairs(self, limit: int | None = None) -> list[tuple[str, str]]:
        """Trajets sans distance km valide (a calculer via ViaMichelin)."""
        return [p.as_tuple() for p in self.load_pending_routes(limit=limit)]

    def load_pending_routes(self, limit: int | None = None) -> list[RoutePair]:
        """Trajets a calculer (exclut ok, ignore, dept hub invalide)."""
        cursor = self.collection.find(
            _PENDING_QUERY,
            projection={
                "depart": 1,
                "arrivee": 1,
                "depart_departement": 1,
                "arrivee_departement": 1,
                "_id": 0,
            },
            sort=[("depart", 1), ("arrivee", 1)],
        )
        routes: list[RoutePair] = []
        for doc in cursor:
            pair = RoutePair.from_mapping(doc)
            if not pair.depart or not pair.arrivee:
                continue
            if not is_scrapable_route(
                pair.depart,
                pair.arrivee,
                pair.depart_departement,
                pair.arrivee_departement,
            ):
                continue
            routes.append(pair)
            if limit is not None and limit > 0 and len(routes) >= limit:
                break
        return routes

    def reset_suspect_trajets(self) -> int:
        """
        Remet en pending les km douteux (navigateur sans geocodage / sans vmrest).
        """
        query = {
            "$or": [
                {"source": "viamichelin-browser", "statut": "ok"},
                {
                    "statut": "ok",
                    "source": {"$in": ["viamichelin-browser", "viamichelin"]},
                    "raw_response": None,
                    "depart_lat": None,
                },
            ]
        }
        result = self.collection.update_many(
            query,
            {
                "$set": {
                    "statut": "pending",
                    "distance_km": None,
                    "source": None,
                    "message_erreur": None,
                    "raw_response": None,
                },
                "$unset": {
                    "depart_lat": "",
                    "depart_lng": "",
                    "depart_zip": "",
                    "depart_formatted_name": "",
                    "arrivee_lat": "",
                    "arrivee_lng": "",
                    "arrivee_zip": "",
                    "arrivee_formatted_name": "",
                },
            },
        )
        return int(result.modified_count)

    def apply_city_departments(self) -> int:
        """Renseigne depart_departement / arrivee_departement pour Paris et Marseille."""
        updated = 0
        for city, dept in CITY_DEPARTMENT.items():
            for field in ("depart", "arrivee"):
                dept_field = f"{field}_departement"
                result = self.collection.update_many(
                    {field: city, dept_field: {"$in": [None, ""]}},
                    {"$set": {dept_field: dept}},
                )
                updated += int(result.modified_count)
        return updated

    def seed_pairs(
        self,
        pairs: list[tuple[str, str]] | list[RoutePair],
    ) -> tuple[int, int]:
        """
        Inscrit les couples en attente. Ne remplace pas un trajet deja ok.
        Retourne (inseres, deja_ok_ignores).
        """
        if not pairs:
            return 0, 0
        ok_pairs = self.existing_ok_pairs()
        ops: list[UpdateOne] = []
        skipped_ok = 0
        for item in pairs:
            route = (
                item
                if isinstance(item, RoutePair)
                else RoutePair.from_cities(item[0], item[1])
            )
            if route.mongo_key() in ok_pairs:
                skipped_ok += 1
                continue
            insert_doc: dict[str, Any] = {
                **route.mongo_filter(),
                "statut": "pending",
                "distance_km": None,
                "source": None,
                "message_erreur": None,
                "scraped_at": datetime.now(timezone.utc),
            }
            ops.append(
                UpdateOne(
                    route.mongo_filter(),
                    {"$setOnInsert": insert_doc},
                    upsert=True,
                )
            )
        inserted = 0
        if ops:
            result = self.collection.bulk_write(ops, ordered=False)
            inserted = result.upserted_count
        return inserted, skipped_ok

    def upsert_trajet(self, record: dict[str, Any]) -> str:
        doc = dict(record)
        doc.setdefault("scraped_at", datetime.now(timezone.utc))
        doc.setdefault("depart_departement", doc.get("depart_departement") or "")
        doc.setdefault("arrivee_departement", doc.get("arrivee_departement") or "")
        filt = {
            "depart": record["depart"],
            "arrivee": record["arrivee"],
            "depart_departement": doc["depart_departement"],
            "arrivee_departement": doc["arrivee_departement"],
        }
        result = self.collection.update_one(filt, {"$set": doc}, upsert=True)
        if result.upserted_id:
            return str(result.upserted_id)
        existing = self.collection.find_one(filt, projection={"_id": 1})
        return str(existing["_id"]) if existing else ""

    def list_trajets(self, limit: int = 50) -> list[dict[str, Any]]:
        cursor = self.collection.find(
            {},
            sort=[("scraped_at", -1)],
            limit=limit,
        )
        rows: list[dict[str, Any]] = []
        for doc in cursor:
            row = dict(doc)
            row["_id"] = str(row["_id"])
            rows.append(row)
        return rows

    def insert_trajet(self, record: dict[str, Any]) -> str:
        return self.upsert_trajet(record)

    def close(self) -> None:
        self.client.close()
