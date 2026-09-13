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
    skill_links:  list[dict] = []
    seen_ids: set = set()

    for country in config.ADZUNA_COUNTRIES:
        log.info("Collecting from country: %s", country)
        for job in collector.iter_jobs(country, config.SEARCH_TEXT):
            vac_row, links = cleaner.parse_vacancy(job, store)
            if vac_row["h_id"] in seen_ids:
                continue
            seen_ids.add(vac_row["h_id"])
            vacancy_rows.append(vac_row)
            skill_links.extend(links)

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

    df_companies = pd.DataFrame.from_records(
        [{"id": v["id"], "name": v["name"], "website": v["website"]}
         for v in store.companies.values()]
    )
    df_locations = pd.DataFrame.from_records(
        [{"id": v["id"], "country": v["country"], "city": v["city"]}
         for v in store.locations.values()]
    )
    df_skills = pd.DataFrame.from_records(
        [{"id": v["id"], "name": v["name"]}
         for v in store.skills.values()]
    )
    df_vacancy_skill = pd.DataFrame(skill_links).drop_duplicates()

    # Columns written to the database (foreign key ids stay in the CSVs only)
    df_vac_db = df_vac[[
        "h_id", "title", "position", "category", "publish_date",
        "company", "skills", "country", "location",
        "min_salary", "max_salary", "currency", "salary_is_predicted", "source_url"
    ]]

    log.info("Vacancies: %d | Companies: %d | Locations: %d | Skills: %d | Links: %d",
             len(df_vac_db), len(df_companies), len(df_locations),
             len(df_skills), len(df_vacancy_skill))

    # ── 3. Save CSV snapshots ─────────────────────────────────────────────────
    loader.save_csv(df_vac_db,        "vacancies")
    loader.save_csv(df_companies,     "companies")
    loader.save_csv(df_locations,     "locations")
    loader.save_csv(df_skills,        "skills")
    loader.save_csv(df_vacancy_skill, "vacancy_skill")

    # ── 4. Load into the database ─────────────────────────────────────────────
    try:
        engine = loader.build_engine()
        stats  = loader.load_all(
            df_vac_db, df_companies, df_locations,
            df_skills, df_vacancy_skill, engine
        )
        log.info("Database load results: %s", stats)

        # ── 5. Dashboard views ────────────────────────────────────────────────
        loader.create_dashboard_views(engine)
        log.info("Dashboard views created successfully.")

    except Exception as exc:
        log.error("Database error: %s", exc)
        log.info("CSV files were still saved and can be used independently.")

    log.info("ETL finished successfully.")


if __name__ == "__main__":
    run()
