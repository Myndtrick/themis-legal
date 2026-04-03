"""Shared APScheduler instance — importable from any module without circular deps."""

import datetime
import logging

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

# Track last run results so the status endpoint can report them
last_run_results: dict[str, dict] = {}


def _job_listener(event):
    """Log job outcomes and track results."""
    if event.exception:
        logger.error("Scheduled job '%s' FAILED: %s", event.job_id, event.exception)
        last_run_results[event.job_id] = {
            "status": "error",
            "error": str(event.exception),
            "ran_at": event.scheduled_run_time.isoformat() if event.scheduled_run_time else None,
        }
    else:
        logger.info("Scheduled job '%s' completed successfully", event.job_id)
        last_run_results[event.job_id] = {
            "status": "ok",
            "ran_at": event.scheduled_run_time.isoformat() if event.scheduled_run_time else None,
        }


scheduler = BackgroundScheduler(timezone=datetime.timezone.utc)
scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
