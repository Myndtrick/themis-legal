"""Tests for Step 6.8 output parser with new fields and backward compatibility."""
from app.services.pipeline_service import _parse_step6_8_output


def test_parse_with_all_new_fields():
    """Parser accepts output with governing_norm_status, condition_table, uncertainty_sources."""
    raw = '''{
        "issues": [{
            "issue_id": "ISSUE-1",
            "issue_label": "Test issue",
            "governing_norm_status": {
                "status": "PRESENT",
                "explanation": "Art. 197 is the governing norm"
            },
            "operative_articles": [],
            "condition_table": [
                {"condition_id": "C1", "norm_ref": "art.197", "condition_text": "test",
                 "source": "HYPOTHESIS", "list_type": null, "list_group": null,
                 "status": "SATISFIED", "evidence": "F1: fact", "missing_fact": null}
            ],
            "subsumption_summary": {
                "total_conditions": 1, "satisfied": 1, "not_satisfied": 0,
                "unknown": 0, "norm_applicable": "YES", "blocking_unknowns": []
            },
            "uncertainty_sources": [],
            "conclusion": "Norm applies.",
            "certainty_level": "CERTAIN",
            "missing_facts": [],
            "missing_articles_needed": []
        }]
    }'''
    result = _parse_step6_8_output(raw)
    assert result is not None
    issue = result["issues"][0]
    assert issue["governing_norm_status"]["status"] == "PRESENT"
    assert len(issue["condition_table"]) == 1
    assert issue["subsumption_summary"]["norm_applicable"] == "YES"
    assert issue["uncertainty_sources"] == []


def test_parse_old_format_gets_defaults():
    """Parser provides defaults for missing new fields (backward compat)."""
    raw = '''{
        "issues": [{
            "issue_id": "ISSUE-1",
            "issue_label": "Test issue",
            "operative_articles": [],
            "decomposed_conditions": [
                {"condition_id": "C1", "norm_ref": "art.197",
                 "condition_text": "test", "condition_status": "SATISFIED",
                 "supporting_fact_ids": ["F1"], "missing_facts": []}
            ],
            "conclusion": "Norm applies.",
            "certainty_level": "CERTAIN",
            "missing_facts": [],
            "missing_articles_needed": []
        }]
    }'''
    result = _parse_step6_8_output(raw)
    assert result is not None
    issue = result["issues"][0]
    assert issue["governing_norm_status"] == {"status": "PRESENT"}
    assert issue["uncertainty_sources"] == []
    assert "decomposed_conditions" in issue


def test_parse_missing_governing_norm():
    """Parser preserves MISSING governing_norm_status."""
    raw = '''{
        "issues": [{
            "issue_id": "ISSUE-1",
            "issue_label": "Test",
            "governing_norm_status": {
                "status": "MISSING",
                "explanation": "Art. 169 not in provided articles",
                "expected_norm_description": "Administrator liability provision",
                "missing_norm_ref": "Legea 85/2014 art.169"
            },
            "operative_articles": [],
            "condition_table": [],
            "subsumption_summary": {
                "total_conditions": 0, "satisfied": 0, "not_satisfied": 0,
                "unknown": 0, "norm_applicable": "NO", "blocking_unknowns": []
            },
            "conclusion": "Analysis incomplete.",
            "certainty_level": "UNCERTAIN",
            "uncertainty_sources": [
                {"type": "LIBRARY_GAP", "detail": "Art. 169 missing",
                 "impact": "Cannot assess liability", "resolvable_by": "ARTICLE_IMPORT"}
            ],
            "missing_facts": [],
            "missing_articles_needed": ["Legea 85/2014 art.169"]
        }]
    }'''
    result = _parse_step6_8_output(raw)
    assert result is not None
    issue = result["issues"][0]
    assert issue["governing_norm_status"]["status"] == "MISSING"
    assert issue["governing_norm_status"]["missing_norm_ref"] == "Legea 85/2014 art.169"
    assert issue["uncertainty_sources"][0]["type"] == "LIBRARY_GAP"
