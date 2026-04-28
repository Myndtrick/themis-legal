"""Models for the rates feed (FX + interest rates)."""
from __future__ import annotations

import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExchangeRate(Base):
    """One row per (date, currency, source) — typically BNR daily fixings.

    Schema mirrors exodus-live so Exodus can swap source URL with no other
    changes.
    """
    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("date", "currency", "source", name="ux_exchange_rates_dcs"),
        Index("idx_exchange_rates_date", "date"),
        Index("idx_exchange_rates_currency", "currency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    rate: Mapped[float] = mapped_column(Float, nullable=False)
    multiplier: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="BNR")
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )


class InterestRate(Base):
    """One row per (date, rate_type, tenor). rate_type ∈ {ROBOR, EURIBOR}."""
    __tablename__ = "interest_rates"
    __table_args__ = (
        UniqueConstraint("date", "rate_type", "tenor", name="ux_interest_rates_drt"),
        Index("idx_interest_rates_date", "date"),
        Index("idx_interest_rates_type", "rate_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    rate_type: Mapped[str] = mapped_column(String(16), nullable=False)
    tenor: Mapped[str] = mapped_column(String(8), nullable=False)
    rate: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )
