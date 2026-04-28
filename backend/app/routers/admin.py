import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models.user import User
from app.scheduler import scheduler, last_run_results

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin"])


# --- Scheduler status & manual trigger ---


@router.get("/scheduler-status")
def get_scheduler_status(admin: User = Depends(require_admin)):
    """Return current scheduler state: running jobs, next run times, last results."""
    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_utc": next_run.isoformat() if next_run else None,
            "last_run": last_run_results.get(job.id),
        })
    return {
        "running": scheduler.running,
        "jobs": jobs,
    }


@router.post("/trigger-discovery/{job_type}")
def trigger_discovery(
    job_type: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Manually trigger a version discovery check. job_type: 'ro' or 'eu'.

    Returns `{job_id}` — the discovery itself runs in the JobService thread
    pool. Frontend polls /api/jobs/{job_id} for progress, which means the work
    is no longer tied to the request that started it.
    """
    if job_type not in ("ro", "eu"):
        raise HTTPException(status_code=400, detail="job_type must be 'ro' or 'eu'")

    from app.services import job_service

    kind = f"discover_{job_type}"

    # One discovery per kind at a time. has_active also covers a stale row
    # left in 'running' from before startup recovery — recover_interrupted_jobs
    # cleans those, but we still re-check at submission time to be safe.
    if job_service.has_active(db, kind=kind):
        raise HTTPException(status_code=409, detail=f"{job_type} discovery is already running")

    job_id = job_service.submit(
        kind=kind,
        params={"job_type": job_type},
        runner=_make_discovery_runner(job_type),
        user_id=admin.id,
        db=db,
    )

    label = "Romanian law version discovery" if job_type == "ro" else "EU law version discovery"
    logger.info("Manually triggered %s as job %s", label, job_id)
    return {"status": "started", "job_type": job_type, "label": label, "job_id": job_id}


def _make_discovery_runner(job_type: str):
    """Build a JobService runner that wraps run_daily/run_eu_weekly_discovery.

    The runner runs in a worker thread with its own DB session. The progress
    callback writes phase/current/total back to the Job row each time we move
    to the next law, which is what the frontend polls.
    """
    import datetime as _dt

    def _runner(db, job_id: str, _params: dict):
        from app.database import SessionLocal
        from app.models.scheduler_settings import SchedulerSetting
        from app.services import job_service as _js

        def _on_progress(current: int, total: int, current_law: str):
            # Use a fresh session — the runner's own session is mid-loop in
            # the discovery code path.
            progress_db = SessionLocal()
            try:
                _js.update_progress(
                    progress_db,
                    job_id,
                    phase=f"Checking: {current_law}",
                    current=current,
                    total=total,
                )
            finally:
                progress_db.close()

        if job_type == "ro":
            from app.services.version_discovery import run_daily_discovery
            results = run_daily_discovery(on_progress=_on_progress)
        else:
            from app.services.eu_version_discovery import run_eu_weekly_discovery
            results = run_eu_weekly_discovery(on_progress=_on_progress)

        # Persist last-run summary on the SchedulerSetting row, just like the
        # cron path does. We use the runner's own session here.
        setting = db.query(SchedulerSetting).filter(SchedulerSetting.id == job_type).first()
        if setting:
            setting.last_run_at = _dt.datetime.now(_dt.timezone.utc)
            setting.last_run_status = "ok" if results.get("errors", 0) == 0 else "error"
            setting.last_run_summary = results
            db.commit()

        from app.services.scheduler_log_service import record_run
        record_run(db, job_type, results, "manual")

        return results

    return _runner


# ---------------------------------------------------------------------------
# Paragraph-notes backfill (Spec 1: 2026-04-08-paragraph-notes-and-backfill)
# ---------------------------------------------------------------------------


class BackfillNotesRequest(BaseModel):
    law_id: int | None = None
    dry_run: bool = True


BACKFILL_NOTES_KIND = "backfill_notes"


@router.post("/backfill/notes")
def trigger_backfill_notes(
    req: BackfillNotesRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Spawn a paragraph-notes backfill job and return its job_id immediately.

    The backfill itself runs in the JobService thread pool. Frontend polls
    /api/jobs/{job_id} for progress and the final report — same pattern as
    /trigger-discovery, so progress survives navigation and refresh.
    """
    from app.services import job_service

    if job_service.has_active(db, kind=BACKFILL_NOTES_KIND):
        raise HTTPException(
            status_code=409,
            detail="A paragraph-notes backfill is already running",
        )

    job_id = job_service.submit(
        kind=BACKFILL_NOTES_KIND,
        params={"law_id": req.law_id, "dry_run": req.dry_run},
        runner=_backfill_notes_runner,
        user_id=admin.id,
        db=db,
    )
    logger.info(
        "Manually triggered paragraph-notes backfill (dry_run=%s, law_id=%s) as job %s",
        req.dry_run, req.law_id, job_id,
    )
    return {
        "status": "started",
        "job_id": job_id,
        "dry_run": req.dry_run,
    }


def _backfill_notes_runner(db: Session, job_id: str, params: dict) -> dict:
    """Job runner: open a fresh session and call backfill_notes with progress.

    Returns a JSON-serializable report dict that the frontend reads from
    job.result_json.
    """
    from dataclasses import asdict

    from app.database import SessionLocal
    from app.services import job_service as _js
    from app.services.notes_backfill import backfill_notes

    law_id = params.get("law_id")
    dry_run = bool(params.get("dry_run", True))

    def _on_progress(current: int, total: int) -> None:
        # Use a fresh short-lived session: the runner's `db` is mid-loop in
        # the backfill code path and writing to it concurrently is unsafe.
        progress_db = SessionLocal()
        try:
            _js.update_progress(
                progress_db,
                job_id,
                phase=f"Processing version {current} of {total}",
                current=current,
                total=total,
            )
        finally:
            progress_db.close()

    # Initial phase so the UI shows something before the first version finishes
    _js.update_progress(db, job_id, phase="Starting backfill", current=0, total=0)

    report = backfill_notes(
        db,
        law_id=law_id,
        dry_run=dry_run,
        on_progress=_on_progress,
        fetch_delay_seconds=0.5,
    )
    # Truncate the long lists so the result_json stays bounded
    return {
        "dry_run": dry_run,
        "versions_processed": report.versions_processed,
        "versions_failed": report.versions_failed,
        "paragraph_notes_to_insert": report.paragraph_notes_to_insert,
        "article_notes_to_insert": report.article_notes_to_insert,
        "text_clean_writes": report.text_clean_writes,
        "unknown_paragraph_labels": report.unknown_paragraph_labels[:200],
        "errors": report.errors[:200],
    }


# ---------------------------------------------------------------------------
# Rates backfill (Spec: 2026-04-28-rates-feed-design)
# ---------------------------------------------------------------------------

BACKFILL_RATES_KIND = "backfill_rates"


@router.post("/rates/backfill")
def trigger_rates_backfill(
    years: int = 7,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Backfill `years` years of FX + interest rates. Returns job_id."""
    if years < 1 or years > 30:
        raise HTTPException(status_code=400, detail="years must be 1..30")

    from app.services import job_service

    if job_service.has_active(db, kind=BACKFILL_RATES_KIND):
        raise HTTPException(status_code=409, detail="rates backfill is already running")

    job_id = job_service.submit(
        kind=BACKFILL_RATES_KIND,
        params={"years": years},
        runner=_rates_backfill_runner,
        user_id=admin.id,
        db=db,
    )
    logger.info("Triggered rates backfill (years=%d) as job %s", years, job_id)
    return {"status": "started", "years": years, "job_id": job_id}


def _rates_backfill_runner(db: Session, job_id: str, params: dict) -> dict:
    """Job runner: backfill rates with progress updates."""
    from app.database import SessionLocal
    from app.services import job_service as _js
    from app.services.rates.backfill import run_rates_backfill

    years_param = int(params.get("years", 7))

    def _on_progress(current: int, total: int, label: str):
        ps = SessionLocal()
        try:
            _js.update_progress(
                ps, job_id, phase=label, current=current, total=total,
            )
        finally:
            ps.close()

    return run_rates_backfill(years=years_param, on_progress=_on_progress)
