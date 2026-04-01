"""Tests for RL-RAP terminology translation in _build_step7_context."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _build_step7_context


def _make_state_with_rl_rap():
    return {
        "question_type": "B",
        "legal_domain": "corporate",
        "output_mode": "compliance",
        "core_issue": "Test issue",
        "primary_target": {"actor": "admin", "concern": "liability", "issue_id": "ISSUE-1"},
        "governing_norm_incomplete": False,
        "facts": {"stated": [{"fact_id": "F1", "description": "Test fact"}], "assumed": [], "missing": []},
        "rl_rap_output": {
            "issues": [{
                "issue_id": "ISSUE-1",
                "issue_label": "Test",
                "certainty_level": "CONDITIONAL",
                "operative_articles": [],
                "condition_table": [
                    {"condition_id": "C1", "condition_text": "test condition",
                     "status": "SATISFIED", "evidence": "F1: fact", "missing_fact": None},
                    {"condition_id": "C2", "condition_text": "unknown condition",
                     "status": "UNKNOWN", "evidence": None, "missing_fact": "some fact"},
                ],
                "subsumption_summary": {
                    "satisfied": 1, "not_satisfied": 0, "unknown": 1,
                    "norm_applicable": "CONDITIONAL", "blocking_unknowns": ["C2"],
                },
                "uncertainty_sources": [
                    {"type": "LIBRARY_GAP", "detail": "Art 117 missing",
                     "impact": "Cannot verify", "resolvable_by": "ARTICLE_IMPORT"},
                    {"type": "FACTUAL_GAP", "detail": "Damage amount",
                     "impact": "Cannot quantify", "resolvable_by": "USER_INPUT"},
                ],
                "temporal_applicability": {"version_matches": True, "temporal_risks": []},
                "conclusion": "Test conclusion",
                "governing_norm_status": {"status": "PRESENT"},
                "missing_facts": [],
            }]
        },
        "retrieved_articles": [],
        "issue_articles": {"ISSUE-1": []},
        "issue_versions": {},
        "fact_version_map": {},
        "legal_issues": [{"issue_id": "ISSUE-1", "applicable_laws": [], "relevant_date": "2026-03-31", "temporal_rule": "act_date"}],
        "flags": [],
    }


def test_no_raw_satisfied_in_context():
    """Context must not contain raw 'SATISFIED' — should be translated."""
    state = _make_state_with_rl_rap()
    ctx = _build_step7_context(state)
    assert "Condiție îndeplinită" in ctx
    assert " — SATISFIED" not in ctx
    assert " — UNKNOWN" not in ctx


def test_no_raw_uncertainty_types_in_context():
    """Context must not contain LIBRARY_GAP, ARTICLE_IMPORT etc."""
    state = _make_state_with_rl_rap()
    ctx = _build_step7_context(state)
    assert "LIBRARY_GAP" not in ctx
    assert "FACTUAL_GAP" not in ctx
    assert "ARTICLE_IMPORT" not in ctx
    assert "USER_INPUT" not in ctx


def test_translated_uncertainty_present():
    """Translated uncertainty descriptions should appear."""
    state = _make_state_with_rl_rap()
    ctx = _build_step7_context(state)
    assert "Articol indisponibil" in ctx
    assert "Informație lipsă din întrebare" in ctx


def test_no_raw_norm_applicable_in_context():
    """Subsumption summary should use translated labels."""
    state = _make_state_with_rl_rap()
    ctx = _build_step7_context(state)
    assert "norm_applicable" not in ctx
    assert "blocking_unknowns" not in ctx


def test_certainty_as_natural_sentence():
    """Certainty level should be a natural sentence, not a label."""
    state = _make_state_with_rl_rap()
    ctx = _build_step7_context(state)
    assert "Concluzia depinde de informații lipsă" in ctx


def test_no_raw_governing_norm_status():
    """Governing norm status MISSING/INFERRED must be translated."""
    state = _make_state_with_rl_rap()
    state["rl_rap_output"]["issues"][0]["governing_norm_status"] = {
        "status": "MISSING",
        "explanation": "Art. 169 not in provided articles",
    }
    ctx = _build_step7_context(state)
    assert "MISSING" not in ctx
    assert "Norma nu a fost identificat" in ctx


def test_no_raw_exception_status():
    """Exception condition_status_summary must be translated."""
    state = _make_state_with_rl_rap()
    state["rl_rap_output"]["issues"][0]["exceptions_checked"] = [
        {
            "exception_ref": "Legea 31/1990 art.197 alin.(4)",
            "condition_status_summary": "UNKNOWN",
            "impact": "Exception for ordinary course",
        }
    ]
    ctx = _build_step7_context(state)
    lines_with_exception = [l for l in ctx.split("\n") if "197" in l and "alin" in l]
    for line in lines_with_exception:
        assert "— UNKNOWN —" not in line


def test_no_raw_conflict_resolution_rule():
    """Conflict resolution_rule must be translated."""
    state = _make_state_with_rl_rap()
    state["rl_rap_output"]["issues"][0]["conflicts"] = {
        "resolution_rule": "UNRESOLVED",
        "rationale": "competing provisions",
    }
    ctx = _build_step7_context(state)
    assert "UNRESOLVED" not in ctx
    assert "Conflict nerezolvat" in ctx


def test_blocking_unknowns_use_condition_text():
    """blocking_unknowns should show condition text, not IDs like C1, C2."""
    state = _make_state_with_rl_rap()
    state["rl_rap_output"]["issues"][0]["subsumption_summary"]["blocking_unknowns"] = ["C2"]
    ctx = _build_step7_context(state)
    assert "unknown condition" in ctx


def test_governing_norm_present_not_shown():
    """When governing_norm_status is PRESENT, nothing should be output about it."""
    state = _make_state_with_rl_rap()
    state["rl_rap_output"]["issues"][0]["governing_norm_status"] = {"status": "PRESENT"}
    ctx = _build_step7_context(state)
    assert "Governing norm" not in ctx
    assert "Norma guvernant" not in ctx
