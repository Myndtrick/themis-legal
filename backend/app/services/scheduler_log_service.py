"""Append rows to scheduler_run_logs. Best-effort: never raises."""

import datetime as _dt
import logging

from sqlalchemy.orm import Session

from app.models.scheduler_run_log import SchedulerRunLog

logger = logging.getLogger(__name__)


def record_run(db: Session, scheduler_id: str, results: dict, trigger: str) -> None:
    """Insert one scheduler_run_logs row.

    Best-effort: a logging failure is logged at WARNING level and swallowed
    so it cannot break the discovery run that called us.

    Args:
        db: SQLAlchemy session (caller-owned; this function commits on it).
        scheduler_id: "ro" or "eu".
        results: Dict returned by run_daily_discovery / run_eu_weekly_discovery.
                 Field mapping from results dict to DB columns:
                     checked    -> laws_checked
                     discovered -> new_versions
                     errors     -> errors
                 Stored in full as summary_json for future debugging.
        trigger: "scheduled" or "manual".
    """
    try:
        errors = int(results.get("errors", 0) or 0)
        row = SchedulerRunLog(
            scheduler_id=scheduler_id,
            ran_at=_dt.datetime.now(_dt.timezone.utc),
            trigger=trigger,
            status="ok" if errors == 0 else "error",
            laws_checked=int(results.get("checked", 0) or 0),
            new_versions=int(results.get("discovered", 0) or 0),
            errors=errors,
            summary_json=results,
        )
        db.add(row)
        db.commit()
    except Exception as e:  # noqa: BLE001 - intentional swallow
        logger.warning("Failed to write scheduler_run_log row: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
