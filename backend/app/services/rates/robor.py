"""ROBOR rate fetcher + parser + storage.

Source: https://www.curs-valutar-bnr.ro/robor
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

# Map column header tokens to standard tenor codes.
# curs-valutar-bnr.ro uses Romanian-language headers like "ROBOR 1S" (1 week),
# "ROBOR 1L" (1 month), etc. ROBOR ON = overnight.
_TENOR_MAP = {
    "ON": "ON",
    "1S": "1W",
    "1L": "1M",
    "3L": "3M",
    "6L": "6M",
    "12L": "12M",
}


# Romanian + English month abbreviations seen in the table's date column.
_MONTHS = {
    # English (used by some BNR tables)
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
    # Romanian (used by curs-valutar-bnr.ro)
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


def parse_robor_html(html: str) -> list[ParsedInterestRate]:
    """Parse curs-valutar-bnr.ro ROBOR table into ParsedInterestRate rows."""
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
    if not headers or headers[0].lower() != "data":
        return []

    # For columns 1..N, derive their tenor (or None to skip)
    column_tenors: list[str | None] = [None]  # column 0 is the date column
    for h in headers[1:]:
        # Header looks like "ROBOR ON" / "ROBOR 1S" — last token is the tenor.
        token = h.split()[-1] if h.split() else ""
        column_tenors.append(_TENOR_MAP.get(token))

    out: list[ParsedInterestRate] = []
    for tr in tbody.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < 2:
            continue
        date = _parse_date(cells[0])
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
                date=date, rate_type="ROBOR", tenor=tenor, rate=rate,
            ))
    return out


def fetch_robor_current(client: httpx.Client | None = None) -> list[ParsedInterestRate]:
    """Fetch + parse current ROBOR table. Returns [] on HTTP/parse errors."""
    own = client is None
    if own:
        client = httpx.Client(timeout=30.0)
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
