"""Exemple Paris-Bordeaux avec variantes departement."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.db.mongo_repository import MongoRepository

repo = MongoRepository()
docs = list(
    repo.collection.find(
        {
            "$or": [
                {"depart": "Paris", "arrivee": "Bordeaux"},
                {"depart": "Bordeaux", "arrivee": "Paris"},
            ]
        },
        {
            "depart": 1,
            "arrivee": 1,
            "depart_departement": 1,
            "arrivee_departement": 1,
            "statut": 1,
            "_id": 0,
        },
    ).sort([("depart_departement", 1), ("arrivee_departement", 1)])
)
print(f"Paris <-> Bordeaux : {len(docs)} variante(s)")
for d in docs:
    print(d)
repo.close()
