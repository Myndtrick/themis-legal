"""Public API: GET /api/rates/exchange and GET /api/rates/interest.

Both endpoints accept a Themis user PKCE bearer OR a shared service-token
bearer (RATES_API_TOKEN). Without auth → 401.
"""
from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient


SERVICE_TOKEN = "test-service-token"


@pytest.fixture(autouse=True)
def _patch_token(monkeypatch):
    monkeypatch.setattr("app.auth_service.RATES_API_TOKEN", SERVICE_TOKEN)


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Boot the app pointing at an in-memory test DB seeded with rate rows."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base, get_db
    import app.models.rates  # noqa: F401
    from app.models.rates import ExchangeRate, InterestRate

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    seed = Session()
    # Seed: 3 FX rows, 4 interest-rate rows
    seed.add_all([
        ExchangeRate(date="2026-03-06", currency="EUR", rate=4.9741, source="BNR"),
        ExchangeRate(date="2026-03-06", currency="USD", rate=4.3981, source="BNR"),
        ExchangeRate(date="2026-03-05", currency="EUR", rate=4.9720, source="BNR"),
        InterestRate(date="2026-03-06", rate_type="ROBOR", tenor="3M", rate=5.92, source="x"),
        InterestRate(date="2026-03-06", rate_type="ROBOR", tenor="6M", rate=6.05, source="x"),
        InterestRate(date="2026-03-06", rate_type="EURIBOR", tenor="3M", rate=2.68, source="y"),
        InterestRate(date="2026-03-05", rate_type="ROBOR", tenor="3M", rate=5.90, source="x"),
    ])
    seed.commit()
    seed.close()

    from app.main import app

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


def test_exchange_no_auth_returns_401(client):
    r = client.get("/api/rates/exchange")
    assert r.status_code == 401


def test_exchange_service_token_returns_rows(client):
    r = client.get(
        "/api/rates/exchange",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 3
    # Sorted: most recent first, then currency ASC
    assert rows[0]["date"] == "2026-03-06"
    # Service-pulled rows are sorted in JS-compatible shape
    assert "rate" in rows[0]


def test_exchange_filter_by_currency(client):
    r = client.get(
        "/api/rates/exchange?currency=EUR",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    )
    rows = r.json()
    assert len(rows) == 2
    assert all(row["currency"] == "EUR" for row in rows)


def test_exchange_filter_by_date_range(client):
    r = client.get(
        "/api/rates/exchange?from=2026-03-06&to=2026-03-06",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    )
    rows = r.json()
    assert len(rows) == 2
    assert all(row["date"] == "2026-03-06" for row in rows)


def test_exchange_limit(client):
    r = client.get(
        "/api/rates/exchange?limit=1",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    )
    assert len(r.json()) == 1


def test_interest_filter_by_rate_type(client):
    r = client.get(
        "/api/rates/interest?rate_type=ROBOR",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    )
    rows = r.json()
    assert len(rows) == 3
    assert all(row["rate_type"] == "ROBOR" for row in rows)


def test_interest_filter_by_tenor(client):
    r = client.get(
        "/api/rates/interest?tenor=3M",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    )
    rows = r.json()
    assert all(row["tenor"] == "3M" for row in rows)


def test_interest_no_auth_returns_401(client):
    r = client.get("/api/rates/interest")
    assert r.status_code == 401
