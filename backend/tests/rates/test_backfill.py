"""Backfill orchestration: EURIBOR daily history first, then per-year loop.

The dense DAILY EURIBOR series comes from the chart JSON API
(fetch_euribor_history); the per-year archive pages (monthly-sampled — first
business day of each month only) are fetched ONLY as fallback when the dense
source fails or returns nothing.
"""
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


def _hist(rows=None, failures=None, sparse=None):
    from app.services.rates.euribor_history import EuriborHistoryFetchResult

    return EuriborHistoryFetchResult(
        rows=rows or [], failures=failures or [], sparse_warnings=sparse or []
    )


def test_backfill_iterates_years_and_aggregates_counts(db):
    """Fallback path: dense history empty → per-year pages are used."""
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
         patch("app.services.rates.backfill.fetch_euribor_history", return_value=_hist()), \
         patch("app.services.rates.backfill.fetch_robor_current", return_value=[]):
        result = run_rates_backfill(years=2, current_year=2025)

    assert result["fx_inserted"] == 3
    assert result["euribor_inserted"] == 1
    assert result["euribor_history_inserted"] == 0
    # ROBOR backfill uses fetch_robor_current as a placeholder (no per-year URL);
    # acceptable. Test just confirms the call doesn't crash.


def test_backfill_continues_when_year_returns_empty(db):
    from app.services.rates.backfill import run_rates_backfill

    with patch("app.services.rates.backfill.fetch_bnr_year", return_value=[]), \
         patch("app.services.rates.backfill.fetch_euribor_year", return_value=[]), \
         patch("app.services.rates.backfill.fetch_euribor_history", return_value=_hist()), \
         patch("app.services.rates.backfill.fetch_robor_current", return_value=[]):
        result = run_rates_backfill(years=3, current_year=2026)

    assert result["fx_inserted"] == 0
    assert result["euribor_inserted"] == 0
    assert result["euribor_history_inserted"] == 0
    assert result["years_processed"] == [2024, 2025, 2026]


def test_backfill_dense_history_wins_and_skips_year_pages(db):
    """When the chart API delivers a CLEAN daily fetch, the monthly-sampled
    per-year EURIBOR pages must NOT be fetched at all (strict subset)."""
    from app.services.rates.backfill import run_rates_backfill
    from app.services.rates.robor import ParsedInterestRate

    rows = [
        ParsedInterestRate(date="2025-01-02", rate_type="EURIBOR", tenor="1M", rate=2.85),
        ParsedInterestRate(date="2025-01-03", rate_type="EURIBOR", tenor="1M", rate=2.86),
        ParsedInterestRate(date="2025-01-02", rate_type="EURIBOR", tenor="3M", rate=2.71),
    ]

    with patch("app.services.rates.backfill.fetch_bnr_year", return_value=[]), \
         patch("app.services.rates.backfill.fetch_euribor_year") as year_pages, \
         patch("app.services.rates.backfill.fetch_euribor_history",
               return_value=_hist(rows=rows)) as dense, \
         patch("app.services.rates.backfill.fetch_robor_current", return_value=[]):
        result = run_rates_backfill(years=2, current_year=2025)

    assert result["euribor_history_inserted"] == 3
    assert result["euribor_inserted"] == 0
    assert result["errors"] == 0
    year_pages.assert_not_called()
    # Dense fetch is scoped to the backfill window's start year.
    dense.assert_called_once_with(start_year=2024)


def test_backfill_partial_history_stores_rows_but_still_runs_fallback(db):
    """Codex P1: a PARTIAL dense fetch (some window×batch requests failed)
    must store what it got, REPORT the failures, and still run the per-year
    fallback — never present as a clean success."""
    from app.services.rates.backfill import run_rates_backfill
    from app.services.rates.robor import ParsedInterestRate

    partial = _hist(
        rows=[ParsedInterestRate(date="2025-01-02", rate_type="EURIBOR", tenor="1M", rate=2.85)],
        failures=["2015-01-01..2016-12-31 series (1, 2, 3): HTTP 500"],
    )
    eur_2025 = [ParsedInterestRate(date="2025-02-03", rate_type="EURIBOR", tenor="3M", rate=2.7)]

    with patch("app.services.rates.backfill.fetch_bnr_year", return_value=[]), \
         patch("app.services.rates.backfill.fetch_euribor_year",
               return_value=eur_2025) as year_pages, \
         patch("app.services.rates.backfill.fetch_euribor_history", return_value=partial), \
         patch("app.services.rates.backfill.fetch_robor_current", return_value=[]):
        result = run_rates_backfill(years=1, current_year=2025)

    assert result["euribor_history_inserted"] == 1   # partial rows kept
    assert result["errors"] == 1                     # failure visible
    assert any("HTTP 500" in m for m in result["error_messages"])
    year_pages.assert_called()                       # fallback engaged
    assert result["euribor_inserted"] == 1


def test_backfill_falls_back_to_year_pages_when_history_raises(db):
    from app.services.rates.backfill import run_rates_backfill
    from app.services.rates.robor import ParsedInterestRate

    def boom(**kwargs):
        raise RuntimeError("chart API down")

    eur_2025 = [ParsedInterestRate(date="2025-02-03", rate_type="EURIBOR", tenor="1M", rate=2.8)]

    with patch("app.services.rates.backfill.fetch_bnr_year", return_value=[]), \
         patch("app.services.rates.backfill.fetch_euribor_year", return_value=eur_2025), \
         patch("app.services.rates.backfill.fetch_euribor_history", side_effect=boom), \
         patch("app.services.rates.backfill.fetch_robor_current", return_value=[]):
        result = run_rates_backfill(years=1, current_year=2025)

    assert result["errors"] == 1
    assert any("euribor_history" in m for m in result["error_messages"])
    # Fallback stored the (monthly-sampled) year-page rows.
    assert result["euribor_inserted"] == 1
