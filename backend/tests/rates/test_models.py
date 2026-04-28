"""Schema sanity tests for ExchangeRate and InterestRate models."""
from __future__ import annotations

import pytest


@pytest.fixture
def db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    # Importing the models module registers the tables on Base.metadata
    import app.models.rates  # noqa: F401
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    s = Session()
    yield s
    s.close()


def test_exchange_rate_round_trip(db):
    from app.models.rates import ExchangeRate
    db.add(ExchangeRate(date="2026-03-06", currency="EUR", rate=4.9741, multiplier=1, source="BNR"))
    db.commit()
    rows = db.query(ExchangeRate).all()
    assert len(rows) == 1
    assert rows[0].currency == "EUR"
    assert rows[0].rate == 4.9741


def test_exchange_rate_unique_constraint(db):
    from app.models.rates import ExchangeRate
    from sqlalchemy.exc import IntegrityError
    db.add(ExchangeRate(date="2026-03-06", currency="EUR", rate=4.9741, source="BNR"))
    db.commit()
    db.add(ExchangeRate(date="2026-03-06", currency="EUR", rate=4.9999, source="BNR"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_interest_rate_round_trip(db):
    from app.models.rates import InterestRate
    db.add(InterestRate(date="2026-03-06", rate_type="ROBOR", tenor="3M", rate=5.92, source="curs-valutar-bnr.ro"))
    db.commit()
    rows = db.query(InterestRate).all()
    assert len(rows) == 1
    assert rows[0].rate_type == "ROBOR"
    assert rows[0].tenor == "3M"


def test_interest_rate_unique_constraint(db):
    from app.models.rates import InterestRate
    from sqlalchemy.exc import IntegrityError
    db.add(InterestRate(date="2026-03-06", rate_type="ROBOR", tenor="3M", rate=5.92, source="x"))
    db.commit()
    db.add(InterestRate(date="2026-03-06", rate_type="ROBOR", tenor="3M", rate=6.10, source="x"))
    with pytest.raises(IntegrityError):
        db.commit()
