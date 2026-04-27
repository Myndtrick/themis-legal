"""AICC-backed Chroma embedding function.

Wraps AICC's OpenAI-compatible /v1/embeddings endpoint. Used by chroma_service
when EMBEDDING_PROVIDER=aicc. Indexed embeddings live in the
legal_articles_v2 collection with 1024 dims (voyage-3 default).

NOT used at all when EMBEDDING_PROVIDER=local — the legacy
SentenceTransformerEmbeddingFunction handles that path.
"""
from __future__ import annotations

import logging
import httpx
from chromadb import Documents, EmbeddingFunction, Embeddings

logger = logging.getLogger(__name__)

# Voyage's per-request input limit. AICC forwards directly so we batch here.
_VOYAGE_MAX_INPUTS_PER_CALL = 128


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
        r = self._http.post(
            "/embeddings",
            json={"model": self._model, "input": batch},
        )
        r.raise_for_status()
        body = r.json()
        # Voyage/OpenAI shape: { "data": [{"index": int, "embedding": [...]}], ... }
        # Sort by index to be defensive about unordered responses.
        items = sorted(body["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in items]

    def close(self) -> None:
        self._http.close()
