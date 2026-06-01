"""Affiche le nombre de paires ville->ville uniques dans paramedic.transports."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.db.transports_repository import TransportsRepository

repo = TransportsRepository()
try:
    print(f"Documents transports : {repo.count_documents()}")
    routes = repo.load_unique_routes()
    print(f"Paires uniques (villes) : {len(routes)}")
    for pair in routes[:5]:
        print(f"  {pair[0]} -> {pair[1]}")
finally:
    repo.close()
