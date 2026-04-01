# Pipeline V2: 5-Step Legal Assistant Redesign

## Problem Statement

The current 15-step pipeline costs $0.40/complex query, takes 255 seconds, and produces legally wrong answers due to a fundamental architectural mistake: global retrieval with downstream filtering. Articles are retrieved into a single pool, then filtered by a harmful reranker, expanded by graph traversal, partitioned back into issues, and often re-retrieved when Step 12 discovers missing governing norms — doubling the most expensive LLM call.

## Validated Design

Retrieval validation on 20 queries (4 real, 16 synthetic) across 6 legal domains achieved **94.1% governing norm recall** using per-issue concept-based retrieval with semantic + BM25 search. This exceeds the 85% threshold required to proceed.

## Architecture: 5 Steps

```
User Question
    |
Step 1: Classify + Temporal Anchor (LLM)
    |
Step 2: Resolve + Version + Gate (local)
    |
Step 3: Retrieve Per-Issue (local)
    |
Step 4: Legal Reasoning / RL-RAP (LLM, ONCE)
    |
Step 5: Answer + Validate (LLM + local)
```

**SIMPLE path:** Steps 1 -> 2 -> 3 -> 5 (skip Step 4, two LLM calls)
**STANDARD/COMPLEX path:** All 5 steps (three LLM calls, each running once)

---

## Step 1 — Classify + Temporal Anchor

**Type:** LLM call (Claude)
**Prompt:** Modified `LA-S1`
**What it produces:**

- Legal issues with priority (PRIMARY / SECONDARY / SUPPORTING)
- Applicable laws per issue with roles
- **Entity perspective per issue** — free-text identification of the legally relevant actor and their role (e.g., "administrator SRL", "creditor in insolventa", "inculpat"). Generic across all legal domains, not hardcoded.
- Per-fact temporal anchoring within each issue:
  - Reference date (TODAY / TODAY+N / explicit past date)
  - Temporal rule (current_law / act_date / insolvency_opening / etc.)
  - mitior_lex_relevant flag for criminal issues
- **Concept descriptions** per issue in precise Romanian legal terminology that incorporate the entity type. These drive retrieval in Step 3. No article number guessing.
- Complexity classification (SIMPLE / STANDARD / COMPLEX)
- Stated, assumed, and missing facts with fact IDs
- Primary target (actor + concern)

**Key changes from current LA-S1:**
- Entity perspective added per issue (new field)
- Concept descriptions made mandatory and entity-aware (existing field, improved instructions)
- Candidate articles field removed (concept descriptions replace it — Step 1 should describe what to find, not guess article numbers)
- Hypothetical scenario anchoring rules clarified (anchor first event to TODAY)

**Schema additions:**
```json
"legal_issues": [{
  "issue_id": "ISSUE-1",
  "entity_perspective": {
    "actor": "administratorul SRL",
    "role": "obligat/raspunzator",
    "counter_party": "asociatii"
  },
  "concept_descriptions": [{
    "law_key": "31/1990",
    "concept": "administratorii societatii cu raspundere limitata nu pot primi mandatul de administrator in alte societati concurente fara autorizarea adunarii asociatilor, sub sanctiunea revocarii si raspunderii pentru daune"
  }],
  "fact_dates": [{
    "fact_ref": "F1",
    "relevant_date": "2026-04-02",
    "temporal_rule": "act_date",
    "applicable_laws": ["31/1990"]
  }]
}]
```

---

## Step 2 — Resolve + Version + Gate

**Type:** Local processing, no LLM call
**Combines:** Current Steps 2a, 2b, 3, 4, 5, 6

**Sub-steps in order:**

### 2A: Version Selection Per Fact
For each (issue, fact, law) triple:
- Query DB for the correct LawVersion where `date_in_force <= fact_reference_date`, ordered DESC, take first
- Never select a version from after the fact reference date
- For `mitior_lex_relevant` issues: select standard version AND flag if newer version exists
- Build `fact_version_map`: `{issue_id:fact_ref:law_key -> law_version_id}`
- Build `unique_versions`: `{law_key -> set(version_ids)}` for retrieval

### 2B: Entity-Aware Concept Search Per Issue
For each issue, for each concept description:
- Run ChromaDB semantic search within the specific `law_version_id` selected in 2A
- The concept description from Step 1 already incorporates entity type
- `n_results=10` per concept
- Validate results against DB (check not abrogated)
- Store as `concept_candidates` per issue

### 2C: Law Availability Check
- Check all required laws exist in DB (reuse `check_laws_in_db`)
- Check all required versions exist (using `unique_versions` from 2A)

### 2D: Version Currency Check
- Only for laws where ANY issue uses `temporal_rule == "current_law"`
- Skip for laws where all issues use historical versions
- Check legislatie.just.ro for newer versions

### 2E: Availability Gate
- If a law is missing entirely: pause, offer import
- If a required version is missing: pause, tell user exactly which version is needed
- If a law is stale and needed as current: pause with warning
- If no laws identified: return clarification
- Otherwise: continue

**Output:** `fact_version_map`, `concept_candidates` per issue, `unique_versions`, gate status

---

## Step 3 — Retrieve Per-Issue

**Type:** Local processing, no LLM call
**Replaces:** Current Steps 7, 8, 9, 10, 11

**For each issue separately:**

1. Start with `concept_candidates` from Step 2B (already scoped to correct version and entity type)
2. Run BM25 search scoped to that issue's specific `law_version_ids`:
   - Query constructed from: issue description + entity-specific terms from concept description
   - Not the full user question (which contains terms from other issues)
   - `limit=10` per BM25 query
3. Run additional semantic search with the issue description as query, scoped to same version IDs, `n_results=10`
4. Deduplicate across all sources (concept + BM25 + semantic)
5. Filter out abrogated articles

**No reranker.** No graph expansion. No partitioning needed.

**Budget per issue:**
- PRIMARY issues: up to 12 articles
- SECONDARY issues: up to 8 articles
- SUPPORTING issues: up to 5 articles

**Lightweight relevance check:** After retrieval, check ChromaDB distances. If best semantic match for any PRIMARY issue has cosine distance > 0.7, set a low-confidence flag (but don't stop the pipeline).

**SIMPLE path optimization:** For SIMPLE queries (single issue, single law, current version), concept search may be skipped — just BM25 + semantic with the user's question directly.

**Output:** `issue_articles`: `{issue_id -> [article_dicts]}` — each issue has its own article set, correctly scoped.

---

## Step 4 — Legal Reasoning / RL-RAP

**Type:** LLM call (Claude), runs ONCE
**Prompt:** `LA-S6.8` (modified)
**Skipped for SIMPLE queries**

Receives per-issue article sets from Step 3. Each issue's articles are already correctly scoped to the right law version and entity type.

**Key changes from current Step 12:**
- Runs exactly once — no conditional retrieval loop
- If governing norm is MISSING, flags it as `governing_norm_status: MISSING` with `uncertainty_source: LIBRARY_GAP`. Does NOT trigger re-retrieval.
- Dynamic token budget: STANDARD (1-2 issues) = 8192, COMPLEX (3+ issues) = min(16384, 4096 + num_issues * 2048)
- Check `stop_reason` for truncation — if `max_tokens`, log specific warning
- Preserve raw response on parse failure for debugging
- Merge conflict resolution rules from LA-CONFLICT (EU law priority, express vs implicit repeal)

**Output:** `rl_rap_output` with per-issue condition tables, certainty levels, operative articles, governing norm status.

---

## Step 5 — Answer + Validate

**Type:** LLM call (streaming) + local validation
**Prompt:** `LA-S7-template` + mode-specific template

**Answer generation is PRESENTATION ONLY.** Prompt explicitly instructs:
> "Your role is PRESENTATION only. Present the conclusions from the LEGAL ANALYSIS section in natural Romanian. Do not re-derive conclusions from the articles. Do not contradict the certainty levels from the analysis. Do not use condition check marks or pipeline terminology."

**For SIMPLE queries (no RL-RAP):** Different prompt mode that allows direct reasoning from articles but does NOT use subsumption format.

**Citation validation** runs after answer generation (same as current Step 15):
- Check every source labeled "DB" against provided articles
- Downgrade phantom citations to "Unverified"
- If >50% phantom, cap confidence at LOW

**Output:** Streamed answer, structured answer JSON, confidence level, citations.

---

## What Is Eliminated

| Current Component | Why Eliminated |
|---|---|
| Reranker (Step 9, `reranker_service.py`) | Actively harmful — MS MARCO model eliminates correct Romanian legal articles. Per-issue retrieval makes filtering unnecessary. |
| Graph expansion (Step 8) | Compensating mechanism for imprecise retrieval. Per-issue concept search + BM25 is more targeted. |
| Article partitioning (Step 11) | Unnecessary when retrieval is per-issue from the start. |
| Conditional retrieval loop (Step 12 re-run) | Most expensive bug. Per-issue retrieval with entity-aware concepts achieves 94% governing norm recall without re-runs. |
| Late relevance gate (Step 10) | Used reranker score as proxy. Replaced by lightweight distance check in Step 3. |
| Date extraction by regex (Step 2a) | Dead code. Step 1 temporal output replaces it. |
| Separate version selection step (Step 6) | Merged into Step 2A. |
| Candidate article validation (Step 2b Phase A) | Candidate articles removed from Step 1. Concept search in Step 2B replaces it. |

## What Is Preserved

| Component | Where It Lives |
|---|---|
| RL-RAP methodology | Step 4, unchanged core protocol |
| Hybrid retrieval (BM25 + semantic) | Step 3, now per-issue |
| Concept-based search | Step 2B, entity-aware |
| Temporal version awareness | Step 2A, per-fact |
| Pause/resume gate | Step 2E |
| Citation validation | Step 5 |
| ChromaDB service | Unchanged |
| BM25 service | Unchanged |
| Claude service | Unchanged |
| Law mapping service | Reused in Step 2C |
| Version currency check | Reused in Step 2D, with per-law filtering |

---

## Entity-Aware Retrieval

The entity perspective flows from Step 1 through the entire pipeline:

1. **Step 1** identifies per-issue entity perspective (free text, not taxonomy)
2. **Step 1** embeds entity type into concept descriptions (e.g., "obligatiile administratorului SRL" not just "obligatiile administratorului")
3. **Step 2B** searches ChromaDB with entity-aware concepts — semantic similarity naturally favors entity-relevant articles
4. **Step 3** constructs BM25 queries from issue description + entity terms — exact keyword matching catches entity-specific provisions
5. **Step 4** receives correctly scoped articles — no SA articles for SRL questions

No ChromaDB re-indexing required. No hardcoded entity taxonomy. Entity awareness comes from concept description quality, which is a Step 1 prompt concern.

---

## Target Performance

| Metric | Current | Target |
|---|---|---|
| Cost (complex) | $0.40 | $0.12-0.18 |
| Cost (simple) | ~$0.08 | $0.05-0.07 |
| Latency (complex) | 255s | 80-120s |
| Latency (simple) | ~30-40s | 15-25s |
| Step 12 re-runs | ~30-40% | 0% (runs once) |
| Governing norm recall | Unknown | 94%+ (validated) |
| Entity bleeding | Frequent | Eliminated by per-issue scoping |

---

## Implementation Scope

**Rewritten:** `pipeline_service.py` orchestration (~3000 lines -> ~1200-1500 lines)

**Modified:**
- `LA-S1-issue-classifier.txt` — entity perspective, concept descriptions, remove candidate articles
- `LA-S6.8-legal-reasoning.txt` — conflict resolution rules from LA-CONFLICT, no re-run instructions
- `LA-S7-answer-template.txt` — presentation-only constraint, fallback mode
- `version_currency.py` — per-law filtering parameter

**Unchanged:**
- `chroma_service.py`, `bm25_service.py`, `claude_service.py`
- Database models and schemas
- `law_mapping.py` (reused)
- Frontend pipeline visualization (adapts to fewer steps)

**Deleted/deprecated:**
- `reranker_service.py` (no longer called)

---

## Risks and Mitigations

**Risk 1: Step 1 becomes single point of failure.**
Mitigation: Step 1 prompt is already mature (260 lines). Additions are incremental. Test prompt quality on 20+ queries before launch.

**Risk 2: Retrieval recall regression for edge cases.**
Mitigation: Validated at 94.1% on 20 queries. Track `governing_norm_status: MISSING` rate post-launch. If >10%, add targeted single-hop cross-reference lookup.

**Risk 3: Pause/resume mechanism complexity.**
Mitigation: Simpler state (5 steps vs 15). Test pause/resume explicitly during implementation.

**Risk 4: SIMPLE path regression.**
Mitigation: Fast-path Step 2 for SIMPLE queries. Benchmark against current SIMPLE path.

---

## Validation Evidence

Run: `backend/validate_retrieval.py`

- 20 queries tested across corporate, criminal, insolvency, fiscal, civil, EU law domains
- Mix of SIMPLE (6), STANDARD (10), COMPLEX (4) queries
- 51 governing norms expected, 48 found
- 94.1% recall (threshold: 85%)
- 3 misses all attributable to concept description quality, not retrieval architecture
- BM25 critical for short articles (contributed 4 governing norms semantic missed)
- Semantic search critical for conceptual matches (contributed 44 governing norms)
