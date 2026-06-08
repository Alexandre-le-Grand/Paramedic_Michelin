import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

SQLITE_PATH = os.getenv("SQLITE_PATH", str(ROOT / "data" / "trajets.db"))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "paramedic_michelin")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "trajets")
# Base patron (dump transports)
PARAMEDIC_DB = os.getenv("PARAMEDIC_DB", "paramedic")
TRANSPORTS_COLLECTION = os.getenv("TRANSPORTS_COLLECTION", "transports")
# csv = data/trajets.csv | transports = paramedic.transports (apres mongorestore)
TRAJETS_SOURCE = os.getenv("TRAJETS_SOURCE", "transports").strip().lower()
SCRAPE_DELAY_SECONDS = float(os.getenv("SCRAPE_DELAY_SECONDS", "0.5"))
# Requetes ViaMichelin en parallele (API uniquement ; 1 = sequentiel)
SCRAPE_WORKERS = max(1, min(10, int(os.getenv("SCRAPE_WORKERS", "5"))))
# Retry HTTP 429/502/503/504 (serveur ViaMichelin sature)
SCRAPE_RETRY_MAX = max(1, int(os.getenv("SCRAPE_RETRY_MAX", "5")))
SCRAPE_RETRY_BASE_SECONDS = float(os.getenv("SCRAPE_RETRY_BASE_SECONDS", "2"))
# Appels HTTP ViaMichelin en parallele (limite la saturation 503)
SCRAPE_API_CONCURRENCY = max(1, min(10, int(os.getenv("SCRAPE_API_CONCURRENCY", "3"))))
# Secours navigateur si API 503/429 (defaut false ; activer via --browser-fallback)
SCRAPE_BROWSER_FALLBACK = os.getenv("SCRAPE_BROWSER_FALLBACK", "false").lower() in (
    "1",
    "true",
    "yes",
)
# OSRM si ViaMichelin vmrest en 503 (defaut : desactive ; activer via --osrm)
SCRAPE_OSRM_FALLBACK = os.getenv("SCRAPE_OSRM_FALLBACK", "false").lower() in (
    "1",
    "true",
    "yes",
)
OSRM_BASE_URL = os.getenv(
    "OSRM_BASE_URL", "https://router.project-osrm.org"
).rstrip("/")

BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "msedge")
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "true").lower() in ("1", "true", "yes")
BROWSER_SLOW_MO_MS = int(os.getenv("BROWSER_SLOW_MO_MS", "0" if BROWSER_HEADLESS else "50"))
SCRAPE_TIMEOUT_MS = int(os.getenv("SCRAPE_TIMEOUT_MS", "120000"))
