from __future__ import annotations

import logging
import time
from typing import Generator

import anthropic

from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
INITIAL_BACKOFF = 2  # seconds


def _cacheable_system(system: str) -> list[dict]:
    """Wrap a system prompt string as a cacheable content block."""
    return [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }
    ]


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

    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=max_tokens,
                temperature=temperature,
                system=_cacheable_system(system),
                messages=messages,
            )
            cache_created = getattr(response.usage, "cache_creation_input_tokens", 0)
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0)
            if cache_created or cache_read:
                logger.info("Cache: created=%d read=%d", cache_created, cache_read)
            duration = time.time() - start
            content = response.content[0].text if response.content else ""
            return {
                "content": content,
                "tokens_in": response.usage.input_tokens,
                "tokens_out": response.usage.output_tokens,
                "duration": duration,
                "model": CLAUDE_MODEL,
            }
        except anthropic.RateLimitError as e:
            if attempt < MAX_RETRIES - 1:
                wait = INITIAL_BACKOFF * (2 ** attempt)
                logger.warning("Rate limited (attempt %d/%d), retrying in %ds…", attempt + 1, MAX_RETRIES, wait)
                time.sleep(wait)
            else:
                logger.error("Rate limited after %d retries: %s", MAX_RETRIES, e)
                raise RuntimeError(
                    "Serviciul este momentan suprasolicitat. "
                    "Vă rugăm să așteptați un minut și să încercați din nou."
                ) from e
        except anthropic.APIError as e:
            logger.error("Claude API error: %s", e)
            raise RuntimeError(
                "A apărut o eroare la comunicarea cu serviciul AI. "
                "Vă rugăm să încercați din nou."
            ) from e


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

    for attempt in range(MAX_RETRIES):
        try:
            with client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=max_tokens,
                temperature=temperature,
                system=_cacheable_system(system),
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    full_text += text
                    yield {"type": "token", "text": text}

                final = stream.get_final_message()
                cache_created = getattr(final.usage, "cache_creation_input_tokens", 0)
                cache_read = getattr(final.usage, "cache_read_input_tokens", 0)
                if cache_created or cache_read:
                    logger.info("Cache: created=%d read=%d", cache_created, cache_read)

            duration = time.time() - start
            yield {
                "type": "done",
                "content": full_text,
                "tokens_in": final.usage.input_tokens,
                "tokens_out": final.usage.output_tokens,
                "duration": duration,
                "model": CLAUDE_MODEL,
            }
            return  # success — exit retry loop
        except anthropic.RateLimitError as e:
            if attempt < MAX_RETRIES - 1:
                wait = INITIAL_BACKOFF * (2 ** attempt)
                logger.warning("Rate limited on stream (attempt %d/%d), retrying in %ds…", attempt + 1, MAX_RETRIES, wait)
                time.sleep(wait)
                full_text = ""  # reset for retry
                start = time.time()
            else:
                logger.error("Rate limited after %d retries: %s", MAX_RETRIES, e)
                yield {
                    "type": "error",
                    "error": "Serviciul este momentan suprasolicitat. Vă rugăm să așteptați un minut și să încercați din nou.",
                }
        except anthropic.APIError as e:
            logger.error("Claude API error on stream: %s", e)
            yield {
                "type": "error",
                "error": "A apărut o eroare la comunicarea cu serviciul AI. Vă rugăm să încercați din nou.",
            }
            return
        except GeneratorExit:
            logger.info("Claude stream interrupted by client disconnect")
            return
        except (OSError, IOError):
            logger.info("Claude stream connection lost")
            return
