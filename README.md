# Data Analyst Job Market Dashboard

A live, self-updating dashboard tracking Data Analyst vacancies across the UK and US job markets — built entirely on free infrastructure.

**Live dashboard:** http://adzuna-job-market-vacancies.streamlit.app/

---

## What this project does

Every day, an automated pipeline collects live "Data Analyst" job postings from the [Adzuna](https://developer.adzuna.com/) API across two markets (UK and US), cleans and normalizes the data, extracts skill mentions from job descriptions, and loads everything into a SQLite database. A Streamlit dashboard reads that database and lets anyone — recruiters, hiring managers, or other job seekers — explore the market with zero setup, just a link.

No manual re-running, no local server, no paid infrastructure. Once configured, it maintains itself.

## Live features

- **Market comparison** — vacancy counts and average salaries side-by-side across countries
- **Skill demand ranking** — most-requested tools/skills, extracted directly from job descriptions and titles
- **Posting trend over time** — cumulative vacancies per market
- **Top hiring companies** — ranked by number of open positions
- **Salary by job category** — converted to a common USD basis for comparability
- **Searchable/browsable raw vacancy table** with direct links back to each listing

## Architecture

```
GitHub Actions (free, scheduled once daily)
        │
        ▼
  collector.py  →  cleaner.py  →  loader.py
  (Adzuna API)     (parsing,       (SQLite +
                    skill           dashboard
                    extraction)     views)
        │
        ▼
  adzuna.db (SQLite file, committed back to the repo automatically)
        │
        ▼
  Streamlit Community Cloud (dashboard/app.py)
        │
        ▼
  Public URL — anyone can open it, always showing the latest data
```

Nothing here requires a server, a paid database, or a machine that has to stay on. GitHub Actions runs the collection job on its own free cloud runners; Streamlit Cloud redeploys automatically whenever the database file changes.

## Tech stack

- **Python** — `requests`, `pandas`, `SQLAlchemy`
- **SQLite** — the entire database is a single file, version-controlled in the repo
- **Streamlit + Plotly** — the live dashboard
- **GitHub Actions** — scheduled automation, no infrastructure to maintain
- **Adzuna API** — job listings data source (UK + US)

## Project structure

```
├── .github/workflows/etl.yml   # scheduled automation (runs once daily)
├── dashboard/app.py            # the live Streamlit dashboard
├── sql/schema.sql              # database schema reference
├── src/
│   ├── config.py                # settings, env vars, country/currency maps
│   ├── collector.py             # talks to the Adzuna API
│   ├── cleaner.py               # parsing, normalization, skill extraction
│   ├── loader.py                # SQLite loading + dashboard views
│   └── main.py                  # orchestrates the full pipeline
├── output/adzuna.db             # the database itself (auto-updated)
├── env.example                  # template for local configuration
└── requirements.txt
```

## Running it yourself

1. Clone the repo
2. Get free Adzuna API credentials at [developer.adzuna.com](https://developer.adzuna.com/) — instant signup, no approval wait
3. Copy `env.example` to `.env` and fill in your `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`
4. Install dependencies: `pip install -r requirements.txt`
5. Run the pipeline: `python src/main.py`
6. Launch the dashboard locally: `streamlit run dashboard/app.py`

## How the automation works

`.github/workflows/etl.yml` runs the pipeline once every 24 hours on GitHub's free cloud infrastructure, then commits the refreshed database straight back to the repo. Streamlit Community Cloud watches the repo and redeploys automatically whenever that file changes — so the public dashboard always reflects the latest run, with no manual steps.

Two settings keep this sustainable on Adzuna's free tier (~1,000 API calls/month):
- Collection is capped at `MAX_PAGES_PER_COUNTRY` (default 10) pages per country per run
- The schedule runs once daily rather than more frequently

Both are configurable via environment variables if you have a higher API quota.

## Skill detection

Adzuna doesn't tag postings with structured skills the way some job APIs do, so skills are detected by scanning each posting's title and description against a known keyword list (see `SKILL_KEYWORDS` in `src/cleaner.py`). This list is easy to extend as new tools become relevant.

## Previous version

An earlier version of this project collected data from HeadHunter.uz using SQL Server and Power BI, targeting the Uzbekistan job market. HeadHunter's public API has since restricted unauthenticated access, so the project was rebuilt on Adzuna. The original version is preserved at [Release v1-hh-uz-sqlserver](../../releases/tag/v1-hh-uz-sqlserver) for reference.