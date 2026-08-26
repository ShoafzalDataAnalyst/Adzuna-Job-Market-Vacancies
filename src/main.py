"""
main.py — ETL pipeline orchestrator.

Usage:
    python src/main.py

Environment variables (.env):
    TEST_MODE=true   → only 3 pages (quick test run)
    TEST_MODE=false  → full collection

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
    log.info("HeadHunter ETL started")
    log.info("Search: '%s' | Area: %s | TEST_MODE: %s",
             config.SEARCH_TEXT, config.AREA_ID, config.TEST_MODE)
    log.info("=" * 60)

    # ── 1. Area ID ─────────────────────────────────────────────────────────────
    area_id = config.AREA_ID
    if not area_id:
        log.info("AREA_ID not set, looking it up via the API...")
        area_id = collector.find_area_id()
        if not area_id:
            log.critical("Could not find Uzbekistan's area_id. Stopping.")
            sys.exit(1)
    log.info("Area ID: %s", area_id)

    # ── 2. Collect vacancy ids ────────────────────────────────────────────────
    store = cleaner.NormalizationStore()
    vacancy_rows: list[dict] = []
    skill_links:  list[dict] = []
    seen_ids: set = set()

    for vac_id in collector.iter_vacancy_ids(area_id, config.SEARCH_TEXT):
        if vac_id in seen_ids:
            continue
        seen_ids.add(vac_id)

        detail = collector.fetch_vacancy_detail(vac_id)
        if not detail:
            log.warning("No detail found for: %s", vac_id)
            continue

        vac_row, links = cleaner.parse_vacancy(detail, store)
        vacancy_rows.append(vac_row)
        skill_links.extend(links)

    log.info("Collected %d unique vacancies in total", len(vacancy_rows))

    if not vacancy_rows:
        log.warning("No data found — nothing to load.")
        return

    # ── 3. Build DataFrames ───────────────────────────────────────────────────
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
        "min_salary", "max_salary", "currency"
    ]]

    log.info("Vacancies: %d | Companies: %d | Locations: %d | Skills: %d | Links: %d",
             len(df_vac_db), len(df_companies), len(df_locations),
             len(df_skills), len(df_vacancy_skill))

    # ── 4. Save CSV snapshots ─────────────────────────────────────────────────
    loader.save_csv(df_vac_db,        "vacancies")
    loader.save_csv(df_companies,     "companies")
    loader.save_csv(df_locations,     "locations")
    loader.save_csv(df_skills,        "skills")
    loader.save_csv(df_vacancy_skill, "vacancy_skill")

    # ── 5. Load into the database ─────────────────────────────────────────────
    try:
        engine = loader.build_engine()
        stats  = loader.load_all(
            df_vac_db, df_companies, df_locations,
            df_skills, df_vacancy_skill, engine
        )
        log.info("Database load results: %s", stats)

        # ── 6. Dashboard views ────────────────────────────────────────────────
        loader.create_dashboard_views(engine)
        log.info("Dashboard views created successfully.")

    except Exception as exc:
        log.error("Database error: %s", exc)
        log.info("CSV files were still saved and can be used independently.")

    log.info("ETL finished successfully.")


if __name__ == "__main__":
    run()
