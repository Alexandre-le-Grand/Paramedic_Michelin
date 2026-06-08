import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient
from config.settings import MONGO_DB, MONGO_COLLECTION, MONGO_URI, PARAMEDIC_DB, TRANSPORTS_COLLECTION

client = MongoClient(MONGO_URI)
traj = client[MONGO_DB][MONGO_COLLECTION]
trans = client[PARAMEDIC_DB][TRANSPORTS_COLLECTION]

for city in ("Abbeville", "Abbéville", "Abbéville-la-Rivière"):
    n = traj.count_documents(
        {"$or": [{"depart": city}, {"arrivee": city}]}
    )
    print(f"trajets {city!r}: {n}")

docs = list(
    traj.find(
        {"depart": {"$regex": "^Abb", "$options": "i"}},
        {"depart": 1, "arrivee": 1, "distance_km": 1, "statut": 1},
    ).limit(10)
)
print("trajets depart Abb*:")
for d in docs:
    print(f"  {d.get('depart')} -> {d.get('arrivee')} km={d.get('distance_km')} {d.get('statut')}")

# distance attendue Abbéville (80) -> Le Plessis-Robinson
pair = traj.find_one({"depart": "Abbéville-la-Rivière", "arrivee": "Le Plessis-Robinson"})
if not pair:
    pair = traj.find_one(
        {
            "$or": [
                {"depart": "Abbéville-la-Rivière"},
                {"depart": "Abbeville"},
            ],
            "arrivee": "Le Plessis-Robinson",
        }
    )
print("pair mongo:", pair)

client.close()
