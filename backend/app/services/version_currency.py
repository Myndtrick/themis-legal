"""Version currency checker — verify local DB versions against legislatie.just.ro.

For each law identified as relevant to a question, checks whether the local
database has the latest officially published version. Returns enriched
candidate_laws with currency_status fields.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.law import LawVersion
from app.services.fetcher import fetch_document

logger = logging.getLogger(__name__)

# In-memory cache: ver_id -> (currency_status, official_info | None, timestamp)
_currency_cache: dict[str, tuple[str, dict | None, float]] = {}
CACHE_TTL = 3600  # 1 hour
FRESHNESS_WINDOW = 86400  # 24 hours — skip check if version imported recently
REQUEST_TIMEOUT = 10  # seconds per request


class SourceUnavailableError(Exception):
    """Raised when legislatie.just.ro cannot be reached."""


def _get_current_db_version(db: Session, db_law_id: int) -> LawVersion | None:
    """Get the current (is_current=True) version for a law."""
    return (
        db.query(LawVersion)
        .filter(LawVersion.law_id == db_law_id, LawVersion.is_current == True)
        .first()
    )


def _get_stored_ver_ids(db: Session, db_law_id: int) -> set[str]:
    """Get all ver_ids stored in DB for a given law."""
    rows = (
        db.query(LawVersion.ver_id)
        .filter(LawVersion.law_id == db_law_id)
        .all()
    )
    return {r[0] for r in rows}


def fetch_latest_version_metadata(ver_id: str, stored_ver_ids: set[str] | None = None) -> dict | None:
    """Check if legislatie.just.ro has a newer version than the one we have.

    This is a lightweight metadata check — it does NOT import anything.

    Args:
        ver_id: The ver_id of the current DB version.
        stored_ver_ids: Set of all ver_ids we have stored. If provided, used to
            detect any version in the history list that we don't have.

    Returns:
        None if no newer version exists (DB is current).
        {"ver_id": str, "date": str | None} if a newer version is found.

    Raises:
        SourceUnavailableError: If legislatie.just.ro cannot be reached.
    """
    try:
        result = fetch_document(ver_id, use_cache=False)
    except Exception as e:
        raise SourceUnavailableError(f"Failed to fetch document {ver_id}: {e}") from e

    doc = result.get("document", {})

    # Check next_ver pointer (direct successor link)
    next_ver = doc.get("next_ver")
    if next_ver and (stored_ver_ids is None or next_ver not in stored_ver_ids):
        return {"ver_id": next_ver, "date": None}

    # Check history list for versions we don't have
    history = doc.get("history", [])
    if not history:
        return None

    # History is typically newest-first from legislatie.just.ro
    # Look for any entry in the history that we don't have stored
    if stored_ver_ids:
        for entry in history:
            entry_vid = entry.get("ver_id")
            if entry_vid and entry_vid not in stored_ver_ids and entry_vid != ver_id:
                return {"ver_id": entry_vid, "date": entry.get("date")}

    # Cross-reference: fetch the newest history entry's page to discover
    # even newer versions that may not appear on our version's page.
    # (Same pattern used in leropa_service._fetch_law_metadata)
    newest_entry = history[0]
    if newest_entry.get("ver_id") and newest_entry["ver_id"] != ver_id:
        if stored_ver_ids is None or newest_entry["ver_id"] not in stored_ver_ids:
            return {"ver_id": newest_entry["ver_id"], "date": newest_entry.get("date")}

    # Cross-reference from the newest known entry
    if newest_entry.get("ver_id") and newest_entry["ver_id"] != ver_id:
        try:
            cross_result = fetch_document(newest_entry["ver_id"], use_cache=False)
            cross_history = cross_result.get("document", {}).get("history", [])
            for entry in cross_history:
                entry_vid = entry.get("ver_id")
                if entry_vid and entry_vid != ver_id:
                    if stored_ver_ids is None or entry_vid not in stored_ver_ids:
                        return {"ver_id": entry_vid, "date": entry.get("date")}
        except Exception:
            pass  # Cross-reference is best-effort

    return None


def _check_single_law(law: dict, db: Session) -> dict:
    """Check version currency for a single law. Returns fields to merge into the law dict."""
    db_law_id = law.get("db_law_id")
    if not db_law_id:
        return {"currency_status": "not_checked"}

    current_version = _get_current_db_version(db, db_law_id)
    if not current_version:
        return {"currency_status": "no_current_version"}

    # Skip if version was imported recently (within freshness window)
    if current_version.date_imported:
        age = (datetime.now() - current_version.date_imported).total_seconds()
        if age < FRESHNESS_WINDOW:
            return {
                "currency_status": "current",
                "currency_note": "Version imported within last 24h — skipping remote check",
            }

    # Check in-memory cache
    cached = _currency_cache.get(current_version.ver_id)
    if cached and time.time() - cached[2] < CACHE_TTL:
        result = {"currency_status": cached[0]}
        if cached[1]:
            result.update(cached[1])
        return result

    # Query legislatie.just.ro
    stored_ver_ids = _get_stored_ver_ids(db, db_law_id)

    try:
        official_latest = fetch_latest_version_metadata(
            current_version.ver_id, stored_ver_ids
        )
    except SourceUnavailableError as e:
        logger.warning(f"Source unavailable for law {db_law_id}: {e}")
        _currency_cache[current_version.ver_id] = ("source_unavailable", None, time.time())
        return {
            "currency_status": "source_unavailable",
            "currency_note": "Could not reach legislatie.just.ro to verify version currency",
        }

    if official_latest is None:
        # DB is current
        _currency_cache[current_version.ver_id] = ("current", None, time.time())
        return {"currency_status": "current"}
    else:
        # DB is stale
        stale_info = {
            "currency_status": "stale",
            "official_latest_ver_id": official_latest["ver_id"],
            "official_latest_date": official_latest.get("date"),
            "db_latest_date": str(current_version.date_in_force) if current_version.date_in_force else None,
        }
        _currency_cache[current_version.ver_id] = ("stale", stale_info, time.time())
        return stale_info


def check_version_currency(
    candidate_laws: list[dict],
    db: Session,
    today: str,
    date_type: str | None = None,
    primary_date: str | None = None,
) -> list[dict]:
    """Check version currency for all available candidate laws.

    For each law with availability="available", queries legislatie.just.ro to
    determine if the local DB has the latest officially published version.

    Skipped when the user asks about a historical date (explicit past date).

    Args:
        candidate_laws: List of law dicts from Step 2 (law mapping).
        db: Database session.
        today: Today's date as ISO string.
        date_type: How the date was determined ("explicit", "relative", "implicit_current").
        primary_date: The primary date extracted from the question.

    Returns:
        The same candidate_laws list, enriched with currency_status fields.
    """
    # Skip currency check for historical questions
    if date_type == "explicit" and primary_date and primary_date < today:
        for law in candidate_laws:
            law["currency_status"] = "not_checked"
            law["currency_note"] = "Historical question — currency check skipped"
        return candidate_laws

    # Identify laws that need checking
    laws_to_check = [
        law for law in candidate_laws
        if law.get("availability") == "available" and law.get("db_law_id")
    ]

    # Mark non-checkable laws
    for law in candidate_laws:
        if law not in laws_to_check:
            if "currency_status" not in law:
                law["currency_status"] = "not_checked"

    if not laws_to_check:
        return candidate_laws

    # Check laws in parallel (max 3 concurrent requests)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_check_single_law, law, db): law
            for law in laws_to_check
        }
        for future in as_completed(futures, timeout=30):
            law = futures[future]
            try:
                result = future.result()
                law.update(result)
            except Exception as e:
                logger.warning(f"Currency check failed for {law.get('law_number')}/{law.get('law_year')}: {e}")
                law["currency_status"] = "source_unavailable"
                law["currency_note"] = f"Currency check error: {str(e)[:100]}"

    return candidate_laws
