"""EURIBOR rate fetcher + parser.

Source: https://www.euribor-rates.eu/en/current-euribor-rates/
        https://www.euribor-rates.eu/en/euribor-rates-by-year/{year}/
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

import httpx
from bs4 import BeautifulSoup

from app.services.rates.robor import ParsedInterestRate

logger = logging.getLogger(__name__)

EURIBOR_URL = "https://www.euribor-rates.eu/en/current-euribor-rates/"


def euribor_year_url(year: int) -> str:
    return f"https://www.euribor-rates.eu/en/euribor-rates-by-year/{year}/"


# Map header tokens like "1-week", "1-month", "12-month" to standard tenors.
_TENOR_RE = re.compile(r"euribor\s+(\d+)[\s-]?(week|month)", re.IGNORECASE)


def _header_to_tenor(header: str) -> str | None:
    m = _TENOR_RE.search(header)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "week":
        return f"{n}W"
    if unit == "month":
        return f"{n}M"
    return None


def _parse_us_or_iso_date(raw: str) -> str | None:
    """Accept '3/6/2026' (M/D/YYYY) or '2026-03-06' (ISO)."""
    raw = raw.strip()
    if "/" in raw:
        parts = raw.split("/")
        if len(parts) == 3:
            try:
                m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
                return f"{y:04d}-{m:02d}-{d:02d}"
            except ValueError:
                return None
    if "-" in raw and len(raw) == 10:
        # already ISO
        return raw
    return None


def parse_euribor_html(html: str) -> list[ParsedInterestRate]:
    if not html or not html.strip():
        return []
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []
    thead = table.find("thead")
    tbody = table.find("tbody")
    if thead is None or tbody is None:
        return []

    headers = [th.get_text(strip=True) for th in thead.find_all("th")]
    if not headers:
        return []
    column_tenors: list[str | None] = [None]  # column 0 is the date column
    for h in headers[1:]:
        column_tenors.append(_header_to_tenor(h))

    out: list[ParsedInterestRate] = []
    for tr in tbody.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < 2:
            continue
        date = _parse_us_or_iso_date(cells[0])
        if not date:
            continue
        for i in range(1, min(len(cells), len(column_tenors))):
            tenor = column_tenors[i]
            if tenor is None:
                continue
            try:
                rate = float(cells[i])
            except ValueError:
                continue
            out.append(ParsedInterestRate(
                date=date, rate_type="EURIBOR", tenor=tenor, rate=rate,
            ))
    return out


def _fetch(url: str, client: httpx.Client | None) -> list[ParsedInterestRate]:
    own = client is None
    if own:
        client = httpx.Client(timeout=30.0)
    try:
        r = client.get(url)
    except httpx.RequestError as e:
        logger.error("[rates/euribor] HTTP error for %s: %s", url, e)
        return []
    finally:
        if own:
            client.close()
    if r.status_code != 200:
        logger.warning("[rates/euribor] %d for %s", r.status_code, url)
        return []
    return parse_euribor_html(r.text)


def fetch_euribor_current(client: httpx.Client | None = None) -> list[ParsedInterestRate]:
    return _fetch(EURIBOR_URL, client)


def fetch_euribor_year(year: int, client: httpx.Client | None = None) -> list[ParsedInterestRate]:
    return _fetch(euribor_year_url(year), client)
