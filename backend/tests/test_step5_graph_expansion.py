"""Tests for Step 5: unified graph expansion."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock
from app.services.pipeline_service import _append_new_articles, _cap_for_expansion


# --- _cap_for_expansion tests ---

def test_cap_no_op_when_under_limit():
    """Articles below MAX_EXPANSION_INPUT pass through unchanged."""
    articles = [{"article_id": i, "distance": 0.5} for i in range(10)]
    state = {"retrieved_articles_raw": articles}
    result = _cap_for_expansion(state)
    assert len(result["retrieved_articles_raw"]) == 10


def test_cap_trims_to_limit():
    """Articles above MAX_EXPANSION_INPUT are trimmed to best by distance."""
    articles = [{"article_id": i, "distance": i * 0.1} for i in range(40)]
    state = {"retrieved_articles_raw": articles}
    result = _cap_for_expansion(state)
    assert len(result["retrieved_articles_raw"]) == 30
    assert result["retrieved_articles_raw"][0]["distance"] == 0.0


def test_cap_sorts_by_distance():
    """Cap should sort by distance ascending (best first)."""
    articles = [
        {"article_id": 1, "distance": 0.9},
        {"article_id": 2, "distance": 0.1},
        {"article_id": 3, "distance": 0.5},
    ]
    filler = [{"article_id": 100 + i, "distance": 0.4} for i in range(30)]
    state = {"retrieved_articles_raw": articles + filler}
    result = _cap_for_expansion(state)
    assert result["retrieved_articles_raw"][0]["distance"] == 0.1


def test_cap_handles_missing_distance():
    """Articles without distance field get default 1.0 (sorted last)."""
    good = [{"article_id": i, "distance": 0.1} for i in range(29)]
    no_dist = [{"article_id": 99}, {"article_id": 98}]
    state = {"retrieved_articles_raw": good + no_dist}
    result = _cap_for_expansion(state)
    assert len(result["retrieved_articles_raw"]) == 30
    kept_ids = [a["article_id"] for a in result["retrieved_articles_raw"]]
    assert 99 in kept_ids or 98 in kept_ids


# --- _append_new_articles tests ---

def test_append_deduplicates():
    """Articles already in state are not re-added."""
    state = {
        "retrieved_articles_raw": [{"article_id": 1}],
        "law_mapping": {"tier1_primary": []},
    }
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = []
    result = _append_new_articles(state, mock_db, [1], source="expansion")
    assert result == 0


def test_append_empty_ids():
    """Empty new_ids list returns 0 added."""
    state = {
        "retrieved_articles_raw": [],
        "law_mapping": {"tier1_primary": []},
    }
    mock_db = MagicMock()
    result = _append_new_articles(state, mock_db, [], source="expansion")
    assert result == 0
