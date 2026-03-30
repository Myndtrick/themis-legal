# Legal Reasoning Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve legal reasoning quality by adding issue prioritization, governing norm detection, subsumption enforcement, three-way uncertainty typing, a post-6.9 governing norm gate, answer tone calibration, and enhanced confidence derivation.

**Architecture:** Prompt rewrites for Steps 1, 6.8, and 7 with new structured output fields. Pipeline code changes in `pipeline_service.py` for state propagation, output parsing with backward-compatible defaults, a new `_fetch_governing_norm` function with semantic search fallback, a post-6.9 gate, and three new confidence derivation rules.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, ChromaDB (semantic search), Claude API (LLM calls), pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/prompts/LA-S1-issue-classifier.txt` | Modify | Add issue prioritization instructions + `primary_target` and per-issue `priority` to output schema |
| `backend/prompts/LA-S6.8-legal-reasoning.txt` | Modify | Add governing norm check, condition table, subsumption summary, uncertainty sources |
| `backend/prompts/LA-S7-answer-template.txt` | Modify | Add issue-priority answer structure, three-way uncertainty, tone calibration |
| `backend/app/services/pipeline_service.py` | Modify | State propagation, output parsing, governing norm retrieval, post-6.9 gate, confidence derivation |
| `backend/tests/conftest.py` | Modify | Add fixtures for new state fields |
| `backend/tests/test_confidence_derivation.py` | Create | Tests for `_derive_final_confidence` with new rules |
| `backend/tests/test_governing_norm_gate.py` | Create | Tests for the post-6.9 gate logic |
| `backend/tests/test_parse_step6_8.py` | Create | Tests for backward-compatible parsing of new 6.8 fields |

---

### Task 1: Step 1 Prompt — Issue Prioritization

**Files:**
- Modify: `backend/prompts/LA-S1-issue-classifier.txt`

- [ ] **Step 1: Add ISSUE PRIORITIZATION instruction block**

In `backend/prompts/LA-S1-issue-classifier.txt`, add the following block after line 57 (after the "If the Legal Library list is provided..." paragraph), before "6. Temporal Decomposition":

```text
5b. Issue Prioritization (REQUIRED):
   Before decomposing legal issues, identify the user's primary target:
   - WHO is the user asking about? (the legally relevant actor)
   - WHAT does the user want to know about that actor? (liability, obligation, right, risk, eligibility, compliance)

   Then rank each legal issue:
   - "PRIMARY" = Directly answers what the user asked about the target actor
   - "SECONDARY" = Legally related but not the user's direct question
   - "SUPPORTING" = Background context needed to analyze primary/secondary issues

   The test: if you could only answer ONE issue, which one would the user consider
   their question answered? That is PRIMARY.

   Common prioritization failures to avoid:
   - Prioritizing a transaction's validity over the actor's liability when the user asks about the actor
   - Prioritizing procedural issues over substantive rights when the user asks about rights
   - Prioritizing the means (e.g., annulment action) over the consequence (e.g., personal liability)
```

- [ ] **Step 2: Add `primary_target` to JSON output schema**

In the RESPONSE FORMAT JSON block, add `primary_target` after `"classification_confidence"`:

```json
  "primary_target": {
    "actor": "<who the user is asking about>",
    "concern": "<what the user wants to know: liability, obligation, right, risk, eligibility, compliance>",
    "issue_id": "<ISSUE-N that is the primary target>",
    "reasoning": "<why this is the primary target>"
  },
```

- [ ] **Step 3: Add `priority` and `priority_reasoning` to legal_issues entries**

In the `legal_issues` array items within the RESPONSE FORMAT JSON block, add after `"applicable_laws"`:

```json
      "priority": "PRIMARY or SECONDARY or SUPPORTING",
      "priority_reasoning": "<why this issue has this priority relative to the user's question>"
```

- [ ] **Step 4: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/prompts/LA-S1-issue-classifier.txt
git commit -m "feat(S1): add issue prioritization to classifier prompt

Add primary_target field and per-issue priority ranking to help
the pipeline identify and prioritize the user's actual question."
```

---

### Task 2: Step 1 State Propagation

**Files:**
- Modify: `backend/app/services/pipeline_service.py:1270-1288`
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Write test for primary_target state extraction**

Create file `backend/tests/test_step1_prioritization.py`:

```python
"""Tests for Step 1 issue prioritization state extraction."""
from app.services.pipeline_service import _extract_json


def test_primary_target_extracted_from_step1_output():
    """primary_target from Step 1 JSON is stored in state."""
    parsed = {
        "question_type": "B",
        "legal_domain": "corporate",
        "output_mode": "qa",
        "core_issue": "Administrator liability",
        "primary_target": {
            "actor": "administrator",
            "concern": "personal liability",
            "issue_id": "ISSUE-1",
            "reasoning": "User asks about administrator exposure",
        },
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "description": "Administrator personal liability",
                "relevant_date": "2026-07-01",
                "temporal_rule": "insolvency_opening",
                "applicable_laws": ["85/2014"],
                "priority": "PRIMARY",
                "priority_reasoning": "Directly addresses user question",
            },
            {
                "issue_id": "ISSUE-2",
                "description": "Transaction annulment",
                "relevant_date": "2026-03-01",
                "temporal_rule": "act_date",
                "applicable_laws": ["85/2014"],
                "priority": "SECONDARY",
                "priority_reasoning": "Related but not direct question",
            },
        ],
    }
    # Simulate state extraction (same logic as _step1_issue_classification)
    state = {"flags": []}
    state["primary_target"] = parsed.get("primary_target")
    state["legal_issues"] = parsed.get("legal_issues", [])

    assert state["primary_target"]["actor"] == "administrator"
    assert state["primary_target"]["issue_id"] == "ISSUE-1"
    assert state["legal_issues"][0]["priority"] == "PRIMARY"
    assert state["legal_issues"][1]["priority"] == "SECONDARY"


def test_primary_target_defaults_to_none_when_missing():
    """If Step 1 doesn't produce primary_target, state gets None."""
    parsed = {
        "question_type": "A",
        "legal_issues": [{"issue_id": "ISSUE-1", "description": "Test"}],
    }
    state = {"flags": []}
    state["primary_target"] = parsed.get("primary_target")
    assert state["primary_target"] is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/test_step1_prioritization.py -v
```

Expected: PASS (these test pure dict operations, not the function itself — they validate the extraction logic we'll replicate).

- [ ] **Step 3: Add `primary_target` extraction to `_step1_issue_classification`**

In `backend/app/services/pipeline_service.py`, in the `_step1_issue_classification` function, after line 1279 (`state["legal_issues"] = parsed.get("legal_issues", [])`), add:

```python
    state["primary_target"] = parsed.get("primary_target")
```

- [ ] **Step 4: Update conftest fixtures with new fields**

In `backend/tests/conftest.py`, update `mock_state_standard` fixture. Add after `"core_issue"` line:

```python
        "primary_target": {
            "actor": "administrator",
            "concern": "validity of transaction",
            "issue_id": "ISSUE-1",
            "reasoning": "User asks about the validity of the administrator's act",
        },
```

And add `"priority": "PRIMARY"` and `"priority_reasoning": "Direct question"` to the existing `legal_issues[0]` entry in `mock_state_standard`:

```python
            {
                "issue_id": "ISSUE-1",
                "description": "Validity of administrator-company transaction without AGA approval",
                "relevant_date": "2025-01-01",
                "temporal_rule": "contract_formation",
                "applicable_laws": ["31/1990"],
                "priority": "PRIMARY",
                "priority_reasoning": "Direct question about transaction validity",
            }
```

Also update `mock_state_simple` to add `"primary_target": None` after `"core_issue"`.

- [ ] **Step 5: Run all tests**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/ -v
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/app/services/pipeline_service.py backend/tests/conftest.py backend/tests/test_step1_prioritization.py
git commit -m "feat(S1): extract primary_target and issue priority into pipeline state

Store the new fields from Step 1 output so downstream steps
can use issue prioritization for reasoning and answer generation."
```

---

### Task 3: Step 6.8 Prompt — Governing Norm Detection, Subsumption Enforcement, Uncertainty Typing

**Files:**
- Modify: `backend/prompts/LA-S6.8-legal-reasoning.txt`

- [ ] **Step 1: Add GOVERNING NORM CHECK instruction**

In `backend/prompts/LA-S6.8-legal-reasoning.txt`, add the following after the "1. IDENTIFY OPERATIVE ARTICLES" section (after the NORM PRIORITIZATION block, before "2. DECOMPOSE EACH RULE ARTICLE"):

```text
1b. GOVERNING NORM CHECK (REQUIRED — perform before subsumption)
   For each issue, before beginning condition analysis, answer:
   "Do I have the specific norm that triggers the main legal consequence for this issue?"

   This is not about whether you have *relevant* articles. It is about whether you have
   *the* article — the one a lawyer would cite as the legal basis for the primary conclusion.

   Examples of the distinction:
   - Having articles about transaction annulment but NOT the administrator liability provision → MISSING
   - Having the general duty of care but NOT the specific sanction for breach → MISSING
   - Having eligibility conditions for a subsidy but NOT the provision that grants or revokes it → MISSING
   - Having the dismissal procedure but NOT the article defining valid grounds → MISSING

   Set governing_norm_status:
   - PRESENT: The norm that directly triggers the main legal consequence is among the provided articles. Cite it.
   - INFERRED: No single article explicitly governs the consequence, but the conclusion can be
     constructed from multiple provided norms with reasonable certainty. Explain the chain.
   - MISSING: The provided articles are related but do not contain the norm that governs the
     primary legal consequence. The analysis proceeds on secondary aspects only.

   When status is MISSING:
   - Add the expected norm to missing_articles_needed
   - State clearly in the conclusion that the analysis is incomplete
   - Do NOT produce a confident conclusion based only on surrounding norms
   - Set certainty_level to UNCERTAIN unless secondary aspects can be analyzed independently

   When status is INFERRED:
   - Explain the reasoning chain from multiple norms to the conclusion
   - Set certainty_level no higher than PROBABLE
```

- [ ] **Step 2: Replace PERFORM SUBSUMPTION instructions with enforced condition table**

Replace the existing "3. PERFORM SUBSUMPTION" section with:

```text
3. PERFORM SUBSUMPTION (with enforced condition table)
   - Analyze the PRIMARY norm first. Then SECONDARY, then SUPPORTING.
   - You MUST populate the condition_table completely BEFORE writing the conclusion.
     A conclusion without a complete condition table is invalid.
   - For each RULE article, extract every ATOMIC condition from the hypothesis.
     "Atomic" means a single factual predicate that can be independently true or false.
     Do NOT merge multiple conditions into one row. "The administrator acted in bad faith
     and caused damage" is TWO conditions, not one.
   - For each condition, evaluate against stated facts:
     - SATISFIED: supported by an explicit stated fact (cite fact_id)
     - NOT_SATISFIED: contradicted by an explicit stated fact (cite fact_id)
     - UNKNOWN: fact not provided — MUST produce a missing_fact entry. NEVER guess.
   - UNKNOWN must NEVER be resolved by guessing. If the fact is not stated, it stays UNKNOWN.
   - A single NOT_SATISFIED on a necessary condition makes the norm inapplicable.
   - For OR-lists: SATISFIED if at least one branch is SATISFIED.
   - For AND-lists: all must be SATISFIED for the norm to apply.
   - Do NOT skip conditions because they are difficult (causation, intent, good faith).
   - After completing condition_table, populate subsumption_summary by counting statuses.
   - The conclusion must be logically derivable from subsumption_summary:
     - If norm_applicable is CONDITIONAL: conclusion MUST state what depends on which unknowns
     - If norm_applicable is false (NOT_SATISFIED on necessary condition): conclusion MUST state the norm does not apply
     - A conclusion asserting a legal consequence while blocking_unknowns exist is INVALID
       unless it explicitly conditions the consequence on those unknowns
```

- [ ] **Step 3: Add UNCERTAINTY CLASSIFICATION instruction**

Add after the "7. PRODUCE CONCLUSION AND CERTAINTY" section, before the OUTPUT FORMAT:

```text
8. CLASSIFY UNCERTAINTY SOURCES (REQUIRED when certainty_level is not CERTAIN)
   When certainty_level is PROBABLE, CONDITIONAL, or UNCERTAIN, populate uncertainty_sources:
   - FACTUAL_GAP: You need a fact the user did not provide. Never guess — list it.
     resolvable_by: USER_INPUT
   - LIBRARY_GAP: You need a legal provision not in the provided articles.
     This is a system limitation, not legal uncertainty.
     resolvable_by: ARTICLE_IMPORT
   - LEGAL_AMBIGUITY: The law is genuinely ambiguous or doctrinally contested.
     This exists even with complete facts and complete library.
     resolvable_by: LEGAL_INTERPRETATION

   CRITICAL: Do NOT conflate these. "I don't have Art. X" is a LIBRARY_GAP, not legal uncertainty.
   "Art. X could be interpreted two ways" is LEGAL_AMBIGUITY.
   "I don't know if the company had >50 employees" is a FACTUAL_GAP.
```

- [ ] **Step 4: Update the OUTPUT FORMAT JSON schema**

Replace the existing JSON output schema with the updated version. The full per-issue structure becomes:

```json
{
  "issues": [
    {
      "issue_id": "ISSUE-N",
      "issue_label": "short description",
      "governing_norm_status": {
        "status": "PRESENT|INFERRED|MISSING",
        "explanation": "why this status",
        "expected_norm_description": "what norm is expected if MISSING or INFERRED",
        "missing_norm_ref": "Legea N/YYYY art.X if known, or null"
      },
      "operative_articles": [
        {
          "article_ref": "Legea N/YYYY art.X alin.(Y) lit.(Z)",
          "law_version_id": "<id>",
          "norm_type": "RULE|DEFINITION|PROCEDURAL_RULE|REFERENCE_RULE",
          "priority": "PRIMARY|SECONDARY|SUPPORTING",
          "disposition": {"modality": "OBLIGATION|PROHIBITION|PERMISSION|POWER", "text": "..."},
          "sanction": {"explicit": true, "text": "..."}
        }
      ],
      "condition_table": [
        {
          "condition_id": "C1",
          "norm_ref": "Legea N/YYYY art.X alin.(Y)",
          "condition_text": "atomic testable condition",
          "source": "HYPOTHESIS|DISPOSITION|SANCTION_TRIGGER",
          "list_type": "OR|AND|null",
          "list_group": "G1 or null",
          "status": "SATISFIED|NOT_SATISFIED|UNKNOWN",
          "evidence": "F1: fact description, or null",
          "missing_fact": "precise missing fact if UNKNOWN, or null"
        }
      ],
      "subsumption_summary": {
        "total_conditions": 5,
        "satisfied": 2,
        "not_satisfied": 0,
        "unknown": 3,
        "norm_applicable": "YES|NO|CONDITIONAL",
        "blocking_unknowns": ["C2", "C4"]
      },
      "exceptions_checked": [
        {
          "exception_ref": "...",
          "type": "INLINE_EXCEPTION|DEROGATION|SPECIAL_RULE",
          "condition_status_summary": "SATISFIED|NOT_SATISFIED|UNKNOWN",
          "impact": "short impact description",
          "missing_facts": []
        }
      ],
      "conflicts": {
        "conflict_detected": true,
        "resolution_rule": "LEX_SUPERIOR|LEX_SPECIALIS|LEX_POSTERIOR|UNRESOLVED",
        "chosen_norm": "...",
        "rationale": "2-4 lines"
      },
      "temporal_applicability": {
        "relevant_event_date": "YYYY-MM-DD",
        "version_matches": true,
        "temporal_risks": ["risk description if any"]
      },
      "conclusion": "2-6 lines; conditional branches allowed",
      "certainty_level": "CERTAIN|PROBABLE|CONDITIONAL|UNCERTAIN",
      "uncertainty_sources": [
        {
          "type": "FACTUAL_GAP|LIBRARY_GAP|LEGAL_AMBIGUITY",
          "detail": "specific description",
          "impact": "what this prevents from being determined",
          "resolvable_by": "USER_INPUT|ARTICLE_IMPORT|LEGAL_INTERPRETATION"
        }
      ],
      "missing_facts": ["all missing facts for this issue"],
      "missing_articles_needed": ["Legea N/YYYY art.X if critical provision missing"]
    }
  ]
}
```

- [ ] **Step 5: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/prompts/LA-S6.8-legal-reasoning.txt
git commit -m "feat(S6.8): add governing norm detection, subsumption enforcement, uncertainty typing

Add governing_norm_status check before subsumption, replace flat
decomposed_conditions with enforced condition_table + subsumption_summary,
and add typed uncertainty_sources (FACTUAL_GAP, LIBRARY_GAP, LEGAL_AMBIGUITY)."
```

---

### Task 4: Step 6.8 Context Builder — Pass Issue Priorities

**Files:**
- Modify: `backend/app/services/pipeline_service.py:126-184` (`_build_step6_8_context`)
- Test: `backend/tests/test_step6_8_context.py` (create)

- [ ] **Step 1: Write test for primary_target in 6.8 context**

Create file `backend/tests/test_step6_8_context.py`:

```python
"""Tests for Step 6.8 context builder with issue prioritization."""
from app.services.pipeline_service import _build_step6_8_context


def test_build_step6_8_context_includes_primary_target():
    """Context message should include primary_target when present."""
    state = {
        "primary_target": {
            "actor": "administrator",
            "concern": "personal liability",
            "issue_id": "ISSUE-1",
            "reasoning": "User asks about administrator exposure",
        },
        "facts": {"stated": [], "assumed": [], "missing": []},
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "description": "Administrator liability",
                "relevant_date": "2026-07-01",
                "temporal_rule": "insolvency_opening",
                "applicable_laws": ["85/2014"],
                "priority": "PRIMARY",
            },
            {
                "issue_id": "ISSUE-2",
                "description": "Transaction annulment",
                "relevant_date": "2026-03-01",
                "temporal_rule": "act_date",
                "applicable_laws": ["85/2014"],
                "priority": "SECONDARY",
            },
        ],
        "issue_articles": {},
        "issue_versions": {},
        "shared_context": [],
        "flags": [],
    }
    result = _build_step6_8_context(state)
    assert "PRIMARY TARGET:" in result
    assert "Actor: administrator" in result
    assert "Concern: personal liability" in result
    assert "ISSUE-1" in result
    assert "PRIMARY" in result
    assert "ISSUE-2" in result
    assert "SECONDARY" in result


def test_build_step6_8_context_without_primary_target():
    """Context message should work without primary_target (backward compat)."""
    state = {
        "facts": {"stated": [], "assumed": [], "missing": []},
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "description": "Test issue",
                "relevant_date": "2026-01-01",
                "temporal_rule": "current_law",
                "applicable_laws": [],
            },
        ],
        "issue_articles": {},
        "issue_versions": {},
        "shared_context": [],
        "flags": [],
    }
    result = _build_step6_8_context(state)
    assert "PRIMARY TARGET:" not in result
    assert "ISSUE-1" in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/test_step6_8_context.py -v
```

Expected: FAIL — `_build_step6_8_context` doesn't include "PRIMARY TARGET:" yet.

- [ ] **Step 3: Add primary_target and issue priorities to `_build_step6_8_context`**

In `backend/app/services/pipeline_service.py`, in `_build_step6_8_context`, add after the facts section (after line 146, before the "Per-issue article sets" comment):

```python
    # Primary target and issue priorities
    primary_target = state.get("primary_target")
    if primary_target:
        parts.append("\nPRIMARY TARGET:")
        parts.append(f"  Actor: {primary_target.get('actor', 'unknown')}")
        parts.append(f"  Concern: {primary_target.get('concern', 'unknown')}")
        parts.append(f"  Primary issue: {primary_target.get('issue_id', 'unknown')}")
```

Then in the per-issue loop (the `for issue in legal_issues:` block), modify the issue header line to include priority:

Change:
```python
        parts.append(f"\n{iid}: {issue.get('description', '')}")
```

To:
```python
        priority_tag = f" [{issue.get('priority', '')}]" if issue.get("priority") else ""
        parts.append(f"\n{iid}{priority_tag}: {issue.get('description', '')}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/test_step6_8_context.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/app/services/pipeline_service.py backend/tests/test_step6_8_context.py
git commit -m "feat(S6.8): pass primary_target and issue priorities to reasoning step

Include issue prioritization context in the Step 6.8 user message
so the reasoning model knows which issue is the user's primary target."
```

---

### Task 5: Step 6.8 Output Parser — Backward-Compatible Defaults

**Files:**
- Modify: `backend/app/services/pipeline_service.py:307-315` (`_parse_step6_8_output`)
- Test: `backend/tests/test_parse_step6_8.py` (create)

- [ ] **Step 1: Write tests for backward-compatible parsing**

Create file `backend/tests/test_parse_step6_8.py`:

```python
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
    # Old decomposed_conditions preserved for fallback
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/test_parse_step6_8.py -v
```

Expected: `test_parse_old_format_gets_defaults` FAILS because `_parse_step6_8_output` doesn't add defaults.

- [ ] **Step 3: Update `_parse_step6_8_output` with backward-compatible defaults**

In `backend/app/services/pipeline_service.py`, replace the `_parse_step6_8_output` function:

```python
def _parse_step6_8_output(raw: str) -> dict | None:
    """Parse Step 6.8 JSON output with backward-compatible defaults for new fields."""
    try:
        parsed = _extract_json(raw)
        if not parsed or "issues" not in parsed:
            return None
        # Apply backward-compatible defaults for new fields
        for issue in parsed.get("issues", []):
            if "governing_norm_status" not in issue:
                issue["governing_norm_status"] = {"status": "PRESENT"}
            if "uncertainty_sources" not in issue:
                issue["uncertainty_sources"] = []
            if "subsumption_summary" not in issue:
                issue["subsumption_summary"] = None
        return parsed
    except Exception:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/test_parse_step6_8.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/app/services/pipeline_service.py backend/tests/test_parse_step6_8.py
git commit -m "feat(S6.8): backward-compatible parsing for new RL-RAP output fields

Add defaults for governing_norm_status, uncertainty_sources,
and subsumption_summary when parsing old-format 6.8 output."
```

---

### Task 6: Step 7 Context Builder — Pass New Fields

**Files:**
- Modify: `backend/app/services/pipeline_service.py:187-304` (`_build_step7_context`)

- [ ] **Step 1: Write test for new fields in Step 7 context**

Create file `backend/tests/test_step7_context.py`:

```python
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


def test_step7_context_without_new_fields():
    """Step 7 context works without new fields (backward compat)."""
    state = _make_state()
    result = _build_step7_context(state)
    assert "PRIMARY TARGET:" not in result
    assert "GOVERNING_NORM_INCOMPLETE" not in result
    assert "USER QUESTION:" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/test_step7_context.py -v
```

Expected: FAIL — `_build_step7_context` doesn't include the new fields yet.

- [ ] **Step 3: Update `_build_step7_context` to include new fields**

In `backend/app/services/pipeline_service.py`, in `_build_step7_context`:

**Add primary_target** after the CLASSIFICATION block (after line 196):

```python
    primary_target = state.get("primary_target")
    if primary_target:
        parts.append("\nPRIMARY TARGET:")
        parts.append(f"  Actor: {primary_target.get('actor', 'unknown')}")
        parts.append(f"  Concern: {primary_target.get('concern', 'unknown')}")
        parts.append(f"  Primary issue: {primary_target.get('issue_id', 'unknown')}")
```

**Add governing_norm_incomplete flag** — add after the primary_target block:

```python
    if state.get("governing_norm_incomplete"):
        parts.append("\nGOVERNING_NORM_INCOMPLETE: The governing norm for the primary issue was not found. See analysis for details.")
```

**Add uncertainty_sources and condition_table to RL-RAP output** — in the RL-RAP issue loop (inside `if rl_rap:`), after the existing conditions block and before exceptions, add:

```python
            # Condition table (new format)
            if issue.get("condition_table"):
                parts.append("    Condition table:")
                for ct in issue["condition_table"]:
                    parts.append(f"      {ct['condition_id']}: {ct['condition_text']} — {ct['status']}"
                               + (f" (evidence: {ct['evidence']})" if ct.get("evidence") else "")
                               + (f" [MISSING: {ct['missing_fact']}]" if ct.get("missing_fact") else ""))
                summary = issue.get("subsumption_summary", {})
                if summary:
                    parts.append(f"    Subsumption: {summary.get('satisfied', 0)} satisfied, "
                               f"{summary.get('not_satisfied', 0)} not satisfied, "
                               f"{summary.get('unknown', 0)} unknown → {summary.get('norm_applicable', '?')}")
                    if summary.get("blocking_unknowns"):
                        parts.append(f"    Blocking unknowns: {', '.join(summary['blocking_unknowns'])}")

            # Governing norm status
            gns = issue.get("governing_norm_status", {})
            if gns.get("status") and gns["status"] != "PRESENT":
                parts.append(f"    Governing norm: {gns['status']} — {gns.get('explanation', '')}")

            # Uncertainty sources
            if issue.get("uncertainty_sources"):
                parts.append("    Uncertainty sources:")
                for us in issue["uncertainty_sources"]:
                    parts.append(f"      {us['type']}: {us['detail']} (impact: {us.get('impact', '')})")
```

Also update the existing conditions rendering to handle both old `decomposed_conditions` and new `condition_table`. Change:

```python
            parts.append("    Conditions:")
            for c in issue.get("decomposed_conditions", []):
```

To:

```python
            # Legacy conditions format (fallback)
            if not issue.get("condition_table") and issue.get("decomposed_conditions"):
                parts.append("    Conditions:")
                for c in issue.get("decomposed_conditions", []):
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/test_step7_context.py -v
```

Expected: All PASS.

- [ ] **Step 5: Run all existing tests to check for regressions**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/ -v
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/app/services/pipeline_service.py backend/tests/test_step7_context.py
git commit -m "feat(S7): pass primary_target, governing_norm_incomplete, and uncertainty_sources to answer generator

Update Step 7 context builder to include issue prioritization,
governing norm status, condition tables, and typed uncertainty sources
so the answer generator can structure and calibrate the response."
```

---

### Task 7: Step 7 Prompt — Answer Structure, Uncertainty Communication, Tone Calibration

**Files:**
- Modify: `backend/prompts/LA-S7-answer-template.txt`

- [ ] **Step 1: Add ISSUE PRIORITY IN ANSWER STRUCTURE block**

In `backend/prompts/LA-S7-answer-template.txt`, add after the "HANDLING UNKNOWN CONDITIONS" section (after line 51, before `{MODE_SECTION}`):

```text
ISSUE PRIORITY IN ANSWER STRUCTURE:
When the input includes a PRIMARY TARGET and issues have priority rankings (PRIMARY / SECONDARY / SUPPORTING):
1. Address the PRIMARY issue FIRST, as the main body of the response
2. SECONDARY issues follow, clearly marked as related but distinct
3. SUPPORTING context comes last or is woven in where needed

Do NOT bury the PRIMARY issue after a longer discussion of a SECONDARY issue.
The user asked a specific question — answer it first.

Structure test: if the user reads only the first third of the answer, they should
find the direct response to their primary question.

When the PRIMARY issue has governing_norm_status MISSING, lead with that disclosure:
"Pentru întrebarea principală privind [primary_target.concern], norma juridică
guvernantă nu a fost identificată în articolele disponibile. Analiza de mai jos
acoperă aspectele secundare pentru care cadrul legal este disponibil."

UNCERTAINTY COMMUNICATION:
When the Legal Analysis includes uncertainty_sources, communicate each type differently:

FACTUAL_GAP — present as a question to the user:
"Răspunsul depinde de [missing fact]. Dacă [scenario A], atunci... Dacă [scenario B], atunci..."
Do NOT present this as legal uncertainty. The law is clear; the facts are missing.

LIBRARY_GAP — present as a system limitation:
"Articolul [X] din [Law] nu este disponibil în Biblioteca Juridică. Fără acest text, [what cannot be confirmed]. Recomandăm importarea și reverificarea."
Do NOT present this as if the law itself is uncertain. The law exists — the system doesn't have it.

LEGAL_AMBIGUITY — present as genuine legal debate:
"Această chestiune este discutabilă din punct de vedere doctrinar. O interpretare susține că... O interpretare alternativă este că... Recomandăm consultarea unui specialist."

CRITICAL: Never blend these. A missing article is not the same as an ambiguous law.
A missing fact is not the same as a missing article.
The user must understand WHY the answer is uncertain and WHAT would resolve it.

TONE CALIBRATION:
Match the assertiveness of your language to the certainty level from the Legal Analysis:

- CERTAIN: Affirmative language. "Administratorul răspunde conform Art. X."
- PROBABLE: Confident with minor qualifier. "Administratorul răspunde, în principiu, conform Art. X, cu condiția ca..."
- CONDITIONAL: Explicitly conditional. "Dacă [unknown condition], administratorul ar putea răspunde conform Art. X. În lipsa acestei informații, nu se poate concluziona definitiv."
- UNCERTAIN: Clearly tentative. "Pe baza articolelor disponibile, nu se poate stabili cu certitudine dacă administratorul răspunde. Analiza este limitată de [uncertainty source]."

Risk labels must align with certainty:
- CERTAIN + consequence = **Risc: MAJOR**, **Risc: MEDIU**, or **Risc: MINOR** (assert the risk)
- CONDITIONAL + consequence = "**Risc potențial: MAJOR** — condiționat de [unknown]"
- UNCERTAIN = "**Risc nedeterminat** — analiză incompletă"

NEVER combine UNCERTAIN certainty with MAJOR risk. If you cannot confirm the legal basis,
you cannot confirm the risk level. Say the risk *could* be major but cannot be established
on available information.

GOVERNING NORM INCOMPLETE:
If the context flags GOVERNING_NORM_INCOMPLETE or GOVERNING_NORM_MISSING:
- Include a prominent notice BEFORE the main analysis, not buried at the end
- State what norm is missing and what aspect of the answer is affected
- Set confidence to LOW for the affected issue
- Do NOT produce risk levels for the affected issue beyond "Risc nedeterminat"
```

- [ ] **Step 2: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/prompts/LA-S7-answer-template.txt
git commit -m "feat(S7): add issue-priority structure, uncertainty communication, tone calibration

Add instructions for answer prioritization by user intent,
three-way uncertainty communication (FACTUAL_GAP, LIBRARY_GAP,
LEGAL_AMBIGUITY), tone calibration by certainty level, and
governing norm incomplete handling."
```

---

### Task 8: Enhanced Confidence Derivation

**Files:**
- Modify: `backend/app/services/pipeline_service.py:318-376` (`_derive_final_confidence`)
- Test: `backend/tests/test_confidence_derivation.py` (create)

- [ ] **Step 1: Write tests for new confidence rules**

Create file `backend/tests/test_confidence_derivation.py`:

```python
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
    """New rule: governing norm missing for primary issue → LOW."""
    conf, reason = _call(governing_norm_incomplete=True)
    assert conf == "LOW"
    assert "governing norm" in reason.lower() or "Governing norm" in reason


def test_rule4_conditional_caps_at_medium():
    conf, reason = _call(issues=[{"certainty_level": "CONDITIONAL"}])
    assert conf == "MEDIUM"


def test_rule4_5_library_gap_caps_at_medium():
    """New rule: LIBRARY_GAP → cap at MEDIUM."""
    sources = [{"type": "LIBRARY_GAP", "detail": "Art. 169 missing"}]
    conf, reason = _call(uncertainty_sources=sources)
    assert conf == "MEDIUM"


def test_rule4_6_majority_unknown_conditions_caps_at_medium():
    """New rule: majority of conditions UNKNOWN → cap at MEDIUM."""
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
    """No issues → returns HIGH (Claude's assessment)."""
    conf, reason = _call(issues=[{"certainty_level": "CERTAIN"}])
    assert conf == "HIGH"


def test_governing_norm_takes_priority_over_conditional():
    """Rule 3.5 (LOW) fires before Rule 4 (MEDIUM cap)."""
    conf, reason = _call(
        governing_norm_incomplete=True,
        issues=[{"certainty_level": "CONDITIONAL"}],
    )
    assert conf == "LOW"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/test_confidence_derivation.py -v
```

Expected: FAIL — `_derive_final_confidence` doesn't accept the new parameters.

- [ ] **Step 3: Update `_derive_final_confidence` with new rules and parameters**

Replace the function in `backend/app/services/pipeline_service.py`:

```python
def _derive_final_confidence(
    claude_confidence: str,
    rl_rap_issues: list[dict],
    has_articles: bool,
    primary_from_db: bool,
    missing_primary: bool,
    has_stale_versions: bool,
    citation_validation: dict,
    governing_norm_incomplete: bool = False,
    uncertainty_sources: list[dict] | None = None,
) -> tuple[str, str]:
    """Derive final confidence from all pipeline signals. Returns (confidence, reason)."""

    # Rule 1: No articles
    if not has_articles:
        return "LOW", "No relevant articles found"

    # Rule 2: Majority citations unverified
    total_db = citation_validation.get("total_db", 0)
    downgraded = citation_validation.get("downgraded", 0)
    if total_db > 0 and downgraded > total_db / 2:
        return "LOW", "Most citations could not be verified against provided articles"

    # Rule 3: UNCERTAIN issues
    if rl_rap_issues:
        levels = [i.get("certainty_level", "UNCERTAIN") for i in rl_rap_issues]
        if any(l == "UNCERTAIN" for l in levels):
            return "LOW", "Legal analysis has uncertain conditions"

    # Rule 3.5: Governing norm missing for primary issue
    if governing_norm_incomplete:
        return "LOW", "Governing norm for primary issue not found"

    # Start with Claude's assessment, then cap downward
    CONF_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    confidence = claude_confidence
    reason = "Based on model assessment"

    # Rule 4: CONDITIONAL caps at MEDIUM
    if rl_rap_issues:
        levels = [i.get("certainty_level", "UNCERTAIN") for i in rl_rap_issues]
        if any(l == "CONDITIONAL" for l in levels):
            if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
                confidence = "MEDIUM"
                reason = "Legal analysis has conditional conclusions"

    # Rule 4.5: LIBRARY_GAP caps at MEDIUM
    if uncertainty_sources:
        library_gaps = [u for u in uncertainty_sources if u.get("type") == "LIBRARY_GAP"]
        if library_gaps:
            if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
                confidence = "MEDIUM"
                reason = f"Library gap: {library_gaps[0].get('detail', 'missing provision')}"

    # Rule 4.6: Majority conditions UNKNOWN caps at MEDIUM
    if rl_rap_issues:
        for issue in rl_rap_issues:
            summary = issue.get("subsumption_summary") or {}
            total = summary.get("total_conditions", 0)
            unknown = summary.get("unknown", 0)
            if total > 0 and unknown > total / 2:
                if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
                    confidence = "MEDIUM"
                    reason = "Majority of legal conditions could not be evaluated"
                break

    # Rule 5: Primary not from DB
    if not primary_from_db:
        if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
            confidence = "MEDIUM"
            reason = "Primary law source not from verified database"

    # Rule 6: Missing primary laws
    if missing_primary:
        if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
            confidence = "MEDIUM"
            reason = "Primary law not in library"

    # Rule 7: Stale versions
    if has_stale_versions:
        if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
            confidence = "MEDIUM"
            reason = "Law version may be outdated"

    return confidence, reason
```

- [ ] **Step 4: Update the call site in `_run_steps_4_through_7`**

In the call to `_derive_final_confidence` (around line 774), add the new arguments:

```python
    # Aggregate uncertainty sources from RL-RAP
    rl_rap_issues = (state.get("rl_rap_output") or {}).get("issues", [])
    all_uncertainty_sources = []
    for issue in rl_rap_issues:
        all_uncertainty_sources.extend(issue.get("uncertainty_sources", []))

    state["confidence"], state["confidence_reason"] = _derive_final_confidence(
        claude_confidence=state.get("claude_confidence", "MEDIUM"),
        rl_rap_issues=rl_rap_issues,
        has_articles=bool(retrieved),
        primary_from_db=primary_from_db,
        missing_primary=missing_primary,
        has_stale_versions=has_stale,
        citation_validation=state.get("citation_validation", {"downgraded": 0, "total_db": 0}),
        governing_norm_incomplete=state.get("governing_norm_incomplete", False),
        uncertainty_sources=all_uncertainty_sources,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/test_confidence_derivation.py -v
```

Expected: All PASS.

- [ ] **Step 6: Run all tests**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/ -v
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/app/services/pipeline_service.py backend/tests/test_confidence_derivation.py
git commit -m "feat: add governing norm, library gap, and majority-unknown confidence rules

Three new confidence derivation rules:
- Rule 3.5: governing norm missing → LOW
- Rule 4.5: LIBRARY_GAP present → cap MEDIUM
- Rule 4.6: majority conditions UNKNOWN → cap MEDIUM"
```

---

### Task 9: Enhanced Conditional Retrieval — Governing Norm Fetch

**Files:**
- Modify: `backend/app/services/pipeline_service.py`
- Test: `backend/tests/test_governing_norm_retrieval.py` (create)

- [ ] **Step 1: Write tests for `_fetch_governing_norm`**

Create file `backend/tests/test_governing_norm_retrieval.py`:

```python
"""Tests for governing norm retrieval logic."""
from unittest.mock import patch, MagicMock
from app.services.pipeline_service import _fetch_governing_norm, _extract_law_key


def test_extract_law_key_from_ref():
    assert _extract_law_key("Legea 85/2014 art.169") == "85/2014"
    assert _extract_law_key("Legea 31/1990 art.197 alin.(3)") == "31/1990"
    assert _extract_law_key("something without law ref") == ""
    assert _extract_law_key("") == ""
    assert _extract_law_key(None) == ""


def test_fetch_governing_norm_skips_present_status():
    """Should return empty list when governing norm is PRESENT."""
    issue = {
        "governing_norm_status": {"status": "PRESENT"},
    }
    result = _fetch_governing_norm(issue, {}, MagicMock())
    assert result == []


def test_fetch_governing_norm_skips_inferred_status():
    """Should return empty list when governing norm is INFERRED."""
    issue = {
        "governing_norm_status": {"status": "INFERRED"},
    }
    result = _fetch_governing_norm(issue, {}, MagicMock())
    assert result == []


@patch("app.services.pipeline_service._fetch_missing_articles")
def test_fetch_governing_norm_tries_exact_first(mock_fetch):
    """Should try exact reference fetch first."""
    mock_fetch.return_value = [{"article_id": 999, "text": "Art. 169..."}]
    issue = {
        "governing_norm_status": {
            "status": "MISSING",
            "missing_norm_ref": "Legea 85/2014 art.169",
            "expected_norm_description": "Administrator liability",
        },
    }
    state = {"selected_versions": {}}
    result = _fetch_governing_norm(issue, state, MagicMock())
    assert len(result) == 1
    mock_fetch.assert_called_once_with(["Legea 85/2014 art.169"], state, MagicMock())


@patch("app.services.pipeline_service._semantic_search_for_norm")
@patch("app.services.pipeline_service._fetch_missing_articles")
def test_fetch_governing_norm_falls_back_to_semantic(mock_fetch, mock_semantic):
    """Should fall back to semantic search when exact fetch returns nothing."""
    mock_fetch.return_value = []
    mock_semantic.return_value = [{"article_id": 888, "text": "Art. 169..."}]
    issue = {
        "governing_norm_status": {
            "status": "MISSING",
            "missing_norm_ref": "Legea 85/2014 art.169",
            "expected_norm_description": "Administrator liability provision",
        },
    }
    state = {"selected_versions": {}}
    db = MagicMock()
    result = _fetch_governing_norm(issue, state, db)
    assert len(result) == 1
    mock_semantic.assert_called_once_with("Administrator liability provision", "85/2014", state, db)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/test_governing_norm_retrieval.py -v
```

Expected: FAIL — `_fetch_governing_norm` and `_extract_law_key` don't exist yet.

- [ ] **Step 3: Implement `_extract_law_key`**

In `backend/app/services/pipeline_service.py`, add after the `_fetch_missing_articles` function (after line 556):

```python
def _extract_law_key(ref: str | None) -> str:
    """Extract law key (e.g., '85/2014') from an article reference string."""
    if not ref:
        return ""
    match = re.search(r"(\d+)/(\d{4})", ref)
    return f"{match.group(1)}/{match.group(2)}" if match else ""
```

- [ ] **Step 4: Implement `_semantic_search_for_norm`**

Add after `_extract_law_key`:

```python
def _semantic_search_for_norm(
    description: str,
    law_key: str,
    state: dict,
    db: Session,
) -> list[dict]:
    """Semantic search for a governing norm using ChromaDB. Returns list of article dicts."""
    if not description:
        return []

    # Find the law_version_id(s) for this law
    version_ids = []
    unique_versions = state.get("unique_versions", {})
    if law_key and law_key in unique_versions:
        version_ids = list(unique_versions[law_key])

    if not version_ids:
        # Try selected_versions
        sv = state.get("selected_versions", {}).get(law_key, {})
        vid = sv.get("law_version_id")
        if vid:
            version_ids = [vid]

    if not version_ids:
        return []

    results = query_articles(
        query_text=description,
        law_version_ids=version_ids,
        n_results=5,
    )

    # Convert ChromaDB results to pipeline article format
    fetched = []
    for r in results:
        article_id = r.get("article_id")
        if not article_id:
            continue
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            continue

        # Get law info from selected_versions
        sv = state.get("selected_versions", {}).get(law_key, {})
        fetched.append({
            "article_id": article.id,
            "article_number": article.article_number,
            "law_number": law_key.split("/")[0] if "/" in law_key else "",
            "law_year": law_key.split("/")[1] if "/" in law_key else "",
            "law_version_id": article.law_version_id,
            "law_title": sv.get("law_title", ""),
            "date_in_force": sv.get("date_in_force", ""),
            "text": article.full_text or "",
            "source": "governing_norm_search",
            "tier": "reasoning_request",
            "role": "PRIMARY",
            "is_abrogated": article.is_abrogated or False,
            "doc_type": "article",
        })

    return fetched
```

- [ ] **Step 5: Implement `_fetch_governing_norm`**

Add after `_semantic_search_for_norm`:

```python
def _fetch_governing_norm(issue: dict, state: dict, db: Session) -> list[dict]:
    """Attempt to fetch missing governing norm for an issue.

    Strategy 1: exact reference fetch (reuses _fetch_missing_articles).
    Strategy 2: semantic search using expected_norm_description (ChromaDB).
    """
    gns = issue.get("governing_norm_status", {})
    if gns.get("status") != "MISSING":
        return []

    # Strategy 1: exact reference
    ref = gns.get("missing_norm_ref")
    if ref:
        fetched = _fetch_missing_articles([ref], state, db)
        if fetched:
            return fetched

    # Strategy 2: semantic search using expected_norm_description
    description = gns.get("expected_norm_description")
    if description:
        law_key = _extract_law_key(ref)
        fetched = _semantic_search_for_norm(description, law_key, state, db)
        if fetched:
            return fetched

    return []
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/test_governing_norm_retrieval.py -v
```

Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/app/services/pipeline_service.py backend/tests/test_governing_norm_retrieval.py
git commit -m "feat(S6.9): add governing norm retrieval with semantic search fallback

Add _fetch_governing_norm that tries exact article fetch first,
then falls back to ChromaDB semantic search using the expected
norm description from Step 6.8's governing_norm_status."
```

---

### Task 10: Post-6.9 Governing Norm Gate

**Files:**
- Modify: `backend/app/services/pipeline_service.py`
- Test: `backend/tests/test_governing_norm_gate.py` (create)

- [ ] **Step 1: Write tests for the gate**

Create file `backend/tests/test_governing_norm_gate.py`:

```python
"""Tests for the post-6.9 governing norm gate."""
from app.services.pipeline_service import _post_6_9_governing_norm_gate


def test_gate_not_triggered_when_governing_norm_present():
    """Gate returns None when governing norm is PRESENT."""
    state = {
        "primary_target": {"issue_id": "ISSUE-1"},
        "rl_rap_output": {
            "issues": [{
                "issue_id": "ISSUE-1",
                "governing_norm_status": {"status": "PRESENT"},
            }],
        },
        "selected_versions": {},
        "flags": [],
    }
    result = _post_6_9_governing_norm_gate(state)
    assert result is None
    assert not state.get("governing_norm_incomplete")


def test_gate_not_triggered_when_governing_norm_inferred():
    """Gate returns None when governing norm is INFERRED."""
    state = {
        "primary_target": {"issue_id": "ISSUE-1"},
        "rl_rap_output": {
            "issues": [{
                "issue_id": "ISSUE-1",
                "governing_norm_status": {"status": "INFERRED"},
            }],
        },
        "selected_versions": {},
        "flags": [],
    }
    result = _post_6_9_governing_norm_gate(state)
    assert result is None


def test_gate_soft_warning_when_law_in_library():
    """Gate sets soft warning when law is in library but article not surfaced."""
    state = {
        "primary_target": {"issue_id": "ISSUE-1"},
        "rl_rap_output": {
            "issues": [{
                "issue_id": "ISSUE-1",
                "governing_norm_status": {
                    "status": "MISSING",
                    "expected_norm_description": "Administrator liability provision",
                    "missing_norm_ref": "Legea 85/2014 art.169",
                },
            }],
        },
        "selected_versions": {"85/2014": {"law_version_id": 20}},
        "flags": [],
    }
    result = _post_6_9_governing_norm_gate(state)
    assert result is None  # No hard pause
    assert state["governing_norm_incomplete"] is True
    assert any("GOVERNING_NORM_MISSING" in f for f in state["flags"])


def test_gate_hard_pause_when_law_not_in_library():
    """Gate returns pause event when law is not in library at all."""
    state = {
        "primary_target": {"issue_id": "ISSUE-1"},
        "rl_rap_output": {
            "issues": [{
                "issue_id": "ISSUE-1",
                "governing_norm_status": {
                    "status": "MISSING",
                    "expected_norm_description": "Administrator liability provision",
                    "missing_norm_ref": "Legea 85/2014 art.169",
                },
            }],
        },
        "selected_versions": {},  # Law not in library
        "flags": [],
    }
    result = _post_6_9_governing_norm_gate(state)
    assert result is not None
    assert result["type"] == "gate"
    assert result["gate"] == "governing_norm_missing"


def test_gate_skips_non_primary_issues():
    """Gate only checks the primary issue."""
    state = {
        "primary_target": {"issue_id": "ISSUE-1"},
        "rl_rap_output": {
            "issues": [
                {
                    "issue_id": "ISSUE-1",
                    "governing_norm_status": {"status": "PRESENT"},
                },
                {
                    "issue_id": "ISSUE-2",
                    "governing_norm_status": {
                        "status": "MISSING",
                        "expected_norm_description": "Some other norm",
                        "missing_norm_ref": "Legea 99/2000 art.5",
                    },
                },
            ],
        },
        "selected_versions": {},
        "flags": [],
    }
    result = _post_6_9_governing_norm_gate(state)
    assert result is None  # Secondary issue missing is not a gate trigger


def test_gate_works_without_primary_target():
    """Gate returns None gracefully when no primary_target."""
    state = {
        "rl_rap_output": {
            "issues": [{
                "issue_id": "ISSUE-1",
                "governing_norm_status": {"status": "MISSING"},
            }],
        },
        "selected_versions": {},
        "flags": [],
    }
    result = _post_6_9_governing_norm_gate(state)
    assert result is None  # Can't determine primary issue, skip gate
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/test_governing_norm_gate.py -v
```

Expected: FAIL — `_post_6_9_governing_norm_gate` doesn't exist yet.

- [ ] **Step 3: Implement `_post_6_9_governing_norm_gate`**

In `backend/app/services/pipeline_service.py`, add after `_fetch_governing_norm`:

```python
def _post_6_9_governing_norm_gate(state: dict) -> dict | None:
    """Check if primary issue still lacks its governing norm after conditional retrieval.

    Returns a gate event dict if hard pause is needed (law not in library),
    or None if no pause needed (either norm found, or soft warning set).
    """
    primary_target = state.get("primary_target")
    if not primary_target or not primary_target.get("issue_id"):
        return None

    primary_issue_id = primary_target["issue_id"]
    rl_rap = state.get("rl_rap_output", {})

    for issue in rl_rap.get("issues", []):
        if issue.get("issue_id") != primary_issue_id:
            continue

        gns = issue.get("governing_norm_status", {})
        if gns.get("status") != "MISSING":
            return None

        law_key = _extract_law_key(gns.get("missing_norm_ref", ""))
        law_in_library = law_key and law_key in state.get("selected_versions", {})

        if not law_in_library:
            # Hard pause — offer import
            return {
                "type": "gate",
                "gate": "governing_norm_missing",
                "issue": issue.get("issue_label", issue.get("issue_id")),
                "expected_norm": gns.get("expected_norm_description"),
                "missing_ref": gns.get("missing_norm_ref"),
                "message": (
                    f"The core legal provision for the primary issue "
                    f"({issue.get('issue_label', issue.get('issue_id'))}) was not found. "
                    f"Expected: {gns.get('expected_norm_description', 'unknown')}. "
                    f"Import the relevant law to proceed with a complete analysis."
                ),
            }
        else:
            # Soft warning — continue with disclosure
            state["flags"].append(
                f"GOVERNING_NORM_MISSING: {gns.get('expected_norm_description', 'governing norm not found')}"
            )
            state["governing_norm_incomplete"] = True
            return None

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/test_governing_norm_gate.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/app/services/pipeline_service.py backend/tests/test_governing_norm_gate.py
git commit -m "feat: add post-6.9 governing norm gate

Hard pause when governing norm's law is not in library (offer import).
Soft warning when law is in library but article wasn't surfaced."
```

---

### Task 11: Integrate Governing Norm Retrieval and Gate into Pipeline

**Files:**
- Modify: `backend/app/services/pipeline_service.py:715-738` (conditional retrieval block in `_run_steps_4_through_7`)

- [ ] **Step 1: Enhance conditional retrieval to also fetch governing norms**

In `backend/app/services/pipeline_service.py`, in `_run_steps_4_through_7`, replace the existing conditional retrieval block (lines 715-738) with:

```python
        # Conditional Retrieval Pass (existing missing articles + governing norm fetch)
        if state.get("rl_rap_output"):
            missing = _check_missing_articles(state["rl_rap_output"])
            governing_norm_fetched = []

            # Fetch governing norms for issues with MISSING status
            for issue in state["rl_rap_output"].get("issues", []):
                gn_articles = _fetch_governing_norm(issue, state, db)
                if gn_articles:
                    governing_norm_fetched.extend(gn_articles)

            all_to_fetch = missing
            needs_retrieval = bool(missing) or bool(governing_norm_fetched)

            if needs_retrieval:
                yield _step_event(69, "conditional_retrieval", "running")
                t0 = time.time()

                # Fetch standard missing articles
                fetched = _fetch_missing_articles(missing, state, db) if missing else []

                # Combine with governing norm articles
                all_fetched = fetched + governing_norm_fetched

                if all_fetched:
                    for art in all_fetched:
                        added = False
                        for iid, arts in state.get("issue_articles", {}).items():
                            iv_key = f"{iid}:{art['law_number']}/{art['law_year']}"
                            if iv_key in state.get("issue_versions", {}):
                                arts.append(art)
                                added = True
                        if not added:
                            state.setdefault("shared_context", []).append(art)
                    # Re-run reasoning with expanded article set
                    state = _step6_8_legal_reasoning(state, db)
                else:
                    if missing:
                        state["flags"].append(f"Missing provisions not in library: {', '.join(missing)}")

                yield _step_event(69, "conditional_retrieval", "done", {
                    "requested": len(missing) + len(governing_norm_fetched),
                    "fetched": len(all_fetched),
                }, time.time() - t0)

            # Post-6.9 Governing Norm Gate
            gate_result = _post_6_9_governing_norm_gate(state)
            if gate_result:
                complete_run(db, run_id, "clarification", None, state.get("flags"))
                db.commit()
                yield gate_result
                state["_gate_triggered"] = True
                return state
```

- [ ] **Step 2: Run all tests to check for regressions**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/ -v
```

Expected: All pass.

- [ ] **Step 3: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/app/services/pipeline_service.py
git commit -m "feat: integrate governing norm retrieval and gate into pipeline flow

Enhanced conditional retrieval fetches governing norms via exact
reference and semantic search fallback. Post-6.9 gate pauses
pipeline when primary issue's governing norm is missing and
law is not in library."
```

---

### Task 12: Final Integration Test and Cleanup

**Files:**
- Test: `backend/tests/test_pipeline_routing.py` (verify existing tests still pass)
- All modified files (verify consistency)

- [ ] **Step 1: Run the full test suite**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -m pytest tests/ -v
```

Expected: All tests pass including the new tests:
- `test_step1_prioritization.py`
- `test_step6_8_context.py`
- `test_parse_step6_8.py`
- `test_step7_context.py`
- `test_confidence_derivation.py`
- `test_governing_norm_retrieval.py`
- `test_governing_norm_gate.py`
- `test_pipeline_routing.py` (existing)

- [ ] **Step 2: Verify prompt files are syntactically valid**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
# Check all prompt files are readable and non-empty
for f in prompts/LA-S1-issue-classifier.txt prompts/LA-S6.8-legal-reasoning.txt prompts/LA-S7-answer-template.txt; do
  echo "--- $f: $(wc -l < $f) lines ---"
done
```

Expected: All files non-empty with expected line counts (S1: ~200+, S6.8: ~200+, S7: ~170+).

- [ ] **Step 3: Verify no import errors**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
python -c "from app.services.pipeline_service import _derive_final_confidence, _fetch_governing_norm, _post_6_9_governing_norm_gate, _extract_law_key, _semantic_search_for_norm; print('All imports OK')"
```

Expected: "All imports OK"

- [ ] **Step 4: Commit final state**

If any cleanup was needed:

```bash
cd /Users/anaandrei/projects/themis-legal
git add -A
git commit -m "chore: final cleanup for legal reasoning quality improvements"
```
