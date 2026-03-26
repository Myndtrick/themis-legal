"""Tests for the conditional retrieval pass after Step 6.8."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _check_missing_articles


def test_no_missing_articles(mock_rl_rap_output):
    """When no missing articles, returns empty list."""
    result = _check_missing_articles(mock_rl_rap_output)
    assert result == []


def test_detects_missing_articles():
    """When issues have missing_articles_needed, returns them."""
    rl_rap = {
        "issues": [
            {
                "issue_id": "ISSUE-1",
                "missing_articles_needed": ["Legea 31/1990 art.72", "Cod Civil art.1357 alin.(1)"],
                "certainty_level": "CONDITIONAL",
            }
        ]
    }
    result = _check_missing_articles(rl_rap)
    assert len(result) == 2
    assert "Legea 31/1990 art.72" in result


def test_caps_at_five():
    """Maximum 5 articles requested."""
    rl_rap = {
        "issues": [
            {
                "issue_id": "ISSUE-1",
                "missing_articles_needed": [f"Legea 1/2000 art.{i}" for i in range(10)],
                "certainty_level": "UNCERTAIN",
            }
        ]
    }
    result = _check_missing_articles(rl_rap)
    assert len(result) == 5


def test_deduplicates():
    """Same reference in multiple issues should appear once."""
    rl_rap = {
        "issues": [
            {
                "issue_id": "ISSUE-1",
                "missing_articles_needed": ["Legea 31/1990 art.72"],
                "certainty_level": "CONDITIONAL",
            },
            {
                "issue_id": "ISSUE-2",
                "missing_articles_needed": ["Legea 31/1990 art.72"],
                "certainty_level": "CONDITIONAL",
            },
        ]
    }
    result = _check_missing_articles(rl_rap)
    assert len(result) == 1
