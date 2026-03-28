"""Mistral provider for chat and OCR."""

import os
from typing import Iterator
from mistralai.client.sdk import Mistral
from app.providers.base import LLMProvider, LLMResponse, TokenUsage


class MistralProvider(LLMProvider):
    def __init__(self, model_id: str, api_model_id: str, supports_ocr: bool = False):
        self.model_id = model_id
        self.api_model_id = api_model_id
        self._supports_ocr = supports_ocr
        api_key = os.environ.get("MISTRAL_API_KEY", "")
        self._client = Mistral(api_key=api_key)

    def chat(self, messages, system=None, max_tokens=4096, temperature=0.0):
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        response = self._client.chat.complete(
            model=self.api_model_id,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = response.choices[0]
        usage = response.usage
        return LLMResponse(
            content=choice.message.content,
            usage=TokenUsage(usage.prompt_tokens, usage.completion_tokens),
            model_id=self.model_id,
        )

    def stream(self, messages, system=None, max_tokens=4096, temperature=0.0):
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        for chunk in self._client.chat.stream(
            model=self.api_model_id,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            delta = chunk.data.choices[0].delta
            if delta.content:
                yield delta.content

    def ocr(self, document_bytes: bytes, mime_type: str) -> str:
        if not self._supports_ocr:
            raise NotImplementedError("This Mistral model does not support OCR")
        import base64
        b64 = base64.b64encode(document_bytes).decode()
        response = self._client.ocr.process(
            model=self.api_model_id,
            document={"type": "base64", "data": b64, "mime_type": mime_type},
        )
        return "\n\n".join(page.markdown for page in response.pages)
