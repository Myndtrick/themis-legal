"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class LLMResponse:
    content: str
    usage: TokenUsage
    model_id: str


class LLMProvider(ABC):
    model_id: str

    @abstractmethod
    def chat(self, messages: list[dict], system: str | None = None,
             max_tokens: int = 4096, temperature: float = 0.0) -> LLMResponse:
        ...

    @abstractmethod
    def stream(self, messages: list[dict], system: str | None = None,
               max_tokens: int = 4096, temperature: float = 0.0) -> Iterator[str]:
        ...

    def ocr(self, document_bytes: bytes, mime_type: str) -> str:
        raise NotImplementedError("This model does not support OCR")
