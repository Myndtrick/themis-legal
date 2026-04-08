"""Append-only log of per-law update checks."""

import datetime
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LawCheckLog(Base):
    """One row per call to POST /api/laws/{law_id}/check-updates.

    Written by law_check_log_service.record_check.
    Read by GET /api/admin/law-check-logs and GET /api/laws/{law_id}/check-logs.
    """

    __tablename__ = "law_check_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    law_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("laws.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(8), nullable=False)  # "ro" | "eu"
    checked_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    new_versions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # "ok" | "error"
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        Index("ix_law_check_logs_law_checked", "law_id", "checked_at"),
    )
