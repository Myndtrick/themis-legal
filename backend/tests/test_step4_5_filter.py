"""Tests for Step 4.5: pre-expansion relevance filter."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _step4_5_pre_expansion_filter


def test_filter_keeps_strong_bm25(mock_articles):
    """Articles with strong BM25 rank are kept."""
    state = {"retrieved_articles_raw": mock_articles}
    result = _step4_5_pre_expansion_filter(state)
    kept_ids = [a["article_id"] for a in result["retrieved_articles_raw"]]
    assert 101 in kept_ids


def test_filter_keeps_strong_semantic(mock_articles):
    """Articles with low semantic distance are kept."""
    state = {"retrieved_articles_raw": mock_articles}
    result = _step4_5_pre_expansion_filter(state)
    kept_ids = [a["article_id"] for a in result["retrieved_articles_raw"]]
    assert 102 in kept_ids


def test_filter_drops_weak_articles():
    """Articles with weak scores on all available metrics are dropped."""
    weak_article = {
        "article_id": 999,
        "article_number": "999",
        "bm25_rank": -0.1,
        "distance": 0.95,
        "source": "bm25",
        "tier": "tier1_primary",
    }
    strong_articles = [
        {
            "article_id": i,
            "article_number": str(i),
            "bm25_rank": -5.5,
            "source": "bm25",
            "tier": "tier1_primary",
        }
        for i in range(11)
    ]
    state = {"retrieved_articles_raw": strong_articles + [weak_article]}
    result = _step4_5_pre_expansion_filter(state)
    kept_ids = [a["article_id"] for a in result["retrieved_articles_raw"]]
    assert all(i in kept_ids for i in range(11))
    assert 999 not in kept_ids


def test_filter_keeps_entity_targeted():
    """Entity-targeted articles are always kept regardless of score."""
    entity_article = {
        "article_id": 500,
        "article_number": "500",
        "bm25_rank": -0.1,
        "source": "entity:SRL",
        "tier": "entity_targeted",
    }
    state = {"retrieved_articles_raw": [entity_article]}
    result = _step4_5_pre_expansion_filter(state)
    assert len(result["retrieved_articles_raw"]) == 1
