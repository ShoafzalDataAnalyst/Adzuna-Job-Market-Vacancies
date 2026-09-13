"""
collector.py — Sends job search requests to the Adzuna API.

Responsibility (single responsibility principle):
  - Talk to the API
  - Return raw JSON data
  - Handle retries and rate limiting

This module never touches the database or pandas — it only knows about
HTTP requests.

Note: unlike the old HeadHunter integration, Adzuna's search endpoint
returns full job details (title, company, salary, description, etc.) in
a single call per page — there is no separate "fetch detail by id" step.
"""

import time
import logging
from typing import Generator

import requests

import config

log = logging.getLogger(__name__)


def _get(url: str, params: dict, retries: int = 3) -> dict | None:
    """Sends a GET request, retrying on network errors or rate limiting."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:          # Too Many Requests
                wait = 2 ** attempt
                log.warning("Rate-limited. Waiting %d s...", wait)
                time.sleep(wait)
                continue
            log.warning("HTTP %d: %s", resp.status_code, url)
            return None
        except requests.RequestException as exc:
            log.error("Request failed (attempt %d/%d): %s", attempt, retries, exc)
            time.sleep(attempt)
    return None


def iter_jobs(country: str, search_text: str) -> Generator[dict, None, None]:
    """
    Yields raw job dicts, page by page, for a single Adzuna country.
    Memory-efficient generator: only one page of results is held in memory
    at a time.
    """
    page = 1
    total_seen = 0

    while True:
        url = config.BASE_SEARCH_URL.format(country=country, page=page)
        params = {
            "app_id": config.ADZUNA_APP_ID,
            "app_key": config.ADZUNA_APP_KEY,
            "results_per_page": config.RESULTS_PER_PAGE,
            "what": search_text,
            "content-type": "application/json",
        }

        data = _get(url, params)
        if not data:
            log.error("[%s] Search request failed (page %d)", country, page)
            break

        results = data.get("results", [])
        if not results:
            log.info("[%s] Page %d is empty — stopping", country, page)
            break

        for job in results:
            job["_country"] = country   # tag each job with its source country
            yield job

        total_seen += len(results)
        log.info("[%s] Page %d — %d jobs retrieved (running total: %d)",
                  country, page, len(results), total_seen)

        page += 1
        if config.TEST_MODE and page > config.MAX_PAGES_TEST:
            log.info("[%s] TEST_MODE: stopped after %d pages", country, config.MAX_PAGES_TEST)
            break

        time.sleep(config.REQUEST_DELAY)
