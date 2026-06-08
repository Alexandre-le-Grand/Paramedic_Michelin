"""Compare volumes transports vs trajets inscrits en MongoDB."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import (
    MONGO_COLLECTION,
    MONGO_DB,
    MONGO_URI,
    PARAMEDIC_DB,
    TRANSPORTS_COLLECTION,
)
from pymongo import MongoClient
from src.db.mongo_repository import MongoRepository
from src.db.transports_repository import TransportsRepository

client = MongoClient(MONGO_URI)
trans = client[PARAMEDIC_DB][TRANSPORTS_COLLECTION]

total = trans.count_documents({})
with_cities = trans.count_documents(
    {
        "departure.city": {"$exists": True, "$type": "string", "$ne": ""},
        "arrival.city": {"$exists": True, "$type": "string", "$ne": ""},
        "$expr": {"$ne": ["$departure.city", "$arrival.city"]},
    }
)
same_city = trans.count_documents(
    {
        "departure.city": {"$exists": True},
        "$expr": {"$eq": ["$departure.city", "$arrival.city"]},
    }
)
no_city = total - trans.count_documents(
    {
        "departure.city": {"$exists": True, "$type": "string", "$ne": ""},
        "arrival.city": {"$exists": True, "$type": "string", "$ne": ""},
    }
)

pipe_oriented = [
    {
        "$match": {
            "departure.city": {"$exists": True, "$type": "string", "$ne": ""},
            "arrival.city": {"$exists": True, "$type": "string", "$ne": ""},
            "$expr": {"$ne": ["$departure.city", "$arrival.city"]},
        }
    },
    {"$group": {"_id": {"d": "$departure.city", "a": "$arrival.city"}}},
    {"$count": "n"},
]
oriented = list(trans.aggregate(pipe_oriented, allowDiskUse=True))[0]["n"]

pipe_canon = [
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
    {"$count": "n"},
]
canon = list(trans.aggregate(pipe_canon, allowDiskUse=True))[0]["n"]

pipe_coverage = [
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
            },
            "n": {"$sum": 1},
        }
    },
    {"$group": {"_id": None, "pairs": {"$sum": 1}, "transports": {"$sum": "$n"}}},
]
cov = list(trans.aggregate(pipe_coverage, allowDiskUse=True))[0]

repo = MongoRepository()
mongo_traj = repo.count_all()
routes_loaded = len(TransportsRepository().load_unique_routes())
repo.close()
client.close()

print("=== paramedic.transports (base patron) ===")
print(f"Transports totaux              : {total:,}")
print(f"Sans ville depart/arrivee valide : {no_city:,}")
print(f"Meme ville (depart = arrivee)    : {same_city:,}")
print(f"Utilisables (2 villes differentes): {with_cities:,} lignes")
print()
print(f"Paires ORIENTEES uniques         : {oriented:,}")
print("  (Paris->Bordeaux et Bordeaux->Paris comptent pour 2)")
print()
print(f"Paires CANONIQUES uniques        : {canon:,}")
print("  (aller-retour fusionne = 1 seul calcul km)")
print()
print("=== paramedic_michelin.trajets (ton projet) ===")
print(f"Documents inscrits (seed)      : {mongo_traj:,}")
print(f"load_unique_routes()           : {routes_loaded:,}")
print()
print("=== Couverture si on propage le km par paire de villes ===")
print(f"Transports inter-villes a renseigner : {cov['transports']:,}")
print(f"  (repetent en moyenne {cov['transports']/cov['pairs']:.1f}x la meme paire)")
print(f"Transports meme ville (km ~0)       : {same_city:,}")
print(f"Total                               : {total:,}")
print()
if mongo_traj == canon == routes_loaded:
    print("OK : MongoDB contient bien TOUTES les paires canoniques possibles.")
    print("     Apres run, chaque transport inter-villes peut recevoir son km par jointure.")
else:
    print("ATTENTION : ecart entre Mongo et transports.")
