"""Tests for Step 7 context builder with new fields."""
from app.services.pipeline_service import _build_step7_context


def _make_state(primary_target=None, governing_norm_incomplete=False, rl_rap=None):
    """Helper to build a minimal state dict for Step 7 context."""
    return {
        "question": "Test question",
        "question_type": "B",
        "legal_domain": "corporate",
        "output_mode": "qa",
        "core_issue": "Test issue",
        "primary_target": primary_target,
        "governing_norm_incomplete": governing_norm_incomplete,
        "rl_rap_output": rl_rap,
        "facts": {"stated": [], "assumed": [], "missing": []},
        "retrieved_articles": [],
        "stale_versions": [],
        "candidate_laws": [],
        "flags": [],
    }


def test_step7_context_includes_primary_target():
    """Step 7 context should include primary_target when present."""
    state = _make_state(
        primary_target={"actor": "administrator", "concern": "liability", "issue_id": "ISSUE-1"},
    )
    result = _build_step7_context(state)
    assert "PRIMARY TARGET:" in result
    assert "Actor: administrator" in result


def test_step7_context_includes_governing_norm_incomplete():
    """Step 7 context should flag governing_norm_incomplete."""
    state = _make_state(governing_norm_incomplete=True)
    result = _build_step7_context(state)
    assert "GOVERNING_NORM_INCOMPLETE" in result


def test_step7_context_includes_uncertainty_sources():
    """Step 7 context should include uncertainty_sources from RL-RAP."""
    rl_rap = {
        "issues": [{
            "issue_id": "ISSUE-1",
            "issue_label": "Test",
            "certainty_level": "CONDITIONAL",
            "operative_articles": [],
            "decomposed_conditions": [],
            "condition_table": [
                {"condition_id": "C1", "condition_text": "test", "status": "UNKNOWN",
                 "norm_ref": "art.1", "evidence": None, "missing_fact": "some fact"}
            ],
            "subsumption_summary": {"total_conditions": 1, "satisfied": 0,
                                    "not_satisfied": 0, "unknown": 1,
                                    "norm_applicable": "CONDITIONAL", "blocking_unknowns": ["C1"]},
            "uncertainty_sources": [
                {"type": "FACTUAL_GAP", "detail": "Missing fact X",
                 "impact": "Cannot evaluate C1", "resolvable_by": "USER_INPUT"}
            ],
            "governing_norm_status": {"status": "PRESENT"},
            "conclusion": "Conditional on X.",
            "missing_facts": ["some fact"],
        }],
    }
    state = _make_state(rl_rap=rl_rap)
    result = _build_step7_context(state)
    assert "Uncertainty sources:" in result
    assert "FACTUAL_GAP" in result
    assert "Condition table:" in result
    assert "Subsumption:" in result


def test_step7_context_without_new_fields():
    """Step 7 context works without new fields (backward compat)."""
    state = _make_state()
    result = _build_step7_context(state)
    assert "PRIMARY TARGET:" not in result
    assert "GOVERNING_NORM_INCOMPLETE" not in result
    assert "USER QUESTION:" in result
