# Pipeline Repair V3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 8 interrelated pipeline problems (wrong dates, wrong versions, missing articles, double Step 12, leaked terminology) and reduce cost from $0.36 to ~$0.18 per query.

**Architecture:** Modify the LA-S1 prompt for better date anchoring, add candidate article direct lookups to retrieval, complete all translation maps in the context builder, and restructure Steps 2/6 so version selection happens before the availability gate.

**Tech Stack:** Python, SQLAlchemy, pytest, ChromaDB, sentence-transformers cross-encoder

---

## File Map

| File | Responsibility | Tasks |
|------|----------------|-------|
| `prompts/LA-S1-issue-classifier.txt` | Issue classification prompt | Task 1 (P1 anchoring + P5A candidate articles) |
| `app/services/pipeline_service.py` | Pipeline orchestration | Task 2 (P5B direct lookup in Step 7), Task 3 (P8 translation), Task 4 (P3+P4 Step 2/6 restructure) |
| `app/services/reranker_service.py` | Article reranking | Task 2 (P5C min_per_law) |
| `tests/test_context_translation.py` | Translation coverage tests | Task 3 |
| `tests/test_candidate_lookup.py` | Candidate article retrieval tests | Task 2 |
| `tests/test_version_preparation.py` | Step 2 version preparation tests | Task 4 |

---

## Batch 1 — Independent fixes (Tasks 1, 2, 3 in parallel)

### Task 1: P1 — Rewrite LA-S1 Hypothetical Date Anchoring + Add Candidate Articles Schema

**Files:**
- Modify: `prompts/LA-S1-issue-classifier.txt:113-118` (anchoring), `:194-214` (schema), `:231-237` (guidance)

- [ ] **Step 1: Replace the HYPOTHETICAL SCENARIO ANCHORING section**

In `prompts/LA-S1-issue-classifier.txt`, replace lines 113-118 (the 6-line section starting with `HYPOTHETICAL SCENARIO ANCHORING (CRITICAL):` and ending before `CRIMINAL LAW — TEMPUS REGIT ACTUM:`) with:

```
   HYPOTHETICAL vs HISTORICAL — DECISION GATE (apply BEFORE choosing temporal_rule):

   Step A — Is there an explicit calendar date (e.g., "pe 15.03.2024", "în anul 2023")
            or reference to a specific historical event in the question?
     YES → The scenario is HISTORICAL. Use act_date/contract_formation/etc.
           with the stated date.
     NO  → Go to Step B.

   Step B — Does the question use conditional language ("Dacă...",
            "în cazul în care...", "ce se întâmplă dacă..."), or describe
            a scenario without anchoring it to a specific past moment?
     YES → The scenario is HYPOTHETICAL. Apply Rule H below.
     NO  → Default to current_law with TODAY'S DATE.

   Rule H (HYPOTHETICAL SCENARIOS):
     - The FIRST described event happens at TODAY'S DATE
     - Subsequent events are computed relative to TODAY
       Example: "~1 year later" → TODAY + 1 year
     - ALL temporal_rules use the anchored dates (not fabricated past dates)
     - Past tense does NOT make it historical — Romanian hypotheticals
       commonly use past tense ("a transferat", "a intrat")
     - For criminal issues: use act_date with the ANCHORED date (= TODAY),
       not a fabricated past date
```

The section being replaced is exactly these 6 lines:
```
   HYPOTHETICAL SCENARIO ANCHORING (CRITICAL):
   When the question uses conditional language ("Dacă...", "în cazul în care...")
   or describes a scenario without specific past dates, anchor the first event
   to TODAY'S DATE and compute subsequent events relative to it.
   Past tense alone does NOT make a scenario historical — only explicit calendar
   dates or historical references do.
```

- [ ] **Step 2: Add `candidate_articles` to the legal_issues schema**

In `prompts/LA-S1-issue-classifier.txt`, find the `legal_issues` array schema (lines 194-214). After `"mitior_lex_relevant": false,` (line 204) and before `"fact_dates": [` (line 205), insert:

```json
      "candidate_articles": [
        {
          "law_key": "<law_number/law_year>",
          "article": "<article number, e.g. '241' or '144^1'>",
          "reason": "<brief reason why this article applies>"
        }
      ],
```

- [ ] **Step 3: Add candidate articles guidance**

In `prompts/LA-S1-issue-classifier.txt`, after the `MITIOR LEX FLAG:` section (line 237), add:

```
CANDIDATE ARTICLES (recommended for STANDARD and COMPLEX questions):
For each legal issue, list specific articles you believe are directly
applicable based on your legal knowledge. Format: law_key and article number.
These improve retrieval precision — the system also searches broadly,
so missing an article here is not critical. List only articles you
are confident about. For SIMPLE questions, use an empty array [].
```

- [ ] **Step 4: Verify prompt is valid**

Run: `python -c "open('prompts/LA-S1-issue-classifier.txt').read(); print('OK')"`
Expected: `OK` (no syntax errors)

- [ ] **Step 5: Commit**

```bash
git add prompts/LA-S1-issue-classifier.txt
git commit -m "fix(P1): rewrite hypothetical anchoring as decision gate + add candidate_articles schema"
```

---

### Task 2: P5+P6 — Candidate Article Direct Lookup in Retrieval + Reranker min_per_law

**Files:**
- Modify: `app/services/pipeline_service.py:2441-2601` (Step 7 retrieval)
- Modify: `app/services/reranker_service.py:40` (min_per_law default)
- Create: `tests/test_candidate_lookup.py`

- [ ] **Step 1: Write failing tests for candidate article lookup**

Create `tests/test_candidate_lookup.py`:

```python
"""Tests for candidate article direct lookup in Step 7 retrieval."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _fetch_candidate_articles


def test_fetch_candidate_articles_finds_matching():
    """Direct lookup returns articles matching candidate references."""
    # Mock: simulate a state with candidate_articles and version info
    state = {
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "candidate_articles": [
                    {"law_key": "31/1990", "article": "72", "reason": "test"},
                ],
                "applicable_laws": ["31/1990"],
            },
        ],
        "unique_versions": {"31/1990": [10]},
    }

    # Create a mock db session that returns a fake article
    class FakeArticle:
        id = 101
        law_version_id = 10
        article_number = "72"
        full_text = "Art. 72 Obligatiile administratorilor..."
        is_abrogated = False
        label = None
        amendment_notes = []

    class FakeQuery:
        def __init__(self):
            self._filters = []
        def filter(self, *args):
            self._filters.extend(args)
            return self
        def first(self):
            return FakeArticle()

    class FakeDB:
        def query(self, model):
            return FakeQuery()

    result = _fetch_candidate_articles(state, FakeDB())
    assert len(result) >= 1
    assert result[0]["article_number"] == "72"
    assert result[0]["source"] == "candidate_lookup"


def test_fetch_candidate_articles_empty_when_no_candidates():
    """Returns empty list when no candidate_articles in issues."""
    state = {
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "applicable_laws": ["31/1990"],
            },
        ],
        "unique_versions": {"31/1990": [10]},
    }

    class FakeDB:
        def query(self, model):
            class FQ:
                def filter(self, *a): return self
                def first(self): return None
            return FQ()

    result = _fetch_candidate_articles(state, FakeDB())
    assert result == []


def test_fetch_candidate_articles_skips_missing():
    """Skips articles not found in DB without error."""
    state = {
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "candidate_articles": [
                    {"law_key": "286/2009", "article": "999", "reason": "nonexistent"},
                ],
                "applicable_laws": ["286/2009"],
            },
        ],
        "unique_versions": {"286/2009": [20]},
    }

    class FakeDB:
        def query(self, model):
            class FQ:
                def filter(self, *a): return self
                def first(self): return None
            return FQ()

    result = _fetch_candidate_articles(state, FakeDB())
    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_candidate_lookup.py -v`
Expected: FAIL — `_fetch_candidate_articles` does not exist yet

- [ ] **Step 3: Implement `_fetch_candidate_articles` function**

In `app/services/pipeline_service.py`, add this function BEFORE `_step4_hybrid_retrieval` (before line 2441):

```python
def _fetch_candidate_articles(state: dict, db) -> list[dict]:
    """Fetch candidate articles from Step 1 by direct DB lookup.

    Returns article dicts ready to merge into the retrieval pool.
    These are articles Claude identified as likely applicable during
    issue classification — fetching them directly ensures retrieval
    doesn't miss legally-correct but semantically-distant articles.
    """
    from app.models.law import Article as ArticleModel

    results = []
    seen = set()
    unique_versions = state.get("unique_versions", {})

    for issue in state.get("legal_issues", []):
        for ca in issue.get("candidate_articles", []):
            law_key = ca.get("law_key", "")
            article_num = ca.get("article", "")
            if not law_key or not article_num:
                continue

            version_ids = unique_versions.get(law_key, [])
            if not version_ids:
                continue

            for vid in version_ids:
                cache_key = f"{vid}:{article_num}"
                if cache_key in seen:
                    continue
                seen.add(cache_key)

                article = (
                    db.query(ArticleModel)
                    .filter(
                        ArticleModel.law_version_id == vid,
                        ArticleModel.article_number == article_num,
                    )
                    .first()
                )
                if not article:
                    continue

                parts = law_key.split("/")
                results.append({
                    "article_id": article.id,
                    "law_version_id": vid,
                    "article_number": article.article_number,
                    "text": article.full_text,
                    "label": article.label,
                    "source": "candidate_lookup",
                    "tier": "tier1_primary",
                    "role": "PRIMARY",
                    "law_number": parts[0] if len(parts) > 0 else "",
                    "law_year": parts[1] if len(parts) > 1 else "",
                    "is_abrogated": article.is_abrogated,
                    "doc_type": "article",
                })

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_candidate_lookup.py -v`
Expected: 3 tests PASS

- [ ] **Step 5: Integrate candidate lookup into Step 7 retrieval**

In `app/services/pipeline_service.py`, in the `_step4_hybrid_retrieval` function, after the line `all_articles = []` (line 2446) and before the `seen_ids = set()` line (line 2447), add:

```python
    # Direct lookup for candidate articles from Step 1 classification
    candidate_results = _fetch_candidate_articles(state, db)
    candidate_count = 0
```

Then after `seen_ids = set()` (line 2447), add:

```python
    for art in candidate_results:
        aid = f"{art.get('doc_type', 'article')}:{art['article_id']}"
        if aid not in seen_ids:
            seen_ids.add(aid)
            all_articles.append(art)
            candidate_count += 1
```

Update the log_step output_summary (line 2591) to include candidate count:

Replace:
```python
        output_summary=f"Retrieved {len(all_articles)} articles (BM25: {bm25_count}, semantic: {semantic_count}, entity: {entity_count}, dupes removed: {duplicates_removed})",
```
With:
```python
        output_summary=f"Retrieved {len(all_articles)} articles (candidate: {candidate_count}, BM25: {bm25_count}, semantic: {semantic_count}, entity: {entity_count}, dupes removed: {duplicates_removed})",
```

Also add `"candidate_count": candidate_count,` to the `output_data` dict (after line 2594).

- [ ] **Step 6: Update reranker min_per_law default**

In `app/services/reranker_service.py`, change line 40 from:

```python
    min_per_law: int = 2,
```

To:

```python
    min_per_law: int = 3,
```

- [ ] **Step 7: Run all existing tests**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/ -v`
Expected: All tests pass (including test_candidate_lookup.py)

- [ ] **Step 8: Commit**

```bash
git add app/services/pipeline_service.py app/services/reranker_service.py tests/test_candidate_lookup.py
git commit -m "feat(P5+P6): add candidate article direct lookup in retrieval + increase min_per_law to 3"
```

---

### Task 3: P8 — Complete Translation Maps for All Bypass Points

**Files:**
- Modify: `app/services/pipeline_service.py:251-345` (translation maps and bypass points in `_build_step7_context`)
- Modify: `tests/test_context_translation.py` (add tests for all 5 bypass points)

- [ ] **Step 1: Write failing tests for all 5 bypass points**

Add these tests to the end of `tests/test_context_translation.py`:

```python
def test_no_raw_governing_norm_status():
    """Governing norm status MISSING/INFERRED must be translated."""
    state = _make_state_with_rl_rap()
    state["rl_rap_output"]["issues"][0]["governing_norm_status"] = {
        "status": "MISSING",
        "explanation": "Art. 169 not in provided articles",
    }
    ctx = _build_step7_context(state)
    assert "MISSING" not in ctx
    assert "Norma nu a fost identificat" in ctx


def test_no_raw_exception_status():
    """Exception condition_status_summary must be translated."""
    state = _make_state_with_rl_rap()
    # conftest mock already has exceptions_checked with "UNKNOWN"
    state["rl_rap_output"]["issues"][0]["exceptions_checked"] = [
        {
            "exception_ref": "Legea 31/1990 art.197 alin.(4)",
            "condition_status_summary": "UNKNOWN",
            "impact": "Exception for ordinary course",
        }
    ]
    ctx = _build_step7_context(state)
    # "UNKNOWN" should not appear as a standalone status
    lines_with_exception = [l for l in ctx.split("\n") if "197" in l and "alin" in l]
    for line in lines_with_exception:
        assert "— UNKNOWN —" not in line


def test_no_raw_conflict_resolution_rule():
    """Conflict resolution_rule must be translated."""
    state = _make_state_with_rl_rap()
    state["rl_rap_output"]["issues"][0]["conflicts"] = {
        "resolution_rule": "UNRESOLVED",
        "rationale": "competing provisions",
    }
    ctx = _build_step7_context(state)
    assert "UNRESOLVED" not in ctx
    assert "Conflict nerezolvat" in ctx


def test_blocking_unknowns_use_condition_text():
    """blocking_unknowns should show condition text, not IDs like C1, C2."""
    state = _make_state_with_rl_rap()
    state["rl_rap_output"]["issues"][0]["subsumption_summary"]["blocking_unknowns"] = ["C2"]
    ctx = _build_step7_context(state)
    # Should contain the condition text "unknown condition" not raw "C2"
    assert "unknown condition" in ctx


def test_governing_norm_present_not_shown():
    """When governing_norm_status is PRESENT, nothing should be output about it."""
    state = _make_state_with_rl_rap()
    state["rl_rap_output"]["issues"][0]["governing_norm_status"] = {"status": "PRESENT"}
    ctx = _build_step7_context(state)
    assert "Governing norm" not in ctx
    assert "Norma guvernant" not in ctx
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_context_translation.py -v`
Expected: 5 new tests FAIL (bypass points not yet fixed)

- [ ] **Step 3: Add new translation maps**

In `app/services/pipeline_service.py`, after the `_UNCERTAINTY_TYPE_MAP` definition (after line 271), add:

```python
        _GOVERNING_NORM_MAP = {
            "PRESENT": None,
            "MISSING": "Norma nu a fost identificată în articolele disponibile",
            "INFERRED": "Norma a fost dedusă din cadrul legal general",
        }
        _EXCEPTION_STATUS_MAP = {
            "SATISFIED": "Excepție aplicabilă",
            "NOT_SATISFIED": "Excepție inaplicabilă",
            "UNKNOWN": "Excepție — informație insuficientă",
        }
        _CONFLICT_RESOLUTION_MAP = {
            "UNRESOLVED": "Conflict nerezolvat între norme concurente",
            "lex_specialis": "Se aplică norma specială",
            "lex_posterior": "Se aplică norma mai recentă",
            "lex_superior": "Se aplică norma superioară",
        }
```

- [ ] **Step 4: Fix bypass point 1 — governing_norm_status (line 332-334)**

Replace lines 332-334:
```python
            gns = issue.get("governing_norm_status", {})
            if gns.get("status") and gns["status"] != "PRESENT":
                parts.append(f"    Governing norm: {gns['status']} — {gns.get('explanation', '')}")
```

With:
```python
            gns = issue.get("governing_norm_status", {})
            if gns.get("status"):
                translated_gns = _GOVERNING_NORM_MAP.get(gns["status"])
                if translated_gns:  # None = PRESENT, don't output
                    parts.append(f"    Norma guvernantă: {translated_gns}")
                    if gns.get("explanation"):
                        parts.append(f"      Detalii: {gns['explanation']}")
```

- [ ] **Step 5: Fix bypass point 2 — exceptions_checked (line 314-317)**

Replace lines 316-317:
```python
                for ex in issue["exceptions_checked"]:
                    parts.append(f"      {ex['exception_ref']} — {ex['condition_status_summary']} — {ex.get('impact', '')}")
```

With:
```python
                for ex in issue["exceptions_checked"]:
                    ex_status = _EXCEPTION_STATUS_MAP.get(
                        ex.get("condition_status_summary", ""),
                        ex.get("condition_status_summary", ""),
                    )
                    parts.append(f"      {ex['exception_ref']} — {ex_status} — {ex.get('impact', '')}")
```

- [ ] **Step 6: Fix bypass point 3 — conflicts resolution_rule (line 319-321)**

Replace line 321:
```python
                parts.append(f"    Conflict: {c.get('resolution_rule', 'UNRESOLVED')} — {c.get('rationale', '')}")
```

With:
```python
                rule = _CONFLICT_RESOLUTION_MAP.get(
                    c.get("resolution_rule", "UNRESOLVED"),
                    c.get("resolution_rule", "UNRESOLVED"),
                )
                parts.append(f"    Conflict: {rule} — {c.get('rationale', '')}")
```

- [ ] **Step 7: Fix bypass point 4 — blocking_unknowns (line 302-303)**

Replace lines 302-303:
```python
                    if summary.get("blocking_unknowns"):
                        parts.append(f"    Condiții nerezolvate: {', '.join(summary['blocking_unknowns'])}")
```

With:
```python
                    if summary.get("blocking_unknowns"):
                        ct_lookup = {
                            ct["condition_id"]: ct.get("condition_text", ct["condition_id"])
                            for ct in issue.get("condition_table", [])
                            if ct.get("condition_id")
                        }
                        blocking_texts = [ct_lookup.get(cid, cid) for cid in summary["blocking_unknowns"]]
                        parts.append(f"    Condiții nerezolvate: {'; '.join(blocking_texts)}")
```

- [ ] **Step 8: Fix bypass point 5 — temporal_risks (line 326-328)**

Replace lines 326-328:
```python
            if ta.get("temporal_risks"):
                for risk in ta["temporal_risks"]:
                    parts.append(f"    Risc temporal: {risk}")
```

With:
```python
            if ta.get("temporal_risks"):
                for risk in ta["temporal_risks"]:
                    if isinstance(risk, dict):
                        parts.append(f"    Risc temporal: {risk.get('description', str(risk))}")
                    else:
                        parts.append(f"    Risc temporal: {risk}")
```

- [ ] **Step 9: Add defense-in-depth sanitizer**

After the `_build_step7_context` function's final `return` statement, add a wrapper call. Find where `_build_step7_context` is called (should be in `_step7_answer_generation`). After the call `ctx = _build_step7_context(state)`, add:

```python
    # Defense-in-depth: warn if any untranslated pipeline terms leaked through
    _FORBIDDEN_TERMS = {
        "SATISFIED", "NOT_SATISFIED", "LIBRARY_GAP", "FACTUAL_GAP",
        "ARTICLE_IMPORT", "USER_INPUT", "GOVERNING_NORM_INCOMPLETE",
        "GOVERNING_NORM_MISSING", "UNRESOLVED", "RISC NEDETERMINAT",
    }
    for term in _FORBIDDEN_TERMS:
        if term in ctx:
            logger.warning(f"Untranslated pipeline term '{term}' in Step 14 context for run {state['run_id']}")
```

- [ ] **Step 10: Run all tests**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_context_translation.py tests/test_step7_context.py tests/test_step7_revised.py -v`
Expected: All tests pass

- [ ] **Step 11: Commit**

```bash
git add app/services/pipeline_service.py tests/test_context_translation.py
git commit -m "fix(P8): complete all 5 translation bypass points + add defense-in-depth sanitizer"
```

---

## Batch 2 — Depends on Batch 1

### Task 4: P3+P4 — Move Version Selection Into Step 2 + Simplify Step 6

**Files:**
- Modify: `app/services/pipeline_service.py:1891-1987` (Step 2), `:2198-2419` (Step 6), `:2227-2237` (move helpers to module level)
- Modify: `app/services/law_mapping.py:11-135` (Step 3 — accept version info)
- Create: `tests/test_version_preparation.py`

- [ ] **Step 1: Write failing tests for version preparation**

Create `tests/test_version_preparation.py`:

```python
"""Tests for Step 2 version preparation with DB lookups."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _find_version_for_date, _fallback_version


class FakeVersion:
    """Minimal LawVersion stand-in for unit tests."""
    def __init__(self, id, date_in_force, is_current=False, ver_id=None):
        self.id = id
        self.date_in_force = date_in_force
        self.is_current = is_current
        self.ver_id = ver_id or f"ver_{id}"


def test_find_version_for_date_exact():
    """Selects newest version with date_in_force <= target."""
    versions = [
        FakeVersion(3, "2026-01-01", is_current=True),
        FakeVersion(2, "2025-06-01"),
        FakeVersion(1, "2024-01-01"),
    ]
    result = _find_version_for_date(versions, "2025-08-01")
    assert result.id == 2


def test_find_version_for_date_future():
    """For future target date, returns latest enacted version."""
    versions = [
        FakeVersion(3, "2026-01-01", is_current=True),
        FakeVersion(2, "2025-06-01"),
    ]
    result = _find_version_for_date(versions, "2027-06-01")
    assert result.id == 3


def test_find_version_for_date_none():
    """Returns None when no version has date_in_force <= target."""
    versions = [
        FakeVersion(3, "2026-01-01"),
    ]
    result = _find_version_for_date(versions, "2025-01-01")
    assert result is None


def test_fallback_version_prefers_current():
    """Fallback returns the current version."""
    versions = [
        FakeVersion(3, "2026-01-01", is_current=True),
        FakeVersion(2, "2025-06-01"),
    ]
    result = _fallback_version(versions)
    assert result.id == 3


def test_fallback_version_first_if_no_current():
    """Fallback returns first version if none is current."""
    versions = [
        FakeVersion(3, "2026-01-01"),
        FakeVersion(2, "2025-06-01"),
    ]
    result = _fallback_version(versions)
    assert result.id == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_version_preparation.py -v`
Expected: FAIL — `_find_version_for_date` not importable (currently nested in Step 6)

- [ ] **Step 3: Move `_find_version_for_date` and `_fallback_version` to module level**

In `app/services/pipeline_service.py`, add these two functions at module level, BEFORE the `_step1b_date_extraction` function (before line 1891). They are currently defined as nested functions inside `_step3_version_selection` at lines 2227-2237.

Add at module level (before line 1891):

```python
def _find_version_for_date(versions, target_date: str):
    """Find the newest version with date_in_force <= target_date.

    Args:
        versions: List of LawVersion objects, sorted by date_in_force DESC.
        target_date: ISO date string (YYYY-MM-DD).
    Returns: LawVersion or None.
    """
    for v in versions:
        if v.date_in_force and str(v.date_in_force) <= target_date:
            return v
    return None


def _fallback_version(versions):
    """Return current version, or first available."""
    current = [v for v in versions if v.is_current]
    return current[0] if current else versions[0] if versions else None
```

Then DELETE the nested definitions inside `_step3_version_selection` (lines 2227-2237 — the two `def` blocks for `_find_version_for_date` and `_fallback_version`). Also delete the `_get_versions` helper (lines 2217-2225) since it will be inlined.

- [ ] **Step 4: Run tests to verify module-level functions work**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/test_version_preparation.py -v`
Expected: 5 tests PASS

- [ ] **Step 5: Add DB version lookup to Step 2**

In `app/services/pipeline_service.py`, modify `_step1b_date_extraction` (line 1891). Rename it to `_step1b_version_preparation` and add DB lookups after the `fact_version_map` is built.

First, rename the function:
```python
def _step1b_version_preparation(state: dict, db: Session) -> dict:
    """Derive temporal context and select law versions from Step 1 output.

    1. Sets state["date_type"] for version currency check
    2. Builds fact_version_map with per-fact dates
    3. Performs DB lookups to select the correct law_version_id per fact
    """
```

After `state["fact_version_map"] = fact_version_map` (line 1960) and before the `law_date_map` update (line 1962), add:

```python
    # --- DB version selection per fact ---
    today = state.get("today", datetime.date.today().isoformat())
    versions_cache = {}  # law_id -> [LawVersion objects, sorted DESC]
    version_notes = []

    for map_key, fact_info in fact_version_map.items():
        law_key = map_key.split(":")[-1]
        parts = law_key.split("/")
        if len(parts) != 2:
            continue
        law_number, law_year = parts

        # Query Law table directly (candidate_laws not available yet)
        db_law = (
            db.query(Law)
            .filter(Law.law_number == law_number, Law.law_year == int(law_year))
            .first()
        )
        if not db_law:
            fact_info["availability"] = "missing"
            continue

        fact_info["law_id"] = db_law.id

        if db_law.id not in versions_cache:
            versions_cache[db_law.id] = (
                db.query(LawVersion)
                .filter(LawVersion.law_id == db_law.id)
                .order_by(LawVersion.date_in_force.desc().nullslast())
                .all()
            )
        versions = versions_cache[db_law.id]
        if not versions:
            fact_info["availability"] = "missing"
            continue

        fact_date = fact_info.get("relevant_date", today)
        if fact_date == "unknown":
            fact_date = today

        selected = _find_version_for_date(versions, fact_date)
        if not selected:
            selected = _fallback_version(versions)
            version_notes.append(f"{map_key}: No version for {fact_date}, using fallback")

        if selected:
            fact_info["law_version_id"] = selected.id
            fact_info["date_in_force"] = str(selected.date_in_force) if selected.date_in_force else None
            fact_info["is_current"] = selected.is_current
            fact_info["ver_id"] = selected.ver_id
            fact_info["availability"] = "available"
        else:
            fact_info["availability"] = "missing"

    state["fact_version_map"] = fact_version_map
    if version_notes:
        state.setdefault("flags", []).extend(version_notes)
```

Also update the function's caller. Search for `_step1b_date_extraction` and replace with `_step1b_version_preparation`.

Update the log_step call to include version info:
```python
        output_data={
            "date_type": state["date_type"],
            "primary_date": state.get("primary_date"),
            "temporal_rules": temporal_rules,
            "derived_from": "step1_classification",
            "versions_needed": {k: sorted(v) for k, v in versions_needed.items()},
            "fact_count": len(fact_version_map),
            "versions_resolved": sum(1 for f in fact_version_map.values() if f.get("law_version_id")),
            "versions_missing": sum(1 for f in fact_version_map.values() if f.get("availability") == "missing"),
        },
```

- [ ] **Step 6: Simplify Step 6 to binding only**

Replace the body of `_step3_version_selection` (lines 2198-2419) with the simplified binding-only version. Keep the function signature and log_step call:

```python
def _step3_version_selection(state: dict, db: Session) -> dict:
    """Bind version IDs from Step 2's fact_version_map into pipeline state structures."""
    t0 = time.time()
    today = state.get("today", datetime.date.today().isoformat())

    fact_version_map = state.get("fact_version_map", {})
    issue_versions = {}
    selected_versions = {}
    unique_versions = {}
    version_notes = []

    for map_key, fact_info in fact_version_map.items():
        if not fact_info.get("law_version_id"):
            continue

        parts = map_key.split(":")
        law_key = parts[-1]
        issue_id = parts[0]

        combo_key = f"{issue_id}:{law_key}"
        if combo_key not in issue_versions:
            issue_versions[combo_key] = {
                "law_version_id": fact_info["law_version_id"],
                "law_id": fact_info.get("law_id"),
                "issue_id": issue_id,
                "law_key": law_key,
                "relevant_date": fact_info.get("relevant_date", today),
                "date_in_force": fact_info.get("date_in_force"),
                "is_current": fact_info.get("is_current"),
                "temporal_rule": fact_info.get("temporal_rule", ""),
                "ver_id": fact_info.get("ver_id"),
            }

        unique_versions.setdefault(law_key, set()).add(fact_info["law_version_id"])

        # Backward-compat: keep latest version per law
        existing = selected_versions.get(law_key)
        if not existing or (fact_info.get("date_in_force") and (
            not existing.get("date_in_force") or
            fact_info["date_in_force"] > existing["date_in_force"]
        )):
            selected_versions[law_key] = {
                "law_version_id": fact_info["law_version_id"],
                "law_id": fact_info.get("law_id"),
                "date_in_force": fact_info.get("date_in_force"),
                "is_current": fact_info.get("is_current"),
                "ver_id": fact_info.get("ver_id"),
            }

    # Check for non-current versions
    for key, v in selected_versions.items():
        if v.get("date_in_force") and not v.get("is_current"):
            version_notes.append(
                f"{key}: Using version from {v['date_in_force']} (not the current version)"
            )

    duration = time.time() - t0
    state["issue_versions"] = issue_versions
    state["selected_versions"] = selected_versions
    state["unique_versions"] = {k: list(v) for k, v in unique_versions.items()}
    state["version_notes"] = version_notes

    if version_notes:
        state["flags"].extend(version_notes)

    log_step(
        db, state["run_id"], "version_selection", 6, "done",
        duration,
        output_summary=f"Bound {len(selected_versions)} law versions for {len(issue_versions)} issue-law pairs",
        output_data={
            "selected_versions": selected_versions,
            "issue_versions": {k: {kk: vv for kk, vv in v.items() if kk != "ver_id"} for k, v in issue_versions.items()},
            "notes": version_notes,
            "unique_version_count": sum(len(s) for s in unique_versions.values()),
        },
    )

    return state
```

- [ ] **Step 7: Update Step 3 (law_mapping.py) to use version info from Step 2**

In `app/services/law_mapping.py`, modify `check_laws_in_db` to accept and use `fact_version_map`:

Add a new parameter to the function signature (line 11):

```python
def check_laws_in_db(
    laws: list[dict],
    db: Session,
    law_date_map: dict[str, list[str] | str] | None = None,
    fact_version_map: dict | None = None,
) -> list[dict]:
```

After the existing version check loop (after line 100, before the `# --- Version status check` comment on line 102), add:

```python
    # --- Enrich with version availability from Step 2's fact_version_map ---
    if fact_version_map:
        for law in laws:
            law_key = f"{law['law_number']}/{law['law_year']}"
            # Check if any fact in fact_version_map for this law has a resolved version
            has_version = any(
                info.get("law_version_id") is not None
                for key, info in fact_version_map.items()
                if key.endswith(f":{law_key}")
            )
            law["version_available"] = has_version
            # Check if any fact has availability == "missing"
            has_missing = any(
                info.get("availability") == "missing"
                for key, info in fact_version_map.items()
                if key.endswith(f":{law_key}")
            )
            if has_missing and not has_version:
                law["availability"] = "missing"
```

Then update the caller in `pipeline_service.py` where `check_laws_in_db` is called to pass `fact_version_map`:

Find the call to `check_laws_in_db` (search for `check_laws_in_db(`) and add the parameter:
```python
check_laws_in_db(laws, db, law_date_map=state.get("law_date_map"), fact_version_map=state.get("fact_version_map"))
```

- [ ] **Step 8: Update the caller of the renamed function**

Search for all references to `_step1b_date_extraction` in `pipeline_service.py` and replace with `_step1b_version_preparation`. There should be exactly one call site in the main pipeline orchestration function.

- [ ] **Step 9: Run all tests**

Run: `cd /Users/anaandrei/projects/themis-legal/backend && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 10: Commit**

```bash
git add app/services/pipeline_service.py app/services/law_mapping.py tests/test_version_preparation.py
git commit -m "feat(P3+P4): move version selection into Step 2 + simplify Step 6 to binding"
```

---

### Task 5: Cost Optimization — Dynamic max_tokens for Step 12

**Files:**
- Modify: `app/services/pipeline_service.py:611-616` (Step 12 max_tokens)

This is already implemented correctly. Lines 611-616 show:

```python
    num_issues = len(state.get("legal_issues", []))
    complexity = state.get("complexity", "STANDARD")
    if complexity == "COMPLEX" or num_issues >= 3:
        rl_rap_max_tokens = min(16384, 4096 + num_issues * 2048)
    else:
        rl_rap_max_tokens = 8192
```

**No changes needed.** The dynamic scaling is already in place from the previous implementation round. The cost savings come primarily from eliminating the second Step 12 run (P7, fixed by P5+P6).

---

## Self-Review

**1. Spec coverage:**
- P1 (hypothetical anchoring): Task 1 Step 1 ✓
- P2 (wrong versions): Fixed by P1, no task needed ✓
- P3+P4 (Step 2/6 restructure): Task 4 ✓
- P5+P6 (candidate articles + retrieval): Task 1 Steps 2-3 (schema) + Task 2 (implementation) ✓
- P7 (double Step 12): Fixed by P5+P6, no task needed ✓
- P8 (terminology leaks): Task 3 ✓
- Cost optimization: Already implemented, verified in Task 5 ✓

**2. Placeholder scan:** No TBDs, TODOs, or "implement later" found.

**3. Type consistency:**
- `_fetch_candidate_articles` returns `list[dict]` in both Task 2 test and implementation ✓
- `_find_version_for_date` signature matches between Task 4 tests and implementation ✓
- `fact_version_map` dict structure consistent across Tasks 4 Step 5 and Step 6 ✓
- `candidate_articles` JSON schema in Task 1 matches the parsing in Task 2 ✓
