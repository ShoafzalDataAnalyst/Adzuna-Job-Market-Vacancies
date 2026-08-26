"""
app.py — Streamlit dashboard for the HeadHunter Vacancy Collector.

Reads directly from the SQLite database produced by the ETL pipeline
(src/main.py) and renders live charts. Deployed for free on Streamlit
Community Cloud, this file is what gives anyone (e.g. an HR reviewer)
a single link that always shows the latest data — no install required.

Run locally with:
    streamlit run dashboard/app.py
"""

import os
import sqlite3
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import streamlit as st

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="HH.uz Data Analyst Vacancies",
    layout="wide",
)

# Path to the database created by the ETL pipeline (src/loader.py).
# Assumes this app is launched from the project root, matching the
# OUTPUT_DIR/DB_NAME defaults used by config.py.
DB_PATH = os.path.join("output", "headhunter.db")


@st.cache_data(ttl=3600)  # re-read the database at most once per hour
def load_data(db_path: str) -> dict[str, pd.DataFrame]:
    """Loads every dashboard view into a dict of DataFrames."""
    if not os.path.exists(db_path):
        return {}

    conn = sqlite3.connect(db_path)
    tables = {
        "vacancies_full":    "SELECT * FROM vw_vacancies_full",
        "skill_demand":      "SELECT * FROM vw_skill_demand ORDER BY vacancy_count DESC",
        "salary_by_category": "SELECT * FROM vw_salary_by_category ORDER BY vacancy_count DESC",
        "daily_trend":       "SELECT * FROM vw_daily_posting_trend ORDER BY publish_date",
        "top_companies":     "SELECT * FROM vw_top_hiring_companies ORDER BY open_positions DESC",
    }
    data = {name: pd.read_sql(query, conn) for name, query in tables.items()}
    conn.close()
    return data


# ── Load data ─────────────────────────────────────────────────────────────────
data = load_data(DB_PATH)

st.title("📊 HH.uz — Data Analyst Vacancy Dashboard")

if not data:
    st.warning(
        "No database found yet. Run `python src/main.py` at least once "
        "to populate the dashboard."
    )
    st.stop()

df_vac   = data["vacancies_full"]
df_skill = data["skill_demand"]
df_sal   = data["salary_by_category"]
df_trend = data["daily_trend"]
df_top   = data["top_companies"]

# Shows when the database file was last modified, so viewers know how
# fresh the data is (GitHub Actions updates this on its own schedule).
last_updated = datetime.fromtimestamp(os.path.getmtime(DB_PATH), tz=timezone.utc)
st.caption(f"Data last refreshed: {last_updated:%Y-%m-%d %H:%M UTC}")

# ── Top-line metrics ──────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("Active vacancies", len(df_vac))
col2.metric("Companies hiring", df_vac["company"].nunique())
col3.metric("Cities covered", df_vac["location"].nunique())
salary_disclosed_pct = df_vac["min_salary_usd"].notna().mean() * 100
col4.metric("Salary disclosed", f"{salary_disclosed_pct:.1f}%")

st.divider()

# ── Row 1: posting trend + top skills ────────────────────────────────────────
left, right = st.columns(2)

with left:
    st.subheader("Vacancies posted over time")
    fig = px.line(
        df_trend, x="publish_date", y="cumulative_total",
        labels={"publish_date": "Date", "cumulative_total": "Cumulative vacancies"},
    )
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Most in-demand skills")
    fig = px.bar(
        df_skill.head(15), x="vacancy_count", y="skill_name",
        orientation="h",
        labels={"vacancy_count": "Number of vacancies", "skill_name": "Skill"},
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)

# ── Row 2: top companies + salary by category ─────────────────────────────────
left, right = st.columns(2)

with left:
    st.subheader("Top hiring companies")
    fig = px.bar(
        df_top.head(10), x="open_positions", y="company",
        orientation="h",
        labels={"open_positions": "Open positions", "company": "Company"},
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Average salary by category (USD)")
    fig = px.bar(
        df_sal, x="category", y=["avg_min_usd", "avg_max_usd"],
        barmode="group",
        labels={"category": "Category", "value": "Average salary (USD)"},
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Raw data table ────────────────────────────────────────────────────────────
st.divider()
st.subheader("Browse all vacancies")
st.dataframe(
    df_vac[["title", "company", "location", "category",
            "min_salary_usd", "max_salary_usd", "publish_date"]],
    use_container_width=True,
    hide_index=True,
)
