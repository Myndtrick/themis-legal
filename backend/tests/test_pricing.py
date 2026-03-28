import pytest
from app.services.pricing import calculate_cost
from app.providers.base import TokenUsage


def test_anthropic_sonnet_cost():
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    cost = calculate_cost("claude-sonnet-4-6", usage)
    assert cost > 0
    assert isinstance(cost, float)


def test_openai_gpt4o_cost():
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    cost = calculate_cost("gpt-4o", usage)
    assert cost > 0


def test_mistral_ocr_page_cost():
    usage = TokenUsage(input_tokens=10, output_tokens=0)
    cost = calculate_cost("mistral-ocr", usage)
    assert cost == pytest.approx(0.02, abs=0.001)


def test_zero_usage():
    usage = TokenUsage(input_tokens=0, output_tokens=0)
    cost = calculate_cost("claude-sonnet-4-6", usage)
    assert cost == 0.0


def test_unknown_model():
    usage = TokenUsage(input_tokens=100, output_tokens=100)
    with pytest.raises(ValueError):
        calculate_cost("unknown-model", usage)
