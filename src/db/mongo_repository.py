"""Persistance MongoDB — documents flexibles + reponse brute du scraping."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection

from config.settings import MONGO_COLLECTION, MONGO_DB, MONGO_URI


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
        self.collection.create_index([("depart", 1), ("arrivee", 1)])
        self.collection.create_index([("scraped_at", -1)])

    def ping(self) -> bool:
        self.client.admin.command("ping")
        return True

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

    def insert_trajet(self, record: dict[str, Any]) -> str:
        doc = dict(record)
        doc.setdefault("scraped_at", datetime.now(timezone.utc))
        result = self.collection.insert_one(doc)
        return str(result.inserted_id)

    def close(self) -> None:
        self.client.close()