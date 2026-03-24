# Pipeline Retrieval Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the English cross-encoder reranker with a Claude-based article selection step so the pipeline correctly identifies relevant Romanian law articles.

**Architecture:** Step 6 (reranking) becomes a Claude `call_claude()` call that receives article summaries and selects relevant ones. Step 4 (retrieval) gains entity-aware keyword searches. The existing reranker is kept as fallback. The answer prompt (Step 7) gets a completeness check instruction.

**Tech Stack:** Python, FastAPI, SQLAlchemy, Anthropic SDK (`call_claude`), SQLite FTS5

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/prompts/LA-S6-article-selector.txt` | Create | Prompt for Claude article selection |
| `backend/app/services/pipeline_service.py` | Modify | Replace `_step6_rerank`, add entity-aware retrieval to Step 4, update reasoning panel |
| `backend/app/services/bm25_service.py` | Modify | Extend `_BM25_EXPANSIONS` dictionary |
| `backend/prompts/LA-S7-answer-qa.txt` | Modify | Add completeness check instruction |
| `backend/app/services/reranker_service.py` | No change | Kept as fallback |

---

### Task 1: Create the Article Selector Prompt

**Files:**
- Create: `backend/prompts/LA-S6-article-selector.txt`

- [ ] **Step 1: Write the prompt file**

```text
You are the Article Selector for the Themis Legal Assistant.

Your task: Given a legal question and a list of candidate law articles, select ALL articles that are relevant to answering the question. Be inclusive — it is better to include a borderline article than to miss a critical one.

ROMANIAN LEGAL ABBREVIATIONS (use these to understand the question):
- SRL = Societate cu Răspundere Limitată (limited liability company)
- SA = Societate pe Acțiuni (joint stock company)
- PFA = Persoană Fizică Autorizată (authorized natural person)
- TVA = Taxa pe Valoarea Adăugată (VAT)
- CIM = Contract Individual de Muncă (individual employment contract)

SELECTION CRITERIA:
- Select articles that DIRECTLY answer any part of the question
- Select articles that define key terms used in the question
- Select articles that set limits, thresholds, or conditions relevant to the question
- Select articles that provide exceptions or special cases
- When the question mentions multiple entities (e.g., SRL AND SA), ensure you select articles covering EACH entity
- When the question asks about both minimum AND maximum, ensure both are covered
- Short articles (1-2 sentences) that directly state a rule are HIGHLY valuable — do not skip them because they are short

RESPONSE FORMAT — respond with valid JSON only:

{
  "selected_ids": [list of article_id integers],
  "reasoning": "Brief explanation of what aspects of the question each selected article covers"
}

IMPORTANT:
- Return ONLY article IDs that appear in the provided list
- Select between 10 and 30 articles (prefer 15-25)
- If fewer than 10 articles seem relevant, include borderline ones
- NEVER return an empty list
```

- [ ] **Step 2: Commit**

```bash
git add backend/prompts/LA-S6-article-selector.txt
git commit -m "feat: add Claude article selector prompt (LA-S6)"
```

---

### Task 2: Replace Step 6 with Claude Article Selection

**Files:**
- Modify: `backend/app/services/pipeline_service.py:620-643`

- [ ] **Step 1: Replace `_step6_rerank` function**

Replace the existing `_step6_rerank` function (lines 620-643) with:

```python
# ---------------------------------------------------------------------------
# Step 6: Article Selection (Claude-based, with local reranker fallback)
# ---------------------------------------------------------------------------


def _step6_select_articles(state: dict, db: Session) -> dict:
    """Use Claude to select relevant articles from the candidate set.
    Falls back to local cross-encoder reranker if Claude call fails.
    """
    t0 = time.time()
    raw = state.get("retrieved_articles_raw", [])

    if not raw:
        state["retrieved_articles"] = []
        log_step(db, state["run_id"], "article_selection", 6, "done", 0,
                 output_summary="No articles to select from")
        return state

    # Build compact article summaries for Claude
    article_summaries = []
    for art in raw:
        text_preview = art.get("text", "")[:500]
        summary = (
            f"[ID:{art['article_id']}] Art. {art.get('article_number', '?')}, "
            f"Legea {art.get('law_number', '?')}/{art.get('law_year', '?')} — "
            f"{text_preview}"
        )
        article_summaries.append(summary)

    articles_block = "\n\n".join(article_summaries)

    # Build the user message with question context
    entity_types = state.get("entity_types", [])
    legal_topic = state.get("legal_topic", "")

    user_msg = (
        f"QUESTION: {state['question']}\n"
    )
    if entity_types:
        user_msg += f"ENTITY TYPES: {', '.join(entity_types)}\n"
    if legal_topic:
        user_msg += f"LEGAL TOPIC: {legal_topic}\n"
    user_msg += f"\nCANDIDATE ARTICLES ({len(raw)} total):\n\n{articles_block}"

    # Load the article selector prompt
    prompt_text, prompt_ver = load_prompt("LA-S6", db)

    try:
        result = call_claude(
            system=prompt_text,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=1024,
            temperature=0.0,
        )
        content = result["content"]

        # Parse JSON response
        import json as _json
        # Strip markdown code fences if present
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[1:])
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        parsed = _json.loads(cleaned)
        selected_ids = set(parsed.get("selected_ids", []))
        selection_reasoning = parsed.get("reasoning", "")

        # Filter articles to only those selected by Claude
        selected = [art for art in raw if art["article_id"] in selected_ids]

        # If Claude selected nothing useful, fall back
        if not selected:
            logger.warning("Claude selected 0 articles — falling back to reranker")
            return _step6_rerank_fallback(state, db, t0)

        # Add a score based on selection order (all selected are equally relevant)
        for i, art in enumerate(selected):
            art["reranker_score"] = 1.0 - (i * 0.01)  # Preserve order, all positive

        state["retrieved_articles"] = selected

        duration = time.time() - t0
        log_step(
            db, state["run_id"], "article_selection", 6, "done", duration,
            output_summary=f"Claude selected {len(selected)} from {len(raw)} articles",
            output_data={
                "top_articles": [
                    {"article_number": a.get("article_number"), "law": f"{a.get('law_number')}/{a.get('law_year')}"}
                    for a in selected[:10]
                ],
                "selection_reasoning": selection_reasoning,
                "prompt_version": prompt_ver,
                "claude_tokens_in": result.get("tokens_in", 0),
                "claude_tokens_out": result.get("tokens_out", 0),
            },
        )
        return state

    except Exception as e:
        logger.warning(f"Claude article selection failed: {e} — falling back to reranker")
        return _step6_rerank_fallback(state, db, t0)


def _step6_rerank_fallback(state: dict, db: Session, t0: float) -> dict:
    """Fallback: use the local cross-encoder reranker."""
    from app.services.reranker_service import rerank_articles

    raw = state.get("retrieved_articles_raw", [])
    ranked = rerank_articles(state["question"], raw, top_k=25)
    state["retrieved_articles"] = ranked

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "article_selection", 6, "done", duration,
        output_summary=f"FALLBACK reranker: {len(raw)} -> top {len(ranked)} articles",
        output_data={"top_articles": [
            {"article_number": a.get("article_number"), "score": a.get("reranker_score", 0)}
            for a in ranked[:5]
        ]},
    )
    state["flags"].append("Used local reranker fallback (Claude article selection failed)")
    return state
```

- [ ] **Step 2: Update the pipeline runner to call the new function**

In the `run_pipeline` function, find the block (around lines 159-165):
```python
        # Step 6: Reranking (local cross-encoder)
        yield _step_event(6, "reranking", "running")
        t0 = time.time()
        state = _step6_rerank(state, db)
        yield _step_event(6, "reranking", "done", {
            "top_articles": len(state.get("retrieved_articles", [])),
        }, time.time() - t0)
```

Replace with:
```python
        # Step 6: Article Selection (Claude-based)
        yield _step_event(6, "article_selection", "running")
        t0 = time.time()
        state = _step6_select_articles(state, db)
        yield _step_event(6, "article_selection", "done", {
            "top_articles": len(state.get("retrieved_articles", [])),
        }, time.time() - t0)
```

- [ ] **Step 3: Update the reasoning panel**

In `_build_reasoning_panel` (around line 828), change the key from `step6_reranking` to `step6_selection`:
```python
        "step6_selection": {
            "top_articles": [
                {"article_number": a.get("article_number"), "score": round(a.get("reranker_score", 0), 3), "law": f"{a.get('law_number')}/{a.get('law_year')}"}
                for a in state.get("retrieved_articles", [])[:10]
            ],
        },
```

- [ ] **Step 4: Verify the import for `call_claude` exists at top of file**

Check the imports at the top of `pipeline_service.py`. `call_claude` should already be imported:
```python
from app.services.claude_service import call_claude, stream_claude
```

If not, add it.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: replace English reranker with Claude article selection (Step 6)"
```

---

### Task 3: Add Entity-Aware Retrieval to Step 4

**Files:**
- Modify: `backend/app/services/pipeline_service.py:520-569`

- [ ] **Step 1: Add entity keyword map and targeted search to `_step4_hybrid_retrieval`**

Add the entity keyword map at module level (before `_step4_hybrid_retrieval`):

```python
_ENTITY_KEYWORDS: dict[str, list[str]] = {
    "SRL": ["raspundere limitata", "asociati", "parte sociala", "parti sociale"],
    "SA": ["actiuni", "actionar", "societate pe actiuni", "capital social", "adunarea generala"],
    "PFA": ["persoana fizica autorizata", "activitate independenta"],
}
```

Then at the end of `_step4_hybrid_retrieval`, after the existing tier loop but before setting `state["retrieved_articles_raw"]`, add entity-aware retrieval:

```python
    # Entity-aware targeted retrieval
    entity_types = state.get("entity_types", [])
    if entity_types:
        # Get all version IDs from primary tier
        primary_version_ids = []
        for law in state.get("law_mapping", {}).get("tier1_primary", []):
            key = f"{law['law_number']}/{law['law_year']}"
            v = state.get("selected_versions", {}).get(key)
            if v:
                primary_version_ids.append(v["law_version_id"])

        if primary_version_ids:
            for entity in entity_types:
                keywords = _ENTITY_KEYWORDS.get(entity.upper(), [])
                for kw in keywords:
                    entity_results = search_bm25(db, kw, primary_version_ids, limit=10)
                    for art in entity_results:
                        aid = art["article_id"]
                        if aid not in seen_ids:
                            seen_ids.add(aid)
                            art["tier"] = "entity_targeted"
                            art["source"] = f"entity:{entity}"
                            all_articles.append(art)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: add entity-aware keyword retrieval to Step 4"
```

---

### Task 4: Extend BM25 Expansion Dictionary

**Files:**
- Modify: `backend/app/services/bm25_service.py:92-102`

- [ ] **Step 1: Update `_BM25_EXPANSIONS`**

Replace the existing `_BM25_EXPANSIONS` dict with:

```python
_BM25_EXPANSIONS: dict[str, list[str]] = {
    "srl": ["raspundere", "limitata", "societate", "asociat", "parte sociala"],
    "sa": ["actiuni", "actionari", "societate", "anonima", "capital social"],
    "pfa": ["persoana", "fizica", "autorizata", "activitate independenta"],
    "asociat": ["asociati", "asociatii", "asociatilor", "numar asociati"],
    "actionar": ["actionari", "actionarii", "actionarilor", "numar actionari"],
    "minim": ["minimum", "minima", "cel putin", "mai mic"],
    "maxim": ["maximum", "maxima", "mai mare", "nu poate fi mai mare", "cel mult"],
    "limita": ["limitare", "limitat", "plafon", "nu poate depasi"],
    "numar": ["numarul", "nr"],
    "capital": ["capitalul", "capital social"],
    "dividende": ["dividend", "profit", "distribuire"],
    "administrator": ["administratori", "administratorii", "administratorilor", "consiliu"],
    "contract": ["contractul", "contracte", "contractului", "act constitutiv"],
}
```

- [ ] **Step 2: Rebuild FTS index to pick up changes**

```bash
cd backend && .venv/bin/python -c "
from app.database import SessionLocal
from app.services.bm25_service import rebuild_fts_index
db = SessionLocal()
rebuild_fts_index(db)
db.close()
print('FTS index rebuilt')
"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/bm25_service.py
git commit -m "feat: extend BM25 query expansion with legal synonyms"
```

---

### Task 5: Update Answer Prompt with Completeness Check

**Files:**
- Modify: `backend/prompts/LA-S7-answer-qa.txt`

- [ ] **Step 1: Add completeness check to the prompt**

Append the following before the final `LAW CONFLICT RESOLUTION` section (before line 45):

```text

COMPLETENESS CHECK:
Before generating your answer, verify that the provided articles cover ALL aspects of the question:
- If the question asks about multiple entities (e.g., SRL AND SA), ensure you address each with specific articles
- If the question asks about both minimum AND maximum, ensure both are covered by cited articles
- If the question asks about multiple conditions (e.g., formation AND dissolution), address each
- Short articles that directly state a numerical limit or rule are especially important — do not overlook them
- If you notice a gap (articles provided don't cover a part of the question), state it explicitly in the missing_info field
```

- [ ] **Step 2: Commit**

```bash
git add backend/prompts/LA-S7-answer-qa.txt
git commit -m "feat: add completeness check instruction to answer prompt"
```

---

### Task 6: Register LA-S6 Prompt in the Manifest

The prompt system uses a `PROMPT_MANIFEST` dict in `prompt_service.py` to map prompt IDs to files. The new `LA-S6` prompt must be registered so `load_prompt("LA-S6", db)` works.

**Files:**
- Modify: `backend/app/services/prompt_service.py:14-55` (the `PROMPT_MANIFEST` dict)

- [ ] **Step 1: Add LA-S6 to PROMPT_MANIFEST**

In `backend/app/services/prompt_service.py`, add this entry to the `PROMPT_MANIFEST` dict (after the `LA-S5` entry, around line 30):

```python
    "LA-S6": {
        "file": "LA-S6-article-selector.txt",
        "desc": "Step 6 — Article Selector",
    },
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/prompt_service.py
git commit -m "feat: register LA-S6 article selector prompt in manifest"
```

---

### Task 7: End-to-End Verification

- [ ] **Step 1: Restart the backend**

Restart `npm run dev:backend` to load all changes.

- [ ] **Step 2: Test the failing case**

In the Themis UI, create a new chat and ask:
```
intr-un SRL si intr-un SA, exista vreo limita minima sau maxima in ceea ce priveste nr de asociati/actionari?
```

**Expected results:**
- Pipeline reasoning shows "Claude selected X from Y articles"
- Top Articles list includes Art. 4 and Art. 12 from Legea 31/1990
- Answer mentions: SRL maximum 50 associates (Art. 12), general minimum 2 associates (Art. 4)
- Confidence should be HIGH

- [ ] **Step 3: Test a Codul Civil question**

```
care este termenul de prescripție pentru o acțiune în răspundere contractuală?
```

Verify relevant prescription articles are found and the answer is accurate.

- [ ] **Step 4: Test fallback behavior**

Temporarily break the Claude API call (e.g., set wrong API key) and verify the pipeline falls back to the local reranker with a flag in the output.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: pipeline retrieval redesign — Claude article selection"
```
