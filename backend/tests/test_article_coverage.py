"""Tests for post-retrieval article coverage validation."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch
from app.services.pipeline_service import _validate_article_coverage


def test_coverage_fills_missing_law():
    """When an issue has 0 articles from an applicable law, BM25 fallback fetches them."""
    state = {
        "question": "Test question about administrator liability",
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "applicable_laws": ["31/1990", "287/2009"],
            }
        ],
        "issue_articles": {
            "ISSUE-1": [
                {"article_id": 1, "law_number": "287", "law_year": "2009", "text": "..."},
            ]
        },
        "issue_versions": {
            "ISSUE-1:31/1990": {"law_version_id": 54},
            "ISSUE-1:287/2009": {"law_version_id": 55},
        },
        "retrieved_articles": [],
        "flags": [],
    }

    mock_bm25_result = [
        {"article_id": 100, "law_number": "31", "law_year": "1990",
         "article_number": "72", "text": "Art 72 text"},
        {"article_id": 101, "law_number": "31", "law_year": "1990",
         "article_number": "73", "text": "Art 73 text"},
    ]

    with patch("app.services.pipeline_service.search_bm25", return_value=mock_bm25_result) as mock_bm25:
        result = _validate_article_coverage(state, MagicMock())

    # Should have called BM25 for the missing law
    mock_bm25.assert_called_once()
    call_args = mock_bm25.call_args
    assert call_args[0][2] == [54]  # law_version_id for 31/1990

    # ISSUE-1 should now have 3 articles (1 original + 2 fetched)
    assert len(result["issue_articles"]["ISSUE-1"]) == 3

    # Fetched articles should be marked
    fetched = [a for a in result["issue_articles"]["ISSUE-1"] if a.get("_coverage_fix")]
    assert len(fetched) == 2

    # Should be added to retrieved_articles too
    assert len(result["retrieved_articles"]) == 2

    # Should have a flag
    assert any("31/1990" in f for f in result["flags"])


def test_coverage_skips_when_articles_exist():
    """When an issue already has articles from all laws, no BM25 fetch occurs."""
    state = {
        "question": "Test question",
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "applicable_laws": ["31/1990"],
            }
        ],
        "issue_articles": {
            "ISSUE-1": [
                {"article_id": 1, "law_number": "31", "law_year": "1990", "text": "..."},
            ]
        },
        "issue_versions": {
            "ISSUE-1:31/1990": {"law_version_id": 54},
        },
        "retrieved_articles": [],
        "flags": [],
    }

    with patch("app.services.pipeline_service.search_bm25") as mock_bm25:
        _validate_article_coverage(state, MagicMock())

    mock_bm25.assert_not_called()


def test_coverage_skips_when_no_version():
    """When issue_versions has no entry for a law, skip gracefully."""
    state = {
        "question": "Test question",
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "applicable_laws": ["999/2099"],
            }
        ],
        "issue_articles": {"ISSUE-1": []},
        "issue_versions": {},
        "retrieved_articles": [],
        "flags": [],
    }

    with patch("app.services.pipeline_service.search_bm25") as mock_bm25:
        _validate_article_coverage(state, MagicMock())

    mock_bm25.assert_not_called()
