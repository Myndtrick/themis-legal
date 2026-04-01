"""Tests for _derive_final_confidence with new rules."""
from app.services.pipeline_service import _derive_final_confidence


def _call(
    claude="HIGH",
    issues=None,
    has_articles=True,
    primary_from_db=True,
    missing_primary=False,
    has_stale=False,
    citation=None,
    governing_norm_incomplete=False,
    uncertainty_sources=None,
):
    return _derive_final_confidence(
        claude_confidence=claude,
        rl_rap_issues=issues or [],
        has_articles=has_articles,
        primary_from_db=primary_from_db,
        missing_primary=missing_primary,
        has_stale_versions=has_stale,
        citation_validation=citation or {"downgraded": 0, "total_db": 0},
        governing_norm_incomplete=governing_norm_incomplete,
        uncertainty_sources=uncertainty_sources or [],
    )


def test_rule1_no_articles_returns_low():
    conf, reason = _call(has_articles=False)
    assert conf == "LOW"


def test_rule3_uncertain_issue_returns_low():
    conf, reason = _call(issues=[{"certainty_level": "UNCERTAIN"}])
    assert conf == "LOW"


def test_rule3_5_governing_norm_incomplete_returns_low():
    """New rule: governing norm missing for primary issue -> LOW."""
    conf, reason = _call(governing_norm_incomplete=True)
    assert conf == "LOW"
    assert "governing norm" in reason.lower() or "Governing norm" in reason


def test_rule4_conditional_caps_at_medium():
    conf, reason = _call(issues=[{"certainty_level": "CONDITIONAL"}])
    assert conf == "MEDIUM"


def test_rule4_5_library_gap_caps_at_medium():
    """New rule: LIBRARY_GAP -> cap at MEDIUM."""
    sources = [{"type": "LIBRARY_GAP", "detail": "Art. 169 missing"}]
    conf, reason = _call(uncertainty_sources=sources)
    assert conf == "MEDIUM"


def test_rule4_6_majority_unknown_conditions_caps_at_medium():
    """New rule: majority of conditions UNKNOWN -> cap at MEDIUM."""
    issues = [{
        "certainty_level": "CONDITIONAL",
        "subsumption_summary": {
            "total_conditions": 4,
            "satisfied": 1,
            "not_satisfied": 0,
            "unknown": 3,
            "norm_applicable": "CONDITIONAL",
            "blocking_unknowns": ["C2", "C3", "C4"],
        },
    }]
    conf, reason = _call(issues=issues)
    assert conf == "MEDIUM"


def test_existing_rule5_primary_not_from_db():
    conf, reason = _call(primary_from_db=False)
    assert conf == "MEDIUM"


def test_existing_rule7_stale_versions():
    conf, reason = _call(has_stale=True)
    assert conf == "MEDIUM"


def test_all_clear_returns_high():
    """No issues -> returns HIGH (Claude's assessment)."""
    conf, reason = _call(issues=[{"certainty_level": "CERTAIN"}])
    assert conf == "HIGH"


def test_governing_norm_takes_priority_over_conditional():
    """Rule 3.5 (LOW) fires before Rule 4 (MEDIUM cap)."""
    conf, reason = _call(
        governing_norm_incomplete=True,
        issues=[{"certainty_level": "CONDITIONAL"}],
    )
    assert conf == "LOW"
