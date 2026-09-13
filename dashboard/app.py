"""
app.py — Streamlit dashboard for the Data Analyst Vacancy Collector.

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
    page_title="Data Analyst Vacancy Dashboard",
    layout="wide",
)

# Path to the database created by the ETL pipeline (src/loader.py).
# Assumes this app is launched from the project root, matching the
# OUTPUT_DIR/DB_NAME defaults used by config.py.
DB_PATH = os.path.join("output", "adzuna.db")


@st.cache_data(ttl=3600)  # re-read the database at most once per hour
def load_data(db_path: str) -> dict[str, pd.DataFrame]:
    """Loads every dashboard view into a dict of DataFrames."""
    if not os.path.exists(db_path):
        return {}

    conn = sqlite3.connect(db_path)
    tables = {
        "vacancies_full":     "SELECT * FROM vw_vacancies_full",
        "skill_demand":       "SELECT * FROM vw_skill_demand ORDER BY vacancy_count DESC",
        "skill_by_country":   "SELECT * FROM vw_skill_demand_by_country",
        "salary_by_category": "SELECT * FROM vw_salary_by_category ORDER BY vacancy_count DESC",
        "daily_trend":        "SELECT * FROM vw_daily_posting_trend ORDER BY publish_date",
        "top_companies":      "SELECT * FROM vw_top_hiring_companies ORDER BY open_positions DESC",
        "country_summary":    "SELECT * FROM vw_country_summary ORDER BY vacancy_count DESC",
    }
    data = {name: pd.read_sql(query, conn) for name, query in tables.items()}
    conn.close()
    return data


# ── Load data ─────────────────────────────────────────────────────────────────
data = load_data(DB_PATH)

st.title("📊 Data Analyst Vacancy Dashboard")
st.caption("Live job market data collected from Adzuna, refreshed automatically.")

if not data:
    st.warning(
        "No database found yet. Run `python src/main.py` at least once "
        "to populate the dashboard."
    )
    st.stop()

df_vac_all  = data["vacancies_full"]
df_skill    = data["skill_demand"]
df_skill_c  = data["skill_by_country"]
df_sal      = data["salary_by_category"]
df_trend    = data["daily_trend"]
df_top      = data["top_companies"]
df_country  = data["country_summary"]

# Shows when the database file was last modified, so viewers know how
# fresh the data is (GitHub Actions updates this on its own schedule).
last_updated = datetime.fromtimestamp(os.path.getmtime(DB_PATH), tz=timezone.utc)
st.caption(f"Data last refreshed: {last_updated:%Y-%m-%d %H:%M UTC}")

# ── Country filter ────────────────────────────────────────────────────────────
# Since the pipeline can collect from several Adzuna markets at once
# (e.g. UK and US), let the viewer narrow to one, or compare all of them.
countries = ["All countries"] + sorted(df_vac_all["country"].dropna().unique().tolist())
selected_country = st.selectbox("Filter by country", countries)

if selected_country != "All countries":
    df_vac = df_vac_all[df_vac_all["country"] == selected_country]
else:
    df_vac = df_vac_all

st.divider()

# ── Top-line metrics ──────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("Active vacancies", len(df_vac))
col2.metric("Companies hiring", df_vac["company"].nunique())
col3.metric("Cities covered", df_vac["location"].nunique())
salary_disclosed_pct = (df_vac["min_salary_usd"].notna().mean() * 100) if len(df_vac) else 0
col4.metric("Salary disclosed", f"{salary_disclosed_pct:.1f}%")

st.divider()

# ── Country comparison (only shown when viewing all countries) ───────────────
if selected_country == "All countries" and len(df_country) > 1:
    st.subheader("Market comparison by country")
    left, right = st.columns(2)

    with left:
        fig = px.bar(
            df_country, x="country", y="vacancy_count",
            labels={"country": "Country", "vacancy_count": "Open vacancies"},
        )
        st.plotly_chart(fig, use_container_width=True)

    with right:
        fig = px.bar(
            df_country, x="country", y=["avg_min_salary_usd", "avg_max_salary_usd"],
            barmode="group",
            labels={"country": "Country", "value": "Average salary (USD)"},
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

# ── Row 1: posting trend + top skills ────────────────────────────────────────
left, right = st.columns(2)

with left:
    st.subheader("Vacancies posted over time")
    trend_data = df_trend if selected_country == "All countries" else \
        df_trend[df_trend["country"] == selected_country]
    fig = px.line(
        trend_data, x="publish_date", y="cumulative_total",
        color="country" if selected_country == "All countries" else None,
        labels={"publish_date": "Date", "cumulative_total": "Cumulative vacancies"},
    )
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Most in-demand skills")
    skill_data = df_skill if selected_country == "All countries" else \
        df_skill_c[df_skill_c["country"] == selected_country].sort_values(
            "vacancy_count", ascending=False
        )
    fig = px.bar(
        skill_data.head(15), x="vacancy_count", y="skill_name",
        orientation="h",
        labels={"vacancy_count": "Number of vacancies", "skill_name": "Skill"},
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)

# ── Row 2: top companies + salary by category ─────────────────────────────────
left, right = st.columns(2)

with left:
    st.subheader("Top hiring companies")
    top_data = df_top if selected_country == "All countries" else \
        df_top[df_top["country"] == selected_country]
    fig = px.bar(
        top_data.head(10), x="open_positions", y="company",
        orientation="h",
        labels={"open_positions": "Open positions", "company": "Company"},
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Average salary by category (USD)")
    sal_data = df_sal if selected_country == "All countries" else \
        df_sal[df_sal["country"] == selected_country]
    fig = px.bar(
        sal_data, x="category", y=["avg_min_usd", "avg_max_usd"],
        barmode="group",
        labels={"category": "Category", "value": "Average salary (USD)"},
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Raw data table ────────────────────────────────────────────────────────────
st.divider()
st.subheader("Browse all vacancies")
st.dataframe(
    df_vac[["title", "company", "country", "location", "category",
            "min_salary_usd", "max_salary_usd", "salary_is_predicted",
            "publish_date", "source_url"]],
    use_container_width=True,
    hide_index=True,
)