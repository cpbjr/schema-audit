"""Configuration for Schema Audit Lead Generator."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# --- Paths ---
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "leads.db"
REPORTS_DIR = BASE_DIR / "reports"
TEMPLATES_DIR = BASE_DIR / "templates"

# --- API Keys ---
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")

# --- API URLs ---
PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_DETAILS_URL = "https://places.googleapis.com/v1/places"
PAGESPEED_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# --- Constants ---
PASSING_MOBILE_SCORE = 80
MAX_LCP_SECONDS = 2.5
REQUEST_TIMEOUT = 10


def ensure_directories() -> None:
    """Create output directories if they don't exist."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
