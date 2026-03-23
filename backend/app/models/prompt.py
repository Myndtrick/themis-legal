import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    created_by: Mapped[str] = mapped_column(String(50), default="system")
    modification_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        UniqueConstraint("prompt_id", "version_number", name="uq_prompt_version"),
    )
