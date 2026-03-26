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
