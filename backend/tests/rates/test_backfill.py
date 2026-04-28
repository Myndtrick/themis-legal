"""Backfill orchestration: iterates years, calls per-year fetchers, stores."""
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
    monkeypatch.setattr("app.database.SessionLocal", Session)
    s = Session()
    yield s
    s.close()


def test_backfill_iterates_years_and_aggregates_counts(db):
    from app.services.rates.backfill import run_rates_backfill
    from app.services.rates.bnr_fx import ParsedFxRate
    from app.services.rates.robor import ParsedInterestRate

    fx_per_year = {
        2024: [ParsedFxRate(date="2024-01-15", currency="EUR", rate=4.9, multiplier=1)],
        2025: [
            ParsedFxRate(date="2025-01-15", currency="EUR", rate=4.95, multiplier=1),
            ParsedFxRate(date="2025-06-01", currency="USD", rate=4.4, multiplier=1),
        ],
    }
    eur_per_year = {
        2024: [ParsedInterestRate(date="2024-01-15", rate_type="EURIBOR", tenor="3M", rate=3.6)],
        2025: [],
    }

    def fake_fx_year(year, client=None):
        return fx_per_year.get(year, [])

    def fake_eur_year(year, client=None):
        return eur_per_year.get(year, [])

    with patch("app.services.rates.backfill.fetch_bnr_year", side_effect=fake_fx_year), \
         patch("app.services.rates.backfill.fetch_euribor_year", side_effect=fake_eur_year), \
         patch("app.services.rates.backfill.fetch_robor_current", return_value=[]):
        result = run_rates_backfill(years=2, current_year=2025)

    assert result["fx_inserted"] == 3
    assert result["euribor_inserted"] == 1
    # ROBOR backfill uses fetch_robor_current as a placeholder (no per-year URL);
    # acceptable. Test just confirms the call doesn't crash.


def test_backfill_continues_when_year_returns_empty(db):
    from app.services.rates.backfill import run_rates_backfill

    with patch("app.services.rates.backfill.fetch_bnr_year", return_value=[]), \
         patch("app.services.rates.backfill.fetch_euribor_year", return_value=[]), \
         patch("app.services.rates.backfill.fetch_robor_current", return_value=[]):
        result = run_rates_backfill(years=3, current_year=2026)

    assert result["fx_inserted"] == 0
    assert result["euribor_inserted"] == 0
    assert result["years_processed"] == [2024, 2025, 2026]
