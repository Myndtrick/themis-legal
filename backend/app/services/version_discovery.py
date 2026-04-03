"""Version discovery service.

Fetches version history from legislatie.just.ro and writes metadata to the
KnownVersion table. Does NOT import full text or modify LawVersion.
"""

import datetime
import logging
import time

from sqlalchemy.orm import Session

from app.models.law import KnownVersion, Law, LawVersion
from app.services.fetcher import fetch_document
from app.services.scheduler_config import discovery_progress

logger = logging.getLogger(__name__)


def _parse_date(date_str: str) -> datetime.date:
    """Parse a date string, falling back to 1900-01-01 on failure."""
    if not date_str:
        return datetime.date(1900, 1, 1)
    try:
        return datetime.date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return datetime.date(1900, 1, 1)


def discover_versions_for_law(db: Session, law: Law) -> int:
    """Discover versions for a single law and populate KnownVersion.

    - Fetches version history from legislatie.just.ro using the current ver_id.
    - If next_ver exists, follows it to get a more complete / up-to-date history.
    - Inserts KnownVersion rows for any ver_id not already recorded.
    - Updates is_current flags (newest date_in_force = current).
    - Updates law.last_checked_at on success only.
    - On fetch error: logs warning, returns 0, does NOT update last_checked_at.

    Returns the count of newly discovered versions.
    """
    # Get current LawVersion as entry point
    current_version = (
        db.query(LawVersion)
        .filter(LawVersion.law_id == law.id, LawVersion.is_current == True)  # noqa: E712
        .first()
    )
    if not current_version:
        logger.warning("No current LawVersion for law %s (%s)", law.id, law.title)
        return 0

    entry_ver_id = current_version.ver_id

    try:
        # First fetch using the current ver_id
        result = fetch_document(entry_ver_id, use_cache=False)
        doc = result["document"]

        history: list[dict] = list(doc.get("history", []))

        # If there's a next_ver, follow it — its history will be more complete
        next_ver = doc.get("next_ver")
        if next_ver:
            next_result = fetch_document(next_ver, use_cache=False)
            next_doc = next_result["document"]
            next_history = next_doc.get("history", [])
            if next_history:
                history = list(next_history)

        # Ensure the original entry ver_id appears in the history
        history_ver_ids = {h["ver_id"] for h in history}
        if entry_ver_id not in history_ver_ids:
            # Add a synthetic entry using the date_in_force from LawVersion
            date_str = (
                current_version.date_in_force.isoformat()
                if current_version.date_in_force
                else ""
            )
            history.append({"ver_id": entry_ver_id, "date": date_str})

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to fetch version history for law %s (%s): %s",
            law.id,
            law.title,
            exc,
        )
        return 0

    # Load already-known ver_ids for this law
    existing_ver_ids: set[str] = {
        kv.ver_id
        for kv in db.query(KnownVersion).filter(KnownVersion.law_id == law.id).all()
    }

    # The current LawVersion's ver_id is the known entry point — inserting it
    # into KnownVersion is bookkeeping, not a "new" discovery.
    pre_known_ver_ids = existing_ver_ids | {entry_ver_id}

    new_count = 0
    for entry in history:
        ver_id = entry.get("ver_id")
        if not ver_id:
            continue

        date_in_force = _parse_date(entry.get("date", ""))

        if ver_id not in existing_ver_ids:
            kv = KnownVersion(
                law_id=law.id,
                ver_id=ver_id,
                date_in_force=date_in_force,
                is_current=False,  # set properly below
                discovered_at=datetime.datetime.utcnow(),
            )
            db.add(kv)
            existing_ver_ids.add(ver_id)
            # Only count as new if it wasn't the existing current ver_id
            if ver_id not in pre_known_ver_ids:
                new_count += 1

    db.flush()

    # Update is_current: the entry with the newest date_in_force is current
    all_known = (
        db.query(KnownVersion).filter(KnownVersion.law_id == law.id).all()
    )
    # Sort descending by date — newest first
    all_known_sorted = sorted(
        all_known,
        key=lambda kv: kv.date_in_force or datetime.date(1900, 1, 1),
        reverse=True,
    )
    for i, kv in enumerate(all_known_sorted):
        kv.is_current = i == 0

    # Update law.last_checked_at on success
    law.last_checked_at = datetime.datetime.utcnow()

    db.commit()

    logger.info(
        "Discovered %d new version(s) for law %s (%s)",
        new_count,
        law.id,
        law.title,
    )
    return new_count


def run_daily_discovery(rate_limit_delay: float = 2.0) -> dict:
    """Run version discovery for all laws.

    Creates Notification entries for laws with newly-discovered versions and
    an AuditLog entry summarising the run.

    Returns a summary dict with keys: checked, discovered, errors.
    """
    from app.database import SessionLocal
    from app.models.notification import AuditLog, Notification

    db = SessionLocal()
    results = {"checked": 0, "discovered": 0, "errors": 0}

    try:
        laws = db.query(Law).all()
        logger.info("Starting daily version discovery for %d law(s)", len(laws))

        total = len(laws)
        discovery_progress["ro"] = {"running": True, "current": 0, "total": total, "current_law": "", "results": None}

        for i, law in enumerate(laws):
            discovery_progress["ro"]["current"] = i + 1
            discovery_progress["ro"]["current_law"] = law.title or f"Law {law.id}"
            results["checked"] += 1

            try:
                new_count = discover_versions_for_law(db, law)
                results["discovered"] += new_count

                if new_count > 0:
                    notification = Notification(
                        title=f"New version(s) found: {law.title}",
                        message=(
                            f"{new_count} new version(s) discovered for "
                            f"Legea {law.law_number}/{law.law_year}."
                        ),
                        notification_type="law_update",
                    )
                    db.add(notification)
                    db.commit()

            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Unexpected error during discovery for law %s: %s", law.id, exc
                )
                results["errors"] += 1

            time.sleep(rate_limit_delay)

        audit = AuditLog(
            action="daily_version_discovery",
            module="legal_library",
            details=(
                f"Checked {results['checked']} law(s): "
                f"{results['discovered']} new version(s) discovered, "
                f"{results['errors']} error(s)."
            ),
        )
        db.add(audit)
        db.commit()
        discovery_progress["ro"] = {"running": False, "current": total, "total": total, "current_law": "", "results": results}

    except Exception:
        logger.exception("run_daily_discovery failed")
        discovery_progress["ro"] = {"running": False, "current": 0, "total": 0, "current_law": "", "results": results}
        db.rollback()
    finally:
        db.close()

    return results


def seed_known_versions_from_imported(db: Session) -> int:
    """Backfill KnownVersion from existing LawVersion rows.

    For each LawVersion that has no corresponding KnownVersion, create one.
    This ensures clean initial state after deploying the KnownVersion feature.
    Returns the number of rows created.
    """
    existing_known = {row[0] for row in db.query(KnownVersion.ver_id).all()}

    versions = db.query(LawVersion).all()
    count = 0
    now = datetime.datetime.utcnow()

    for v in versions:
        if v.ver_id in existing_known:
            continue
        kv = KnownVersion(
            law_id=v.law_id,
            ver_id=v.ver_id,
            date_in_force=v.date_in_force or datetime.date(1900, 1, 1),
            is_current=v.is_current,
            discovered_at=now,
        )
        db.add(kv)
        existing_known.add(v.ver_id)
        count += 1

    if count > 0:
        db.commit()
    return count
