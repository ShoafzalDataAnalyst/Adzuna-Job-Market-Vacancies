"""
loader.py — Writes DataFrames to SQLite and exports CSV files.

Responsibilities:
  - Create the SQLAlchemy engine (SQLite, file-based, no server needed)
  - Upsert logic (insert new rows, skip ones that already exist by primary key)
  - Save CSV snapshots for portability / manual inspection
  - Create SQL views used by the dashboard
"""

import os
import logging

import pandas as pd
from sqlalchemy import create_engine, text, inspect

import config

log = logging.getLogger(__name__)


# ── Engine ────────────────────────────────────────────────────────────────────

def build_engine():
    """
    Returns a SQLAlchemy engine pointing at a local SQLite file.

    SQLite is used instead of SQL Server because it needs no installed
    server, no credentials, and no network access — it is just a single
    file that lives inside the repository. This is what makes the whole
    pipeline runnable for free inside GitHub Actions.
    """
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    db_path = os.path.join(config.OUTPUT_DIR, f"{config.DB_NAME}.db")
    return create_engine(f"sqlite:///{db_path}")


# ── CSV export ────────────────────────────────────────────────────────────────

def save_csv(df: pd.DataFrame, name: str) -> str:
    """Saves a DataFrame to the output/ folder and returns its path."""
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    path = os.path.join(config.OUTPUT_DIR, f"{config.CSV_PREFIX}{name}.csv")
    df.to_csv(path, index=False, encoding="utf-8-sig")   # utf-8-sig plays nicely with Excel
    log.info("CSV saved: %s (%d rows)", path, len(df))
    return path


# ── Database loading ────────────────────────────────────────────────────────

def upsert_table(df: pd.DataFrame, table: str, pk: str, engine) -> int:
    """
    Inserts only the rows whose primary key does not already exist in the
    table. This keeps the pipeline idempotent — running it many times a day
    never creates duplicate vacancies.

    On the very first run the table doesn't exist yet (no manual schema
    setup is required), so an empty "existing" set is used instead.
    """
    if df.empty:
        return 0

    if inspect(engine).has_table(table):
        with engine.connect() as conn:
            existing = pd.read_sql(f'SELECT "{pk}" FROM "{table}"', conn)
        existing_set = set(existing[pk].astype(str))
    else:
        existing_set = set()

    new_rows = df[~df[pk].astype(str).isin(existing_set)]
    if new_rows.empty:
        log.info("%s: no new rows (all already present)", table)
        return 0

    new_rows.to_sql(table, con=engine, if_exists="append", index=False)
    log.info("%s: %d new rows added", table, len(new_rows))
    return len(new_rows)


def load_all(
    df_vacancies:     pd.DataFrame,
    df_companies:     pd.DataFrame,
    df_locations:     pd.DataFrame,
    df_skills:        pd.DataFrame,
    df_vacancy_skill: pd.DataFrame,
    engine,
) -> dict:
    """Loads every table in dependency order and returns row-count stats."""
    stats = {}
    # Reference tables first, to satisfy foreign key relationships
    stats["companies"]     = upsert_table(df_companies,     "companies",     "id",   engine)
    stats["locations"]     = upsert_table(df_locations,     "locations",     "id",   engine)
    stats["skills"]        = upsert_table(df_skills,        "skills",        "id",   engine)
    stats["vacancies"]     = upsert_table(df_vacancies,     "vacancies",     "h_id", engine)
    # vacancy_skill has a composite key (h_id, skill_id)
    stats["vacancy_skill"] = _upsert_vacancy_skill(df_vacancy_skill, engine)
    return stats


def _upsert_vacancy_skill(df: pd.DataFrame, engine) -> int:
    """Avoids duplicate rows in the vacancy_skill many-to-many table."""
    if df.empty:
        return 0

    if inspect(engine).has_table("vacancy_skill"):
        with engine.connect() as conn:
            existing = pd.read_sql("SELECT h_id, skill_id FROM vacancy_skill", conn)
        existing_keys = set(existing["h_id"].astype(str) + "_" + existing["skill_id"].astype(str))
    else:
        existing_keys = set()
    df = df.copy()
    df["_key"] = df["h_id"].astype(str) + "_" + df["skill_id"].astype(str)
    new_rows = df[~df["_key"].isin(existing_keys)].drop(columns=["_key"])

    if new_rows.empty:
        return 0
    new_rows.to_sql("vacancy_skill", con=engine, if_exists="append", index=False)
    log.info("vacancy_skill: %d new links added", len(new_rows))
    return len(new_rows)


# ── Dashboard views ───────────────────────────────────────────────────────────
# These views pre-aggregate the data so the Streamlit dashboard can run a
# single simple SELECT instead of repeating complex logic in Python.
# SQLite has no "CREATE OR ALTER VIEW", so we drop and recreate each one.

DASHBOARD_VIEWS = {

    "vw_vacancies_full": """
        CREATE VIEW vw_vacancies_full AS
        SELECT
            v.h_id,
            v.title,
            v.position,
            v.category,
            v.publish_date,
            v.company,
            v.country,
            v.location,
            v.min_salary,
            v.max_salary,
            v.currency,
            -- Rough USD conversion so salaries are comparable across currencies
            CASE v.currency
                WHEN 'UZS' THEN v.min_salary / 12500.0
                WHEN 'USD' THEN v.min_salary
                WHEN 'EUR' THEN v.min_salary * 1.08
                ELSE v.min_salary
            END AS min_salary_usd,
            CASE v.currency
                WHEN 'UZS' THEN v.max_salary / 12500.0
                WHEN 'USD' THEN v.max_salary
                WHEN 'EUR' THEN v.max_salary * 1.08
                ELSE v.max_salary
            END AS max_salary_usd,
            v.skills
        FROM vacancies v
    """,

    "vw_skill_demand": """
        CREATE VIEW vw_skill_demand AS
        SELECT
            s.name          AS skill_name,
            COUNT(vs.h_id)  AS vacancy_count,
            COUNT(DISTINCT v.company) AS company_count
        FROM skills s
        JOIN vacancy_skill vs ON vs.skill_id = s.id
        JOIN vacancies v      ON v.h_id = vs.h_id
        GROUP BY s.name
    """,

    "vw_salary_by_category": """
        CREATE VIEW vw_salary_by_category AS
        SELECT
            category,
            COUNT(*) AS vacancy_count,
            AVG(CASE currency WHEN 'UZS' THEN min_salary / 12500.0
                              WHEN 'EUR' THEN min_salary * 1.08
                              ELSE min_salary END) AS avg_min_usd,
            AVG(CASE currency WHEN 'UZS' THEN max_salary / 12500.0
                              WHEN 'EUR' THEN max_salary * 1.08
                              ELSE max_salary END) AS avg_max_usd
        FROM vacancies
        WHERE category IS NOT NULL
        GROUP BY category
    """,

    "vw_daily_posting_trend": """
        CREATE VIEW vw_daily_posting_trend AS
        SELECT
            publish_date,
            COUNT(*)                AS vacancies_posted,
            COUNT(DISTINCT company) AS unique_companies,
            SUM(COUNT(*)) OVER (ORDER BY publish_date ROWS UNBOUNDED PRECEDING)
                                     AS cumulative_total
        FROM vacancies
        GROUP BY publish_date
    """,

    "vw_top_hiring_companies": """
        CREATE VIEW vw_top_hiring_companies AS
        SELECT
            v.company,
            c.website,
            COUNT(v.h_id)       AS open_positions,
            MIN(v.publish_date) AS first_posted,
            MAX(v.publish_date) AS last_posted,
            AVG(CASE v.currency WHEN 'UZS' THEN v.max_salary / 12500.0
                                ELSE v.max_salary END) AS avg_max_salary_usd
        FROM vacancies v
        LEFT JOIN companies c ON c.name = v.company
        GROUP BY v.company, c.website
    """,

    "vw_location_heatmap": """
        CREATE VIEW vw_location_heatmap AS
        SELECT
            country,
            location AS city,
            COUNT(*) AS vacancy_count,
            COUNT(DISTINCT company) AS company_count,
            AVG(CASE currency WHEN 'UZS' THEN min_salary / 12500.0
                              ELSE min_salary END) AS avg_min_usd
        FROM vacancies
        GROUP BY country, location
    """,
}


def create_dashboard_views(engine) -> None:
    """(Re)creates every dashboard view. Safe to call on every pipeline run."""
    with engine.connect() as conn:
        for view_name, ddl in DASHBOARD_VIEWS.items():
            try:
                conn.execute(text(f"DROP VIEW IF EXISTS {view_name}"))
                conn.execute(text(ddl))
                conn.commit()
                log.info("View created: %s", view_name)
            except Exception as exc:
                log.error("View error (%s): %s", view_name, exc)
