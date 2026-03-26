"""Tests for Step 6.8: RL-RAP legal reasoning."""
import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _build_step6_8_context, _parse_step6_8_output, _derive_confidence


def test_build_context_includes_facts(mock_state_standard, mock_articles, mock_issue_versions):
    """Context should include structured facts."""
    mock_state_standard["issue_articles"] = {"ISSUE-1": mock_articles[:2]}
    mock_state_standard["shared_context"] = []
    mock_state_standard["issue_versions"] = mock_issue_versions
    ctx = _build_step6_8_context(mock_state_standard)
    assert "STATED FACTS:" in ctx
    assert "F1:" in ctx
    assert "F2:" in ctx


def test_build_context_includes_per_issue_articles(mock_state_standard, mock_articles, mock_issue_versions):
    """Context should show articles grouped by issue."""
    mock_state_standard["issue_articles"] = {"ISSUE-1": mock_articles[:2]}
    mock_state_standard["shared_context"] = [mock_articles[3]]
    mock_state_standard["issue_versions"] = mock_issue_versions
    ctx = _build_step6_8_context(mock_state_standard)
    assert "ISSUE-1:" in ctx
    assert "SHARED CONTEXT" in ctx


def test_parse_valid_output(mock_rl_rap_output):
    """Valid RL-RAP JSON should parse correctly."""
    raw = json.dumps(mock_rl_rap_output)
    parsed = _parse_step6_8_output(raw)
    assert parsed is not None
    assert "issues" in parsed
    assert parsed["issues"][0]["issue_id"] == "ISSUE-1"
    assert parsed["issues"][0]["certainty_level"] == "CONDITIONAL"


def test_parse_malformed_output():
    """Malformed output should return None."""
    parsed = _parse_step6_8_output("this is not json {{{")
    assert parsed is None


def test_derive_confidence_all_certain():
    issues = [{"certainty_level": "CERTAIN"}, {"certainty_level": "CERTAIN"}]
    assert _derive_confidence(issues) == "HIGH"


def test_derive_confidence_any_conditional():
    issues = [{"certainty_level": "CERTAIN"}, {"certainty_level": "CONDITIONAL"}]
    assert _derive_confidence(issues) == "MEDIUM"


def test_derive_confidence_any_uncertain():
    issues = [{"certainty_level": "CERTAIN"}, {"certainty_level": "UNCERTAIN"}]
    assert _derive_confidence(issues) == "LOW"


def test_derive_confidence_empty():
    assert _derive_confidence([]) == "LOW"


def test_derive_confidence_probable():
    issues = [{"certainty_level": "CERTAIN"}, {"certainty_level": "PROBABLE"}]
    assert _derive_confidence(issues) == "HIGH"
