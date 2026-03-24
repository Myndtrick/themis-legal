# Pipeline Retrieval Redesign: Claude Pre-Screening

## Problem

The Q&A pipeline consistently misses critical law articles for straightforward legal questions. For "what are the min/max limits on associates in SRL/SA?", it fails to find Art. 4 (minimum 2 associates) and Art. 12 (SRL max 50) from Legea 31/1990 — despite retrieving 308 candidate articles.

**Root causes:**
1. Step 6 uses `ms-marco-MiniLM-L-6-v2`, an English cross-encoder, to rank Romanian legal text — it cannot judge relevance in Romanian
2. Entity types identified in Step 1 (e.g., "SRL", "SA") are never used in retrieval
3. The reranker's hard cutoff (top 25 from 308) drops critical articles that score low in the English model

## Solution Overview

Replace the local English cross-encoder reranker (Step 6) with a Claude API call that selects relevant articles from the candidate set. Claude understands Romanian legal terminology and can accurately judge which articles answer the question.

### Pipeline Flow (Before → After)

**Before:**
```
Step 4: BM25 + semantic → ~308 candidates
Step 5: Neighbor expansion → ~308 (same)
Step 6: English cross-encoder → top 25  ← FAILURE POINT
Step 7: Claude generates answer from 25 articles
```

**After:**
```
Step 4: BM25 + semantic (with entity-aware keywords) → ~50-90 candidates
Step 5: Neighbor expansion → ~60-100
Step 6: Claude pre-screening → 20-30 relevant articles
Step 7: Claude generates answer from 20-30 articles
```

## Detailed Design

### Change 1: New Step 6 — Claude Article Selection

**Replace** `_step6_rerank()` in `pipeline_service.py`.

**Input:** All articles from Step 5 expansion (typically 50-100 after dedup).

**Prompt:** A new prompt file `LA-S6-article-selector.txt` that instructs Claude to:
- Read the question and the article summaries
- Select ALL articles that could be relevant to answering the question
- Return a JSON list of selected article IDs
- Consider Romanian legal abbreviations (SRL = societate cu răspundere limitată, etc.)

**Article summary format sent to Claude:**
```
[ID:123] Art. 4, Legea 31/1990 — Societatea cu personalitate juridică va avea cel puțin 2 asociați, în afară de cazul în care legea prevede altfel.
[ID:456] Art. 12, Legea 31/1990 — În societatea cu răspundere limitată, numărul asociaților nu poate fi mai mare de 50.
```

Each article: ID + law reference + full text (NOT truncated to 100 chars — send the full article text up to 500 chars, enough for short articles to be fully represented).

**Claude model:** Use `call_claude()` (non-streaming, synchronous) with the same model as the rest of the pipeline. This is a fast classification task.

**Expected response:**
```json
{
  "selected_ids": [123, 456, 789, ...],
  "reasoning": "Selected articles covering: minimum associate count (Art. 4), maximum SRL associates (Art. 12), ..."
}
```

**Fallback:** If the Claude call fails (timeout, rate limit, API error), fall back to the existing local cross-encoder reranker. Keep `reranker_service.py` intact for this purpose.

**Cost estimate:**
- Input: ~50-100 articles × ~80 tokens each = 4,000-8,000 tokens
- System prompt: ~300 tokens
- Output: ~200 tokens
- Total per call: ~5,000-9,000 tokens
- Cost with Sonnet: ~$0.01-0.03 per question

### Change 2: Entity-Aware BM25 Retrieval in Step 4

**Modify** `_step4_hybrid_retrieval()` in `pipeline_service.py`.

When `state["entity_types"]` contains known corporate forms, add a **targeted keyword search** alongside the regular BM25:

```python
entity_keywords = {
    "SRL": ["răspundere limitată", "asociați", "parte socială"],
    "SA": ["acțiuni", "acționar", "societate pe acțiuni", "capital social"],
    "PFA": ["persoană fizică autorizată", "activitate independentă"],
}
```

For each entity type found, run an additional BM25 query using the entity-specific keywords against the same law versions. Merge results into the candidate set.

This ensures that even if the user's query wording doesn't match the legal text, the entity-specific terms bridge the gap.

### Change 3: Pass Entity Types to Step 6

Include `entity_types` and `legal_topic` from Step 1 classification in the Claude pre-screening prompt. This gives Claude additional context:

```
QUESTION: "intr-un SRL si intr-un SA, exista vreo limita minima sau maxima..."
ENTITY TYPES: SRL, SA
LEGAL TOPIC: număr asociați
```

### Change 4: Update Answer Prompt (LA-S7)

Add to `LA-S7-answer-qa.txt`:

```
COMPLETENESS CHECK:
Before generating your answer, verify that the provided articles cover ALL aspects of the question:
- If the question asks about multiple entities (e.g., SRL AND SA), ensure you have articles about each
- If the question asks about both minimum AND maximum, ensure both are covered
- If you notice a gap, state it explicitly in the missing_info field
```

### Change 5: Simplify BM25 Expansion Dictionary

The `_BM25_EXPANSIONS` in `bm25_service.py` should be extended with the full forms that actually appear in legal text:

```python
_BM25_EXPANSIONS = {
    "srl": ["raspundere", "limitata", "societate", "asociat"],
    "sa": ["actiuni", "actionari", "societate", "anonima"],
    ...
}
```

## Files to Modify

| File | Change |
|------|--------|
| `backend/app/services/pipeline_service.py` | Replace `_step6_rerank()` with Claude selection; add entity-aware retrieval to Step 4 |
| `backend/prompts/LA-S6-article-selector.txt` | **Create** — prompt for Claude article selection |
| `backend/prompts/LA-S7-answer-qa.txt` | Add completeness check instruction |
| `backend/app/services/bm25_service.py` | Extend `_BM25_EXPANSIONS` |
| `backend/app/services/reranker_service.py` | Keep as fallback — no changes |

## Files NOT Modified

| File | Reason |
|------|--------|
| `backend/app/models/law.py` | No schema changes |
| `backend/app/services/chroma_service.py` | Semantic search stays the same |
| `backend/app/services/article_expander.py` | Neighbor expansion stays the same |
| `backend/app/services/claude_service.py` | `call_claude()` already exists and will be reused |
| All frontend files | No UI changes needed |

## Scaling Behavior

| Law Size | BM25+Semantic Candidates | After Expansion | Claude Screens | Articles to Answer |
|----------|--------------------------|-----------------|----------------|-------------------|
| Legea 31 (283 articles) | ~30 | ~40 | ~40 summaries | 15-20 |
| Codul Civil (2,664 articles) | ~15 | ~25 | ~25 summaries | 8-12 |
| Multi-law (3 laws) | ~60 | ~80 | ~80 summaries | 20-30 |

Claude article selection input stays under 10K tokens even for complex multi-law questions.

## Verification

1. **Test the specific failing case:** "intr-un SRL si intr-un SA, exista vreo limita minima sau maxima in ceea ce priveste nr de asociati/actionari?"
   - Verify Art. 4 and Art. 12 are in Claude's selected set
   - Verify the answer mentions "maximum 50" for SRL and "minimum 2" for general companies

2. **Test with Codul Civil question:** "care este termenul de prescripție pentru o acțiune în răspundere contractuală?"
   - Verify relevant prescription articles from Codul Civil are found

3. **Test multi-law question:** "ce capital social minim trebuie sa aiba un SRL si ce obligatii fiscale are?"
   - Verify articles from both Legea 31 and Codul Fiscal are found

4. **Test fallback:** Temporarily disable Claude API key and verify the local reranker fallback works

5. **Monitor pipeline reasoning panel:** Check that the "Top Articles" section in the UI shows the correct articles after the redesign
