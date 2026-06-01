import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

SQLITE_PATH = os.getenv("SQLITE_PATH", str(ROOT / "data" / "trajets.db"))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "paramedic_michelin")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "trajets")
SCRAPE_DELAY_SECONDS = float(os.getenv("SCRAPE_DELAY_SECONDS", "3"))
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "msedge")
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes")