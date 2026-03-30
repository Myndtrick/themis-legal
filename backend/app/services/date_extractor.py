"""Local date extraction — handles explicit dates without a Claude API call."""
from __future__ import annotations

import datetime
import re

# Patterns for Romanian date expressions
_FULL_DATE = re.compile(
    r"(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})"  # DD.MM.YYYY or DD/MM/YYYY
)
_YEAR_PHRASE = re.compile(
    r"\b(?:in|din|anul|din anul|pe|la)\s+(\d{4})\b", re.IGNORECASE
)
_RELATIVE_YEARS = re.compile(
    r"\bacum\s+(\d+)\s+ani?\b", re.IGNORECASE
)
_RELATIVE_MONTHS = re.compile(
    r"\bacum\s+(\d+)\s+luni?\b", re.IGNORECASE
)


def _safe_replace_year(d: datetime.date, year: int) -> datetime.date:
    """Replace year safely, handling Feb 29 on non-leap years."""
    try:
        return d.replace(year=year)
    except ValueError:
        # Feb 29 on a non-leap year -> use Feb 28
        return d.replace(year=year, day=28)


def extract_date_local(question: str, today: str) -> dict:
    """Extract dates from the question using regex.

    Returns a dict matching the Claude date extractor output schema.
    Finds ALL dates in the question (not just the first) so comparison
    questions are handled correctly.
    Always returns a result (falls back to today's date).
    """
    today_date = datetime.date.fromisoformat(today)
    dates_found: list[dict] = []

    # 1. Full dates: DD.MM.YYYY — find ALL occurrences
    for m in _FULL_DATE.finditer(question):
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            d = datetime.date(year, month, day)
            dates_found.append({
                "date": d.isoformat(),
                "type": "explicit",
                "context": "extracted locally",
                "source_text": m.group(0),
            })
        except ValueError:
            pass

    if dates_found:
        # Use the latest date as primary (matters for currency check:
        # if the latest explicit date < today, all dates are historical)
        primary = max(dates_found, key=lambda x: x["date"])
        return {
            "primary_date": primary["date"],
            "dates_found": dates_found,
            "date_logic": (
                f"Local extraction: {len(dates_found)} explicit date(s) found — "
                + ", ".join(d["source_text"] for d in dates_found)
            ),
            "needs_clarification": False,
        }

    # 2. "in 2023", "din anul 2020", etc. (requires a date-introducing word)
    m = _YEAR_PHRASE.search(question)
    if m:
        return _result(m.group(1), "explicit", m.group(0))

    # 3. "acum 3 ani"
    m = _RELATIVE_YEARS.search(question)
    if m:
        years_ago = int(m.group(1))
        d = _safe_replace_year(today_date, today_date.year - years_ago)
        return _result(d.isoformat(), "relative", m.group(0))

    # 4. "acum 6 luni"
    m = _RELATIVE_MONTHS.search(question)
    if m:
        months_ago = int(m.group(1))
        year = today_date.year
        month = today_date.month - months_ago
        while month <= 0:
            month += 12
            year -= 1
        d = _safe_replace_year(today_date, year).replace(month=month)
        return _result(d.isoformat(), "relative", m.group(0))

    # 5. No date found — use today (implicit current)
    # Note: we intentionally do NOT match standalone years (e.g., "1990")
    # because they usually appear in law references like "Legea 31/1990"
    return _result(today, "implicit_current", "")


def _result(date: str, date_type: str, source_text: str) -> dict:
    return {
        "primary_date": date,
        "dates_found": [
            {
                "date": date,
                "type": date_type,
                "context": "extracted locally",
                "source_text": source_text,
            }
        ],
        "date_logic": (
            f"Local extraction: {date_type} date '{source_text}'"
            if source_text
            else "No date mentioned, using current date"
        ),
        "needs_clarification": False,
    }
