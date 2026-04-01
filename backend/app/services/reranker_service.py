# backend/app/services/reranker_service.py
"""
Local cross-encoder reranking using sentence-transformers.
Scores each article against the question for relevance.
Free, runs locally, ~80MB model, ~5ms per article.
"""
from __future__ import annotations
import logging
from collections import Counter
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
    min_per_law: int = 3,
) -> list[dict]:
    """Rerank articles by relevance to the question.
    Uses a cross-encoder model to score each (question, article) pair.
    Returns top_k articles sorted by score, with score added to each dict.

    min_per_law: guarantee at least this many articles per law in the
    result, swapping out the lowest-scoring articles from over-represented
    laws when necessary.  Set to 0 to disable.
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

    ranked = sorted(articles, key=lambda a: a.get("reranker_score", 0), reverse=True)
    selected = list(ranked[:top_k])

    # --- Per-law minimum guarantee ---
    if min_per_law > 0:
        selected_set = set(id(a) for a in selected)
        law_counts = Counter(
            f"{a.get('law_number', '')}/{a.get('law_year', '')}" for a in selected
        )
        all_laws = set(
            f"{a.get('law_number', '')}/{a.get('law_year', '')}" for a in articles
        )

        for law_key in all_laws:
            if not law_key or law_key == "/":
                continue
            current_count = law_counts.get(law_key, 0)
            if current_count >= min_per_law:
                continue

            # Find best candidates for this law not already selected
            candidates = [
                a for a in ranked
                if f"{a.get('law_number', '')}/{a.get('law_year', '')}" == law_key
                and id(a) not in selected_set
            ]
            needed = min_per_law - current_count

            for candidate in candidates[:needed]:
                # Find the most over-represented law
                if not law_counts:
                    break
                over_rep_law = law_counts.most_common(1)[0][0]
                over_rep_count = law_counts[over_rep_law]
                if over_rep_count <= min_per_law:
                    # All laws are at minimum — expand top_k instead of swapping
                    selected.append(candidate)
                    selected_set.add(id(candidate))
                    law_counts[law_key] = law_counts.get(law_key, 0) + 1
                    continue

                # Find lowest-scoring article from the over-represented law
                victims = [
                    a for a in selected
                    if f"{a.get('law_number', '')}/{a.get('law_year', '')}" == over_rep_law
                ]
                if not victims:
                    break
                victim = min(victims, key=lambda a: a.get("reranker_score", 0))

                selected.remove(victim)
                selected_set.discard(id(victim))
                selected.append(candidate)
                selected_set.add(id(candidate))
                law_counts[over_rep_law] -= 1
                law_counts[law_key] = law_counts.get(law_key, 0) + 1

    return sorted(selected, key=lambda a: a.get("reranker_score", 0), reverse=True)
