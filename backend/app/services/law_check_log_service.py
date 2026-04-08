"""Append rows to law_check_logs. Best-effort: never raises."""

import datetime as _dt
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.law import Law
from app.models.law_check_log import LawCheckLog

logger = logging.getLogger(__name__)

_ERROR_MESSAGE_MAX = 512


def record_check(
    db: Session,
    law: Law,
    user_id: Optional[int],
    new_versions: int,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """Insert one law_check_logs row.

    Best-effort: a logging failure is logged at WARNING level and
    swallowed so it cannot break the per-law check that called us.

    Args:
        db: SQLAlchemy session (caller-owned; this function commits on it).
        law: The Law that was checked. Reads law.id and law.source.
        user_id: Triggering user id, or None if unauthenticated.
        new_versions: Number of new KnownVersion rows discovered.
        status: "ok" or "error".
        error_message: Truncated to 512 chars before insert.
    """
    try:
        truncated = error_message[:_ERROR_MESSAGE_MAX] if error_message else None
        row = LawCheckLog(
            law_id=law.id,
            source=law.source,
            checked_at=_dt.datetime.now(_dt.timezone.utc),
            user_id=user_id,
            new_versions=int(new_versions or 0),
            status=status,
            error_message=truncated,
        )
        db.add(row)
        db.commit()
    except Exception as e:  # noqa: BLE001 - intentional best-effort swallow
        logger.warning("Failed to write law_check_log row: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
