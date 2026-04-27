"""AICC-backed Chroma embedding function.

Wraps AICC's OpenAI-compatible /v1/embeddings endpoint. Used by chroma_service
when EMBEDDING_PROVIDER=aicc. Indexed embeddings live in the
legal_articles_v2 collection with 1024 dims (voyage-3 default).

NOT used at all when EMBEDDING_PROVIDER=local — the legacy
SentenceTransformerEmbeddingFunction handles that path.
"""
from __future__ import annotations

import logging
import os
import time
import httpx
from chromadb import Documents, EmbeddingFunction, Embeddings

logger = logging.getLogger(__name__)

# Voyage's per-request input limit. AICC forwards directly so we batch here.
_VOYAGE_MAX_INPUTS_PER_CALL = 128

# Retry policy for 429 / 5xx from AICC. Exponential backoff with cap.
# Cumulative wait at 5 attempts: ~1+2+4+8+16 = 31s before giving up.
_RETRY_MAX_ATTEMPTS = 5
_RETRY_BASE_BACKOFF_S = 1.0
_RETRY_MAX_BACKOFF_S = 16.0

# Optional inter-call pacing: sleep this many seconds AFTER each successful
# embedding call to smooth the request rate. Useful for bulk reindex when
# AICC enforces a tight per-minute quota. Default 0 (no pacing) to keep
# query-time embedding latency unchanged. Override via env for batch jobs.
_INTER_CALL_PACING_S = float(os.environ.get("AICC_EMBED_PACING_S", "0"))


class AiccEmbeddingFunction(EmbeddingFunction[Documents]):
    """Generate embeddings via AICC /v1/embeddings (proxies to Voyage)."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "voyage-3",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("AiccEmbeddingFunction: api_key is required")
        if not base_url:
            raise ValueError("AiccEmbeddingFunction: base_url is required")
        self._model = model
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            transport=transport,
        )

    def __call__(self, input: Documents) -> Embeddings:
        # Defensive guard: Chroma's EmbeddingFunction wrapper validates the
        # output and rejects empty results, so this branch is unreachable
        # through the protocol. Kept for direct test/script callers and as
        # a hedge against future protocol changes.
        if not input:
            return []

        items = list(input)
        out: Embeddings = []
        for start in range(0, len(items), _VOYAGE_MAX_INPUTS_PER_CALL):
            batch = items[start : start + _VOYAGE_MAX_INPUTS_PER_CALL]
            out.extend(self._embed_batch(batch))
        return out

    def _embed_batch(self, batch: list[str]) -> Embeddings:
        # Retry on 429 (rate limit) and 5xx (transient upstream). 4xx other
        # than 429 are client errors (model not enabled, malformed input,
        # etc.) — retrying won't help, raise immediately.
        last_exc: Exception | None = None
        for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
            try:
                r = self._http.post(
                    "/embeddings",
                    json={"model": self._model, "input": batch},
                )
            except httpx.RequestError as e:
                last_exc = e
                if attempt == _RETRY_MAX_ATTEMPTS:
                    raise
                wait = min(_RETRY_BASE_BACKOFF_S * 2 ** (attempt - 1), _RETRY_MAX_BACKOFF_S)
                logger.warning(
                    "[aicc-embed] network error on attempt %d/%d: %s; retrying in %.1fs",
                    attempt, _RETRY_MAX_ATTEMPTS, e, wait,
                )
                time.sleep(wait)
                continue

            if r.status_code < 400:
                body = r.json()
                items = sorted(body["data"], key=lambda d: d["index"])
                result = [item["embedding"] for item in items]
                if _INTER_CALL_PACING_S > 0:
                    time.sleep(_INTER_CALL_PACING_S)
                return result

            if r.status_code == 429 or r.status_code >= 500:
                # Honor Retry-After if present, else exponential backoff.
                retry_after_header = r.headers.get("Retry-After")
                if retry_after_header:
                    try:
                        wait = float(retry_after_header)
                    except ValueError:
                        wait = _RETRY_BASE_BACKOFF_S * 2 ** (attempt - 1)
                else:
                    wait = _RETRY_BASE_BACKOFF_S * 2 ** (attempt - 1)
                wait = min(wait, _RETRY_MAX_BACKOFF_S)

                if attempt == _RETRY_MAX_ATTEMPTS:
                    logger.error(
                        "[aicc-embed] %d after %d attempts; giving up",
                        r.status_code, attempt,
                    )
                    r.raise_for_status()  # raises HTTPStatusError
                logger.warning(
                    "[aicc-embed] %d on attempt %d/%d; retrying in %.1fs",
                    r.status_code, attempt, _RETRY_MAX_ATTEMPTS, wait,
                )
                time.sleep(wait)
                continue

            # Non-retryable 4xx — raise immediately.
            r.raise_for_status()

        # Defensive: shouldn't reach here. raise_for_status above always raises.
        if last_exc:
            raise last_exc
        raise RuntimeError("aicc embed: exhausted retries without raising")

    def close(self) -> None:
        self._http.close()
