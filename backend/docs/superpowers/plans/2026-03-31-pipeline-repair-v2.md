# Pipeline Repair v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 10 pipeline problems (P1–P10) to produce legally accurate, natural-language answers for any question domain — while reducing API cost by ~43% and response time by ~44%.

**Architecture:** Fixes span 4 batches across prompt files, `pipeline_service.py`, `chroma_service.py`, and `leropa_service.py`. Batch 1 fixes data/indexing issues. Batch 2 adds a retrieval safety net. Batch 3 eliminates redundant LLM calls. Batch 4 rewrites the answer presentation layer.

**Tech Stack:** Python 3.11, SQLAlchemy, ChromaDB, SQLite FTS5, Claude API

---

## File Map

| File | Responsibility | Tasks |
|------|---------------|-------|
| `app/services/chroma_service.py` | ChromaDB indexing + verification | 1 |
| `app/services/leropa_service.py` | Law import flow (ChromaDB validation) | 1 |
| `prompts/LA-S1-issue-classifier.txt` | Issue classification prompt | 2 |
| `app/services/pipeline_service.py` | Pipeline orchestration (~3000 lines) | 3, 4, 5, 6, 7, 8 |
| `prompts/LA-S7-answer-template.txt` | Answer generation prompt | 7 |
| `tests/test_chroma_validation.py` | New: ChromaDB validation tests | 1 |
| `tests/test_article_coverage.py` | New: Coverage validation tests | 4 |
| `tests/test_step13_restructured.py` | New: Step 13 restructuring tests | 5 |
| `tests/test_context_translation.py` | New: Context builder translation tests | 7 |
| `tests/test_tiered_context.py` | New: Tiered article context tests | 8 |

---

## Batch 1 — Data & Indexing Fixes (parallel)

### Task 1: P2+P8 — ChromaDB Re-index + Import Validation

**Files:**
- Modify: `app/services/chroma_service.py:134-170`
- Modify: `app/services/leropa_service.py:736-745,847-853,998-1008`
- Create: `tests/test_chroma_validation.py`
- Create: `scripts/reindex_missing.py`

- [ ] **Step 1: Write test for `verify_index_completeness`**

```python
# tests/test_chroma_validation.py
"""Tests for ChromaDB index verification."""
import pytest
from unittest.mock import MagicMock, patch


def test_verify_detects_missing_versions():
    """verify_index_completeness returns mismatches when ChromaDB is missing articles."""
    from app.services.chroma_service import verify_index_completeness

    mock_db = MagicMock()
    # Simulate one current version with 100 DB articles
    mock_version = MagicMock()
    mock_version.id = 54
    mock_version.law_id = 3
    mock_db.query.return_value.join.return_value.filter.return_value.group_by.return_value.all.return_value = [
        (mock_version, 100)
    ]

    with patch("app.services.chroma_service.get_collection") as mock_col:
        mock_col.return_value.get.return_value = {"ids": []}  # 0 in ChromaDB
        result = verify_index_completeness(mock_db)

    assert len(result) == 1
    assert result[0]["law_version_id"] == 54
    assert result[0]["db_count"] == 100
    assert result[0]["chroma_count"] == 0
    assert result[0]["status"] == "MISSING"


def test_verify_no_mismatch_when_indexed():
    """verify_index_completeness returns empty list when all versions are indexed."""
    from app.services.chroma_service import verify_index_completeness

    mock_db = MagicMock()
    mock_version = MagicMock()
    mock_version.id = 54
    mock_version.law_id = 3
    mock_db.query.return_value.join.return_value.filter.return_value.group_by.return_value.all.return_value = [
        (mock_version, 100)
    ]

    with patch("app.services.chroma_service.get_collection") as mock_col:
        mock_col.return_value.get.return_value = {"ids": [f"art-{i}" for i in range(100)]}
        result = verify_index_completeness(mock_db)

    assert len(result) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_chroma_validation.py -v`
Expected: FAIL — `verify_index_completeness` does not exist yet.

- [ ] **Step 3: Implement `verify_index_completeness` in `chroma_service.py`**

Add after the `remove_law_articles` function (after line 170):

```python
def verify_index_completeness(db: Session) -> list[dict]:
    """Compare current versions' DB article counts against ChromaDB counts.
    Returns list of mismatches for logging/alerting."""
    from sqlalchemy import func

    collection = get_collection()
    mismatches = []

    current_versions = (
        db.query(LawVersion, func.count(Article.id))
        .join(Article, Article.law_version_id == LawVersion.id)
        .filter(LawVersion.is_current == True)
        .group_by(LawVersion.id)
        .all()
    )

    for version, db_count in current_versions:
        try:
            chroma_result = collection.get(where={"law_version_id": version.id})
            chroma_count = len(chroma_result["ids"])
        except Exception:
            chroma_count = 0

        if chroma_count == 0 and db_count > 0:
            mismatches.append({
                "law_version_id": version.id,
                "law_id": version.law_id,
                "db_count": db_count,
                "chroma_count": 0,
                "status": "MISSING",
            })

    return mismatches
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_chroma_validation.py -v`
Expected: PASS

- [ ] **Step 5: Add import-time validation to `leropa_service.py`**

In `leropa_service.py`, replace the three ChromaDB indexing blocks with validated versions.

**Block 1 (lines 736-745)** — replace:
```python
    # Index imported versions into ChromaDB
    try:
        from app.services.chroma_service import index_law_version as chroma_index
        all_db_versions = (
            db.query(LawVersion).filter(LawVersion.law_id == law.id).all()
        )
        for v in all_db_versions:
            chroma_index(db, law.id, v.id)
    except Exception as e:
        logger.warning(f"ChromaDB indexing failed (non-fatal): {e}")
```

With:
```python
    # Index imported versions into ChromaDB (with validation)
    try:
        from app.services.chroma_service import index_law_version as chroma_index
        all_db_versions = (
            db.query(LawVersion).filter(LawVersion.law_id == law.id).all()
        )
        for v in all_db_versions:
            indexed = chroma_index(db, law.id, v.id)
            expected = db.query(Article).filter(Article.law_version_id == v.id).count()
            if indexed < expected:
                logger.error(
                    f"ChromaDB indexing incomplete for {law.law_number}/{law.law_year} "
                    f"v{v.id}: indexed {indexed}/{expected} articles — retrying"
                )
                indexed = chroma_index(db, law.id, v.id)
                if indexed < expected:
                    logger.error(f"ChromaDB retry also incomplete: {indexed}/{expected}")
    except Exception as e:
        logger.warning(f"ChromaDB indexing failed (non-fatal): {e}")
```

**Block 2 (lines 847-853)** — replace:
```python
        try:
            from app.services.chroma_service import index_law_version as chroma_index
            for v in all_versions:
                chroma_index(db, law.id, v.id)
        except Exception as e:
            logger.warning(f"Background ChromaDB indexing failed: {e}")
```

With:
```python
        try:
            from app.services.chroma_service import index_law_version as chroma_index
            for v in all_versions:
                indexed = chroma_index(db, law.id, v.id)
                expected = db.query(Article).filter(Article.law_version_id == v.id).count()
                if indexed < expected:
                    logger.error(
                        f"Background ChromaDB incomplete for v{v.id}: {indexed}/{expected} — retrying"
                    )
                    chroma_index(db, law.id, v.id)
        except Exception as e:
            logger.warning(f"Background ChromaDB indexing failed: {e}")
```

**Block 3 (lines 998-1008)** — replace:
```python
    try:
        from app.services.chroma_service import index_law_version as chroma_index

        db_versions = (
            db.query(LawVersion).filter(LawVersion.law_id == law.id).all()
        )
        for v in db_versions:
            chroma_index(db, law.id, v.id)
    except Exception as e:
        logger.warning(f"ChromaDB indexing failed (non-fatal): {e}")
```

With:
```python
    try:
        from app.services.chroma_service import index_law_version as chroma_index

        db_versions = (
            db.query(LawVersion).filter(LawVersion.law_id == law.id).all()
        )
        for v in db_versions:
            indexed = chroma_index(db, law.id, v.id)
            expected = db.query(Article).filter(Article.law_version_id == v.id).count()
            if indexed < expected:
                logger.error(
                    f"EU ChromaDB incomplete for v{v.id}: {indexed}/{expected} — retrying"
                )
                chroma_index(db, law.id, v.id)
    except Exception as e:
        logger.warning(f"ChromaDB indexing failed (non-fatal): {e}")
```

- [ ] **Step 6: Create re-index script for missing versions**

```python
# scripts/reindex_missing.py
"""One-time script to re-index law versions missing from ChromaDB."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal
from app.services.chroma_service import index_law_version, verify_index_completeness

db = SessionLocal()

print("Checking for missing ChromaDB indexes...")
mismatches = verify_index_completeness(db)

if not mismatches:
    print("All current versions are fully indexed.")
else:
    print(f"Found {len(mismatches)} versions missing from ChromaDB:")
    for m in mismatches:
        print(f"  law_id={m['law_id']}, version_id={m['law_version_id']}, "
              f"DB articles={m['db_count']}")

    print("\nRe-indexing...")
    for m in mismatches:
        count = index_law_version(db, m["law_id"], m["law_version_id"])
        print(f"  version {m['law_version_id']}: indexed {count} items")

    # Verify
    remaining = verify_index_completeness(db)
    if remaining:
        print(f"\nWARNING: {len(remaining)} versions still incomplete after re-index")
    else:
        print("\nAll versions now fully indexed.")

db.close()
```

- [ ] **Step 7: Run the re-index script**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && source .venv/bin/activate && python scripts/reindex_missing.py`
Expected: All 8 missing versions re-indexed successfully.

- [ ] **Step 8: Run all existing tests to verify no regression**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
git add app/services/chroma_service.py app/services/leropa_service.py \
       tests/test_chroma_validation.py scripts/reindex_missing.py
git commit -m "fix(P2+P8): add ChromaDB index validation and re-index missing versions"
```

---

### Task 2: P4 — LA-S1 Prompt Trim

**Files:**
- Modify: `prompts/LA-S1-issue-classifier.txt`

- [ ] **Step 1: Trim HYPOTHETICAL SCENARIO ANCHORING**

In `LA-S1-issue-classifier.txt`, replace lines 109-120 (the full hypothetical anchoring section with the worked example) with:

```
   HYPOTHETICAL SCENARIO ANCHORING (CRITICAL):
   When the question uses conditional language ("Dacă...", "în cazul în care...")
   or describes a scenario without specific past dates, anchor the first event
   to TODAY'S DATE and compute subsequent events relative to it.
   Past tense alone does NOT make a scenario historical — only explicit calendar
   dates or historical references do.
```

- [ ] **Step 2: Trim FACT-LEVEL DATE DECOMPOSITION**

Replace lines 221-231 (the fact-level decomposition section with long example) with:

```
FACT-LEVEL DATE DECOMPOSITION:
Use "fact_dates" when a single issue involves multiple facts with different
relevant dates (e.g., a transfer on one date and insolvency opening on another).
If all facts share the same date, leave fact_dates as an empty array [].
```

- [ ] **Step 3: Trim MITIOR LEX FLAG**

Replace lines 233-237 (the mitior lex section) with:

```
MITIOR LEX FLAG: For criminal issues referencing Codul Penal, set
"mitior_lex_relevant": true to flag potential applicability of a more favorable law.
```

- [ ] **Step 4: Add conflict of interest example in ISSUE SEPARATION**

After line 81 (the line ending `- Obligations of different actors...`), add:

```
   - Direct liability (breach of duty) vs Conflict of interest (violation of disclosure obligations)
```

After line 87 (the line `   - ISSUE-3: Criminal exposure if applicable...`), add:

```
   - ISSUE-4: Conflict of interest obligations (governing norm: disclosure/approval requirements)
```

- [ ] **Step 5: Commit**

```bash
git add prompts/LA-S1-issue-classifier.txt
git commit -m "fix(P4): trim LA-S1 prompt and add conflict of interest example"
```

---

### Task 3: P6 — Step 2 Display Update

**Files:**
- Modify: `app/services/pipeline_service.py:1830`

- [ ] **Step 1: Update output_summary**

In `pipeline_service.py`, change line 1830 from:

```python
        output_summary=f"primary_date={state.get('primary_date')}, date_type={state.get('date_type')}",
```

To:

```python
        output_summary=f"date_type={state['date_type']}, fact_mappings={len(fact_version_map)}, versions_needed={len(versions_needed)}",
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add app/services/pipeline_service.py
git commit -m "fix(P6): update Step 2 output_summary to show new data structures"
```

---

## Batch 2 — Retrieval Safety Net

### Task 4: P9 — Article Coverage Validation

**Files:**
- Modify: `app/services/pipeline_service.py:1020-1025`
- Create: `tests/test_article_coverage.py`

- [ ] **Step 1: Write test for coverage validation**

```python
# tests/test_article_coverage.py
"""Tests for post-retrieval article coverage validation."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch
from app.services.pipeline_service import _validate_article_coverage


def test_coverage_fills_missing_law():
    """When an issue has 0 articles from an applicable law, BM25 fallback fetches them."""
    state = {
        "question": "Test question about administrator liability",
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "applicable_laws": ["31/1990", "287/2009"],
            }
        ],
        "issue_articles": {
            "ISSUE-1": [
                {"article_id": 1, "law_number": "287", "law_year": "2009", "text": "..."},
            ]
        },
        "issue_versions": {
            "ISSUE-1:31/1990": {"law_version_id": 54},
            "ISSUE-1:287/2009": {"law_version_id": 55},
        },
        "retrieved_articles": [],
        "flags": [],
    }

    mock_bm25_result = [
        {"article_id": 100, "law_number": "31", "law_year": "1990",
         "article_number": "72", "text": "Art 72 text"},
        {"article_id": 101, "law_number": "31", "law_year": "1990",
         "article_number": "73", "text": "Art 73 text"},
    ]

    with patch("app.services.pipeline_service.search_bm25", return_value=mock_bm25_result) as mock_bm25:
        result = _validate_article_coverage(state, MagicMock())

    # Should have called BM25 for the missing law
    mock_bm25.assert_called_once()
    call_args = mock_bm25.call_args
    assert call_args[0][2] == [54]  # law_version_id for 31/1990

    # ISSUE-1 should now have 3 articles (1 original + 2 fetched)
    assert len(result["issue_articles"]["ISSUE-1"]) == 3

    # Fetched articles should be marked
    fetched = [a for a in result["issue_articles"]["ISSUE-1"] if a.get("_coverage_fix")]
    assert len(fetched) == 2

    # Should be added to retrieved_articles too
    assert len(result["retrieved_articles"]) == 2

    # Should have a flag
    assert any("31/1990" in f for f in result["flags"])


def test_coverage_skips_when_articles_exist():
    """When an issue already has articles from all laws, no BM25 fetch occurs."""
    state = {
        "question": "Test question",
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "applicable_laws": ["31/1990"],
            }
        ],
        "issue_articles": {
            "ISSUE-1": [
                {"article_id": 1, "law_number": "31", "law_year": "1990", "text": "..."},
            ]
        },
        "issue_versions": {
            "ISSUE-1:31/1990": {"law_version_id": 54},
        },
        "retrieved_articles": [],
        "flags": [],
    }

    with patch("app.services.pipeline_service.search_bm25") as mock_bm25:
        _validate_article_coverage(state, MagicMock())

    mock_bm25.assert_not_called()


def test_coverage_skips_when_no_version():
    """When issue_versions has no entry for a law, skip gracefully."""
    state = {
        "question": "Test question",
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "applicable_laws": ["999/2099"],
            }
        ],
        "issue_articles": {"ISSUE-1": []},
        "issue_versions": {},
        "retrieved_articles": [],
        "flags": [],
    }

    with patch("app.services.pipeline_service.search_bm25") as mock_bm25:
        _validate_article_coverage(state, MagicMock())

    mock_bm25.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_article_coverage.py -v`
Expected: FAIL — `_validate_article_coverage` does not exist.

- [ ] **Step 3: Implement `_validate_article_coverage` in `pipeline_service.py`**

Add the function before the `_step6_8_legal_reasoning` function (around line 490). Add the import at the top of the function:

```python
def _validate_article_coverage(state: dict, db: Session) -> dict:
    """Ensure each issue has articles from all its applicable laws.
    If a law has 0 articles for an issue, fetch directly from DB via BM25."""
    from app.services.bm25_service import search_bm25
    from collections import Counter

    issue_articles = state.get("issue_articles", {})
    issue_versions = state.get("issue_versions", {})

    for issue in state.get("legal_issues", []):
        iid = issue["issue_id"]
        arts = issue_articles.get(iid, [])

        law_counts = Counter(
            f"{a.get('law_number', '')}/{a.get('law_year', '')}" for a in arts
        )

        for law_key in issue.get("applicable_laws", []):
            if law_counts.get(law_key, 0) > 0:
                continue

            iv_key = f"{iid}:{law_key}"
            iv = issue_versions.get(iv_key, {})
            if not iv:
                continue

            version_id = iv["law_version_id"]
            fetched = search_bm25(db, state["question"], [version_id], limit=5)

            if fetched:
                for art in fetched:
                    art["_coverage_fix"] = True
                issue_articles.setdefault(iid, []).extend(fetched)
                state["flags"].append(
                    f"{iid}: {law_key} lipsea din rezultatele căutării — "
                    f"s-au adăugat {len(fetched)} articole direct din baza de date"
                )

    state["issue_articles"] = issue_articles

    for issue in state.get("legal_issues", []):
        iid = issue["issue_id"]
        for art in issue_articles.get(iid, []):
            if art.get("_coverage_fix"):
                state.setdefault("retrieved_articles", []).append(art)

    return state
```

- [ ] **Step 4: Call `_validate_article_coverage` after Step 11**

In `pipeline_service.py`, find the Step 12 invocation (around line 1025-1027):

```python
        # Step 12: Legal Reasoning (RL-RAP)
        yield _step_event(12, "legal_reasoning", "running")
        state = _step6_8_legal_reasoning(state, db)
```

Insert before it:

```python
        # Coverage validation: ensure each issue has articles from all applicable laws
        state = _validate_article_coverage(state, db)

```

- [ ] **Step 5: Run tests**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_article_coverage.py tests/ -v`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/services/pipeline_service.py tests/test_article_coverage.py
git commit -m "feat(P9): add post-retrieval article coverage validation"
```

---

## Batch 3 — Step 12/13 Restructuring

### Task 5: P7 — Eliminate Double Step 12

**Files:**
- Modify: `app/services/pipeline_service.py:1033-1099`
- Create: `tests/test_step13_restructured.py`

- [ ] **Step 1: Write test for Step 13 restructured behavior**

```python
# tests/test_step13_restructured.py
"""Tests for restructured Step 13: re-run only for governing norms."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_no_rerun_for_library_gap_only():
    """Step 13 should NOT re-run Step 12 when only LIBRARY_GAPs exist (no MISSING governing norm)."""
    # When rl_rap_output has issues with LIBRARY_GAP but governing_norm_status is PRESENT,
    # Step 13 should fetch articles and add to context but NOT re-run reasoning.
    rl_rap = {
        "issues": [{
            "issue_id": "ISSUE-1",
            "issue_label": "Test",
            "governing_norm_status": {"status": "PRESENT"},
            "operative_articles": [],
            "condition_table": [],
            "conclusion": "Test",
            "certainty_level": "CONDITIONAL",
            "uncertainty_sources": [
                {"type": "LIBRARY_GAP", "detail": "Art 117 missing", "resolvable_by": "ARTICLE_IMPORT"}
            ],
            "missing_facts": [],
            "missing_articles_needed": ["Legea 85/2014 art.117"],
        }]
    }
    # The key assertion: should_rerun must be False when governing_norm_status is PRESENT
    governing_norm_issues = []
    for issue in rl_rap["issues"]:
        gns = issue.get("governing_norm_status", {})
        if gns.get("status") == "MISSING":
            governing_norm_issues.append(issue["issue_id"])

    should_rerun = bool([]) and bool(governing_norm_issues)  # no governing_norm_fetched
    assert should_rerun is False


def test_rerun_for_missing_governing_norm():
    """Step 13 SHOULD re-run Step 12 when a governing norm was MISSING and is now found."""
    rl_rap = {
        "issues": [{
            "issue_id": "ISSUE-1",
            "issue_label": "Test",
            "governing_norm_status": {
                "status": "MISSING",
                "explanation": "Art 72 not provided",
            },
            "operative_articles": [],
            "condition_table": [],
            "conclusion": "Incomplete",
            "certainty_level": "UNCERTAIN",
            "uncertainty_sources": [],
            "missing_facts": [],
            "missing_articles_needed": [],
        }]
    }
    governing_norm_issues = []
    for issue in rl_rap["issues"]:
        gns = issue.get("governing_norm_status", {})
        if gns.get("status") == "MISSING":
            governing_norm_issues.append(issue["issue_id"])

    governing_norm_fetched = [{"article_number": "72", "law_number": "31", "law_year": "1990"}]
    should_rerun = bool(governing_norm_fetched) and bool(governing_norm_issues)
    assert should_rerun is True
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_step13_restructured.py -v`
Expected: PASS (these are logic-level tests, not integration).

- [ ] **Step 3: Restructure Step 13 in `pipeline_service.py`**

Replace the Step 13 block (lines 1033-1099) with:

```python
        # Conditional Retrieval Pass (flag-only, re-run only for governing norms)
        if state.get("rl_rap_output"):
            missing = _check_missing_articles(state["rl_rap_output"])
            governing_norm_issues = []
            governing_norm_fetched = []

            # Fetch governing norms for issues with MISSING status
            for issue in state["rl_rap_output"].get("issues", []):
                gns = issue.get("governing_norm_status", {})
                if gns.get("status") == "MISSING":
                    governing_norm_issues.append(issue["issue_id"])
                    gn_articles = _fetch_governing_norm(issue, state, db)
                    if gn_articles:
                        governing_norm_fetched.extend(gn_articles)

            # Fetch standard missing articles (non-governing)
            fetched = _fetch_missing_articles(missing, state, db) if missing else []

            all_fetched = fetched + governing_norm_fetched
            needs_step13_log = bool(missing) or bool(governing_norm_issues)

            if all_fetched:
                # Add fetched articles to issue_articles / shared_context
                for art in all_fetched:
                    added = False
                    for iid, arts in state.get("issue_articles", {}).items():
                        iv_key = f"{iid}:{art['law_number']}/{art['law_year']}"
                        if iv_key in state.get("issue_versions", {}):
                            arts.append(art)
                            added = True
                    if not added:
                        state.setdefault("shared_context", []).append(art)

            # Re-run Step 12 ONLY if a governing norm was MISSING and is now found
            should_rerun = bool(governing_norm_fetched) and bool(governing_norm_issues)

            if should_rerun:
                state = _step6_8_legal_reasoning(state, db)

            # Flag unfetched articles
            if missing:
                fetched_refs = set()
                for a in all_fetched:
                    fetched_refs.add(
                        f"{a.get('law_number', '')}/{a.get('law_year', '')} "
                        f"art.{a.get('article_number', '')}"
                    )
                unfetched = [m for m in missing if m not in fetched_refs]
                if unfetched:
                    state["flags"].append(
                        f"Articole solicitate de analiză dar nedisponibile: "
                        f"{', '.join(unfetched)}"
                    )

            if needs_step13_log:
                yield _step_event(13, "conditional_retrieval", "running")
                cond_duration = time.time() - t0 if 't0' in dir() else 0
                cond_data = {
                    "requested_refs": missing,
                    "governing_norms_searched": governing_norm_issues,
                    "fetched_articles": [
                        {
                            "article_number": a.get("article_number"),
                            "law": f"{a.get('law_number')}/{a.get('law_year')}",
                            "source": a.get("source", ""),
                        }
                        for a in all_fetched
                    ],
                    "fetched_count": len(all_fetched),
                    "requested_count": len(missing) + len(governing_norm_issues),
                    "re_ran_reasoning": should_rerun,
                }
                log_step(
                    db, state["run_id"], "conditional_retrieval", 13, "done",
                    cond_duration,
                    output_summary=(
                        f"Requested {len(missing)} missing + "
                        f"{len(governing_norm_issues)} governing norms, "
                        f"fetched {len(all_fetched)}"
                        + (", re-ran reasoning" if should_rerun else "")
                    ),
                    output_data=cond_data,
                )
                yield _step_event(13, "conditional_retrieval", "done", {
                    "requested": cond_data["requested_count"],
                    "fetched": cond_data["fetched_count"],
                    "re_ran": should_rerun,
                }, cond_duration)
```

- [ ] **Step 4: Run all tests**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/pipeline_service.py tests/test_step13_restructured.py
git commit -m "fix(P7): restructure Step 13 to only re-run Step 12 for governing norms"
```

---

### Task 6: P5 — Version Mismatch Handling

**Files:**
- Modify: `app/services/pipeline_service.py:526-545` (after Step 12 parse)
- Modify: `app/services/pipeline_service.py:290-292` (in `_build_step7_context`)

- [ ] **Step 1: Add version mismatch flag after Step 12 parse**

In `pipeline_service.py`, after line 545 (`state["flags"].append(f"{mid}: not analyzed by reasoning step")`), add:

```python
        # Surface version mismatches as flags
        for issue in parsed.get("issues", []):
            ta = issue.get("temporal_applicability", {})
            if not ta.get("version_matches", True):
                risks = ta.get("temporal_risks", [])
                risk_text = (
                    "; ".join(risks) if risks
                    else "versiunea utilizată nu corespunde datei evenimentului"
                )
                state["flags"].append(
                    f"{issue['issue_id']}: Necorelare versiune — {risk_text}"
                )
```

- [ ] **Step 2: Add version mismatch caveat in `_build_step7_context`**

In `pipeline_service.py`, after line 292 (`parts.append(f"    Temporal risks: {', '.join(ta['temporal_risks'])}")`), add an additional check before the temporal risks block. Replace lines 290-292:

```python
            ta = issue.get("temporal_applicability", {})
            if ta.get("temporal_risks"):
                parts.append(f"    Temporal risks: {', '.join(ta['temporal_risks'])}")
```

With:

```python
            ta = issue.get("temporal_applicability", {})
            if not ta.get("version_matches", True):
                parts.append(
                    "    ⚠ Versiunea legii utilizată nu corespunde exact datei evenimentului."
                )
            if ta.get("temporal_risks"):
                for risk in ta["temporal_risks"]:
                    parts.append(f"    Risc temporal: {risk}")
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add app/services/pipeline_service.py
git commit -m "fix(P5): surface version mismatches from Step 12 as pipeline flags"
```

---

## Batch 4 — Answer Quality

### Task 7: P1 — Answer Template Rewrite + Context Builder Translation

**Files:**
- Modify: `prompts/LA-S7-answer-template.txt:14-49,94-110,112-138`
- Modify: `app/services/pipeline_service.py:250-309` (`_build_step7_context`)
- Create: `tests/test_context_translation.py`

- [ ] **Step 1: Write test for context builder translation**

```python
# tests/test_context_translation.py
"""Tests for RL-RAP terminology translation in _build_step7_context."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _build_step7_context


def _make_state_with_rl_rap():
    return {
        "question_type": "B",
        "legal_domain": "corporate",
        "output_mode": "compliance",
        "core_issue": "Test issue",
        "primary_target": {"actor": "admin", "concern": "liability", "issue_id": "ISSUE-1"},
        "facts": {"stated": [{"fact_id": "F1", "description": "Test fact"}], "assumed": [], "missing": []},
        "rl_rap_output": {
            "issues": [{
                "issue_id": "ISSUE-1",
                "issue_label": "Test",
                "certainty_level": "CONDITIONAL",
                "operative_articles": [],
                "condition_table": [
                    {"condition_id": "C1", "condition_text": "test condition",
                     "status": "SATISFIED", "evidence": "F1: fact", "missing_fact": None},
                    {"condition_id": "C2", "condition_text": "unknown condition",
                     "status": "UNKNOWN", "evidence": None, "missing_fact": "some fact"},
                ],
                "subsumption_summary": {
                    "satisfied": 1, "not_satisfied": 0, "unknown": 1,
                    "norm_applicable": "CONDITIONAL", "blocking_unknowns": ["C2"],
                },
                "uncertainty_sources": [
                    {"type": "LIBRARY_GAP", "detail": "Art 117 missing",
                     "impact": "Cannot verify", "resolvable_by": "ARTICLE_IMPORT"},
                    {"type": "FACTUAL_GAP", "detail": "Damage amount",
                     "impact": "Cannot quantify", "resolvable_by": "USER_INPUT"},
                ],
                "temporal_applicability": {"version_matches": True, "temporal_risks": []},
                "conclusion": "Test conclusion",
                "governing_norm_status": {"status": "PRESENT"},
                "missing_facts": [],
            }]
        },
        "retrieved_articles": [],
        "issue_articles": {"ISSUE-1": []},
        "issue_versions": {},
        "fact_version_map": {},
        "legal_issues": [{"issue_id": "ISSUE-1", "applicable_laws": [], "relevant_date": "2026-03-31", "temporal_rule": "act_date"}],
        "flags": [],
    }


def test_no_raw_satisfied_in_context():
    """Context must not contain raw 'SATISFIED' — should be translated."""
    state = _make_state_with_rl_rap()
    ctx = _build_step7_context(state)
    # Should contain translated version
    assert "Condiție îndeplinită" in ctx
    # Should NOT contain raw English status
    assert " — SATISFIED" not in ctx
    assert " — UNKNOWN" not in ctx


def test_no_raw_uncertainty_types_in_context():
    """Context must not contain LIBRARY_GAP, ARTICLE_IMPORT etc."""
    state = _make_state_with_rl_rap()
    ctx = _build_step7_context(state)
    assert "LIBRARY_GAP" not in ctx
    assert "FACTUAL_GAP" not in ctx
    assert "ARTICLE_IMPORT" not in ctx
    assert "USER_INPUT" not in ctx


def test_translated_uncertainty_present():
    """Translated uncertainty descriptions should appear."""
    state = _make_state_with_rl_rap()
    ctx = _build_step7_context(state)
    assert "Articol indisponibil" in ctx
    assert "Informație lipsă din întrebare" in ctx


def test_no_raw_norm_applicable_in_context():
    """Subsumption summary should use translated labels."""
    state = _make_state_with_rl_rap()
    ctx = _build_step7_context(state)
    assert "norm_applicable" not in ctx
    assert "blocking_unknowns" not in ctx


def test_certainty_as_natural_sentence():
    """Certainty level should be a natural sentence, not a label."""
    state = _make_state_with_rl_rap()
    ctx = _build_step7_context(state)
    assert "CONDITIONAL" not in ctx or "Condiție" in ctx  # only as part of Romanian translation
    assert "Concluzia depinde de informații lipsă" in ctx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_context_translation.py -v`
Expected: FAIL — context still contains raw English labels.

- [ ] **Step 3: Rewrite `_build_step7_context` RL-RAP section**

In `pipeline_service.py`, replace lines 250-309 (the entire RL-RAP analysis section within `_build_step7_context`) with:

```python
        # RL-RAP analysis — translated to Romanian for Step 14
        _STATUS_MAP = {
            "SATISFIED": "Condiție îndeplinită",
            "NOT_SATISFIED": "Condiție neîndeplinită",
            "UNKNOWN": "Informație lipsă",
        }
        _CERTAINTY_MAP = {
            "CERTAIN": "Concluzia este fermă.",
            "PROBABLE": "Concluzia este probabilă, cu rezerve minore.",
            "CONDITIONAL": "Concluzia depinde de informații lipsă.",
            "UNCERTAIN": "Analiza este incompletă — concluzie nesigură.",
        }
        _NORM_MAP = {
            "YES": "Norma se aplică",
            "NO": "Norma nu se aplică",
            "CONDITIONAL": "Aplicabilitate condiționată",
        }
        _UNCERTAINTY_TYPE_MAP = {
            "LIBRARY_GAP": "Articol indisponibil",
            "FACTUAL_GAP": "Informație lipsă din întrebare",
            "LEGAL_AMBIGUITY": "Chestiune juridică interpretabilă",
        }

        parts.append("\nLEGAL ANALYSIS (from reasoning step):")
        for issue in rl_rap.get("issues", []):
            parts.append(f"\n  {issue['issue_id']}: {issue.get('issue_label', '')}")
            certainty = issue.get("certainty_level", "UNKNOWN")
            parts.append(f"    {_CERTAINTY_MAP.get(certainty, certainty)}")

            for oa in issue.get("operative_articles", []):
                parts.append(f"    Operative article: {oa['article_ref']} — {oa.get('disposition', {}).get('modality', '')}")

            # Condition table — translated statuses
            if issue.get("condition_table"):
                parts.append("    Conditions:")
                for ct in issue["condition_table"]:
                    status_ro = _STATUS_MAP.get(ct.get("status", ""), ct.get("status", ""))
                    line = f"      {ct['condition_id']}: {ct['condition_text']} — {status_ro}"
                    if ct.get("evidence"):
                        line += f" (fapt: {ct['evidence']})"
                    if ct.get("missing_fact"):
                        line += f" [Lipsă: {ct['missing_fact']}]"
                    parts.append(line)

                summary = issue.get("subsumption_summary") or {}
                if summary:
                    norm_status = _NORM_MAP.get(summary.get("norm_applicable", "?"), summary.get("norm_applicable", "?"))
                    parts.append(
                        f"    Rezultat: {summary.get('satisfied', 0)} îndeplinite, "
                        f"{summary.get('not_satisfied', 0)} neîndeplinite, "
                        f"{summary.get('unknown', 0)} lipsă → {norm_status}"
                    )
                    if summary.get("blocking_unknowns"):
                        parts.append(f"    Condiții nerezolvate: {', '.join(summary['blocking_unknowns'])}")

            # Legacy conditions format
            elif issue.get("decomposed_conditions"):
                parts.append("    Conditions:")
                for c in issue.get("decomposed_conditions", []):
                    status_ro = _STATUS_MAP.get(c.get("condition_status", ""), c.get("condition_status", ""))
                    fact_refs = ", ".join(c.get("supporting_fact_ids", []))
                    parts.append(f"      {c['condition_id']}: {c['condition_text']} — {status_ro}" +
                               (f" ({fact_refs})" if fact_refs else ""))

            if issue.get("exceptions_checked"):
                parts.append("    Excepții verificate:")
                for ex in issue["exceptions_checked"]:
                    parts.append(f"      {ex['exception_ref']} — {ex['condition_status_summary']} — {ex.get('impact', '')}")

            if issue.get("conflicts"):
                c = issue["conflicts"]
                parts.append(f"    Conflict: {c.get('resolution_rule', 'UNRESOLVED')} — {c.get('rationale', '')}")

            ta = issue.get("temporal_applicability", {})
            if not ta.get("version_matches", True):
                parts.append("    ⚠ Versiunea legii utilizată nu corespunde exact datei evenimentului.")
            if ta.get("temporal_risks"):
                for risk in ta["temporal_risks"]:
                    parts.append(f"    Risc temporal: {risk}")

            parts.append(f"    Conclusion: {issue.get('conclusion', '')}")

            gns = issue.get("governing_norm_status", {})
            if gns.get("status") and gns["status"] != "PRESENT":
                parts.append(f"    Governing norm: {gns['status']} — {gns.get('explanation', '')}")

            # Uncertainty sources — translated
            if issue.get("uncertainty_sources"):
                parts.append("    Surse de incertitudine:")
                for us in issue["uncertainty_sources"]:
                    type_ro = _UNCERTAINTY_TYPE_MAP.get(us.get("type", ""), us.get("type", ""))
                    parts.append(f"      {type_ro}: {us['detail']} (impact: {us.get('impact', '')})")

            if issue.get("missing_facts"):
                parts.append(f"    Informații lipsă: {'; '.join(issue['missing_facts'])}")
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_context_translation.py tests/ -v`
Expected: All tests pass.

- [ ] **Step 5: Rewrite answer template `LA-S7-answer-template.txt`**

**Replace lines 14-49** (LEGAL ANALYSIS INPUT + SUBSUMPTION PRESENTATION) with:

```
LEGAL ANALYSIS INPUT:
You may receive a LEGAL ANALYSIS section from a prior reasoning step. This analysis
contains per-issue conclusions, condition evaluations, and certainty assessments.

When a LEGAL ANALYSIS is present:
- Your job is to COMMUNICATE this analysis clearly in Romanian, not to re-derive it.
- Structure your answer by issue, following the analysis structure.
- For conditions marked as missing information, present them as questions the user must answer.
- For conditional conclusions, explain what the outcome depends on.
- Your confidence cannot be higher than the certainty levels in the analysis.
- Cite articles with version dates as provided in the analysis.

PRESENTING LEGAL ANALYSIS (REQUIRED for each norm cited):
When presenting a legal provision, show how it applies to the user's specific facts.
For each norm, explain in natural language:
1. What the law requires (the conditions for applicability)
2. Which conditions are met based on the user's facts, citing the specific facts
3. Which conditions cannot be verified and what information would be needed
4. The conclusion given the condition analysis

Write as a lawyer explaining to a client. Use natural Romanian sentences, not tables
or checklists. The reader should understand the legal reasoning without any technical
or system knowledge.

Example — GOOD:
"Art. 72 din Legea 31/1990 stabilește obligația administratorului de a acționa cu
prudența unui bun administrator. În cazul dvs., transferul de fonduri către o entitate
controlată indirect, fără aprobarea asociaților, reprezintă o încălcare a acestei
obligații. Totuși, pentru a stabili răspunderea civilă, trebuie demonstrat și
prejudiciul cauzat societății — informație care nu rezultă din datele furnizate."

Example — BAD (just restates the law):
"Art. 72 prevede că administratorul trebuie să acționeze cu prudență."

PROHIBITED TERMS — never use these in the answer:
SATISFIED, NOT_SATISFIED, UNKNOWN, LIBRARY_GAP, FACTUAL_GAP, ARTICLE_IMPORT,
USER_INPUT, CONDITIONAL (as a standalone label), CERTAIN (as a standalone label),
subsumption, condition_table, operative_articles, norm_applicable, blocking_unknowns,
LEGAL_INTERPRETATION, governing_norm_status, RISC NEDETERMINAT (as a standalone label).

Do NOT use ✅, ❓, ✓, ✗, or similar symbols in the answer.
```

**Before line 94** (UNCERTAINTY COMMUNICATION), add:

```
IMPORTANT: The uncertainty types below guide YOUR reasoning about how to present
information. The TYPE NAMES themselves must NEVER appear in the answer text.
Use the natural language patterns shown below.

```

**Replace lines 120-128** (risk labels after TONE CALIBRATION) with:

```
Risk communication must be woven into the analysis narrative:
- When risk is clear and all conditions are met: state the risk directly.
  "Administratorul răspunde personal conform art. X. Riscul este major."
- When risk depends on unknown facts: state it conditionally.
  "Dacă se dovedește prejudiciul, administratorul ar putea răspunde personal,
  riscul fiind potențial major."
- When analysis is incomplete: state what cannot be determined.
  "Pe baza informațiilor disponibile, nu se poate stabili cu certitudine dacă
  există un risc de răspundere penală."

Do NOT use standalone risk labels like "**Risc: MAJOR**" or "**Risc nedeterminat**"
as section headers. Integrate risk assessment into the narrative.
```

**After line 138** (after status labels section), add:

```
These labels are conclusions, not formatting. Use them within sentences, not as
standalone tags. Example: "Situația este potențial contestabilă, deoarece..."
not "Status: POTENȚIAL CONTESTABIL".
```

- [ ] **Step 6: Run all tests**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/services/pipeline_service.py prompts/LA-S7-answer-template.txt \
       tests/test_context_translation.py
git commit -m "fix(P1): rewrite answer template and translate RL-RAP terms in context builder"
```

---

### Task 8: P10 — Tiered Article Context for Step 14

**Files:**
- Modify: `app/services/pipeline_service.py:310-337` (article rendering in `_build_step7_context`)
- Create: `tests/test_tiered_context.py`

- [ ] **Step 1: Write test for tiered article rendering**

```python
# tests/test_tiered_context.py
"""Tests for tiered article context in _build_step7_context."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _build_step7_context


def test_operative_articles_have_full_text():
    """Tier 1 (operative) articles should have full text in context."""
    state = {
        "question_type": "B", "legal_domain": "corporate",
        "output_mode": "compliance", "core_issue": "Test",
        "rl_rap_output": {
            "issues": [{
                "issue_id": "ISSUE-1", "issue_label": "Test",
                "certainty_level": "CERTAIN",
                "operative_articles": [{"article_ref": "Legea 31/1990 art.72"}],
                "condition_table": [], "conclusion": "Test",
                "temporal_applicability": {"version_matches": True},
                "governing_norm_status": {"status": "PRESENT"},
                "uncertainty_sources": [], "missing_facts": [],
            }]
        },
        "retrieved_articles": [
            {"article_id": 1, "article_number": "72", "law_number": "31",
             "law_year": "1990", "law_title": "Legea societatilor",
             "date_in_force": "2025-12-18",
             "text": "Full text of article 72 about administrator duties " * 20},
            {"article_id": 2, "article_number": "798", "law_number": "287",
             "law_year": "2009", "law_title": "Codul Civil",
             "date_in_force": "2025-12-19",
             "text": "Full text of article 798 about civil administration " * 20},
        ],
        "issue_articles": {"ISSUE-1": [
            {"article_id": 1, "article_number": "72", "law_number": "31", "law_year": "1990"},
            {"article_id": 2, "article_number": "798", "law_number": "287", "law_year": "2009"},
        ]},
        "issue_versions": {}, "fact_version_map": {},
        "legal_issues": [{"issue_id": "ISSUE-1", "applicable_laws": [], "relevant_date": "2026-03-31", "temporal_rule": "act_date"}],
        "flags": [], "facts": {},
    }
    ctx = _build_step7_context(state)

    # Art 72 is operative — should have full text
    assert "ARTICOLE RELEVANTE" in ctx
    assert "Full text of article 72" in ctx

    # Art 798 is tier 2 (in issue but not operative) — abbreviated
    assert "ARTICOLE SUPLIMENTARE" in ctx


def test_tier3_articles_reference_only():
    """Tier 3 articles should appear as reference only (no full text)."""
    state = {
        "question_type": "B", "legal_domain": "corporate",
        "output_mode": "compliance", "core_issue": "Test",
        "rl_rap_output": {
            "issues": [{
                "issue_id": "ISSUE-1", "issue_label": "Test",
                "certainty_level": "CERTAIN",
                "operative_articles": [],
                "condition_table": [], "conclusion": "Test",
                "temporal_applicability": {"version_matches": True},
                "governing_norm_status": {"status": "PRESENT"},
                "uncertainty_sources": [], "missing_facts": [],
            }]
        },
        "retrieved_articles": [
            {"article_id": 99, "article_number": "999", "law_number": "1",
             "law_year": "2000", "law_title": "Test Law",
             "date_in_force": "2025-01-01",
             "text": "This text should NOT appear in full " * 20},
        ],
        "issue_articles": {"ISSUE-1": []},  # not assigned to any issue
        "issue_versions": {}, "fact_version_map": {},
        "legal_issues": [{"issue_id": "ISSUE-1", "applicable_laws": [], "relevant_date": "2026-03-31", "temporal_rule": "act_date"}],
        "flags": [], "facts": {},
    }
    ctx = _build_step7_context(state)

    # Art 999 is tier 3 — reference only
    assert "ALTE ARTICOLE" in ctx
    assert "Art. 999" in ctx
    # Full text should NOT be present
    assert "This text should NOT appear in full" not in ctx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_tiered_context.py -v`
Expected: FAIL — current code renders all articles with full text.

- [ ] **Step 3: Replace article rendering in `_build_step7_context`**

In `pipeline_service.py`, replace the article rendering section (lines 310-337, starting with `# Supporting article texts — operative first`) with:

```python
        # Tiered article rendering: operative (full) > related (abbreviated) > rest (reference)
        operative_refs = set()
        for issue in rl_rap.get("issues", []):
            for oa in issue.get("operative_articles", []):
                operative_refs.add(oa.get("article_ref", ""))

        all_articles = [a for a in state.get("retrieved_articles", []) if a]

        issue_article_ids = set()
        for arts in state.get("issue_articles", {}).values():
            for a in arts:
                issue_article_ids.add(a.get("article_id"))

        tier1, tier2, tier3 = [], [], []
        for art in all_articles:
            art_ref = f"art.{art.get('article_number', '')}"
            if any(art_ref in ref for ref in operative_refs):
                tier1.append(art)
            elif art.get("article_id") in issue_article_ids:
                tier2.append(art)
            else:
                tier3.append(art)

        # Tier 1 — full text (operative articles analyzed by reasoning step)
        parts.append("\nARTICOLE RELEVANTE (analizate juridic):")
        if tier1:
            for art in tier1:
                law_ref = f"{art.get('law_title', '')} ({art.get('law_number', '')}/{art.get('law_year', '')})"
                parts.append(f"  [Art. {art.get('article_number', '')}] {law_ref}, versiune {art.get('date_in_force', '')}")
                parts.append(f"  {art.get('text', '')}")
        else:
            parts.append("  (niciun articol operativ identificat)")

        # Tier 2 — abbreviated (assigned to issues but not operative)
        if tier2:
            parts.append("\nARTICOLE SUPLIMENTARE (disponibile pentru citare):")
            for art in tier2:
                law_ref = f"{art.get('law_number', '')}/{art.get('law_year', '')}"
                text = art.get("text", "")
                if len(text) > 200:
                    text_preview = text[:200].rsplit(" ", 1)[0] + "..."
                else:
                    text_preview = text
                parts.append(f"  [Art. {art.get('article_number', '')}] {law_ref}: {text_preview}")

        # Tier 3 — reference only (not assigned to any issue)
        if tier3:
            parts.append("\nALTE ARTICOLE RECUPERATE (referință):")
            refs = [
                f"Art. {a.get('article_number', '')} ({a.get('law_number', '')}/{a.get('law_year', '')})"
                for a in tier3
            ]
            parts.append(f"  {', '.join(refs)}")
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_tiered_context.py tests/ -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/pipeline_service.py tests/test_tiered_context.py
git commit -m "feat(P10): tiered article context reduces Step 14 input by ~50%"
```

---

## Final Verification

- [ ] **Run full test suite**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/ -v
```

All tests must pass.

- [ ] **Verify ChromaDB re-indexing**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && source .venv/bin/activate && python -c "
from app.services.chroma_service import verify_index_completeness
from app.database import SessionLocal
db = SessionLocal()
m = verify_index_completeness(db)
print(f'Missing versions: {len(m)}')
for x in m: print(f'  {x}')
db.close()
"
```

Expected: `Missing versions: 0`
