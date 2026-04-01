
# Pipeline Optimization Design Spec

**Date:** 2026-03-30
**Scope:** Reduce pipeline redundancy, consolidate prompts, centralize confidence logic
**Approach:** Incremental refactoring, ordered by risk (lowest first)

---

## 1. Dead Code Removal

### 1.1 Delete LA-CONF prompt
- `LA-CONF-confidence.txt` is registered in `PROMPT_MANIFEST` (prompt_service.py:67-70) and seeded by `seed_defaults()` but **never called** in `pipeline_service.py`.
- Confidence is computed entirely in code via `_derive_confidence()` and ad-hoc adjustments.
- **Action:** Delete prompt file, remove from `PROMPT_MANIFEST`.

### 1.2 Delete LA-S3 prompt
- `LA-S3` (law identifier) exists as a prompt but is **never called** in the pipeline. Step 1 (LA-S1) handles law identification directly.
- **Action:** Delete prompt file, remove from `PROMPT_MANIFEST` if present.

**Risk:** Zero. No behavioral change.

---

## 2. Merge Step 5 + Step 5.5 into Unified Graph Expansion

### Current state
Two nearly identical functions in `pipeline_service.py`:
- `_step5_expand()` (L1825-1879): calls `expand_articles()`, builds article dict, appends to `retrieved_articles_raw`
- `_step5_5_exception_retrieval()` (L1887-1942): calls `expand_with_exceptions()`, builds identical article dict, appends to `retrieved_articles_raw`

Both share the same 11-field article construction logic with amendment notes, same deduplication pattern, same logging structure.

### Design
Replace both with `_step5_graph_expansion(state, db)`:

```python
def _step5_graph_expansion(state, db):
    t0 = time.time()

    # Phase 1: neighbors + cross-references
    raw_ids = [a["article_id"] for a in state.get("retrieved_articles_raw", [])]
    neighbor_ids, neighbor_details = expand_articles(db, raw_ids, ...)
    added_neighbors = _append_new_articles(state, db, neighbor_ids, source="expansion")

    # Phase 2: exception/exclusion articles
    exception_ids, exception_details = expand_with_exceptions(db, state["retrieved_articles_raw"])
    added_exceptions = _append_new_articles(state, db, exception_ids, source="exception")

    # Single log entry with combined details
    log_step(db, state["run_id"], "graph_expansion", 5, "done", duration,
        output_data={
            "neighbors_added": neighbor_details.get("neighbors_added", 0),
            "crossrefs_added": neighbor_details.get("crossrefs_added", 0),
            "exceptions_added": added_exceptions,
            "forward_matches": exception_details.get("forward_count", 0),
            "reverse_matches": exception_details.get("reverse_count", 0),
        })
```

Shared article-building logic (lines 1843-1864 / 1904-1925) extracted into:
```python
def _append_new_articles(state, db, new_ids, source) -> int:
    """Fetch articles by ID, build enriched dicts, append to state. Returns count added."""
```

### Pipeline orchestrator changes
- Remove separate `step 55` event yield.
- Emit single `step 5` event named `"graph_expansion"` with combined stats.

### Frontend
- `StepIndicator` shows one step instead of two. Check for hardcoded step name `"exception_retrieval"` in frontend and update to `"graph_expansion"`.

### Service layer unchanged
- `article_expander.py` functions (`expand_articles`, `expand_with_exceptions`) remain separate. Only pipeline orchestration is merged.

### Tests
- Step 5/5.5 have no existing tests. Add tests for merged function: neighbors added, exceptions added, deduplication across phases, empty input.

**Risk:** Low. The `article_expander.py` logic is untouched.

---

## 3. Replace Step 4.5 with Simple Cap

### Current state
`_step4_5_pre_expansion_filter()` (L1768-1809) uses BM25 median per tier + semantic distance < 0.7 to filter articles before expansion. Step 6 then reranks everything with a cross-encoder anyway. Step 4.5 exists only to prevent Step 5 from expanding too many articles.

### Design
Replace the entire step with a sort-and-cap at the start of `_step5_graph_expansion`:

```python
MAX_EXPANSION_INPUT = 30

def _cap_for_expansion(state):
    articles = state["retrieved_articles_raw"]
    if len(articles) <= MAX_EXPANSION_INPUT:
        return state
    articles.sort(key=lambda a: a.get("distance", 1.0))
    state["retrieved_articles_raw"] = articles[:MAX_EXPANSION_INPUT]
    return state
```

### Why 30
Full path retrieves 30 (primary) + 15 (secondary) = 45 max. Capping at 30 keeps the best articles. Fast path retrieves 15+5=20, so the cap never triggers there.

### Pipeline orchestrator
- Remove `step 45` event yield. The cap is an inline operation inside `_step5_graph_expansion`, not a separate logged step.

### Tests
- Delete `test_step4_5_filter.py` (4 existing tests for the old heuristic).
- Add simpler tests: articles under cap pass through unchanged, articles over cap are trimmed to top N by score.

**Risk:** Low. The cross-encoder in Step 6 is the real quality gate.

---

## 4. Centralize Confidence Logic

### Current state — 5 scattered locations

| Location | Lines | Logic |
|---|---|---|
| `_derive_confidence()` | 318-327 | Maps RL-RAP certainty → HIGH/MEDIUM/LOW |
| `_cap_confidence()` | 330-339 | Caps Step 7 confidence to not exceed Step 6.8's |
| `_step6_8_legal_reasoning()` | 363,383,387 | Sets `state["derived_confidence"]` |
| `_step7_answer_generation()` | 2254-2283 | 5 ad-hoc adjustments |
| `_step7_5_citation_validation()` | 2447 | Downgrades to LOW if majority citations unverified |

### Design
Single function called after Step 7.5, before final response assembly:

```python
def _derive_final_confidence(
    claude_confidence: str,        # What Claude said in Step 7
    rl_rap_issues: list[dict],     # Per-issue certainty from Step 6.8
    has_articles: bool,            # Were any articles retrieved?
    primary_source: str,           # Are primary laws from DB?
    missing_primary: bool,         # Any primary laws missing?
    has_stale_versions: bool,      # Any versions flagged stale?
    citation_validation: dict,     # Step 7.5 results
) -> tuple[str, str]:             # (confidence, reason)
```

### Rules in priority order (highest override wins)
1. No articles -> LOW ("No relevant articles found")
2. Majority citations unverified -> LOW ("Most citations could not be verified")
3. Any RL-RAP issue UNCERTAIN -> LOW ("Legal analysis has uncertain conditions")
4. Any RL-RAP issue CONDITIONAL -> MEDIUM at most
5. Primary laws from non-DB source -> MEDIUM at most
6. Missing primary laws -> MEDIUM at most ("Primary law not in library")
7. Stale versions -> MEDIUM at most ("Law version may be outdated")
8. Otherwise -> use Claude's assessment

### Deletions
- Delete `_derive_confidence()` and `_cap_confidence()` — logic absorbed.
- Remove ad-hoc confidence adjustments from `_step7_answer_generation()` (L2254-2283).
- Remove confidence downgrade from `_step7_5_citation_validation()` (L2447) — move to `_derive_final_confidence`.

### Step 6.8
Still sets `state["derived_confidence"]` for logging, but it's no longer used to cap. `_derive_final_confidence` reads raw RL-RAP issues directly.

### Tests
Expand existing tests in `test_step6_8_reasoning.py` (which already test `_derive_confidence`) to cover the full consolidated function. Test each priority rule independently.

**Risk:** Medium. Confidence is user-facing. Must verify all priority rules produce same outputs as current scattered logic for known inputs.

---

## 5. Consolidate LA-S7 Prompts into Template

### Current state — 6 files with ~80% shared boilerplate
- `LA-S7-answer-qa.txt` (159 lines)
- `LA-S7-simple.txt` (28 lines)
- `LA-S7-M2-answer-memo.txt` (95 lines)
- `LA-S7-M3-answer-comparison.txt` (95 lines)
- `LA-S7-M4-answer-compliance.txt` (97 lines)
- `LA-S7-M5-answer-checklist.txt` (102 lines)

All repeat: JSON response structure, citation rules, markdown formatting, stale version handling, domain relevance checks, no-articles guard.

### Design

**One template file:** `LA-S7-answer-template.txt` with `{MODE_SECTION}` placeholder.

**Template structure:**
```
[shared preamble — role, civil law jurisdiction, context description]
[shared RL-RAP integration instructions]
[shared temporal reasoning instructions]
[shared UNKNOWN handling with worked examples]

{MODE_SECTION}

[shared JSON response format]
[shared critical rules — citations, domain relevance, stale versions, no-articles guard]
[shared article priority rules]
```

**6 mode definition files** (lean, mode-specific only):
- `LA-S7-mode-simple.txt` (~10 lines) — 1-3 paragraphs, direct answer
- `LA-S7-mode-qa.txt` (~30 lines) — SHORT + FULL STRUCTURED FORMAT
- `LA-S7-mode-memo.txt` (~25 lines) — memo structure, formal tone
- `LA-S7-mode-comparison.txt` (~25 lines) — comparison table layout
- `LA-S7-mode-compliance.txt` (~25 lines) — compliance checklist format
- `LA-S7-mode-checklist.txt` (~25 lines) — actionable checklist format

### Prompt assembly in code
Modify `_step7_answer_generation()`:
1. Load template: `load_prompt("LA-S7-template")`
2. Load mode: `load_prompt(f"LA-S7-mode-{output_mode}")`
3. Replace `{MODE_SECTION}` with mode content

### PROMPT_MANIFEST
Remove 6 old entries, add 1 template + 6 mode entries. Seeding logic unchanged.

### UNKNOWN handling examples (added to template shared section)
```
HANDLING UNKNOWN CONDITIONS (from Legal Analysis):
When the Legal Analysis marks a condition as UNKNOWN, present it as a question:

Example — UNKNOWN condition: "whether the company has >50 employees"
Write: "Raspunsul depinde de numarul de angajati ai societatii:
  - Daca societatea are peste 50 de angajati, se aplica Art. 135 [DB], care prevede...
  - Daca societatea are sub 50 de angajati, se aplica regimul general din Art. 12 [DB]..."

Example — UNKNOWN condition: "date of contract signing"
Write: "Data semnarii contractului determina versiunea legii aplicabile:
  - Pentru contracte semnate inainte de 01.01.2025, se aplica...
  - Pentru contracte semnate dupa 01.01.2025, se aplica..."

NEVER guess or assume the answer to an UNKNOWN condition. Always present both branches.
```

### Frontend impact
None. Response format unchanged.

### Migration
Old prompt files deleted after new ones are verified. Prompt version history preserved in DB.

**Risk:** Medium. Must verify all 6 modes produce equivalent outputs. The shared rules are currently copy-pasted, so they should already be identical — but verify.

---

## 6. Sharpen LA-S1 Complexity Criteria

### Current state (LA-S1 lines 71-74)
Sparse guidance: one line per level with examples but no scoring mechanism. At ~50% simple queries, misclassification is costly.

### Design — add decision rubric
Add to LA-S1 prompt:

```
COMPLEXITY DECISION RUBRIC — count the signals:
  Signal A: Multiple distinct legal issues (not sub-points of one issue)
  Signal B: Multiple parties with different legal positions
  Signal C: Temporal dimension (past events, future deadlines, version changes)
  Signal D: Potential conflicts between laws or articles
  Signal E: Scenario with stated/assumed facts requiring condition analysis

  0 signals -> SIMPLE
  1-2 signals -> STANDARD
  3+ signals -> COMPLEX

  Override: If the question is literally "what is X" or "what does Art. Y say" -> always SIMPLE
```

### Tests
Add test cases to `test_pipeline_routing.py` for borderline complexity classification.

**Risk:** Medium. Changes routing behavior. Must verify with real query samples that the rubric produces sensible classifications.

---

## Implementation Order

| Step | Change | Risk | Dependencies |
|---|---|---|---|
| 1 | Delete LA-CONF, LA-S3 prompts | Zero | None |
| 2 | Merge Step 5 + 5.5 into graph expansion | Low | None |
| 3 | Replace Step 4.5 with simple cap | Low | Step 2 (cap lives inside graph expansion) |
| 4 | Centralize confidence logic | Medium | None |
| 5 | Consolidate LA-S7 into template + modes | Medium | None |
| 6 | Sharpen LA-S1 complexity + UNKNOWN handling | Medium | Step 5 (UNKNOWN examples go in template) |

Steps 4 and 5 are independent and can be developed in parallel.

---

## Files Modified

### Backend
- `backend/app/services/pipeline_service.py` — steps 2, 3, 4 (major)
- `backend/app/services/prompt_service.py` — steps 1, 5 (PROMPT_MANIFEST)
- `backend/prompts/LA-CONF-confidence.txt` — deleted (step 1). Note: do NOT delete `LA-CONFLICT-conflict-resolver.txt` which is a separate, active prompt.
- `backend/prompts/LA-S3-law-identifier.txt` — deleted (step 1)
- `backend/prompts/LA-S7-*.txt` — 6 files deleted, replaced with template + 6 modes (step 5)
- `backend/prompts/LA-S1-issue-classifier.txt` — rubric added (step 6)

### Frontend
- Step indicator: update any hardcoded references to `"exception_retrieval"` or step number `55`

### Tests
- `backend/tests/test_step4_5_filter.py` — deleted, replaced with cap tests (step 3)
- `backend/tests/test_step6_8_reasoning.py` — expanded for confidence (step 4)
- New: `backend/tests/test_step5_graph_expansion.py` (step 2)
- New: `backend/tests/test_confidence.py` (step 4)
- `backend/tests/test_pipeline_routing.py` — add complexity rubric tests (step 6)
