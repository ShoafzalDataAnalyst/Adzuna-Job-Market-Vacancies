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
import plotly.graph_objects as go
import streamlit as st


ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
ICON_PATH = os.path.join(ASSETS_DIR, "icon.png")

favicon = ICON_PATH if os.path.exists(ICON_PATH) else "📊"

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Data Analyst Vacancy Dashboard",
    page_icon=favicon,
    layout="wide",
    initial_sidebar_state="expanded",
)

COUNTRY_COLORS = {
    "United Kingdom": "#00247D",   # Union Jack blue
    "United States":  "#B22234",   # Old Glory red
}
COUNTRY_COLORS_SECONDARY = {
    "United Kingdom": "#CF142B",   # Union Jack red
    "United States":  "#3C3B6E",   # Old Glory navy
}
DEFAULT_ACCENT = "#4F8BF9"
DEFAULT_ACCENT_DARK = "#2E5FCC"

# Light custom styling: rounded metric cards and tighter spacing. Kept minimal
# on purpose — Streamlit's own theme already handles dark mode and layout;
# this just polishes the parts that look most "default" out of the box.
st.markdown(f"""
    <style>
        div[data-testid="stMetric"] {{
            background-color: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 10px;
            padding: 14px 18px;
        }}
        div[data-testid="stMetricValue"] {{
            font-size: 1.6rem;
        }}
        .block-container {{
            padding-top: 2rem;
        }}
    </style>
""", unsafe_allow_html=True)

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


def apply_chart_theme(fig: go.Figure) -> go.Figure:
    """Applies one consistent look to every Plotly chart in the app."""
    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return fig


# ── Load data ─────────────────────────────────────────────────────────────────
data = load_data(DB_PATH)

if not data:
    st.title("Data Analyst Vacancy Dashboard")
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

last_updated = datetime.fromtimestamp(os.path.getmtime(DB_PATH), tz=timezone.utc)

# ── Sidebar: branding, context, and filters ───────────────────────────────────
with st.sidebar:
    if not os.path.exists(LOGO_PATH):
        st.markdown("## 📊 Vacancy Dashboard")
    st.caption("Data Analyst job market, tracked automatically.")
    st.divider()

    countries = ["All countries"] + sorted(df_vac_all["country"].dropna().unique().tolist())
    selected_country = st.selectbox("Filter by country", countries)

    st.divider()
    st.caption(f"🕒 Data refreshed: {last_updated:%d %b %Y, %H:%M UTC}")

    with st.expander("ℹ️ About this dashboard"):
        st.markdown(
            "Collected daily from the [Adzuna](https://developer.adzuna.com/) "
            "job search API. Skills are detected by scanning job titles and "
            "descriptions against a known keyword list. Salaries are "
            "converted to an approximate USD figure for cross-country "
            "comparison.\n\n"
            "Built with Python, SQLite, and Streamlit — automated end-to-end "
            "with GitHub Actions on free infrastructure."
        )

if selected_country != "All countries":
    df_vac = df_vac_all[df_vac_all["country"] == selected_country]
    # When one country is selected, theme the whole dashboard around its flag colors
    ACCENT = COUNTRY_COLORS.get(selected_country, DEFAULT_ACCENT)
    ACCENT_DARK = COUNTRY_COLORS_SECONDARY.get(selected_country, DEFAULT_ACCENT_DARK)
else:
    df_vac = df_vac_all
    ACCENT = DEFAULT_ACCENT
    ACCENT_DARK = DEFAULT_ACCENT_DARK

# ── Header ────────────────────────────────────────────────────────────────────
st.title("Data Analyst Job Market")
st.caption(
    "Live vacancy tracking across the UK and US — updated daily, no manual work."
)

# ── Top-line metrics ──────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("Active vacancies", f"{len(df_vac):,}")
col2.metric("Companies hiring", f"{df_vac['company'].nunique():,}")
col3.metric("Cities covered", f"{df_vac['location'].nunique():,}")
salary_disclosed_pct = (df_vac["min_salary_usd"].notna().mean() * 100) if len(df_vac) else 0
col4.metric("Salary disclosed", f"{salary_disclosed_pct:.0f}%")

st.write("")

# ── Tabbed sections — keeps the dashboard scannable instead of one long scroll
tab_overview, tab_skills, tab_companies, tab_browse = st.tabs(
    ["📈 Overview", "🛠️ Skills & Trends", "🏢 Companies & Salary", "🔎 Browse Vacancies"]
)

# ── Tab 1: Overview ───────────────────────────────────────────────────────────
with tab_overview:
    if selected_country == "All countries" and len(df_country) > 1:
        st.subheader("Market comparison by country")
        left, right = st.columns(2)

        with left:
            fig = px.bar(
                df_country, x="country", y="vacancy_count",
                labels={"country": "Country", "vacancy_count": "Open vacancies"},
                color="country", color_discrete_map=COUNTRY_COLORS,
            )
            fig.update_layout(showlegend=False)
            st.plotly_chart(apply_chart_theme(fig), use_container_width=True)

        with right:
            fig = px.bar(
                df_country, x="country", y=["avg_min_salary_usd", "avg_max_salary_usd"],
                barmode="group",
                labels={"country": "Country", "value": "Average salary (USD)", "variable": ""},
                color="country", color_discrete_map=COUNTRY_COLORS,
                pattern_shape="variable", pattern_shape_sequence=["", "/"],
            )
            st.plotly_chart(apply_chart_theme(fig), use_container_width=True)
    else:
        st.info(f"Showing {selected_country} only. Switch to \"All countries\" in the sidebar to compare markets.")

    st.subheader("Vacancies posted over time")
    trend_data = df_trend if selected_country == "All countries" else \
        df_trend[df_trend["country"] == selected_country]
    fig = px.area(
        trend_data, x="publish_date", y="cumulative_total",
        color="country" if selected_country == "All countries" else None,
        labels={"publish_date": "Date", "cumulative_total": "Cumulative vacancies"},
        color_discrete_map=COUNTRY_COLORS if selected_country == "All countries" else None,
        color_discrete_sequence=None if selected_country == "All countries" else [ACCENT],
    )
    st.plotly_chart(apply_chart_theme(fig), use_container_width=True)

# ── Tab 2: Skills & Trends ────────────────────────────────────────────────────
with tab_skills:
    st.subheader("Most in-demand skills")
    skill_data = df_skill if selected_country == "All countries" else \
        df_skill_c[df_skill_c["country"] == selected_country].sort_values(
            "vacancy_count", ascending=False
        )
    fig = px.bar(
        skill_data.head(15), x="vacancy_count", y="skill_name",
        orientation="h",
        labels={"vacancy_count": "Number of vacancies", "skill_name": ""},
        color_discrete_sequence=[ACCENT],
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(apply_chart_theme(fig), use_container_width=True)

    st.subheader("Average salary by category (USD)")
    sal_data = df_sal if selected_country == "All countries" else \
        df_sal[df_sal["country"] == selected_country]
    fig = px.bar(
        sal_data, x="category", y=["avg_min_usd", "avg_max_usd"],
        barmode="group",
        labels={"category": "Category", "value": "Average salary (USD)", "variable": ""},
        color_discrete_sequence=[ACCENT, ACCENT_DARK],
    )
    st.plotly_chart(apply_chart_theme(fig), use_container_width=True)

# ── Tab 3: Companies & Salary ─────────────────────────────────────────────────
with tab_companies:
    st.subheader("Top hiring companies")
    top_data = df_top if selected_country == "All countries" else \
        df_top[df_top["country"] == selected_country]
    fig = px.bar(
        top_data.head(12), x="open_positions", y="company",
        orientation="h",
        labels={"open_positions": "Open positions", "company": ""},
        color_discrete_sequence=[ACCENT],
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(apply_chart_theme(fig), use_container_width=True)

    st.subheader("Company details")
    st.dataframe(
        top_data[["company", "country", "open_positions", "first_posted",
                  "last_posted", "avg_max_salary_usd"]].head(20),
        use_container_width=True,
        hide_index=True,
    )

# ── Tab 4: Browse Vacancies ────────────────────────────────────────────────────
with tab_browse:
    st.subheader("Search and browse all vacancies")

    search = st.text_input("🔎 Search by title or company", "")
    df_browse = df_vac
    if search:
        mask = (
            df_browse["title"].str.contains(search, case=False, na=False)
            | df_browse["company"].str.contains(search, case=False, na=False)
        )
        df_browse = df_browse[mask]

    st.caption(f"Showing {len(df_browse):,} of {len(df_vac):,} vacancies")
    st.dataframe(
        df_browse[["title", "company", "country", "location", "category",
                   "min_salary_usd", "max_salary_usd", "salary_is_predicted",
                   "publish_date", "source_url"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "source_url": st.column_config.LinkColumn("Listing", display_text="Open ↗"),
            "min_salary_usd": st.column_config.NumberColumn("Min salary (USD)", format="$%.0f"),
            "max_salary_usd": st.column_config.NumberColumn("Max salary (USD)", format="$%.0f"),
        },
    )