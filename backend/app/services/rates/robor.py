"""ROBOR rate fetcher + parser + storage.

Source: https://www.curs-valutar-bnr.ro/robor

Real-page structure (verified live, 2026-04-28):
  - One <table> with <th> header row and <td> data rows as direct siblings
    (no <thead>/<tbody> split).
  - Headers: Data | O/N | T/N | 1 sapt. | 1 luna | 3 luni | 6 luni | 12 luni
  - Dates in English: "27 Apr 2026"
  - Rates use comma decimal: "5,69"
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

ROBOR_URL = "https://www.curs-valutar-bnr.ro/robor"

_REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (Themis rates feed)"}

# T/N (tomorrow-next) is intentionally skipped — not a standard tenor we want
# to publish; consumers expect ON, 1W, 1M, 3M, 6M, 12M.
_TENOR_MAP = {
    "o/n": "ON",
    "1 sapt.": "1W",
    "1 luna": "1M",
    "3 luni": "3M",
    "6 luni": "6M",
    "12 luni": "12M",
}


_MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
    "Ian": "01", "Ian.": "01",
    "Feb.": "02",
    "Mar.": "03",
    "Apr.": "04",
    "Mai": "05",
    "Iun": "06", "Iun.": "06",
    "Iul": "07", "Iul.": "07",
    "Aug.": "08",
    "Sep.": "09", "Sept": "09", "Sept.": "09",
    "Oct.": "10",
    "Noi": "11", "Noi.": "11",
    "Dec.": "12",
}


@dataclass(frozen=True)
class ParsedInterestRate:
    date: str         # YYYY-MM-DD
    rate_type: str    # "ROBOR" | "EURIBOR"
    tenor: str        # "ON" | "1W" | "1M" | "3M" | "6M" | "12M"
    rate: float


def _parse_date(raw: str) -> str | None:
    """Parse "06 Mar 2026" or "6 Mar 2026" -> "2026-03-06"."""
    parts = raw.strip().split()
    if len(parts) != 3:
        return None
    day, month_token, year = parts
    month = _MONTHS.get(month_token) or _MONTHS.get(month_token + ".")
    if not month:
        return None
    try:
        return f"{int(year):04d}-{month}-{int(day):02d}"
    except ValueError:
        return None


def _parse_rate(raw: str) -> float | None:
    """Parse a rate that may use comma OR dot as decimal separator,
    optionally suffixed with '%' or ' %'."""
    s = raw.strip().rstrip("%").strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_robor_html(html: str) -> list[ParsedInterestRate]:
    """Parse curs-valutar-bnr.ro ROBOR table into ParsedInterestRate rows.

    Real layout has no thead/tbody split: rows are direct <tr> children of
    <table>. The first <tr> with cells starting at "Data" is the header; the
    rest are data rows.
    """
    if not html or not html.strip():
        return []
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []

    all_rows = table.find_all("tr")
    if not all_rows:
        return []

    header_idx = None
    headers: list[str] = []
    for i, tr in enumerate(all_rows):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        if cells[0].name == "th" and cells[0].get_text(strip=True).lower() == "data":
            headers = [c.get_text(strip=True) for c in cells]
            header_idx = i
            break
    if header_idx is None:
        return []

    column_tenors: list[str | None] = [None]  # column 0 = date
    for h in headers[1:]:
        column_tenors.append(_TENOR_MAP.get(h.strip().lower()))

    out: list[ParsedInterestRate] = []
    for tr in all_rows[header_idx + 1:]:
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        date = _parse_date(cells[0])
        if not date:
            continue
        for i in range(1, min(len(cells), len(column_tenors))):
            tenor = column_tenors[i]
            if tenor is None:
                continue
            rate = _parse_rate(cells[i])
            if rate is None:
                continue
            out.append(ParsedInterestRate(
                date=date, rate_type="ROBOR", tenor=tenor, rate=rate,
            ))
    return out


def fetch_robor_current(client: httpx.Client | None = None) -> list[ParsedInterestRate]:
    """Fetch + parse current ROBOR table. Returns [] on HTTP/parse errors."""
    own = client is None
    if own:
        client = httpx.Client(timeout=30.0, follow_redirects=True, headers=_REQUEST_HEADERS)
    try:
        r = client.get(ROBOR_URL)
    except httpx.RequestError as e:
        logger.error("[rates/robor] HTTP error: %s", e)
        return []
    finally:
        if own:
            client.close()
    if r.status_code != 200:
        logger.warning("[rates/robor] %d for %s", r.status_code, ROBOR_URL)
        return []
    return parse_robor_html(r.text)


def store_interest_rates(
    db: Session,
    rates: Iterable[ParsedInterestRate],
    source: str,
) -> int:
    """Store interest rates idempotently. Returns count of newly inserted rows."""
    inserted = 0
    for r in rates:
        result = db.execute(
            text(
                "INSERT OR IGNORE INTO interest_rates "
                "(date, rate_type, tenor, rate, source, fetched_at) "
                "VALUES (:date, :rate_type, :tenor, :rate, :source, datetime('now'))"
            ),
            {"date": r.date, "rate_type": r.rate_type, "tenor": r.tenor, "rate": r.rate, "source": source},
        )
        inserted += result.rowcount or 0
    db.commit()
    return inserted
