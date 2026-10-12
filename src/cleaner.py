"""
cleaner.py — Turns raw Adzuna job JSON into clean Python dicts.

Responsibility:
  - Text cleanup (whitespace, encoding)
  - Skill extraction (Adzuna has no structured skills field, unlike
    HeadHunter's key_skills — so we scan title + description against a
    known list of data-analyst-relevant skill keywords instead)
  - Splitting the parsed location hierarchy into country / city
  - Managing normalization maps (companies, locations, skills), so each
    unique value gets a single stable numeric id across the whole run

This module never touches requests or the database.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

import config

log = logging.getLogger(__name__)


# ── Skill keyword dictionary ───────────────────────────────────────────────────
# Adzuna doesn't tag structured skills like HeadHunter did, so we detect
# mentions of common data-analyst-relevant tools/skills directly from the
# job title and description text. This list can be extended over time.
#
# Each skill maps to the spellings that count as a mention of it. Matching
# uses word boundaries, so "excel" does not fire inside "excellent", "git"
# inside "digital", "sas" inside "Kansas", or "aws" inside "laws".
SKILL_KEYWORDS = {
    "sql":              ["sql"],
    "python":           ["python"],
    "r programming":    ["r programming", "rstudio", "r studio"],
    "excel":            ["excel"],
    "power bi":         ["power bi", "powerbi", "power-bi"],
    "tableau":          ["tableau"],
    "looker":           ["looker"],
    "dax":              ["dax"],
    "vba":              ["vba"],
    "sas":              ["sas"],
    "spss":             ["spss"],
    "aws":              ["aws", "amazon web services"],
    "azure":            ["azure"],
    "gcp":              ["gcp", "google cloud"],
    "snowflake":        ["snowflake"],
    "spark":            ["apache spark", "pyspark"],
    "hadoop":           ["hadoop"],
    "airflow":          ["airflow"],
    "dbt":              ["dbt"],
    "etl":              ["etl"],
    "machine learning": ["machine learning"],
    "statistics":       ["statistics", "statistical"],
    "powerpoint":       ["powerpoint"],
    "git":              ["git", "github", "gitlab"],
    "javascript":       ["javascript"],
    "mongodb":          ["mongodb"],
    "nosql":            ["nosql"],
    "postgresql":       ["postgresql", "postgres"],
    "mysql":            ["mysql"],
    "bigquery":         ["bigquery"],
    "redshift":         ["redshift"],
}

# "excel" is also an everyday verb ("excel in a fast-paced environment"), so
# a mention followed by "in" or "at" is not counted as the spreadsheet tool.
_SKILL_TAILS = {"excel": r"(?!\s+(?:in|at)\b)"}


def _compile_skill_pattern(skill: str, aliases: list[str]) -> re.Pattern:
    """Builds one regex per skill that only matches whole words/phrases."""
    body = "|".join(re.escape(a) for a in aliases)
    return re.compile(rf"(?<![a-z0-9])(?:{body})(?![a-z0-9]){_SKILL_TAILS.get(skill, '')}")


# Compiled once at import time, not once per vacancy.
_SKILL_PATTERNS = {s: _compile_skill_pattern(s, a) for s, a in SKILL_KEYWORDS.items()}


# ── Helper functions ──────────────────────────────────────────────────────────

def clean_text(value) -> Optional[str]:
    """Collapses repeated whitespace into a single space and trims the ends."""
    if value is None:
        return None
    return re.sub(r"\s+", " ", str(value)).strip() or None


def extract_skills(title: str, description: str) -> list[str]:
    """Scans title + description text for known skills (whole-word matches only)."""
    haystack = f"{title or ''} {description or ''}".lower()
    return [skill for skill, pattern in _SKILL_PATTERNS.items() if pattern.search(haystack)]


def parse_flag(value) -> bool:
    """
    Normalises a 0/1 flag that an API may send as a number (1) or as text ("1").
    Plain bool("0") is True in Python because any non-empty string is truthy,
    which would silently mark every row as True.
    """
    return str(value).strip().lower() in ("1", "true")


def split_location(area: list) -> tuple[str, str]:
    """
    Adzuna's location "area" field is a hierarchy list, e.g.
    ["UK", "South East England", "Buckinghamshire", "Marlow"].
    Returns (country, city) — country is the first element, city the last.
    """
    if not area:
        return "Unknown", "Unknown"
    country = area[0]
    city = area[-1] if len(area) > 1 else area[0]
    return country, city


# ── Normalization state ───────────────────────────────────────────────────────

@dataclass
class NormalizationStore:
    """
    Holds the companies, locations, and skills mappings.
    A single instance is shared across the whole ETL run so that the same
    company/location/skill always maps to the same numeric id.
    """
    companies: dict  = field(default_factory=dict)   # name  → {id, name, website}
    locations: dict  = field(default_factory=dict)   # key   → {id, country, city}
    skills:    dict  = field(default_factory=dict)   # norm  → {id, name}

    _company_ctr:  int = field(default=1, repr=False)
    _location_ctr: int = field(default=1, repr=False)
    _skill_ctr:    int = field(default=1, repr=False)

    def get_or_add_company(self, name: str, website: str | None) -> int | None:
        if not name:
            return None
        if name not in self.companies:
            self.companies[name] = {"id": self._company_ctr, "name": name, "website": website}
            self._company_ctr += 1
        return self.companies[name]["id"]

    def get_or_add_location(self, country: str, city: str) -> int:
        key = f"{country}|{city}"
        if key not in self.locations:
            self.locations[key] = {"id": self._location_ctr, "country": country, "city": city}
            self._location_ctr += 1
        return self.locations[key]["id"]

    def get_or_add_skill(self, raw_name: str) -> int | None:
        norm = raw_name.strip().lower() if raw_name else None
        if not norm:
            return None
        if norm not in self.skills:
            self.skills[norm] = {"id": self._skill_ctr, "name": norm}
            self._skill_ctr += 1
        return self.skills[norm]["id"]


# ── Main parser ────────────────────────────────────────────────────────────────

def parse_vacancy(job: dict, store: NormalizationStore) -> tuple[dict, list[dict]]:
    """
    Converts a single Adzuna job JSON into a clean vacancy_row plus a list
    of vacancy_skill links.

    Returns:
        vacancy_row  — one row for the vacancies table
        skill_links  — [{"h_id": ..., "skill_id": ...}] for the vacancy_skill table
    """
    country_code = job.get("_country", "")
    # Prefix the id with the country code: Adzuna ids are not guaranteed
    # unique *across* countries, only within one, and we collect from
    # several countries into the same table.
    hid = f"{country_code}_{job.get('id')}"

    title       = clean_text(job.get("title"))
    description = clean_text(job.get("description"))
    category    = clean_text((job.get("category") or {}).get("label"))
    created     = job.get("created") or ""
    publish_date = created[:10] if created else None

    # ── Company ──────────────────────────────────────────────────────────────
    company_name = clean_text((job.get("company") or {}).get("display_name"))
    company_id   = store.get_or_add_company(company_name, None)  # Adzuna has no company website field

    # ── Location ─────────────────────────────────────────────────────────────
    area = (job.get("location") or {}).get("area") or []
    country, city = split_location(area)
    location_id   = store.get_or_add_location(country, city)

    # ── Salary ───────────────────────────────────────────────────────────────
    min_sal  = job.get("salary_min")
    max_sal  = job.get("salary_max")
    currency = config.COUNTRY_CURRENCY.get(country_code, "USD")
    is_predicted = parse_flag(job.get("salary_is_predicted", 0))

    # ── Skills (keyword-extracted, since Adzuna has no structured field) ──────
    raw_skills = extract_skills(title, description)
    skill_ids  = [store.get_or_add_skill(s) for s in raw_skills]
    skill_ids  = [sid for sid in skill_ids if sid is not None]

    vacancy_row = {
        "h_id":          hid,
        "title":         title,
        "position":      title,   # Adzuna has no separate "role" field; title doubles as position
        "category":      category,
        "publish_date":  publish_date,
        "company":       company_name,
        "country":       config.COUNTRY_NAMES.get(country_code, country),
        "location":      city,
        "min_salary":    min_sal,
        "max_salary":    max_sal,
        "currency":      currency,
        "salary_is_predicted": is_predicted,
        "skills":        ";".join(raw_skills),   # for CSV export and the dashboard
        "source_url":    job.get("redirect_url"),
    }

    skill_links = [{"h_id": hid, "skill_id": sid} for sid in skill_ids]
    return vacancy_row, skill_links
