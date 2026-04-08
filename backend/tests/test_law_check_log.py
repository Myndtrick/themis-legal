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


# --- Endpoint tests ---

import datetime as _dt
from fastapi.testclient import TestClient

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.main import app as fastapi_app
from app.models.user import User


@pytest.fixture
def admin_client(db):
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


def _seed_user(db, email="ana@example.com"):
    user = User(email=email, role="user")
    db.add(user)
    db.commit()
    return user


def _seed_log_set(db):
    """Seed: 1 user, 2 laws (RO + EU), 5 logs across them, varied timestamps."""
    user = _seed_user(db)
    ro_law = Law(title="Legea societăților", law_number="31", law_year=1990, source="ro")
    eu_law = Law(title="GDPR", law_number="2016/679", law_year=2016, source="eu")
    db.add(ro_law)
    db.add(eu_law)
    db.commit()

    base = _dt.datetime(2026, 4, 8, 9, 0, 0, tzinfo=_dt.timezone.utc)
    for i in range(3):
        db.add(LawCheckLog(
            law_id=ro_law.id, source="ro",
            checked_at=base + _dt.timedelta(hours=i),
            user_id=user.id, new_versions=i, status="ok",
        ))
    for i in range(2):
        db.add(LawCheckLog(
            law_id=eu_law.id, source="eu",
            checked_at=base + _dt.timedelta(hours=10 + i),
            user_id=user.id, new_versions=0, status="ok",
        ))
    db.commit()
    return ro_law, eu_law, user


def test_combined_feed_returns_rows_descending(admin_client, db):
    _seed_log_set(db)
    res = admin_client.get("/api/admin/law-check-logs")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 5
    timestamps = [r["checked_at"] for r in rows]
    assert timestamps == sorted(timestamps, reverse=True)
    assert rows[0]["source"] == "eu"
    assert rows[0]["user_email"] == "ana@example.com"
    assert "law_label" in rows[0]


def test_combined_feed_respects_limit(admin_client, db):
    _seed_log_set(db)
    res = admin_client.get("/api/admin/law-check-logs?limit=2")
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_combined_feed_caps_limit_at_200(admin_client, db):
    _seed_log_set(db)
    res = admin_client.get("/api/admin/law-check-logs?limit=9999")
    assert res.status_code == 200
    assert len(res.json()) <= 200


def test_combined_feed_empty_returns_empty_array(admin_client):
    res = admin_client.get("/api/admin/law-check-logs")
    assert res.status_code == 200
    assert res.json() == []


def test_combined_feed_handles_null_user(admin_client, db):
    law = Law(title="Orphan", law_number="1", law_year=2020, source="ro")
    db.add(law)
    db.commit()
    db.add(LawCheckLog(
        law_id=law.id, source="ro",
        checked_at=_dt.datetime(2026, 4, 8, 12, 0, 0, tzinfo=_dt.timezone.utc),
        user_id=None, new_versions=0, status="ok",
    ))
    db.commit()

    res = admin_client.get("/api/admin/law-check-logs")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["user_email"] is None


@pytest.fixture
def user_client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_user():
        return User(id=1, email="ana@example.com", role="user")

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_current_user] = override_user
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


def test_per_law_history_returns_only_that_law(user_client, db):
    ro_law, eu_law, _ = _seed_log_set(db)

    res = user_client.get(f"/api/laws/{ro_law.id}/check-logs")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 3  # 3 RO logs seeded
    for r in rows:
        assert "law_id" not in r  # constant, omitted from response


def test_per_law_history_orders_descending(user_client, db):
    ro_law, _, _ = _seed_log_set(db)
    res = user_client.get(f"/api/laws/{ro_law.id}/check-logs")
    timestamps = [r["checked_at"] for r in res.json()]
    assert timestamps == sorted(timestamps, reverse=True)


def test_per_law_history_respects_limit(user_client, db):
    ro_law, _, _ = _seed_log_set(db)
    res = user_client.get(f"/api/laws/{ro_law.id}/check-logs?limit=2")
    assert len(res.json()) == 2


def test_per_law_history_returns_404_for_unknown_law(user_client):
    res = user_client.get("/api/laws/9999/check-logs")
    assert res.status_code == 404


def test_per_law_history_empty_returns_empty_array(user_client, db):
    law = Law(title="Quiet Law", law_number="42", law_year=2024, source="ro")
    db.add(law)
    db.commit()
    res = user_client.get(f"/api/laws/{law.id}/check-logs")
    assert res.status_code == 200
    assert res.json() == []


def test_post_check_updates_writes_log_row(user_client, db, monkeypatch):
    """End-to-end: POST /check-updates writes a log row with the right fields."""
    law = Law(title="Integration Law", law_number="100", law_year=2020, source="ro")
    db.add(law)
    db.commit()

    # Stub the discovery so the test doesn't hit the network.
    def fake_discover(_db, _law):
        return 2

    monkeypatch.setattr(
        "app.services.version_discovery.discover_versions_for_law",
        fake_discover,
    )

    res = user_client.post(f"/api/laws/{law.id}/check-updates")
    assert res.status_code == 200
    assert res.json()["discovered"] == 2

    rows = db.query(LawCheckLog).filter(LawCheckLog.law_id == law.id).all()
    assert len(rows) == 1
    log = rows[0]
    assert log.status == "ok"
    assert log.new_versions == 2
    assert log.user_id == 1
    assert log.source == "ro"
