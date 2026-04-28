"""Public read API for FX + interest rates.

Auth: either Themis user PKCE bearer or shared RATES_API_TOKEN bearer.
Both gated by the verify_caller dependency.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth_service import verify_caller
from app.database import get_db
from app.models.rates import ExchangeRate, InterestRate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rates", tags=["Rates"])


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
