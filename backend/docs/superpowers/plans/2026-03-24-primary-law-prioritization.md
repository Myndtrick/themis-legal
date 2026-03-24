# Primary Law Prioritization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure PRIMARY law articles rank above SECONDARY law articles in retrieval results, so Claude answers from the directly applicable law first.

**Architecture:** Add a `role` field ("PRIMARY"/"SECONDARY") to every article dict flowing through the pipeline. Apply an additive score boost in the reranker based on role. Tag articles with `[PRIMARY]`/`[SECONDARY]` in the Claude prompt context and add a prompt rule to prioritize PRIMARY articles.

**Tech Stack:** Python (pipeline_service.py, reranker_service.py), text prompts (LA-S7-*)

**Spec:** `docs/superpowers/specs/2026-03-24-primary-law-prioritization-design.md`

---

### Task 1: Add `role` field in Step 4 hybrid retrieval

**Files:**
- Modify: `backend/app/services/pipeline_service.py:940-948` (tier loop merge section)
- Modify: `backend/app/services/pipeline_service.py:967-974` (entity-targeted section)

- [ ] **Step 1: Add role mapping and tag articles in tier loop**

In `_step4_hybrid_retrieval()`, add a mapping dict at the top of the function (after `tier_limits`), and set `role` alongside `tier` when merging articles:

```python
# Add after tier_limits (line 916):
TIER_TO_ROLE = {
    "tier1_primary": "PRIMARY",
    "tier2_secondary": "SECONDARY",
}
```

Then in the merge loop (line 945), add role alongside tier:

```python
# Change line 945 from:
art["tier"] = tier_key
# To:
art["tier"] = tier_key
art["role"] = TIER_TO_ROLE.get(tier_key, "SECONDARY")
```

- [ ] **Step 2: Tag entity-targeted articles as PRIMARY**

In the entity-targeted section (line 971), add role:

```python
# Change line 971 from:
art["tier"] = "entity_targeted"
# To:
art["tier"] = "entity_targeted"
art["role"] = "PRIMARY"
```

- [ ] **Step 3: Verify — restart backend, run a query, check pipeline debug tab**

Run a query like "ce capital social minim trebuie la infiintare SRL". In the pipeline debug tab, Step 4 output should show articles with `role` field in the top_articles log. Verify PRIMARY articles have `role: "PRIMARY"` and SECONDARY have `role: "SECONDARY"`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: add role field (PRIMARY/SECONDARY) to articles in hybrid retrieval"
```

---

### Task 2: Add `role` to expansion and exception articles (Steps 5 & 5.5)

**Files:**
- Modify: `backend/app/services/pipeline_service.py:1070-1081` (Step 5 expansion append)
- Modify: `backend/app/services/pipeline_service.py:1130-1141` (Step 5.5 exception append)

- [ ] **Step 1: Create a helper to derive role from law_number/law_year**

Add a small helper function before `_step5_expand()` (around line 1043):

```python
def _derive_role(law_number: str, law_year: str, state: dict) -> str:
    """Determine if an article's law is PRIMARY or SECONDARY based on law mapping."""
    for law in state.get("law_mapping", {}).get("tier1_primary", []):
        if str(law["law_number"]) == str(law_number) and str(law["law_year"]) == str(law_year):
            return "PRIMARY"
    return "SECONDARY"
```

- [ ] **Step 2: Use helper in Step 5 expansion**

In `_step5_expand()`, after building the article dict (line 1070-1081), add `role`:

```python
# After line 1080 (tier: "expansion"), add:
"role": _derive_role(law.law_number, str(law.law_year), state),
```

The full dict append becomes:

```python
state["retrieved_articles_raw"].append({
    "article_id": art.id,
    "article_number": art.article_number,
    "law_version_id": version.id,
    "law_number": law.law_number,
    "law_year": str(law.law_year),
    "law_title": law.title[:200],
    "date_in_force": str(version.date_in_force) if version.date_in_force else "",
    "text": "\n".join(text_parts),
    "source": "expansion",
    "tier": "expansion",
    "role": _derive_role(law.law_number, str(law.law_year), state),
})
```

- [ ] **Step 3: Use helper in Step 5.5 exception retrieval**

Same change in `_step5_5_exception_retrieval()` (line 1130-1141):

```python
state["retrieved_articles_raw"].append({
    "article_id": art.id,
    "article_number": art.article_number,
    "law_version_id": version.id,
    "law_number": law.law_number,
    "law_year": str(law.law_year),
    "law_title": law.title[:200],
    "date_in_force": str(version.date_in_force) if version.date_in_force else "",
    "text": "\n".join(text_parts),
    "source": "exception",
    "tier": "exception",
    "role": _derive_role(law.law_number, str(law.law_year), state),
})
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: derive role for expansion and exception articles from law mapping"
```

---

### Task 3: Apply tier boost in reranker

**Files:**
- Modify: `backend/app/services/reranker_service.py:26-49`

- [ ] **Step 1: Add TIER_BOOST constant and apply after scoring**

Edit `reranker_service.py`. Add the constant at module level (after line 14) and the boost logic after scoring (after line 46):

```python
# Add at module level (after MODEL_NAME):
# Additive boost to cross-encoder scores based on law role.
# PRIMARY articles get a relevance bonus so they rank above SECONDARY
# unless significantly less relevant. Calibrate against actual score
# distributions from pipeline logs.
TIER_BOOST = {
    "PRIMARY": 0.15,
    "SECONDARY": 0.0,
}
```

Then in `rerank_articles()`, after the scoring loop (line 46), add:

```python
    for art, score in zip(articles, scores):
        art["reranker_score"] = float(score)

    # Apply tier-based boost: PRIMARY articles get a relevance bonus
    for art in articles:
        role = art.get("role", "SECONDARY")
        boost = TIER_BOOST.get(role, 0.0)
        if boost:
            art["reranker_score"] += boost

    articles.sort(key=lambda x: x["reranker_score"], reverse=True)
    return articles[:top_k]
```

- [ ] **Step 2: Verify — restart backend, run same query, check Step 6 output**

Run "ce capital social minim trebuie la infiintare SRL". In the pipeline debug tab, Step 6 should now show Legea 31/1990 articles ranking higher than before. The top articles should include articles from 31/1990 (PRIMARY), not be dominated by 287/2009 (SECONDARY).

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/reranker_service.py
git commit -m "feat: apply tier-aware score boost in reranker (PRIMARY +0.15)"
```

---

### Task 4: Prepend role tags in answer generation context

**Files:**
- Modify: `backend/app/services/pipeline_service.py:1360-1371` (article formatting in Step 7)

- [ ] **Step 1: Add role tag to article context formatting**

In `_step7_answer_generation()`, modify the article formatting loop (lines 1360-1371). Add the role tag at the start of each article header:

```python
# Replace lines 1360-1371 with:
for i, art in enumerate(retrieved, 1):
    role_tag = f"[{art.get('role', 'SECONDARY')}] " if art.get("role") else ""
    abrogated_tag = " [ABROGATED — this article has been repealed]" if art.get("is_abrogated") else ""
    articles_context += (
        f"[Article {i}] {role_tag}{abrogated_tag}{art.get('law_title', '')} "
        f"({art.get('law_number', '')}/{art.get('law_year', '')}), "
        f"Art. {art.get('article_number', '')}"
    )
    if art.get("date_in_force"):
        articles_context += f", version {art['date_in_force']}"
    if art.get("reranker_score") is not None:
        articles_context += f" [relevance: {art['reranker_score']:.2f}]"
    articles_context += f"\n{art.get('text', '')}\n\n"
```

This produces output like:
```
[Article 1] [PRIMARY] Legea societăților comerciale (31/1990), Art. 11, version 2025-12-18 [relevance: 0.87]
<article text>

[Article 5] [SECONDARY] Codul Civil (287/2009), Art. 769, version 2025-12-19 [relevance: 0.72]
<article text>
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: prepend [PRIMARY]/[SECONDARY] role tags in Claude article context"
```

---

### Task 5: Update answer prompts with PRIMARY prioritization rule

**Files:**
- Modify: `backend/prompts/LA-S7-answer-qa.txt:69-73` (after LAW CONFLICT RESOLUTION)
- Modify: `backend/prompts/LA-S7-M2-answer-memo.txt:24-33` (RULES section)
- Modify: `backend/prompts/LA-S7-M3-answer-comparison.txt:24-33`
- Modify: `backend/prompts/LA-S7-M4-answer-compliance.txt:24-33`
- Modify: `backend/prompts/LA-S7-M5-answer-checklist.txt:24-33`

- [ ] **Step 1: Add rule to LA-S7-answer-qa.txt**

Append after line 73 (after the LAW CONFLICT RESOLUTION section):

```
ARTICLE PRIORITY:
- Articles marked [PRIMARY] are from the directly applicable law (lex specialis).
  Articles marked [SECONDARY] apply subsidiarily. Build your answer primarily from
  [PRIMARY] articles. Use [SECONDARY] articles only to complement where the primary
  law is silent or to provide general framework context.
```

- [ ] **Step 2: Add same rule to LA-S7-M2-answer-memo.txt**

Append after the last RULES line (line 33):

```

ARTICLE PRIORITY:
- Articles marked [PRIMARY] are from the directly applicable law (lex specialis).
  Articles marked [SECONDARY] apply subsidiarily. Build the memo primarily from
  [PRIMARY] articles. Use [SECONDARY] articles only to complement where the primary
  law is silent or to provide general framework context.
```

- [ ] **Step 3: Add same rule to LA-S7-M3-answer-comparison.txt**

Append after the last RULES line (line 33):

```

ARTICLE PRIORITY:
- Articles marked [PRIMARY] are from the directly applicable law (lex specialis).
  Articles marked [SECONDARY] apply subsidiarily. Compare versions from [PRIMARY]
  articles first. Use [SECONDARY] articles only for context where the primary
  law is silent.
```

- [ ] **Step 4: Add same rule to LA-S7-M4-answer-compliance.txt**

Append after the last RULES line (line 33):

```

ARTICLE PRIORITY:
- Articles marked [PRIMARY] are from the directly applicable law (lex specialis).
  Articles marked [SECONDARY] apply subsidiarily. Assess compliance primarily against
  [PRIMARY] articles. Use [SECONDARY] articles only where the primary law is silent
  or to provide general framework context.
```

- [ ] **Step 5: Add same rule to LA-S7-M5-answer-checklist.txt**

Append after the last RULES line (line 33):

```

ARTICLE PRIORITY:
- Articles marked [PRIMARY] are from the directly applicable law (lex specialis).
  Articles marked [SECONDARY] apply subsidiarily. Build the checklist primarily from
  [PRIMARY] articles. Use [SECONDARY] articles only where the primary law is silent
  or to provide general framework context.
```

- [ ] **Step 6: Commit**

```bash
git add backend/prompts/LA-S7-answer-qa.txt backend/prompts/LA-S7-M2-answer-memo.txt backend/prompts/LA-S7-M3-answer-comparison.txt backend/prompts/LA-S7-M4-answer-compliance.txt backend/prompts/LA-S7-M5-answer-checklist.txt
git commit -m "feat: add PRIMARY/SECONDARY article priority rule to all answer prompts"
```

---

### Task 6: End-to-end verification

- [ ] **Step 1: Restart backend**

- [ ] **Step 2: Test PRIMARY prioritization**

Ask: "ce capital social minim trebuie la infiintare SRL"
- Pipeline debug: Step 4 should show `role` on articles
- Pipeline debug: Step 6 top articles should include Legea 31/1990 (PRIMARY) in top positions
- Answer should cite Legea 31/1990 articles as primary source

- [ ] **Step 3: Test all-SECONDARY case**

Ask a general question where no PRIMARY law is mapped. Verify pipeline works without errors and no boost is applied.

- [ ] **Step 4: Check reranker score distributions**

In the pipeline debug, note the actual score range from the cross-encoder. If scores range much wider than [-1, 1], the 0.15 boost may need adjustment. Log this for future tuning.
