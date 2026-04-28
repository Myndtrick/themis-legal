"""EURIBOR rate fetcher + parser.

Source: https://www.euribor-rates.eu/en/current-euribor-rates/
        https://www.euribor-rates.eu/en/euribor-rates-by-year/{year}/

Real-page structure (verified live, 2026-04-28):
  TRANSPOSED table — dates run across the header row, tenors run down the
  first column. Cells are "1.915 %" etc.

      |          | 4/24/2026 | 4/23/2026 | 4/22/2026 | ...
      | 1 week   | 1.915 %   | 1.922 %   | 1.904 %   | ...
      | 1 month  | 1.968 %   | ...
      | ...
"""
from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from app.services.rates.robor import ParsedInterestRate

logger = logging.getLogger(__name__)

EURIBOR_URL = "https://www.euribor-rates.eu/en/current-euribor-rates/"

_REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (Themis rates feed)"}


def euribor_year_url(year: int) -> str:
    return f"https://www.euribor-rates.eu/en/euribor-rates-by-year/{year}/"


# "Euribor 1 week" / "Euribor 12 months" → tenor code.
_TENOR_RE = re.compile(r"euribor\s+(\d+)\s+(week|weeks|month|months)", re.IGNORECASE)


def _label_to_tenor(label: str) -> str | None:
    m = _TENOR_RE.search(label)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower().rstrip("s")
    if unit == "week":
        return f"{n}W"
    if unit == "month":
        return f"{n}M"
    return None


def _parse_us_or_iso_date(raw: str) -> str | None:
    """Accept '4/24/2026' (M/D/YYYY) or '2026-04-24' (ISO)."""
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
        return raw
    return None


def _parse_rate(raw: str) -> float | None:
    """Parse a rate string, tolerating ' %' / '%' suffix and comma decimals."""
    s = raw.strip().rstrip("%").strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_euribor_html(html: str) -> list[ParsedInterestRate]:
    """Parse euribor-rates.eu's table into ParsedInterestRate rows.

    The site uses two layouts depending on the page:

    Current-rates (`/current-euribor-rates/`) — TRANSPOSED:
      header has DATES, each data row starts with a TENOR label.

    Per-year archive (`/euribor-rates-by-year/{year}/`) — NORMAL:
      header has TENOR labels, each data row starts with a DATE.

    We detect orientation by inspecting the header's second cell: if it parses
    as a tenor label we're on the per-year page, otherwise transposed.
    """
    if not html or not html.strip():
        return []
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []

    all_rows = table.find_all("tr")
    if len(all_rows) < 2:
        return []

    header_cells = all_rows[0].find_all(["th", "td"])
    if len(header_cells) < 2:
        return []
    header_texts = [c.get_text(strip=True) for c in header_cells]

    out: list[ParsedInterestRate] = []
    if _label_to_tenor(header_texts[1]) is not None:
        # Normal layout: header = tenors, rows = dates × rates.
        column_tenors: list[str | None] = [None] + [_label_to_tenor(t) for t in header_texts[1:]]
        for tr in all_rows[1:]:
            cells = tr.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            date = _parse_us_or_iso_date(cells[0].get_text(strip=True))
            if date is None:
                continue
            for i in range(1, min(len(cells), len(column_tenors))):
                tenor = column_tenors[i]
                if tenor is None:
                    continue
                rate = _parse_rate(cells[i].get_text(strip=True))
                if rate is None:
                    continue
                out.append(ParsedInterestRate(
                    date=date, rate_type="EURIBOR", tenor=tenor, rate=rate,
                ))
    else:
        # Transposed layout: header = dates, rows = tenors × rates.
        column_dates: list[str | None] = [None] + [_parse_us_or_iso_date(t) for t in header_texts[1:]]
        for tr in all_rows[1:]:
            cells = tr.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            tenor = _label_to_tenor(cells[0].get_text(strip=True))
            if tenor is None:
                continue
            for i in range(1, min(len(cells), len(column_dates))):
                date = column_dates[i]
                if date is None:
                    continue
                rate = _parse_rate(cells[i].get_text(strip=True))
                if rate is None:
                    continue
                out.append(ParsedInterestRate(
                    date=date, rate_type="EURIBOR", tenor=tenor, rate=rate,
                ))
    return out


def _fetch(url: str, client: httpx.Client | None) -> list[ParsedInterestRate]:
    own = client is None
    if own:
        client = httpx.Client(timeout=30.0, follow_redirects=True, headers=_REQUEST_HEADERS)
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
