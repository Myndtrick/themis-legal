from __future__ import annotations

import logging
import time
from typing import Generator

from openai import OpenAI, RateLimitError, APIError

from app.config import AICC_KEY, AICC_BASE_URL, CLAUDE_MODEL

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
INITIAL_BACKOFF = 20  # seconds (rate limit is per-minute, need longer waits)


_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not AICC_KEY:
            raise ValueError(
                "AICC_KEY environment variable is not set. "
                "Set it before using the Legal Assistant."
            )
        _client = OpenAI(api_key=AICC_KEY, base_url=AICC_BASE_URL)
    return _client


def call_claude(
    system: str,
    messages: list[dict],
    max_tokens: int = 4096,
    temperature: float = 0.2,
    model: str | None = None,
) -> dict:
    """Call Claude via AICC synchronously. Returns dict with content, usage stats."""
    client = get_client()
    use_model = model or CLAUDE_MODEL
    start = time.time()

    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=use_model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=msgs,
            )
            duration = time.time() - start
            choice = response.choices[0]
            content = choice.message.content or ""
            return {
                "content": content,
                "tokens_in": response.usage.prompt_tokens,
                "tokens_out": response.usage.completion_tokens,
                "duration": duration,
                "model": use_model,
            }
        except RateLimitError as e:
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
        except APIError as e:
            logger.error("AICC API error (type=%s, status=%s): %s", type(e).__name__, getattr(e, 'status_code', '?'), e)
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
    """Stream Claude via AICC. Yields dicts: {type: 'token', text} or {type: 'done', ...}."""
    client = get_client()
    start = time.time()
    full_text = ""

    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    for attempt in range(MAX_RETRIES):
        try:
            stream = client.chat.completions.create(
                model=CLAUDE_MODEL,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=msgs,
                stream=True,
                stream_options={"include_usage": True},
            )
            tokens_in = 0
            tokens_out = 0
            for chunk in stream:
                if chunk.usage is not None:
                    tokens_in = chunk.usage.prompt_tokens
                    tokens_out = chunk.usage.completion_tokens
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None)
                if text:
                    full_text += text
                    yield {"type": "token", "text": text}

            duration = time.time() - start
            yield {
                "type": "done",
                "content": full_text,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "duration": duration,
                "model": CLAUDE_MODEL,
            }
            return  # success — exit retry loop
        except RateLimitError as e:
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
        except APIError as e:
            logger.error("AICC API error on stream: %s", e)
            yield {
                "type": "error",
                "error": "A apărut o eroare la comunicarea cu serviciul AI. Vă rugăm să încercați din nou.",
            }
            return
        except GeneratorExit:
            logger.info("AICC stream interrupted by client disconnect")
            return
        except (OSError, IOError):
            logger.info("AICC stream connection lost")
            return
