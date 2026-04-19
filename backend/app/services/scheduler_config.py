"""Scheduler settings helpers (seed defaults, read settings).

Cron scheduling itself now lives in AICC Scheduler, which POSTs to
/internal/scheduler/* on a cron. This module only manages the DB rows that
record the intended frequency (informational) and the last-run status/summary.
"""

import logging

from sqlalchemy.orm import Session

from app.models.scheduler_settings import SchedulerSetting

logger = logging.getLogger(__name__)

DEFAULTS = {
    "ro": {"frequency": "daily", "time_hour": 3, "time_minute": 0},
    "eu": {"frequency": "weekly", "time_hour": 4, "time_minute": 0},
}


def seed_scheduler_settings(db: Session) -> None:
    """Insert default rows for 'ro' and 'eu' if they don't exist. Never modifies existing rows."""
    for sched_id, defaults in DEFAULTS.items():
        existing = db.query(SchedulerSetting).filter(SchedulerSetting.id == sched_id).first()
        if not existing:
            db.add(SchedulerSetting(
                id=sched_id,
                enabled=True,
                frequency=defaults["frequency"],
                time_hour=defaults["time_hour"],
                time_minute=defaults["time_minute"],
            ))
            logger.info("Seeded scheduler_settings row for '%s'", sched_id)
    db.commit()


def get_all_settings(db: Session) -> list[SchedulerSetting]:
    """Return all scheduler settings rows."""
    return db.query(SchedulerSetting).all()


def compute_next_run(setting: SchedulerSetting) -> str | None:
    """Next-run time is owned by AICC Scheduler, not knowable from here."""
    return None
