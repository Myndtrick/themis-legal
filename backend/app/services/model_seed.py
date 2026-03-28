"""Seed the models and model_assignments tables."""

from sqlalchemy.orm import Session
from app.models.model_config import Model, ModelAssignment

SEED_MODELS = [
    {"id": "claude-haiku-4-5", "provider": "anthropic", "api_model_id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5", "cost_tier": "$", "capabilities": '["chat"]'},
    {"id": "claude-sonnet-4-6", "provider": "anthropic", "api_model_id": "claude-sonnet-4-20250514", "label": "Claude Sonnet 4.6", "cost_tier": "$$", "capabilities": '["chat"]'},
    {"id": "claude-opus-4-6", "provider": "anthropic", "api_model_id": "claude-opus-4-20250514", "label": "Claude Opus 4.6", "cost_tier": "$$$", "capabilities": '["chat"]'},
    {"id": "mistral-small", "provider": "mistral", "api_model_id": "mistral-small-latest", "label": "Mistral Small", "cost_tier": "$", "capabilities": '["chat"]'},
    {"id": "mistral-large", "provider": "mistral", "api_model_id": "mistral-large-latest", "label": "Mistral Large", "cost_tier": "$$", "capabilities": '["chat"]'},
    {"id": "mistral-ocr", "provider": "mistral", "api_model_id": "mistral-ocr-latest", "label": "Mistral OCR", "cost_tier": "$", "capabilities": '["ocr"]'},
    {"id": "gpt-4o", "provider": "openai", "api_model_id": "gpt-4o", "label": "GPT-4o", "cost_tier": "$$", "capabilities": '["chat"]'},
    {"id": "gpt-4o-mini", "provider": "openai", "api_model_id": "gpt-4o-mini", "label": "GPT-4o Mini", "cost_tier": "$", "capabilities": '["chat"]'},
    {"id": "gpt-4.1", "provider": "openai", "api_model_id": "gpt-4.1", "label": "GPT-4.1", "cost_tier": "$$", "capabilities": '["chat"]'},
    {"id": "gpt-4.1-mini", "provider": "openai", "api_model_id": "gpt-4.1-mini", "label": "GPT-4.1 Mini", "cost_tier": "$", "capabilities": '["chat"]'},
    {"id": "gpt-4.1-nano", "provider": "openai", "api_model_id": "gpt-4.1-nano", "label": "GPT-4.1 Nano", "cost_tier": "$", "capabilities": '["chat"]'},
    {"id": "o3", "provider": "openai", "api_model_id": "o3", "label": "o3", "cost_tier": "$$$", "capabilities": '["chat", "reasoning"]'},
    {"id": "o4-mini", "provider": "openai", "api_model_id": "o4-mini", "label": "o4 Mini", "cost_tier": "$$", "capabilities": '["chat", "reasoning"]'},
]

DEFAULT_ASSIGNMENTS = {
    "issue_classification": "claude-haiku-4-5",
    "law_mapping": "claude-haiku-4-5",
    "fast_general": "claude-haiku-4-5",
    "article_selection": "claude-sonnet-4-6",
    "answer_generation": "claude-sonnet-4-6",
    "diff_summary": "claude-sonnet-4-6",
    "ocr": "mistral-ocr",
}


def seed_models(db: Session):
    """Seed models and default assignments. Idempotent."""
    for model_data in SEED_MODELS:
        existing = db.query(Model).filter(Model.id == model_data["id"]).first()
        if not existing:
            db.add(Model(**model_data))

    for task, model_id in DEFAULT_ASSIGNMENTS.items():
        existing = db.query(ModelAssignment).filter(ModelAssignment.task == task).first()
        if not existing:
            db.add(ModelAssignment(task=task, model_id=model_id))

    db.commit()
