"""Tests for POST /api/laws/{id}/check-updates."""
import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import Base, get_db
from app.main import app as fastapi_app
from app.models.law import Law, LawVersion, KnownVersion
from app.models.user import User
import app.models.category  # register categories table


@pytest.fixture
def client_and_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_get_current_user():
        return User(id=1, email="test@example.com")

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_current_user] = override_get_current_user
    db = TestingSessionLocal()
    yield TestClient(fastapi_app), db
    db.close()
    fastapi_app.dependency_overrides.clear()


def _seed_law(db, *, ver_ids_with_dates, current_ver_id=None):
    law = Law(title="Test Law", law_number="500", law_year=2020)
    db.add(law)
    db.flush()
    for vid, d in ver_ids_with_dates:
        db.add(LawVersion(
            law_id=law.id, ver_id=vid, date_in_force=d,
            is_current=(vid == current_ver_id),
        ))
    db.commit()
    return law


def test_check_updates_returns_200_when_no_law_version_is_current(client_and_db):
    """The dead-state bug: previously returned 400. Now returns 200 with discovered count."""
    client, db = client_and_db
    law = _seed_law(db, ver_ids_with_dates=[
        ("V1", datetime.date(2024, 1, 1)),
        ("V2", datetime.date(2024, 6, 1)),
    ], current_ver_id=None)  # nothing is_current

    mock_result = {
        "document": {
            "next_ver": None,
            "history": [
                {"ver_id": "V2", "date": "2024-06-01"},
                {"ver_id": "V1", "date": "2024-01-01"},
            ],
        }
    }

    with patch("app.services.version_discovery.fetch_document", return_value=mock_result):
        response = client.post(f"/api/laws/{law.id}/check-updates")

    assert response.status_code == 200
    body = response.json()
    assert "discovered" in body
    assert "last_checked_at" in body
    assert body["last_checked_at"] is not None


def test_check_updates_does_not_auto_import(client_and_db):
    """The new contract: check-updates only refreshes KnownVersion, never imports text."""
    client, db = client_and_db
    law = _seed_law(db, ver_ids_with_dates=[
        ("V1", datetime.date(2024, 1, 1)),
    ], current_ver_id="V1")

    mock_result = {
        "document": {
            "next_ver": None,
            "history": [
                {"ver_id": "V99", "date": "2025-01-01"},  # new upstream version
                {"ver_id": "V1", "date": "2024-01-01"},
            ],
        }
    }

    with patch("app.services.version_discovery.fetch_document", return_value=mock_result):
        response = client.post(f"/api/laws/{law.id}/check-updates")

    assert response.status_code == 200
    # No new LawVersion should have been created — only KnownVersion
    lv_ids = {lv.ver_id for lv in
              db.query(LawVersion).filter(LawVersion.law_id == law.id).all()}
    assert lv_ids == {"V1"}  # V99 must NOT have been auto-imported

    kv_ids = {kv.ver_id for kv in
              db.query(KnownVersion).filter(KnownVersion.law_id == law.id).all()}
    assert "V99" in kv_ids  # but V99 should now be a KnownVersion


def test_check_updates_returns_404_for_unknown_law(client_and_db):
    client, _ = client_and_db
    response = client.post("/api/laws/999999/check-updates")
    assert response.status_code == 404
