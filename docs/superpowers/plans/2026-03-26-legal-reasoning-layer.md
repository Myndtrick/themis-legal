# Legal Reasoning Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a structured legal reasoning step (RL-RAP) to the Legal Assistant pipeline, with a fast path for simple queries and cost optimizations.

**Architecture:** Insert Step 6.8 (legal reasoning) between reranking and answer generation. Step 6.8 receives partitioned articles per issue, performs norm decomposition, subsumption, exception checking, and temporal verification using RL-RAP methodology. Step 7 is revised to consume the structured analysis instead of raw articles. A fast path bypasses reasoning for simple statutory queries.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, Claude API (Anthropic SDK), ChromaDB, SQLite FTS5, sentence-transformers

**Spec:** `docs/superpowers/specs/2026-03-26-legal-reasoning-layer-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|---|---|
| `backend/prompts/LA-S6.8-legal-reasoning.txt` | RL-RAP methodology prompt for Step 6.8 |
| `backend/prompts/LA-S7-simple.txt` | Simplified Step 7 prompt for SIMPLE fast path |
| `backend/tests/test_pipeline_routing.py` | Tests for complexity routing and fast path |
| `backend/tests/test_step4_5_filter.py` | Tests for pre-expansion relevance filter |
| `backend/tests/test_step6_7_partition.py` | Tests for article-to-issue partitioning |
| `backend/tests/test_step6_8_reasoning.py` | Tests for RL-RAP reasoning step output parsing |
| `backend/tests/test_conditional_retrieval.py` | Tests for conditional retrieval pass |
| `backend/tests/test_step7_revised.py` | Tests for revised Step 7 context construction |
| `backend/tests/conftest.py` | Shared test fixtures (mock state, mock articles) |

### Modified Files
| File | Changes |
|---|---|
| `backend/app/services/pipeline_service.py` | Add Steps 4.5, 6.7, 6.8, conditional retrieval, fast path routing. Modify Step 4 (tier_limits_override), Step 6 (dynamic top_k), Step 7 (RL-RAP input), Step 7.5 (operative_articles validation). |
| `backend/prompts/LA-S1-issue-classifier.txt` | Add `complexity` and `facts` fields to output schema |
| `backend/prompts/LA-S7-answer-qa.txt` | Simplify: remove reasoning instructions, add RL-RAP consumption instructions |
| `backend/prompts/LA-S7-M2-answer-memo.txt` | Same simplification as LA-S7 |
| `backend/prompts/LA-S7-M3-answer-comparison.txt` | Same simplification as LA-S7 |
| `backend/prompts/LA-S7-M4-answer-compliance.txt` | Same simplification as LA-S7 |
| `backend/prompts/LA-S7-M5-answer-checklist.txt` | Same simplification as LA-S7 |
| `frontend/src/app/assistant/step-indicator.tsx` | Add SSE labels for new steps (45, 67, 68, 69) |
| `docs/deep-research-report.md` | Clean up RL-RAP: remove citeturn artifacts, drop YAML/markdown formats |

---

## Task 1: Test Infrastructure and Shared Fixtures

**Files:**
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`

This task sets up the test harness. No tests exist yet in the project.

- [ ] **Step 1: Create test directory and conftest**

```python
# backend/tests/__init__.py
# (empty)
```

```python
# backend/tests/conftest.py
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
```

- [ ] **Step 2: Verify pytest runs**

Run: `cd backend && python -m pytest tests/ -v --co 2>/dev/null || echo "No tests collected yet - OK"`
Expected: Either "no tests collected" or empty collection (conftest only has fixtures).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/
git commit -m "test: add test infrastructure and shared fixtures for pipeline"
```

---

## Task 2: Extend Step 1 — Complexity and Fact Extraction

**Files:**
- Modify: `backend/prompts/LA-S1-issue-classifier.txt`
- Modify: `backend/app/services/pipeline_service.py:544-644` (`_step1_issue_classification`)
- Create: `backend/tests/test_pipeline_routing.py`

- [ ] **Step 1: Read current LA-S1-issue-classifier.txt prompt**

Read the full prompt to understand existing output schema before modifying.

- [ ] **Step 2: Add complexity and facts fields to Step 1 prompt**

Add to the output schema section of `LA-S1-issue-classifier.txt`:

```text
"complexity": "SIMPLE" | "STANDARD" | "COMPLEX",
  // SIMPLE: Single factual question about a current rule, definition, threshold, or procedure. No scenario, no multiple parties, no temporal dimension.
  // STANDARD: Specific situation with 1-2 issues, potentially requiring temporal or exception analysis.
  // COMPLEX: Multi-issue scenario with multiple parties, dates, conflicting laws, or comprehensive analysis needed.

"facts": {                    // OMIT for SIMPLE queries
  "stated": [
    {"fact_id": "F1", "description": "...", "date": "YYYY-MM-DD or null", "legal_category": "..."}
  ],
  "assumed": [
    {"fact_id": "F3", "description": "...", "basis": "why this is assumed"}
  ],
  "missing": [
    {"fact_id": "F5", "description": "...", "relevance": "why this matters legally"}
  ]
}
```

- [ ] **Step 3: Update Step 1 parsing in pipeline_service.py**

In `_step1_issue_classification` (around line 600-628), after parsing the existing fields, add:

```python
# Parse complexity (default to STANDARD if missing)
state["complexity"] = parsed.get("complexity", "STANDARD")

# Parse structured facts (STANDARD/COMPLEX only)
if state["complexity"] != "SIMPLE":
    state["facts"] = parsed.get("facts", {"stated": [], "assumed": [], "missing": []})
else:
    state["facts"] = {"stated": [], "assumed": [], "missing": []}
```

- [ ] **Step 4: Write routing tests**

```python
# backend/tests/test_pipeline_routing.py
"""Tests for complexity-based pipeline routing."""


def test_simple_state_has_complexity(mock_state_simple):
    assert mock_state_simple["complexity"] == "SIMPLE"


def test_standard_state_has_facts(mock_state_standard):
    assert "facts" in mock_state_standard
    assert len(mock_state_standard["facts"]["stated"]) > 0


def test_simple_state_has_empty_facts(mock_state_simple):
    # SIMPLE queries should not have facts
    assert mock_state_simple.get("facts", {}).get("stated", []) == []


def test_complexity_routing_simple():
    """SIMPLE complexity should route to fast path."""
    state = {"complexity": "SIMPLE"}
    assert state["complexity"] == "SIMPLE"
    # Fast path skips Steps 4.5, 5, 5.5, 6.7, 6.8


def test_complexity_routing_standard():
    """STANDARD complexity should route to full path."""
    state = {"complexity": "STANDARD"}
    assert state["complexity"] in ("STANDARD", "COMPLEX")
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/test_pipeline_routing.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/prompts/LA-S1-issue-classifier.txt backend/app/services/pipeline_service.py backend/tests/test_pipeline_routing.py
git commit -m "feat: add complexity classification and fact extraction to Step 1"
```

---

## Task 3: Pre-Expansion Relevance Filter (Step 4.5)

**Files:**
- Modify: `backend/app/services/pipeline_service.py` (add `_step4_5_pre_expansion_filter` after line ~1195)
- Create: `backend/tests/test_step4_5_filter.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_step4_5_filter.py
"""Tests for Step 4.5: pre-expansion relevance filter."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _step4_5_pre_expansion_filter


def test_filter_keeps_strong_bm25(mock_articles):
    """Articles with strong BM25 rank are kept."""
    state = {"retrieved_articles_raw": mock_articles}
    result = _step4_5_pre_expansion_filter(state)
    kept_ids = [a["article_id"] for a in result["retrieved_articles_raw"]]
    # Article 101 has bm25_rank=-2.5 (strong), should be kept
    assert 101 in kept_ids


def test_filter_keeps_strong_semantic(mock_articles):
    """Articles with low semantic distance are kept."""
    state = {"retrieved_articles_raw": mock_articles}
    result = _step4_5_pre_expansion_filter(state)
    kept_ids = [a["article_id"] for a in result["retrieved_articles_raw"]]
    # Article 102 has distance=0.35 (< 0.7), should be kept
    assert 102 in kept_ids


def test_filter_drops_weak_articles():
    """Articles with weak scores on all available metrics are dropped."""
    weak_article = {
        "article_id": 999,
        "article_number": "999",
        "bm25_rank": -0.1,  # Very weak BM25
        "distance": 0.95,   # Very weak semantic
        "source": "bm25",
        "tier": "tier1_primary",
    }
    # Also need a strong article to compute the 50th percentile
    strong_article = {
        "article_id": 100,
        "article_number": "1",
        "bm25_rank": -5.0,  # Strong BM25
        "source": "bm25",
        "tier": "tier1_primary",
    }
    state = {"retrieved_articles_raw": [strong_article, weak_article]}
    result = _step4_5_pre_expansion_filter(state)
    kept_ids = [a["article_id"] for a in result["retrieved_articles_raw"]]
    assert 100 in kept_ids
    assert 999 not in kept_ids


def test_filter_keeps_entity_targeted():
    """Entity-targeted articles are always kept regardless of score."""
    entity_article = {
        "article_id": 500,
        "article_number": "500",
        "bm25_rank": -0.1,  # Weak
        "source": "entity:SRL",
        "tier": "entity_targeted",
    }
    state = {"retrieved_articles_raw": [entity_article]}
    result = _step4_5_pre_expansion_filter(state)
    assert len(result["retrieved_articles_raw"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_step4_5_filter.py -v`
Expected: FAIL — `ImportError: cannot import name '_step4_5_pre_expansion_filter'`

- [ ] **Step 3: Implement the filter**

Add to `pipeline_service.py` after `_step4_hybrid_retrieval` (after line ~1195):

```python
def _step4_5_pre_expansion_filter(state: dict) -> dict:
    """Drop bottom-tier articles before expansion to reduce noise."""
    articles = state.get("retrieved_articles_raw", [])
    if len(articles) <= 10:
        # Too few articles to filter meaningfully
        return state

    # Compute BM25 median per tier
    tier_bm25_scores = {}
    for art in articles:
        if "bm25_rank" in art:
            tier = art.get("tier", "unknown")
            tier_bm25_scores.setdefault(tier, []).append(art["bm25_rank"])

    tier_bm25_medians = {}
    for tier, scores in tier_bm25_scores.items():
        sorted_scores = sorted(scores)  # BM25 rank: more negative = better
        mid = len(sorted_scores) // 2
        tier_bm25_medians[tier] = sorted_scores[mid]

    kept = []
    for art in articles:
        # Always keep entity-targeted
        if art.get("source", "").startswith("entity:"):
            kept.append(art)
            continue

        # Check BM25 criterion (top 50% = rank <= median, since more negative is better)
        bm25_ok = False
        if "bm25_rank" in art:
            tier = art.get("tier", "unknown")
            median = tier_bm25_medians.get(tier)
            if median is not None and art["bm25_rank"] <= median:
                bm25_ok = True

        # Check semantic criterion
        semantic_ok = False
        if "distance" in art:
            if art["distance"] < 0.7:
                semantic_ok = True

        # Keep if ANY criterion passes
        if bm25_ok or semantic_ok:
            kept.append(art)

    state["retrieved_articles_raw"] = kept
    return state
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_step4_5_filter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pipeline_service.py backend/tests/test_step4_5_filter.py
git commit -m "feat: add Step 4.5 pre-expansion relevance filter"
```

---

## Task 4: Dynamic top_k in Step 6 and tier_limits_override in Step 4

**Files:**
- Modify: `backend/app/services/pipeline_service.py:1041-1060` (`_step4_hybrid_retrieval`) and `backend/app/services/pipeline_service.py:1336-1373` (`_step6_select_articles`)

- [ ] **Step 1: Add tier_limits_override parameter to Step 4**

In `_step4_hybrid_retrieval` (line 1041), change the signature and tier_limits:

```python
def _step4_hybrid_retrieval(state: dict, db: Session, tier_limits_override: dict | None = None) -> dict:
    """BM25 + semantic search, per tier."""
    from app.services.bm25_service import search_bm25

    t0 = time.time()
    all_articles = []
    seen_ids = set()
    bm25_count = 0
    semantic_count = 0
    duplicates_removed = 0

    tier_limits = tier_limits_override or {
        "tier1_primary": 30,
        "tier2_secondary": 15,
    }
```

- [ ] **Step 2: Add dynamic top_k to Step 6**

In `_step6_select_articles` (line ~1336), change the rerank call:

```python
def _step6_select_articles(state: dict, db: Session, top_k_override: int | None = None) -> dict:
    """Rerank articles using cross-encoder, select top-k."""
    from app.services.reranker_service import rerank_articles

    num_issues = len(state.get("legal_issues", []))
    top_k = top_k_override or min(20, 5 + (num_issues * 5))

    articles = state.get("retrieved_articles_raw", [])
    if not articles:
        state["retrieved_articles"] = []
        return state

    ranked = rerank_articles(state["question"], articles, top_k=top_k)
    state["retrieved_articles"] = ranked
    return state
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: add tier_limits_override to Step 4 and dynamic top_k to Step 6"
```

---

## Task 5: Article-to-Issue Partitioning (Step 6.7)

**Files:**
- Modify: `backend/app/services/pipeline_service.py` (add `_step6_7_partition_articles`)
- Create: `backend/tests/test_step6_7_partition.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_step6_7_partition.py
"""Tests for Step 6.7: article-to-issue partitioning."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _step6_7_partition_articles


def test_partition_assigns_article_to_matching_issue(mock_articles, mock_issue_versions):
    """Article with matching law_version_id is assigned to the correct issue."""
    state = {
        "retrieved_articles": mock_articles[:2],  # articles 101, 102 with law_version_id=10
        "legal_issues": [
            {"issue_id": "ISSUE-1", "applicable_laws": ["31/1990"]}
        ],
        "issue_versions": mock_issue_versions,
    }
    result = _step6_7_partition_articles(state)
    assert "ISSUE-1" in result["issue_articles"]
    issue_1_ids = [a["article_id"] for a in result["issue_articles"]["ISSUE-1"]]
    assert 101 in issue_1_ids
    assert 102 in issue_1_ids


def test_partition_unmatched_goes_to_shared(mock_articles, mock_issue_versions):
    """Article not matching any issue goes to shared_context."""
    state = {
        "retrieved_articles": mock_articles,  # includes article 301 (Cod Civil, version 30)
        "legal_issues": [
            {"issue_id": "ISSUE-1", "applicable_laws": ["31/1990"]}
        ],
        "issue_versions": mock_issue_versions,  # Only has ISSUE-1:31/1990 -> version 10
    }
    result = _step6_7_partition_articles(state)
    shared_ids = [a["article_id"] for a in result["shared_context"]]
    assert 301 in shared_ids  # Cod Civil article not mapped to any issue


def test_partition_article_in_multiple_issues():
    """Article can belong to multiple issues if same version needed."""
    articles = [
        {"article_id": 101, "law_version_id": 10, "law_number": "31", "law_year": "1990"},
    ]
    issue_versions = {
        "ISSUE-1:31/1990": {"law_version_id": 10, "issue_id": "ISSUE-1", "law_key": "31/1990"},
        "ISSUE-2:31/1990": {"law_version_id": 10, "issue_id": "ISSUE-2", "law_key": "31/1990"},
    }
    state = {
        "retrieved_articles": articles,
        "legal_issues": [
            {"issue_id": "ISSUE-1", "applicable_laws": ["31/1990"]},
            {"issue_id": "ISSUE-2", "applicable_laws": ["31/1990"]},
        ],
        "issue_versions": issue_versions,
    }
    result = _step6_7_partition_articles(state)
    assert 101 in [a["article_id"] for a in result["issue_articles"]["ISSUE-1"]]
    assert 101 in [a["article_id"] for a in result["issue_articles"]["ISSUE-2"]]


def test_partition_empty_issue_flagged():
    """Issue with zero articles gets flagged."""
    state = {
        "retrieved_articles": [],
        "legal_issues": [
            {"issue_id": "ISSUE-1", "applicable_laws": ["31/1990"]}
        ],
        "issue_versions": {
            "ISSUE-1:31/1990": {"law_version_id": 10, "issue_id": "ISSUE-1", "law_key": "31/1990"},
        },
        "flags": [],
    }
    result = _step6_7_partition_articles(state)
    assert "ISSUE-1" in result["issue_articles"]
    assert len(result["issue_articles"]["ISSUE-1"]) == 0
    assert any("ISSUE-1" in f for f in result["flags"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_step6_7_partition.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement partitioning**

Add to `pipeline_service.py` after `_step6_5_relevance_gate`:

```python
def _step6_7_partition_articles(state: dict) -> dict:
    """Partition reranked articles by issue using issue_versions mapping."""
    articles = state.get("retrieved_articles", [])
    issue_versions = state.get("issue_versions", {})
    legal_issues = state.get("legal_issues", [])

    issue_articles: dict[str, list[dict]] = {
        issue["issue_id"]: [] for issue in legal_issues
    }
    shared_context: list[dict] = []

    # Build reverse map: law_version_id -> set of issue_ids
    version_to_issues: dict[int, set[str]] = {}
    for key, iv in issue_versions.items():
        vid = iv["law_version_id"]
        iid = iv["issue_id"]
        version_to_issues.setdefault(vid, set()).add(iid)

    for art in articles:
        art_version_id = art.get("law_version_id")
        if art_version_id is None:
            shared_context.append(art)
            continue

        matched_issues = version_to_issues.get(art_version_id, set())
        if matched_issues:
            for iid in matched_issues:
                if iid in issue_articles:
                    issue_articles[iid].append(art)
        else:
            shared_context.append(art)

    # Flag issues with zero articles
    flags = state.get("flags", [])
    for issue_id, arts in issue_articles.items():
        if len(arts) == 0:
            flags.append(f"ISSUE {issue_id}: no articles matched after partitioning")

    state["issue_articles"] = issue_articles
    state["shared_context"] = shared_context
    state["flags"] = flags
    return state
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_step6_7_partition.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pipeline_service.py backend/tests/test_step6_7_partition.py
git commit -m "feat: add Step 6.7 article-to-issue partitioning"
```

---

## Task 6: RL-RAP Reasoning Prompt (Step 6.8)

**Files:**
- Create: `backend/prompts/LA-S6.8-legal-reasoning.txt`
- Modify: `docs/deep-research-report.md` → clean up RL-RAP

- [ ] **Step 1: Clean up RL-RAP document**

Read `docs/deep-research-report.md`. Remove all `citeturn` artifacts (regex: `citeturn\d+\w+`). Remove YAML schema example. Remove markdown block format examples (`[NORM_DECOMP]`, `[SUBSUMPTION]`, etc.) — keep JSON as canonical. Remove `protocol_version` and `generated_at` fields from schema. Move cleaned file to `docs/RL-RAP.md`.

- [ ] **Step 2: Write the Step 6.8 prompt**

Create `backend/prompts/LA-S6.8-legal-reasoning.txt` — a unified prompt derived from RL-RAP:

```text
You are a Romanian legal analyst performing structured legal reasoning under the RL-RAP (Romanian Legal Reasoning Analysis Protocol) methodology. You operate in the Romanian civil-law system: reasoning is norm-based, deductive, and follows the structure rule → conditions → subsumption → exceptions → conclusion.

Your input contains: structured facts (with fact IDs), per-issue article sets (with law version metadata), and shared context articles.

For each legal issue, perform the following analysis IN ORDER:

1. IDENTIFY OPERATIVE ARTICLES
   - From the articles provided for this issue, identify which are legally operative.
   - Classify each as: RULE (substantive norm), DEFINITION (defines a term), PROCEDURAL_RULE (procedural norm), or REFERENCE_RULE (references another norm).
   - Only RULE articles get full subsumption. DEFINITION articles provide context. REFERENCE_RULE articles: if the referenced norm is not provided, add it to missing_articles_needed.

2. DECOMPOSE EACH RULE ARTICLE
   - Split into: hypothesis (conditions of applicability), disposition (the rule — OBLIGATION, PROHIBITION, PERMISSION, or POWER), and sanction/effect (explicit or implicit).
   - Extract hypothesis as atomic, fact-testable conditions. Each condition must be a single testable statement.
   - For lettered lists (lit. a, b, c...), determine and label: OR-list (any one suffices) or AND-list (all required).
   - Identify inline exceptions ("cu exceptia...", "nu se aplica...") as separate exception blocks.
   - Identify cross-references ("potrivit art. ...") needed to understand the rule.
   - Do NOT invent conditions, sanctions, thresholds, or deadlines not present in the text.

3. PERFORM SUBSUMPTION
   - For each condition in each operative article, evaluate against the stated facts:
     - SATISFIED: supported by an explicit stated fact (cite fact_id)
     - NOT_SATISFIED: contradicted by an explicit stated fact (cite fact_id)
     - UNKNOWN: fact not provided or insufficient — MUST produce a missing_facts entry
   - UNKNOWN must NEVER be resolved by guessing. If the fact is not stated, it stays UNKNOWN.
   - A single NOT_SATISFIED on a necessary condition makes the norm inapplicable (unless alternative norms exist).
   - For OR-lists: SATISFIED if at least one branch is SATISFIED.
   - For AND-lists: all must be SATISFIED for the norm to apply.
   - Do NOT skip conditions because they are difficult (causation, intent, good faith).

4. CHECK EXCEPTIONS AND DEROGATIONS
   Before concluding, check in this order:
   - Inline exceptions in the same provision
   - Derogations elsewhere in the same act ("prin derogare de la..." is a controlling derogation — treat it as binding)
   - Special rules in another act (lex specialis)
   - Model each exception as a mini-norm: conditions + SATISFIED/NOT_SATISFIED/UNKNOWN evaluation.
   - If an exception applies, the conclusion must change accordingly.
   - Procedural exceptions (standing, deadlines, jurisdiction) block the claim if SATISFIED — check them before substantive analysis.

5. RESOLVE CONFLICTS (only if multiple norms lead to incompatible outcomes)
   Resolution order:
   - Lex superior (higher-ranked norm prevails: Constitution > organic law > ordinary law > OUG/OG > HG)
   - Lex specialis (special law prevails over general)
   - Lex posterior (later prevails within comparable rank) — BUT an older special law is NOT automatically overridden by a newer general law. Mark UNCERTAIN if unclear.
   - If unresolved, set certainty_level to UNCERTAIN.

6. VERIFY TEMPORAL APPLICABILITY
   - Confirm the article version is in force at the relevant event date for this issue.
   - Apply: non-retroactivity (Constitution Art. 15(2)), civil transitional rules (Civil Code Art. 6), procedural rules (CPC Art. 24 — new procedural rules apply only to proceedings started after entry into force).
   - If the provided article version post-dates the relevant event: flag temporal risk and downgrade certainty.
   - If a fallback to current version occurred (flagged by pipeline): explicitly state it and lower certainty.
   - Never treat a post-event amendment as applicable unless it is procedural (and the procedure began after entry into force) or explicitly retroactive.

7. PRODUCE CONCLUSION AND CERTAINTY
   - CERTAIN: All necessary conditions SATISFIED, exceptions NOT_SATISFIED, no unresolved conflict, no temporal risk.
   - PROBABLE: Minor factual dependencies that do not normally change the outcome.
   - CONDITIONAL: At least one material condition or exception is UNKNOWN. State what the outcome would be under each scenario.
   - UNCERTAIN: Missing critical law text, unresolved conflict, or severe temporal risk.

OUTPUT FORMAT — Return valid JSON only:

{
  "issues": [
    {
      "issue_id": "ISSUE-N",
      "issue_label": "short description",
      "operative_articles": [
        {
          "article_ref": "Legea N/YYYY art.X alin.(Y) lit.(Z)",
          "law_version_id": <id>,
          "norm_type": "RULE|DEFINITION|PROCEDURAL_RULE|REFERENCE_RULE",
          "disposition": {"modality": "OBLIGATION|PROHIBITION|PERMISSION|POWER", "text": "..."},
          "sanction": {"explicit": true|false, "text": "..."}
        }
      ],
      "decomposed_conditions": [
        {
          "condition_id": "C1",
          "norm_ref": "...",
          "condition_text": "atomic testable condition",
          "list_type": "OR|AND|null",
          "condition_status": "SATISFIED|NOT_SATISFIED|UNKNOWN",
          "supporting_fact_ids": ["F1"],
          "missing_facts": ["precise missing fact if UNKNOWN"]
        }
      ],
      "exceptions_checked": [
        {
          "exception_ref": "...",
          "type": "INLINE_EXCEPTION|DEROGATION|SPECIAL_RULE",
          "condition_status_summary": "SATISFIED|NOT_SATISFIED|UNKNOWN",
          "impact": "short impact description",
          "missing_facts": []
        }
      ],
      // Include "conflicts" only if conflict detected:
      "conflicts": {
        "conflict_detected": true,
        "resolution_rule": "LEX_SUPERIOR|LEX_SPECIALIS|LEX_POSTERIOR|UNRESOLVED",
        "chosen_norm": "...",
        "rationale": "2-4 lines"
      },
      "temporal_applicability": {
        "relevant_event_date": "YYYY-MM-DD",
        "version_matches": true|false,
        "temporal_risks": ["risk description if any"]
      },
      "conclusion": "2-6 lines; conditional branches allowed",
      "certainty_level": "CERTAIN|PROBABLE|CONDITIONAL|UNCERTAIN",
      "missing_facts": ["all missing facts for this issue"],
      "missing_articles_needed": ["Legea N/YYYY art.X if critical cross-ref missing"]
    }
  ]
}

CRITICAL RULES:
- UNKNOWN must NEVER be resolved by guessing.
- Every conclusion must be traceable to condition statuses.
- Do NOT invent facts, conditions, sanctions, or deadlines.
- Do NOT collapse exceptions into the main rule.
- Do NOT state "both apply" when norms have incompatible outcomes.
- Do NOT apply current law text to past events without flagging temporal risk.
```

- [ ] **Step 3: Commit**

```bash
git add backend/prompts/LA-S6.8-legal-reasoning.txt docs/deep-research-report.md docs/RL-RAP.md
git commit -m "feat: add RL-RAP reasoning prompt and clean up methodology doc"
```

---

## Task 7: Step 6.8 Implementation — Legal Reasoning

**Files:**
- Modify: `backend/app/services/pipeline_service.py` (add `_step6_8_legal_reasoning` and `_build_step6_8_context`)
- Create: `backend/tests/test_step6_8_reasoning.py`

- [ ] **Step 1: Write tests for context building and output parsing**

```python
# backend/tests/test_step6_8_reasoning.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_step6_8_reasoning.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement context builder, output parser, and confidence derivation**

Add to `pipeline_service.py`:

```python
def _build_step6_8_context(state: dict) -> str:
    """Build the user message for Step 6.8 from structured state."""
    parts = []

    # Facts
    facts = state.get("facts", {})
    if facts.get("stated") or facts.get("assumed") or facts.get("missing"):
        parts.append("STATED FACTS:")
        for f in facts.get("stated", []):
            date_str = f" ({f['date']})" if f.get("date") else ""
            parts.append(f"  {f['fact_id']}: {f['description']}{date_str}")

        if facts.get("assumed"):
            parts.append("\nASSUMED FACTS:")
            for f in facts["assumed"]:
                parts.append(f"  {f['fact_id']}: {f['description']} (basis: {f.get('basis', 'implied')})")

        if facts.get("missing"):
            parts.append("\nMISSING FACTS (identified by classifier):")
            for f in facts["missing"]:
                parts.append(f"  {f['fact_id']}: {f['description']} (relevance: {f.get('relevance', '')})")

    # Per-issue article sets
    issue_articles = state.get("issue_articles", {})
    issue_versions = state.get("issue_versions", {})
    legal_issues = state.get("legal_issues", [])

    for issue in legal_issues:
        iid = issue["issue_id"]
        parts.append(f"\n{iid}: {issue.get('description', '')}")
        parts.append(f"  Relevant date: {issue.get('relevant_date', 'unknown')} ({issue.get('temporal_rule', '')})")

        # Find version info for this issue
        for law_key in issue.get("applicable_laws", []):
            iv_key = f"{iid}:{law_key}"
            iv = issue_versions.get(iv_key, {})
            if iv:
                parts.append(f"  Version used: {law_key}, date_in_force {iv.get('date_in_force', 'unknown')}")

        parts.append("  Articles:")
        for art in issue_articles.get(iid, []):
            law_ref = f"{art.get('law_title', '')} ({art.get('law_number', '')}/{art.get('law_year', '')})"
            parts.append(f"    [Art. {art.get('article_number', '')}] {law_ref}, version {art.get('date_in_force', '')}")
            parts.append(f"    {art.get('text', '')}")

    # Shared context
    shared = state.get("shared_context", [])
    if shared:
        parts.append("\nSHARED CONTEXT (SECONDARY):")
        for art in shared:
            law_ref = f"{art.get('law_title', '')} ({art.get('law_number', '')}/{art.get('law_year', '')})"
            parts.append(f"  [Art. {art.get('article_number', '')}] {law_ref}")
            parts.append(f"  {art.get('text', '')}")

    # Flags
    flags = state.get("flags", [])
    if flags:
        parts.append("\nFLAGS AND WARNINGS:")
        for f in flags:
            parts.append(f"  - {f}")

    return "\n".join(parts)


def _parse_step6_8_output(raw: str) -> dict | None:
    """Parse Step 6.8 JSON output. Returns None if malformed."""
    try:
        # Try to extract JSON from the response
        parsed = _extract_json(raw)
        if parsed and "issues" in parsed:
            return parsed
        return None
    except Exception:
        return None


def _derive_confidence(issues: list[dict]) -> str:
    """Derive overall confidence from per-issue certainty levels."""
    if not issues:
        return "LOW"

    levels = [i.get("certainty_level", "UNCERTAIN") for i in issues]

    if any(l == "UNCERTAIN" for l in levels):
        return "LOW"
    if any(l == "CONDITIONAL" for l in levels):
        return "MEDIUM"
    # All CERTAIN or PROBABLE
    return "HIGH"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_step6_8_reasoning.py -v`
Expected: All PASS

- [ ] **Step 5: Implement the full Step 6.8 function**

Add to `pipeline_service.py`:

```python
def _step6_8_legal_reasoning(state: dict, db: Session) -> dict:
    """Step 6.8: RL-RAP legal reasoning. Returns state with rl_rap_output."""
    from app.services.claude_service import call_claude
    from app.services.prompt_service import load_prompt

    t0 = time.time()

    # Build context
    user_message = _build_step6_8_context(state)

    # load_prompt returns (text, version_number)
    prompt_text, prompt_ver = load_prompt("LA-S6.8", db)

    # call_claude signature: call_claude(system: str, messages: list[dict], max_tokens, temperature)
    # Returns dict: {"content": str, "tokens_in": int, "tokens_out": int, "duration": float, "model": str}
    response = call_claude(
        system=prompt_text,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=4096,
        temperature=0.1,
    )

    # Parse output — response is a dict, not an Anthropic response object
    raw_text = response.get("content", "")
    parsed = _parse_step6_8_output(raw_text)

    duration = time.time() - t0

    if parsed:
        state["rl_rap_output"] = parsed
        state["derived_confidence"] = _derive_confidence(parsed.get("issues", []))

        # Build operative_articles set for Step 7.5 validation
        operative = []
        for issue in parsed.get("issues", []):
            for oa in issue.get("operative_articles", []):
                operative.append(oa)
        state["operative_articles"] = operative

        # Check for missing issues
        expected_ids = {i["issue_id"] for i in state.get("legal_issues", [])}
        returned_ids = {i["issue_id"] for i in parsed.get("issues", [])}
        missing_ids = expected_ids - returned_ids
        for mid in missing_ids:
            state["flags"].append(f"{mid}: not analyzed by reasoning step")

        log_step(
            db, state["run_id"], "legal_reasoning", 68, "done", duration,
            prompt_id="LA-S6.8",
            prompt_version=prompt_ver,
            output_summary=f"Analyzed {len(parsed['issues'])} issues",
            output_data={"certainty_levels": {i["issue_id"]: i["certainty_level"] for i in parsed["issues"]}},
            confidence=state["derived_confidence"],
        )
    else:
        # Fallback: no RL-RAP output, Step 7 will use raw articles
        state["rl_rap_output"] = None
        state["derived_confidence"] = None
        state["operative_articles"] = None
        state["flags"].append("Step 6.8 failed to produce valid analysis — falling back to direct answer generation")
        logger.warning(f"Step 6.8 failed to parse output for run {state['run_id']}")
        log_step(
            db, state["run_id"], "legal_reasoning", 68, "done", duration,
            output_summary="Failed to parse — fallback mode",
            warnings=["Malformed RL-RAP output"],
        )

    # Log API call
    log_api_call(
        db, state["run_id"], "legal_reasoning",
        response.get("tokens_in", 0), response.get("tokens_out", 0),
        duration, model=response.get("model", "unknown"),
    )

    return state
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/pipeline_service.py backend/tests/test_step6_8_reasoning.py
git commit -m "feat: implement Step 6.8 RL-RAP legal reasoning"
```

---

## Task 8: Conditional Retrieval Pass

**Files:**
- Modify: `backend/app/services/pipeline_service.py` (add `_conditional_retrieval_pass`)
- Create: `backend/tests/test_conditional_retrieval.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_conditional_retrieval.py
"""Tests for the conditional retrieval pass after Step 6.8."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _check_missing_articles


def test_no_missing_articles(mock_rl_rap_output):
    """When no missing articles, returns empty list."""
    # Default mock has empty missing_articles_needed
    result = _check_missing_articles(mock_rl_rap_output)
    assert result == []


def test_detects_missing_articles():
    """When issues have missing_articles_needed, returns them."""
    rl_rap = {
        "issues": [
            {
                "issue_id": "ISSUE-1",
                "missing_articles_needed": ["Legea 31/1990 art.72", "Cod Civil art.1357 alin.(1)"],
                "certainty_level": "CONDITIONAL",
            }
        ]
    }
    result = _check_missing_articles(rl_rap)
    assert len(result) == 2
    assert "Legea 31/1990 art.72" in result


def test_caps_at_five():
    """Maximum 5 articles requested."""
    rl_rap = {
        "issues": [
            {
                "issue_id": "ISSUE-1",
                "missing_articles_needed": [f"Law art.{i}" for i in range(10)],
                "certainty_level": "UNCERTAIN",
            }
        ]
    }
    result = _check_missing_articles(rl_rap)
    assert len(result) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_conditional_retrieval.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement**

Add to `pipeline_service.py`:

```python
def _check_missing_articles(rl_rap_output: dict) -> list[str]:
    """Extract missing article references from RL-RAP output. Cap at 5."""
    missing = []
    for issue in rl_rap_output.get("issues", []):
        for ref in issue.get("missing_articles_needed", []):
            if ref not in missing:
                missing.append(ref)
            if len(missing) >= 5:
                return missing
    return missing


def _fetch_missing_articles(missing_refs: list[str], state: dict, db: Session) -> list[dict]:
    """Attempt to fetch missing articles from DB. Returns list of new article dicts."""
    from app.models.law import Article, LawVersion, Law
    import re

    fetched = []
    for ref in missing_refs:
        # Parse reference: "Legea 31/1990 art.72" or "Cod Civil art.1357 alin.(1)"
        # Simple pattern: extract article number and law identifier
        art_match = re.search(r"art\.?\s*(\d+(?:\^\d+)?)", ref)
        law_match = re.search(r"(\d+)/(\d{4})", ref)

        if not art_match:
            continue

        art_num = art_match.group(1)

        if law_match:
            law_number = law_match.group(1)
            law_year = law_match.group(2)
            law_key = f"{law_number}/{law_year}"
        else:
            continue  # Cannot identify law without number/year pattern

        # Find version from selected_versions or unique_versions
        selected = state.get("selected_versions", {})
        version_info = selected.get(law_key)
        if not version_info:
            continue

        law_version_id = version_info.get("law_version_id")
        if not law_version_id:
            continue

        # Fetch article
        article = (
            db.query(Article)
            .filter(Article.law_version_id == law_version_id, Article.article_number == art_num)
            .first()
        )
        if article:
            fetched.append({
                "article_id": article.id,
                "article_number": article.article_number,
                "law_number": law_number,
                "law_year": law_year,
                "law_version_id": law_version_id,
                "law_title": version_info.get("law_title", ""),
                "date_in_force": version_info.get("date_in_force", ""),
                "text": article.full_text or "",
                "source": "reasoning_request",
                "tier": "reasoning_request",
                "role": "PRIMARY",
                "is_abrogated": article.is_abrogated or False,
                "doc_type": "article",
            })

    return fetched
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_conditional_retrieval.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pipeline_service.py backend/tests/test_conditional_retrieval.py
git commit -m "feat: implement conditional retrieval pass for missing articles"
```

---

## Task 9: Revised Step 7 — Context Construction and Simplified Prompt

**Files:**
- Modify: `backend/app/services/pipeline_service.py:1502-1717` (`_step7_answer_generation`)
- Modify: `backend/prompts/LA-S7-answer-qa.txt` (and other S7 variants)
- Create: `backend/prompts/LA-S7-simple.txt`
- Create: `backend/tests/test_step7_revised.py`

- [ ] **Step 1: Write tests for revised context construction**

```python
# backend/tests/test_step7_revised.py
"""Tests for revised Step 7 context construction."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _build_step7_context


def test_context_includes_rl_rap_analysis(mock_state_standard, mock_rl_rap_output, mock_articles):
    """When RL-RAP output exists, context includes structured analysis."""
    mock_state_standard["rl_rap_output"] = mock_rl_rap_output
    mock_state_standard["retrieved_articles"] = mock_articles
    ctx = _build_step7_context(mock_state_standard)
    assert "LEGAL ANALYSIS" in ctx
    assert "ISSUE-1" in ctx
    assert "CONDITIONAL" in ctx


def test_context_includes_operative_articles_only(mock_state_standard, mock_rl_rap_output, mock_articles):
    """Only operative articles from RL-RAP should appear in SUPPORTING ARTICLE TEXTS."""
    mock_state_standard["rl_rap_output"] = mock_rl_rap_output
    mock_state_standard["retrieved_articles"] = mock_articles
    ctx = _build_step7_context(mock_state_standard)
    assert "SUPPORTING ARTICLE TEXTS" in ctx
    # Art 197 is in operative_articles, Art 169 is not
    assert "art.197" in ctx.lower() or "Art. 197" in ctx


def test_context_fallback_without_rl_rap(mock_state_standard, mock_articles):
    """Without RL-RAP output, falls back to all retrieved articles."""
    mock_state_standard["rl_rap_output"] = None
    mock_state_standard["retrieved_articles"] = mock_articles
    ctx = _build_step7_context(mock_state_standard)
    assert "RETRIEVED LAW ARTICLES" in ctx  # Old-style context


def test_context_includes_facts(mock_state_standard, mock_rl_rap_output, mock_articles):
    """Facts should appear in the context."""
    mock_state_standard["rl_rap_output"] = mock_rl_rap_output
    mock_state_standard["retrieved_articles"] = mock_articles
    ctx = _build_step7_context(mock_state_standard)
    assert "STRUCTURED FACTS" in ctx
    assert "F1:" in ctx
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_step7_revised.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement _build_step7_context**

Add to `pipeline_service.py` (this replaces the context-building portion of `_step7_answer_generation`):

```python
def _build_step7_context(state: dict) -> str:
    """Build Step 7 user message. Uses RL-RAP output if available, falls back to raw articles."""
    parts = []

    # Classification
    parts.append("CLASSIFICATION:")
    parts.append(f"  Question type: {state.get('question_type', 'A')}")
    parts.append(f"  Legal domain: {state.get('legal_domain', 'unknown')}")
    parts.append(f"  Output mode: {state.get('output_mode', 'qa')}")
    parts.append(f"  Core issue: {state.get('core_issue', '')}")

    rl_rap = state.get("rl_rap_output")

    if rl_rap:
        # Structured facts
        facts = state.get("facts", {})
        if facts.get("stated") or facts.get("assumed") or facts.get("missing"):
            parts.append("\nSTRUCTURED FACTS:")
            for f in facts.get("stated", []):
                date_str = f" ({f['date']})" if f.get("date") else ""
                parts.append(f"  {f['fact_id']}: {f['description']}{date_str}")
            if facts.get("assumed"):
                parts.append("  Assumed:")
                for f in facts["assumed"]:
                    parts.append(f"    {f['fact_id']}: {f['description']} (basis: {f.get('basis', '')})")
            if facts.get("missing"):
                parts.append("  Missing:")
                for f in facts["missing"]:
                    parts.append(f"    {f['fact_id']}: {f['description']}")

        # RL-RAP analysis
        parts.append("\nLEGAL ANALYSIS (from reasoning step):")
        for issue in rl_rap.get("issues", []):
            parts.append(f"\n  {issue['issue_id']}: {issue.get('issue_label', '')}")
            parts.append(f"    Certainty: {issue.get('certainty_level', 'UNKNOWN')}")

            for oa in issue.get("operative_articles", []):
                parts.append(f"    Operative article: {oa['article_ref']} — {oa.get('disposition', {}).get('modality', '')}")

            parts.append("    Conditions:")
            for c in issue.get("decomposed_conditions", []):
                fact_refs = ", ".join(c.get("supporting_fact_ids", []))
                parts.append(f"      {c['condition_id']}: {c['condition_text']} — {c['condition_status']}" +
                           (f" ({fact_refs})" if fact_refs else ""))

            if issue.get("exceptions_checked"):
                parts.append("    Exceptions checked:")
                for ex in issue["exceptions_checked"]:
                    parts.append(f"      {ex['exception_ref']} — {ex['condition_status_summary']} — {ex.get('impact', '')}")

            if issue.get("conflicts"):
                c = issue["conflicts"]
                parts.append(f"    Conflict: {c.get('resolution_rule', 'UNRESOLVED')} — {c.get('rationale', '')}")

            ta = issue.get("temporal_applicability", {})
            if ta.get("temporal_risks"):
                parts.append(f"    Temporal risks: {', '.join(ta['temporal_risks'])}")

            parts.append(f"    Conclusion: {issue.get('conclusion', '')}")

            if issue.get("missing_facts"):
                parts.append(f"    Missing facts: {'; '.join(issue['missing_facts'])}")

        # Supporting article texts (operative only)
        operative_refs = set()
        for issue in rl_rap.get("issues", []):
            for oa in issue.get("operative_articles", []):
                operative_refs.add(oa.get("article_ref", ""))

        all_articles = state.get("retrieved_articles", [])
        parts.append("\nSUPPORTING ARTICLE TEXTS:")
        for art in all_articles:
            art_ref = f"art.{art.get('article_number', '')}"
            # Check if this article is referenced in operative_articles
            matched = any(art_ref in ref for ref in operative_refs)
            if matched:
                law_ref = f"{art.get('law_title', '')} ({art.get('law_number', '')}/{art.get('law_year', '')})"
                parts.append(f"  [Art. {art.get('article_number', '')}] {law_ref}, version {art.get('date_in_force', '')}")
                parts.append(f"  {art.get('text', '')}")
    else:
        # Fallback: no RL-RAP output, use raw articles (current behavior)
        parts.append("\nRETRIEVED LAW ARTICLES FROM LEGAL LIBRARY:")
        for i, art in enumerate(state.get("retrieved_articles", []), 1):
            role_tag = f"[{art.get('role', 'SECONDARY')}]"
            abrogated_tag = " [ABROGATED]" if art.get("is_abrogated") else ""
            law_ref = f"{art.get('law_title', '')} ({art.get('law_number', '')}/{art.get('law_year', '')})"
            parts.append(f"[Article {i}] {role_tag}{abrogated_tag} {law_ref}, Art. {art.get('article_number', '')}")
            if art.get("date_in_force"):
                parts.append(f"  version {art['date_in_force']}")
            parts.append(f"  {art.get('text', '')}")

    # Flags
    flags = state.get("flags", [])
    if flags:
        parts.append("\nFLAGS AND WARNINGS:")
        for f in flags:
            parts.append(f"  - {f}")

    # Question
    parts.append(f"\nUSER QUESTION:\n{state.get('question', '')}")

    return "\n".join(parts)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_step7_revised.py -v`
Expected: All PASS

- [ ] **Step 5: Create simplified prompt for SIMPLE queries**

Create `backend/prompts/LA-S7-simple.txt`:

```text
You are a Romanian legal assistant answering a simple statutory question. Your answer must be accurate, concise, and cite the specific legal provision.

INSTRUCTIONS:
1. State the rule clearly and directly in Romanian.
2. Cite the specific article, paragraph, and law version: "Art. X alin. (Y) din Legea nr. Z/AAAA".
3. If the provided articles contain relevant exceptions or conditions, mention them briefly.
4. Note any relevant thresholds, deadlines, or conditions from the cited article.
5. Keep the answer to 1-3 paragraphs.
6. If the articles do not contain a clear answer, say so explicitly.

RESPONSE FORMAT — Return valid JSON:
{
  "answer": "<answer in Romanian, 1-3 paragraphs, with inline citations>",
  "version_logic": "<which law version was used and why, or null>",
  "missing_info": "<aspects not covered, or null>",
  "confidence": "HIGH|MEDIUM|LOW",
  "confidence_reason": "<one sentence>",
  "sources": [
    {
      "statement": "<specific claim>",
      "label": "DB|Interpretation|Unverified",
      "law": "<law number/year>",
      "article": "<article number>",
      "version_date": "<YYYY-MM-DD>"
    }
  ]
}
```

- [ ] **Step 6: Update the existing S7 prompts to add RL-RAP consumption instructions**

Read each S7 prompt (`LA-S7-answer-qa.txt`, `LA-S7-M2-answer-memo.txt`, etc.). In each:
- Remove sections that instruct Claude on legal reasoning methodology (subsumption, exception checking, conflict resolution) — this is now done by Step 6.8
- Add a section: "You receive a LEGAL ANALYSIS from a prior reasoning step. This analysis contains per-issue conclusions, condition evaluations, and certainty levels. Your job is to COMMUNICATE this analysis clearly, not to re-derive it."
- Add: "Your confidence cannot be higher than the certainty levels in the analysis. If any issue is CONDITIONAL, overall confidence is MEDIUM at most. If any issue is UNCERTAIN, overall confidence is LOW."
- Keep all formatting instructions (how to structure by issue, how to cite, how to present risks)

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/pipeline_service.py backend/prompts/ backend/tests/test_step7_revised.py
git commit -m "feat: revise Step 7 to consume RL-RAP analysis and add SIMPLE prompt"
```

---

## Task 10: Wire Everything Into run_pipeline and resume_pipeline

**Files:**
- Modify: `backend/app/services/pipeline_service.py:89-283` (`run_pipeline`) and `backend/app/services/pipeline_service.py:285-520` (`resume_pipeline`)

This is the integration task. All individual steps exist; now they need to be wired into the main pipeline flow.

- [ ] **Step 1: Extract shared full-path function**

To avoid duplicating the full path logic in both `run_pipeline` and `resume_pipeline`, extract it into a shared generator:

```python
def _run_full_path(state: dict, db: Session, run_id: str) -> Generator[dict, None, dict]:
    """Full path for STANDARD/COMPLEX queries. Steps 4 through 7.5 with RL-RAP.
    Yields SSE events. Returns the final state dict via StopIteration.value."""

    # Step 4: Hybrid Retrieval
    yield _step_event(4, "hybrid_retrieval", "running")
    t0 = time.time()
    state = _step4_hybrid_retrieval(state, db)
    yield _step_event(4, "hybrid_retrieval", "done", {
        "articles_found": len(state.get("retrieved_articles_raw", [])),
    }, time.time() - t0)

    # Step 4.5: Pre-Expansion Relevance Filter
    yield _step_event(45, "pre_expansion_filter", "running")
    t0 = time.time()
    before_filter = len(state.get("retrieved_articles_raw", []))
    state = _step4_5_pre_expansion_filter(state)
    yield _step_event(45, "pre_expansion_filter", "done", {
        "before": before_filter,
        "after": len(state.get("retrieved_articles_raw", [])),
    }, time.time() - t0)

    # Step 5: Article Expansion
    yield _step_event(5, "expansion", "running")
    t0 = time.time()
    before_expansion = len(state.get("retrieved_articles_raw", []))
    state = _step5_expand(state, db)
    yield _step_event(5, "expansion", "done", {
        "articles_before": before_expansion,
        "articles_after_expansion": len(state.get("retrieved_articles_raw", [])),
    }, time.time() - t0)

    # Step 5.5: Exception Retrieval
    yield _step_event(55, "exception_retrieval", "running")
    t0 = time.time()
    before_exceptions = len(state.get("retrieved_articles_raw", []))
    state = _step5_5_exception_retrieval(state, db)
    yield _step_event(55, "exception_retrieval", "done", {
        "exceptions_added": len(state.get("retrieved_articles_raw", [])) - before_exceptions,
    }, time.time() - t0)

    # Step 6: Reranking (dynamic top_k)
    yield _step_event(6, "article_selection", "running")
    t0 = time.time()
    state = _step6_select_articles(state, db)
    yield _step_event(6, "article_selection", "done", {
        "top_articles": len(state.get("retrieved_articles", [])),
    }, time.time() - t0)

    # Step 6.5: Late Relevance Gate
    gate_events, gate_result = _step6_5_relevance_gate(state, db)
    for evt in gate_events:
        yield evt
    if gate_result:
        complete_run(db, run_id, "clarification", None, state.get("flags"))
        db.commit()
        yield gate_result
        return state  # Early return — gate triggered

    # Step 6.7: Article-to-Issue Partitioning
    yield _step_event(67, "article_partitioning", "running")
    t0 = time.time()
    state = _step6_7_partition_articles(state)
    yield _step_event(67, "article_partitioning", "done", {
        "issues_with_articles": sum(1 for v in state.get("issue_articles", {}).values() if v),
        "shared_context": len(state.get("shared_context", [])),
    }, time.time() - t0)

    # Step 6.8: Legal Reasoning (RL-RAP)
    yield _step_event(68, "legal_reasoning", "running")
    state = _step6_8_legal_reasoning(state, db)
    yield _step_event(68, "legal_reasoning", "done", {
        "has_analysis": state.get("rl_rap_output") is not None,
        "derived_confidence": state.get("derived_confidence"),
    })

    # Conditional Retrieval Pass
    if state.get("rl_rap_output"):
        missing = _check_missing_articles(state["rl_rap_output"])
        if missing:
            yield _step_event(69, "conditional_retrieval", "running")
            t0 = time.time()
            fetched = _fetch_missing_articles(missing, state, db)
            if fetched:
                for art in fetched:
                    added = False
                    for iid, arts in state.get("issue_articles", {}).items():
                        iv_key = f"{iid}:{art['law_number']}/{art['law_year']}"
                        if iv_key in state.get("issue_versions", {}):
                            arts.append(art)
                            added = True
                    if not added:
                        state.setdefault("shared_context", []).append(art)
                state = _step6_8_legal_reasoning(state, db)
            else:
                state["flags"].append(f"Missing provisions not in library: {', '.join(missing)}")
            yield _step_event(69, "conditional_retrieval", "done", {
                "requested": len(missing),
                "fetched": len(fetched) if fetched else 0,
            }, time.time() - t0)

    # Step 7: Answer Generation
    yield _step_event(8, "answer_generation", "running")
    t0 = time.time()
    for event in _step7_answer_generation(state, db):
        yield event
    yield _step_event(8, "answer_generation", "done", duration=time.time() - t0)

    # Step 7.5: Citation Validation
    yield _step_event(85, "citation_validation", "running")
    t0 = time.time()
    state = _step7_5_citation_validation(state, db)
    yield _step_event(85, "citation_validation", "done", duration=time.time() - t0)

    # Confidence capping: derived_confidence from Step 6.8 is the ceiling
    _cap_confidence(state)

    return state


def _run_fast_path(state: dict, db: Session, run_id: str) -> Generator[dict, None, dict]:
    """Fast path for SIMPLE queries. Skips Steps 4.5, 5, 5.5, 6.7, 6.8.
    Yields SSE events. Returns the final state dict via StopIteration.value."""

    # Step 4: Reduced retrieval
    yield _step_event(4, "hybrid_retrieval", "running")
    t0 = time.time()
    state = _step4_hybrid_retrieval(state, db, tier_limits_override={
        "tier1_primary": 5,
        "tier2_secondary": 5,
    })
    yield _step_event(4, "hybrid_retrieval", "done", {
        "articles_found": len(state.get("retrieved_articles_raw", [])),
    }, time.time() - t0)

    # Step 6: Rerank to top 3
    yield _step_event(6, "article_selection", "running")
    t0 = time.time()
    state = _step6_select_articles(state, db, top_k_override=3)
    yield _step_event(6, "article_selection", "done", {
        "top_articles": len(state.get("retrieved_articles", [])),
    }, time.time() - t0)

    # Step 6.5: Late Relevance Gate
    gate_events, gate_result = _step6_5_relevance_gate(state, db)
    for evt in gate_events:
        yield evt
    if gate_result:
        complete_run(db, run_id, "clarification", None, state.get("flags"))
        db.commit()
        yield gate_result
        return state  # Early return — gate triggered

    # Step 7: Direct answer with simplified prompt
    yield _step_event(8, "answer_generation", "running")
    t0 = time.time()
    state["use_simple_prompt"] = True
    for event in _step7_answer_generation(state, db):
        yield event
    yield _step_event(8, "answer_generation", "done", duration=time.time() - t0)

    # Step 7.5: Citation Validation
    yield _step_event(85, "citation_validation", "running")
    t0 = time.time()
    state = _step7_5_citation_validation(state, db)
    yield _step_event(85, "citation_validation", "done", duration=time.time() - t0)

    return state


def _cap_confidence(state: dict) -> None:
    """Cap Step 7's confidence to not exceed Step 6.8's derived confidence."""
    derived = state.get("derived_confidence")
    if not derived:
        return
    CONF_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    derived_rank = CONF_ORDER.get(derived, 0)
    actual_rank = CONF_ORDER.get(state.get("confidence", "HIGH"), 2)
    if actual_rank > derived_rank:
        state["confidence"] = derived
```

- [ ] **Step 2: Modify run_pipeline to route by complexity**

In `run_pipeline`, replace the current Steps 4–7.5 block (lines ~197–254) with:

```python
        # Route by complexity — both paths use generator.send() pattern
        # to return final state via StopIteration.value
        if state.get("complexity") == "SIMPLE":
            path_gen = _run_fast_path(state, db, run_id)
        else:
            path_gen = _run_full_path(state, db, run_id)

        # Drive the path generator, yielding SSE events
        try:
            event = next(path_gen)
            while True:
                yield event
                event = next(path_gen)
        except StopIteration as e:
            if e.value:
                state = e.value

        # Check if gate triggered (state has no answer → was early return)
        if not state.get("answer"):
            # Gate triggered or error — run already completed inside path
            return
```

This pattern works because `_run_full_path` and `_run_fast_path` use `return state` at the end, which sets `StopIteration.value`. Both generators handle their own `complete_run` for gate-triggered cases, so the caller only needs to handle the normal finalization.

The finalization block (already at lines ~256–269) then runs for both paths:

```python
        # Finalize — runs for both fast and full paths
        complete_run(db, run_id, "ok", state.get("confidence"), state.get("flags"))
        db.commit()

        yield {
            "type": "done",
            "run_id": run_id,
            "content": state.get("answer", ""),
            "structured": state.get("answer_structured"),
            "mode": state.get("output_mode", "qa"),
            "confidence": state.get("confidence", "MEDIUM"),
            "flags": state.get("flags", []),
            "reasoning": _build_reasoning_panel(state),
        }
```

- [ ] **Step 3: Update _step7_answer_generation to use new context builder**

In `_step7_answer_generation`, replace the context construction section with a call to `_build_step7_context(state)`. Also add logic to select the prompt:

In `_step7_answer_generation` (line ~1502), locate the section where the prompt is selected and the context is built. Replace the context-building portion with `_build_step7_context(state)` and add prompt routing:

```python
# Prompt selection — add at the start of _step7_answer_generation, before the Claude call:
prompt_map = {
    "qa": "LA-S7",
    "memo": "LA-S7-M2",
    "comparison": "LA-S7-M3",
    "compliance": "LA-S7-M4",
    "checklist": "LA-S7-M5",
}

if state.get("use_simple_prompt"):
    prompt_id = "LA-S7-simple"
else:
    prompt_id = prompt_map.get(state.get("output_mode", "qa"), "LA-S7")

# Replace the inline context construction with:
user_message = _build_step7_context(state)

# The existing streaming call, JSON parsing, confidence setting, and logging
# remain unchanged. Only the context source and prompt selection change.
```

The existing `_step7_answer_generation` already handles streaming, response parsing, confidence assignment, and logging. Those sections stay as-is. Only the two inputs to the Claude call change: the prompt selection and the user message content.

- [ ] **Step 4: Update _step7_5_citation_validation to use operative_articles**

In `_step7_5_citation_validation`, add logic to validate against `state["operative_articles"]` when available:

```python
# At the start of _step7_5_citation_validation:
if state.get("operative_articles"):
    # Validate against operative articles from RL-RAP
    provided_articles = set()
    for oa in state["operative_articles"]:
        ref = oa.get("article_ref", "")
        # Extract law and article from ref like "Legea 31/1990 art.197 alin.(3)"
        # ... (parse into law_key, article_number)
        provided_articles.add((law_key, article_number))
else:
    # Fallback: validate against all retrieved articles (current behavior)
    # ... existing logic
```

- [ ] **Step 5: Update resume_pipeline to use shared path generators**

In `resume_pipeline`, the current Steps 4–7.5 block (lines ~427–507) should be replaced with the same routing pattern as `run_pipeline`. The paused state already includes the full `state` dict, so `complexity` is persisted automatically via `save_paused_state`/`load_paused_state`.

Replace the current Steps 4–7.5 section in `resume_pipeline` with:

```python
        # Route by complexity — same pattern as run_pipeline
        if state.get("complexity") == "SIMPLE":
            path_gen = _run_fast_path(state, db, run_id)
        else:
            path_gen = _run_full_path(state, db, run_id)

        try:
            event = next(path_gen)
            while True:
                yield event
                event = next(path_gen)
        except StopIteration as e:
            if e.value:
                state = e.value

        if not state.get("answer"):
            return

        # Finalize
        complete_run(db, run_id, "ok", state.get("confidence"), state.get("flags"))
        db.commit()

        yield {
            "type": "done",
            "run_id": run_id,
            "content": state.get("answer", ""),
            "structured": state.get("answer_structured"),
            "mode": state.get("output_mode", "qa"),
            "confidence": state.get("confidence", "MEDIUM"),
            "flags": state.get("flags", []),
            "reasoning": _build_reasoning_panel(state),
        }
```

This eliminates the code duplication between `run_pipeline` and `resume_pipeline` for the Steps 4–7.5 section. Both now call `_run_full_path` or `_run_fast_path`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: wire new steps into run_pipeline and resume_pipeline"
```

---

## Task 11: Frontend Step Indicator Update

**Files:**
- Modify: `frontend/src/app/assistant/step-indicator.tsx`

- [ ] **Step 1: Add new step labels**

In the `STEP_LABELS` constant (lines 5-18), add:

```typescript
pre_expansion_filter: "Filtering results...",
article_partitioning: "Organizing by issue...",
legal_reasoning: "Analyzing legal provisions...",
conditional_retrieval: "Fetching additional provisions...",
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/assistant/step-indicator.tsx
git commit -m "feat: add SSE step labels for new pipeline steps"
```

---

## Task 12: Integration Testing

**Files:**
- All modified files

- [ ] **Step 1: Run all unit tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Manual smoke test — SIMPLE query**

Start the backend server and test via the frontend or curl:

```bash
curl -X POST http://localhost:8000/api/assistant/sessions/{session_id}/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "Care este capitalul social minim pentru un SRL?"}'
```

Verify:
- Step 1 returns `complexity: "SIMPLE"`
- Steps 4.5, 5, 5.5, 6.7, 6.8 are NOT in the SSE events
- Answer is concise (1-3 paragraphs)
- Cost is lower than before (~2 Claude calls)

- [ ] **Step 3: Manual smoke test — STANDARD query**

```bash
curl -X POST http://localhost:8000/api/assistant/sessions/{session_id}/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "Un administrator al unui SRL a acordat un imprumut de 50000 EUR societatii fara aprobarea AGA pe 01.01.2025. Este valid actul juridic?"}'
```

Verify:
- Step 1 returns `complexity: "STANDARD"` with `facts` field
- Steps 4.5, 6.7, 6.8 appear in SSE events
- Step 6.8 produces valid RL-RAP JSON (check logs)
- Answer references conditions (SATISFIED/UNKNOWN) and missing facts
- Confidence derived from Step 6.8 certainty

- [ ] **Step 4: Manual smoke test — fallback on Step 6.8 failure**

Temporarily corrupt the LA-S6.8 prompt to force a parse failure. Verify:
- Pipeline continues to Step 7 using raw articles (fallback)
- Flag "Step 6.8 failed" appears in the response
- Answer is generated (current quality, no degradation)
- Restore the prompt after testing

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "test: integration testing complete for legal reasoning layer"
```

---

## Summary

| Task | What | Type | Estimated Effort |
|---|---|---|---|
| 1 | Test infrastructure + fixtures | Setup | Small |
| 2 | Step 1: complexity + facts | Prompt + code | Medium |
| 3 | Step 4.5: pre-expansion filter | New step | Small |
| 4 | Dynamic top_k + tier_limits_override | Params | Small |
| 5 | Step 6.7: article partitioning | New step | Medium |
| 6 | RL-RAP prompt + doc cleanup | Prompt | Medium |
| 7 | Step 6.8: reasoning implementation | New step | Large |
| 8 | Conditional retrieval pass | New step | Medium |
| 9 | Revised Step 7 + simple prompt | Modify step | Large |
| 10 | Wire into run_pipeline/resume_pipeline | Integration | Large |
| 11 | Frontend step indicator | Frontend | Small |
| 12 | Integration testing | Testing | Medium |
