from __future__ import annotations

import logging
import time
from typing import Generator

import anthropic

from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Set it before using the Legal Assistant."
            )
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def call_claude(
    system: str,
    messages: list[dict],
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> dict:
    """Call Claude API synchronously. Returns dict with content, usage stats."""
    client = get_client()
    start = time.time()
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=messages,
    )
    duration = time.time() - start
    content = response.content[0].text if response.content else ""
    return {
        "content": content,
        "tokens_in": response.usage.input_tokens,
        "tokens_out": response.usage.output_tokens,
        "duration": duration,
        "model": CLAUDE_MODEL,
    }


def stream_claude(
    system: str,
    messages: list[dict],
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> Generator[dict, None, None]:
    """Stream Claude API response. Yields dicts: {type: 'token', text} or {type: 'done', ...}."""
    client = get_client()
    start = time.time()
    full_text = ""

    with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            full_text += text
            yield {"type": "token", "text": text}

        final = stream.get_final_message()

    duration = time.time() - start
    yield {
        "type": "done",
        "content": full_text,
        "tokens_in": final.usage.input_tokens,
        "tokens_out": final.usage.output_tokens,
        "duration": duration,
        "model": CLAUDE_MODEL,
    }
