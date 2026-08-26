"""
collector.py — Sends vacancy list and detail requests to the HeadHunter API.

Responsibility (single responsibility principle):
  - Talk to the API
  - Return raw JSON data
  - Handle retries and rate limiting

This module never touches the database or pandas — it only knows about
HTTP requests.
"""

import time
import logging
import requests
from typing import Generator

import config

log = logging.getLogger(__name__)


def _get(url: str, params: dict = None, retries: int = 3) -> dict | None:
    """Sends a GET request, retrying on network errors or rate limiting."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, headers=config.HEADERS, timeout=30)
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


def find_area_id(name_hints: tuple = ("uzbekistan", "ўзбекистон", "uzbek")) -> str | None:
    """Finds Uzbekistan's area id from HH's list of areas."""
    data = _get("https://api.hh.ru/areas")
    if not data:
        return None

    def _search(nodes: list) -> str | None:
        for node in nodes:
            if any(h in (node.get("name") or "").lower() for h in name_hints):
                return node["id"]
            children = node.get("areas") or node.get("items") or []
            found = _search(children)
            if found:
                return found
        return None

    return _search(data)


def iter_vacancy_ids(area_id: str, search_text: str) -> Generator[str, None, None]:
    """
    Yields vacancy ids page by page (generator).
    Memory-efficient: only one page of results is held in memory at a time.
    """
    page = 0
    total_pages = None

    while True:
        params = {
            "area": area_id,
            "text": search_text,
            "page": page,
            "per_page": config.PER_PAGE,
        }
        data = _get(config.BASE_LIST_URL, params=params)
        if not data:
            log.error("List request failed (page %d)", page)
            break

        if total_pages is None:
            total_pages = data.get("pages", 1)
            log.info("Total pages: %d", total_pages)

        items = data.get("items", [])
        if not items:
            log.info("Page %d is empty — stopping", page)
            break

        for item in items:
            yield item["id"]

        log.info("Page %d/%d — %d ids retrieved", page + 1, total_pages, len(items))
        page += 1

        if config.TEST_MODE and page >= config.MAX_PAGES_TEST:
            log.info("TEST_MODE: stopped after %d pages", config.MAX_PAGES_TEST)
            break
        if page >= total_pages:
            break

        time.sleep(config.REQUEST_DELAY)


def fetch_vacancy_detail(vacancy_id: str) -> dict | None:
    """Returns the full JSON details for a single vacancy."""
    url = config.BASE_DETAIL_URL.format(vacancy_id)
    detail = _get(url)
    time.sleep(config.REQUEST_DELAY)
    return detail
