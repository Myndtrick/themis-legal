"""OpenAI provider — routes through AICC proxy."""

from typing import Iterator
from openai import OpenAI
from app.config import AICC_KEY, AICC_BASE_URL
from app.providers.base import LLMProvider, LLMResponse, TokenUsage


class OpenAIProvider(LLMProvider):
    def __init__(self, model_id: str, api_model_id: str):
        self.model_id = model_id
        self.api_model_id = api_model_id
        self._client = OpenAI(api_key=AICC_KEY, base_url=AICC_BASE_URL)

    def chat(self, messages, system=None, max_tokens=4096, temperature=0.0):
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        response = self._client.chat.completions.create(
            model=self.model_id,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = response.choices[0]
        usage = response.usage
        return LLMResponse(
            content=choice.message.content or "",
            usage=TokenUsage(usage.prompt_tokens, usage.completion_tokens),
            model_id=self.model_id,
        )

    def stream(self, messages, system=None, max_tokens=4096, temperature=0.0):
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        stream = self._client.chat.completions.create(
            model=self.model_id,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
