"""Tests for law_check_log_service.record_check and the two read endpoints."""
import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.law import Law
from app.models.law_check_log import LawCheckLog
from app.services import law_check_log_service
import app.models.category  # noqa: F401 — register categories table
import app.models.user  # noqa: F401 — register users table


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


def _make_law(db, *, source="ro", title="Test Law"):
    law = Law(title=title, law_number="500", law_year=2020, source=source)
    db.add(law)
    db.commit()
    return law


def test_record_check_inserts_row_with_expected_fields(db):
    law = _make_law(db, source="ro")

    law_check_log_service.record_check(
        db, law=law, user_id=42, new_versions=3, status="ok"
    )

    rows = db.query(LawCheckLog).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.law_id == law.id
    assert row.source == "ro"
    assert row.user_id == 42
    assert row.new_versions == 3
    assert row.status == "ok"
    assert row.error_message is None
    assert row.checked_at is not None


def test_record_check_stores_error_message_when_status_is_error(db):
    law = _make_law(db, source="eu")

    law_check_log_service.record_check(
        db, law=law, user_id=1, new_versions=0, status="error", error_message="upstream 503"
    )

    row = db.query(LawCheckLog).one()
    assert row.status == "error"
    assert row.error_message == "upstream 503"
    assert row.source == "eu"


def test_record_check_truncates_long_error_messages(db):
    law = _make_law(db)
    long_msg = "x" * 2000

    law_check_log_service.record_check(
        db, law=law, user_id=1, new_versions=0, status="error", error_message=long_msg
    )

    row = db.query(LawCheckLog).one()
    assert len(row.error_message) == 512
    assert row.error_message == "x" * 512


def test_record_check_accepts_null_user_id(db):
    law = _make_law(db)

    law_check_log_service.record_check(
        db, law=law, user_id=None, new_versions=0, status="ok"
    )

    row = db.query(LawCheckLog).one()
    assert row.user_id is None


def test_record_check_swallows_db_failures(db, monkeypatch, caplog):
    """A logging failure must not break the underlying check call."""
    law = _make_law(db)

    def boom(*a, **kw):
        raise RuntimeError("db is down")

    monkeypatch.setattr(db, "add", boom)

    with caplog.at_level(logging.WARNING, logger="app.services.law_check_log_service"):
        # Should not raise
        law_check_log_service.record_check(
            db, law=law, user_id=1, new_versions=0, status="ok"
        )
    assert any("db is down" in r.message for r in caplog.records)


def test_record_check_rolls_back_when_commit_fails(db, monkeypatch, caplog):
    """When commit fails, the staged row must be rolled back and the error swallowed."""
    law = _make_law(db)
    real_commit = db.commit

    def boom_commit():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db, "commit", boom_commit)

    with caplog.at_level(logging.WARNING, logger="app.services.law_check_log_service"):
        # Should not raise
        law_check_log_service.record_check(
            db, law=law, user_id=1, new_versions=0, status="ok"
        )

    assert any("commit failed" in r.message for r in caplog.records)

    monkeypatch.setattr(db, "commit", real_commit)
    assert db.query(LawCheckLog).count() == 0
