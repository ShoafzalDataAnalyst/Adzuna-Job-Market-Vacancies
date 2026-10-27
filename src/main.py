"""
main.py — ETL pipeline orchestrator.

Usage:
    python src/main.py

Environment variables (.env):
    TEST_MODE=true   → only 2 pages per country (quick test run)
    TEST_MODE=false  → full collection
    ADZUNA_COUNTRIES=gb,us → which country markets to collect from

This script is also what GitHub Actions runs on a schedule to keep the
database — and therefore the live dashboard — up to date automatically.
"""

import logging
import sys

import pandas as pd

import config
import collector
import cleaner
import loader

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("etl.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("main")


def run():
    log.info("=" * 60)
    log.info("Adzuna ETL started")
    log.info("Search: '%s' | Countries: %s | TEST_MODE: %s",
             config.SEARCH_TEXT, config.ADZUNA_COUNTRIES, config.TEST_MODE)
    log.info("=" * 60)

    if not config.ADZUNA_APP_ID or not config.ADZUNA_APP_KEY:
        log.critical(
            "ADZUNA_APP_ID / ADZUNA_APP_KEY are not set. "
            "Get free instant credentials at https://developer.adzuna.com/ "
            "and add them to your .env file."
        )
        sys.exit(1)

    # ── 1. Collect jobs from every configured country ────────────────────────
    store = cleaner.NormalizationStore()
    vacancy_rows: list[dict] = []
    seen_ids: set = set()

    for country in config.ADZUNA_COUNTRIES:
        log.info("Collecting from country: %s", country)
        for job in collector.iter_jobs(country, config.SEARCH_TEXT):
            vac_row, _ = cleaner.parse_vacancy(job, store)
            if vac_row["h_id"] in seen_ids:
                continue
            seen_ids.add(vac_row["h_id"])
            vacancy_rows.append(vac_row)

    log.info("Collected %d unique vacancies in total", len(vacancy_rows))

    if not vacancy_rows:
        log.warning("No data found — nothing to load.")
        return

    # ── 2. Build DataFrames ───────────────────────────────────────────────────
    df_vac = (
        pd.DataFrame(vacancy_rows)
        .drop_duplicates(subset=["h_id"], keep="first")
        .reset_index(drop=True)
    )

    # Columns written to the database
    df_vac_db = df_vac[[
        "h_id", "title", "position", "category", "publish_date",
        "company", "skills", "country", "location",
        "min_salary", "max_salary", "currency", "salary_is_predicted", "source_url"
    ]]

    log.info("Vacancies collected this run: %d", len(df_vac_db))

    # ── 3. Save CSV snapshot ──────────────────────────────────────────────────
    loader.save_csv(df_vac_db, "vacancies")

    # ── 4. Load into the database ─────────────────────────────────────────────
    try:
        engine = loader.build_engine()
        stats  = loader.load_all(df_vac_db, engine)
        log.info("Database load results: %s", stats)

        # ── 5. Dashboard views ────────────────────────────────────────────────
        loader.create_dashboard_views(engine)
        log.info("Dashboard views created successfully.")

        # ── 6. Power BI exports ───────────────────────────────────────────────
        loader.export_views_for_powerbi(engine)
        log.info("Power BI CSV exports complete.")

    except Exception as exc:
        log.error("Database error: %s", exc)
        log.info("CSV files were still saved and can be used independently.")

    log.info("ETL finished successfully.")


if __name__ == "__main__":
    run()
