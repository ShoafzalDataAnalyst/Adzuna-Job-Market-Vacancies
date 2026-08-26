"""
cleaner.py — Turns raw API JSON into clean Python dicts.

Responsibility:
  - Text cleanup (whitespace, encoding)
  - Salary parsing
  - Skill normalization
  - Splitting location into country / city
  - Managing normalization maps (companies, locations, skills), so each
    unique value gets a single stable numeric id across the whole run

This module never touches requests or the database.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


# ── Helper functions ──────────────────────────────────────────────────────────

def clean_text(value) -> Optional[str]:
    """Collapses repeated whitespace into a single space and trims the ends."""
    if value is None:
        return None
    return re.sub(r"\s+", " ", str(value)).strip() or None


def normalize_skill(skill: str) -> Optional[str]:
    """Normalizes a skill name: lowercase, trimmed, dash characters unified."""
    if not skill:
        return None
    return skill.strip().lower().replace("–", "-").replace("—", "-")


def parse_salary(sal: dict | None) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Returns (min, max, currency); (None, None, None) if no salary data."""
    if not sal:
        return None, None, None
    return sal.get("from"), sal.get("to"), sal.get("currency")


def split_area(area_name: str) -> tuple[str, str]:
    """
    HH area names usually look like "Tashkent" or "Uzbekistan, Tashkent".
    Returns (country, city).
    """
    if not area_name:
        return "Uzbekistan", ""
    parts = [p.strip() for p in area_name.split(",")]
    if len(parts) == 1:
        # Only a city name was given, so default the country to Uzbekistan
        return "Uzbekistan", parts[0]
    return parts[0], parts[1]


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
        norm = normalize_skill(raw_name)
        if not norm:
            return None
        if norm not in self.skills:
            self.skills[norm] = {"id": self._skill_ctr, "name": norm}
            self._skill_ctr += 1
        return self.skills[norm]["id"]


# ── Main parser ────────────────────────────────────────────────────────────────

def parse_vacancy(detail: dict, store: NormalizationStore) -> tuple[dict, list[dict]]:
    """
    Converts a single vacancy JSON into a clean vacancy_row plus a list of
    vacancy_skill links.

    Returns:
        vacancy_row  — one row for the vacancies table
        skill_links  — [{"h_id": ..., "skill_id": ...}] for the vacancy_skill table
    """
    hid = detail.get("id")

    # ── Core fields ────────────────────────────────────────────────────────────
    title    = clean_text(detail.get("name"))
    category = _extract_category(detail)
    published_at = detail.get("published_at") or ""
    publish_date = published_at[:10] if published_at else None

    # ── Company ──────────────────────────────────────────────────────────────────
    employer     = detail.get("employer") or {}
    company_name = clean_text(employer.get("name"))
    company_site = employer.get("alternate_url")
    company_id   = store.get_or_add_company(company_name, company_site)

    # ── Location ─────────────────────────────────────────────────────────────────
    area_name  = (detail.get("area") or {}).get("name") or ""
    country, city = split_area(area_name)
    location_id   = store.get_or_add_location(country, city)

    # ── Salary ───────────────────────────────────────────────────────────────────
    min_sal, max_sal, currency = parse_salary(detail.get("salary"))

    # ── Skills ───────────────────────────────────────────────────────────────────
    raw_skills = [ks.get("name") for ks in (detail.get("key_skills") or []) if ks.get("name")]
    skill_ids  = [store.get_or_add_skill(s) for s in raw_skills]
    skill_ids  = [sid for sid in skill_ids if sid is not None]
    skill_names_norm = [normalize_skill(s) for s in raw_skills if normalize_skill(s)]

    vacancy_row = {
        "h_id":        hid,
        "title":       title,
        "position":    _infer_position(title),   # extracted from the title
        "category":    category,
        "publish_date": publish_date,
        "company":     company_name,
        "company_id":  company_id,
        "country":     country,
        "location":    city,
        "location_id": location_id,
        "min_salary":  min_sal,
        "max_salary":  max_sal,
        "currency":    currency,
        "skills":      ";".join(skill_names_norm),   # for CSV export and the dashboard
    }

    skill_links = [{"h_id": hid, "skill_id": sid} for sid in skill_ids]
    return vacancy_row, skill_links


# ── Internal helpers ────────────────────────────────────────────────────────────

def _extract_category(detail: dict) -> Optional[str]:
    """Extracts a category from HH's 'specializations' or 'professional_roles'."""
    # Current API field
    roles = detail.get("professional_roles") or []
    if roles:
        return clean_text(roles[0].get("name"))
    # Older API field, kept as a fallback
    specs = detail.get("specializations") or []
    if specs:
        sp = specs[0]
        return clean_text(sp.get("profarea_name") or sp.get("name"))
    return None


def _infer_position(title: str | None) -> Optional[str]:
    """
    Infers the job position from the vacancy title.
    Example: "Junior Data Analyst (Tashkent)" → "Junior Data Analyst"
    Could be replaced with an ML classifier in the future for better accuracy.
    """
    if not title:
        return None
    # Strips out parenthesized/bracketed extras
    clean = re.sub(r"\(.*?\)|\[.*?\]", "", title).strip()
    return clean or title
