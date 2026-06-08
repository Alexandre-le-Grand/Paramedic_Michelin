"""Debug extraction km navigateur (ViaMichelinScraper)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.scraper.viamichelin import ViaMichelinScraper

DEPART = "Ablon-sur-Seine"
ARRIVEE = "Paris"

with ViaMichelinScraper(headless=True, use_browser=True) as scraper:
    result = scraper.fetch_route_browser(
        DEPART,
        ARRIVEE,
        arrivee_departement="Département de Paris",
    )
    print("statut:", result.statut)
    print("km:", result.distance_km)
    print("geo:", result.depart_lat, result.depart_lng, "->", result.arrivee_lat, result.arrivee_lng)
    if result.message_erreur:
        print("erreur:", result.message_erreur)
    print("raw:", "oui" if result.raw_response else "non")
