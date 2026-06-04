"""Lecture des trajets depuis la base patron (paramedic.transports)."""
from __future__ import annotations

from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection

from config.settings import MONGO_URI, PARAMEDIC_DB, TRANSPORTS_COLLECTION


def _city(doc_field: dict[str, Any] | None) -> str:
    if not doc_field:
        return ""
    for key in ("city", "lightened", "value"):
        val = doc_field.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


class TransportsRepository:
    """Acces en lecture a paramedic.transports (dump du patron)."""

    def __init__(
        self,
        uri: str | None = None,
        db_name: str | None = None,
        collection_name: str | None = None,
    ) -> None:
        self.client = MongoClient(uri or MONGO_URI, serverSelectionTimeoutMS=5000)
        self.collection: Collection = self.client[db_name or PARAMEDIC_DB][
            collection_name or TRANSPORTS_COLLECTION
        ]

    def count_documents(self) -> int:
        return self.collection.count_documents({})

    def load_unique_routes(self, limit: int | None = None) -> list[tuple[str, str]]:
        """
        Paires depart/arrivee uniques (ville), sans doublon aller-retour :
        Paris -> Bordeaux et Bordeaux -> Paris ne comptent qu'une fois
        (sens canonique : ville la plus petite en alphabet, puis l'autre).
        """
        pipeline: list[dict[str, Any]] = [
            {
                "$match": {
                    "departure.city": {"$exists": True, "$type": "string", "$ne": ""},
                    "arrival.city": {"$exists": True, "$type": "string", "$ne": ""},
                    "$expr": {"$ne": ["$departure.city", "$arrival.city"]},
                }
            },
            {
                "$group": {
                    "_id": {
                        "depart": {"$min": ["$departure.city", "$arrival.city"]},
                        "arrivee": {"$max": ["$departure.city", "$arrival.city"]},
                    }
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "depart": "$_id.depart",
                    "arrivee": "$_id.arrivee",
                }
            },
            {"$sort": {"depart": 1, "arrivee": 1}},
        ]
        if limit is not None and limit > 0:
            pipeline.append({"$limit": limit})

        routes: list[tuple[str, str]] = []
        for doc in self.collection.aggregate(pipeline, allowDiskUse=True):
            depart = (doc.get("depart") or "").strip()
            arrivee = (doc.get("arrivee") or "").strip()
            if depart and arrivee:
                routes.append((depart, arrivee))
        return routes

    def close(self) -> None:
        self.client.close()
