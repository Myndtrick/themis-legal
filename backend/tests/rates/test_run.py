"""Orchestrator that calls all three fetchers and stores results."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    import app.models.rates  # noqa: F401
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    # Patch SessionLocal so run_rates_update_check uses our test session
    monkeypatch.setattr("app.database.SessionLocal", Session)
    s = Session()
    yield s
    s.close()


def test_run_calls_all_three_fetchers_and_stores(db):
    from app.services.rates.bnr_fx import ParsedFxRate
    from app.services.rates.robor import ParsedInterestRate
    from app.services.rates.run import run_rates_update_check

    fake_fx = [ParsedFxRate(date="2026-03-06", currency="EUR", rate=4.97, multiplier=1)]
    fake_robor = [ParsedInterestRate(date="2026-03-06", rate_type="ROBOR", tenor="3M", rate=5.92)]
    fake_eur = [ParsedInterestRate(date="2026-03-06", rate_type="EURIBOR", tenor="3M", rate=2.68)]

    with patch("app.services.rates.run.fetch_bnr_daily", return_value=fake_fx), \
         patch("app.services.rates.run.fetch_robor_current", return_value=fake_robor), \
         patch("app.services.rates.run.fetch_euribor_current", return_value=fake_eur):
        result = run_rates_update_check()

    assert result["fx_inserted"] == 1
    assert result["robor_inserted"] == 1
    assert result["euribor_inserted"] == 1
    assert result["errors"] == 0


def test_run_continues_when_one_fetcher_returns_empty(db):
    from app.services.rates.run import run_rates_update_check

    with patch("app.services.rates.run.fetch_bnr_daily", return_value=[]), \
         patch("app.services.rates.run.fetch_robor_current", return_value=[]), \
         patch("app.services.rates.run.fetch_euribor_current", return_value=[]):
        result = run_rates_update_check()

    assert result["fx_inserted"] == 0
    assert result["robor_inserted"] == 0
    assert result["euribor_inserted"] == 0
    # Empty isn't an error per se — could be a holiday
    assert result["errors"] == 0


def test_run_records_error_when_fetcher_raises(db):
    from app.services.rates.run import run_rates_update_check

    def boom(*a, **k):
        raise RuntimeError("BNR is down")

    with patch("app.services.rates.run.fetch_bnr_daily", side_effect=boom), \
         patch("app.services.rates.run.fetch_robor_current", return_value=[]), \
         patch("app.services.rates.run.fetch_euribor_current", return_value=[]):
        result = run_rates_update_check()

    assert result["errors"] == 1
    # Other fetchers still ran
    assert result["robor_inserted"] == 0
