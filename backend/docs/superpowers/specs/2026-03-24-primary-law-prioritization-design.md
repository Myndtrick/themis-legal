# Primary Law Prioritization in Retrieval Pipeline

## Problem

The pipeline correctly classifies laws as PRIMARY (directly applicable) and SECONDARY (applies subsidiarily) in Step 2 (Law Mapping). However, this role information is ignored during article ranking. The cross-encoder reranker in Step 6 scores all articles by pure text relevance, regardless of tier. Large, broad laws like the Codul Civil (SECONDARY) frequently outscore the specific applicable law (PRIMARY) because their language is more general and matches more queries.

**Result:** For a question about "capital social minim la infiintare SRL", the top 10 articles are all from Codul Civil (287/2009, SECONDARY) while Legea societatilor comerciale (31/1990, PRIMARY) is buried — even though 31/1990 is the directly applicable law.

## Solution: Tier-Aware Score Boost

Apply an additive boost to reranker scores based on law role, so PRIMARY articles rank higher unless they are significantly less relevant.

## Design

### 1. Propagate Role to Articles

**File:** `backend/app/services/pipeline_service.py` — `_step4_hybrid_retrieval()`

When articles are merged into `all_articles`, add a `role` field derived from the tier key:
- `tier1_primary` -> `role: "PRIMARY"`
- `tier2_secondary` -> `role: "SECONDARY"`

Additionally, map other internal tier values:
- `entity_targeted` -> `role: "PRIMARY"` (entity retrieval only searches primary law version IDs)

**File:** `backend/app/services/pipeline_service.py` — `_step5_expand()` and `_step5_5_exception_retrieval()`

Articles added by expansion and exception retrieval derive their role by looking up which law they belong to: check if the article's `law_number/law_year` appears in `state["law_mapping"]["tier1_primary"]` -> PRIMARY, else SECONDARY. This avoids needing parent-child lineage tracking in the expander internals.

### 2. Apply Tier Boost in Reranker

**File:** `backend/app/services/reranker_service.py` — `rerank_articles()`

After cross-encoder scoring, before sorting:

```python
TIER_BOOST = {
    "PRIMARY": 0.15,
    "SECONDARY": 0.0,
}

for art in articles:
    role = art.get("role", "SECONDARY")
    art["reranker_score"] += TIER_BOOST.get(role, 0.0)
```

**Why additive:** Cross-encoder scores can be negative or near zero. A multiplier would flip signs or have no effect. Additive is predictable.

**Why 0.15:** This is an initial value that should be calibrated against actual score distributions from pipeline logs. The cross-encoder model (`cross-encoder/ms-marco-MiniLM-L-6-v2`) outputs logit scores whose range varies by input. After deployment, check actual PRIMARY vs SECONDARY score distributions and adjust. The constant is defined at module level for easy tuning.

### 3. Pass Role Info to Claude in Answer Generation

**File:** `backend/app/services/pipeline_service.py` — `_step7_answer_generation()`

When formatting articles for the Claude prompt context, prepend a role tag:

```
[PRIMARY] Art. 11 — Legea 31/1990 — Legea societatilor comerciale
<article text>

[SECONDARY] Art. 769 — Legea 287/2009 — Codul Civil
<article text>
```

### 4. Update Answer Prompts

**Files:**
- `backend/prompts/LA-S7-answer-qa.txt`
- `backend/prompts/LA-S7-M2-answer-memo.txt`
- `backend/prompts/LA-S7-M3-answer-comparison.txt`
- `backend/prompts/LA-S7-M4-answer-compliance.txt`
- `backend/prompts/LA-S7-M5-answer-checklist.txt`

Add rule (complements existing lex specialis guidance):

```
- Articles marked [PRIMARY] are from the directly applicable law (lex specialis).
  Articles marked [SECONDARY] apply subsidiarily. This reinforces the lex specialis
  principle already in the rules above — use PRIMARY articles as the foundation of
  your answer, and SECONDARY only to fill gaps where the primary law is silent.
```

## Edge Cases

- **All laws are SECONDARY:** If the law mapper classifies everything as `tier2_secondary`, no article gets a boost and behavior is unchanged. This is expected — no bug.
- **No PRIMARY articles retrieved:** If BM25/semantic search returns nothing from the primary law (e.g., very niche topic), SECONDARY articles proceed without penalty. The boost only helps PRIMARY; it does not harm SECONDARY.
- **Expansion/exception articles:** Role is determined by law lookup against the mapping tiers, not by parent-child inheritance. An expanded article from a SECONDARY law stays SECONDARY even if its parent was found via a PRIMARY article's cross-reference.

## Files Changed

| File | Change |
|------|--------|
| `pipeline_service.py` — `_step4_hybrid_retrieval()` | Add `role` field to each article based on tier key |
| `pipeline_service.py` — `_step5_expand()`, `_step5_5_exception_retrieval()` | Assign `role` by law lookup against mapping tiers |
| `reranker_service.py` — `rerank_articles()` | Add `TIER_BOOST` constant, apply after scoring |
| `pipeline_service.py` — `_step7_answer_generation()` | Prepend `[PRIMARY]`/`[SECONDARY]` tag in context |
| `prompts/LA-S7-answer-qa.txt` | Add PRIMARY prioritization rule |
| `prompts/LA-S7-M2-answer-memo.txt` | Same rule |
| `prompts/LA-S7-M3-answer-comparison.txt` | Same rule |
| `prompts/LA-S7-M4-answer-compliance.txt` | Same rule |
| `prompts/LA-S7-M5-answer-checklist.txt` | Same rule |

## Not Changed

- BM25 service, ChromaDB service, law mapping, frontend
- No new Claude calls added
- No structural pipeline changes

## Verification

1. Ask "ce capital social minim trebuie la infiintare SRL" — top articles should now be from Legea 31/1990 (PRIMARY), not Codul Civil
2. Ask a question with multiple PRIMARY laws — both should rank above SECONDARY
3. Ask a question where SECONDARY law is genuinely more relevant — it should still be able to rank high if its reranker score exceeds the PRIMARY boost gap
4. Ask a general question (all SECONDARY) — behavior unchanged, no errors
5. Check pipeline debug logs for actual reranker score distributions to calibrate the 0.15 boost value
