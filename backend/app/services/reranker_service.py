# backend/app/services/reranker_service.py
"""
Reranker stub — no model loaded.

The previous implementation used a sentence-transformers cross-encoder
(`mmarco-mMiniLMv2-L12-H384-v1`) to score each (question, article) pair.
That dependency was dropped along with the embedder migration to AICC.

This stub preserves the public surface (`rerank_articles(question, articles, top_k)`
returning articles with `reranker_score` populated) so the pipeline keeps
working, but the score is derived from existing retrieval signals rather
than a fresh model evaluation. It produces a reasonable ordering for the
already-retrieved candidate set; quality is lower than a real cross-encoder
but acceptable for the current state of the system.

If/when reranker quality matters, replace this with a real cross-encoder
(via AICC if it exposes one, or a smaller in-process model behind its own
optional dependency).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Same tier boost the original implementation applied.
TIER_BOOST = {
    "PRIMARY": 0.15,
    "SECONDARY": 0.0,
}


def _candidate_score(art: dict) -> float:
    """Map an article's existing retrieval signals to a [0, 1]-ish score.

    Sources (in priority order):
    - Chroma distance (0=identical, 2=opposite for cosine) → invert to similarity.
    - BM25 rank (1=best) → normalize within candidate set is hard at this stage,
      so use a simple decay 1/(1+rank).
    - Fallback: 0.5 (neutral).
    """
    distance = art.get("distance")
    if distance is not None:
        # Cosine distance ∈ [0, 2]. Map to similarity ∈ [0, 1].
        try:
            return max(0.0, 1.0 - (float(distance) / 2.0))
        except (TypeError, ValueError):
            pass

    bm25_rank = art.get("bm25_rank")
    if bm25_rank is not None:
        try:
            return 1.0 / (1.0 + float(bm25_rank))
        except (TypeError, ValueError):
            pass

    return 0.5


def rerank_articles(
    question: str,  # noqa: ARG001 — kept for API compatibility
    articles: list[dict],
    top_k: int = 25,
) -> list[dict]:
    """Score articles by retrieval signals + tier boost; return top_k sorted."""
    if not articles:
        return []

    for art in articles:
        score = _candidate_score(art)
        role = art.get("role", "SECONDARY")
        score += TIER_BOOST.get(role, 0.0)
        art["reranker_score"] = float(score)

    articles.sort(key=lambda x: x["reranker_score"], reverse=True)
    return articles[:top_k]
