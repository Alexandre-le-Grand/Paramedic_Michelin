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

BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "msedge")
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "true").lower() in ("1", "true", "yes")
BROWSER_SLOW_MO_MS = int(os.getenv("BROWSER_SLOW_MO_MS", "0" if BROWSER_HEADLESS else "50"))
SCRAPE_TIMEOUT_MS = int(os.getenv("SCRAPE_TIMEOUT_MS", "120000"))

# ViaMichelin vmrest : avoidTolls=true = eviter les peages (defaut)
VIAMICHELIN_AVOID_TOLLS = os.getenv("VIAMICHELIN_AVOID_TOLLS", "true").lower() in (
    "1",
    "true",
    "yes",
)
