"""In-process background job runner backed by SQLite.

This is the foundation that lets long-running operations (imports, version
discovery, deletes) survive page navigation. The shape is:

  endpoint -> JobService.submit(kind, params, runner) -> {job_id}
                            |
                            v
                  ThreadPoolExecutor worker
                            |
                            v
            opens its own Session, calls runner(...)
            updates the Job row with phase/current/total
            writes status=succeeded|failed at the end

The frontend then polls GET /api/jobs/{job_id} and resumes after refresh.

Why a thread pool, not Celery / RQ / arq?
  This app is single-process FastAPI on SQLite. A real queue would be massive
  overkill and add operational overhead (Redis, broker, worker process). The
  in-process executor is enough — it can be replaced later without touching
  callers if scaling demands it.
"""
from __future__ import annotations

import datetime
import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.job import (
    ACTIVE_STATUSES,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    Job,
)

logger = logging.getLogger(__name__)


# Single shared executor. 4 workers is plenty for SQLite + a single-user app —
# imports and discovery are I/O bound (HTTP fetches) and SQLite serializes
# writes anyway.
_executor: ThreadPoolExecutor = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="job-worker"
)

# Lock to serialize concurrency checks against the jobs table. Without this,
# two POSTs to e.g. /trigger-discovery could both pass the "is anything
# running?" check before either has written its row. The contention here is
# trivial — only job submission, not the work itself.
_submit_lock = threading.Lock()


# Type alias for runner functions. A runner is given:
#   db:           a fresh Session it owns and must use carefully
#   job_id:       the job row to update via update_progress()
#   params:       the dict that was passed to submit()
# It returns a JSON-serializable result on success, or raises on failure.
RunnerFn = Callable[[Session, str, dict[str, Any]], Any]


# ---------- Submission ----------


def submit(
    kind: str,
    params: dict[str, Any] | None,
    runner: RunnerFn,
    *,
    entity_kind: str | None = None,
    entity_id: str | int | None = None,
    user_id: int | None = None,
    db: Session | None = None,
) -> str:
    """Create a Job row and dispatch its runner to the worker pool.

    Returns the new job_id immediately. Caller does not wait for completion.

    `db` is optional and only used for the initial INSERT. The runner always
    opens its own session — never touch the caller's session from the worker
    thread, because Sessions are not thread-safe.
    """
    job_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow()
    params_json = json.dumps(params) if params is not None else None

    owns_session = db is None
    if owns_session:
        db = SessionLocal()

    try:
        with _submit_lock:
            job = Job(
                id=job_id,
                kind=kind,
                status=STATUS_PENDING,
                params_json=params_json,
                entity_kind=entity_kind,
                entity_id=str(entity_id) if entity_id is not None else None,
                created_by_user_id=user_id,
                created_at=now,
            )
            db.add(job)
            db.commit()
    finally:
        if owns_session:
            db.close()

    _executor.submit(_run_job, job_id, runner, params or {})
    logger.info("Submitted job %s kind=%s", job_id, kind)
    return job_id


def _run_job(job_id: str, runner: RunnerFn, params: dict[str, Any]) -> None:
    """Worker entrypoint. Runs in a pool thread with its own DB session."""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            logger.error("Job %s vanished before worker started", job_id)
            return
        job.status = STATUS_RUNNING
        job.started_at = datetime.datetime.utcnow()
        db.commit()

        try:
            result = runner(db, job_id, params)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Job %s failed: %s", job_id, exc)
            db.rollback()
            _mark_failed(db, job_id, exc)
            return

        # Re-fetch in case the runner refreshed/expired the row.
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            return
        job.status = STATUS_SUCCEEDED
        job.finished_at = datetime.datetime.utcnow()
        try:
            job.result_json = json.dumps(result) if result is not None else None
        except (TypeError, ValueError) as exc:
            logger.warning("Job %s result not JSON-serializable: %s", job_id, exc)
            job.result_json = json.dumps({"_warning": "result not serializable"})
        db.commit()
        logger.info("Job %s succeeded", job_id)
    finally:
        db.close()


def _mark_failed(db: Session, job_id: str, exc: BaseException) -> None:
    """Persist a failure terminal state. Best-effort: never raises."""
    try:
        # Try to map to ThemisError shape if available, else generic.
        err_payload: dict[str, Any]
        try:
            from app.errors import map_exception_to_error  # local import to avoid cycles

            mapped = map_exception_to_error(exc)
            err_payload = mapped.to_dict()
        except Exception:
            err_payload = {"code": "internal", "message": str(exc) or exc.__class__.__name__}

        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            return
        job.status = STATUS_FAILED
        job.finished_at = datetime.datetime.utcnow()
        job.error_json = json.dumps(err_payload)
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to mark job %s as failed", job_id)
        try:
            db.rollback()
        except Exception:
            pass


# ---------- Progress updates (called from runner threads) ----------


def update_progress(
    db: Session,
    job_id: str,
    *,
    phase: str | None = None,
    current: int | None = None,
    total: int | None = None,
    entity_kind: str | None = None,
    entity_id: str | int | None = None,
) -> None:
    """Push a progress update to the job row.

    Any field left as None is left unchanged. Safe to call repeatedly. Uses a
    short transaction so the next poll sees the update.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        return
    if phase is not None:
        job.phase = phase[:200]
    if current is not None:
        job.current = current
    if total is not None:
        job.total = total
    if entity_kind is not None:
        job.entity_kind = entity_kind
    if entity_id is not None:
        job.entity_id = str(entity_id)
    db.commit()


# ---------- Queries ----------


def get(db: Session, job_id: str) -> Job | None:
    return db.query(Job).filter(Job.id == job_id).first()


def list_jobs(
    db: Session,
    *,
    kind: str | None = None,
    entity_kind: str | None = None,
    entity_id: str | int | None = None,
    active: bool | None = None,
    limit: int = 50,
) -> list[Job]:
    q = db.query(Job)
    if kind is not None:
        q = q.filter(Job.kind == kind)
    if entity_kind is not None:
        q = q.filter(Job.entity_kind == entity_kind)
    if entity_id is not None:
        q = q.filter(Job.entity_id == str(entity_id))
    if active is True:
        q = q.filter(Job.status.in_(ACTIVE_STATUSES))
    elif active is False:
        q = q.filter(~Job.status.in_(ACTIVE_STATUSES))
    return q.order_by(Job.created_at.desc()).limit(limit).all()


def has_active(
    db: Session,
    *,
    kind: str | None = None,
    entity_kind: str | None = None,
    entity_id: str | int | None = None,
) -> bool:
    """Concurrency-check helper. Used by endpoints that disallow duplicates."""
    q = db.query(Job.id).filter(Job.status.in_(ACTIVE_STATUSES))
    if kind is not None:
        q = q.filter(Job.kind == kind)
    if entity_kind is not None:
        q = q.filter(Job.entity_kind == entity_kind)
    if entity_id is not None:
        q = q.filter(Job.entity_id == str(entity_id))
    return db.query(q.exists()).scalar()


# ---------- Startup recovery ----------


def recover_interrupted_jobs(db: Session) -> int:
    """Mark any jobs left running by a previous process as failed.

    Called once at app startup. Without this, a crashed/killed worker would
    leave rows in `running` forever and the UI would spin.

    Returns the number of rows updated.
    """
    interrupted = (
        db.query(Job).filter(Job.status.in_((STATUS_PENDING, STATUS_RUNNING))).all()
    )
    if not interrupted:
        return 0
    err = json.dumps(
        {"code": "interrupted", "message": "Process restarted before completion"}
    )
    now = datetime.datetime.utcnow()
    for job in interrupted:
        job.status = STATUS_FAILED
        job.error_json = err
        job.finished_at = now
    db.commit()
    logger.info("Recovered %d interrupted job(s) on startup", len(interrupted))
    return len(interrupted)


# ---------- Serialization for API responses ----------


def to_dict(job: Job) -> dict[str, Any]:
    """Render a Job row for the JSON API. JSON-encoded TEXT columns get parsed."""

    def _decode(s: str | None) -> Any:
        if s is None:
            return None
        try:
            return json.loads(s)
        except (TypeError, ValueError):
            return s

    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "phase": job.phase,
        "current": job.current,
        "total": job.total,
        "params": _decode(job.params_json),
        "result": _decode(job.result_json),
        "error": _decode(job.error_json),
        "entity_kind": job.entity_kind,
        "entity_id": job.entity_id,
        "created_by_user_id": job.created_by_user_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def to_dicts(jobs: Iterable[Job]) -> list[dict[str, Any]]:
    return [to_dict(j) for j in jobs]
