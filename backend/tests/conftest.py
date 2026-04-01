"""Shared fixtures for pipeline tests."""
import pytest


@pytest.fixture
def mock_state_simple():
    """State dict after Step 1 for a SIMPLE query."""
    return {
        "question": "Care este capitalul social minim pentru un SRL?",
        "session_context": [],
        "run_id": "test_run_001",
        "flags": [],
        "today": "2026-03-26",
        "question_type": "A",
        "complexity": "SIMPLE",
        "legal_domain": "corporate",
        "output_mode": "qa",
        "core_issue": "Capitalul social minim SRL",
        "primary_target": None,
        "sub_issues": [],
        "entity_types": ["SRL"],
        "applicable_laws": [
            {"law_number": "31", "law_year": "1990", "title": "Legea societatilor", "role": "PRIMARY"}
        ],
        "events": [],
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "description": "Minimum share capital for SRL",
                "relevant_date": "2026-03-26",
                "temporal_rule": "current_law",
                "applicable_laws": ["31/1990"],
            }
        ],
        "law_date_map": {"31/1990": "2026-03-26"},
        "primary_date": "2026-03-26",
    }


@pytest.fixture
def mock_state_standard():
    """State dict after Step 1 for a STANDARD query with facts."""
    return {
        "question": "Un administrator al unui SRL a acordat un imprumut de 50000 EUR societatii fara aprobarea AGA. Este valid actul?",
        "session_context": [],
        "run_id": "test_run_002",
        "flags": [],
        "today": "2026-03-26",
        "question_type": "B",
        "complexity": "STANDARD",
        "legal_domain": "corporate",
        "output_mode": "qa",
        "core_issue": "Validitatea actului juridic administrator-societate",
        "primary_target": {
            "actor": "administrator",
            "concern": "validity of transaction",
            "issue_id": "ISSUE-1",
            "reasoning": "User asks about the validity of the administrator's act",
        },
        "sub_issues": [],
        "entity_types": ["SRL"],
        "applicable_laws": [
            {"law_number": "31", "law_year": "1990", "title": "Legea societatilor", "role": "PRIMARY"}
        ],
        "events": [
            {"event": "Administrator loans 50000 EUR to company", "date": "2025-01-01", "date_source": "explicit"}
        ],
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "description": "Validity of administrator-company transaction without AGA approval",
                "relevant_date": "2025-01-01",
                "temporal_rule": "contract_formation",
                "applicable_laws": ["31/1990"],
                "priority": "PRIMARY",
                "priority_reasoning": "Direct question about transaction validity",
            }
        ],
        "facts": {
            "stated": [
                {"fact_id": "F1", "description": "Administrator loaned 50000 EUR to company", "date": "2025-01-01", "legal_category": "related_party_transaction"},
                {"fact_id": "F2", "description": "No AGA approval obtained", "date": None, "legal_category": "corporate_governance"},
            ],
            "assumed": [
                {"fact_id": "F3", "description": "Company is an SRL registered in Romania", "basis": "user mentions administrator and SRL"}
            ],
            "missing": [
                {"fact_id": "F5", "description": "Whether the loan was in the ordinary course of business", "relevance": "May trigger exception under art.197(4)"}
            ],
        },
        "law_date_map": {"31/1990": "2025-01-01"},
        "primary_date": "2025-01-01",
    }


@pytest.fixture
def mock_articles():
    """A set of mock articles with metadata for testing."""
    return [
        {
            "article_id": 101,
            "article_number": "197",
            "law_number": "31",
            "law_year": "1990",
            "law_title": "Legea societatilor",
            "law_version_id": 10,
            "date_in_force": "2024-11-15",
            "text": "Art. 197 (3) Administratorul nu poate incheia acte juridice cu societatea...",
            "source": "bm25",
            "tier": "tier1_primary",
            "role": "PRIMARY",
            "bm25_rank": -2.5,
            "is_abrogated": False,
            "doc_type": "article",
            "reranker_score": 5.2,
        },
        {
            "article_id": 102,
            "article_number": "72",
            "law_number": "31",
            "law_year": "1990",
            "law_title": "Legea societatilor",
            "law_version_id": 10,
            "date_in_force": "2024-11-15",
            "text": "Art. 72 Obligatiile si raspunderea administratorilor sunt reglementate...",
            "source": "semantic",
            "tier": "tier1_primary",
            "role": "PRIMARY",
            "distance": 0.35,
            "is_abrogated": False,
            "doc_type": "article",
            "reranker_score": 4.1,
        },
        {
            "article_id": 201,
            "article_number": "169",
            "law_number": "85",
            "law_year": "2014",
            "law_title": "Legea insolventei",
            "law_version_id": 20,
            "date_in_force": "2026-01-15",
            "text": "Art. 169 (1) In cazul in care in raportul intocmit...",
            "source": "bm25",
            "tier": "tier1_primary",
            "role": "PRIMARY",
            "bm25_rank": -3.1,
            "is_abrogated": False,
            "doc_type": "article",
            "reranker_score": 3.8,
        },
        {
            "article_id": 301,
            "article_number": "1357",
            "law_number": "287",
            "law_year": "2009",
            "law_title": "Codul Civil",
            "law_version_id": 30,
            "date_in_force": "2023-06-01",
            "text": "Art. 1357 (1) Cel care cauzeaza altuia un prejudiciu...",
            "source": "semantic",
            "tier": "tier2_secondary",
            "role": "SECONDARY",
            "distance": 0.45,
            "is_abrogated": False,
            "doc_type": "article",
            "reranker_score": 2.1,
        },
    ]


@pytest.fixture
def mock_issue_versions():
    """issue_versions mapping from Step 3."""
    return {
        "ISSUE-1:31/1990": {
            "law_version_id": 10,
            "law_id": 1,
            "issue_id": "ISSUE-1",
            "law_key": "31/1990",
            "relevant_date": "2025-01-01",
            "date_in_force": "2024-11-15",
            "is_current": False,
            "temporal_rule": "contract_formation",
        },
    }


@pytest.fixture
def mock_rl_rap_output():
    """Sample RL-RAP Step 6.8 output."""
    return {
        "issues": [
            {
                "issue_id": "ISSUE-1",
                "issue_label": "Validity of administrator-company transaction",
                "operative_articles": [
                    {
                        "article_ref": "Legea 31/1990 art.197 alin.(3)",
                        "law_version_id": 10,
                        "norm_type": "RULE",
                        "disposition": {
                            "modality": "PROHIBITION",
                            "text": "Administratorul nu poate incheia acte juridice cu societatea fara aprobarea AGA"
                        },
                        "sanction": {"explicit": True, "text": "Nulitatea actului"},
                    }
                ],
                "decomposed_conditions": [
                    {
                        "condition_id": "C1",
                        "norm_ref": "Legea 31/1990 art.197 alin.(3)",
                        "condition_text": "Act juridic intre administrator si societate",
                        "list_type": None,
                        "condition_status": "SATISFIED",
                        "supporting_fact_ids": ["F1"],
                        "missing_facts": [],
                    },
                    {
                        "condition_id": "C2",
                        "norm_ref": "Legea 31/1990 art.197 alin.(3)",
                        "condition_text": "Aprobarea AGA nu a fost obtinuta",
                        "list_type": None,
                        "condition_status": "SATISFIED",
                        "supporting_fact_ids": ["F2"],
                        "missing_facts": [],
                    },
                ],
                "exceptions_checked": [
                    {
                        "exception_ref": "Legea 31/1990 art.197 alin.(4)",
                        "type": "INLINE_EXCEPTION",
                        "condition_status_summary": "UNKNOWN",
                        "impact": "Exception for ordinary course transactions",
                        "missing_facts": ["Whether the loan was in the ordinary course of business"],
                    }
                ],
                "temporal_applicability": {
                    "relevant_event_date": "2025-01-01",
                    "version_matches": True,
                    "temporal_risks": [],
                },
                "conclusion": "Art. 197(3) likely applies. Transaction without AGA approval is voidable, unless ordinary course exception applies.",
                "certainty_level": "CONDITIONAL",
                "missing_facts": ["Whether the loan was in the ordinary course of business"],
                "missing_articles_needed": [],
            }
        ]
    }
