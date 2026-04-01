"""Tests for the post-6.9 governing norm gate."""
from app.services.pipeline_service import _post_6_9_governing_norm_gate


def test_gate_not_triggered_when_governing_norm_present():
    """Gate returns None when governing norm is PRESENT."""
    state = {
        "primary_target": {"issue_id": "ISSUE-1"},
        "rl_rap_output": {
            "issues": [{
                "issue_id": "ISSUE-1",
                "governing_norm_status": {"status": "PRESENT"},
            }],
        },
        "selected_versions": {},
        "flags": [],
    }
    result = _post_6_9_governing_norm_gate(state)
    assert result is None
    assert not state.get("governing_norm_incomplete")


def test_gate_not_triggered_when_governing_norm_inferred():
    """Gate returns None when governing norm is INFERRED."""
    state = {
        "primary_target": {"issue_id": "ISSUE-1"},
        "rl_rap_output": {
            "issues": [{
                "issue_id": "ISSUE-1",
                "governing_norm_status": {"status": "INFERRED"},
            }],
        },
        "selected_versions": {},
        "flags": [],
    }
    result = _post_6_9_governing_norm_gate(state)
    assert result is None


def test_gate_soft_warning_when_law_in_library():
    """Gate sets soft warning when law is in library but article not surfaced."""
    state = {
        "primary_target": {"issue_id": "ISSUE-1"},
        "rl_rap_output": {
            "issues": [{
                "issue_id": "ISSUE-1",
                "governing_norm_status": {
                    "status": "MISSING",
                    "expected_norm_description": "Administrator liability provision",
                    "missing_norm_ref": "Legea 85/2014 art.169",
                },
            }],
        },
        "selected_versions": {"85/2014": {"law_version_id": 20}},
        "flags": [],
    }
    result = _post_6_9_governing_norm_gate(state)
    assert result is None  # No hard pause
    assert state["governing_norm_incomplete"] is True
    assert any("GOVERNING_NORM_MISSING" in f for f in state["flags"])


def test_gate_hard_pause_when_law_not_in_library():
    """Gate returns pause event when law is not in library at all."""
    state = {
        "primary_target": {"issue_id": "ISSUE-1"},
        "rl_rap_output": {
            "issues": [{
                "issue_id": "ISSUE-1",
                "governing_norm_status": {
                    "status": "MISSING",
                    "expected_norm_description": "Administrator liability provision",
                    "missing_norm_ref": "Legea 85/2014 art.169",
                },
            }],
        },
        "selected_versions": {},  # Law not in library
        "flags": [],
    }
    result = _post_6_9_governing_norm_gate(state)
    assert result is not None
    assert result["type"] == "gate"
    assert result["gate"] == "governing_norm_missing"


def test_gate_skips_non_primary_issues():
    """Gate only checks the primary issue."""
    state = {
        "primary_target": {"issue_id": "ISSUE-1"},
        "rl_rap_output": {
            "issues": [
                {
                    "issue_id": "ISSUE-1",
                    "governing_norm_status": {"status": "PRESENT"},
                },
                {
                    "issue_id": "ISSUE-2",
                    "governing_norm_status": {
                        "status": "MISSING",
                        "expected_norm_description": "Some other norm",
                        "missing_norm_ref": "Legea 99/2000 art.5",
                    },
                },
            ],
        },
        "selected_versions": {},
        "flags": [],
    }
    result = _post_6_9_governing_norm_gate(state)
    assert result is None


def test_gate_works_without_primary_target():
    """Gate returns None gracefully when no primary_target."""
    state = {
        "rl_rap_output": {
            "issues": [{
                "issue_id": "ISSUE-1",
                "governing_norm_status": {"status": "MISSING"},
            }],
        },
        "selected_versions": {},
        "flags": [],
    }
    result = _post_6_9_governing_norm_gate(state)
    assert result is None
