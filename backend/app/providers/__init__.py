"""Provider factory — get_provider(model_id) returns the right LLMProvider."""

import json
from app.providers.base import LLMProvider, LLMResponse, TokenUsage
from app.services.model_seed import SEED_MODELS

_MODEL_LOOKUP = {m["id"]: m for m in SEED_MODELS}


def get_provider(model_id: str) -> LLMProvider:
    model = _MODEL_LOOKUP.get(model_id)
    if not model:
        raise ValueError(f"Unknown model: {model_id}")

    provider = model["provider"]
    api_model_id = model["api_model_id"]

    # capabilities may be stored as a JSON string or a list
    capabilities = model["capabilities"]
    if isinstance(capabilities, str):
        capabilities = json.loads(capabilities)

    if provider == "anthropic":
        from app.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model_id, api_model_id)
    elif provider == "mistral":
        from app.providers.mistral_provider import MistralProvider
        supports_ocr = "ocr" in capabilities
        return MistralProvider(model_id, api_model_id, supports_ocr=supports_ocr)
    elif provider == "openai":
        from app.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(model_id, api_model_id)
    else:
        raise ValueError(f"Unknown provider: {provider}")
