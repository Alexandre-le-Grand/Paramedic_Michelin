"""Compare la vitesse API selon le nombre de workers (test charge ViaMichelin)."""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.scraper.viamichelin_api import fetch_route_viamichelin

# Paires variées pour un mini benchmark
PAIRS = [
    ("Paris", "Lyon"),
    ("Marseille", "Nice"),
    ("Nantes", "Rennes"),
    ("Bordeaux", "Toulouse"),
    ("Lille", "Strasbourg"),
    ("Paris", "Marseille"),
    ("Lyon", "Grenoble"),
    ("Toulouse", "Montpellier"),
    ("Rennes", "Brest"),
]


def run_batch(workers: int) -> tuple[float, int, int]:
    ok = err = 0
    t0 = time.perf_counter()

    def task(pair: tuple[str, str]) -> str:
        d, a = pair
        r = fetch_route_viamichelin(d, a)
        return r.statut

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(task, p) for p in PAIRS]
        for fut in as_completed(futures):
            if fut.result() == "ok":
                ok += 1
            else:
                err += 1

    return time.perf_counter() - t0, ok, err


def main() -> None:
    print(f"Benchmark : {len(PAIRS)} trajets (itineraire standard avec peages)\n")
    for w in (1, 3, 5):
        elapsed, ok, err = run_batch(w)
        rate = len(PAIRS) / elapsed if elapsed > 0 else 0
        print(f"  workers={w} : {elapsed:.1f}s | {rate:.2f} trajet/s | ok={ok} err={err}")
    print("\nSi err augmente fortement avec 5, preferer 3 workers.")


if __name__ == "__main__":
    main()
