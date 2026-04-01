"""Tests for Step 6.8 context builder with issue prioritization."""
from app.services.pipeline_service import _build_step6_8_context


def test_build_step6_8_context_includes_primary_target():
    """Context message should include primary_target when present."""
    state = {
        "primary_target": {
            "actor": "administrator",
            "concern": "personal liability",
            "issue_id": "ISSUE-1",
            "reasoning": "User asks about administrator exposure",
        },
        "facts": {"stated": [], "assumed": [], "missing": []},
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "description": "Administrator liability",
                "relevant_date": "2026-07-01",
                "temporal_rule": "insolvency_opening",
                "applicable_laws": ["85/2014"],
                "priority": "PRIMARY",
            },
            {
                "issue_id": "ISSUE-2",
                "description": "Transaction annulment",
                "relevant_date": "2026-03-01",
                "temporal_rule": "act_date",
                "applicable_laws": ["85/2014"],
                "priority": "SECONDARY",
            },
        ],
        "issue_articles": {},
        "issue_versions": {},
        "shared_context": [],
        "flags": [],
    }
    result = _build_step6_8_context(state)
    assert "PRIMARY TARGET:" in result
    assert "Actor: administrator" in result
    assert "Concern: personal liability" in result
    assert "[PRIMARY]" in result
    assert "[SECONDARY]" in result


def test_build_step6_8_context_without_primary_target():
    """Context message should work without primary_target (backward compat)."""
    state = {
        "facts": {"stated": [], "assumed": [], "missing": []},
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "description": "Test issue",
                "relevant_date": "2026-01-01",
                "temporal_rule": "current_law",
                "applicable_laws": [],
            },
        ],
        "issue_articles": {},
        "issue_versions": {},
        "shared_context": [],
        "flags": [],
    }
    result = _build_step6_8_context(state)
    assert "PRIMARY TARGET:" not in result
    assert "ISSUE-1" in result
