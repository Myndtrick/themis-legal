"""Tests for centralized confidence derivation."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _derive_final_confidence


def test_no_articles_returns_low():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[],
        has_articles=False,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 0},
    )
    assert conf == "LOW"
    assert "articles" in reason.lower()


def test_majority_citations_unverified_returns_low():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[{"certainty_level": "CERTAIN"}],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 5, "total_db": 8},
    )
    assert conf == "LOW"
    assert "citation" in reason.lower()


def test_uncertain_issue_returns_low():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[
            {"certainty_level": "CERTAIN"},
            {"certainty_level": "UNCERTAIN"},
        ],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "LOW"


def test_conditional_issue_caps_at_medium():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[
            {"certainty_level": "CERTAIN"},
            {"certainty_level": "CONDITIONAL"},
        ],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "MEDIUM"


def test_primary_not_from_db_caps_at_medium():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[{"certainty_level": "CERTAIN"}],
        has_articles=True,
        primary_from_db=False,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "MEDIUM"


def test_missing_primary_caps_at_medium():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[{"certainty_level": "CERTAIN"}],
        has_articles=True,
        primary_from_db=True,
        missing_primary=True,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "MEDIUM"


def test_stale_versions_caps_at_medium():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[{"certainty_level": "CERTAIN"}],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=True,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "MEDIUM"


def test_all_clear_uses_claude_confidence():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[{"certainty_level": "CERTAIN"}],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "HIGH"


def test_claude_says_low_respected():
    conf, reason = _derive_final_confidence(
        claude_confidence="LOW",
        rl_rap_issues=[{"certainty_level": "CERTAIN"}],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "LOW"


def test_probable_maps_to_high():
    conf, _ = _derive_final_confidence(
        claude_confidence="MEDIUM",
        rl_rap_issues=[{"certainty_level": "PROBABLE"}],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "MEDIUM"


def test_empty_rl_rap_issues_no_cap():
    conf, _ = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "HIGH"


def test_priority_order_low_beats_medium():
    conf, _ = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[{"certainty_level": "UNCERTAIN"}],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=True,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "LOW"
