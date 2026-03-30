# Legal Reasoning Quality: Issue Prioritization, Governing Norm Detection, and Subsumption Rigor

**Date:** 2026-03-30
**Status:** Approved
**Scope:** Steps 1, 6.8, 6.9, post-6.9 gate, 7, and confidence derivation

## Problem Statement

A diagnostic failure case exposed eight general pipeline weaknesses that affect legal analysis across all domains — not just insolvency or company law. The system:

1. Prioritized a secondary legal issue over the user's primary question
2. Missed the governing norm for the main legal consequence
3. Produced risk conclusions inconsistent with factual certainty
4. Did not perform rigorous condition-by-condition subsumption
5. Blurred legal uncertainty, factual gaps, and library gaps
6. Used tone more certain than the analysis justified
7. Did not surface all relevant consequence layers
8. Communicated temporal reasoning unclearly

This design addresses items 1-6 as Tier 1 and Tier 2 priorities. Items 7-8 are deferred to a future design round.

### Priority Order and Rationale

1. **Issue prioritization** — if the system answers the wrong question, everything downstream is weaker
2. **Governing norm detection** — if the governing norm is missing, the answer can look convincing but be legally wrong
3. **Condition-by-condition subsumption rigor** — the core of lawyer-like reasoning
4. **Risk calibration vs. certainty** — never output strong risk conclusions when essential conditions are unknown
5. **Legal uncertainty vs. data gaps vs. factual gaps** — critical for trustworthiness
6. **Tone calibration** — the answer should reflect the reasoning's actual certainty

## Approach

**Approach B: Prompt + Structural Enforcement** — rewrite prompts for Steps 1, 6.8, and 7, and add structural enforcement via new output fields, a post-6.9 governing norm gate, and enhanced confidence derivation. No new pipeline steps beyond the gate. No changes to retrieval (Steps 4-6), existing gates (2.5, 6.5), or mode-specific templates.

Rejected alternatives:
- **Approach A (Prompt-only):** No structural enforcement. The model can still shortcut subsumption and miss governing norms without pipeline-level detection.
- **Approach C (Full reasoning decomposition):** Split Step 6.8 into 4 sub-calls. Maximum enforcement but 4x token cost, higher latency, and more complex pipeline code. Worth revisiting if Approach B proves insufficient.

---

## Section 1: Step 1 — Issue Prioritization

### Current State

Step 1 (LA-S1-issue-classifier.txt) produces `core_issue`, `sub_issues`, and `legal_issues`, but nothing ranks issues by user intent. All issues are treated equally downstream.

### Changes

#### New Output Fields

Add `primary_target` at the top level and `priority` per issue:

```json
{
  "primary_target": {
    "actor": "administrator",
    "concern": "personal liability / legal exposure",
    "issue_id": "ISSUE-1",
    "reasoning": "User asks 'is the administrator affected' — the question targets the administrator's legal position, not the transaction itself"
  },
  "legal_issues": [
    {
      "issue_id": "ISSUE-1",
      "description": "...",
      "priority": "PRIMARY",
      "priority_reasoning": "Directly addresses the user's question about administrator exposure",
      "...existing fields..."
    },
    {
      "issue_id": "ISSUE-2",
      "description": "...",
      "priority": "SECONDARY",
      "priority_reasoning": "Related transaction annulment issue, but not the user's direct question",
      "...existing fields..."
    }
  ]
}
```

#### New Prompt Instructions

Add after the current classification rules:

> **ISSUE PRIORITIZATION (REQUIRED):**
>
> Before decomposing legal issues, identify the user's primary target:
> - **Who** is the user asking about? (the legally relevant actor)
> - **What** does the user want to know about that actor? (liability, obligation, right, risk, eligibility, compliance)
>
> Then rank each legal issue:
> - **PRIMARY**: Directly answers what the user asked about the target actor
> - **SECONDARY**: Legally related but not the user's direct question
> - **SUPPORTING**: Background context needed to analyze primary/secondary issues
>
> The test: if you could only answer one issue, which one would the user consider their question answered? That is PRIMARY.
>
> Common prioritization failures to avoid:
> - Prioritizing a transaction's validity over the actor's liability when the user asks about the actor
> - Prioritizing procedural issues over substantive rights when the user asks about rights
> - Prioritizing the means (e.g., annulment action) over the consequence (e.g., personal liability)

#### What Stays the Same

All existing fields, complexity assessment, temporal decomposition, applicable laws identification. Changes are additive.

---

## Section 2: Step 6.8 — Governing Norm Detection, Subsumption Rigor, Uncertainty Typing

### 2A: Governing Norm Detection

#### Current State

Step 6.8 identifies operative articles and assigns PRIMARY/SECONDARY/SUPPORTING priority, but does not explicitly assess whether the norm governing the *main* legal consequence is present.

#### New Output Field

Add `governing_norm_status` per issue, required before subsumption begins:

```json
{
  "governing_norm_status": {
    "status": "PRESENT | INFERRED | MISSING",
    "explanation": "The liability provision for administrators under insolvency law (Art. 169 Legea 85/2014) is not present in the provided articles.",
    "expected_norm_description": "A norm establishing personal liability conditions for the administrator in the context of insolvency",
    "missing_norm_ref": "Legea 85/2014 art.169"
  }
}
```

**Status definitions:**
- **PRESENT**: The norm that directly triggers the main legal consequence is among the provided articles.
- **INFERRED**: No single article explicitly governs the consequence, but the conclusion can be constructed from multiple provided norms with reasonable certainty.
- **MISSING**: The provided articles are related but do not contain the norm that governs the primary legal consequence.

#### New Prompt Instructions

> **GOVERNING NORM CHECK (REQUIRED — perform before subsumption):**
>
> For each issue, before beginning condition analysis, answer:
> "Do I have the specific norm that triggers the main legal consequence for this issue?"
>
> This is not about whether you have *relevant* articles. It is about whether you have *the* article — the one a lawyer would cite as the legal basis for the primary conclusion.
>
> Examples:
> - Having articles about transaction annulment but NOT the administrator liability provision → MISSING
> - Having the general duty of care but NOT the specific sanction for breach → MISSING
> - Having eligibility conditions for a subsidy but NOT the provision that grants or revokes it → MISSING
> - Having the dismissal procedure but NOT the article defining valid grounds → MISSING
>
> When status is MISSING:
> - Add the expected norm to `missing_articles_needed`
> - State clearly in the conclusion that the analysis is incomplete for this issue
> - Do NOT produce a confident conclusion based only on surrounding norms
> - Set certainty_level to UNCERTAIN unless secondary aspects can be analyzed independently
>
> When status is INFERRED:
> - Explain the reasoning chain from multiple norms to the conclusion
> - Set certainty_level no higher than PROBABLE

### 2B: Condition-by-Condition Subsumption Enforcement

#### Current State

The prompt specifies subsumption but the model shortcuts — it produces plausible conclusions without walking through each condition atomically. The flat `decomposed_conditions` list allows this.

#### New Output Structure

Replace `decomposed_conditions` with `condition_table` and `subsumption_summary`:

```json
{
  "condition_table": [
    {
      "condition_id": "C1",
      "norm_ref": "Legea 85/2014 art.169 alin.(1)",
      "condition_text": "the company is in insolvency proceedings",
      "source": "HYPOTHESIS | DISPOSITION | SANCTION_TRIGGER",
      "list_type": "AND | OR | null",
      "list_group": "G1",
      "status": "SATISFIED | NOT_SATISFIED | UNKNOWN",
      "evidence": "F1: company entered insolvency July 2026",
      "missing_fact": null
    }
  ],
  "subsumption_summary": {
    "total_conditions": 5,
    "satisfied": 2,
    "not_satisfied": 0,
    "unknown": 3,
    "norm_applicable": "CONDITIONAL",
    "blocking_unknowns": ["C2", "C4"]
  }
}
```

#### New Prompt Instructions

> **SUBSUMPTION ENFORCEMENT:**
>
> You MUST populate the `condition_table` completely before writing the `conclusion`. A conclusion without a complete condition table is invalid.
>
> For each RULE article (starting with PRIMARY):
> 1. Extract every atomic condition from the hypothesis. "Atomic" means a single factual predicate that can be independently true or false.
> 2. Do NOT merge multiple conditions into one row. "The administrator acted in bad faith and caused damage" is TWO conditions, not one.
> 3. For each condition, evaluate against stated facts only.
> 4. Populate the `subsumption_summary` by counting statuses.
>
> The `conclusion` must be logically derivable from the `subsumption_summary`:
> - If `norm_applicable` is CONDITIONAL, the conclusion MUST state what depends on which unknowns
> - If `norm_applicable` is false (NOT_SATISFIED on a necessary condition), the conclusion MUST state the norm does not apply and why
> - A conclusion that asserts a legal consequence while `blocking_unknowns` exist is invalid unless it explicitly conditions the consequence on those unknowns

### 2C: Three-Way Uncertainty Typing

#### Current State

The output has `missing_facts` and `missing_articles_needed` but does not type *why* the analysis is uncertain.

#### New Output Field

Add `uncertainty_sources` per issue:

```json
{
  "uncertainty_sources": [
    {
      "type": "FACTUAL_GAP",
      "detail": "Unknown whether administrator acted in bad faith",
      "impact": "Cannot determine if liability condition C2 is satisfied",
      "resolvable_by": "USER_INPUT"
    },
    {
      "type": "LIBRARY_GAP",
      "detail": "Art. 169 Legea 85/2014 not in provided articles",
      "impact": "Cannot assess primary liability provision",
      "resolvable_by": "ARTICLE_IMPORT"
    },
    {
      "type": "LEGAL_AMBIGUITY",
      "detail": "Interaction between art.117 and art.169 regarding temporal scope is doctrinally debated",
      "impact": "Two legitimate interpretations exist",
      "resolvable_by": "LEGAL_INTERPRETATION"
    }
  ]
}
```

**Type definitions:**
- **FACTUAL_GAP**: A fact needed for subsumption was not stated. Resolvable by asking the user.
- **LIBRARY_GAP**: A norm needed for the analysis is not in the provided articles. Resolvable by importing the article.
- **LEGAL_AMBIGUITY**: The law itself is ambiguous or doctrinally contested. Not resolvable by more data.

#### New Prompt Instructions

> **UNCERTAINTY CLASSIFICATION (REQUIRED when certainty_level is not CERTAIN):**
>
> Classify each source of uncertainty:
> - FACTUAL_GAP: You need a fact the user did not provide. Never guess — list it.
> - LIBRARY_GAP: You need a legal provision not in the provided articles. This is a system limitation, not legal uncertainty.
> - LEGAL_AMBIGUITY: The law is genuinely ambiguous or contested. This exists even with complete facts and complete library.
>
> CRITICAL: Do NOT conflate these. "I don't have Art. X" is a LIBRARY_GAP, not legal uncertainty. "Art. X could be interpreted two ways" is LEGAL_AMBIGUITY. "I don't know if the company had >50 employees" is a FACTUAL_GAP.

---

## Section 3: Step 6.9 Enhanced Conditional Retrieval + Post-6.9 Gate

### 3A: Enhanced Conditional Retrieval

#### Current State

`_fetch_missing_articles` parses article references from `missing_articles_needed` and fetches them from DB by exact match. Limited to references the model can name precisely.

#### Change

When `governing_norm_status` is MISSING, attempt two retrieval strategies:

1. **Exact reference fetch** (existing): If `missing_norm_ref` is populated, fetch directly from DB.
2. **Semantic search fallback** (new): If exact fetch fails or reference is imprecise, use `expected_norm_description` to run a targeted semantic search against the law's articles via existing ChromaDB infrastructure. Top 3-5 results, filtered to the relevant law's version.

```python
def _fetch_governing_norm(issue: dict, state: dict, db: Session) -> list[dict]:
    """Attempt to fetch missing governing norm for an issue."""
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
        law_key = _extract_law_key(ref or "")
        fetched = _semantic_search_for_norm(description, law_key, state, db)
        if fetched:
            return fetched

    return []
```

`_semantic_search_for_norm` is a thin wrapper around existing `query_articles` (ChromaDB), filtered to the relevant law version, returning top 3-5 results.

### 3B: Post-6.9 Governing Norm Gate

#### Gate Logic

After conditional retrieval completes and Step 6.8 re-runs, check whether the PRIMARY issue's governing norm is still missing.

**Behavior — two tiers:**

- **Law not in library at all**: Hard pause — offer import (same pattern as Step 2.5). The user can import the law and the pipeline resumes.
- **Law in library but article not surfaced**: Soft warning — set `state["governing_norm_incomplete"] = True`, add flag, continue to Step 7. The answer will prominently disclose incompleteness.

```python
def _post_6_9_governing_norm_gate(state: dict) -> dict | None:
    rl_rap = state.get("rl_rap_output", {})
    issues = rl_rap.get("issues", [])
    primary_issue_id = state.get("primary_target", {}).get("issue_id") \
        or _find_primary_issue_id(state)

    for issue in issues:
        if issue.get("issue_id") != primary_issue_id:
            continue
        gns = issue.get("governing_norm_status", {})
        if gns.get("status") == "MISSING":
            law_key = _extract_law_key(gns.get("missing_norm_ref", ""))
            law_in_library = law_key in state.get("selected_versions", {})

            if not law_in_library:
                # Hard pause — offer import
                return hard_pause_event(issue, gns)
            else:
                # Soft warning — continue with disclosure
                state["flags"].append(
                    f"GOVERNING_NORM_MISSING: {gns.get('expected_norm_description')}"
                )
                state["governing_norm_incomplete"] = True
                return None
    return None
```

**Integration point:** Runs in `_run_steps_4_through_7` after the existing Step 6.9 conditional retrieval block, before Step 7 begins.

---

## Section 4: Step 7 — Answer Generation Improvements

### 4A: Issue-Priority-Driven Answer Structure

> **ISSUE PRIORITY IN ANSWER STRUCTURE:**
>
> When the input includes a `primary_target` and issues have priority rankings:
> 1. Address the PRIMARY issue first, as the main body of the response
> 2. SECONDARY issues follow, clearly marked as related but distinct
> 3. SUPPORTING context comes last or is woven in
>
> Do NOT bury the PRIMARY issue after a longer discussion of a SECONDARY issue.
>
> Structure test: if the user reads only the first third of the answer, they should find the direct response to their primary question.
>
> When the PRIMARY issue has `governing_norm_status: MISSING`, lead with that disclosure.

### 4B: Three-Way Uncertainty Communication

> **UNCERTAINTY COMMUNICATION:**
>
> **FACTUAL_GAP** — present as a question to the user:
> "Raspunsul depinde de [missing fact]. Daca [scenario A], atunci... Daca [scenario B], atunci..."
> Do NOT present this as legal uncertainty.
>
> **LIBRARY_GAP** — present as a system limitation:
> "Articolul [X] din [Law] nu este disponibil in Biblioteca Juridica. Fara acest text, [what cannot be confirmed]."
> Do NOT present this as if the law itself is uncertain.
>
> **LEGAL_AMBIGUITY** — present as genuine legal debate:
> "Aceasta chestiune este discutabila din punct de vedere doctrinar..."
>
> CRITICAL: Never blend these.

### 4C: Tone Calibration

> **TONE CALIBRATION:**
>
> Match assertiveness to certainty level:
> - **CERTAIN**: "Administratorul raspunde conform Art. X."
> - **PROBABLE**: "Administratorul raspunde, in principiu, conform Art. X, cu conditia ca..."
> - **CONDITIONAL**: "Daca [unknown condition], administratorul ar putea raspunde... In lipsa acestei informatii, nu se poate concluziona definitiv."
> - **UNCERTAIN**: "Pe baza articolelor disponibile, nu se poate stabili cu certitudine..."
>
> Risk labels must align:
> - CERTAIN + consequence = **Risc: MAJOR/MEDIU/MINOR**
> - CONDITIONAL + consequence = "**Risc potential: MAJOR** — conditionat de [unknown]"
> - UNCERTAIN = "**Risc nedeterminat** — analiza incompleta"
>
> NEVER combine UNCERTAIN certainty with MAJOR risk.

### 4D: Governing Norm Incomplete Flag

> **GOVERNING NORM INCOMPLETE:**
>
> If `GOVERNING_NORM_MISSING` or `governing_norm_incomplete` is flagged:
> - Prominent notice before the main analysis
> - State what norm is missing and what is affected
> - Confidence LOW for the affected issue
> - Do NOT produce risk levels beyond "Risc nedeterminat"

---

## Section 5: Confidence Derivation

### Updated Rules

| Priority | Rule | Result |
|----------|------|--------|
| 1 | No articles | LOW |
| 2 | Majority citations unverified | LOW |
| 3 | Any UNCERTAIN issue | LOW |
| **3.5** | **Governing norm missing for primary issue** | **LOW** |
| 4 | Any CONDITIONAL issue | cap MEDIUM |
| **4.5** | **LIBRARY_GAP on primary issue** | **cap MEDIUM** |
| **4.6** | **Majority conditions UNKNOWN** | **cap MEDIUM** |
| 5 | Primary not from DB | cap MEDIUM |
| 6 | Missing primary laws | cap MEDIUM |
| 7 | Stale versions | cap MEDIUM |

### New Parameters

```python
def _derive_final_confidence(
    claude_confidence: str,
    rl_rap_issues: list[dict],
    has_articles: bool,
    primary_from_db: bool,
    missing_primary: bool,
    has_stale_versions: bool,
    citation_validation: dict,
    governing_norm_incomplete: bool,       # NEW
    uncertainty_sources: list[dict],        # NEW
) -> tuple[str, str]:
```

New params default to `False` and `[]` for backward compatibility.

### Source of New Inputs

- `governing_norm_incomplete`: from `state.get("governing_norm_incomplete", False)` — set by post-6.9 gate
- `uncertainty_sources`: aggregated from all RL-RAP issues' `uncertainty_sources` arrays

---

## Section 6: Cross-Cutting Concerns

### 6A: State Propagation Step 1 → Step 6.8

`_build_step6_8_context` includes `primary_target` and per-issue priorities in the user message.

### 6B: State Propagation Step 6.8 → Step 7

`_build_step7_context` includes `primary_target` and `governing_norm_incomplete`. New RL-RAP fields flow through automatically as part of the JSON.

### 6C: Fast Path (SIMPLE) — No Changes

SIMPLE questions skip Step 6.8. New fields don't exist for SIMPLE questions. Existing fallback handling covers this.

### 6D: Backward Compatibility

`_parse_step6_8_output` provides safe defaults for missing new fields:
- `governing_norm_status` defaults to `{"status": "PRESENT"}`
- Missing `condition_table` falls back to existing `decomposed_conditions`
- Missing `uncertainty_sources` defaults to `[]`

### 6E: Explicit Out of Scope

- Steps 4-6 retrieval (BM25, semantic search, graph expansion, reranking)
- Steps 2.5 / 6.5 existing relevance gates
- Mode-specific templates (memo, comparison, compliance, checklist)
- Step 1b date extraction
- Steps 2/2a law mapping and currency check
- Step 3 version selection

---

## Summary of All Changes

| Component | File | Change |
|-----------|------|--------|
| Step 1 prompt | `LA-S1-issue-classifier.txt` | Add `primary_target`, per-issue `priority`, prioritization instructions |
| Step 6.8 prompt | `LA-S6.8-legal-reasoning.txt` | Add `governing_norm_status`, `condition_table` + `subsumption_summary`, `uncertainty_sources`, enforcement instructions |
| Step 6.8 context builder | `pipeline_service.py` `_build_step6_8_context` | Pass primary_target and issue priorities |
| Step 6.8 output parser | `pipeline_service.py` `_parse_step6_8_output` | Backward-compatible defaults for new fields |
| Conditional retrieval | `pipeline_service.py` new `_fetch_governing_norm` | Semantic search fallback for governing norm |
| Post-6.9 gate | `pipeline_service.py` new `_post_6_9_governing_norm_gate` | Soft warning or hard pause depending on law availability |
| Step 7 context builder | `pipeline_service.py` `_build_step7_context` | Pass primary_target and governing_norm_incomplete |
| Step 7 prompt | `LA-S7-answer-template.txt` | Issue-priority answer structure, three-way uncertainty, tone calibration, governing norm incomplete handling |
| Confidence derivation | `pipeline_service.py` `_derive_final_confidence` | Three new rules + two new parameters |
