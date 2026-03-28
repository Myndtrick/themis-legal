"""Cost calculation for LLM API calls."""

from app.providers.base import TokenUsage

# Prices per 1M tokens (input, output)
TOKEN_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (0.80, 4.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-6": (15.00, 75.00),
    "mistral-small": (0.20, 0.60),
    "mistral-large": (2.00, 6.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "o3": (10.00, 40.00),
    "o4-mini": (1.10, 4.40),
}

# Page-based pricing
PAGE_PRICING: dict[str, float] = {
    "mistral-ocr": 0.002,
}


def calculate_cost(model_id: str, usage: TokenUsage) -> float:
    if model_id in PAGE_PRICING:
        return PAGE_PRICING[model_id] * usage.input_tokens

    if model_id not in TOKEN_PRICING:
        raise ValueError(f"Unknown model for pricing: {model_id}")

    input_rate, output_rate = TOKEN_PRICING[model_id]
    return (usage.input_tokens / 1_000_000) * input_rate + \
           (usage.output_tokens / 1_000_000) * output_rate
