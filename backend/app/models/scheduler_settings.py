"""SQLAlchemy model for scheduler configuration (persists across restarts)."""

import datetime
from sqlalchemy import Boolean, DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SchedulerSetting(Base):
    __tablename__ = "scheduler_settings"

    id: Mapped[str] = mapped_column(String(10), primary_key=True)  # "ro" or "eu"
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)  # daily, every_3_days, weekly, monthly
    time_hour: Mapped[int] = mapped_column(Integer, default=3)
    time_minute: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    last_run_status: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    last_run_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
