# backend/app/services/reranker_service.py
"""
Local cross-encoder reranking using sentence-transformers.
Scores each article against the question for relevance.
Free, runs locally, ~80MB model, ~5ms per article.
"""
from __future__ import annotations
import logging
from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

_model: CrossEncoder | None = None
MODEL_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

# Additive boost to cross-encoder scores based on law role.
# PRIMARY articles get a relevance bonus so they rank above SECONDARY
# unless significantly less relevant. Calibrate against actual score
# distributions from pipeline logs.
TIER_BOOST = {
    "PRIMARY": 0.15,
    "SECONDARY": 0.0,
}


def get_reranker() -> CrossEncoder:
    global _model
    if _model is None:
        logger.info(f"Loading cross-encoder model: {MODEL_NAME}")
        _model = CrossEncoder(MODEL_NAME)
        logger.info("Cross-encoder model loaded")
    return _model


def rerank_articles(
    question: str,
    articles: list[dict],
    top_k: int = 25,
) -> list[dict]:
    """Rerank articles by relevance to the question.
    Uses a cross-encoder model to score each (question, article) pair.
    Returns top_k articles sorted by score, with score added to each dict.
    """
    if not articles:
        return []

    model = get_reranker()

    # Build pairs — let tokenizer handle length limits
    pairs = [(question, art["text"]) for art in articles]

    scores = model.predict(pairs)

    for art, score in zip(articles, scores):
        art["reranker_score"] = float(score)

    # Apply tier-based boost: PRIMARY articles get a relevance bonus
    for art in articles:
        role = art.get("role", "SECONDARY")
        boost = TIER_BOOST.get(role, 0.0)
        if boost:
            art["reranker_score"] += boost

    articles.sort(key=lambda x: x["reranker_score"], reverse=True)
    return articles[:top_k]
