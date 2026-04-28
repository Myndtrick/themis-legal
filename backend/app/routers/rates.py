"""Public read API for FX + interest rates.

Auth: either Themis user PKCE bearer or shared RATES_API_TOKEN bearer.
Both gated by the verify_caller dependency.
"""
from __future__ import annotations

import datetime
import logging

from fastapi import APIRouter, Depends, Query
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
