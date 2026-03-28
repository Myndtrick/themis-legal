# backend/tests/test_settings_endpoints.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.database import get_db, Base
from app.services.model_seed import seed_models

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = TestSession()
    seed_models(db)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_list_models_returns_all_13(client):
    res = client.get("/api/settings/models")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 13


def test_toggle_model_disabled(client):
    res = client.put("/api/settings/models/gpt-4o", json={"enabled": False})
    assert res.status_code == 200
    res = client.get("/api/settings/models")
    gpt4o = next(m for m in res.json() if m["id"] == "gpt-4o")
    assert gpt4o["enabled"] is False


def test_list_assignments(client):
    res = client.get("/api/settings/model-assignments")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 7
    assert any(a["task"] == "issue_classification" for a in data)


def test_update_assignment(client):
    res = client.put(
        "/api/settings/model-assignments",
        json={"task": "issue_classification", "model_id": "claude-sonnet-4-6"},
    )
    assert res.status_code == 200
    res = client.get("/api/settings/model-assignments")
    ic = next(a for a in res.json() if a["task"] == "issue_classification")
    assert ic["model_id"] == "claude-sonnet-4-6"


def test_assign_incapable_model_fails(client):
    res = client.put(
        "/api/settings/model-assignments",
        json={"task": "issue_classification", "model_id": "mistral-ocr"},
    )
    assert res.status_code == 422
