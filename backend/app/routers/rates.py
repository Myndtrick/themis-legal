"""Public read API for FX + interest rates.

Auth: either Themis user PKCE bearer or shared RATES_API_TOKEN bearer.
Both gated by the verify_caller dependency.

Also hosts POST /backfill-history — the service-token-triggerable EURIBOR
daily-history ingest (additive INSERT OR IGNORE; see euribor_history.py).
"""
from __future__ import annotations

import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth_service import verify_caller
from app.database import get_db
from app.models.rates import ExchangeRate, InterestRate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rates", tags=["Rates"])


def _age_days(latest_iso: str | None, today: datetime.date) -> int | None:
    if not latest_iso:
        return None
    try:
        return (today - datetime.date.fromisoformat(latest_iso)).days
    except ValueError:
        return None


@router.get("/health")
def rates_health(db: Session = Depends(get_db)) -> dict:
    """Public freshness probe for monitoring (no auth).

    Returns row counts, latest dates, and ages in days for FX, ROBOR, and
    EURIBOR. Exposes only metadata — no rates — so it's safe to leave open.
    Lets dashboards / oncall alert if the AICC scheduler stops firing.
    """
    today = datetime.date.today()

    fx_count, fx_latest = db.query(
        func.count(ExchangeRate.id), func.max(ExchangeRate.date)
    ).first() or (0, None)

    robor_count, robor_latest = db.query(
        func.count(InterestRate.id), func.max(InterestRate.date)
    ).filter(InterestRate.rate_type == "ROBOR").first() or (0, None)

    eur_count, eur_latest = db.query(
        func.count(InterestRate.id), func.max(InterestRate.date)
    ).filter(InterestRate.rate_type == "EURIBOR").first() or (0, None)

    # Per-tenor EURIBOR density. The aggregate count above can look healthy
    # while a tenor's history is monthly-sampled or missing — this breakdown
    # is what makes that visible (the 2026-07 EURIBOR-1M gap would have been
    # caught on day one with it).
    euribor_tenors: dict[str, dict] = {}
    for tenor, count, latest in (
        db.query(
            InterestRate.tenor, func.count(InterestRate.id), func.max(InterestRate.date)
        )
        .filter(InterestRate.rate_type == "EURIBOR")
        .group_by(InterestRate.tenor)
        .all()
    ):
        euribor_tenors[tenor] = {
            "row_count": count or 0,
            "latest_date": latest,
            "age_days": _age_days(latest, today),
        }

    return {
        "fx": {
            "row_count": fx_count or 0,
            "latest_date": fx_latest,
            "age_days": _age_days(fx_latest, today),
        },
        "robor": {
            "row_count": robor_count or 0,
            "latest_date": robor_latest,
            "age_days": _age_days(robor_latest, today),
        },
        "euribor": {
            "row_count": eur_count or 0,
            "latest_date": eur_latest,
            "age_days": _age_days(eur_latest, today),
        },
        "euribor_tenors": euribor_tenors,
    }


@router.get("/exchange")
def list_exchange_rates(
    currency: str | None = Query(None, description="Filter by currency, e.g. 'EUR'"),
    from_: str | None = Query(None, alias="from", description="ISO date >= filter"),
    to: str | None = Query(None, description="ISO date <= filter"),
    limit: int = Query(30, ge=1, le=10000),
    db: Session = Depends(get_db),
    _caller: dict = Depends(verify_caller),
) -> list[dict]:
    q = db.query(ExchangeRate)
    if currency:
        q = q.filter(ExchangeRate.currency == currency.upper())
    if from_:
        q = q.filter(ExchangeRate.date >= from_)
    if to:
        q = q.filter(ExchangeRate.date <= to)
    rows = (
        q.order_by(ExchangeRate.date.desc(), ExchangeRate.currency.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            "date": r.date,
            "currency": r.currency,
            "rate": r.rate,
            "multiplier": r.multiplier,
            "source": r.source,
        }
        for r in rows
    ]


@router.get("/interest")
def list_interest_rates(
    rate_type: str | None = Query(None, description="Filter by rate_type, e.g. 'ROBOR'"),
    tenor: str | None = Query(None, description="Filter by tenor, e.g. '3M'"),
    from_: str | None = Query(None, alias="from", description="ISO date >= filter"),
    to: str | None = Query(None, description="ISO date <= filter"),
    limit: int = Query(30, ge=1, le=10000),
    db: Session = Depends(get_db),
    _caller: dict = Depends(verify_caller),
) -> list[dict]:
    q = db.query(InterestRate)
    if rate_type:
        q = q.filter(InterestRate.rate_type == rate_type.upper())
    if tenor:
        q = q.filter(InterestRate.tenor == tenor.upper())
    if from_:
        q = q.filter(InterestRate.date >= from_)
    if to:
        q = q.filter(InterestRate.date <= to)
    rows = (
        q.order_by(
            InterestRate.date.desc(),
            InterestRate.rate_type.asc(),
            InterestRate.tenor.asc(),
        )
        .limit(limit)
        .all()
    )
    return [
        {
            "date": r.date,
            "rate_type": r.rate_type,
            "tenor": r.tenor,
            "rate": r.rate,
            "source": r.source,
        }
        for r in rows
    ]


@router.post("/backfill-history")
def backfill_euribor_history(
    start_year: int = Query(
        1999, ge=1999, description="Earliest year to backfill (EURIBOR exists since 1999)"
    ),
    db: Session = Depends(get_db),
    caller: dict = Depends(verify_caller),
) -> dict:
    """One-shot EURIBOR DAILY-history backfill (all tenors, additive).

    SERVICE-TOKEN ONLY: the rates-feed spec (Q1) designates the shared
    RATES_API_TOKEN bearer as the service-to-service adapter; regular user
    PKCE tokens are rejected (403) — humans trigger backfills through the
    admin path (/api/admin/rates/backfill). The operation is strictly
    additive (INSERT OR IGNORE on (date, rate_type, tenor)) and idempotent.
    Runs synchronously (~30 upstream calls, ~1 min) and returns the per-tenor
    summary — including fetch failures and per-tenor sparse warnings — so the
    caller can verify coverage, not just row counts.
    """
    from app.services.rates.euribor_history import (
        run_euribor_history_backfill,
        release_history_backfill_lock,
        try_acquire_history_backfill_lock,
    )
    from app.services.scheduler_log_service import record_run

    if caller.get("kind") != "service":
        raise HTTPException(
            status_code=403,
            detail="backfill-history requires the service token (RATES_API_TOKEN)",
        )

    today_year = datetime.date.today().year
    if start_year > today_year:
        raise HTTPException(status_code=400, detail="start_year must not be in the future")

    if not try_acquire_history_backfill_lock():
        raise HTTPException(
            status_code=409, detail="a EURIBOR history backfill is already running"
        )
    try:
        summary = run_euribor_history_backfill(db, start_year=start_year)
    finally:
        release_history_backfill_lock()

    # Ops visibility in the admin scheduler log (best-effort, never raises).
    # Logged under the existing "rates" scheduler id (scheduler_id is
    # String(8)); trigger="manual" distinguishes it from the daily cron runs
    # and summary_json carries the full backfill detail.
    record_run(db, "rates", summary, "manual")
    logger.info(
        "[rates] EURIBOR history backfill: %d fetched, %d inserted, %d errors",
        summary.get("fetched_rows", 0),
        summary.get("inserted_rows", 0),
        summary.get("errors", 0),
    )
    return summary
