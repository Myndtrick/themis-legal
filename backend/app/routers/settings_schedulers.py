"""Settings endpoints for scheduler configuration."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models.law import Law
from app.models.law_check_log import LawCheckLog
from app.models.scheduler_run_log import SchedulerRunLog
from app.models.scheduler_settings import SchedulerSetting
from app.models.user import User
from app.services.scheduler_config import (
    compute_next_run,
    get_all_settings,
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


class SchedulerRunLogOut(BaseModel):
    id: int
    scheduler_id: str
    ran_at: str
    trigger: str
    status: str
    laws_checked: int
    new_versions: int
    errors: int


class LawCheckLogOut(BaseModel):
    id: int
    law_id: int
    source: str
    law_label: str
    checked_at: str
    user_email: str | None
    new_versions: int
    status: str
    error_message: str | None


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

    # Frequency is stored for UI display only. The actual cron lives in
    # AICC Scheduler (project THEMIS → SCHEDULER). Edit it there to change
    # when jobs actually run.
    logger.info("Scheduler settings saved (AICC owns the cron)")
    return {"status": "ok"}


@router.get("/scheduler-logs", response_model=list[SchedulerRunLogOut])
def list_scheduler_logs(
    scheduler_id: str,
    limit: int = 20,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Return the most recent scheduler runs, newest first.

    Read-only. summary_json is intentionally omitted from the response —
    it stays in the DB for future drilldowns.
    """
    if scheduler_id not in ("ro", "eu"):
        raise HTTPException(status_code=400, detail="scheduler_id must be 'ro' or 'eu'")

    capped = max(1, min(limit, 200))

    rows = (
        db.query(SchedulerRunLog)
        .filter(SchedulerRunLog.scheduler_id == scheduler_id)
        .order_by(SchedulerRunLog.ran_at.desc())
        .limit(capped)
        .all()
    )
    return [
        SchedulerRunLogOut(
            id=r.id,
            scheduler_id=r.scheduler_id,
            ran_at=r.ran_at.isoformat(),
            trigger=r.trigger,
            status=r.status,
            laws_checked=r.laws_checked,
            new_versions=r.new_versions,
            errors=r.errors,
        )
        for r in rows
    ]


@router.get("/law-check-logs", response_model=list[LawCheckLogOut])
def list_law_check_logs(
    limit: int = 20,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Combined feed of per-law update checks across both sources, newest first.

    Read-only. Admin-only.
    """
    capped = max(1, min(limit, 200))

    rows = (
        db.query(LawCheckLog, Law, User)
        .join(Law, Law.id == LawCheckLog.law_id)
        .outerjoin(User, User.id == LawCheckLog.user_id)
        .order_by(LawCheckLog.checked_at.desc())
        .limit(capped)
        .all()
    )

    return [
        LawCheckLogOut(
            id=log.id,
            law_id=log.law_id,
            source=log.source,
            law_label=f"{law.title} ({law.law_number}/{law.law_year})",
            checked_at=log.checked_at.isoformat(),
            user_email=user.email if user else None,
            new_versions=log.new_versions,
            status=log.status,
            error_message=log.error_message,
        )
        for (log, law, user) in rows
    ]


# Note: the old GET /discovery-progress/{job_type} endpoint was removed when
# discovery moved to the unified jobs system. Frontend now polls /api/jobs by
# kind ("discover_ro" / "discover_eu") instead.
