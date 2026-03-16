"""Configuration for Schema Audit Lead Generator."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# --- Paths (env vars allow same code to run locally and on server) ---
BASE_DIR = Path(__file__).parent
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", str(BASE_DIR / "reports")))
TEMPLATES_DIR = Path(os.getenv("TEMPLATES_DIR", str(BASE_DIR / "templates")))

# --- Supabase ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# --- API Keys ---
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY", "")

# --- Auth ---
WPA_AUDIT_API_KEY = os.getenv("WPA_AUDIT_API_KEY", "")

# --- Rate Limiting ---
DAILY_DISCOVERY_LIMIT = int(os.getenv("DAILY_DISCOVERY_LIMIT", "5"))

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
