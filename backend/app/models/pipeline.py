import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    module: Mapped[str] = mapped_column(String(50), default="legal_assistant")
    mode: Mapped[str | None] = mapped_column(String(30), nullable=True)
    question_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    overall_status: Mapped[str] = mapped_column(String(20), default="running")
    overall_confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    total_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    flags: Mapped[str | None] = mapped_column(Text, nullable=True)
    paused_state: Mapped[str | None] = mapped_column(Text, nullable=True)

    steps: Mapped[list["StepLog"]] = relationship(
        back_populates="pipeline_run", cascade="all, delete-orphan"
    )
    api_calls: Mapped[list["APICallLog"]] = relationship(
        back_populates="pipeline_run", cascade="all, delete-orphan"
    )


class StepLog(Base):
    __tablename__ = "step_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("pipeline_runs.run_id"), nullable=False
    )
    step_name: Mapped[str] = mapped_column(String(50), nullable=False)
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    warnings: Mapped[str | None] = mapped_column(Text, nullable=True)

    pipeline_run: Mapped["PipelineRun"] = relationship(back_populates="steps")


class APICallLog(Base):
    __tablename__ = "api_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("pipeline_runs.run_id"), nullable=False
    )
    step_name: Mapped[str] = mapped_column(String(50), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    model: Mapped[str] = mapped_column(String(50), nullable=False)

    pipeline_run: Mapped["PipelineRun"] = relationship(back_populates="api_calls")
