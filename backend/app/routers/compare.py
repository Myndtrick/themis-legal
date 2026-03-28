"""Model comparison endpoint — runs the same question against multiple models."""

import asyncio
import logging
import time
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.auth import get_current_user
from app.database import get_db
from app.schemas.compare import CompareRequest, CompareResponse, CompareModelResult
from app.providers import get_provider
from app.services.pricing import calculate_cost
from app.providers.base import TokenUsage
from app.services.model_seed import SEED_MODELS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/assistant", tags=["assistant"], dependencies=[Depends(get_current_user)])

_MODEL_LABELS = {m["id"]: m["label"] for m in SEED_MODELS}


def run_pipeline_for_model(question: str, model_id: str, mode: str, db: Session) -> dict:
    """Run the pipeline with a specific model. Placeholder for now."""
    provider = get_provider(model_id)
    response = provider.chat(
        messages=[{"role": "user", "content": question}],
        system="You are a Romanian legal assistant. Answer the question based on Romanian law.",
    )
    return {
        "answer": response.content,
        "citations": [],
        "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
        "pipeline_steps": {},
    }


@router.post("/compare", response_model=CompareResponse)
async def compare_models(req: CompareRequest, db: Session = Depends(get_db)):
    async def run_one(model_id: str) -> CompareModelResult:
        label = _MODEL_LABELS.get(model_id, model_id)
        start = time.monotonic()
        try:
            result = await asyncio.to_thread(
                run_pipeline_for_model, req.question, model_id, req.mode, db
            )
            duration = int((time.monotonic() - start) * 1000)
            usage = result.get("usage", {})
            token_usage = TokenUsage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )
            return CompareModelResult(
                model_id=model_id,
                model_label=label,
                status="success",
                duration_ms=duration,
                usage=usage,
                cost_usd=calculate_cost(model_id, token_usage),
                answer=result.get("answer"),
                citations=result.get("citations"),
                pipeline_steps=result.get("pipeline_steps") if req.mode == "pipeline_steps" else None,
            )
        except Exception as e:
            duration = int((time.monotonic() - start) * 1000)
            logger.error("[compare] run_pipeline_for_model failed for %s: %s", model_id, e)
            return CompareModelResult(
                model_id=model_id,
                model_label=label,
                status="error",
                duration_ms=duration,
                error=str(e),
            )

    results = await asyncio.gather(*(run_one(m) for m in req.models))
    return CompareResponse(question=req.question, results=list(results))
