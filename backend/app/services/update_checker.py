"""Daily law update checker service."""

import logging
import time
from datetime import datetime

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.law import Law, LawVersion
from app.models.notification import AuditLog, Notification
from app.services.fetcher import fetch_document
from app.services.leropa_service import fetch_and_store_version

logger = logging.getLogger(__name__)

# Reset the global tracker before each check
import app.services.leropa_service as _ls


def check_for_updates(rate_limit_delay: float = 2.0) -> dict:
    """Check all stored laws for new versions.

    Returns a summary of what was found and updated.
    """
    db = SessionLocal()
    results = {"checked": 0, "updated": 0, "errors": 0, "details": []}

    try:
        laws = db.query(Law).all()
        logger.info(f"Checking {len(laws)} laws for updates")

        for law in laws:
            results["checked"] += 1

            # Get the current version
            current = (
                db.query(LawVersion)
                .filter(LawVersion.law_id == law.id, LawVersion.is_current == True)
                .first()
            )
            if not current:
                logger.warning(f"No current version for law {law.id} ({law.title})")
                continue

            try:
                time.sleep(rate_limit_delay)

                # Fetch the document fresh (bypass cache) to check for updates
                result = fetch_document(current.ver_id, use_cache=False)
                doc = result["document"]

                # Check if there's a next_ver (newer version)
                next_ver = doc.get("next_ver")
                if not next_ver:
                    # Also check history — the fetched doc might reference newer versions
                    # that we don't have yet
                    history = doc.get("history", [])
                    stored_ver_ids = {
                        v.ver_id
                        for v in db.query(LawVersion)
                        .filter(LawVersion.law_id == law.id)
                        .all()
                    }
                    new_versions = [
                        h for h in history if h["ver_id"] not in stored_ver_ids
                    ]
                    if not new_versions:
                        logger.info(f"No updates for: {law.title}")
                        results["details"].append({
                            "law": law.title,
                            "status": "up_to_date",
                        })
                        continue

                    # Import new versions found in history
                    for entry in new_versions:
                        _ls._stored_article_ids = set()
                        _, new_version = fetch_and_store_version(
                            db,
                            entry["ver_id"],
                            law=law,
                            rate_limit_delay=rate_limit_delay,
                        )
                        logger.info(
                            f"Imported new version {entry['ver_id']} for {law.title}"
                        )

                else:
                    # Import the next version
                    existing = (
                        db.query(LawVersion)
                        .filter(LawVersion.ver_id == next_ver)
                        .first()
                    )
                    if existing:
                        logger.info(f"Next version {next_ver} already imported")
                        results["details"].append({
                            "law": law.title,
                            "status": "up_to_date",
                        })
                        continue

                    _ls._stored_article_ids = set()
                    _, new_version = fetch_and_store_version(
                        db,
                        next_ver,
                        law=law,
                        rate_limit_delay=rate_limit_delay,
                    )
                    logger.info(f"Imported new version {next_ver} for {law.title}")

                # Update current version flags
                all_versions = (
                    db.query(LawVersion)
                    .filter(LawVersion.law_id == law.id)
                    .all()
                )
                dated = [
                    (v, v.date_in_force) for v in all_versions if v.date_in_force
                ]
                if dated:
                    dated.sort(key=lambda x: x[1], reverse=True)
                    for v in all_versions:
                        v.is_current = False
                    dated[0][0].is_current = True

                # Create notification
                notification = Notification(
                    title=f"Law updated: {law.title}",
                    message=f"A new version of Legea {law.law_number}/{law.law_year} was found and imported.",
                    notification_type="law_update",
                )
                db.add(notification)

                results["updated"] += 1
                results["details"].append({
                    "law": law.title,
                    "status": "updated",
                })

            except Exception as e:
                logger.exception(f"Error checking updates for {law.title}")
                results["errors"] += 1
                results["details"].append({
                    "law": law.title,
                    "status": "error",
                    "error": str(e),
                })

                # Notify about the error
                notification = Notification(
                    title=f"Update check failed: {law.title}",
                    message=f"Failed to check for updates: {str(e)}",
                    notification_type="error",
                )
                db.add(notification)

        # Audit log
        audit = AuditLog(
            action="check_updates",
            module="legal_library",
            details=f"Checked {results['checked']} laws: {results['updated']} updated, {results['errors']} errors",
        )
        db.add(audit)
        db.commit()

    except Exception as e:
        logger.exception("Update checker failed")
        db.rollback()
    finally:
        db.close()

    return results
