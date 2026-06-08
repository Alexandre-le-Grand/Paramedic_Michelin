"""Stats Paris / Marseille dans transports et trajets Mongo."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient
from config.settings import (
    MONGO_COLLECTION,
    MONGO_DB,
    MONGO_URI,
    PARAMEDIC_DB,
    TRANSPORTS_COLLECTION,
)

client = MongoClient(MONGO_URI)
trans = client[PARAMEDIC_DB][TRANSPORTS_COLLECTION]
traj = client[MONGO_DB][MONGO_COLLECTION]

for city in ("Paris", "Marseille"):
    n = trans.count_documents(
        {"$or": [{"departure.city": city}, {"arrival.city": city}]}
    )
    pairs = list(
        trans.aggregate(
            [
                {
                    "$match": {
                        "$or": [
                            {"departure.city": city},
                            {"arrival.city": city},
                        ]
                    }
                },
                {
                    "$project": {
                        "dep": "$departure.city",
                        "arr": "$arrival.city",
                        "dep_dept": "$departure.department",
                        "arr_dept": "$arrival.department",
                    }
                },
                {"$limit": 3},
            ]
        )
    )
    print(f"\n=== {city} : {n} transports ===")
    for p in pairs:
        print(p)

    mongo_n = traj.count_documents(
        {"$or": [{"depart": city}, {"arrivee": city}]}
    )
    print(f"Trajets Mongo avec {city}: {mongo_n}")
    sample = traj.find_one({"$or": [{"depart": city}, {"arrivee": city}]})
    if sample:
        print("Champs Mongo:", {k: sample.get(k) for k in ("depart", "arrivee", "depart_departement", "arrivee_departement")})

# departments distincts pour Paris/Marseille
for city in ("Paris", "Marseille"):
    depts = trans.aggregate(
        [
            {"$match": {"departure.city": city}},
            {"$group": {"_id": "$departure.department", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
        ]
    )
    print(f"\nDepartements departure.city={city}:")
    for d in depts:
        print(f"  {d['_id']}: {d['n']}")

client.close()
