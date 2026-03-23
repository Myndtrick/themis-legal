# Structured Legal Retrieval Pipeline — Design Spec

## Problem

The current RAG pipeline uses semantic search (ChromaDB) + keyword search (SQLite LIKE) to find relevant law articles. This approach has fundamental weaknesses:

1. **Short critical articles are missed.** Art. 4 of Legea 31/1990 ("cel puțin 2 asociați") is one sentence — too short for embeddings to rank it, and keyword search drowns it in 300+ false positives.
2. **Keyword search is noisy.** Searching for "asociați" returns 121 articles. Fusion and merger articles score higher than the actual rule articles because they contain more keyword matches.
3. **No structural awareness.** The search doesn't know that Art. 4 is in the "General Provisions" chapter, or that Art. 12 is a neighbor of Art. 13 (asociat unic). Legal articles derive meaning from their position in the law's structure.
4. **No secondary law coverage.** When Legea 31/1990 is PRIMARY, the Codul Civil applies subsidiarily — but the pipeline has no systematic way to retrieve relevant Codul Civil articles.
5. **No reasoning visibility.** The "Show details" panel doesn't work because the frontend and backend disagree on the data format.

## Design — Structured Retrieval Pipeline

Replace the current search-based retrieval (Steps 3-7) with a structured pipeline that mirrors how a Romanian lawyer actually finds applicable law.

### Overview

```
Question → Step 1: Classify → Step 2: Map to Laws (rule-based)
→ Step 3: Select Versions → Step 4: Hybrid Search (BM25 + Semantic)
→ Step 5: Expand Neighbors + Cross-refs → Step 6: Rerank (local model)
→ Step 7: Generate Answer
```

Steps 1, 3, and 7 use Claude API. Steps 2, 4, 5, 6 are local/deterministic — zero API cost.

---

### Step 1 — Issue Classification (Claude API)

**Input:** User question + conversation history
**Output:** Structured JSON with topic, domain, entity type, date

```json
{
  "legal_topic": "număr asociați / acționari",
  "legal_domain": "corporate",
  "entity_types": ["SRL", "SA"],
  "relevant_date": "2026-03-23",
  "date_logic": "current law, no specific date mentioned"
}
```

**What changes from current:** The current Step 1 already does this. Minor prompt adjustment to extract `legal_topic` as a more specific string (not just domain).

**File:** `backend/app/services/pipeline_service.py` — modify `_step1_issue_classification`
**Prompt:** `backend/prompts/LA-S1-issue-classifier.txt` — add `legal_topic` field

---

### Step 2 — Law Applicability Mapping (Rule-Based, No Claude)

**Input:** legal_topic, legal_domain, entity_types from Step 1
**Output:** Tiered list of applicable laws

```json
{
  "tier1_primary": [
    {"law_number": "31", "law_year": 1990, "reason": "Legea societăților — directly governs SRL/SA"}
  ],
  "tier2_secondary": [
    {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — applies subsidiarily to all corporate matters"}
  ],
  "tier3_connected": []
}
```

**How the rule map works:**

A deterministic mapping dictionary. No Claude call needed.

```python
DOMAIN_LAW_MAP = {
    "corporate": {
        "primary": [
            {"law_number": "31", "law_year": 1990, "reason": "Legea societăților comerciale"},
        ],
        "secondary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — subsidiarily"},
        ],
    },
    "fiscal": {
        "primary": [
            {"law_number": "227", "law_year": 2015, "reason": "Codul Fiscal"},
        ],
        "secondary": [
            {"law_number": "207", "law_year": 2015, "reason": "Codul de Procedură Fiscală"},
        ],
    },
    "employment": {
        "primary": [
            {"law_number": "53", "law_year": 2003, "reason": "Codul Muncii"},
        ],
        "secondary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — subsidiarily"},
        ],
    },
    # ... more domains added as laws are imported
}
```

The map is verified against the database — only laws that are actually imported are included. If a PRIMARY law is not in the database, the pipeline flags it for import (existing Step 5 behavior).

**Fallback:** If the domain has no mapping (new domain, or question spans multiple domains), fall back to the current Claude-based law identification (Step 3 from current pipeline).

**File:** New file `backend/app/services/law_mapping.py`

---

### Step 3 — Version Selection (DB Query, Already Implemented)

No changes. Select the correct version of each mapped law for the relevant date.

**File:** `backend/app/services/pipeline_service.py` — existing `_step6_version_selection`

---

### Step 4 — Hybrid Retrieval (BM25 + Semantic, No Claude)

Run two searches in parallel, both filtered to the selected law versions:

**4a — BM25 Full-Text Search (SQLite FTS5)**

Create a virtual FTS5 table that indexes article text + amendment notes. BM25 is excellent for exact term matching — it will find "asociați" in Art. 4 without the noise problems of LIKE search because BM25 ranks by term frequency and document length (short articles with the search term rank higher).

```sql
CREATE VIRTUAL TABLE articles_fts USING fts5(
    full_text,
    amendment_text,
    content='articles',
    content_rowid='id'
);
```

Query: `SELECT * FROM articles_fts WHERE articles_fts MATCH 'asociați OR asociat' AND law_version_id IN (...)`

BM25 naturally favors short documents that are dense in the search terms — exactly what we need for Art. 4 and Art. 12.

**4b — ChromaDB Semantic Search (Already Implemented)**

Same as current, filtered by law_version_ids.

**Merge:** Combine results from both searches, deduplicate by article_id. Keep top N per tier:
- TIER 1 (PRIMARY): top 15 articles
- TIER 2 (SECONDARY): top 10 articles
- TIER 3 (CONNECTED): top 5 articles (only if triggered by Step 5)

**Files:**
- New: `backend/app/services/bm25_service.py` — FTS5 setup, indexing, querying
- Modify: `backend/app/services/chroma_service.py` — simplify (remove keyword search hack)
- Modify: `backend/app/services/pipeline_service.py` — new `_step4_hybrid_retrieval`

---

### Step 5 — Structural Expansion (DB Query, No Claude)

For each article found in Step 4, expand the context:

**5a — Neighbor Articles**
Add articles N-2 to N+2 from the same structural section (chapter/section). This catches:
- Art. 4 (neighbor of Art. 3/5 which search finds)
- Definition articles at the start of chapters
- Exception articles immediately following a rule

Implementation: Query the `structural_elements` table to find the parent section, then get all articles in that section within range.

```python
def expand_neighbors(db, article_id, range=2):
    article = db.query(Article).get(article_id)
    section_id = article.structural_element_id
    neighbors = db.query(Article).filter(
        Article.structural_element_id == section_id,
        Article.order_index.between(
            article.order_index - range,
            article.order_index + range
        )
    ).all()
    return neighbors
```

**5b — Cross-Reference Extraction**
Parse article text for explicit references to other articles or laws:
- "conform art. 153" → fetch Art. 153 from the same law
- "prevăzut la art. 237 din Legea nr. 31/1990" → fetch Art. 237
- "în condițiile Codului Civil" → trigger TIER 3 retrieval for Codul Civil

Regex patterns for Romanian legal cross-references:
```
art\.\s*(\d+)
art\.\s*(\d+)\s*alin\.\s*\((\d+)\)
Legea\s*nr\.\s*(\d+)/(\d{4})
Codul\s*(Civil|Fiscal|Muncii|Penal)
```

**5c — Definition Articles**
For each structural section containing a found article, also fetch articles titled "Definiții" or "Dispoziții generale" from the same title/chapter.

**File:** New function in `backend/app/services/pipeline_service.py` — `_step5_expand_articles`

---

### Step 6 — Reranking (Local Model, No Claude)

Take all candidate articles from Steps 4+5 (typically 30-60 articles after expansion). Score each against the original question using a cross-encoder model.

**Model:** `cross-encoder/ms-marco-MiniLM-L-6-v2`
- Free, open source, ~80MB
- Runs locally via `sentence-transformers` (already installed)
- Scores each article in ~5ms → 50 articles = ~250ms
- Produces a relevance score 0-1 for each article

```python
from sentence_transformers import CrossEncoder
model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')

scores = model.predict([
    (question, article.full_text) for article in candidates
])
```

**Keep:** Top 15 articles by reranker score. Discard the rest (noise removed before sending to Claude).

**Per-tier limits after reranking:**
- From TIER 1 laws: up to 12 articles
- From TIER 2 laws: up to 5 articles
- From TIER 3 laws: up to 3 articles

**File:** New file `backend/app/services/reranker_service.py`

---

### Step 7 — Answer Generation (Claude API)

Same as current, but with better context:

**Input to Claude:**
- Original question
- Top 15 reranked articles with:
  - Full article text (verbatim from DB)
  - Article number, law name, version date
  - Which tier the law came from (PRIMARY/SECONDARY/CONNECTED)
  - Reranker confidence score
  - Amendment notes if any
- Version context (which versions were selected and why)

**Output:** Structured JSON (same format as current):
```json
{
  "short_answer": "...",
  "legal_basis": "...",
  "version_logic": "...",
  "nuances": "...",
  "sources": [...]
}
```

**Change from current:** The prompt adds a rule: "If the reranker confidence for an article is below 0.3, treat it as [Unverified] and flag it."

**File:** Modify prompts in `backend/prompts/LA-S7*.txt`

---

### Reasoning/Details Panel Fix

**Problem:** The backend stores `reasoning_data` as the raw reasoning dict `{step1_classification: ..., step3_laws: ...}` but the frontend `AnswerDetail` component expects `{structured: {...}, reasoning: {...}, confidence: "...", flags: [...]}`.

**Fix:** In the SSE router (`routers/assistant.py`), when storing the assistant message, combine both:

```python
combined_data = {
    "structured": event.get("structured"),   # from pipeline done event
    "reasoning": event.get("reasoning"),      # from pipeline done event
    "confidence": event.get("confidence"),
    "flags": event.get("flags", []),
}
reasoning_data = json.dumps(combined_data)
```

This is a one-line fix in `routers/assistant.py` where the assistant message is stored after the `done` event.

**File:** `backend/app/routers/assistant.py` — fix the `add_message` call in event_generator

---

## New Files

| File | Purpose |
|------|---------|
| `backend/app/services/law_mapping.py` | Deterministic domain → law mapping (Step 2) |
| `backend/app/services/bm25_service.py` | SQLite FTS5 setup, indexing, querying (Step 4a) |
| `backend/app/services/reranker_service.py` | Cross-encoder reranking (Step 6) |

## Modified Files

| File | Change |
|------|--------|
| `backend/app/services/pipeline_service.py` | Replace Steps 3-7 with new Steps 2-7 |
| `backend/app/services/chroma_service.py` | Simplify — remove keyword search, keep semantic only |
| `backend/app/routers/assistant.py` | Fix reasoning_data format in stored messages |
| `backend/prompts/LA-S1-issue-classifier.txt` | Add legal_topic extraction |
| `backend/prompts/LA-S7-answer-qa.txt` | Add reranker confidence awareness |
| `backend/app/main.py` | Initialize FTS5 index on startup |

## Cost Per Question

| Step | Claude API? | Cost |
|------|------------|------|
| Step 1 — Classification | Yes | ~$0.01 |
| Step 2 — Law Mapping | No (rule-based) | $0 |
| Step 3 — Version Selection | No (DB query) | $0 |
| Step 4 — Hybrid Search | No (FTS5 + ChromaDB) | $0 |
| Step 5 — Expansion | No (DB query) | $0 |
| Step 6 — Reranking | No (local model) | $0 |
| Step 7 — Answer Generation | Yes | ~$0.05 |
| **Total** | **2 API calls** | **~$0.06** |

## Verification

Test with these questions after implementation:

1. "Ce capital social trebuie un SRL la înființare?" → Should cite Art. 11 amendment (500 lei) from Legea 239/2025
2. "Într-un SRL și într-un SA, există vreo limită în ceea ce privește nr de asociați?" → Should cite Art. 4 (min 2), Art. 12 (max 50 SRL), Art. 13 (asociat unic)
3. "Care sunt obligațiile unui administrator de SRL?" → Should cite Art. 197, Art. 194 + relevant Codul Civil articles (if imported)
4. Follow-up: "Dar într-un SA?" → Should reuse context, cite SA administrator articles
