"""GET /api/rates/health — public freshness probe for monitoring.

No auth required: the response only exposes counts and dates, no rates
themselves. Lets oncall / Grafana alert if the AICC scheduler stops firing
without needing to manage a service token.
"""
from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base, get_db
    import app.models.rates  # noqa: F401
    from app.models.rates import ExchangeRate, InterestRate

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    seed = Session()
    today = datetime.date.today()
    yday = today - datetime.timedelta(days=1)
    seed.add_all([
        ExchangeRate(date=yday.isoformat(), currency="EUR", rate=4.97, source="BNR"),
        ExchangeRate(date=yday.isoformat(), currency="USD", rate=4.40, source="BNR"),
        InterestRate(date=yday.isoformat(), rate_type="ROBOR", tenor="3M", rate=5.92, source="x"),
        InterestRate(date=(today - datetime.timedelta(days=30)).isoformat(),
                     rate_type="EURIBOR", tenor="3M", rate=2.68, source="y"),
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


def test_health_no_auth_required_and_returns_freshness(client):
    """No Authorization header → 200 (it's a public probe)."""
    r = client.get("/api/rates/health")
    assert r.status_code == 200
    body = r.json()

    assert body["fx"]["row_count"] == 2
    assert body["fx"]["age_days"] == 1
    assert body["fx"]["latest_date"] is not None

    assert body["robor"]["row_count"] == 1
    assert body["robor"]["age_days"] == 1

    assert body["euribor"]["row_count"] == 1
    assert body["euribor"]["age_days"] == 30


def test_health_with_empty_db_returns_zero_counts_and_null_ages(tmp_path):
    """No rows yet → counts 0, latest_date null, age_days null. (No 5xx.)"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base, get_db
    import app.models.rates  # noqa: F401

    engine = create_engine(f"sqlite:///{tmp_path}/empty.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    from app.main import app

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    try:
        client = TestClient(app)
        r = client.get("/api/rates/health")
        assert r.status_code == 200
        body = r.json()
        assert body["fx"] == {"row_count": 0, "latest_date": None, "age_days": None}
        assert body["robor"] == {"row_count": 0, "latest_date": None, "age_days": None}
        assert body["euribor"] == {"row_count": 0, "latest_date": None, "age_days": None}
    finally:
        app.dependency_overrides.clear()
