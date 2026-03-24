from __future__ import annotations

import json
import logging
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.pipeline import APICallLog, PipelineRun, StepLog
from app.schemas.pipeline import (
    APICallLogResponse,
    HealthStats,
    PipelineRunDetail,
    PipelineRunSummary,
    StepLogResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings/pipeline", tags=["Settings — Pipeline"])


@router.get("/runs", response_model=list[PipelineRunSummary])
def list_runs(
    module: str | None = None,
    mode: str | None = None,
    status: str | None = None,
    confidence: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List pipeline runs with optional filters."""
    query = db.query(PipelineRun).order_by(PipelineRun.started_at.desc())

    if module:
        query = query.filter(PipelineRun.module == module)
    if mode:
        query = query.filter(PipelineRun.mode == mode)
    if status:
        query = query.filter(PipelineRun.overall_status == status)
    if confidence:
        query = query.filter(PipelineRun.overall_confidence == confidence)

    runs = query.offset(offset).limit(limit).all()

    return [
        PipelineRunSummary(
            run_id=r.run_id,
            module=r.module,
            mode=r.mode,
            question_summary=r.question_summary,
            started_at=r.started_at.isoformat(),
            completed_at=r.completed_at.isoformat() if r.completed_at else None,
            overall_status=r.overall_status,
            overall_confidence=r.overall_confidence,
            total_duration_seconds=r.total_duration_seconds,
            estimated_cost=r.estimated_cost,
        )
        for r in runs
    ]


@router.get("/runs/{run_id}", response_model=PipelineRunDetail)
def get_run_detail(run_id: str, db: Session = Depends(get_db)):
    """Get full detail of a pipeline run including all steps and API calls."""
    run = db.query(PipelineRun).filter(PipelineRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    steps = (
        db.query(StepLog)
        .filter(StepLog.run_id == run_id)
        .order_by(StepLog.step_number)
        .all()
    )
    api_calls = (
        db.query(APICallLog)
        .filter(APICallLog.run_id == run_id)
        .all()
    )

    return PipelineRunDetail(
        run_id=run.run_id,
        module=run.module,
        mode=run.mode,
        question_summary=run.question_summary,
        started_at=run.started_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        overall_status=run.overall_status,
        overall_confidence=run.overall_confidence,
        total_duration_seconds=run.total_duration_seconds,
        estimated_cost=run.estimated_cost,
        flags=run.flags,
        steps=[
            StepLogResponse(
                step_name=s.step_name,
                step_number=s.step_number,
                status=s.status,
                duration_seconds=s.duration_seconds,
                prompt_id=s.prompt_id,
                prompt_version=s.prompt_version,
                input_summary=s.input_summary,
                output_summary=s.output_summary,
                output_data=json.loads(s.output_data) if s.output_data else None,
                confidence=s.confidence,
                warnings=s.warnings,
            )
            for s in steps
        ],
        api_calls=[
            APICallLogResponse(
                step_name=c.step_name,
                tokens_in=c.tokens_in,
                tokens_out=c.tokens_out,
                duration_seconds=c.duration_seconds,
                model=c.model,
            )
            for c in api_calls
        ],
    )


@router.get("/health", response_model=HealthStats)
def get_health_stats(db: Session = Depends(get_db)):
    """Get system health dashboard data."""
    runs = db.query(PipelineRun).filter(PipelineRun.overall_status != "running").all()

    total = len(runs)
    if total == 0:
        return HealthStats(
            total_runs=0,
            ok_count=0,
            warning_count=0,
            error_count=0,
            partial_count=0,
            ok_pct=0,
            warning_pct=0,
            error_pct=0,
            avg_confidence_high_pct=0,
            avg_duration_seconds=0,
            avg_cost=0,
            most_common_warnings=[],
        )

    status_counts = Counter(r.overall_status for r in runs)
    ok = status_counts.get("ok", 0)
    warning = status_counts.get("warning", 0)
    error = status_counts.get("error", 0)
    partial = status_counts.get("partial", 0)

    high_confidence = sum(1 for r in runs if r.overall_confidence == "HIGH")

    durations = [r.total_duration_seconds for r in runs if r.total_duration_seconds]
    costs = [r.estimated_cost for r in runs if r.estimated_cost]

    # Collect warnings from flags
    all_warnings = []
    for r in runs:
        if r.flags:
            try:
                flags = json.loads(r.flags)
                all_warnings.extend(flags)
            except (json.JSONDecodeError, TypeError):
                pass

    warning_counts = Counter(all_warnings)
    most_common = [w for w, _ in warning_counts.most_common(5)]

    return HealthStats(
        total_runs=total,
        ok_count=ok,
        warning_count=warning,
        error_count=error,
        partial_count=partial,
        ok_pct=round(ok / total * 100, 1) if total else 0,
        warning_pct=round(warning / total * 100, 1) if total else 0,
        error_pct=round(error / total * 100, 1) if total else 0,
        avg_confidence_high_pct=round(high_confidence / total * 100, 1) if total else 0,
        avg_duration_seconds=round(sum(durations) / len(durations), 1) if durations else 0,
        avg_cost=round(sum(costs) / len(costs), 4) if costs else 0,
        most_common_warnings=most_common,
    )
