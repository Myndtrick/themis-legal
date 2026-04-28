"""BNR FX rate fetcher + parser + storage.

Sources:
  - Daily:  https://www.bnr.ro/nbrfxrates.xml
  - Yearly: https://www.bnr.ro/files/xml/years/nbrfxrates{year}.xml
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

BNR_DAILY_URL = "https://www.bnr.ro/nbrfxrates.xml"


def bnr_year_url(year: int) -> str:
    return f"https://www.bnr.ro/files/xml/years/nbrfxrates{year}.xml"


_NS_WILDCARD = "{*}"


@dataclass(frozen=True)
class ParsedFxRate:
    date: str       # YYYY-MM-DD
    currency: str
    rate: float
    multiplier: int


def parse_bnr_xml(xml_text: str) -> list[ParsedFxRate]:
    """Parse a BNR DataSet XML into ParsedFxRate objects.

    Tolerant of malformed input — returns [] on any parse error rather than
    raising, so the daily run keeps going if BNR ever ships unexpected data.
    """
    if not xml_text or not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    out: list[ParsedFxRate] = []
    body = root.find(f"{_NS_WILDCARD}Body")
    if body is None:
        return []
    for cube in body.findall(f"{_NS_WILDCARD}Cube"):
        date = cube.attrib.get("date", "")
        if not date:
            continue
        for rate_el in cube.findall(f"{_NS_WILDCARD}Rate"):
            currency = rate_el.attrib.get("currency", "")
            multiplier_attr = rate_el.attrib.get("multiplier", "1")
            try:
                multiplier = int(multiplier_attr)
            except ValueError:
                multiplier = 1
            try:
                rate = float((rate_el.text or "").strip())
            except (ValueError, AttributeError):
                continue
            if not currency:
                continue
            out.append(ParsedFxRate(date=date, currency=currency, rate=rate, multiplier=multiplier))
    return out


def fetch_bnr_daily(client: httpx.Client | None = None) -> list[ParsedFxRate]:
    """Fetch + parse today's BNR feed. Returns [] on HTTP/parse errors."""
    return _fetch_url(BNR_DAILY_URL, client)


def fetch_bnr_year(year: int, client: httpx.Client | None = None) -> list[ParsedFxRate]:
    """Fetch + parse one year's BNR feed."""
    return _fetch_url(bnr_year_url(year), client)


def _fetch_url(url: str, client: httpx.Client | None) -> list[ParsedFxRate]:
    own = client is None
    if own:
        client = httpx.Client(timeout=30.0)
    try:
        r = client.get(url)
    except httpx.RequestError as e:
        logger.error("[rates/bnr_fx] HTTP error for %s: %s", url, e)
        return []
    finally:
        if own:
            client.close()
    if r.status_code != 200:
        logger.warning("[rates/bnr_fx] %d for %s", r.status_code, url)
        return []
    return parse_bnr_xml(r.text)


def store_fx_rates(db: Session, rates: Iterable[ParsedFxRate]) -> int:
    """Store rates with INSERT OR IGNORE — idempotent. Returns count of newly
    inserted rows."""
    inserted = 0
    for r in rates:
        result = db.execute(
            text(
                "INSERT OR IGNORE INTO exchange_rates "
                "(date, currency, rate, multiplier, source, fetched_at) "
                "VALUES (:date, :currency, :rate, :multiplier, 'BNR', datetime('now'))"
            ),
            {"date": r.date, "currency": r.currency, "rate": r.rate, "multiplier": r.multiplier},
        )
        inserted += result.rowcount or 0
    db.commit()
    return inserted
