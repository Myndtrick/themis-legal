# Legal Reasoning Layer — Design Spec

**Date:** 2026-03-26
**Status:** Approved
**Scope:** Add structured legal reasoning (RL-RAP) to the Legal Assistant pipeline, with fast path for simple queries and cost optimizations.

---

## Problem

The Legal Assistant pipeline is currently a well-engineered RAG system: it retrieves relevant law articles and asks Claude to generate an answer in a single Step 7 call. All legal reasoning — subsumption, exception handling, conflict resolution, temporal verification — happens implicitly inside that one call, with no structured methodology.

This means:
- Claude must simultaneously reason about the law AND write the answer
- There is no auditable reasoning trace between "here are articles" and "here is the conclusion"
- The system cannot distinguish between "I analyzed this carefully" and "I pattern-matched what legal analysis looks like"
- Simple statutory lookups pay the same cost as complex multi-issue scenarios

## Goals

1. Separate legal reasoning from answer generation — reasoning becomes a dedicated pipeline step
2. Encode Romanian civil law methodology (RL-RAP) into the reasoning step so it performs norm decomposition, subsumption, exception checking, and temporal verification
3. Produce structured, machine-consumable analysis that Step 7 consumes for communication
4. Add a fast path for simple statutory queries that skips the reasoning step
5. Reduce token waste through smarter article filtering and dynamic context sizing

## Non-Goals

- EU law retrieval or EU priority resolution (no EU law data available yet)
- Replacing the cross-encoder reranker with a legal-domain model (separate research task)
- Reducing output modes from 5 to 2 (separate product decision)
- Changing the import pipeline architecture

## Constraints

- Maximum 3 Claude calls for standard queries, 4 for complex queries with retrieval retry
- Target cost: ~$0.03–0.04 for simple, ~$0.08–0.09 for standard, ~$0.11–0.12 for complex
- No new external API dependencies (all new steps are local or use existing Claude/DB)
- Must be backward-compatible: if Step 6.8 fails, pipeline falls back to current behavior (raw articles to Step 7)

---

## Design

### Section 1: Extended Step 1 — Fact Extraction and Complexity Classification

Extend the existing Step 1 (issue classification) prompt to output two new fields.

**`complexity` field:**

```json
{
  "complexity": "SIMPLE" | "STANDARD" | "COMPLEX"
}
```

Classification criteria (added to LA-S1-issue-classifier.txt):
- **SIMPLE:** Single factual question about a current rule, definition, threshold, or procedure. No scenario, no multiple parties, no temporal dimension. A lawyer would answer from memory or a single article lookup.
- **STANDARD:** Question involving a specific situation with 1–2 issues, potentially requiring temporal or exception analysis.
- **COMPLEX:** Multi-issue scenario with multiple parties, dates, conflicting laws, or requiring comprehensive analysis.

**`facts` field (STANDARD/COMPLEX only, omitted for SIMPLE):**

```json
{
  "facts": {
    "stated": [
      {
        "fact_id": "F1",
        "description": "Administrator took personal loan of 50,000 EUR from company",
        "date": "2025-01-01",
        "legal_category": "related_party_transaction"
      }
    ],
    "assumed": [
      {
        "fact_id": "F3",
        "description": "Company is an SRL registered in Romania",
        "basis": "implied by context - user mentions 'asociat' and 'administrator'"
      }
    ],
    "missing": [
      {
        "fact_id": "F5",
        "description": "Whether shareholder approval was obtained for the loan",
        "relevance": "Determines applicability of Art. 1444 Cod Civil"
      }
    ]
  }
}
```

Each stated fact gets a `fact_id` for reference in the reasoning step. Assumed facts must state the basis for the assumption. Missing facts must state why they are legally relevant.

**Token impact:** Step 1 output grows by ~200–400 tokens for STANDARD/COMPLEX. No change for SIMPLE.

**Files:** `LA-S1-issue-classifier.txt` (add complexity and facts fields to prompt and output schema), `pipeline_service.py` (parse new fields).

---

### Section 2: Pipeline Routing by Complexity

After Step 1, the pipeline routes based on the `complexity` field.

```
Step 1 output: complexity = ?
  |
  +-- SIMPLE --> Fast Path (Section 3)
  |
  +-- STANDARD / COMPLEX --> Full Path (Sections 4-8)
```

**Routing logic in `pipeline_service.py`:** A single conditional after Step 1 parsing. If `complexity == "SIMPLE"`, call `_run_fast_path(state, db)`. Otherwise, continue the existing pipeline with new steps inserted.

**Resume pipeline path:** The `resume_pipeline` function (which re-enters the pipeline after an import pause at Step 2.5) must also respect the complexity routing. The `complexity` field must be persisted in `PipelineRun.paused_state` alongside the rest of the state dict. On resume, if `complexity == "SIMPLE"`, resume into the fast path; otherwise resume into the full path with all new steps (4.5, 6.7, 6.8, conditional retrieval). In practice, SIMPLE queries are unlikely to pause (they typically reference one well-known law), but the resume path must handle it correctly regardless.

---

### Section 3: Fast Path for Simple Statutory Queries

For SIMPLE queries, the pipeline skips fact extraction, expansion, exception retrieval, partitioning, and the reasoning step.

**Steps that run:**

| Step | Behavior |
|---|---|
| Steps 1.5–2.5 | Unchanged (law mapping, version selection, import gate) |
| Step 3 | Unchanged (version selection) |
| Step 4 | **Reduced retrieval:** BM25 retrieves 5 (not 30) per tier, semantic retrieves 5 (not 30). Entity-targeted retrieval skipped. Total raw: ~8–10 articles. |
| Step 4.5 | Skipped |
| Step 5 | Skipped |
| Step 5.5 | Skipped |
| Step 6 | Rerank ~8–10 articles, select **top 3** |
| Step 6.5 | Late relevance gate still runs |
| Step 6.7 | Skipped |
| Step 6.8 | Skipped |
| Conditional retrieval | Skipped |
| Step 7 | **Simplified prompt** — receives 3 articles + question directly. No RL-RAP analysis. |
| Step 7.5 | Unchanged |

**Simplified Step 7 prompt (`LA-S7-simple.txt`):**
- State the rule clearly
- Cite the specific article and version
- Mention key exceptions if they exist in the provided articles
- Note any relevant thresholds, deadlines, or conditions
- Keep the answer short (1–3 paragraphs)
- Same JSON output structure as normal Step 7

**Cost:** ~$0.03–0.04 per query (2 Claude calls).

**Safety:** If Step 1 misclassifies a complex question as SIMPLE, the answer will be less thorough but not incorrect — it will miss nuances. The late relevance gate (Step 6.5) still runs and can flag low-confidence results. Step 7 low-confidence answers include a note suggesting the user provide more context.

**Implementation approach:** The fast path reuses existing step functions (`_step4_hybrid_retrieval`, `_step6_select_articles`) with different parameters, NOT a duplicated code path. Specifically:
- `_step4_hybrid_retrieval` gains an optional `tier_limits_override` parameter to accept `{"tier1_primary": 5, "tier2_secondary": 5}`
- `_step6_select_articles` already accepts `top_k` — pass `top_k=3`
- `_run_fast_path` is a thin orchestrator that calls existing functions with fast-path parameters and skips Steps 4.5, 5, 5.5, 6.7, 6.8

**Files:** `pipeline_service.py` (add `_run_fast_path` function, add `tier_limits_override` parameter to Step 4), new prompt `LA-S7-simple.txt`.

---

### Section 4: Pre-Expansion Relevance Filter (Step 4.5)

**Type:** LOCAL STEP (no API cost)
**Position:** After hybrid retrieval (Step 4), before expansion (Step 5)
**Applies to:** STANDARD/COMPLEX path only

**What it does:** Drops bottom-tier articles before expansion to reduce noise amplification.

**Filter criteria — keep articles that match ANY of:**
- Has a BM25 score and ranks in top 50% of BM25 results for their tier
- Has a semantic distance score and distance < 0.7
- Source is `"entity_targeted"`

Note: articles from BM25-only have no semantic distance; articles from semantic-only have no BM25 rank. The OR logic ensures each article is evaluated by whichever score(s) it has. An article is only dropped if ALL its available scores fall below threshold.

**Typical result:** ~30–40 articles retained (from 60–90 raw).

**Why this is safe:** Articles with weak BM25 AND weak semantic scores are unlikely to become relevant after expansion. The filter uses a lenient threshold — it removes the bottom of both retrieval methods, not the middle.

**Impact:** Expansion (Step 5) generates ~30% fewer articles. Reranking (Step 6) scores 50–70 articles instead of 150–200.

**Files:** `pipeline_service.py` (add `_step4_5_pre_expansion_filter` function).

---

### Section 5: Dynamic Article Count in Reranking (Step 6)

**Current:** Step 6 always selects top-20 articles regardless of query complexity.

**New:** Scale top_k based on issue count:

```python
num_issues = len(state.get("legal_issues", []))
top_k = min(20, 5 + (num_issues * 5))
```

| Issues | top_k |
|---|---|
| 1 | 10 |
| 2 | 15 |
| 3+ | 20 |

This reduces articles flowing into Steps 6.7, 6.8, and 7 for simpler queries. Note: `num_issues` is derived from `state["legal_issues"]` which is populated by Step 1. For SIMPLE queries this code path is not reached (fast path skips to top-3 directly).

**Files:** `pipeline_service.py` (pass dynamic top_k to `rerank_articles`), `reranker_service.py` (already accepts `top_k` parameter — no change needed).

---

### Section 6: Article-to-Issue Partitioning (Step 6.7)

**Type:** LOCAL STEP (no API cost)
**Position:** After reranking (Step 6), before reasoning (Step 6.8)
**Applies to:** STANDARD/COMPLEX path only

**What it does:** Assigns each reranked article to the issue(s) it serves, using the `issue_versions` mapping from Step 3.

**Prerequisite — article enrichment with `law_version_id`:** Articles from BM25 and semantic search may not carry `law_version_id` consistently. Before partitioning, Step 6.7 must ensure each article has a `law_version_id` by looking it up from the `Article` table using the article's `article_id` if not already present. This is a single batch DB query (one query for all articles missing the field), not per-article.

**Matching logic:**

```python
for article in reranked_articles:
    for issue in state["legal_issues"]:
        law_key = f"{issue.get('law_number', '')}/{issue.get('law_year', '')}"
        issue_key = f"{issue['issue_id']}:{law_key}"
        if issue_key in state["issue_versions"]:
            expected_version_id = issue_versions[issue_key]["law_version_id"]
            if article["law_version_id"] == expected_version_id:
                assign article to this issue
```

An article can belong to multiple issues (same law, same version needed by two issues). Articles that match no issue (e.g., SECONDARY law articles not mapped to a specific issue) go into a `shared_context` bucket.

**Output:**

```json
{
  "issue_articles": {
    "ISSUE-1": [{"article_id": 123, "law_key": "85/2014", ...}],
    "ISSUE-2": [...]
  },
  "shared_context": [{"article_id": 456, "law_key": "287/2009", ...}]
}
```

**Edge cases:**
- Issue has zero assigned articles: flag in `state["flags"]`, include issue in reasoning step anyway (will be marked UNCERTAIN)
- All articles in `shared_context`: fall back to sending all articles unpartitioned. Reasoning step handles sorting.

**Files:** `pipeline_service.py` (add `_step6_7_partition_articles` function).

---

### Section 7: Legal Reasoning Step (Step 6.8 — RL-RAP)

**Type:** CLAUDE STEP (API cost)
**Position:** After partitioning (Step 6.7), before answer generation (Step 7)
**Applies to:** STANDARD/COMPLEX path only

#### 7A: Input Construction

Step 6.8 receives a structured prompt with four blocks:

**Block 1 — Structured Facts** (from Step 1)
```
STATED FACTS:
  F1: Administrator took personal loan of 50,000 EUR from company (2025-01-01)
  F2: No shareholder approval obtained
  F3: Company entered insolvency (2026-07-01)

ASSUMED FACTS:
  F4: Company is an SRL registered in Romania (basis: user mentions 'asociat')

MISSING FACTS:
  F5: Whether loan had board approval (relevant to Art. 1444 Cod Civil)
```

**Block 2 — Per-Issue Article Sets** (from Step 6.7)
```
ISSUE-1: Validity of related-party loan
  Relevant date: 2025-01-01
  Temporal rule: contract_formation
  Version used: Legea 31/1990, version 2024-11-15
  Articles:
    [Art. 197] Full text...
    [Art. 1444] Full text...

ISSUE-2: Administrator liability in insolvency
  Relevant date: 2026-07-01
  Temporal rule: insolvency_opening
  Version used: Legea 85/2014, version 2026-01-15
  Articles:
    [Art. 169] Full text...

SHARED CONTEXT (SECONDARY):
    [Art. 1357 Cod Civil] Full text...
```

**Block 3 — Reasoning Instructions** (system prompt, derived from RL-RAP)

The system prompt encodes the RL-RAP methodology as a unified instruction set:

1. For each issue, identify operative articles. Classify each as RULE / DEFINITION / PROCEDURAL_RULE / REFERENCE_RULE. Only RULE articles get full subsumption. REFERENCE_RULE articles trigger cross-reference requests. DEFINITION articles provide context only.
2. For each RULE article, decompose into hypothesis (conditions), disposition (modality + rule), sanction/effect (explicit or implicit). Extract hypothesis as atomic, fact-testable conditions. For lettered lists (lit. a-h), explicitly label as OR-list or AND-list.
3. For each condition, evaluate against stated facts: SATISFIED / NOT_SATISFIED / UNKNOWN. UNKNOWN must produce a specific missing_facts entry. Never speculate or fill gaps.
4. Check exceptions and derogations before concluding. Treat "prin derogare de la..." as a controlling derogation. Model each exception as a mini-norm with conditions and status. Check in order: inline exceptions, same-act derogations, cross-act special rules.
5. If multiple norms lead to incompatible outcomes, declare a conflict and resolve: lex superior, then lex specialis, then lex posterior. An older special law is NOT automatically overridden by a newer general law — mark UNCERTAIN if unclear.
6. Verify temporal applicability per issue: confirm the article version is in force at the relevant event date. Apply non-retroactivity (Constitution Art. 15(2)), civil transitional rules (Civil Code Art. 6), procedural rules (CPC Art. 24). If fallback to current version occurred, flag temporal risk and downgrade certainty.
7. Produce conclusion and certainty level per issue (CERTAIN / PROBABLE / CONDITIONAL / UNCERTAIN).
8. If a critical cross-reference is needed but not in the provided articles, add it to `missing_articles_needed`.

**Block 4 — Output Format Instruction**

Return JSON only, following the RL-RAP output schema.

#### 7B: Claude API Call Parameters

| Parameter | Value | Rationale |
|---|---|---|
| Model | Same model as configured for the pipeline (currently claude-sonnet-4-20250514) | Consistent with Steps 1 and 7; configured via `config.py`, not hardcoded in step |
| Max tokens | 4,096 | Enough for 3 issues with full decomposition |
| Temperature | 0.1 | Lower than other steps — reasoning should be deterministic |
| Streaming | No | Output consumed as complete JSON, not displayed |
| System prompt caching | Yes (ephemeral) | RL-RAP methodology prompt is same across all queries |

#### 7C: Output Schema

```json
{
  "issues": [
    {
      "issue_id": "ISSUE-1",
      "issue_label": "Validity of related-party loan",
      "operative_articles": [
        {
          "article_ref": "Legea 31/1990 art.197 alin.(3)",
          "law_version_id": "...",
          "norm_type": "RULE",
          "disposition": {
            "modality": "PROHIBITION",
            "text": "Administratorul nu poate incheia acte juridice cu societatea fara aprobarea AGA"
          },
          "sanction": {
            "explicit": true,
            "text": "Nulitatea actului"
          }
        }
      ],
      "decomposed_conditions": [
        {
          "condition_id": "C1",
          "norm_ref": "Legea 31/1990 art.197 alin.(3)",
          "condition_text": "Act juridic intre administrator si societate",
          "list_type": null,
          "condition_status": "SATISFIED",
          "supporting_fact_ids": ["F1"],
          "missing_facts": []
        },
        {
          "condition_id": "C2",
          "norm_ref": "Legea 31/1990 art.197 alin.(3)",
          "condition_text": "Aprobarea AGA nu a fost obtinuta",
          "list_type": null,
          "condition_status": "SATISFIED",
          "supporting_fact_ids": ["F2"],
          "missing_facts": []
        }
      ],
      "exceptions_checked": [
        {
          "exception_ref": "Legea 31/1990 art.197 alin.(4)",
          "type": "INLINE_EXCEPTION",
          "condition_status_summary": "NOT_SATISFIED",
          "impact": "Exception for ordinary course transactions - not applicable to loans",
          "missing_facts": []
        }
      ],
      "temporal_applicability": {
        "relevant_event_date": "2025-01-01",
        "version_matches": true,
        "temporal_risks": []
      },
      "conclusion": "Art. 197(3) applies: the loan is a legal act between administrator and company without AGA approval. The act is likely voidable (nulitate relativa). Both conditions are satisfied and no exception applies.",
      "certainty_level": "CERTAIN",
      "missing_facts": [],
      "missing_articles_needed": []
    }
  ]
}
```

**Conditional sections:**
- `conflicts` section: omitted entirely when no conflict detected
- `temporal_applicability`: one-line format when no risks (`version_matches: true`, empty risks)
- Full temporal block only when risks exist (fallback version, post-event amendment)

#### 7D: Failure Modes

| Failure | Handling |
|---|---|
| Claude returns malformed JSON | Fall back: pass reranked articles directly to Step 7 without reasoning layer. Log error. Pipeline operates as it does today. |
| Claude omits an issue | Pipeline checks: if any issue_id from Step 1 is missing in output, flag it and inform Step 7 |
| Output exceeds 4,096 tokens | Retry with max_tokens 6,144. Only expected with 4+ issues. |

**Files:** `pipeline_service.py` (add `_step6_8_legal_reasoning` function), new prompt `LA-S6.8-legal-reasoning.txt`.

---

### Section 8: Conditional Retrieval Pass

**Type:** DATABASE STEP (no API cost) + conditional CLAUDE STEP (only if triggered)
**Position:** After Step 6.8, before Step 7
**Applies to:** STANDARD/COMPLEX path only

#### Trigger Condition

If any issue in the Step 6.8 output has a non-empty `missing_articles_needed` array.

If no issues have missing articles: skip entirely, proceed to Step 7 (common case).

#### Phase 1: DB Lookup (local)

For each missing article reference:
1. Parse reference into law identifier + article number (reuse cross-reference parsing from `article_expander.py`)
2. Look up the law in `selected_versions` or `unique_versions` — use the version matching the requesting issue's relevant date
3. If law not in selected set: look up in `Law` table by number/year, find version for issue date
4. Fetch article text from `Article` table
5. If article doesn't exist in DB: record as unfetchable, continue

#### Phase 2: Augment and Re-run (conditional)

If new articles were fetched:
1. Add to relevant issue's article set, tagged `"source": "reasoning_request"`
2. Re-run Step 6.8 with augmented input
3. Proceed to Step 7 with new output

If no articles fetchable:
1. Skip re-run
2. Add flags: "Reasoning step identified missing provisions not available in library: [list]"
3. Proceed to Step 7 with original Step 6.8 output

#### Guard Rails

- **One pass only.** Re-run output may contain new `missing_articles_needed`. These are NOT fetched. They are passed to Step 7 as flags.
- **Cap: 5 articles.** If Step 6.8 requests more than 5, fetch first 5 (ordered by issue priority), flag rest as unfetched.
- **No imports.** Missing articles from laws not in DB are NOT imported. Import only triggers at Step 2.5 for PRIMARY laws.

#### Cost Impact

| Scenario | Extra Claude Calls | Extra Cost |
|---|---|---|
| No missing articles (common) | 0 | $0.00 |
| Missing articles found in DB | 1 (re-run 6.8) | ~$0.02-0.03 |
| Missing articles not in DB | 0 | $0.00 |

**Files:** `pipeline_service.py` (add `_conditional_retrieval_pass` function).

---

### Section 9: Revised Step 7 — Answer Generation from Structured Analysis

**Applies to STANDARD/COMPLEX path.** SIMPLE path uses existing Step 7 logic with simplified prompt (Section 3).

#### New Input Construction

Step 7 receives RL-RAP analysis instead of raw articles:

```
CLASSIFICATION:
  (question_type, legal_domain, output_mode, core_issue)

STRUCTURED FACTS:
  (stated, assumed, missing - from Step 1)

LEGAL ANALYSIS (from Step 6.8):
  ISSUE-1: [label]
    Certainty: [level]
    Operative article: [ref] - [MODALITY]
    Conditions:
      C1: [text] - SATISFIED (F1)
      C2: [text] - UNKNOWN
    Exceptions checked:
      [ref] - NOT APPLICABLE
    Temporal: [status]
    Conclusion: [text]

FLAGS AND WARNINGS:
  (version fallbacks, unfetchable articles, etc.)

SUPPORTING ARTICLE TEXTS:
  [Only operative articles cited in the analysis - typically 4-8]
  [Art. 197(3)] Full text...
  [Art. 169(1)] Full text...

USER QUESTION:
  (original text)
```

#### Key Changes from Current Step 7

**Article context reduced:** From all 20 reranked articles (~2,000-3,500 tokens) to only operative articles cited in RL-RAP analysis (~600-1,500 tokens). Step 7 still receives article text for accurate quoting.

**Prompt simplified:** No longer instructs on legal reasoning methodology. The Step 7 prompt (modified `LA-S7-answer-qa.txt` and variants) focuses on:
- How to structure the answer by issue
- How to explain conditions and their status in plain Romanian
- How to present UNKNOWN conditions as questions the user should answer
- How to present CONDITIONAL conclusions honestly
- How to cite articles with version dates
- How to format per output_mode

**Confidence derived from Step 6.8:**

| Issue certainties | Overall confidence |
|---|---|
| All CERTAIN | HIGH |
| Mix of CERTAIN and PROBABLE | HIGH |
| Any CONDITIONAL, no UNCERTAIN | MEDIUM |
| Any UNCERTAIN | LOW |
| Step 6.8 returned no issues (parse failure, partial output) | LOW |
| Step 6.8 was skipped (fallback mode) | Determined by Step 7 as today (no constraint) |

Step 7 can lower confidence below the derived value but cannot raise it above. If Step 6.8 omitted an issue (flagged by pipeline), that issue is treated as UNCERTAIN for confidence derivation purposes.

#### Token Budget (New vs Current)

| Component | Current Step 7 | New Step 7 |
|---|---|---|
| System prompt | ~800 | ~600 |
| Article text | ~2,000-3,500 | ~600-1,500 |
| Classification + facts | ~200 | ~400 |
| RL-RAP analysis | - | ~500-1,000 |
| Question + history | ~300 | ~300 |
| **Total input** | **~3,300-4,800** | **~2,400-3,800** |

Net input reduction: ~20-30%.

#### Step 7.5 Citation Validation (Modified)

Validates against operative articles from RL-RAP analysis only (not all reranked articles). If Step 7 cites an article that was in the top-20 but NOT identified as operative by Step 6.8, it is flagged as "Unverified."

**Data flow:** After Step 6.8, the pipeline populates `state["operative_articles"]` — a list of article references extracted from the RL-RAP output's `operative_articles` arrays across all issues. Step 7.5 validates against this set instead of `state["retrieved_articles"]`.

**Files:** `LA-S7-answer-qa.txt` and other S7 variants (simplify, add RL-RAP consumption instructions), `pipeline_service.py` (modify Step 7 context construction, populate `state["operative_articles"]`, modify Step 7.5 validation).

---

### Section 10: RL-RAP Document Cleanup

The existing `docs/deep-research-report.md` (RL-RAP) is cleaned up to serve as the canonical methodology reference:

- Remove `citeturn` citation artifacts throughout
- Remove YAML output schema alternative (JSON only)
- Remove markdown block output format (`[NORM_DECOMP]`, `[SUBSUMPTION]`, etc.) — JSON is canonical
- Remove `protocol_version` and `generated_at` metadata fields
- Add `list_type` field to condition schema for OR/AND labeling
- Add note that EU priority logic is acknowledged but deferred until EU law is retrievable
- Rename file to `docs/RL-RAP.md` for clarity

The RL-RAP document is the source of truth. The Step 6.8 prompt (`LA-S6.8-legal-reasoning.txt`) is derived from it as a unified instruction set, not a copy.

---

## Pipeline Summary

### STANDARD/COMPLEX Path (3-4 Claude calls)

```
STEP 1    Classification + Facts + Complexity    [CLAUDE]
STEP 1.5  Compute law_date_map                   [LOCAL]
STEP 2    Law Mapping                            [DATABASE]
STEP 2.5  Early Relevance Gate                   [LOCAL/IMPORT]
STEP 3    Per-Issue Version Selection            [DATABASE]
STEP 4    Hybrid Retrieval                       [DATABASE]
STEP 4.5  Pre-Expansion Relevance Filter         [LOCAL] *NEW*
STEP 5    Article Expansion                      [DATABASE]
STEP 5.5  Exception Retrieval                    [DATABASE]
STEP 6    Reranking (dynamic top_k)              [LOCAL]
STEP 6.5  Late Relevance Gate                    [LOCAL]
STEP 6.7  Article-to-Issue Partitioning          [LOCAL] *NEW*
STEP 6.8  Legal Reasoning (RL-RAP)               [CLAUDE] *NEW*
          Conditional Retrieval Pass             [DATABASE + optional CLAUDE]
STEP 7    Answer Generation                      [CLAUDE]
STEP 7.5  Citation Validation                    [LOCAL]
```

### SIMPLE Path (2 Claude calls)

```
STEP 1    Classification (complexity=SIMPLE)     [CLAUDE]
STEP 1.5  Compute law_date_map                   [LOCAL]
STEP 2    Law Mapping                            [DATABASE]
STEP 2.5  Early Relevance Gate                   [LOCAL/IMPORT]
STEP 3    Version Selection                      [DATABASE]
STEP 4    Reduced Retrieval (5+5)                [DATABASE]
STEP 6    Rerank -> top 3                        [LOCAL]
STEP 6.5  Late Relevance Gate                    [LOCAL]
STEP 7    Direct Answer (simplified prompt)      [CLAUDE]
STEP 7.5  Citation Validation                    [LOCAL]
```

### SSE Step Events for Frontend

New steps need assigned step numbers and display names for the frontend `StepIndicator`:

| Step | Number | SSE Name | Display Text |
|---|---|---|---|
| Step 4.5 | 45 | `pre_expansion_filter` | "Filtering retrieval results..." |
| Step 6.7 | 67 | `article_partitioning` | "Organizing articles by issue..." |
| Step 6.8 | 68 | `legal_reasoning` | "Analyzing legal provisions..." |
| Conditional retrieval | 69 | `conditional_retrieval` | "Fetching additional provisions..." |

These follow the existing numbering convention (e.g., Step 2.5 = 25, Step 5.5 = 55). The frontend `step-indicator.tsx` needs to be updated with the new step names and display text.

### Cost Summary

| Path | Claude Calls | Estimated Cost |
|---|---|---|
| SIMPLE | 2 | ~$0.03-0.04 |
| STANDARD (no retry) | 3 | ~$0.08-0.09 |
| COMPLEX (with retrieval retry) | 4 | ~$0.11-0.12 |

## Files Changed

| File | Changes |
|---|---|
| `backend/app/services/pipeline_service.py` | Add Steps 4.5, 6.7, 6.8, conditional retrieval pass. Add fast path routing. Modify Step 7 context construction. Dynamic top_k in Step 6. |
| `backend/prompts/LA-S1-issue-classifier.txt` | Add complexity and facts fields |
| `backend/prompts/LA-S7-answer-qa.txt` (and S7 variants) | Simplify: remove reasoning instructions, add RL-RAP consumption instructions |
| `backend/prompts/LA-S6.8-legal-reasoning.txt` | NEW: RL-RAP methodology prompt |
| `backend/prompts/LA-S7-simple.txt` | NEW: Simplified prompt for SIMPLE fast path |
| `backend/app/services/reranker_service.py` | Accept dynamic top_k (minor) |
| `backend/app/services/pipeline_logger.py` | Log Steps 4.5, 6.7, 6.8 |
| `docs/deep-research-report.md` | Clean up and move to `docs/RL-RAP.md` |

## Deferred

| Item | Reason |
|---|---|
| EU priority logic in Step 6.8 | No EU law data available yet |
| Legal-domain reranker model | Separate research task |
| Reducing output modes from 5 to 2 | Separate product decision |
| Conversation history optimization in Step 1 | Low waste relative to total |
| Protocol versioning / audit metadata in RL-RAP output | No audit requirements yet |
