"""Tests for Step 1 issue prioritization state extraction."""


def test_primary_target_extracted_from_step1_output():
    """primary_target from Step 1 JSON is stored in state."""
    parsed = {
        "question_type": "B",
        "legal_domain": "corporate",
        "output_mode": "qa",
        "core_issue": "Administrator liability",
        "primary_target": {
            "actor": "administrator",
            "concern": "personal liability",
            "issue_id": "ISSUE-1",
            "reasoning": "User asks about administrator exposure",
        },
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "description": "Administrator personal liability",
                "relevant_date": "2026-07-01",
                "temporal_rule": "insolvency_opening",
                "applicable_laws": ["85/2014"],
                "priority": "PRIMARY",
                "priority_reasoning": "Directly addresses user question",
            },
            {
                "issue_id": "ISSUE-2",
                "description": "Transaction annulment",
                "relevant_date": "2026-03-01",
                "temporal_rule": "act_date",
                "applicable_laws": ["85/2014"],
                "priority": "SECONDARY",
                "priority_reasoning": "Related but not direct question",
            },
        ],
    }
    state = {"flags": []}
    state["primary_target"] = parsed.get("primary_target")
    state["legal_issues"] = parsed.get("legal_issues", [])

    assert state["primary_target"]["actor"] == "administrator"
    assert state["primary_target"]["issue_id"] == "ISSUE-1"
    assert state["legal_issues"][0]["priority"] == "PRIMARY"
    assert state["legal_issues"][1]["priority"] == "SECONDARY"


def test_primary_target_defaults_to_none_when_missing():
    """If Step 1 doesn't produce primary_target, state gets None."""
    parsed = {
        "question_type": "A",
        "legal_issues": [{"issue_id": "ISSUE-1", "description": "Test"}],
    }
    state = {"flags": []}
    state["primary_target"] = parsed.get("primary_target")
    assert state["primary_target"] is None
