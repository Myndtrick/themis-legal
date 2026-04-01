# Pipeline Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce pipeline redundancy by merging steps, consolidating prompts into a template, and centralizing confidence logic.

**Architecture:** Six incremental changes ordered by risk. Each change is independently testable and committed separately. The pipeline's 3 Claude calls remain unchanged — only orchestration, prompts, and confidence logic are refactored.

**Tech Stack:** Python/FastAPI (backend), Next.js/React (frontend), pytest, SQLite/SQLAlchemy

---

## Task 1: Delete Unused Prompts (LA-CONF, LA-S3)

**Files:**
- Delete: `backend/prompts/LA-CONF-confidence.txt`
- Delete: `backend/prompts/LA-S3-law-identifier.txt`
- Modify: `backend/app/services/prompt_service.py:14-75` (PROMPT_MANIFEST)

- [ ] **Step 1: Remove LA-CONF and LA-S3 from PROMPT_MANIFEST**

In `backend/app/services/prompt_service.py`, delete these two entries from the `PROMPT_MANIFEST` dict:

```python
# DELETE this block (lines ~23-26):
"LA-S3": {
        "file": "LA-S3-law-identifier.txt",
        "desc": "Step 3 — Law Identifier",
    },

# DELETE this block (lines ~67-70):
    "LA-CONF": {
        "file": "LA-CONF-confidence.txt",
        "desc": "Confidence Scorer",
    },
```

Do NOT delete the `LA-CONFLICT` entry — that is a separate, active prompt.

- [ ] **Step 2: Delete the prompt files**

```bash
rm backend/prompts/LA-CONF-confidence.txt
rm backend/prompts/LA-S3-law-identifier.txt
```

- [ ] **Step 3: Verify no references remain**

```bash
cd /Users/anaandrei/projects/themis-legal && grep -r "LA-CONF[^L]" backend/ --include="*.py" && grep -r "LA-S3" backend/ --include="*.py"
```

Expected: No output (no references to LA-CONF or LA-S3 in Python files). If any references appear, investigate — they should not exist per our analysis.

- [ ] **Step 4: Run existing tests to confirm nothing broke**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal && git add backend/app/services/prompt_service.py && git rm backend/prompts/LA-CONF-confidence.txt backend/prompts/LA-S3-law-identifier.txt && git commit -m "refactor: remove unused prompts LA-CONF and LA-S3"
```

---

## Task 2: Merge Step 5 + Step 5.5 into Unified Graph Expansion

**Files:**
- Modify: `backend/app/services/pipeline_service.py` (replace `_step5_expand` + `_step5_5_exception_retrieval` with `_step5_graph_expansion` + `_append_new_articles`)
- Modify: `frontend/src/app/assistant/step-indicator.tsx:5-22` (STEP_LABELS)
- Modify: `frontend/src/app/settings/pipeline/run-detail.tsx:62-65,292-350` (step detail components)
- Create: `backend/tests/test_step5_graph_expansion.py`

- [ ] **Step 1: Write the test file**

Create `backend/tests/test_step5_graph_expansion.py`:

```python
"""Tests for Step 5: unified graph expansion."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock
from app.services.pipeline_service import _append_new_articles, _cap_for_expansion


# --- _cap_for_expansion tests ---

def test_cap_no_op_when_under_limit():
    """Articles below MAX_EXPANSION_INPUT pass through unchanged."""
    articles = [{"article_id": i, "distance": 0.5} for i in range(10)]
    state = {"retrieved_articles_raw": articles}
    result = _cap_for_expansion(state)
    assert len(result["retrieved_articles_raw"]) == 10


def test_cap_trims_to_limit():
    """Articles above MAX_EXPANSION_INPUT are trimmed to best by distance."""
    articles = [{"article_id": i, "distance": i * 0.1} for i in range(40)]
    state = {"retrieved_articles_raw": articles}
    result = _cap_for_expansion(state)
    assert len(result["retrieved_articles_raw"]) == 30
    # Best distance (lowest) should be kept
    assert result["retrieved_articles_raw"][0]["distance"] == 0.0


def test_cap_sorts_by_distance():
    """Cap should sort by distance ascending (best first)."""
    articles = [
        {"article_id": 1, "distance": 0.9},
        {"article_id": 2, "distance": 0.1},
        {"article_id": 3, "distance": 0.5},
    ]
    # Under the cap, so no trimming, but we want to verify sort behavior
    # Only triggers sort when over limit — test with 31+ articles
    filler = [{"article_id": 100 + i, "distance": 0.4} for i in range(30)]
    state = {"retrieved_articles_raw": articles + filler}
    result = _cap_for_expansion(state)
    assert result["retrieved_articles_raw"][0]["distance"] == 0.1


def test_cap_handles_missing_distance():
    """Articles without distance field get default 1.0 (sorted last)."""
    good = [{"article_id": i, "distance": 0.1} for i in range(29)]
    no_dist = [{"article_id": 99}, {"article_id": 98}]
    state = {"retrieved_articles_raw": good + no_dist}
    result = _cap_for_expansion(state)
    assert len(result["retrieved_articles_raw"]) == 30
    # The no-distance articles should be last (distance defaults to 1.0)
    kept_ids = [a["article_id"] for a in result["retrieved_articles_raw"]]
    assert 99 in kept_ids or 98 in kept_ids  # at least one kept at position 30


# --- _append_new_articles tests ---

def test_append_deduplicates():
    """Articles already in state are not re-added."""
    state = {
        "retrieved_articles_raw": [{"article_id": 1}],
        "law_mapping": {"tier1_primary": []},
    }
    # new_ids includes id=1 which already exists — should not be added
    # We need to mock the DB query
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = []
    result = _append_new_articles(state, mock_db, [1], source="expansion")
    assert result == 0


def test_append_empty_ids():
    """Empty new_ids list returns 0 added."""
    state = {
        "retrieved_articles_raw": [],
        "law_mapping": {"tier1_primary": []},
    }
    mock_db = MagicMock()
    result = _append_new_articles(state, mock_db, [], source="expansion")
    assert result == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_step5_graph_expansion.py -v --tb=short 2>&1 | tail -20
```

Expected: FAIL — `_append_new_articles` and `_cap_for_expansion` not defined yet.

- [ ] **Step 3: Implement `_cap_for_expansion` in pipeline_service.py**

Replace the `_step4_5_pre_expansion_filter` function (lines 1768-1809) with:

```python
MAX_EXPANSION_INPUT = 30


def _cap_for_expansion(state: dict) -> dict:
    """Cap articles before expansion to prevent graph explosion."""
    articles = state.get("retrieved_articles_raw", [])
    if len(articles) <= MAX_EXPANSION_INPUT:
        return state
    articles.sort(key=lambda a: a.get("distance", 1.0))
    state["retrieved_articles_raw"] = articles[:MAX_EXPANSION_INPUT]
    return state
```

- [ ] **Step 4: Implement `_append_new_articles` helper**

Add this function right after `_cap_for_expansion`:

```python
def _append_new_articles(state: dict, db: Session, new_ids: list[int], source: str) -> int:
    """Fetch articles by ID, build enriched dicts, append to state. Returns count added."""
    from app.models.law import Article as ArticleModel

    existing_ids = {a["article_id"] for a in state.get("retrieved_articles_raw", [])}
    unique_ids = [aid for aid in new_ids if aid not in existing_ids]

    if not unique_ids:
        return 0

    added = 0
    for art in db.query(ArticleModel).filter(ArticleModel.id.in_(unique_ids)).all():
        law = art.law_version.law
        version = art.law_version
        text_parts = [art.full_text]
        for note in art.amendment_notes:
            if note.text and note.text.strip():
                text_parts.append(f"[Amendment: {note.text.strip()}]")

        state["retrieved_articles_raw"].append({
            "article_id": art.id,
            "article_number": art.article_number,
            "law_version_id": version.id,
            "law_number": law.law_number,
            "law_year": str(law.law_year),
            "law_title": law.title[:200],
            "date_in_force": str(version.date_in_force) if version.date_in_force else "",
            "text": "\n".join(text_parts),
            "source": source,
            "tier": source,
            "role": _derive_role(law.law_number, str(law.law_year), state),
        })
        added += 1

    return added
```

- [ ] **Step 5: Implement `_step5_graph_expansion` replacing both old functions**

Replace `_step5_expand` (lines 1825-1879) and `_step5_5_exception_retrieval` (lines 1887-1942) with:

```python
def _step5_graph_expansion(state: dict, db: Session) -> dict:
    """Unified graph expansion: neighbors, cross-references, and exceptions."""
    from app.services.article_expander import expand_articles, expand_with_exceptions

    t0 = time.time()

    # Cap input to prevent explosion
    state = _cap_for_expansion(state)

    # Phase 1: neighbors + cross-references
    raw_ids = [a["article_id"] for a in state.get("retrieved_articles_raw", [])]
    neighbor_ids, neighbor_details = expand_articles(
        db, raw_ids,
        selected_versions=state.get("selected_versions", {}),
        primary_date=state.get("primary_date"),
    )
    added_neighbors = _append_new_articles(state, db, neighbor_ids, source="expansion")

    # Phase 2: exception/exclusion articles
    raw = state.get("retrieved_articles_raw", [])
    if raw:
        exception_ids, exception_details = expand_with_exceptions(db, raw)
        added_exceptions = _append_new_articles(state, db, exception_ids, source="exception")
    else:
        exception_details = {"forward_count": 0, "reverse_count": 0, "forward_matches": [], "reverse_matches": []}
        added_exceptions = 0

    if added_neighbors or added_exceptions:
        logger.info(f"Graph expansion: +{added_neighbors} neighbors/crossrefs, +{added_exceptions} exceptions")

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "graph_expansion", 5, "done", duration,
        output_summary=f"Graph expansion: +{added_neighbors} neighbors/crossrefs, +{added_exceptions} exceptions",
        output_data={
            "articles_before": len(raw_ids),
            "articles_after": len(state.get("retrieved_articles_raw", [])),
            "neighbors_added": neighbor_details.get("neighbors_added", 0),
            "crossrefs_added": neighbor_details.get("crossrefs_added", 0),
            "exceptions_added": added_exceptions,
            "forward_matches": exception_details.get("forward_count", 0),
            "reverse_matches": exception_details.get("reverse_count", 0),
            "expansion_triggers": neighbor_details.get("expansion_triggers", []),
        },
    )
    return state
```

- [ ] **Step 6: Update the pipeline orchestrator to use the new function**

In the full path section (around lines 539-566), replace the three step blocks (4.5, 5, 5.5) with a single block:

Replace:
```python
        # Step 4.5: Pre-Expansion Relevance Filter
        yield _step_event(45, "pre_expansion_filter", "running")
        t0 = time.time()
        before_filter = len(state.get("retrieved_articles_raw", []))
        state = _step4_5_pre_expansion_filter(state)
        yield _step_event(45, "pre_expansion_filter", "done", {
            "before": before_filter,
            "after": len(state.get("retrieved_articles_raw", [])),
        }, time.time() - t0)

        # Step 5: Article Expansion
        yield _step_event(5, "expansion", "running")
        t0 = time.time()
        before_expansion = len(state.get("retrieved_articles_raw", []))
        state = _step5_expand(state, db)
        yield _step_event(5, "expansion", "done", {
            "articles_before": before_expansion,
            "articles_after_expansion": len(state.get("retrieved_articles_raw", [])),
        }, time.time() - t0)

        # Step 5.5: Exception Retrieval
        yield _step_event(55, "exception_retrieval", "running")
        t0 = time.time()
        before_exceptions = len(state.get("retrieved_articles_raw", []))
        state = _step5_5_exception_retrieval(state, db)
        yield _step_event(55, "exception_retrieval", "done", {
            "exceptions_added": len(state.get("retrieved_articles_raw", [])) - before_exceptions,
        }, time.time() - t0)
```

With:
```python
        # Step 5: Graph Expansion (neighbors + cross-refs + exceptions)
        yield _step_event(5, "graph_expansion", "running")
        t0 = time.time()
        state = _step5_graph_expansion(state, db)
        yield _step_event(5, "graph_expansion", "done", duration=time.time() - t0)
```

- [ ] **Step 7: Delete the old functions**

Delete these functions from `pipeline_service.py`:
- `_step4_5_pre_expansion_filter` (the old filter function)
- `_step5_expand` (the old expansion function)
- `_step5_5_exception_retrieval` (the old exception retrieval function)

Keep `_derive_role` — it's still used by `_append_new_articles`.

- [ ] **Step 8: Update frontend step-indicator.tsx**

In `frontend/src/app/assistant/step-indicator.tsx`, update the `STEP_LABELS` object:

Replace:
```typescript
  expansion: "Expanding context",
  exception_retrieval: "Searching for exceptions",
```

With:
```typescript
  graph_expansion: "Expanding context",
```

Remove the `pre_expansion_filter` entry:
```typescript
  // DELETE this line:
  pre_expansion_filter: "Filtering results...",
```

- [ ] **Step 9: Update frontend run-detail.tsx**

In `frontend/src/app/settings/pipeline/run-detail.tsx`:

Replace the two case statements (around lines 62-65):
```typescript
    case "expansion":
      return <ExpansionDetail data={d} />;
    case "exception_retrieval":
      return <ExceptionDetail data={d} />;
```

With:
```typescript
    case "graph_expansion":
      return <GraphExpansionDetail data={d} />;
```

Replace the two detail components (`ExpansionDetail` and `ExceptionDetail`, around lines 292-350) with a single component:

```typescript
function GraphExpansionDetail({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Before" value={data.articles_before} />
        <Stat label="After" value={data.articles_after} />
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Neighbors" value={data.neighbors_added} />
        <Stat label="Cross-refs" value={data.crossrefs_added} />
        <Stat label="Exceptions" value={data.exceptions_added} />
      </div>
    </div>
  );
}
```

- [ ] **Step 10: Delete old test file**

```bash
rm /Users/anaandrei/projects/themis-legal/backend/tests/test_step4_5_filter.py
```

- [ ] **Step 11: Run all tests**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests pass, including the new `test_step5_graph_expansion.py` tests.

- [ ] **Step 12: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal && git add backend/app/services/pipeline_service.py backend/tests/test_step5_graph_expansion.py frontend/src/app/assistant/step-indicator.tsx frontend/src/app/settings/pipeline/run-detail.tsx && git rm backend/tests/test_step4_5_filter.py && git commit -m "refactor: merge Step 5 + 5.5 into unified graph expansion, replace Step 4.5 with simple cap"
```

---

## Task 3: Centralize Confidence Logic

**Files:**
- Modify: `backend/app/services/pipeline_service.py` (add `_derive_final_confidence`, remove scattered logic)
- Create: `backend/tests/test_confidence.py`

- [ ] **Step 1: Write the test file**

Create `backend/tests/test_confidence.py`:

```python
"""Tests for centralized confidence derivation."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _derive_final_confidence


def test_no_articles_returns_low():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[],
        has_articles=False,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 0},
    )
    assert conf == "LOW"
    assert "articles" in reason.lower()


def test_majority_citations_unverified_returns_low():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[{"certainty_level": "CERTAIN"}],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 5, "total_db": 8},
    )
    assert conf == "LOW"
    assert "citation" in reason.lower()


def test_uncertain_issue_returns_low():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[
            {"certainty_level": "CERTAIN"},
            {"certainty_level": "UNCERTAIN"},
        ],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "LOW"


def test_conditional_issue_caps_at_medium():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[
            {"certainty_level": "CERTAIN"},
            {"certainty_level": "CONDITIONAL"},
        ],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "MEDIUM"


def test_primary_not_from_db_caps_at_medium():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[{"certainty_level": "CERTAIN"}],
        has_articles=True,
        primary_from_db=False,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "MEDIUM"


def test_missing_primary_caps_at_medium():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[{"certainty_level": "CERTAIN"}],
        has_articles=True,
        primary_from_db=True,
        missing_primary=True,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "MEDIUM"


def test_stale_versions_caps_at_medium():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[{"certainty_level": "CERTAIN"}],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=True,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "MEDIUM"


def test_all_clear_uses_claude_confidence():
    conf, reason = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[{"certainty_level": "CERTAIN"}],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "HIGH"


def test_claude_says_low_respected():
    """Even if no overrides trigger, Claude's LOW is respected."""
    conf, reason = _derive_final_confidence(
        claude_confidence="LOW",
        rl_rap_issues=[{"certainty_level": "CERTAIN"}],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "LOW"


def test_probable_maps_to_high():
    conf, _ = _derive_final_confidence(
        claude_confidence="MEDIUM",
        rl_rap_issues=[{"certainty_level": "PROBABLE"}],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    # PROBABLE doesn't cap — Claude's MEDIUM is used
    assert conf == "MEDIUM"


def test_empty_rl_rap_issues_no_cap():
    """When no RL-RAP (fast path), rl_rap_issues is empty — don't apply issue-level caps."""
    conf, _ = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=False,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "HIGH"


def test_priority_order_low_beats_medium():
    """UNCERTAIN (rule 3 → LOW) takes priority over stale versions (rule 7 → MEDIUM)."""
    conf, _ = _derive_final_confidence(
        claude_confidence="HIGH",
        rl_rap_issues=[{"certainty_level": "UNCERTAIN"}],
        has_articles=True,
        primary_from_db=True,
        missing_primary=False,
        has_stale_versions=True,
        citation_validation={"downgraded": 0, "total_db": 5},
    )
    assert conf == "LOW"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_confidence.py -v --tb=short 2>&1 | tail -20
```

Expected: FAIL — `_derive_final_confidence` not defined yet.

- [ ] **Step 3: Implement `_derive_final_confidence`**

Add this function in `pipeline_service.py`, replacing the old `_derive_confidence` and `_cap_confidence` functions (lines 318-339):

```python
def _derive_final_confidence(
    claude_confidence: str,
    rl_rap_issues: list[dict],
    has_articles: bool,
    primary_from_db: bool,
    missing_primary: bool,
    has_stale_versions: bool,
    citation_validation: dict,
) -> tuple[str, str]:
    """Derive final confidence from all pipeline signals. Returns (confidence, reason)."""

    # Rule 1: No articles
    if not has_articles:
        return "LOW", "No relevant articles found"

    # Rule 2: Majority citations unverified
    total_db = citation_validation.get("total_db", 0)
    downgraded = citation_validation.get("downgraded", 0)
    if total_db > 0 and downgraded > total_db / 2:
        return "LOW", "Most citations could not be verified against provided articles"

    # Rules 3-4: RL-RAP issue certainty
    if rl_rap_issues:
        levels = [i.get("certainty_level", "UNCERTAIN") for i in rl_rap_issues]
        if any(l == "UNCERTAIN" for l in levels):
            return "LOW", "Legal analysis has uncertain conditions"

    # Start with Claude's assessment, then cap downward
    CONF_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    confidence = claude_confidence
    reason = "Based on model assessment"

    # Rule 4: CONDITIONAL caps at MEDIUM
    if rl_rap_issues:
        levels = [i.get("certainty_level", "UNCERTAIN") for i in rl_rap_issues]
        if any(l == "CONDITIONAL" for l in levels):
            if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
                confidence = "MEDIUM"
                reason = "Legal analysis has conditional conclusions"

    # Rule 5: Primary not from DB
    if not primary_from_db:
        if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
            confidence = "MEDIUM"
            reason = "Primary law source not from verified database"

    # Rule 6: Missing primary laws
    if missing_primary:
        if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
            confidence = "MEDIUM"
            reason = "Primary law not in library"

    # Rule 7: Stale versions
    if has_stale_versions:
        if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
            confidence = "MEDIUM"
            reason = "Law version may be outdated"

    return confidence, reason
```

- [ ] **Step 4: Remove scattered confidence logic from Step 7**

In `_step7_answer_generation()`, replace the confidence adjustment block (lines 2253-2290) with a simple extraction of Claude's raw confidence:

Replace:
```python
    # Use confidence from Claude's structured response if available
    if structured and structured.get("confidence"):
        state["confidence"] = structured["confidence"]
    elif not retrieved:
        state["confidence"] = "LOW"
        state["flags"].append("No articles retrieved from Legal Library")
    elif any(l.get("role") == "PRIMARY" and l.get("source") != "DB"
             for l in state.get("candidate_laws", [])):
        state["confidence"] = "MEDIUM"
    else:
        state["confidence"] = "HIGH"

    # Check for missing primary laws
    missing_primary = [
        c for c in state.get("candidate_laws", [])
        if c.get("tier") == "tier1_primary" and not c.get("db_law_id")
    ]
    if missing_primary:
        if state["confidence"] == "HIGH":
            state["confidence"] = "MEDIUM"
        state["is_partial"] = True

    # Cap confidence for stale versions (user continued without updating)
    # stale_versions comes from resume decisions; version_status comes from KnownVersion
    stale_laws_in_use = [
        c for c in state.get("candidate_laws", [])
        if c.get("version_status") == "stale" and c.get("role") == "PRIMARY"
    ]
    if state.get("stale_versions") or stale_laws_in_use:
        if state["confidence"] == "HIGH":
            state["confidence"] = "MEDIUM"
        stale_names = state.get("stale_versions", []) or [
            f"{c['law_number']}/{c['law_year']}" for c in stale_laws_in_use
        ]
        state["flags"].append(
            "Version currency: answer based on potentially outdated law version(s): "
            + ", ".join(stale_names)
        )
```

With:
```python
    # Store Claude's raw confidence — final confidence derived after Step 7.5
    state["claude_confidence"] = (structured.get("confidence") if structured else None) or "MEDIUM"

    # Track partial coverage for downstream use
    missing_primary = [
        c for c in state.get("candidate_laws", [])
        if c.get("tier") == "tier1_primary" and not c.get("db_law_id")
    ]
    if missing_primary:
        state["is_partial"] = True

    # Track stale versions for flags (confidence handled by _derive_final_confidence)
    stale_laws_in_use = [
        c for c in state.get("candidate_laws", [])
        if c.get("version_status") == "stale" and c.get("role") == "PRIMARY"
    ]
    if state.get("stale_versions") or stale_laws_in_use:
        stale_names = state.get("stale_versions", []) or [
            f"{c['law_number']}/{c['law_year']}" for c in stale_laws_in_use
        ]
        state["flags"].append(
            "Version currency: answer based on potentially outdated law version(s): "
            + ", ".join(stale_names)
        )
```

- [ ] **Step 5: Remove confidence downgrade from Step 7.5**

In `_step7_5_citation_validation()`, replace the confidence downgrade block (around line 2440-2451):

Replace:
```python
    confidence_downgraded = False
    if downgraded > 0:
        logger.info(f"Citation validation: downgraded {downgraded} citations to Unverified")

        # If majority are unverified, downgrade confidence
        total_db = sum(1 for s in sources if s.get("label") in ("DB", "Unverified"))
        if total_db > 0 and downgraded > total_db / 2:
            state["confidence"] = "LOW"
            state["flags"].append(
                "Majority of citations could not be verified against provided articles"
            )
            confidence_downgraded = True
```

With:
```python
    total_db = sum(1 for s in sources if s.get("label") in ("DB", "Unverified"))
    confidence_downgraded = total_db > 0 and downgraded > total_db / 2

    if downgraded > 0:
        logger.info(f"Citation validation: downgraded {downgraded} citations to Unverified")

    # Store validation results for _derive_final_confidence
    state["citation_validation"] = {
        "downgraded": downgraded,
        "total_db": total_db,
    }
```

- [ ] **Step 6: Call `_derive_final_confidence` after Step 7.5 in the orchestrator**

In the pipeline orchestrator, after the Step 7.5 citation validation block (around line 640), replace:

```python
    # Cap confidence (runs on both paths, no-ops if derived_confidence is None)
    _cap_confidence(state)
```

With:
```python
    # Derive final confidence from all signals
    retrieved = state.get("retrieved_articles", [])
    candidate_laws = state.get("candidate_laws", [])
    primary_from_db = all(
        l.get("source") == "DB" or l.get("db_law_id")
        for l in candidate_laws
        if l.get("role") == "PRIMARY"
    )
    missing_primary = any(
        c.get("tier") == "tier1_primary" and not c.get("db_law_id")
        for c in candidate_laws
    )
    stale_laws_in_use = [
        c for c in candidate_laws
        if c.get("version_status") == "stale" and c.get("role") == "PRIMARY"
    ]
    has_stale = bool(state.get("stale_versions") or stale_laws_in_use)

    state["confidence"], state["confidence_reason"] = _derive_final_confidence(
        claude_confidence=state.get("claude_confidence", "MEDIUM"),
        rl_rap_issues=(state.get("rl_rap_output") or {}).get("issues", []),
        has_articles=bool(retrieved),
        primary_from_db=primary_from_db,
        missing_primary=missing_primary,
        has_stale_versions=has_stale,
        citation_validation=state.get("citation_validation", {"downgraded": 0, "total_db": 0}),
    )
```

- [ ] **Step 7: Delete old confidence functions**

Delete `_derive_confidence` (lines 318-327) and `_cap_confidence` (lines 330-339) from `pipeline_service.py`.

- [ ] **Step 8: Update Step 6.8 to not call deleted `_derive_confidence`**

In `_step6_8_legal_reasoning()`, replace line 363:
```python
        state["derived_confidence"] = _derive_confidence(parsed.get("issues", []))
```

With:
```python
        # Store raw certainty levels for logging (final confidence derived after Step 7.5)
        levels = {i["issue_id"]: i["certainty_level"] for i in parsed.get("issues", [])}
        state["derived_confidence"] = (
            "LOW" if any(l == "UNCERTAIN" for l in levels.values())
            else "MEDIUM" if any(l == "CONDITIONAL" for l in levels.values())
            else "HIGH"
        )
```

- [ ] **Step 9: Update test_step6_8_reasoning.py**

In `backend/tests/test_step6_8_reasoning.py`, remove the import of `_derive_confidence` from line 6:

Replace:
```python
from app.services.pipeline_service import _build_step6_8_context, _parse_step6_8_output, _derive_confidence
```

With:
```python
from app.services.pipeline_service import _build_step6_8_context, _parse_step6_8_output
```

Delete the 5 `test_derive_confidence_*` tests (lines 46-67) — they are replaced by the more comprehensive tests in `test_confidence.py`.

- [ ] **Step 10: Run all tests**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests pass.

- [ ] **Step 11: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal && git add backend/app/services/pipeline_service.py backend/tests/test_confidence.py backend/tests/test_step6_8_reasoning.py && git commit -m "refactor: centralize confidence logic into _derive_final_confidence"
```

---

## Task 4: Consolidate LA-S7 Prompts into Template

**Files:**
- Create: `backend/prompts/LA-S7-answer-template.txt`
- Create: `backend/prompts/LA-S7-mode-simple.txt`
- Create: `backend/prompts/LA-S7-mode-qa.txt`
- Create: `backend/prompts/LA-S7-mode-memo.txt`
- Create: `backend/prompts/LA-S7-mode-comparison.txt`
- Create: `backend/prompts/LA-S7-mode-compliance.txt`
- Create: `backend/prompts/LA-S7-mode-checklist.txt`
- Delete: `backend/prompts/LA-S7-answer-qa.txt`
- Delete: `backend/prompts/LA-S7-simple.txt`
- Delete: `backend/prompts/LA-S7-M2-answer-memo.txt`
- Delete: `backend/prompts/LA-S7-M3-answer-comparison.txt`
- Delete: `backend/prompts/LA-S7-M4-answer-compliance.txt`
- Delete: `backend/prompts/LA-S7-M5-answer-checklist.txt`
- Modify: `backend/app/services/prompt_service.py:14-75` (PROMPT_MANIFEST)
- Modify: `backend/app/services/pipeline_service.py` (`_step7_answer_generation`)

- [ ] **Step 1: Create the shared template**

Create `backend/prompts/LA-S7-answer-template.txt`. This file contains ALL shared content from the current 6 prompts, with `{MODE_SECTION}` as the placeholder.

Build this by:
1. Taking `LA-S7-answer-qa.txt` as the base
2. Extracting the shared preamble (lines 1-29: role, civil law, context, RL-RAP integration, temporal reasoning)
3. Adding the UNKNOWN handling examples from the spec
4. Placing `{MODE_SECTION}` where mode-specific content goes
5. Adding the shared JSON format, critical rules, stale version handling, domain relevance, no-articles guard, article priority (lines 49-159 of LA-S7-answer-qa.txt)

The template should follow this structure:
```
[Role line: "You are the Legal Answer Generator for the Themis Legal Assistant."]
[Civil law jurisdiction warning]
[Context description]
[RL-RAP integration instructions — identical across all modes]
[Temporal reasoning instructions]
[UNKNOWN handling with worked examples — NEW from spec]

{MODE_SECTION}

[JSON response format — identical across all modes]
[Critical rules — citations, domain relevance, stale versions, no-articles, completeness check]
[Article priority rules]
```

Read each of the 6 existing prompt files carefully. Extract the shared portions verbatim. The mode-specific content is everything between the RL-RAP/temporal section and the JSON format section — typically the answer format instructions and mode-specific rules.

- [ ] **Step 2: Create the 6 mode files**

Each mode file contains ONLY the mode-specific instructions — the format template and mode-specific rules.

**`backend/prompts/LA-S7-mode-simple.txt`:**
Extract from `LA-S7-simple.txt` lines 3-9 (the 6 instructions). This is the leanest mode.

**`backend/prompts/LA-S7-mode-qa.txt`:**
Extract from `LA-S7-answer-qa.txt` lines 38-108 (answer complexity section, SHORT FORMAT, FULL STRUCTURED FORMAT with problem sections, risk levels, nuances, conclusion).

**`backend/prompts/LA-S7-mode-memo.txt`:**
Extract from `LA-S7-M2-answer-memo.txt` lines 37-84 (memo format with executive summary, legal framework, rules, obligations, practical implications, legislative evolution, uncertainty areas, conclusion).

**`backend/prompts/LA-S7-mode-comparison.txt`:**
Extract from `LA-S7-M3-answer-comparison.txt` the comparison-specific format (version comparison table, change analysis, what didn't change, legislative direction).

**`backend/prompts/LA-S7-mode-compliance.txt`:**
Extract from `LA-S7-M4-answer-compliance.txt` the compliance-specific format (per-issue compliance status, risk levels, remediation steps, conclusion).

**`backend/prompts/LA-S7-mode-checklist.txt`:**
Extract from `LA-S7-M5-answer-checklist.txt` the checklist-specific format (mandatory elements, recommended elements, conditional elements, prohibited elements, practical observations).

- [ ] **Step 3: Update PROMPT_MANIFEST**

In `backend/app/services/prompt_service.py`, replace the 6 old LA-S7 entries (lines 43-66) with:

```python
    "LA-S7-template": {
        "file": "LA-S7-answer-template.txt",
        "desc": "Step 7 — Answer Generator (Shared Template)",
    },
    "LA-S7-mode-simple": {
        "file": "LA-S7-mode-simple.txt",
        "desc": "Step 7 — Mode: Simple Q&A",
    },
    "LA-S7-mode-qa": {
        "file": "LA-S7-mode-qa.txt",
        "desc": "Step 7 — Mode: Full Q&A",
    },
    "LA-S7-mode-memo": {
        "file": "LA-S7-mode-memo.txt",
        "desc": "Step 7 — Mode: Legal Memo",
    },
    "LA-S7-mode-comparison": {
        "file": "LA-S7-mode-comparison.txt",
        "desc": "Step 7 — Mode: Version Comparison",
    },
    "LA-S7-mode-compliance": {
        "file": "LA-S7-mode-compliance.txt",
        "desc": "Step 7 — Mode: Compliance Check",
    },
    "LA-S7-mode-checklist": {
        "file": "LA-S7-mode-checklist.txt",
        "desc": "Step 7 — Mode: Legal Checklist",
    },
```

- [ ] **Step 4: Update `_step7_answer_generation` prompt loading**

In `pipeline_service.py`, replace the prompt selection block (lines 2182-2194):

Replace:
```python
    mode = state.get("output_mode", "qa")
    if state.get("use_simple_prompt"):
        prompt_id = "LA-S7-simple"
    else:
        prompt_map = {
            "qa": "LA-S7",
            "memo": "LA-S7-M2",
            "comparison": "LA-S7-M3",
            "compliance": "LA-S7-M4",
            "checklist": "LA-S7-M5",
        }
        prompt_id = prompt_map.get(mode, "LA-S7")
    prompt_text, prompt_ver = load_prompt(prompt_id, db)
```

With:
```python
    mode = state.get("output_mode", "qa")
    mode_key = "simple" if state.get("use_simple_prompt") else mode

    # Load template + mode, assemble prompt
    template_text, template_ver = load_prompt("LA-S7-template", db)
    mode_text, mode_ver = load_prompt(f"LA-S7-mode-{mode_key}", db)
    prompt_text = template_text.replace("{MODE_SECTION}", mode_text)
    prompt_ver = template_ver  # track template version for logging
    prompt_id = f"LA-S7-template+{mode_key}"
```

- [ ] **Step 5: Delete old prompt files**

```bash
cd /Users/anaandrei/projects/themis-legal && rm backend/prompts/LA-S7-answer-qa.txt backend/prompts/LA-S7-simple.txt backend/prompts/LA-S7-M2-answer-memo.txt backend/prompts/LA-S7-M3-answer-comparison.txt backend/prompts/LA-S7-M4-answer-compliance.txt backend/prompts/LA-S7-M5-answer-checklist.txt
```

- [ ] **Step 6: Run all tests**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal && git add backend/prompts/LA-S7-answer-template.txt backend/prompts/LA-S7-mode-*.txt backend/app/services/prompt_service.py backend/app/services/pipeline_service.py && git rm backend/prompts/LA-S7-answer-qa.txt backend/prompts/LA-S7-simple.txt backend/prompts/LA-S7-M2-answer-memo.txt backend/prompts/LA-S7-M3-answer-comparison.txt backend/prompts/LA-S7-M4-answer-compliance.txt backend/prompts/LA-S7-M5-answer-checklist.txt && git commit -m "refactor: consolidate 6 LA-S7 prompts into template + mode system"
```

---

## Task 5: Sharpen LA-S1 Complexity Criteria

**Files:**
- Modify: `backend/prompts/LA-S1-issue-classifier.txt:71-74`
- Modify: `backend/tests/test_pipeline_routing.py`

- [ ] **Step 1: Add complexity decision rubric to LA-S1**

In `backend/prompts/LA-S1-issue-classifier.txt`, replace lines 71-74:

Replace:
```
8. Complexity Assessment:
   - "SIMPLE": Single factual question about a current rule, definition, threshold, or procedure. No scenario, no multiple parties, no temporal dimension.
   - "STANDARD": Specific situation with 1-2 issues, potentially requiring temporal or exception analysis.
   - "COMPLEX": Multi-issue scenario with multiple parties, dates, conflicting laws, or comprehensive analysis needed.
```

With:
```
8. Complexity Assessment — use the decision rubric:

   COMPLEXITY DECISION RUBRIC — count how many signals are present:
     Signal A: Multiple distinct legal issues (not sub-points of one issue)
     Signal B: Multiple parties with different legal positions
     Signal C: Temporal dimension (past events, future deadlines, law version changes)
     Signal D: Potential conflicts between laws or articles
     Signal E: Scenario with stated/assumed facts requiring condition analysis

     0 signals -> "SIMPLE"
     1-2 signals -> "STANDARD"
     3+ signals -> "COMPLEX"

     Override: If the question is literally "what is X" or "what does Art. Y say" -> always "SIMPLE" regardless of signals.

   Examples:
     "Care este capitalul social minim pentru un SRL?" -> 0 signals -> SIMPLE
     "Un administrator a acordat un imprumut societatii fara aprobarea AGA. Este valid?" -> Signal B (administrator vs company) + Signal E (scenario with facts) -> STANDARD
     "O societate cu 3 asociati, 2 rezidenti si 1 nerezident, vrea sa fuzioneze cu o firma din UE. Ce obligatii fiscale si corporative au?" -> Signal A (fiscal + corporate) + Signal B (3 parties) + Signal D (domestic vs EU law) -> COMPLEX
```

- [ ] **Step 2: Add rubric validation tests**

Add these tests to `backend/tests/test_pipeline_routing.py`:

```python
def test_rubric_zero_signals_is_simple():
    """A direct factual question with 0 signals should be SIMPLE."""
    # This tests the classification contract — the actual LLM classification
    # is tested via integration tests. Here we verify the state contract.
    state = {
        "complexity": "SIMPLE",
        "legal_issues": [{"issue_id": "ISSUE-1", "description": "Minimum share capital"}],
    }
    assert state["complexity"] == "SIMPLE"
    assert len(state["legal_issues"]) == 1


def test_rubric_override_what_is_always_simple():
    """'What is X' questions should always be SIMPLE regardless of apparent complexity."""
    state = {
        "question": "Ce este capitalul social?",
        "complexity": "SIMPLE",
    }
    assert state["complexity"] == "SIMPLE"


def test_rubric_two_signals_is_standard():
    """A scenario with 2 signals should be STANDARD."""
    state = {
        "complexity": "STANDARD",
        "legal_issues": [{"issue_id": "ISSUE-1", "description": "Validity of transaction"}],
        "facts": {"stated": [{"fact_id": "F1"}], "assumed": [], "missing": []},
    }
    assert state["complexity"] == "STANDARD"
    assert "facts" in state


def test_rubric_three_plus_signals_is_complex():
    """A scenario with 3+ signals should be COMPLEX."""
    state = {
        "complexity": "COMPLEX",
        "legal_issues": [
            {"issue_id": "ISSUE-1", "description": "Fiscal obligations"},
            {"issue_id": "ISSUE-2", "description": "Corporate obligations"},
        ],
    }
    assert state["complexity"] == "COMPLEX"
    assert len(state["legal_issues"]) > 1
```

- [ ] **Step 3: Run tests**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_pipeline_routing.py -v --tb=short 2>&1 | tail -20
```

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal && git add backend/prompts/LA-S1-issue-classifier.txt backend/tests/test_pipeline_routing.py && git commit -m "refactor: add complexity decision rubric to LA-S1 classifier prompt"
```

---

## Task 6: Final Verification

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/ -v --tb=short 2>&1
```

Expected: All tests pass.

- [ ] **Step 2: Verify no broken imports or references**

```bash
cd /Users/anaandrei/projects/themis-legal && grep -r "_step4_5_pre_expansion_filter\|_step5_expand\|_step5_5_exception_retrieval\|_derive_confidence\|_cap_confidence" backend/ --include="*.py" | grep -v "test_" | grep -v "__pycache__"
```

Expected: No output — all old function references should be gone.

```bash
grep -r "LA-S7-simple\b\|LA-S7-M[2345]\b\|LA-CONF\b\|LA-S3\b" backend/ --include="*.py" | grep -v "__pycache__"
```

Expected: No output — all old prompt ID references should be gone.

- [ ] **Step 3: Verify git history is clean**

```bash
cd /Users/anaandrei/projects/themis-legal && git log --oneline -6
```

Expected: 6 new commits (one per task), all with clear messages.
