import pytest
from unittest.mock import patch, MagicMock
from app.providers import get_provider
from app.providers.base import LLMProvider, LLMResponse, TokenUsage


def test_get_provider_returns_anthropic_for_claude():
    from app.providers.anthropic_provider import AnthropicProvider
    provider = get_provider("claude-sonnet-4-6")
    assert isinstance(provider, AnthropicProvider)


def test_get_provider_returns_mistral_for_mistral():
    from app.providers.mistral_provider import MistralProvider
    provider = get_provider("mistral-large")
    assert isinstance(provider, MistralProvider)


def test_get_provider_returns_openai_for_gpt():
    from app.providers.openai_provider import OpenAIProvider
    provider = get_provider("gpt-4.1")
    assert isinstance(provider, OpenAIProvider)


def test_get_provider_unknown_model():
    with pytest.raises(ValueError, match="Unknown model"):
        get_provider("unknown-model-xyz")


def test_provider_interface():
    for model_id in ["claude-sonnet-4-6", "mistral-large", "gpt-4.1"]:
        provider = get_provider(model_id)
        assert hasattr(provider, "chat")
        assert hasattr(provider, "stream")
        assert hasattr(provider, "ocr")


def test_non_ocr_model_raises_on_ocr():
    provider = get_provider("claude-sonnet-4-6")
    with pytest.raises(NotImplementedError):
        provider.ocr(b"fake", "application/pdf")


def test_anthropic_chat_calls_api():
    provider = get_provider("claude-sonnet-4-6")
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Hello"))]
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 5

    with patch.object(provider, "_client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_response
        result = provider.chat(
            messages=[{"role": "user", "content": "Hi"}],
            system="You are helpful",
        )
        assert isinstance(result, LLMResponse)
        assert result.content == "Hello"
        assert result.usage.input_tokens == 10
        sent_messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        assert sent_messages[0] == {"role": "system", "content": "You are helpful"}
