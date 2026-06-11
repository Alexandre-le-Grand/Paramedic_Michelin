"""Lecture des trajets depuis la base patron (paramedic.transports)."""
from __future__ import annotations

from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection

from config.settings import MONGO_URI, PARAMEDIC_DB, TRANSPORTS_COLLECTION
from src.city_departments import HUB_CITIES, is_plausible_hub_department
from src.hub_expansion import canonical_route_pair
from src.route_pair import RoutePair


def _city(doc_field: dict[str, Any] | None) -> str:
    if not doc_field:
        return ""
    for key in ("city", "lightened", "value"):
        val = doc_field.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _department(doc_field: dict[str, Any] | None) -> str | None:
    if not doc_field:
        return None
    for key in ("department", "dept", "value"):
        val = doc_field.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


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
        """Paires ville uniquement (retrocompatibilite)."""
        return [p.as_tuple() for p in self.load_unique_route_pairs(limit=limit)]

    def load_hub_departments(self) -> dict[str, set[str]]:
        """Departements distincts lies a Paris/Marseille dans les transports."""
        hub_depts: dict[str, set[str]] = {city: set() for city in HUB_CITIES}
        for hub in HUB_CITIES:
            for field in ("departure", "arrival"):
                other = "arrival" if field == "departure" else "departure"
                pipeline = [
                    {
                        "$match": {
                            f"{field}.city": hub,
                            f"{field}.department": {
                                "$exists": True,
                                "$type": "string",
                                "$ne": "",
                            },
                        }
                    },
                    {
                        "$group": {
                            "_id": f"${field}.department",
                            "n": {"$sum": 1},
                        }
                    },
                ]
                for doc in self.collection.aggregate(pipeline, allowDiskUse=True):
                    dept = (doc.get("_id") or "").strip()
                    if dept and is_plausible_hub_department(hub, dept):
                        hub_depts[hub].add(dept)
        return hub_depts

    def load_unique_route_pairs(self, limit: int | None = None) -> list[RoutePair]:
        """
        Paires uniques avec departements quand Paris ou Marseille est implique.
        Aller-retour fusionne (sens canonique).
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
                        "dep": "$departure.city",
                        "arr": "$arrival.city",
                        "depDept": "$departure.department",
                        "arrDept": "$arrival.department",
                    }
                }
            },
        ]
        if limit is not None and limit > 0:
            pipeline.append({"$limit": limit})

        routes: dict[tuple, RoutePair] = {}
        for doc in self.collection.aggregate(pipeline, allowDiskUse=True):
            key = doc.get("_id") or {}
            pair = canonical_route_pair(
                key.get("dep") or "",
                key.get("arr") or "",
                key.get("depDept"),
                key.get("arrDept"),
            )
            if pair is not None:
                routes[pair.mongo_key()] = pair
        return sorted(routes.values(), key=lambda r: r.mongo_key())

    def load_routes_to_city(self, city: str) -> list[RoutePair]:
        """
        Tous les departs (ville + dept hub) vers `city` dans les transports.
        Utilise pour « tous les departements vers Bordeaux » quand Paris y va.
        """
        city = city.strip()
        if not city:
            return []
        pipeline = [
            {
                "$match": {
                    "arrival.city": city,
                    "departure.city": {"$exists": True, "$type": "string", "$ne": ""},
                    "$expr": {"$ne": ["$departure.city", "$arrival.city"]},
                }
            },
            {
                "$group": {
                    "_id": {
                        "dep": "$departure.city",
                        "depDept": "$departure.department",
                    }
                }
            },
        ]
        routes: dict[tuple, RoutePair] = {}
        for doc in self.collection.aggregate(pipeline, allowDiskUse=True):
            key = doc.get("_id") or {}
            dep = (key.get("dep") or "").strip()
            if not dep or dep == city:
                continue
            pair = canonical_route_pair(dep, city, key.get("depDept"), None)
            if pair is not None:
                routes[pair.mongo_key()] = pair
        return sorted(routes.values(), key=lambda r: r.mongo_key())

    def load_routes_to_cities(self, cities: set[str]) -> dict[str, list[RoutePair]]:
        """Tous les departs vers chaque ville cible (une seule aggregation Mongo)."""
        if not cities:
            return {}
        city_list = sorted(cities)
        pipeline = [
            {
                "$match": {
                    "arrival.city": {"$in": city_list},
                    "departure.city": {"$exists": True, "$type": "string", "$ne": ""},
                    "$expr": {"$ne": ["$departure.city", "$arrival.city"]},
                }
            },
            {
                "$group": {
                    "_id": {
                        "target": "$arrival.city",
                        "dep": "$departure.city",
                        "depDept": "$departure.department",
                    }
                }
            },
        ]
        buckets: dict[str, dict[tuple, RoutePair]] = {c: {} for c in city_list}
        for doc in self.collection.aggregate(pipeline, allowDiskUse=True):
            key = doc.get("_id") or {}
            target = (key.get("target") or "").strip()
            dep = (key.get("dep") or "").strip()
            if not target or target not in buckets or not dep or dep == target:
                continue
            pair = canonical_route_pair(dep, target, key.get("depDept"), None)
            if pair is not None:
                buckets[target][pair.mongo_key()] = pair
        return {
            city: sorted(bucket.values(), key=lambda r: r.mongo_key())
            for city, bucket in buckets.items()
        }

    def close(self) -> None:
        self.client.close()
