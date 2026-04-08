"""Append-only log of scheduler runs (RO + EU version discovery)."""

import datetime
from sqlalchemy import DateTime, Integer, JSON, String, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SchedulerRunLog(Base):
    """One row per scheduler run, written by scheduler_log_service.record_run."""

    __tablename__ = "scheduler_run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scheduler_id: Mapped[str] = mapped_column(String(8), nullable=False, index=True)  # "ro" | "eu"
    ran_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)  # "scheduled" | "manual"
    status: Mapped[str] = mapped_column(String(16), nullable=False)   # "ok" | "error"
    laws_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_versions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)

    __table_args__ = (
        Index("ix_scheduler_run_logs_sched_ran", "scheduler_id", "ran_at"),
    )
