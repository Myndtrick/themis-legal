from pydantic import BaseModel, field_validator


class CompareRequest(BaseModel):
    question: str
    models: list[str]
    mode: str = "full"

    @field_validator("models")
    @classmethod
    def validate_models(cls, v):
        if len(v) == 0:
            raise ValueError("At least one model must be selected")
        if len(v) > 5:
            raise ValueError("Maximum 5 models per comparison")
        return v


class CompareModelResult(BaseModel):
    model_id: str
    model_label: str
    status: str
    duration_ms: int = 0
    usage: dict | None = None
    cost_usd: float = 0.0
    answer: str | None = None
    citations: list | None = None
    pipeline_steps: dict | None = None
    error: str | None = None


class CompareResponse(BaseModel):
    question: str
    results: list[CompareModelResult]
