"""Read-only API for background jobs.

Jobs are created by the kind-specific endpoints (import, discovery, delete).
This router only exposes GET access — frontend polls these endpoints to
display progress and to recover state after a page refresh.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services import job_service

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])


@router.get("/{job_id}")
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    job = job_service.get(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_service.to_dict(job)


@router.get("")
def list_jobs(
    kind: str | None = Query(None),
    entity_kind: str | None = Query(None),
    entity_id: str | None = Query(None),
    active: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    jobs = job_service.list_jobs(
        db,
        kind=kind,
        entity_kind=entity_kind,
        entity_id=entity_id,
        active=active,
        limit=limit,
    )
    return {"jobs": job_service.to_dicts(jobs)}
