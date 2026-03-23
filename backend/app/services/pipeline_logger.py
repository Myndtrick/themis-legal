from __future__ import annotations

import datetime
import json
import uuid

from sqlalchemy.orm import Session

from app.models.pipeline import APICallLog, PipelineRun, StepLog


def create_run(db: Session, question_summary: str) -> str:
    """Create a new pipeline run. Returns run_id."""
    run_id = uuid.uuid4().hex[:12]
    run = PipelineRun(
        run_id=run_id,
        question_summary=question_summary[:500],
    )
    db.add(run)
    db.flush()
    return run_id


def log_step(
    db: Session,
    run_id: str,
    step_name: str,
    step_number: int,
    status: str,
    duration: float,
    prompt_id: str | None = None,
    prompt_version: int | None = None,
    input_summary: str | None = None,
    output_summary: str | None = None,
    output_data: dict | None = None,
    confidence: str | None = None,
    warnings: list[str] | None = None,
):
    """Log a single pipeline step execution."""
    step = StepLog(
        run_id=run_id,
        step_name=step_name,
        step_number=step_number,
        status=status,
        duration_seconds=duration,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        input_summary=(input_summary or "")[:1000],
        output_summary=(output_summary or "")[:1000],
        output_data=json.dumps(output_data, ensure_ascii=False) if output_data else None,
        confidence=confidence,
        warnings=json.dumps(warnings, ensure_ascii=False) if warnings else None,
    )
    db.add(step)
    db.flush()


def log_api_call(
    db: Session,
    run_id: str,
    step_name: str,
    tokens_in: int,
    tokens_out: int,
    duration: float,
    model: str,
):
    """Log a single Claude API call."""
    call = APICallLog(
        run_id=run_id,
        step_name=step_name,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duration_seconds=duration,
        model=model,
    )
    db.add(call)
    db.flush()


def update_run_mode(db: Session, run_id: str, mode: str):
    """Update the mode of a pipeline run after classification."""
    run = db.query(PipelineRun).filter(PipelineRun.run_id == run_id).first()
    if run:
        run.mode = mode
        db.flush()


def save_paused_state(db: Session, run_id: str, state_data: dict):
    """Save pipeline state when pausing for user input."""
    run = db.query(PipelineRun).filter(PipelineRun.run_id == run_id).first()
    if run:
        run.overall_status = "paused"
        # Serialize state, excluding non-serializable objects
        serializable = {
            k: v for k, v in state_data.items()
            if k not in ("db",)
        }
        run.paused_state = json.dumps(serializable, ensure_ascii=False, default=str)
        db.flush()


def load_paused_state(db: Session, run_id: str) -> dict | None:
    """Load a previously paused pipeline state."""
    run = db.query(PipelineRun).filter(PipelineRun.run_id == run_id).first()
    if run and run.paused_state:
        return json.loads(run.paused_state)
    return None


def complete_run(
    db: Session,
    run_id: str,
    status: str,
    confidence: str | None,
    flags: list[str] | None,
):
    """Mark a pipeline run as complete and calculate cost."""
    run = db.query(PipelineRun).filter(PipelineRun.run_id == run_id).first()
    if not run:
        return

    run.completed_at = datetime.datetime.utcnow()
    run.overall_status = status
    run.overall_confidence = confidence
    run.flags = json.dumps(flags, ensure_ascii=False) if flags else None
    run.total_duration_seconds = (
        run.completed_at - run.started_at
    ).total_seconds()

    # Calculate cost estimate (Claude Sonnet 4 pricing: $3/MTok in, $15/MTok out)
    api_calls = db.query(APICallLog).filter(APICallLog.run_id == run_id).all()
    total_in = sum(c.tokens_in for c in api_calls)
    total_out = sum(c.tokens_out for c in api_calls)
    run.estimated_cost = (total_in * 3.0 / 1_000_000) + (total_out * 15.0 / 1_000_000)

    db.flush()
