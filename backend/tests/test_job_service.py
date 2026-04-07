"""Tests for the in-process JobService."""
import json
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.job import (
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    Job,
)
from app.services import job_service
import app.models.job  # noqa: F401 — register table


@pytest.fixture
def db():
    """A fresh in-memory SQLite shared across threads (StaticPool)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)

    # JobService opens its own sessions via app.database.SessionLocal — point
    # that at our test engine for the duration of this fixture.
    import app.database as database_mod

    original = database_mod.SessionLocal
    database_mod.SessionLocal = SessionLocal
    # job_service captured a reference at import time too
    job_service.SessionLocal = SessionLocal  # type: ignore[attr-defined]

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        database_mod.SessionLocal = original
        job_service.SessionLocal = original  # type: ignore[attr-defined]


def _wait_for_terminal(db, job_id: str, timeout: float = 5.0) -> Job:
    """Poll the DB until the job reaches a terminal state."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        db.expire_all()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is not None and job.status in (STATUS_SUCCEEDED, STATUS_FAILED):
            return job
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not reach terminal state in {timeout}s")


def test_submit_runs_runner_and_marks_succeeded(db):
    def runner(_db, _job_id, params):
        return {"echoed": params["x"] * 2}

    job_id = job_service.submit("test_kind", {"x": 21}, runner)
    job = _wait_for_terminal(db, job_id)

    assert job.status == STATUS_SUCCEEDED
    assert job.started_at is not None
    assert job.finished_at is not None
    assert json.loads(job.result_json) == {"echoed": 42}
    assert job.error_json is None


def test_submit_marks_failed_on_exception(db):
    def runner(_db, _job_id, _params):
        raise ValueError("nope")

    job_id = job_service.submit("test_kind", None, runner)
    job = _wait_for_terminal(db, job_id)

    assert job.status == STATUS_FAILED
    assert job.error_json is not None
    err = json.loads(job.error_json)
    # message field is populated either way (mapped error or generic fallback)
    assert "message" in err


def test_update_progress_persists_phase_current_total(db):
    """Runner uses update_progress; the row reflects the latest values."""
    seen_running = threading_event = None  # placeholder so name lints

    import threading

    started = threading.Event()
    release = threading.Event()

    def runner(inner_db, job_id, _params):
        job_service.update_progress(
            inner_db, job_id, phase="phase1", current=1, total=10
        )
        started.set()
        release.wait(timeout=2)
        job_service.update_progress(
            inner_db, job_id, phase="phase2", current=5, total=10
        )
        return {"ok": True}

    job_id = job_service.submit("test_kind", None, runner)
    assert started.wait(timeout=2)

    # Mid-flight read: progress should reflect phase1
    db.expire_all()
    job = db.query(Job).filter(Job.id == job_id).first()
    assert job.status == STATUS_RUNNING
    assert job.phase == "phase1"
    assert job.current == 1
    assert job.total == 10

    release.set()
    final = _wait_for_terminal(db, job_id)
    assert final.phase == "phase2"
    assert final.current == 5


def test_recover_interrupted_jobs_marks_running_as_failed(db):
    import datetime

    db.add(
        Job(
            id="ghost-1",
            kind="test_kind",
            status=STATUS_RUNNING,
            started_at=datetime.datetime.utcnow(),
        )
    )
    db.add(
        Job(
            id="ghost-2",
            kind="test_kind",
            status="pending",
        )
    )
    db.add(
        Job(
            id="done-1",
            kind="test_kind",
            status=STATUS_SUCCEEDED,
        )
    )
    db.commit()

    n = job_service.recover_interrupted_jobs(db)
    assert n == 2

    db.expire_all()
    g1 = db.query(Job).filter(Job.id == "ghost-1").first()
    g2 = db.query(Job).filter(Job.id == "ghost-2").first()
    done = db.query(Job).filter(Job.id == "done-1").first()
    assert g1.status == STATUS_FAILED
    assert g2.status == STATUS_FAILED
    assert json.loads(g1.error_json)["code"] == "interrupted"
    assert done.status == STATUS_SUCCEEDED  # untouched


def test_has_active_filters_correctly(db):
    db.add(Job(id="a", kind="k1", status=STATUS_RUNNING))
    db.add(Job(id="b", kind="k1", status=STATUS_SUCCEEDED))
    db.add(Job(id="c", kind="k2", status=STATUS_RUNNING, entity_kind="law", entity_id="42"))
    db.commit()

    assert job_service.has_active(db, kind="k1") is True
    assert job_service.has_active(db, kind="k_none") is False
    assert job_service.has_active(db, entity_kind="law", entity_id=42) is True
    assert job_service.has_active(db, entity_kind="law", entity_id=99) is False


def test_list_jobs_filters_and_orders(db):
    import datetime

    base = datetime.datetime(2026, 1, 1)
    db.add(Job(id="old", kind="k1", status=STATUS_SUCCEEDED, created_at=base))
    db.add(
        Job(
            id="new",
            kind="k1",
            status=STATUS_RUNNING,
            created_at=base + datetime.timedelta(hours=1),
        )
    )
    db.add(Job(id="other", kind="k2", status=STATUS_RUNNING, created_at=base))
    db.commit()

    rows = job_service.list_jobs(db, kind="k1")
    assert [j.id for j in rows] == ["new", "old"]  # desc by created_at

    active = job_service.list_jobs(db, kind="k1", active=True)
    assert [j.id for j in active] == ["new"]

    inactive = job_service.list_jobs(db, kind="k1", active=False)
    assert [j.id for j in inactive] == ["old"]


def test_to_dict_decodes_json_fields(db):
    db.add(
        Job(
            id="x",
            kind="k",
            status=STATUS_SUCCEEDED,
            result_json=json.dumps({"law_id": 7}),
            error_json=None,
            params_json=json.dumps({"ver_id": "123"}),
        )
    )
    db.commit()

    job = db.query(Job).filter(Job.id == "x").first()
    payload = job_service.to_dict(job)
    assert payload["result"] == {"law_id": 7}
    assert payload["params"] == {"ver_id": "123"}
    assert payload["error"] is None
