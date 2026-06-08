"""Persistance MongoDB — documents flexibles + reponse brute du scraping."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient, UpdateOne
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from config.settings import MONGO_COLLECTION, MONGO_DB, MONGO_URI
from src.city_departments import CITY_DEPARTMENT
from src.route_pair import RoutePair


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

    def _ensure_indexes(self) -> None:
        self.collection.create_index([("scraped_at", -1)])
        self.collection.create_index([("statut", 1)])
        try:
            self.collection.create_index(
                [("depart", 1), ("arrivee", 1)],
                unique=True,
                name="uniq_depart_arrivee",
            )
        except DuplicateKeyError:
            removed = self.dedupe_pairs()
            if removed:
                print(f"MongoDB : {removed} doublon(s) supprime(s) avant index unique.")
            self.collection.create_index(
                [("depart", 1), ("arrivee", 1)],
                unique=True,
                name="uniq_depart_arrivee",
            )

    def dedupe_pairs(self) -> int:
        """Garde le meilleur doc par couple (ok+km prioritaire, sinon plus recent)."""
        removed = 0
        pipeline = [
            {
                "$group": {
                    "_id": {"depart": "$depart", "arrivee": "$arrivee"},
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
        return self.collection.count_documents(
            {
                "$or": [
                    {"statut": {"$ne": "ok"}},
                    {"distance_km": None},
                    {"distance_km": {"$exists": False}},
                ]
            }
        )

    def clear_all(self) -> int:
        result = self.collection.delete_many({})
        return int(result.deleted_count)

    def existing_ok_pairs(self) -> set[tuple[str, str]]:
        """Couples depart->arrivee deja calcules avec succes."""
        pairs: set[tuple[str, str]] = set()
        cursor = self.collection.find(
            {"statut": "ok", "distance_km": {"$ne": None}},
            projection={"depart": 1, "arrivee": 1, "_id": 0},
        )
        for doc in cursor:
            depart = doc.get("depart")
            arrivee = doc.get("arrivee")
            if depart and arrivee:
                pairs.add((depart, arrivee))
        return pairs

    def load_pending_pairs(self, limit: int | None = None) -> list[tuple[str, str]]:
        """Trajets sans distance km valide (a calculer via ViaMichelin)."""
        return [p.as_tuple() for p in self.load_pending_routes(limit=limit)]

    def load_pending_routes(self, limit: int | None = None) -> list[RoutePair]:
        """Trajets en attente avec departements Paris/Marseille si connus."""
        query = {
            "$or": [
                {"statut": {"$ne": "ok"}},
                {"distance_km": None},
                {"distance_km": {"$exists": False}},
            ]
        }
        cursor = self.collection.find(
            query,
            projection={
                "depart": 1,
                "arrivee": 1,
                "depart_departement": 1,
                "arrivee_departement": 1,
                "_id": 0,
            },
            sort=[("depart", 1), ("arrivee", 1)],
        )
        if limit is not None and limit > 0:
            cursor = cursor.limit(limit)
        routes: list[RoutePair] = []
        for doc in cursor:
            pair = RoutePair.from_mapping(doc)
            if pair.depart and pair.arrivee:
                routes.append(pair)
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
            depart, arrivee = route.depart, route.arrivee
            if (depart, arrivee) in ok_pairs:
                skipped_ok += 1
                continue
            insert_doc: dict[str, Any] = {
                "depart": depart,
                "arrivee": arrivee,
                "statut": "pending",
                "distance_km": None,
                "source": None,
                "message_erreur": None,
                "scraped_at": datetime.now(timezone.utc),
            }
            if route.depart_departement:
                insert_doc["depart_departement"] = route.depart_departement
            if route.arrivee_departement:
                insert_doc["arrivee_departement"] = route.arrivee_departement
            ops.append(
                UpdateOne(
                    {"depart": depart, "arrivee": arrivee},
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
        result = self.collection.update_one(
            {"depart": record["depart"], "arrivee": record["arrivee"]},
            {"$set": doc},
            upsert=True,
        )
        if result.upserted_id:
            return str(result.upserted_id)
        existing = self.collection.find_one(
            {"depart": record["depart"], "arrivee": record["arrivee"]},
            projection={"_id": 1},
        )
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
