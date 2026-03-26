"""Tests for Step 6.7: article-to-issue partitioning."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _step6_7_partition_articles


def test_partition_assigns_article_to_matching_issue(mock_articles, mock_issue_versions):
    """Article with matching law_version_id is assigned to the correct issue."""
    state = {
        "retrieved_articles": mock_articles[:2],  # articles 101, 102 with law_version_id=10
        "legal_issues": [
            {"issue_id": "ISSUE-1", "applicable_laws": ["31/1990"]}
        ],
        "issue_versions": mock_issue_versions,
        "flags": [],
    }
    result = _step6_7_partition_articles(state)
    assert "ISSUE-1" in result["issue_articles"]
    issue_1_ids = [a["article_id"] for a in result["issue_articles"]["ISSUE-1"]]
    assert 101 in issue_1_ids
    assert 102 in issue_1_ids


def test_partition_unmatched_goes_to_shared(mock_articles, mock_issue_versions):
    """Article not matching any issue goes to shared_context."""
    state = {
        "retrieved_articles": mock_articles,  # includes article 301 (Cod Civil, version 30)
        "legal_issues": [
            {"issue_id": "ISSUE-1", "applicable_laws": ["31/1990"]}
        ],
        "issue_versions": mock_issue_versions,
        "flags": [],
    }
    result = _step6_7_partition_articles(state)
    shared_ids = [a["article_id"] for a in result["shared_context"]]
    assert 301 in shared_ids


def test_partition_article_in_multiple_issues():
    """Article can belong to multiple issues if same version needed."""
    articles = [
        {"article_id": 101, "law_version_id": 10, "law_number": "31", "law_year": "1990"},
    ]
    issue_versions = {
        "ISSUE-1:31/1990": {"law_version_id": 10, "issue_id": "ISSUE-1", "law_key": "31/1990"},
        "ISSUE-2:31/1990": {"law_version_id": 10, "issue_id": "ISSUE-2", "law_key": "31/1990"},
    }
    state = {
        "retrieved_articles": articles,
        "legal_issues": [
            {"issue_id": "ISSUE-1", "applicable_laws": ["31/1990"]},
            {"issue_id": "ISSUE-2", "applicable_laws": ["31/1990"]},
        ],
        "issue_versions": issue_versions,
        "flags": [],
    }
    result = _step6_7_partition_articles(state)
    assert 101 in [a["article_id"] for a in result["issue_articles"]["ISSUE-1"]]
    assert 101 in [a["article_id"] for a in result["issue_articles"]["ISSUE-2"]]


def test_partition_empty_issue_flagged():
    """Issue with zero articles gets flagged."""
    state = {
        "retrieved_articles": [],
        "legal_issues": [
            {"issue_id": "ISSUE-1", "applicable_laws": ["31/1990"]}
        ],
        "issue_versions": {
            "ISSUE-1:31/1990": {"law_version_id": 10, "issue_id": "ISSUE-1", "law_key": "31/1990"},
        },
        "flags": [],
    }
    result = _step6_7_partition_articles(state)
    assert "ISSUE-1" in result["issue_articles"]
    assert len(result["issue_articles"]["ISSUE-1"]) == 0
    assert any("ISSUE-1" in f for f in result["flags"])
