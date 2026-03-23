from __future__ import annotations

from pydantic import BaseModel


class PipelineRunSummary(BaseModel):
    run_id: str
    module: str
    mode: str | None = None
    question_summary: str | None = None
    started_at: str
    completed_at: str | None = None
    overall_status: str
    overall_confidence: str | None = None
    total_duration_seconds: float | None = None
    estimated_cost: float | None = None


class StepLogResponse(BaseModel):
    step_name: str
    step_number: int
    status: str
    duration_seconds: float | None = None
    prompt_id: str | None = None
    prompt_version: int | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    confidence: str | None = None
    warnings: str | None = None  # JSON string


class APICallLogResponse(BaseModel):
    step_name: str
    tokens_in: int
    tokens_out: int
    duration_seconds: float
    model: str


class PipelineRunDetail(BaseModel):
    run_id: str
    module: str
    mode: str | None = None
    question_summary: str | None = None
    started_at: str
    completed_at: str | None = None
    overall_status: str
    overall_confidence: str | None = None
    total_duration_seconds: float | None = None
    estimated_cost: float | None = None
    flags: str | None = None  # JSON string
    steps: list[StepLogResponse]
    api_calls: list[APICallLogResponse]


class HealthStats(BaseModel):
    total_runs: int
    ok_count: int
    warning_count: int
    error_count: int
    partial_count: int
    ok_pct: float
    warning_pct: float
    error_pct: float
    avg_confidence_high_pct: float
    avg_duration_seconds: float
    avg_cost: float
    most_common_warnings: list[str]
