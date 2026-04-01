# Pipeline Retrieval Overhaul V4 — Design Spec

## Goal

Fix the root cause of wrong article retrieval: Step 1 hallucinating article numbers, the reranker eliminating correct articles, and Step 12 running twice. Reduce cost from $0.40 to ~$0.19-0.22 per query and time from 255s to ~160s. Step 12 must run only once.

## Architecture

The pipeline remains a 15-step sequential flow. This spec:
- Modifies **Step 1** (LA-S1 prompt schema — add concept descriptions)
- Adds **Step 1c** (new: concept-based article resolution, between Steps 1b and 2)
- Modifies **Step 7** (candidate articles bypass reranker)
- Modifies **Step 9** (reranker only processes non-candidate articles)
- Fixes **Step 9** (min_per_law swap bug)
- Modifies **Step 14** (prompt constraint — presentation only)
- Reduces **retrieval volume** (tier limits)
- Adds **UI visibility** of candidate articles in pipeline analysis frontend

## Root Cause Analysis

### Why the current pipeline costs $0.40 and takes 255s

**Run 515761968198** with the standard test question produced:

1. **Step 1 hallucinated all 6 candidate article numbers.** Claude correctly identified the legal concepts ("administrator liability in Legea 31/1990") but guessed wrong article numbers (art. 138, 139 — both abrogated since 2006; art. 297 — applies to public servants not private administrators; art. 80 — about interest caps not annulment).

2. **The reranker (mmarco-MiniLM) eliminated correct articles.** Articles found by BM25/semantic search that were legally relevant (from graph expansion) scored low because the cross-encoder is trained on web search relevance, not Romanian legal normative connections. All 286/2009 articles were eliminated despite `min_per_law=3`.

3. **Step 12 ran twice.** First run flagged missing governing norms (art. 73, 117, 297, 308). Step 13 fetched them and re-ran Step 12. Cost: $0.28 and 139s just for legal reasoning.

### Why concept search works

Direct evidence from ChromaDB filtered queries:

| Issue | Concept search within law | Result |
|-------|--------------------------|--------|
| ISSUE-1 (31/1990) | "răspunderea civilă personală a administratorului, obligațiile administratorilor față de societate" | All 4 correct articles (72, 73, 144^1, 144^2) in top 5 |
| ISSUE-2 (85/2014) | "acțiuni pentru anularea actelor sau operațiunilor frauduloase ale debitorului în dauna drepturilor creditorilor, în cei 2 ani anteriori deschiderii procedurii" | Art. 117 at #1 |
| ISSUE-3 (286/2009) | "bancruta frauduloasă, infracțiuni contra patrimoniului prin abuz de încredere, gestiune frauduloasă" | Art. 241 at #3, art. 308 at #2, art. 239 at #1 |
| ISSUE-4 (31/1990) | "conflictul de interese al administratorului, obligația de înștiințare pentru operațiuni care depășesc limitele obișnuite" | Art. 78 at #2, art. 144^3 at #1 |

Semantic search within a single law version is far more precise than searching across 180K documents because the concept space is smaller and the embedding model handles intra-law distinctions adequately.

---

## Change 1: Step 1 Schema — Concept Descriptions (LA-S1 Prompt)

### What changes

Each `legal_issues[]` entry outputs two new fields alongside `candidate_articles`:

```json
{
  "issue_id": "ISSUE-1",
  "description": "...",
  "applicable_laws": ["31/1990"],
  "concept_descriptions": [
    {
      "law_key": "31/1990",
      "concept_general": "răspunderea civilă personală a administratorului, obligațiile administratorilor față de societate",
      "concept_specific": "administratorii sunt solidar răspunzători față de societate pentru stricta îndeplinire a îndatoririlor impuse de lege și actul constitutiv"
    }
  ],
  "candidate_articles": [
    {
      "law_key": "31/1990",
      "article": "73",
      "reason": "răspunderea solidară a administratorilor"
    }
  ]
}
```

- `concept_general`: The legal concept in standard Romanian legal terminology. Always provided.
- `concept_specific`: If Claude knows the approximate phrasing of the legal provision, reproduce it. Otherwise `null`.
- `candidate_articles`: Kept as-is (article number guesses). These are validated before use — not trusted blindly.

### Prompt additions to LA-S1

After the existing `candidate_articles` guidance section, add:

```
CONCEPT DESCRIPTIONS (REQUIRED for each applicable law per issue):

For each law listed in an issue's applicable_laws, provide a concept description
that describes the legal provision you expect to find. This description will be
used for semantic search within that specific law to locate the correct articles.

Rules:
- concept_general: Describe the legal norm using precise Romanian legal terminology.
  Use the language the law itself would use, not general paraphrases.
- concept_specific: If you know the approximate wording of the legal provision,
  reproduce it. If unsure, set to null. Do NOT guess — a wrong specific description
  is worse than null.

Examples of GOOD concept descriptions:
  concept_general: "răspunderea solidară a administratorilor față de societate
                     pentru îndeplinirea obligațiilor impuse de lege și actul constitutiv"
  concept_specific: "administratorii sunt solidar răspunzători față de societate pentru
                     stricta îndeplinire a îndatoririlor pe care legea și actul constitutiv
                     le impun"
  → Finds: Art. 73 din Legea 31/1990 (exact match)

  concept_general: "anularea actelor sau operațiunilor frauduloase ale debitorului
                     în dauna creditorilor, în perioada anterioară deschiderii procedurii
                     de insolvență"
  concept_specific: "administratorul judiciar poate introduce acțiuni pentru anularea
                     actelor sau operațiunilor frauduloase ale debitorului în dauna
                     drepturilor creditorilor, în cei 2 ani anteriori deschiderii procedurii"
  → Finds: Art. 117 din Legea 85/2014 (exact match)

Examples of BAD concept descriptions (too generic):
  concept_general: "răspunderea administratorilor"
  → Returns 20+ irrelevant articles
  concept_general: "acte prejudiciabile în insolvență"
  → Misses Art. 117 entirely
```

### File

`prompts/LA-S1-issue-classifier.txt` — add `concept_descriptions` to the JSON schema and add the guidance section.

### Cost impact

Zero. Step 1 output grows by ~200-300 tokens (concept descriptions). Negligible at Sonnet pricing.

---

## Change 2: Step 1c — Concept-Based Article Resolution (New Step)

### What it does

A new function `_step1c_concept_resolution` runs after `_step1b_version_preparation` and before `_step2_law_mapping`. It:

1. **Validates** Claude's proposed `candidate_articles` against the DB
2. **Runs concept search** within each law to find the correct articles
3. **Merges** validated candidates + concept search results into a protected set
4. **Tags** all results as `source: "concept_lookup"` for downstream protection

### Algorithm

```python
def _step1c_concept_resolution(state: dict, db) -> list[dict]:
    protected_articles = []
    seen = set()  # (law_version_id, article_number)

    for issue in state.get("legal_issues", []):
        issue_id = issue["issue_id"]

        # --- Phase A: Validate proposed candidate_articles ---
        for ca in issue.get("candidate_articles", []):
            law_key = ca["law_key"]
            article_num = ca["article"]
            version_ids = state["unique_versions"].get(law_key, [])

            for vid in version_ids:
                article = db.query(Article).filter(
                    Article.law_version_id == vid,
                    Article.article_number == article_num,
                    Article.is_abrogated == False,
                ).first()

                if article and (vid, article_num) not in seen:
                    seen.add((vid, article_num))
                    protected_articles.append(_build_article_dict(
                        article, law_key, vid, issue_id,
                        source="candidate_validated"
                    ))

        # --- Phase B: Concept search within each law ---
        for cd in issue.get("concept_descriptions", []):
            law_key = cd["law_key"]
            version_ids = state["unique_versions"].get(law_key, [])

            for vid in version_ids:
                # Run 1-2 queries per concept
                queries = [cd["concept_general"]]
                if cd.get("concept_specific"):
                    queries.append(cd["concept_specific"])

                for query_text in queries:
                    results = chroma_collection.query(
                        query_texts=[query_text],
                        n_results=5,
                        where={"law_version_id": vid},
                    )

                    # Adaptive: if top distance > 0.35, widen to top 7
                    top_distance = results["distances"][0][0]
                    n_take = 7 if top_distance > 0.35 else 5

                    for i in range(min(n_take, len(results["ids"][0]))):
                        meta = results["metadatas"][0][i]
                        art_num = meta["article_number"]
                        art_id = int(meta["article_id"])

                        if (vid, art_num) in seen:
                            continue
                        if meta.get("is_abrogated") == "True":
                            continue

                        seen.add((vid, art_num))
                        protected_articles.append(_build_article_dict_from_chroma(
                            results, i, law_key, vid, issue_id,
                            source="concept_search"
                        ))

    state["protected_candidates"] = protected_articles
    return protected_articles
```

### Adaptive result count

- Top distance < 0.30: High confidence. Take top 5 results.
- Top distance 0.30-0.35: Moderate. Take top 5.
- Top distance > 0.35: Low confidence. Widen to top 7 for better coverage.

### Output

`state["protected_candidates"]`: list of article dicts, each tagged with:
- `source`: `"candidate_validated"` or `"concept_search"`
- `issue_id`: which issue this candidate belongs to
- `protected`: `True` (flag for downstream steps)

### Expected candidate counts

Per issue: 2-3 validated candidates + 5-7 concept search results = ~7-10 per issue.
For 4 issues with some overlap: ~15-25 unique protected articles total.

### File

`pipeline_service.py` — new function after `_step1b_version_preparation`.

### Cost impact

Zero API cost. ~3-4s latency (6-10 ChromaDB queries at 0.3-0.5s each).

---

## Change 3: Candidate Protection in Steps 7, 8, 9 (Variant 3)

### What changes

Protected candidates from Step 1c bypass the reranker but participate in graph expansion.

### Step 7 (`_step4_hybrid_retrieval`)

Protected candidates are **added to the retrieval pool** alongside BM25/semantic results. They're tagged with `protected: True` so they can be separated later.

No change to how BM25/semantic search works — they continue finding discovery articles independently.

### Step 8 (`_step5_graph_expansion`)

Protected candidates **participate** in graph expansion. If art. 241 (bancruta frauduloasă) is a protected candidate, graph expansion can find its neighbors (art. 239, 240, 242) and cross-references. This is how art. 238 (abuz de încredere, missed by concept search) gets discovered.

No code change needed — protected candidates are already in the retrieval pool, and graph expansion operates on the entire pool.

### Step 9 (`_step6_select_articles`)

**Split the pool before reranking:**

```python
def _step6_select_articles(state, ...):
    raw = state["retrieved_articles_raw"]

    # Separate protected from non-protected
    protected = [a for a in raw if a.get("protected")]
    searchable = [a for a in raw if not a.get("protected")]

    # Rerank only the searchable articles
    ranked = rerank_articles(state["question"], searchable, top_k=top_k)

    # Merge: protected (always kept) + reranked top-k
    state["retrieved_articles"] = protected + ranked
```

Protected candidates always reach Step 11. The reranker only filters BM25/semantic/expansion articles.

### Maximum protected set size

Step 12's context can comfortably handle 40-50K input tokens. With ~20 protected candidates averaging ~800 tokens each, that's ~16K tokens for candidates. Plus ~8K for reranked articles, ~5K for facts/prompt overhead = ~29K total. Well within budget.

### Risk assessment

**If Step 1 generates a wrong concept description:** The concept search returns articles that are semantically close to the wrong concept within the correct law. These articles may not be the exact right ones but they'll be from the right law and broadly related. Step 12 will simply not reference them in its analysis. Cost: a few hundred extra tokens. Impact on answer: none.

**If Step 1 misses a law entirely:** No concept search runs for that law. The law's articles can still be discovered through BM25/semantic search and survive the reranker (especially with the min_per_law fix). This is strictly no worse than the current pipeline.

### Files

`pipeline_service.py` — modify `_step4_hybrid_retrieval` (add protected to pool), `_step6_select_articles` (split before reranking).

### Cost impact

Zero. This reorganizes existing data flow without adding API calls.

---

## Change 4: Fix min_per_law Swap Bug (Step 9)

### The bug

In `reranker_service.py`, the min_per_law enforcement loop (lines ~112-125) has a subtle issue. When swapping a low-scoring article from an over-represented law with a candidate from an under-represented law:

```python
victims = [a for a in selected if law_key_of(a) == over_rep_law]
if not victims:
    break  # BUG: candidate is silently dropped
```

If previous iterations already removed all articles from the over-represented law, `victims` is empty and the `break` exits the loop without adding the needed candidate. The under-represented law gets fewer than `min_per_law` articles.

### Fix

Replace the `break` with an append (expand the selection instead of swapping):

```python
victims = [a for a in selected if law_key_of(a) == over_rep_law]
if not victims:
    # No swap target — expand selection instead
    selected.append(candidate)
    law_counts[law_key] = law_counts.get(law_key, 0) + 1
    continue
```

### File

`reranker_service.py` — one logic change in the min_per_law enforcement loop.

### Cost impact

Zero.

---

## Change 5: Reduce Search Volume (Step 7)

### What changes

Reduce retrieval limits since protected candidates carry the precision load:

| Parameter | Current | New | Rationale |
|-----------|---------|-----|-----------|
| `tier1_limit` (primary laws) | 30 | 15 | Candidates provide precision; search provides discovery only |
| `tier2_limit` (secondary laws) | 15 | 8 | Secondary laws need fewer discovery articles |

### Effect

Total retrieval pool drops from ~122 to ~50-60 articles (before graph expansion). After expansion: ~80-100 instead of ~132. After reranking: ~15-18 non-protected articles instead of ~20.

Combined with ~15-25 protected candidates: total Step 12 input is ~30-40 articles, well within budget.

### File

`pipeline_service.py` — change 2 numeric constants in `_step4_hybrid_retrieval`.

### Cost impact

Zero API cost. Latency saving: ~8-12s (faster retrieval and reranking on smaller pool).

---

## Change 6: Step 14 Prompt Constraint

### What changes

Add explicit presentation-only instructions to the LA-S7 answer template. No code changes — prompt only.

### Addition to LA-S7-answer-template.txt

After the existing "When a LEGAL ANALYSIS is present:" section, add:

```
CRITICAL ROLE CONSTRAINT:
When a LEGAL ANALYSIS section is present, your role is PRESENTATION, not REASONING.
The LEGAL ANALYSIS section contains the definitive legal conclusions produced by
structured legal reasoning. Your job is to:
1. Present these conclusions in natural Romanian as a lawyer explaining to a client
2. Structure the answer by issue, following the analysis structure
3. Use the certainty levels from the analysis to calibrate your language
4. Cite the operative articles referenced in the analysis

You must NOT:
- Re-derive conclusions from the article texts
- Contradict the certainty levels or condition evaluations in the analysis
- Add legal reasoning that is not supported by the analysis
- Cite articles not referenced in the analysis as operative articles
- Use a higher confidence than the analysis supports
```

### Article text in Step 14 context

**Keep Tier 1 (operative article full texts).** Removing them would prevent Step 14 from quoting article text directly, which degrades answer quality. The real fix is the prompt constraint above, not removing context.

### max_tokens

**Keep at 8192.** Reducing to 4096 risks truncating complex multi-issue answers. The COMPLEX question type with 4 issues and closing sections needs the full budget.

### File

`prompts/LA-S7-answer-template.txt` — add ~10 lines of prompt constraint.

### Cost impact

Zero. May save ~3-5s if Claude generates more focused (shorter) answers.

---

## Change 7: UI Visibility of Candidate Articles

### What changes

Show candidate articles per issue in the pipeline analysis UI (Settings > Pipeline > Run Detail).

### Frontend change

In `frontend/src/app/settings/pipeline/run-detail.tsx`, modify the `ClassificationDetail` component to render `candidate_articles` and `concept_descriptions` within each issue's display.

### Display format

Within each issue in the "Issue Decomposition" section, add:

```
Candidate Articles:
  31/1990 art. 73 — "răspunderea solidară a administratorilor"
    ✓ Validated (found in DB, not abrogated)
  31/1990 art. 138 — "răspunderea administratorilor"
    ✗ Abrogated (filtered out)

Concept Descriptions:
  31/1990: "răspunderea civilă personală a administratorului..."
    → Found: art. 144^2, 72, 144^1, 73 (top 4, dist 0.21-0.25)
```

### Backend change

Step 1c should log its results to `output_data` in the step_logs table:

```json
{
  "validated_candidates": [
    {"law_key": "31/1990", "article": "73", "status": "valid", "article_id": 19103}
  ],
  "rejected_candidates": [
    {"law_key": "31/1990", "article": "138", "status": "abrogated"}
  ],
  "concept_search_results": [
    {"issue_id": "ISSUE-1", "law_key": "31/1990", "concept": "răspunderea civilă...",
     "found": ["144^2", "72", "144^1", "73"], "top_distance": 0.21}
  ],
  "total_protected": 18
}
```

### Files

- `frontend/src/app/settings/pipeline/run-detail.tsx` — modify `ClassificationDetail` component
- `pipeline_service.py` — log Step 1c output_data via `log_step()`

### Cost impact

Zero.

---

## Implementation Order

All changes are independent except Step 1c depends on the Step 1 schema change.

```
Batch 1 (parallel):
  ├── Change 1: LA-S1 prompt schema (concept_descriptions)
  ├── Change 4: Fix min_per_law bug (one-line fix)
  ├── Change 5: Reduce search volume (two numbers)
  └── Change 6: Step 14 prompt constraint

Batch 2 (sequential, depends on Change 1):
  ├── Change 2: Step 1c concept resolution (new function)
  └── Change 3: Candidate protection in Steps 7/9

Batch 3 (independent):
  └── Change 7: UI visibility (frontend + logging)
```

---

## Projected Outcome

### Cost

| Component | Current ($0.40) | After changes |
|-----------|----------------|---------------|
| Step 1 (classification) | $0.014 | $0.015 (slightly more output) |
| Step 1c (concept resolution) | N/A | $0 (local ChromaDB) |
| Step 12 (legal reasoning) | $0.28 (2 runs) | **$0.14 (1 run)** |
| Step 14 (answer generation) | $0.03 | $0.03 (unchanged) |
| Other steps | $0 | $0 |
| **Total** | **$0.40** | **~$0.19-0.22** |

### Latency

| Component | Current (255s) | After changes |
|-----------|---------------|---------------|
| Step 1 | 31s | 31s |
| Step 1c | N/A | +3-4s |
| Steps 2-6 | 6s | 6s |
| Step 7 (retrieval) | 20s | 12-15s (reduced volume) |
| Steps 8-9 (expansion + reranking) | 21s | 12-15s (smaller pool) |
| Steps 10-11 | 0.1s | 0.1s |
| Step 12 | 139s (2 runs) | **65-70s (1 run)** |
| Step 13 | 0s | 0s (no re-run needed) |
| Step 14 | 34s | 30-34s |
| Step 15 | 0s | 0s |
| **Total** | **255s** | **~160-170s** |

### Quality

- Correct articles reach Step 12 on the first pass (no missing governing norms)
- Step 14 presents Step 12's conclusions faithfully (no contradiction)
- min_per_law works correctly for discovery articles
- Candidate articles visible in UI for operator verification

---

## What This Spec Does NOT Address

- **60-90s latency target:** Not achievable without changing models (Haiku) or merging steps (12+14). These are quality tradeoffs that should be evaluated separately after this spec is deployed and measured.
- **Reranker replacement:** Not needed. Protected candidates bypass the reranker, and the min_per_law fix ensures discovery articles have fair representation.
- **Per-issue parallel Step 12:** Not needed. Single Step 12 run with correct articles is fast enough and preserves cross-issue coherence.
- **Step 2 Phase 2 per-fact version mapping:** Already implemented in V3. This spec builds on top of it.

---

## Verification Plan

After implementation, run the same test question ("Dacă un administrator al unui SRL transferă bani...") and verify:

1. **Step 1** generates concept_descriptions for each issue/law pair
2. **Step 1c** finds art. 72, 73, 144^1, 144^2 for ISSUE-1; art. 117 for ISSUE-2; art. 241, 239, 308 for ISSUE-3; art. 78 for ISSUE-4
3. **Step 1c** rejects abrogated candidates (art. 138, 139 if still proposed)
4. **Step 9** does not eliminate protected candidates
5. **Step 12** runs exactly once with all governing norms present
6. **Step 14** presents Step 12's conclusions without contradiction
7. **Total cost** is $0.19-0.22
8. **Total time** is 155-175s
9. **Pipeline UI** shows candidate articles per issue with validation status
