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
    def boom(*a, **kw):
        raise RuntimeError("db is down")

    monkeypatch.setattr(db, "add", boom)

    # Should not raise
    scheduler_log_service.record_run(db, "ro", {"checked": 1, "discovered": 0, "errors": 0}, "scheduled")
    assert any("scheduler_run_log" in r.message or "db is down" in r.message for r in caplog.records)
