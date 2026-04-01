"""Tests for tiered article context in _build_step7_context."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _build_step7_context


def _make_tiered_state():
    return {
        "question_type": "B", "legal_domain": "corporate",
        "output_mode": "compliance", "core_issue": "Test",
        "governing_norm_incomplete": False,
        "facts": {},
        "rl_rap_output": {
            "issues": [{
                "issue_id": "ISSUE-1", "issue_label": "Test",
                "certainty_level": "CERTAIN",
                "operative_articles": [{"article_ref": "Legea 31/1990 art.72"}],
                "condition_table": [], "conclusion": "Test",
                "subsumption_summary": {},
                "temporal_applicability": {"version_matches": True, "temporal_risks": []},
                "governing_norm_status": {"status": "PRESENT"},
                "uncertainty_sources": [], "missing_facts": [],
            }]
        },
        "retrieved_articles": [
            {"article_id": 1, "article_number": "72", "law_number": "31",
             "law_year": "1990", "law_title": "Legea societatilor",
             "date_in_force": "2025-12-18",
             "text": "Full text of article 72 about administrator duties " * 20},
            {"article_id": 2, "article_number": "798", "law_number": "287",
             "law_year": "2009", "law_title": "Codul Civil",
             "date_in_force": "2025-12-19",
             "text": "Full text of article 798 about civil administration " * 20},
            {"article_id": 99, "article_number": "999", "law_number": "1",
             "law_year": "2000", "law_title": "Other Law",
             "date_in_force": "2025-01-01",
             "text": "This tier 3 text should NOT appear in full " * 20},
        ],
        "issue_articles": {"ISSUE-1": [
            {"article_id": 1, "article_number": "72", "law_number": "31", "law_year": "1990"},
            {"article_id": 2, "article_number": "798", "law_number": "287", "law_year": "2009"},
        ]},
        "issue_versions": {}, "fact_version_map": {},
        "legal_issues": [{"issue_id": "ISSUE-1", "applicable_laws": [], "relevant_date": "2026-03-31", "temporal_rule": "act_date"}],
        "flags": [],
    }


def test_operative_articles_have_full_text():
    """Tier 1 (operative) articles should have full text in context."""
    state = _make_tiered_state()
    ctx = _build_step7_context(state)
    assert "ARTICOLE RELEVANTE" in ctx
    assert "Full text of article 72" in ctx


def test_tier2_articles_abbreviated():
    """Tier 2 articles should be abbreviated."""
    state = _make_tiered_state()
    ctx = _build_step7_context(state)
    assert "ARTICOLE SUPLIMENTARE" in ctx
    # Should have a preview, not the full repeated text
    assert "..." in ctx


def test_tier3_articles_reference_only():
    """Tier 3 articles should appear as reference only (no full text)."""
    state = _make_tiered_state()
    ctx = _build_step7_context(state)
    assert "ALTE ARTICOLE" in ctx
    assert "Art. 999" in ctx
    assert "This tier 3 text should NOT appear in full" not in ctx
