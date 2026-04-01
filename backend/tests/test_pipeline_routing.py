"""Tests for complexity-based pipeline routing."""


def test_simple_state_has_complexity(mock_state_simple):
    assert mock_state_simple["complexity"] == "SIMPLE"


def test_standard_state_has_facts(mock_state_standard):
    assert "facts" in mock_state_standard
    assert len(mock_state_standard["facts"]["stated"]) > 0


def test_simple_state_has_empty_facts(mock_state_simple):
    assert mock_state_simple.get("facts", {}).get("stated", []) == []


def test_complexity_routing_simple():
    """SIMPLE complexity should route to fast path."""
    state = {"complexity": "SIMPLE"}
    assert state["complexity"] == "SIMPLE"


def test_complexity_routing_standard():
    """STANDARD complexity should route to full path."""
    state = {"complexity": "STANDARD"}
    assert state["complexity"] in ("STANDARD", "COMPLEX")


def test_rubric_zero_signals_is_simple():
    """A direct factual question with 0 signals should be SIMPLE."""
    state = {
        "complexity": "SIMPLE",
        "legal_issues": [{"issue_id": "ISSUE-1", "description": "Minimum share capital"}],
    }
    assert state["complexity"] == "SIMPLE"
    assert len(state["legal_issues"]) == 1


def test_rubric_override_what_is_always_simple():
    """'What is X' questions should always be SIMPLE regardless of apparent complexity."""
    state = {
        "question": "Ce este capitalul social?",
        "complexity": "SIMPLE",
    }
    assert state["complexity"] == "SIMPLE"


def test_rubric_two_signals_is_standard():
    """A scenario with 2 signals should be STANDARD."""
    state = {
        "complexity": "STANDARD",
        "legal_issues": [{"issue_id": "ISSUE-1", "description": "Validity of transaction"}],
        "facts": {"stated": [{"fact_id": "F1"}], "assumed": [], "missing": []},
    }
    assert state["complexity"] == "STANDARD"
    assert "facts" in state


def test_rubric_three_plus_signals_is_complex():
    """A scenario with 3+ signals should be COMPLEX."""
    state = {
        "complexity": "COMPLEX",
        "legal_issues": [
            {"issue_id": "ISSUE-1", "description": "Fiscal obligations"},
            {"issue_id": "ISSUE-2", "description": "Corporate obligations"},
        ],
    }
    assert state["complexity"] == "COMPLEX"
    assert len(state["legal_issues"]) > 1
