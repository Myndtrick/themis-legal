"""Tests for the GET endpoints on /api/jobs."""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import Base, get_db
from app.main import app as fastapi_app
from app.models.job import STATUS_RUNNING, STATUS_SUCCEEDED, Job
from app.models.user import User
import app.models.category  # noqa: F401 — register category table for create_all


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

    def override_user():
        return User(id=1, email="t@example.com")

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_current_user] = override_user
    db = TestingSessionLocal()
    yield TestClient(fastapi_app), db
    db.close()
    fastapi_app.dependency_overrides.clear()


def _seed(db, **kw):
    defaults = dict(
        id="job-1",
        kind="test",
        status=STATUS_SUCCEEDED,
        created_at=datetime.datetime.utcnow(),
    )
    defaults.update(kw)
    job = Job(**defaults)
    db.add(job)
    db.commit()
    return job


def test_get_returns_job(client_and_db):
    client, db = client_and_db
    _seed(db, id="abc", kind="import_law", phase="parsing", current=2, total=10)
    res = client.get("/api/jobs/abc")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "abc"
    assert body["kind"] == "import_law"
    assert body["phase"] == "parsing"
    assert body["current"] == 2
    assert body["total"] == 10


def test_get_returns_404_for_unknown(client_and_db):
    client, _ = client_and_db
    res = client.get("/api/jobs/missing")
    assert res.status_code == 404


def test_list_filters_by_kind_and_active(client_and_db):
    client, db = client_and_db
    _seed(db, id="a", kind="import_law", status=STATUS_RUNNING)
    _seed(db, id="b", kind="import_law", status=STATUS_SUCCEEDED)
    _seed(db, id="c", kind="discover_ro", status=STATUS_RUNNING)

    res = client.get("/api/jobs?kind=import_law")
    ids = {j["id"] for j in res.json()["jobs"]}
    assert ids == {"a", "b"}

    res = client.get("/api/jobs?kind=import_law&active=true")
    ids = {j["id"] for j in res.json()["jobs"]}
    assert ids == {"a"}


def test_list_filters_by_entity(client_and_db):
    client, db = client_and_db
    _seed(db, id="d1", kind="delete_law", status=STATUS_RUNNING, entity_kind="law", entity_id="42")
    _seed(db, id="d2", kind="delete_law", status=STATUS_RUNNING, entity_kind="law", entity_id="99")

    res = client.get("/api/jobs?entity_kind=law&entity_id=42")
    ids = {j["id"] for j in res.json()["jobs"]}
    assert ids == {"d1"}
