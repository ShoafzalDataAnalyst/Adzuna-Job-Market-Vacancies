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
#
# Approximate currency-to-USD rates, used only to make cross-country salary
# comparisons readable on the dashboard. These are fixed, illustrative rates,
# not live exchange rates — good enough for a portfolio project, not for
# financial decisions.
_FX_TO_USD_CASE = """
    CASE currency
        WHEN 'USD' THEN 1.0
        WHEN 'GBP' THEN 1.27
        WHEN 'EUR' THEN 1.08
        WHEN 'AUD' THEN 0.66
        WHEN 'CAD' THEN 0.73
        WHEN 'INR' THEN 0.012
        WHEN 'PLN' THEN 0.25
        WHEN 'SGD' THEN 0.74
        WHEN 'ZAR' THEN 0.055
        WHEN 'BRL' THEN 0.18
        WHEN 'MXN' THEN 0.05
        WHEN 'RUB' THEN 0.011
        ELSE 1.0
    END
"""

DASHBOARD_VIEWS = {

    "vw_vacancies_full": f"""
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
            v.salary_is_predicted,
            v.source_url,
            -- Approximate USD conversion so salaries are comparable across countries
            v.min_salary * ({_FX_TO_USD_CASE}) AS min_salary_usd,
            v.max_salary * ({_FX_TO_USD_CASE}) AS max_salary_usd,
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

    "vw_skill_demand_by_country": """
        CREATE VIEW vw_skill_demand_by_country AS
        SELECT
            v.country,
            s.name         AS skill_name,
            COUNT(vs.h_id) AS vacancy_count
        FROM skills s
        JOIN vacancy_skill vs ON vs.skill_id = s.id
        JOIN vacancies v      ON v.h_id = vs.h_id
        GROUP BY v.country, s.name
    """,

    "vw_salary_by_category": f"""
        CREATE VIEW vw_salary_by_category AS
        SELECT
            category,
            country,
            COUNT(*) AS vacancy_count,
            AVG(min_salary * ({_FX_TO_USD_CASE})) AS avg_min_usd,
            AVG(max_salary * ({_FX_TO_USD_CASE})) AS avg_max_usd
        FROM vacancies
        WHERE category IS NOT NULL
        GROUP BY category, country
    """,

    "vw_daily_posting_trend": """
        CREATE VIEW vw_daily_posting_trend AS
        SELECT
            publish_date,
            country,
            COUNT(*)                AS vacancies_posted,
            COUNT(DISTINCT company) AS unique_companies,
            SUM(COUNT(*)) OVER (PARTITION BY country ORDER BY publish_date ROWS UNBOUNDED PRECEDING)
                                     AS cumulative_total
        FROM vacancies
        GROUP BY publish_date, country
    """,

    "vw_top_hiring_companies": f"""
        CREATE VIEW vw_top_hiring_companies AS
        SELECT
            v.company,
            v.country,
            COUNT(v.h_id)       AS open_positions,
            MIN(v.publish_date) AS first_posted,
            MAX(v.publish_date) AS last_posted,
            AVG(v.max_salary * ({_FX_TO_USD_CASE})) AS avg_max_salary_usd
        FROM vacancies v
        GROUP BY v.company, v.country
    """,

    "vw_country_summary": f"""
        CREATE VIEW vw_country_summary AS
        SELECT
            country,
            COUNT(*)                       AS vacancy_count,
            COUNT(DISTINCT company)        AS company_count,
            AVG(min_salary * ({_FX_TO_USD_CASE})) AS avg_min_salary_usd,
            AVG(max_salary * ({_FX_TO_USD_CASE})) AS avg_max_salary_usd
        FROM vacancies
        GROUP BY country
    """,

    "vw_location_heatmap": f"""
        CREATE VIEW vw_location_heatmap AS
        SELECT
            country,
            location AS city,
            COUNT(*) AS vacancy_count,
            COUNT(DISTINCT company) AS company_count,
            AVG(min_salary * ({_FX_TO_USD_CASE})) AS avg_min_usd
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
