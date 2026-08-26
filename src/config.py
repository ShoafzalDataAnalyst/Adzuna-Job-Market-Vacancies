"""
config.py — All settings in one place.

Reads from a .env file so the pipeline can be reconfigured without touching
any other module. Every value has a sane default, so the project also runs
out of the box (e.g. inside GitHub Actions, where no .env file exists).
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── HeadHunter API ──────────────────────────────────────────────────────────
SEARCH_TEXT    = os.getenv("SEARCH_TEXT", "data analyst")
AREA_ID        = os.getenv("AREA_ID", "97")        # 97 = Uzbekistan
PER_PAGE       = int(os.getenv("PER_PAGE", "100"))
TEST_MODE      = os.getenv("TEST_MODE", "false").lower() == "true"
MAX_PAGES_TEST = int(os.getenv("MAX_PAGES_TEST", "3"))
REQUEST_DELAY  = float(os.getenv("REQUEST_DELAY", "0.2"))

HEADERS = {
    "User-Agent": os.getenv("USER_AGENT", "hh-uz-collector/2.0 (your@email.com)")
}

BASE_LIST_URL   = "https://api.hh.ru/vacancies"
BASE_DETAIL_URL = "https://api.hh.ru/vacancies/{}"

# ── Database (SQLite — free, file-based, no server required) ────────────────
# The database is a single file committed to the repo. GitHub Actions
# refreshes it on a schedule; Streamlit Cloud reads it to render the dashboard.
DB_NAME = os.getenv("DB_NAME", "headhunter")

# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
CSV_PREFIX = "hh_"
LOG_LEVEL  = os.getenv("LOG_LEVEL", "INFO")
