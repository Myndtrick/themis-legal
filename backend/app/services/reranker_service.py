# backend/app/services/reranker_service.py
"""LLM-based reranker via AICC.

Replaces the previous sentence-transformers cross-encoder. Uses
claude-haiku-4-5 (cheap, fast) through AICC's OpenAI-compatible
chat completions to score each article for relevance to the question.

Per-query cost: ~$0.005 at typical 25-50 articles. Latency: ~2-5s.
"""
from __future__ import annotations

import json
import logging
import re

from openai import OpenAI

from app.config import AICC_BASE_URL, AICC_KEY, CLAUDE_MODEL_FAST

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=AICC_KEY, base_url=AICC_BASE_URL)
    return _client


# Additive boost based on law role. PRIMARY laws get a small bonus so
# they rank above SECONDARY when LLM scores are similar.
TIER_BOOST = {
    "PRIMARY": 0.15,
    "SECONDARY": 0.0,
}

# Per-article truncation when building the rerank prompt. The first ~400
# chars are usually enough to assess relevance; full text would blow context
# at 25-50 articles.
_PER_ARTICLE_CHARS = 400

# Max articles to score in one LLM call. Above this, score the rest with
# the retrieval-signal stub to avoid context blowout.
_MAX_ARTICLES_PER_CALL = 60


def _stub_score(art: dict) -> float:
    """Score from existing retrieval signals, used when LLM call fails or
    article exceeds the LLM batch cap. Returns a value in [0, 1].
    """
    distance = art.get("distance")
    if distance is not None:
        try:
            # Cosine distance in [0, 2]; map to similarity in [0, 1].
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


def _llm_score_articles(question: str, articles: list[dict]) -> dict[int, float] | None:
    """Ask the LLM to score each article 0.0-1.0 for relevance.

    Returns {position_index: score} keyed by the article's position in
    the input list, or None on failure.
    """
    if not articles:
        return {}

    items = []
    for i, art in enumerate(articles):
        text = (art.get("text") or "")[:_PER_ARTICLE_CHARS]
        items.append(f"[{i}] {text}")

    prompt = (
        f"Question: {question}\n\n"
        "Articles:\n" + "\n\n".join(items) + "\n\n"
        "For each article above, judge how directly relevant it is to answering "
        "the question. Return ONLY a JSON object of the form:\n"
        '{"scores": [{"idx": int, "score": float}, ...]}\n'
        "where idx is the article number (0-based) and score is in [0.0, 1.0]. "
        "1.0 = directly answers the question; 0.5 = somewhat related; 0.0 = irrelevant. "
        "Output JSON only, no prose."
    )

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=CLAUDE_MODEL_FAST,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.0,
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error("[reranker] LLM call failed: %s", e)
        return None

    # Extract JSON object (LLM may wrap in code fences or add stray text).
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        logger.warning("[reranker] LLM returned no JSON: %r", text[:200])
        return None

    try:
        data = json.loads(match.group())
        scores = data.get("scores") or []
        return {int(s["idx"]): float(s["score"]) for s in scores}
    except Exception as e:
        logger.warning("[reranker] failed to parse LLM JSON: %s; text=%r", e, text[:200])
        return None


def rerank_articles(
    question: str,
    articles: list[dict],
    top_k: int = 25,
) -> list[dict]:
    """Rerank articles by LLM relevance + tier boost; return top_k."""
    if not articles:
        return []

    # Score the first N via LLM; rest via stub to keep prompt size bounded.
    target = articles[:_MAX_ARTICLES_PER_CALL]
    rest = articles[_MAX_ARTICLES_PER_CALL:]

    score_map = _llm_score_articles(question, target)

    if score_map is None:
        # LLM failed entirely — degrade to retrieval-signal stub for all.
        logger.warning("[reranker] LLM rerank failed; using retrieval-signal stub")
        for art in articles:
            art["reranker_score"] = _stub_score(art)
    else:
        for i, art in enumerate(target):
            art["reranker_score"] = float(score_map.get(i, _stub_score(art)))
        for art in rest:
            art["reranker_score"] = _stub_score(art)

    # Apply tier boost.
    for art in articles:
        role = art.get("role", "SECONDARY")
        boost = TIER_BOOST.get(role, 0.0)
        if boost:
            art["reranker_score"] += boost

    articles.sort(key=lambda x: x["reranker_score"], reverse=True)
    return articles[:top_k]
