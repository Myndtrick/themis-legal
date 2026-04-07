import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import NEXTAUTH_SECRET
from app.database import get_db
from app.models.user import AllowedEmail, User
from app.scheduler import scheduler, last_run_results
from app.services.user_service import ADMIN_EMAILS, verify_and_upsert_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin"])


# --- Auth verification (called by NextAuth signIn callback) ---


class VerifyUserRequest(BaseModel):
    email: str
    name: str | None = None
    picture: str | None = None


class VerifyUserResponse(BaseModel):
    email: str
    name: str | None
    role: str
    allowed: bool


@router.post("/verify-user", response_model=VerifyUserResponse)
def verify_user(
    body: VerifyUserRequest,
    x_auth_secret: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    """Called by NextAuth during sign-in to check if user is allowed.

    Protected by shared secret header, not JWT (since user has no JWT yet).
    """
    if x_auth_secret != NEXTAUTH_SECRET:
        raise HTTPException(status_code=403, detail="Invalid auth secret")

    user = verify_and_upsert_user(db, body.email, body.name, body.picture)
    if not user:
        return VerifyUserResponse(
            email=body.email, name=body.name, role="", allowed=False
        )

    return VerifyUserResponse(
        email=user.email, name=user.name, role=user.role, allowed=True
    )


# --- Whitelist management (admin only) ---


class WhitelistEntry(BaseModel):
    email: str
    added_by: str
    created_at: str
    is_admin: bool


class AddEmailRequest(BaseModel):
    email: str


@router.get("/whitelist", response_model=list[WhitelistEntry])
def list_whitelist(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all users and whitelisted emails."""
    entries: list[WhitelistEntry] = []

    # Add existing users
    users = db.query(User).order_by(User.created_at).all()
    for u in users:
        entries.append(WhitelistEntry(
            email=u.email,
            added_by="system" if u.email in ADMIN_EMAILS else u.email,
            created_at=u.created_at.isoformat(),
            is_admin=u.role == "admin",
        ))

    # Add whitelisted emails not yet signed in
    seen_emails = {e.email for e in entries}
    allowed = db.query(AllowedEmail).order_by(AllowedEmail.created_at).all()
    for a in allowed:
        if a.email not in seen_emails:
            entries.append(WhitelistEntry(
                email=a.email,
                added_by=a.added_by,
                created_at=a.created_at.isoformat(),
                is_admin=False,
            ))

    return entries


@router.post("/whitelist", status_code=201)
def add_to_whitelist(
    body: AddEmailRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Add an email to the whitelist."""
    email = body.email.strip().lower()

    # Check if already exists
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise HTTPException(status_code=409, detail="Email already has access")

    existing_allowed = db.query(AllowedEmail).filter(AllowedEmail.email == email).first()
    if existing_allowed:
        raise HTTPException(status_code=409, detail="Email already whitelisted")

    db.add(AllowedEmail(email=email, added_by=admin.email))
    db.commit()
    return {"email": email, "status": "added"}


@router.delete("/whitelist/{email}")
def remove_from_whitelist(
    email: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Remove an email from the whitelist. Cannot remove admins."""
    # Check if trying to remove an admin
    user = db.query(User).filter(User.email == email).first()
    if user and user.role == "admin":
        raise HTTPException(status_code=400, detail="Cannot remove admin users")

    # Remove from AllowedEmail
    allowed = db.query(AllowedEmail).filter(AllowedEmail.email == email).first()
    if allowed:
        db.delete(allowed)

    # Remove from User table too (revokes access)
    if user:
        db.delete(user)

    db.commit()
    return {"email": email, "status": "removed"}


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

        return results

    return _runner
