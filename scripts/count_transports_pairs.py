"""Compte exact des paires de trajets dans paramedic.transports."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient
from config.settings import MONGO_URI, PARAMEDIC_DB, TRANSPORTS_COLLECTION

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
col = client[PARAMEDIC_DB][TRANSPORTS_COLLECTION]

total = col.count_documents({})
print("=== TOTAL ===")
print("documents transports:", total)

valid_match = {
    "departure.city": {"$exists": True, "$type": "string", "$ne": ""},
    "arrival.city": {"$exists": True, "$type": "string", "$ne": ""},
    "$expr": {"$ne": ["$departure.city", "$arrival.city"]},
}

valid = col.count_documents(valid_match)
print("transports avec 2 villes differentes:", valid)

same_city = col.count_documents(
    {
        "departure.city": {"$exists": True, "$type": "string", "$ne": ""},
        "arrival.city": {"$exists": True, "$type": "string", "$ne": ""},
        "$expr": {"$eq": ["$departure.city", "$arrival.city"]},
    }
)
print("transports meme ville depart/arrivee:", same_city)
print("autres / invalides:", total - valid - same_city)

oriented = list(
    col.aggregate(
        [
            {"$match": valid_match},
            {"$group": {"_id": {"dep": "$departure.city", "arr": "$arrival.city"}}},
            {"$count": "n"},
        ],
        allowDiskUse=True,
    )
)
oriented_n = oriented[0]["n"] if oriented else 0
print()
print("paires ORIENTEES uniques (Paris->Bordeaux != Bordeaux->Paris):", oriented_n)

canon = list(
    col.aggregate(
        [
            {"$match": valid_match},
            {
                "$group": {
                    "_id": {
                        "depart": {"$min": ["$departure.city", "$arrival.city"]},
                        "arrivee": {"$max": ["$departure.city", "$arrival.city"]},
                    }
                }
            },
            {"$count": "n"},
        ],
        allowDiskUse=True,
    )
)
canon_n = canon[0]["n"] if canon else 0
print("paires ALLER-RETOUR fusionnees (Paris-Bordeaux = Bordeaux-Paris):", canon_n)

with_dept = list(
    col.aggregate(
        [
            {"$match": valid_match},
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
            {"$count": "n"},
        ],
        allowDiskUse=True,
    )
)
with_dept_n = with_dept[0]["n"] if with_dept else 0
print("combinaisons ville+dept (brut, oriente):", with_dept_n)

dist = list(
    col.aggregate(
        [
            {"$match": valid_match},
            {
                "$group": {
                    "_id": {
                        "depart": {"$min": ["$departure.city", "$arrival.city"]},
                        "arrivee": {"$max": ["$departure.city", "$arrival.city"]},
                    },
                    "n": {"$sum": 1},
                }
            },
            {
                "$group": {
                    "_id": None,
                    "avg": {"$avg": "$n"},
                    "max": {"$max": "$n"},
                    "min": {"$min": "$n"},
                }
            },
        ],
        allowDiskUse=True,
    )
)
if dist:
    d = dist[0]
    print()
    print("=== REPARTITION ===")
    print("moyenne transports par paire canonique:", round(d["avg"], 1))
    print("max transports sur une paire:", d["max"])
    print("min transports sur une paire:", d["min"])

top = list(
    col.aggregate(
        [
            {"$match": valid_match},
            {
                "$group": {
                    "_id": {
                        "depart": {"$min": ["$departure.city", "$arrival.city"]},
                        "arrivee": {"$max": ["$departure.city", "$arrival.city"]},
                    },
                    "n": {"$sum": 1},
                }
            },
            {"$sort": {"n": -1}},
            {"$limit": 5},
        ],
        allowDiskUse=True,
    )
)
print()
print("=== TOP 5 paires les plus frequentes ===")
for t in top:
    p = t["_id"]
    print(f"  {p['depart']} <-> {p['arrivee']}: {t['n']} transports")

client.close()
