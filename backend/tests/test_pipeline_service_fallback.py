"""Search must fall back to BM25 when semantic embeddings (AICC) fail."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import httpx


def test_semantic_search_falls_back_to_bm25_on_aicc_5xx():
    """When query_articles raises (AICC down), _semantic_search_for_norm must
    return BM25 results instead of crashing or returning []."""
    from app.services.pipeline_service import _semantic_search_for_norm

    db = MagicMock()
    state = {
        "unique_versions": {"31/1990": [42]},  # law key -> [law_version_id]
    }

    bm25_hits = [
        {
            "article_id": 100, "article_number": "1",
            "law_number": "31", "law_year": 1990,
            "law_title": "Test", "text": "matched by BM25",
            "is_abrogated": False, "doc_type": "article",
            "annex_title": "", "date_in_force": "", "is_current": "True",
        }
    ]

    with patch(
        "app.services.pipeline_service.query_articles",
        side_effect=httpx.HTTPStatusError(
            "503", request=httpx.Request("POST", "http://x/v1/embeddings"),
            response=httpx.Response(503),
        ),
    ), patch(
        "app.services.bm25_service.search_bm25",
        return_value=bm25_hits,
    ) as mock_bm25:
        result = _semantic_search_for_norm(
            description="contract de munca",
            law_key="31/1990",
            state=state,
            db=db,
        )

    assert mock_bm25.called
    # Result should pass through BM25 hits with the same conversion the
    # function applies to ChromaDB results
    assert len(result) == 1
    assert result[0]["article_id"] == 100
    assert result[0]["law_version_id"] == 42  # propagated from version_ids[0]


def test_semantic_search_returns_empty_when_both_fail():
    from app.services.pipeline_service import _semantic_search_for_norm

    db = MagicMock()
    state = {"unique_versions": {"31/1990": [42]}}

    with patch(
        "app.services.pipeline_service.query_articles",
        side_effect=httpx.HTTPStatusError(
            "503", request=httpx.Request("POST", "http://x/v1/embeddings"),
            response=httpx.Response(503),
        ),
    ), patch(
        "app.services.bm25_service.search_bm25",
        side_effect=Exception("FTS broken"),
    ):
        result = _semantic_search_for_norm(
            description="x",
            law_key="31/1990",
            state=state,
            db=db,
        )

    assert result == []


def test_semantic_search_no_fallback_on_happy_path():
    from app.services.pipeline_service import _semantic_search_for_norm

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = MagicMock(
        id=100, article_number="1",
    )
    state = {"unique_versions": {"31/1990": [42]}}

    semantic_hits = [
        {
            "article_id": 100, "article_number": "1",
            "law_number": "31", "law_year": "1990",
            "law_title": "Test", "text": "semantic match",
            "is_abrogated": False, "doc_type": "article",
            "annex_title": "", "date_in_force": "", "is_current": "True",
            "distance": 0.1,
        }
    ]

    with patch(
        "app.services.pipeline_service.query_articles",
        return_value=semantic_hits,
    ), patch(
        "app.services.bm25_service.search_bm25",
    ) as mock_bm25:
        _semantic_search_for_norm(
            description="contract",
            law_key="31/1990",
            state=state,
            db=db,
        )

    assert not mock_bm25.called, "BM25 should not be called on happy path"


def test_tier_search_semantic_failure_doesnt_break_loop():
    """If the per-law semantic call raises mid-loop, we should log and use
    only BM25 results for that law (BM25 was already called separately),
    not abort the whole tier."""
    from app.services.pipeline_service import _safe_semantic_search

    with patch(
        "app.services.pipeline_service.query_articles",
        side_effect=httpx.HTTPStatusError(
            "503", request=httpx.Request("POST", "http://x"),
            response=httpx.Response(503),
        ),
    ):
        result = _safe_semantic_search("question", [42], n_results=5)
    assert result == []
