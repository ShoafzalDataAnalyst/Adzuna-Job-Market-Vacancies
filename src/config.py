"""
config.py — All settings in one place.

Reads from a .env file so the pipeline can be reconfigured without touching
any other module. Every value has a sane default, so the project also runs
out of the box (e.g. inside GitHub Actions, where no .env file exists).
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Adzuna API ────────────────────────────────────────────────────────────────
# Free instant signup at https://developer.adzuna.com/ — no manual approval,
# unlike HeadHunter's API, which now requires employer verification.
ADZUNA_APP_ID  = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")

# Comma-separated list of Adzuna country codes to collect from.
# Supported by Adzuna: gb, us, at, au, br, ca, de, fr, in, it, mx, nl, pl, ru, sg, za
# Collecting from more than one country lets the dashboard compare markets
# (e.g. "UK vs US data analyst demand") side by side.
ADZUNA_COUNTRIES = [c.strip() for c in os.getenv("ADZUNA_COUNTRIES", "gb,us").split(",") if c.strip()]

# Human-readable country names and currency codes, keyed by Adzuna's country code.
COUNTRY_NAMES = {
    "gb": "United Kingdom", "us": "United States", "au": "Australia",
    "ca": "Canada", "de": "Germany", "fr": "France", "in": "India",
    "it": "Italy", "nl": "Netherlands", "pl": "Poland", "sg": "Singapore",
    "za": "South Africa", "br": "Brazil", "mx": "Mexico", "at": "Austria",
    "ru": "Russia",
}
COUNTRY_CURRENCY = {
    "gb": "GBP", "us": "USD", "au": "AUD", "ca": "CAD", "de": "EUR",
    "fr": "EUR", "in": "INR", "it": "EUR", "nl": "EUR", "pl": "PLN",
    "sg": "SGD", "za": "ZAR", "br": "BRL", "mx": "MXN", "at": "EUR",
    "ru": "RUB",
}

SEARCH_TEXT       = os.getenv("SEARCH_TEXT", "data analyst")
RESULTS_PER_PAGE  = int(os.getenv("RESULTS_PER_PAGE", "50"))   # Adzuna's max per page
TEST_MODE         = os.getenv("TEST_MODE", "false").lower() == "true"
MAX_PAGES_TEST    = int(os.getenv("MAX_PAGES_TEST", "2"))
REQUEST_DELAY     = float(os.getenv("REQUEST_DELAY", "0.3"))

BASE_SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

# ── Database (SQLite — free, file-based, no server required) ────────────────
# The database is a single file committed to the repo. GitHub Actions
# refreshes it on a schedule; Streamlit Cloud reads it to render the dashboard.
DB_NAME = os.getenv("DB_NAME", "headhunter")

# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
CSV_PREFIX = "hh_"
LOG_LEVEL  = os.getenv("LOG_LEVEL", "INFO")
