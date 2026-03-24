# Token Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce pipeline token usage from 30,000-70,000 to ~8,000-12,000 input tokens per question while maintaining answer accuracy.

**Architecture:** Replace Claude-based article selection (Step 6) with the existing local reranker, remove the redundant relevance check (Step 6.5), truncate conversation history in Step 7, enable prompt caching, and add local date extraction.

**Tech Stack:** Python, Anthropic SDK (>=0.40.0), sentence-transformers CrossEncoder, regex

**Dependencies:** Task 3 depends on Task 1 (needs real reranker scores, not synthetic ones from Claude path).

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `backend/app/services/pipeline_service.py` | Modify | Tasks 1-3, 5-6 — rewrite Steps 6, 6.5, 7, 1b |
| `backend/app/services/claude_service.py` | Modify | Task 4 — enable prompt caching |
| `backend/app/services/date_extractor.py` | Create | Task 5 — local date extraction with regex |

---

### Task 1: Replace Step 6 Claude call with local reranker

**Files:**
- Modify: `backend/app/services/pipeline_service.py` — the `_step6_select_articles` function and `_step6_rerank_fallback`

The fallback reranker (`_step6_rerank_fallback`) already does exactly what we need. We promote it to be the primary (and only) method.

- [ ] **Step 1: Rewrite `_step6_select_articles` to use reranker directly**

Replace the entire function body. The new function skips the Claude call entirely and uses the local reranker:

```python
def _step6_select_articles(state: dict, db: Session) -> dict:
    """Select top articles using local cross-encoder reranker."""
    from app.services.reranker_service import rerank_articles

    t0 = time.time()
    raw = state.get("retrieved_articles_raw", [])
    if not raw:
        state["retrieved_articles"] = []
        log_step(db, state["run_id"], "article_selection", 6, "done", 0,
                 output_summary="No articles to select from")
        return state

    ranked = rerank_articles(state["question"], raw, top_k=20)
    state["retrieved_articles"] = ranked

    kept_ids = {a["article_id"] for a in ranked}
    dropped = [a for a in raw if a["article_id"] not in kept_ids]

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "article_selection", 6, "done", duration,
        output_summary=f"Reranker: {len(raw)} -> top {len(ranked)} articles",
        output_data={
            "method": "reranker",
            "kept_articles": [
                {
                    "article_id": a["article_id"],
                    "article_number": a.get("article_number"),
                    "law": f"{a.get('law_number')}/{a.get('law_year')}",
                    "score": round(a.get("reranker_score", 0), 3),
                }
                for a in ranked
            ],
            "dropped_count": len(dropped),
            "total_candidates": len(raw),
        },
    )
    return state
```

- [ ] **Step 2: Delete `_step6_rerank_fallback` function**

Remove the old fallback function since it's now the primary path integrated into `_step6_select_articles`.

- [ ] **Step 3: Verify the pipeline still runs**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.services.pipeline_service import run_pipeline; print('OK')"`
Expected: `OK` (no import errors)

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "perf: replace Claude article selection (Step 6) with local reranker

Saves ~24,000-40,000 input tokens per question. The cross-encoder
reranker (ms-marco-MiniLM-L-6-v2) was already the fallback — now
promoted to primary. top_k=20 caps articles for downstream steps."
```

---

### Task 2: Truncate conversation history in Step 7

**Files:**
- Modify: `backend/app/services/pipeline_service.py` — the `_step7_answer_generation` function, history construction block

Note: Article cap is not needed here because Task 1 already caps at top_k=20 via the reranker.

- [ ] **Step 1: Truncate conversation history in Step 7**

In `_step7_answer_generation`, find the history construction block and replace:

```python
# Before:
history_msgs = []
for msg in state.get("session_context", [])[-10:]:
    history_msgs.append({"role": msg["role"], "content": msg["content"]})

# After:
history_msgs = []
for msg in state.get("session_context", [])[-5:]:
    history_msgs.append({"role": msg["role"], "content": msg["content"][:500]})
```

This matches Step 1's approach: last 5 messages, 500 chars each.

- [ ] **Step 2: Verify the pipeline still runs**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.services.pipeline_service import run_pipeline; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "perf: truncate Step 7 history to 5 msgs x 500 chars

Saves ~5,000-15,000 input tokens per question. Matches Step 1's
truncation approach — last 5 messages, 500 chars each."
```

---

### Task 3: Remove Step 6.5 Claude call, derive relevance from reranker scores

**Depends on:** Task 1 (needs real cross-encoder scores from reranker, not synthetic ones)

**Files:**
- Modify: `backend/app/services/pipeline_service.py` — the `_step6_5_relevance_gate` function
- Note: This function is called from both `run_pipeline` (line ~238) and `resume_pipeline` (line ~358). Both callers use the same interface `(events, gate_result)` — no caller changes needed since the function signature stays the same.

The cross-encoder reranker scores can replace the Claude relevance check. If the top reranker score is very low, articles are likely irrelevant. Cross-encoder `ms-marco-MiniLM-L-6-v2` scores typically range from -10 to +10.

- [ ] **Step 1: Rewrite `_step6_5_relevance_gate` to use reranker scores**

Replace the function. Preserves the "missing law import" feature by checking if laws from the domain mapping are actually in the DB:

```python
def _step6_5_relevance_gate(state: dict, db: Session) -> tuple[list[dict], dict | None]:
    """Check if selected articles are relevant using reranker scores (no Claude call).

    Called from both run_pipeline and resume_pipeline.
    """
    t0 = time.time()
    retrieved = state.get("retrieved_articles", [])
    events = []

    if not retrieved:
        events.append(_step_event(7, "relevance_check", "done", {"skipped": True}, 0))
        return events, None

    # Use the top reranker score as a relevance proxy
    # Cross-encoder ms-marco-MiniLM-L-6-v2 scores range roughly -10 to +10
    top_score = max((a.get("reranker_score", 0) for a in retrieved), default=0)
    avg_score = sum(a.get("reranker_score", 0) for a in retrieved) / len(retrieved)

    # Normalize to 0-1: score of -5 → 0.0, score of +10 → 1.0
    relevance_score = min(1.0, max(0.0, (top_score + 5) / 15))
    state["relevance_score"] = relevance_score

    gate_will_trigger = relevance_score < 0.2  # ~top_score < -2 (clearly irrelevant)
    gate_will_warn = 0.2 <= relevance_score < 0.4  # ~top_score < 1

    duration = time.time() - t0
    events.append(_step_event(7, "relevance_check", "done", {
        "relevance_score": round(relevance_score, 3),
        "top_reranker_score": round(top_score, 3),
        "avg_reranker_score": round(avg_score, 3),
        "gate_triggered": gate_will_trigger,
        "gate_warning": gate_will_warn,
        "method": "reranker_scores",
    }, duration))

    if gate_will_warn:
        state["flags"].append(
            f"Low article relevance (score: {relevance_score:.2f}) — answer may be incomplete"
        )

    if gate_will_trigger:
        clarification_round = _count_clarification_rounds(state.get("session_context", []))

        # Try to identify missing laws from the domain mapping
        candidate_laws = state.get("candidate_laws", [])
        primary_missing = [
            c for c in candidate_laws
            if c.get("tier") == "tier1_primary" and not c.get("db_law_id")
        ]

        if primary_missing:
            # We know which laws are needed → offer import
            law_names = ", ".join(
                f"{l.get('title', '')} ({l['law_number']}/{l['law_year']})"
                for l in primary_missing
            )
            content = (
                f"Pentru a răspunde corect la această întrebare, am nevoie de articole din: "
                f"{law_names}. "
                f"Aceste legi nu sunt în biblioteca juridică. "
                f"Doriți să le importați din legislatie.just.ro?"
            )
            return events, {
                "type": "done",
                "run_id": state["run_id"],
                "content": content,
                "structured": None,
                "mode": "needs_import",
                "output_mode": "needs_import",
                "confidence": "LOW",
                "flags": state.get("flags", []),
                "reasoning": _build_reasoning_panel(state),
                "clarification_type": "missing_law",
                "missing_laws": [
                    {
                        "law_number": l["law_number"],
                        "law_year": l["law_year"],
                        "title": l.get("title", ""),
                        "reason": l.get("reason", ""),
                    }
                    for l in primary_missing
                ],
            }

        if clarification_round >= 1:
            state["flags"].append(
                f"Low relevance (score: {relevance_score:.2f}) but proceeding after "
                f"{clarification_round} clarification round(s)"
            )
            state["confidence"] = "MEDIUM"
            return events, None

        # First time: trigger clarification
        state["confidence"] = "LOW"
        clarification_msg = (
            "Nu am putut identifica articole suficient de relevante pentru "
            "întrebarea dumneavoastră. Puteți preciza despre ce lege sau "
            "domeniu juridic este vorba?"
        )
        return events, {
            "type": "done",
            "run_id": state["run_id"],
            "content": clarification_msg,
            "structured": None,
            "mode": "clarification",
            "output_mode": "clarification",
            "confidence": "LOW",
            "flags": state.get("flags", []),
            "reasoning": _build_reasoning_panel(state),
            "clarification_type": "missing_context",
            "missing_laws": [],
        }

    return events, None
```

- [ ] **Step 2: Verify the pipeline still runs**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.services.pipeline_service import run_pipeline; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "perf: replace Step 6.5 Claude relevance check with reranker scores

Saves ~800 tokens and 1 API call per question. Derives relevance
from cross-encoder scores instead of a separate Claude call. Gate
logic preserved: missing law import, clarification, and warning
paths all retained using candidate_laws state and reranker scores."
```

---

### Task 4: Enable prompt caching in claude_service.py

**Files:**
- Modify: `backend/app/services/claude_service.py`

The Anthropic SDK supports prompt caching by passing `system` as a list of content blocks with `cache_control`. This caches static system prompts at 90% discount on subsequent calls (within 5-min TTL).

- [ ] **Step 1: Add a helper to wrap system prompts for caching**

Add after the constants at the top of `claude_service.py`:

```python
def _cacheable_system(system: str) -> list[dict]:
    """Wrap a system prompt string as a cacheable content block."""
    return [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }
    ]
```

- [ ] **Step 2: Update `call_claude` to use cached system prompts**

In the `client.messages.create()` call, change:

```python
# Before:
system=system,

# After:
system=_cacheable_system(system),
```

- [ ] **Step 3: Update `stream_claude` to use cached system prompts**

In the `client.messages.stream()` call, change:

```python
# Before:
system=system,

# After:
system=_cacheable_system(system),
```

- [ ] **Step 4: Log cache usage in both functions**

After getting the response, add cache token logging. In `call_claude`, after `response = client.messages.create(...)`:

```python
cache_created = getattr(response.usage, "cache_creation_input_tokens", 0)
cache_read = getattr(response.usage, "cache_read_input_tokens", 0)
if cache_created or cache_read:
    logger.info("Cache: created=%d read=%d", cache_created, cache_read)
```

In `stream_claude`, after `final = stream.get_final_message()`, add the same logging using `final.usage`.

- [ ] **Step 5: Verify the service still loads**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.services.claude_service import call_claude, stream_claude; print('OK')"`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/claude_service.py
git commit -m "perf: enable Anthropic prompt caching for all Claude calls

System prompts are now sent as cacheable content blocks. After first
call, cached prompts cost 90% less. Saves ~2,250 tokens equivalent
per question across 2 remaining Claude calls (S1, S7)."
```

---

### Task 5: Local date extraction for Step 1b

**Files:**
- Create: `backend/app/services/date_extractor.py`
- Modify: `backend/app/services/pipeline_service.py` — the `_step1b_date_extraction` function

Most questions either have no date (use today) or an obvious explicit date like "in 2023". A local regex extractor handles 90%+ of cases without a Claude call.

- [ ] **Step 1: Create `date_extractor.py`**

```python
"""Local date extraction — handles explicit dates without a Claude API call."""
from __future__ import annotations

import datetime
import re

# Patterns for Romanian date expressions
_FULL_DATE = re.compile(
    r"(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})"  # DD.MM.YYYY or DD/MM/YYYY
)
_YEAR_PHRASE = re.compile(
    r"\b(?:in|din|anul|din anul|pe|la)\s+(\d{4})\b", re.IGNORECASE
)
_RELATIVE_YEARS = re.compile(
    r"\bacum\s+(\d+)\s+ani?\b", re.IGNORECASE
)
_RELATIVE_MONTHS = re.compile(
    r"\bacum\s+(\d+)\s+luni?\b", re.IGNORECASE
)


def _safe_replace_year(d: datetime.date, year: int) -> datetime.date:
    """Replace year safely, handling Feb 29 on non-leap years."""
    try:
        return d.replace(year=year)
    except ValueError:
        # Feb 29 on a non-leap year -> use Feb 28
        return d.replace(year=year, day=28)


def extract_date_local(question: str, today: str) -> dict:
    """Extract a primary date from the question using regex.

    Returns a dict matching the Claude date extractor output schema.
    Always returns a result (falls back to today's date).
    """
    today_date = datetime.date.fromisoformat(today)

    # 1. Full date: DD.MM.YYYY
    m = _FULL_DATE.search(question)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            d = datetime.date(year, month, day)
            return _result(d.isoformat(), "explicit", m.group(0))
        except ValueError:
            pass

    # 2. "in 2023", "din anul 2020", etc. (requires a date-introducing word)
    m = _YEAR_PHRASE.search(question)
    if m:
        return _result(m.group(1), "explicit", m.group(0))

    # 3. "acum 3 ani"
    m = _RELATIVE_YEARS.search(question)
    if m:
        years_ago = int(m.group(1))
        d = _safe_replace_year(today_date, today_date.year - years_ago)
        return _result(d.isoformat(), "relative", m.group(0))

    # 4. "acum 6 luni"
    m = _RELATIVE_MONTHS.search(question)
    if m:
        months_ago = int(m.group(1))
        year = today_date.year
        month = today_date.month - months_ago
        while month <= 0:
            month += 12
            year -= 1
        d = _safe_replace_year(today_date, year).replace(month=month)
        return _result(d.isoformat(), "relative", m.group(0))

    # 5. No date found — use today (implicit current)
    # Note: we intentionally do NOT match standalone years (e.g., "1990")
    # because they usually appear in law references like "Legea 31/1990"
    return _result(today, "implicit_current", "")


def _result(date: str, date_type: str, source_text: str) -> dict:
    return {
        "primary_date": date,
        "dates_found": [
            {
                "date": date,
                "type": date_type,
                "context": "extracted locally",
                "source_text": source_text,
            }
        ],
        "date_logic": (
            f"Local extraction: {date_type} date '{source_text}'"
            if source_text
            else "No date mentioned, using current date"
        ),
        "needs_clarification": False,
    }
```

- [ ] **Step 2: Update Step 1b to use local extractor, skip Claude**

Replace `_step1b_date_extraction` in `pipeline_service.py`. Keep the `log_step` call for observability:

```python
def _step1b_date_extraction(state: dict, db: Session) -> dict:
    """Extract temporal context — local regex, no Claude call."""
    from app.services.date_extractor import extract_date_local

    t0 = time.time()
    parsed = extract_date_local(state["question"], state["today"])

    if parsed and parsed.get("primary_date"):
        state["primary_date"] = parsed["primary_date"]
        state["date_logic"] = parsed.get("date_logic", "")
        state["dates_found"] = parsed.get("dates_found", [])

        if parsed.get("needs_clarification"):
            state["flags"].append(
                f"Date ambiguous: {parsed.get('date_logic', 'unclear temporal context')} "
                f"— using {state['primary_date']} as best estimate"
            )
    else:
        state["flags"].append("No specific date detected — using current law versions")

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "date_extraction", 15, "done", duration,
        input_summary=state["question"][:200],
        output_summary=f"primary_date={state.get('primary_date')}",
        output_data=parsed,
    )

    return state
```

- [ ] **Step 3: Verify import works**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.services.date_extractor import extract_date_local; print(extract_date_local('Ce capital social trebuie un SRL in 2024?', '2026-03-24'))"`
Expected: `{'primary_date': '2024', ...}`

Also verify law references are NOT matched as dates:
Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.services.date_extractor import extract_date_local; r = extract_date_local('Care sunt obligatiile conform Legii 31/1990?', '2026-03-24'); print(r['primary_date'])"`
Expected: `2026-03-24` (today's date, not 1990)

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/date_extractor.py backend/app/services/pipeline_service.py
git commit -m "perf: replace Claude date extraction (Step 1b) with local regex

Handles explicit dates (DD.MM.YYYY, 'in 2023'), relative dates
('acum 3 ani'), and implicit current. Does NOT match standalone
years in law references (e.g., 'Legea 31/1990'). Saves ~550 tokens
and 1 API call per question."
```

---

### Task 6: Clean up dead code and verify end-to-end

**Files:**
- Modify: `backend/app/services/pipeline_service.py` — remove dead imports, old Step 6 article formatting code

- [ ] **Step 1: Remove unused imports and dead code**

Search for and remove:
- Any remaining references to the old `_step6_rerank_fallback`
- The old article summary formatting code that built `articles_block` for Claude in the old `_step6_select_articles`
- Unused prompt loading for `LA-S6` and `LA-S6.5` (the `load_prompt()` calls)
- Old `LA-S2` prompt loading in the old `_step1b_date_extraction`

- [ ] **Step 2: Test the full pipeline manually**

Start the backend and send a test question through the UI. Verify:
1. No errors in backend logs
2. Answer is generated successfully
3. Step indicators show in the UI
4. Response quality looks correct

- [ ] **Step 3: Check token usage in logs**

After a test question, check the backend logs for token counts on the remaining Claude calls (S1, S7). Expected:
- S1 (classification): ~1,200 tokens
- S7 (answer): ~6,000-10,000 tokens (down from 25,000-40,000)
- Total: ~7,000-11,000 tokens (down from 30,000-70,000)

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "chore: remove dead code from token optimization migration"
```

---

## Verification

After all tasks:
1. Send 3 different test questions through the UI
2. Verify answers are accurate and well-cited
3. Check backend logs — total tokens per question should be ~8,000-12,000
4. Send 2 questions within 1 minute — should NOT hit rate limit
5. Verify the step indicator in the UI still shows all steps progressing

## Token Budget After All Changes

| Step | Tokens (before) | Tokens (after) | Change |
|------|-----------------|----------------|--------|
| S1 Classification | 1,200 | 1,200 | same |
| S1b Date Extraction | 550 | 0 | **eliminated** |
| S6 Article Selection | 24,000-40,000 | 0 | **eliminated** |
| S6.5 Relevance Check | 800 | 0 | **eliminated** |
| S7 Answer Generation | 25,000-30,000 | 6,000-10,000 | **-70%** |
| **Total** | **30,000-70,000** | **~7,000-11,000** | **-75-85%** |

Claude API calls reduced from **5 per question to 2** (S1 + S7).
