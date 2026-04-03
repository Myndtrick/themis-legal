"""Scheduler configuration: seeding defaults, rescheduling jobs, progress tracking."""

import datetime
import logging

from sqlalchemy.orm import Session

from app.models.scheduler_settings import SchedulerSetting
from app.scheduler import scheduler

logger = logging.getLogger(__name__)

# --- Progress tracking for manual runs ---
# Updated by discovery functions, read by the progress endpoint.
discovery_progress: dict[str, dict] = {}

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


def _build_trigger_kwargs(frequency: str, hour: int, minute: int) -> tuple[str, dict]:
    """Return (trigger_type, trigger_kwargs) for APScheduler based on frequency.

    Returns:
        ("cron", {...}) or ("interval", {...})
    """
    if frequency == "daily":
        return "cron", {"hour": hour, "minute": minute}
    elif frequency == "every_3_days":
        # interval trigger: every 3 days starting at the configured time today (or tomorrow if past)
        now = datetime.datetime.now(datetime.timezone.utc)
        start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start < now:
            start += datetime.timedelta(days=1)
        return "interval", {"days": 3, "start_date": start}
    elif frequency == "weekly":
        return "cron", {"day_of_week": "sun", "hour": hour, "minute": minute}
    elif frequency == "monthly":
        return "cron", {"day": 1, "hour": hour, "minute": minute}
    else:
        raise ValueError(f"Unknown frequency: {frequency}")


def schedule_jobs(db: Session) -> None:
    """Read settings from DB and register/remove APScheduler jobs accordingly.

    Called on startup and after saving settings.
    """
    from app.main import run_update_check, run_eu_update_check

    job_map = {
        "ro": {"id": "daily_law_update", "func": run_update_check},
        "eu": {"id": "weekly_eu_discovery", "func": run_eu_update_check},
    }

    settings = {s.id: s for s in get_all_settings(db)}

    for sched_id, job_info in job_map.items():
        job_id = job_info["id"]

        # Remove existing job if present
        existing_job = scheduler.get_job(job_id)
        if existing_job:
            scheduler.remove_job(job_id)

        setting = settings.get(sched_id)
        if not setting or not setting.enabled:
            logger.info("Scheduler '%s' is disabled — job removed", sched_id)
            continue

        trigger_type, trigger_kwargs = _build_trigger_kwargs(
            setting.frequency, setting.time_hour, setting.time_minute
        )

        scheduler.add_job(
            job_info["func"],
            trigger_type,
            id=job_id,
            replace_existing=True,
            misfire_grace_time=43200,
            **trigger_kwargs,
        )
        logger.info(
            "Scheduled '%s': trigger=%s, kwargs=%s",
            job_id,
            trigger_type,
            trigger_kwargs,
        )


def compute_next_run(setting: SchedulerSetting) -> str | None:
    """Compute the next run time for a scheduler setting by checking the APScheduler job."""
    job_ids = {"ro": "daily_law_update", "eu": "weekly_eu_discovery"}
    job_id = job_ids.get(setting.id)
    if not job_id:
        return None
    job = scheduler.get_job(job_id)
    if not job or not job.next_run_time:
        return None
    return job.next_run_time.isoformat()
