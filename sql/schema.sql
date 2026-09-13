-- ============================================================
-- Data Analyst Vacancy Collector — SQLite Schema (Adzuna source)
-- ============================================================
-- Run manually only if you want to inspect the structure ahead of time.
-- In normal use, loader.py creates these tables automatically via
-- pandas.to_sql() on the first pipeline run, so this file is
-- documentation as much as it is a script.

CREATE TABLE IF NOT EXISTS companies (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    website TEXT
);

CREATE TABLE IF NOT EXISTS locations (
    id      INTEGER PRIMARY KEY,
    country TEXT NOT NULL,
    city    TEXT
);

CREATE TABLE IF NOT EXISTS skills (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS vacancies (
    -- h_id is TEXT, not an integer: it's built as "{country_code}_{adzuna_id}"
    -- (e.g. "gb_4821093") because we collect from several Adzuna country
    -- markets into the same table, and Adzuna's own ids are only
    -- guaranteed unique within a single country.
    h_id                 TEXT PRIMARY KEY,
    title                TEXT,
    position             TEXT,
    category             TEXT,
    publish_date         TEXT,     -- stored as ISO date string (YYYY-MM-DD)
    company              TEXT,
    skills               TEXT,     -- semicolon-separated skill keywords found in the posting
    country              TEXT,     -- human-readable country name, e.g. "United Kingdom"
    location             TEXT,     -- city
    min_salary           REAL,
    max_salary           REAL,
    currency             TEXT,
    salary_is_predicted  INTEGER,  -- 1 if Adzuna estimated the salary, 0 if advertised
    source_url           TEXT      -- link back to the original listing
);

CREATE INDEX IF NOT EXISTS ix_vac_date     ON vacancies(publish_date);
CREATE INDEX IF NOT EXISTS ix_vac_company  ON vacancies(company);
CREATE INDEX IF NOT EXISTS ix_vac_category ON vacancies(category);
CREATE INDEX IF NOT EXISTS ix_vac_country  ON vacancies(country);

CREATE TABLE IF NOT EXISTS vacancy_skill (
    h_id     TEXT    NOT NULL,
    skill_id INTEGER NOT NULL,
    PRIMARY KEY (h_id, skill_id),
    FOREIGN KEY (h_id)     REFERENCES vacancies(h_id),
    FOREIGN KEY (skill_id) REFERENCES skills(id)
);
