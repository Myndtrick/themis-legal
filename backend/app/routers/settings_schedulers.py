"""Settings endpoints for scheduler configuration."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models.scheduler_settings import SchedulerSetting
from app.models.user import User
from app.services.scheduler_config import (
    compute_next_run,
    get_all_settings,
    schedule_jobs,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin"])


# --- Response models ---

class SchedulerSettingOut(BaseModel):
    id: str
    enabled: bool
    frequency: str
    time_hour: int
    time_minute: int
    last_run_at: str | None
    last_run_status: str | None
    last_run_summary: dict | None
    next_run_utc: str | None


class SchedulerSettingUpdate(BaseModel):
    enabled: bool
    frequency: str = Field(pattern=r"^(daily|every_3_days|weekly|monthly)$")
    time_hour: int = Field(ge=0, le=23)
    time_minute: int = Field(ge=0, le=59)


class SchedulerSettingsBatch(BaseModel):
    ro: SchedulerSettingUpdate
    eu: SchedulerSettingUpdate


# --- Endpoints ---

@router.get("/scheduler-settings", response_model=list[SchedulerSettingOut])
def list_scheduler_settings(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Return settings for both schedulers."""
    settings = get_all_settings(db)
    return [
        SchedulerSettingOut(
            id=s.id,
            enabled=s.enabled,
            frequency=s.frequency,
            time_hour=s.time_hour,
            time_minute=s.time_minute,
            last_run_at=s.last_run_at.isoformat() if s.last_run_at else None,
            last_run_status=s.last_run_status,
            last_run_summary=s.last_run_summary,
            next_run_utc=compute_next_run(s),
        )
        for s in settings
    ]


@router.put("/scheduler-settings")
def save_scheduler_settings(
    batch: SchedulerSettingsBatch,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Save settings for both schedulers and reschedule APScheduler jobs."""
    for sched_id, update in [("ro", batch.ro), ("eu", batch.eu)]:
        setting = db.query(SchedulerSetting).filter(SchedulerSetting.id == sched_id).first()
        if not setting:
            raise HTTPException(status_code=404, detail=f"Scheduler '{sched_id}' not found")
        setting.enabled = update.enabled
        setting.frequency = update.frequency
        setting.time_hour = update.time_hour
        setting.time_minute = update.time_minute

    db.commit()

    # Reschedule APScheduler jobs with new settings
    schedule_jobs(db)

    logger.info("Scheduler settings saved and jobs rescheduled")
    return {"status": "ok"}


# Note: the old GET /discovery-progress/{job_type} endpoint was removed when
# discovery moved to the unified jobs system. Frontend now polls /api/jobs by
# kind ("discover_ro" / "discover_eu") instead.
