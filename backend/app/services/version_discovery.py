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
from app.services.version_state import (
    SENTINEL_DATE,
    recalculate_current_version as _recalculate_current_version,
)

logger = logging.getLogger(__name__)


def _parse_date(date_str: str) -> datetime.date:
    """Parse a date string from legislatie.just.ro history.

    legislatie.just.ro returns dates in European DD.MM.YYYY format (e.g.
    "31.03.2026"). Older tests and some callers pass ISO YYYY-MM-DD. We
    accept both and fall back to the 1900-01-01 sentinel on failure.
    """
    if not date_str:
        return SENTINEL_DATE
    s = date_str.strip()
    # Try DD.MM.YYYY first (the format legislatie.just.ro actually returns)
    if "." in s:
        parts = s.split(".")
        if len(parts) == 3:
            try:
                return datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
            except (ValueError, IndexError):
                pass
    # Try ISO YYYY-MM-DD
    try:
        return datetime.date.fromisoformat(s)
    except (ValueError, TypeError):
        return SENTINEL_DATE


def _get_probe_ver_id(db: Session, law: Law) -> str | None:
    """Pick a ver_id we can use as an entry point when fetching upstream history.

    Order of preference:
      1. The is_current=True LawVersion (when the law is up to date).
      2. The newest LawVersion by date_in_force (we have imports but none are current).
      3. Any LawVersion for the law (last-resort fallback for rows with NULL date_in_force).
      4. The newest KnownVersion by date_in_force (discovery has run but nothing is imported).
      5. None (genuine empty state — the law has no versions at all).

    Safe because legislatie.just.ro returns the same `history` list regardless of
    which version's page you fetch.
    """
    current_lv = (
        db.query(LawVersion)
        .filter(LawVersion.law_id == law.id, LawVersion.is_current == True)  # noqa: E712
        .first()
    )
    if current_lv:
        return current_lv.ver_id

    newest_lv = (
        db.query(LawVersion)
        .filter(LawVersion.law_id == law.id, LawVersion.date_in_force.is_not(None))
        .order_by(LawVersion.date_in_force.desc())
        .first()
    )
    if newest_lv:
        return newest_lv.ver_id

    # Last-resort fallback: any LawVersion at all (date may be NULL)
    any_lv = (
        db.query(LawVersion)
        .filter(LawVersion.law_id == law.id)
        .first()
    )
    if any_lv:
        return any_lv.ver_id

    newest_kv = (
        db.query(KnownVersion)
        .filter(KnownVersion.law_id == law.id)
        .order_by(KnownVersion.date_in_force.desc())
        .first()
    )
    if newest_kv:
        return newest_kv.ver_id

    return None


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
    # Pick any usable ver_id as the upstream probe entry point. We do NOT
    # require an is_current LawVersion — see _get_probe_ver_id docstring.
    entry_ver_id = _get_probe_ver_id(db, law)
    if entry_ver_id is None:
        logger.warning("No versions at all for law %s (%s) — skipping discovery", law.id, law.title)
        return 0

    # Resolve a date_in_force to use for the synthetic-history fallback below.
    # Prefer LawVersion (richer source), fall back to KnownVersion.
    probe_lv = (
        db.query(LawVersion)
        .filter(LawVersion.law_id == law.id, LawVersion.ver_id == entry_ver_id)
        .first()
    )
    probe_kv = (
        db.query(KnownVersion)
        .filter(KnownVersion.law_id == law.id, KnownVersion.ver_id == entry_ver_id)
        .first()
    )
    probe_date = (
        (probe_lv.date_in_force if probe_lv else None)
        or (probe_kv.date_in_force if probe_kv else None)
    )

    try:
        # First fetch using the probe ver_id
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

        # Ensure the probe ver_id appears in the history
        history_ver_ids = {h["ver_id"] for h in history}
        if entry_ver_id not in history_ver_ids:
            date_str = probe_date.isoformat() if probe_date else ""
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

    # Any already-imported LawVersion ver_id is "pre-known" — inserting it
    # into KnownVersion is bookkeeping, not a "new" discovery.
    imported_ver_ids: set[str] = {
        lv.ver_id
        for lv in db.query(LawVersion).filter(LawVersion.law_id == law.id).all()
    }
    pre_known_ver_ids = existing_ver_ids | imported_ver_ids

    # Pre-load existing KnownVersion rows so we can heal broken dates in-place.
    existing_kvs: dict[str, KnownVersion] = {
        kv.ver_id: kv
        for kv in db.query(KnownVersion).filter(KnownVersion.law_id == law.id).all()
    }

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
        else:
            # Heal sentinel dates from the old broken parser. Only overwrite
            # when the stored date is the SENTINEL_DATE *and* the freshly
            # parsed date is real — never clobber a real date with a sentinel.
            kv = existing_kvs.get(ver_id)
            if (
                kv is not None
                and kv.date_in_force == SENTINEL_DATE
                and date_in_force != SENTINEL_DATE
            ):
                kv.date_in_force = date_in_force

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

    # Re-derive LawVersion.is_current from the freshly-authoritative
    # KnownVersion.is_current. This is what makes stuck production laws
    # self-heal on first visit after deploy.
    _recalculate_current_version(db, law.id)

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
