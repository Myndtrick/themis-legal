"""Tests for scheduler_log_service.record_run and GET /api/admin/scheduler-logs."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.scheduler_run_log import SchedulerRunLog
from app.services import scheduler_log_service


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def test_record_run_inserts_row_with_expected_fields(db):
    results = {"checked": 142, "discovered": 3, "errors": 0, "extra": "kept"}

    scheduler_log_service.record_run(db, "ro", results, "scheduled")

    rows = db.query(SchedulerRunLog).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.scheduler_id == "ro"
    assert row.trigger == "scheduled"
    assert row.status == "ok"
    assert row.laws_checked == 142
    assert row.new_versions == 3
    assert row.errors == 0
    assert row.summary_json == results
    assert row.ran_at is not None


def test_record_run_marks_error_status_when_errors_present(db):
    scheduler_log_service.record_run(
        db, "eu", {"checked": 50, "discovered": 0, "errors": 2}, "manual"
    )
    row = db.query(SchedulerRunLog).one()
    assert row.status == "error"
    assert row.trigger == "manual"
    assert row.scheduler_id == "eu"


def test_record_run_swallows_db_failures(db, monkeypatch, caplog):
    """A logging failure must not break the discovery run."""
    import logging

    def boom(*a, **kw):
        raise RuntimeError("db is down")

    monkeypatch.setattr(db, "add", boom)

    with caplog.at_level(logging.WARNING, logger="app.services.scheduler_log_service"):
        # Should not raise
        scheduler_log_service.record_run(
            db, "ro", {"checked": 1, "discovered": 0, "errors": 0}, "scheduled"
        )
    assert any("db is down" in r.message for r in caplog.records)


def test_record_run_rolls_back_when_commit_fails(db, monkeypatch, caplog):
    """When commit fails, the staged row must be rolled back and the error swallowed."""
    import logging

    real_commit = db.commit

    def boom_commit():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db, "commit", boom_commit)

    with caplog.at_level(logging.WARNING, logger="app.services.scheduler_log_service"):
        # Should not raise
        scheduler_log_service.record_run(
            db, "ro", {"checked": 1, "discovered": 0, "errors": 0}, "scheduled"
        )

    assert any("commit failed" in r.message for r in caplog.records)

    # Restore commit and confirm the failed row is NOT in the table.
    monkeypatch.setattr(db, "commit", real_commit)
    assert db.query(SchedulerRunLog).count() == 0


import datetime as _dt
from fastapi.testclient import TestClient

from app.auth import require_admin, get_current_user
from app.database import get_db
from app.main import app as fastapi_app
from app.models.user import User


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_admin():
        return User(id=1, email="admin@example.com", role="admin")

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[require_admin] = override_admin
    fastapi_app.dependency_overrides[get_current_user] = override_admin
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


def _seed_logs(db):
    base = _dt.datetime(2026, 4, 8, 9, 0, 0, tzinfo=_dt.timezone.utc)
    for i in range(5):
        db.add(SchedulerRunLog(
            scheduler_id="ro",
            ran_at=base + _dt.timedelta(hours=i),
            trigger="scheduled" if i % 2 == 0 else "manual",
            status="ok",
            laws_checked=100 + i,
            new_versions=i,
            errors=0,
            summary_json={"checked": 100 + i, "discovered": i, "errors": 0},
        ))
    db.add(SchedulerRunLog(
        scheduler_id="eu",
        ran_at=base,
        trigger="scheduled",
        status="error",
        laws_checked=10,
        new_versions=0,
        errors=1,
        summary_json={"checked": 10, "discovered": 0, "errors": 1},
    ))
    db.commit()


def test_list_scheduler_logs_returns_rows_descending(client, db):
    _seed_logs(db)
    res = client.get("/api/admin/scheduler-logs?scheduler_id=ro")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 5
    timestamps = [r["ran_at"] for r in rows]
    assert timestamps == sorted(timestamps, reverse=True)
    assert rows[0]["laws_checked"] == 104
    assert rows[0]["new_versions"] == 4
    assert "summary_json" not in rows[0]


def test_list_scheduler_logs_respects_limit(client, db):
    _seed_logs(db)
    res = client.get("/api/admin/scheduler-logs?scheduler_id=ro&limit=2")
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_list_scheduler_logs_filters_by_scheduler_id(client, db):
    _seed_logs(db)
    res = client.get("/api/admin/scheduler-logs?scheduler_id=eu")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "error"
    assert rows[0]["errors"] == 1


def test_list_scheduler_logs_rejects_bad_scheduler_id(client):
    res = client.get("/api/admin/scheduler-logs?scheduler_id=fr")
    assert res.status_code == 400


def test_list_scheduler_logs_caps_limit_at_200(client, db):
    _seed_logs(db)
    res = client.get("/api/admin/scheduler-logs?scheduler_id=ro&limit=9999")
    assert res.status_code == 200  # accepted, just capped
    assert len(res.json()) <= 200


def test_list_scheduler_logs_empty_returns_empty_array(client):
    res = client.get("/api/admin/scheduler-logs?scheduler_id=ro")
    assert res.status_code == 200
    assert res.json() == []
