"""Anthropic (Claude) provider."""

import os
import anthropic
from typing import Iterator
from app.providers.base import LLMProvider, LLMResponse, TokenUsage


class AnthropicProvider(LLMProvider):
    def __init__(self, model_id: str, api_model_id: str):
        self.model_id = model_id
        self.api_model_id = api_model_id
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = anthropic.Anthropic(api_key=api_key)

    def chat(self, messages, system=None, max_tokens=4096, temperature=0.0):
        kwargs = {
            "model": self.api_model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            kwargs["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        response = self._client.messages.create(**kwargs)
        content = response.content[0].text if response.content else ""
        return LLMResponse(
            content=content,
            usage=TokenUsage(response.usage.input_tokens, response.usage.output_tokens),
            model_id=self.model_id,
        )

    def stream(self, messages, system=None, max_tokens=4096, temperature=0.0):
        kwargs = {
            "model": self.api_model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            kwargs["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        with self._client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text
