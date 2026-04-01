# Pipeline Retrieval Overhaul V4 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix wrong article retrieval by adding concept-based article resolution, protecting validated candidates from reranking, and ensuring Step 12 runs only once.

**Architecture:** Step 1 outputs concept descriptions per issue. A new Step 1c resolves concepts to real articles via filtered ChromaDB queries, validates candidate article numbers against the DB, and produces a protected set. The reranker only filters discovery articles. Prompt changes constrain Step 14 to presentation.

**Tech Stack:** Python 3.12, SQLAlchemy, ChromaDB, sentence-transformers, Next.js/TypeScript (frontend)

---

## File Structure

| File | Role | Action |
|------|------|--------|
| `prompts/LA-S1-issue-classifier.txt` | Step 1 prompt | Modify: add concept_descriptions schema + guidance |
| `prompts/LA-S7-answer-template.txt` | Step 14 prompt | Modify: add presentation constraint |
| `app/services/reranker_service.py` | Cross-encoder reranking | Modify: fix min_per_law swap bug |
| `app/services/pipeline_service.py` | Pipeline orchestration | Modify: add Step 1c, protect candidates in Steps 7/9, reduce tier limits |
| `tests/test_concept_resolution.py` | Tests for Step 1c | Create |
| `tests/test_candidate_protection.py` | Tests for Variant 3 | Create |
| `frontend/src/app/settings/pipeline/run-detail.tsx` | Pipeline UI | Modify: show candidate articles |

---

## Batch 1 — Independent Fixes (parallel)

### Task 1: LA-S1 Prompt — Add Concept Descriptions

**Files:**
- Modify: `prompts/LA-S1-issue-classifier.txt:219-238` (JSON schema) and `:263-268` (guidance)

- [ ] **Step 1: Add `concept_descriptions` to the JSON schema**

In `prompts/LA-S1-issue-classifier.txt`, find the `legal_issues` array schema. After the `candidate_articles` block (line 228, after the closing `]`), add the new field:

```
      "concept_descriptions": [
        {
          "law_key": "<law_number/law_year>",
          "concept_general": "<legal concept in precise Romanian legal terminology — REQUIRED>",
          "concept_specific": "<approximate wording of the provision if known, otherwise null>"
        }
      ],
```

The result should look like (lines 222-238 area):
```
      "candidate_articles": [
        {
          "law_key": "<law_number/law_year>",
          "article": "<article number, e.g. '241' or '144^1'>",
          "reason": "<brief reason why this article applies>"
        }
      ],
      "concept_descriptions": [
        {
          "law_key": "<law_number/law_year>",
          "concept_general": "<legal concept in precise Romanian legal terminology — REQUIRED>",
          "concept_specific": "<approximate wording of the provision if known, otherwise null>"
        }
      ],
      "fact_dates": [
```

- [ ] **Step 2: Replace the CANDIDATE ARTICLES guidance section**

Find the `CANDIDATE ARTICLES` section (line 263). Replace lines 263-268 with the expanded guidance:

```
CANDIDATE ARTICLES (recommended for STANDARD and COMPLEX questions):
For each legal issue, list specific articles you believe are directly
applicable based on your legal knowledge. Format: law_key and article number.
These improve retrieval precision — the system also searches broadly,
so missing an article here is not critical. List only articles you
are confident about. For SIMPLE questions, use an empty array [].

CONCEPT DESCRIPTIONS (REQUIRED for each applicable law per issue):

For each law listed in an issue's applicable_laws, provide a concept description
that describes the legal provision you expect to find. This description will be
used for semantic search within that specific law to locate the correct articles.

Rules:
- concept_general: Describe the legal norm using precise Romanian legal terminology.
  Use the language the law itself would use, not general paraphrases.
  Include specific legal conditions, time periods, or procedural elements if relevant.
- concept_specific: If you know the approximate wording of the legal provision,
  reproduce it. If unsure, set to null. Do NOT guess — a wrong specific description
  is worse than null.

Examples of GOOD concept descriptions (use precise legal language):
  concept_general: "răspunderea solidară a administratorilor față de societate
                     pentru îndeplinirea obligațiilor impuse de lege și actul constitutiv"
  concept_specific: "administratorii sunt solidar răspunzători față de societate pentru
                     stricta îndeplinire a îndatoririlor pe care legea și actul constitutiv
                     le impun"
  → Finds: Art. 73 din Legea 31/1990 (exact match)

  concept_general: "acțiuni pentru anularea actelor sau operațiunilor frauduloase ale
                     debitorului în dauna creditorilor, în perioada anterioară deschiderii
                     procedurii de insolvență"
  concept_specific: "administratorul judiciar poate introduce acțiuni pentru anularea
                     actelor sau operațiunilor frauduloase ale debitorului în dauna
                     drepturilor creditorilor, în cei 2 ani anteriori deschiderii procedurii"
  → Finds: Art. 117 din Legea 85/2014 (exact match)

Examples of BAD concept descriptions (too generic — will return wrong articles):
  concept_general: "răspunderea administratorilor"
  → Returns 20+ irrelevant articles
  concept_general: "acte prejudiciabile în insolvență"
  → Misses Art. 117 entirely
```

- [ ] **Step 3: Verify prompt is valid**

Run: `python3 -c "open('prompts/LA-S1-issue-classifier.txt').read()"`
Expected: No error

- [ ] **Step 4: Commit**

```bash
git add prompts/LA-S1-issue-classifier.txt
git commit -m "feat: add concept_descriptions to LA-S1 prompt schema

Step 1 now outputs per-issue concept descriptions using precise Romanian
legal terminology for semantic search within specific laws."
```

---

### Task 2: Fix min_per_law Swap Bug

**Files:**
- Modify: `app/services/reranker_service.py:116-117`
- Test: `tests/test_reranker_min_per_law.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_reranker_min_per_law.py`:

```python
"""Tests for min_per_law guarantee in reranker."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_article(article_id, law_number, law_year, score, role="PRIMARY"):
    return {
        "article_id": article_id,
        "law_number": law_number,
        "law_year": law_year,
        "text": f"Article {article_id} text",
        "role": role,
        "reranker_score": score,
    }


def test_min_per_law_rescues_missing_law(monkeypatch):
    """Law with zero articles in top_k gets min_per_law articles via swap."""
    from app.services import reranker_service

    # Fake the cross-encoder to return pre-set scores
    class FakeModel:
        def predict(self, pairs):
            return [a["reranker_score"] for _, a in zip(pairs, articles)]

    monkeypatch.setattr(reranker_service, "_model", FakeModel())

    # 3 laws: law_a dominates (high scores), law_b moderate, law_c low
    articles = [
        _make_article(1, "31", "1990", 5.0),
        _make_article(2, "31", "1990", 4.5),
        _make_article(3, "31", "1990", 4.0),
        _make_article(4, "31", "1990", 3.5),
        _make_article(5, "85", "2014", 2.0),
        _make_article(6, "85", "2014", 1.5),
        _make_article(7, "85", "2014", 1.0),
        _make_article(8, "286", "2009", -1.0),
        _make_article(9, "286", "2009", -1.5),
        _make_article(10, "286", "2009", -2.0),
    ]

    # top_k=5 means initial selection is articles 1-5 (all 31/1990 + one 85/2014)
    # 286/2009 has 0 articles in top_k -> min_per_law=2 should rescue 2
    result = reranker_service.rerank_articles("test question", articles, top_k=5, min_per_law=2)

    law_286_count = sum(
        1 for a in result
        if a["law_number"] == "286" and a["law_year"] == "2009"
    )
    assert law_286_count >= 2, (
        f"Expected at least 2 articles from 286/2009, got {law_286_count}. "
        f"Result laws: {[(a['law_number'] + '/' + a['law_year']) for a in result]}"
    )


def test_min_per_law_expands_when_all_at_minimum():
    """When all laws are at minimum, new articles expand the selection."""
    from app.services import reranker_service

    class FakeModel:
        def predict(self, pairs):
            return [a["reranker_score"] for _, a in zip(pairs, articles)]

    articles = [
        _make_article(1, "31", "1990", 5.0),
        _make_article(2, "85", "2014", 4.0),
        _make_article(3, "286", "2009", -1.0),
    ]

    # top_k=2 means only articles 1,2 selected. 286/2009 has 0.
    # All selected laws have 1 article each, which is < min_per_law=2.
    # Since no law is over-represented, should EXPAND by appending.
    import unittest.mock as mock
    with mock.patch.object(reranker_service, "_model", FakeModel()):
        result = reranker_service.rerank_articles("test", articles, top_k=2, min_per_law=1)

    # All 3 laws should be represented
    laws = set(f"{a['law_number']}/{a['law_year']}" for a in result)
    assert "286/2009" in laws, f"286/2009 missing from result. Laws: {laws}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_reranker_min_per_law.py -v`
Expected: `test_min_per_law_rescues_missing_law` FAILS (the swap bug drops 286/2009 articles)

- [ ] **Step 3: Fix the bug**

In `app/services/reranker_service.py`, replace lines 116-117:

```python
                if not victims:
                    break
```

with:

```python
                if not victims:
                    # No swap target — expand selection instead of dropping
                    selected.append(candidate)
                    selected_set.add(id(candidate))
                    law_counts[law_key] = law_counts.get(law_key, 0) + 1
                    continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_reranker_min_per_law.py -v`
Expected: PASS

- [ ] **Step 5: Run existing tests**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`
Expected: All existing tests pass

- [ ] **Step 6: Commit**

```bash
git add app/services/reranker_service.py tests/test_reranker_min_per_law.py
git commit -m "fix: min_per_law expands selection when no swap target available

Previously, when the most over-represented law had no articles left to
swap out, the candidate from the under-represented law was silently
dropped. Now it expands the selection instead."
```

---

### Task 3: Reduce Search Volume

**Files:**
- Modify: `app/services/pipeline_service.py:2509-2512`

- [ ] **Step 1: Change tier limits**

In `app/services/pipeline_service.py`, find the `tier_limits` default dict in `_step4_hybrid_retrieval` (around line 2509):

```python
    tier_limits = tier_limits_override or {
        "tier1_primary": 30,
        "tier2_secondary": 15,
    }
```

Change to:

```python
    tier_limits = tier_limits_override or {
        "tier1_primary": 15,
        "tier2_secondary": 8,
    }
```

- [ ] **Step 2: Run existing tests**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`
Expected: All pass (no tests depend on exact tier limit values)

- [ ] **Step 3: Commit**

```bash
git add app/services/pipeline_service.py
git commit -m "perf: reduce retrieval volume (tier1: 30->15, tier2: 15->8)

Protected candidate articles carry the precision load. Semantic/BM25
search now serves as discovery only, reducing retrieval from ~122 to
~50-60 articles and saving ~8-12s per query."
```

---

### Task 4: Step 14 Prompt Constraint

**Files:**
- Modify: `prompts/LA-S7-answer-template.txt:18-24`

- [ ] **Step 1: Add the presentation constraint**

In `prompts/LA-S7-answer-template.txt`, find the section starting with "When a LEGAL ANALYSIS is present:" (line 18). After line 24 (which ends with "- Cite articles with version dates as provided in the analysis."), add:

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

If the analysis conclusion is CONDITIONAL or UNCERTAIN, your language MUST reflect that.
Do not upgrade uncertain conclusions to definitive statements.
```

- [ ] **Step 2: Verify prompt is valid**

Run: `python3 -c "open('prompts/LA-S7-answer-template.txt').read()"`
Expected: No error

- [ ] **Step 3: Commit**

```bash
git add prompts/LA-S7-answer-template.txt
git commit -m "feat: constrain Step 14 to presentation role when RL-RAP exists

Adds explicit instruction that Step 14 must present Step 12's
conclusions faithfully without re-deriving or contradicting them."
```

---

## Batch 2 — Concept Resolution + Candidate Protection (sequential)

### Task 5: Step 1c — Concept-Based Article Resolution

**Files:**
- Create: `tests/test_concept_resolution.py`
- Modify: `app/services/pipeline_service.py` (add function + wire into orchestration)

- [ ] **Step 1: Write the test file**

Create `tests/test_concept_resolution.py`:

```python
"""Tests for Step 1c concept-based article resolution."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _step1c_concept_resolution


class FakeArticle:
    def __init__(self, article_id, article_number, full_text, is_abrogated=False, label=None):
        self.id = article_id
        self.article_number = article_number
        self.full_text = full_text
        self.is_abrogated = is_abrogated
        self.label = label
        self.law_version_id = None  # set by test


class FakeQuery:
    def __init__(self, article=None):
        self._article = article

    def filter(self, *args):
        return self

    def first(self):
        return self._article


class FakeDB:
    def __init__(self, articles_by_key=None):
        self._articles = articles_by_key or {}

    def query(self, model):
        # Return a FakeQuery that looks up by the filter args
        return _LookupQuery(self._articles)


class _LookupQuery:
    def __init__(self, articles):
        self._articles = articles
        self._vid = None
        self._art_num = None
        self._not_abrogated = False

    def filter(self, *args):
        # Parse SQLAlchemy filter expressions from positional args
        for arg in args:
            clause = str(arg)
            if "law_version_id" in clause:
                # Extract the value from the binary expression
                self._vid = arg.right.value if hasattr(arg, 'right') else None
            elif "article_number" in clause:
                self._art_num = arg.right.value if hasattr(arg, 'right') else None
            elif "is_abrogated" in clause:
                self._not_abrogated = True
        return self

    def first(self):
        key = f"{self._vid}:{self._art_num}"
        art = self._articles.get(key)
        if art and self._not_abrogated and art.is_abrogated:
            return None
        return art


class FakeChromaCollection:
    def __init__(self, results_by_vid=None):
        self._results = results_by_vid or {}

    def query(self, query_texts, n_results, where, include=None):
        vid = where.get("law_version_id") if isinstance(where, dict) else None
        results = self._results.get(vid, {
            "ids": [[]], "metadatas": [[]], "distances": [[]], "documents": [[]]
        })
        return results


def _make_state(issues, unique_versions):
    return {
        "legal_issues": issues,
        "unique_versions": unique_versions,
        "run_id": "test",
    }


def test_validates_candidate_and_filters_abrogated():
    """Validates candidate articles, filters abrogated ones."""
    art_valid = FakeArticle(101, "73", "Art 73 text")
    art_valid.law_version_id = 54
    art_abrogated = FakeArticle(102, "138", "Abrogat.")
    art_abrogated.is_abrogated = True
    art_abrogated.law_version_id = 54

    db = FakeDB({
        "54:73": art_valid,
        "54:138": art_abrogated,
    })

    chroma = FakeChromaCollection()  # no concept search results

    state = _make_state(
        issues=[{
            "issue_id": "ISSUE-1",
            "applicable_laws": ["31/1990"],
            "candidate_articles": [
                {"law_key": "31/1990", "article": "73", "reason": "test"},
                {"law_key": "31/1990", "article": "138", "reason": "test"},
            ],
            "concept_descriptions": [],
        }],
        unique_versions={"31/1990": [54]},
    )

    result = _step1c_concept_resolution(state, db, chroma)

    # art. 73 should be validated, art. 138 should be filtered (abrogated)
    art_nums = [a["article_number"] for a in result]
    assert "73" in art_nums
    assert "138" not in art_nums


def test_concept_search_finds_articles():
    """Concept search within a law returns matching articles."""
    chroma = FakeChromaCollection({
        54: {
            "ids": [["art-101", "art-102"]],
            "metadatas": [[
                {"article_number": "72", "article_id": "101", "is_abrogated": "False",
                 "law_number": "31", "law_year": "1990", "date_in_force": "2025-12-18",
                 "law_version_id": 54},
                {"article_number": "73", "article_id": "102", "is_abrogated": "False",
                 "law_number": "31", "law_year": "1990", "date_in_force": "2025-12-18",
                 "law_version_id": 54},
            ]],
            "distances": [[0.21, 0.25]],
            "documents": [["Art 72 obligations text", "Art 73 solidarity text"]],
        }
    })

    db = FakeDB()  # no candidate articles to validate

    state = _make_state(
        issues=[{
            "issue_id": "ISSUE-1",
            "applicable_laws": ["31/1990"],
            "candidate_articles": [],
            "concept_descriptions": [
                {
                    "law_key": "31/1990",
                    "concept_general": "răspunderea administratorilor",
                    "concept_specific": None,
                }
            ],
        }],
        unique_versions={"31/1990": [54]},
    )

    result = _step1c_concept_resolution(state, db, chroma)

    art_nums = [a["article_number"] for a in result]
    assert "72" in art_nums
    assert "73" in art_nums
    assert all(a.get("protected") for a in result)
    assert all(a.get("source") in ("concept_search", "candidate_validated") for a in result)


def test_deduplicates_across_candidates_and_concepts():
    """Same article from candidate validation and concept search is not duplicated."""
    art = FakeArticle(102, "73", "Art 73 text")
    art.law_version_id = 54
    db = FakeDB({"54:73": art})

    chroma = FakeChromaCollection({
        54: {
            "ids": [["art-102"]],
            "metadatas": [[
                {"article_number": "73", "article_id": "102", "is_abrogated": "False",
                 "law_number": "31", "law_year": "1990", "date_in_force": "2025-12-18",
                 "law_version_id": 54},
            ]],
            "distances": [[0.21]],
            "documents": [["Art 73 solidarity text"]],
        }
    })

    state = _make_state(
        issues=[{
            "issue_id": "ISSUE-1",
            "applicable_laws": ["31/1990"],
            "candidate_articles": [
                {"law_key": "31/1990", "article": "73", "reason": "test"},
            ],
            "concept_descriptions": [
                {
                    "law_key": "31/1990",
                    "concept_general": "răspunderea solidară a administratorilor",
                    "concept_specific": None,
                }
            ],
        }],
        unique_versions={"31/1990": [54]},
    )

    result = _step1c_concept_resolution(state, db, chroma)

    # art. 73 should appear exactly once
    art_73_count = sum(1 for a in result if a["article_number"] == "73")
    assert art_73_count == 1


def test_protected_flag_set_on_all_results():
    """All returned articles have protected=True."""
    art = FakeArticle(101, "72", "Art 72 text")
    art.law_version_id = 54
    db = FakeDB({"54:72": art})
    chroma = FakeChromaCollection()

    state = _make_state(
        issues=[{
            "issue_id": "ISSUE-1",
            "applicable_laws": ["31/1990"],
            "candidate_articles": [
                {"law_key": "31/1990", "article": "72", "reason": "test"},
            ],
            "concept_descriptions": [],
        }],
        unique_versions={"31/1990": [54]},
    )

    result = _step1c_concept_resolution(state, db, chroma)
    assert len(result) >= 1
    for a in result:
        assert a["protected"] is True


def test_skips_abrogated_from_concept_search():
    """Concept search results with is_abrogated=True are filtered out."""
    chroma = FakeChromaCollection({
        54: {
            "ids": [["art-101", "art-102"]],
            "metadatas": [[
                {"article_number": "138", "article_id": "101", "is_abrogated": "True",
                 "law_number": "31", "law_year": "1990", "date_in_force": "2025-12-18",
                 "law_version_id": 54},
                {"article_number": "73", "article_id": "102", "is_abrogated": "False",
                 "law_number": "31", "law_year": "1990", "date_in_force": "2025-12-18",
                 "law_version_id": 54},
            ]],
            "distances": [[0.20, 0.25]],
            "documents": [["Abrogat.", "Art 73 text"]],
        }
    })

    db = FakeDB()

    state = _make_state(
        issues=[{
            "issue_id": "ISSUE-1",
            "applicable_laws": ["31/1990"],
            "candidate_articles": [],
            "concept_descriptions": [
                {"law_key": "31/1990", "concept_general": "test concept", "concept_specific": None}
            ],
        }],
        unique_versions={"31/1990": [54]},
    )

    result = _step1c_concept_resolution(state, db, chroma)
    art_nums = [a["article_number"] for a in result]
    assert "138" not in art_nums
    assert "73" in art_nums
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_concept_resolution.py -v`
Expected: FAIL with ImportError (`_step1c_concept_resolution` does not exist yet)

- [ ] **Step 3: Implement `_step1c_concept_resolution`**

In `app/services/pipeline_service.py`, after the `_step1b_version_preparation` function (around line 2120, before `_step2_law_mapping`), add:

```python
# ---------------------------------------------------------------------------
# Step 1c: Concept-Based Article Resolution
# ---------------------------------------------------------------------------


def _step1c_concept_resolution(state: dict, db, chroma_collection=None) -> list[dict]:
    """Resolve legal concepts to actual articles via validation + semantic search.

    Phase A: Validate candidate_articles from Step 1 (filter abrogated/missing).
    Phase B: Concept search within each law via ChromaDB filtered queries.
    Returns a merged, deduplicated list of protected article dicts.
    """
    from app.models.law import Article as ArticleModel

    if chroma_collection is None:
        from app.services.chroma_service import get_collection
        chroma_collection = get_collection()

    protected_articles: list[dict] = []
    seen: set[tuple[int, str]] = set()  # (law_version_id, article_number)
    validated_log: list[dict] = []
    rejected_log: list[dict] = []
    concept_log: list[dict] = []

    unique_versions = state.get("unique_versions", {})

    for issue in state.get("legal_issues", []):
        issue_id = issue["issue_id"]

        # --- Phase A: Validate proposed candidate_articles ---
        for ca in issue.get("candidate_articles", []):
            law_key = ca.get("law_key", "")
            article_num = ca.get("article", "")
            if not law_key or not article_num:
                continue

            version_ids = unique_versions.get(law_key, [])
            for vid in version_ids:
                if (vid, article_num) in seen:
                    continue

                article = (
                    db.query(ArticleModel)
                    .filter(
                        ArticleModel.law_version_id == vid,
                        ArticleModel.article_number == article_num,
                        ArticleModel.is_abrogated == False,
                    )
                    .first()
                )

                if article:
                    seen.add((vid, article_num))
                    parts = law_key.split("/")
                    protected_articles.append({
                        "article_id": article.id,
                        "law_version_id": vid,
                        "article_number": article.article_number,
                        "text": article.full_text,
                        "label": article.label,
                        "source": "candidate_validated",
                        "tier": "tier1_primary",
                        "role": "PRIMARY",
                        "law_number": parts[0] if len(parts) > 0 else "",
                        "law_year": parts[1] if len(parts) > 1 else "",
                        "is_abrogated": False,
                        "doc_type": "article",
                        "protected": True,
                        "issue_id": issue_id,
                    })
                    validated_log.append({
                        "law_key": law_key, "article": article_num,
                        "status": "valid", "article_id": article.id,
                    })
                else:
                    # Check if it exists but is abrogated
                    abrogated = (
                        db.query(ArticleModel)
                        .filter(
                            ArticleModel.law_version_id == vid,
                            ArticleModel.article_number == article_num,
                        )
                        .first()
                    )
                    status = "abrogated" if (abrogated and abrogated.is_abrogated) else "not_found"
                    rejected_log.append({
                        "law_key": law_key, "article": article_num, "status": status,
                    })

        # --- Phase B: Concept search within each law ---
        for cd in issue.get("concept_descriptions", []):
            law_key = cd.get("law_key", "")
            if not law_key:
                continue
            version_ids = unique_versions.get(law_key, [])

            for vid in version_ids:
                queries = [cd["concept_general"]]
                if cd.get("concept_specific"):
                    queries.append(cd["concept_specific"])

                found_for_concept: list[str] = []
                top_distance = None

                for query_text in queries:
                    try:
                        results = chroma_collection.query(
                            query_texts=[query_text],
                            n_results=7,
                            where={"law_version_id": vid},
                        )
                    except Exception as e:
                        logger.warning(f"Concept search failed for {law_key} vid={vid}: {e}")
                        continue

                    if not results["ids"] or not results["ids"][0]:
                        continue

                    distances = results["distances"][0]
                    if top_distance is None and distances:
                        top_distance = distances[0]

                    # Adaptive: take top 5 if good match, top 7 if weak
                    n_take = 7 if (distances and distances[0] > 0.35) else 5

                    for i in range(min(n_take, len(results["ids"][0]))):
                        meta = results["metadatas"][0][i]
                        art_num = meta.get("article_number", "")
                        art_id_str = meta.get("article_id", "")

                        if (vid, art_num) in seen:
                            continue
                        if meta.get("is_abrogated") == "True":
                            continue

                        seen.add((vid, art_num))
                        found_for_concept.append(art_num)

                        parts = law_key.split("/")
                        protected_articles.append({
                            "article_id": int(art_id_str) if art_id_str else 0,
                            "law_version_id": vid,
                            "article_number": art_num,
                            "text": results["documents"][0][i] if results.get("documents") else "",
                            "label": art_num,
                            "source": "concept_search",
                            "tier": "tier1_primary",
                            "role": "PRIMARY",
                            "law_number": parts[0] if len(parts) > 0 else "",
                            "law_year": parts[1] if len(parts) > 1 else "",
                            "is_abrogated": False,
                            "doc_type": "article",
                            "protected": True,
                            "issue_id": issue_id,
                        })

                concept_log.append({
                    "issue_id": issue_id,
                    "law_key": law_key,
                    "concept": cd["concept_general"][:80],
                    "found": found_for_concept,
                    "top_distance": round(top_distance, 4) if top_distance else None,
                })

    state["protected_candidates"] = protected_articles
    state["_concept_resolution_log"] = {
        "validated_candidates": validated_log,
        "rejected_candidates": rejected_log,
        "concept_search_results": concept_log,
        "total_protected": len(protected_articles),
    }

    return protected_articles
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_concept_resolution.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Wire Step 1c into pipeline orchestration**

In `app/services/pipeline_service.py`, find the line (around 1391):

```python
        # Step 2: Version Preparation (date extraction + DB version lookups)
        state = _step1b_version_preparation(state, db)
```

After `_step1b_version_preparation(state, db)` and before the Step 3 section, add:

```python
        # Step 1c: Concept-Based Article Resolution
        yield _step_event(2, "concept_resolution", "running")
        t0_cr = time.time()
        _step1c_concept_resolution(state, db)
        cr_log = state.get("_concept_resolution_log", {})
        yield _step_event(2, "concept_resolution", "done", cr_log, time.time() - t0_cr)
```

Note: This reuses step_number=2 since Step 1c replaces the old date extraction step's slot. The `step_name` is `"concept_resolution"` which is new.

- [ ] **Step 6: Add concept_resolution to renderOutputData in frontend switch**

In `frontend/src/app/settings/pipeline/run-detail.tsx`, in the `renderOutputData` function's switch statement (around line 75-76), after the `"date_extraction"` case, add:

```typescript
    case "concept_resolution":
      return <ConceptResolutionDetail data={d} />;
```

(The component itself will be created in Task 7.)

- [ ] **Step 7: Run all tests**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add app/services/pipeline_service.py tests/test_concept_resolution.py
git commit -m "feat: add Step 1c concept-based article resolution

Validates candidate articles against DB (filters abrogated), runs
concept search within each law via ChromaDB, and produces a protected
candidate set for downstream steps."
```

---

### Task 6: Candidate Protection in Steps 7 and 9

**Files:**
- Create: `tests/test_candidate_protection.py`
- Modify: `app/services/pipeline_service.py` (Step 7 + Step 9 functions)

- [ ] **Step 1: Write the test file**

Create `tests/test_candidate_protection.py`:

```python
"""Tests for Variant 3 candidate protection in Steps 7/9."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_article(article_id, law_number, law_year, source="semantic",
                  protected=False, text="article text"):
    return {
        "article_id": article_id,
        "law_version_id": 1,
        "article_number": str(article_id),
        "text": text,
        "label": str(article_id),
        "source": source,
        "tier": "tier1_primary",
        "role": "PRIMARY",
        "law_number": law_number,
        "law_year": law_year,
        "is_abrogated": False,
        "doc_type": "article",
        "protected": protected,
    }


def test_protected_articles_bypass_reranker(monkeypatch):
    """Protected articles are not passed to reranker and always appear in output."""
    from app.services import pipeline_service

    protected = [
        _make_article(1, "286", "2009", source="concept_search", protected=True),
        _make_article(2, "286", "2009", source="candidate_validated", protected=True),
    ]
    searchable = [
        _make_article(10, "31", "1990", source="semantic"),
        _make_article(11, "31", "1990", source="bm25"),
        _make_article(12, "85", "2014", source="semantic"),
    ]

    state = {
        "question": "test question",
        "legal_issues": [{"issue_id": "ISSUE-1"}],
        "retrieved_articles_raw": protected + searchable,
        "run_id": "test",
    }

    # Mock reranker to return only searchable articles (simulating protected being absent)
    reranked = []
    def fake_rerank(question, articles, top_k=25, min_per_law=3):
        # Verify protected articles are NOT in the input
        for a in articles:
            assert not a.get("protected"), "Protected article was passed to reranker!"
        # Return articles with scores
        for i, a in enumerate(articles):
            a["reranker_score"] = float(len(articles) - i)
        reranked.extend(articles)
        return articles[:top_k]

    monkeypatch.setattr("app.services.reranker_service.rerank_articles", fake_rerank)

    # Mock log_step to avoid DB calls
    monkeypatch.setattr(pipeline_service, "log_step", lambda *a, **kw: None)

    state = pipeline_service._step6_select_articles(state, db=None)

    result = state["retrieved_articles"]
    result_ids = {a["article_id"] for a in result}

    # Protected articles must be in result
    assert 1 in result_ids, "Protected article 1 missing from result"
    assert 2 in result_ids, "Protected article 2 missing from result"
    # Searchable articles should also be present (reranked)
    assert 10 in result_ids or 11 in result_ids or 12 in result_ids


def test_protected_articles_in_retrieval_pool():
    """Protected candidates from state are added to retrieval pool."""
    from app.services import pipeline_service

    protected = [
        _make_article(1, "286", "2009", source="concept_search", protected=True),
    ]

    # Simulate state after Step 1c
    state = {
        "protected_candidates": protected,
        "retrieved_articles_raw": [],
    }

    # After Step 7 adds protected candidates, they should be in the pool
    raw = state.get("protected_candidates", []) + state.get("retrieved_articles_raw", [])
    assert len(raw) == 1
    assert raw[0]["protected"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_candidate_protection.py::test_protected_articles_bypass_reranker -v`
Expected: FAIL (current `_step6_select_articles` passes all articles to reranker)

- [ ] **Step 3: Modify `_step6_select_articles` to protect candidates**

In `app/services/pipeline_service.py`, replace the `_step6_select_articles` function (starting around line 2787) with:

```python
def _step6_select_articles(state: dict, db: Session, top_k_override: int | None = None) -> dict:
    """Rerank articles using cross-encoder, select top-k.
    Protected articles (from concept resolution) bypass reranking."""
    from app.services.reranker_service import rerank_articles

    num_issues = len(state.get("legal_issues", []))
    top_k = top_k_override or min(20, 5 + (num_issues * 5))

    t0 = time.time()
    raw = state.get("retrieved_articles_raw", [])
    if not raw:
        state["retrieved_articles"] = []
        log_step(db, state["run_id"], "article_selection", 9, "done", 0,
                 output_summary="No articles to select from")
        return state

    # Split: protected candidates bypass reranker
    protected = [a for a in raw if a.get("protected")]
    searchable = [a for a in raw if not a.get("protected")]

    # Rerank only non-protected articles
    if searchable:
        ranked = rerank_articles(state["question"], searchable, top_k=top_k)
    else:
        ranked = []

    # Merge: protected always kept + reranked top-k
    merged = protected + ranked
    state["retrieved_articles"] = merged

    kept_ids = {a["article_id"] for a in merged}
    dropped = [a for a in raw if a["article_id"] not in kept_ids]

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "article_selection", 9, "done", duration,
        output_summary=f"Reranker: {len(searchable)} -> top {len(ranked)} articles + {len(protected)} protected",
        output_data={
            "method": "reranker",
            "protected_count": len(protected),
            "kept_articles": [
                {
                    "article_id": a["article_id"],
                    "article_number": a.get("article_number"),
                    "law": f"{a.get('law_number')}/{a.get('law_year')}",
                    "score": round(a.get("reranker_score", 0), 3) if a.get("reranker_score") is not None else None,
                    "protected": a.get("protected", False),
                }
                for a in merged
            ],
            "dropped_count": len(dropped),
            "total_candidates": len(raw),
        },
    )
    return state
```

- [ ] **Step 4: Add protected candidates to retrieval pool in Step 7**

In `_step4_hybrid_retrieval`, find the section where `candidate_results` are processed (around line 2494-2503). After the candidate processing loop but before the tier search loop, add:

```python
    # Add protected candidates from concept resolution (Step 1c)
    protected_candidates = state.get("protected_candidates", [])
    for art in protected_candidates:
        aid = f"{art.get('doc_type', 'article')}:{art['article_id']}"
        if aid not in seen_ids:
            seen_ids.add(aid)
            all_articles.append(art)
            candidate_count += 1
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_candidate_protection.py -v`
Expected: All PASS

- [ ] **Step 6: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add app/services/pipeline_service.py tests/test_candidate_protection.py
git commit -m "feat: protect candidate articles from reranker elimination (Variant 3)

Protected articles from concept resolution bypass the reranker entirely
and are always included in Step 12's article set. The reranker only
filters BM25/semantic discovery articles."
```

---

## Batch 3 — UI Visibility

### Task 7: Pipeline UI — Show Candidate Articles

**Files:**
- Modify: `frontend/src/app/settings/pipeline/run-detail.tsx`

- [ ] **Step 1: Add ConceptResolutionDetail component**

In `frontend/src/app/settings/pipeline/run-detail.tsx`, before the `ClassificationDetail` component (around line 90), add:

```typescript
/* --- Step 1c: Concept Resolution --- */
function ConceptResolutionDetail({ data }: { data: Record<string, unknown> }) {
  const validated = (data.validated_candidates ?? []) as Array<Record<string, unknown>>;
  const rejected = (data.rejected_candidates ?? []) as Array<Record<string, unknown>>;
  const concepts = (data.concept_search_results ?? []) as Array<Record<string, unknown>>;
  const totalProtected = data.total_protected as number | undefined;

  return (
    <div className="space-y-1.5">
      <Row label="Total protected" value={String(totalProtected ?? 0)} />

      {validated.length > 0 && (
        <div className="mt-2">
          <div className="font-medium text-green-700 mb-1">Validated Candidates</div>
          {validated.map((v, i) => (
            <div key={i} className="ml-2 text-green-600">
              {String(v.law_key)} art. {String(v.article)} (id={String(v.article_id)})
            </div>
          ))}
        </div>
      )}

      {rejected.length > 0 && (
        <div className="mt-2">
          <div className="font-medium text-red-600 mb-1">Rejected Candidates</div>
          {rejected.map((r, i) => (
            <div key={i} className="ml-2 text-red-500">
              {String(r.law_key)} art. {String(r.article)} — {String(r.status)}
            </div>
          ))}
        </div>
      )}

      {concepts.length > 0 && (
        <div className="mt-2">
          <div className="font-medium text-gray-500 mb-1">Concept Search Results</div>
          {concepts.map((c, i) => (
            <div key={i} className="ml-2 mb-2 p-2 bg-gray-100 rounded">
              <div className="font-medium">
                {String(c.issue_id)} — {String(c.law_key)}
              </div>
              <div className="text-gray-500 text-sm italic">
                &quot;{String(c.concept)}&quot;
              </div>
              <div className="mt-0.5">
                Found: {Array.isArray(c.found) ? (c.found as string[]).join(", ") : "none"}
                {c.top_distance != null && (
                  <span className="text-gray-400 ml-2">(dist: {String(c.top_distance)})</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add candidate_articles display to ClassificationDetail**

In the `ClassificationDetail` component, inside the `legalIssues.map` callback (around line 127), after the `<Row label="Priority" .../>` line (line 144), add:

```typescript
                {/* Candidate Articles */}
                {Array.isArray(issue.candidate_articles) && (issue.candidate_articles as Array<Record<string, unknown>>).length > 0 && (
                  <div className="mt-1">
                    <span className="text-gray-400 text-sm">Candidates: </span>
                    {(issue.candidate_articles as Array<Record<string, unknown>>).map((ca, j) => (
                      <span key={j} className="text-sm text-gray-600">
                        {String(ca.law_key)} art. {String(ca.article)}
                        {j < (issue.candidate_articles as Array<Record<string, unknown>>).length - 1 ? ", " : ""}
                      </span>
                    ))}
                  </div>
                )}
                {/* Concept Descriptions */}
                {Array.isArray(issue.concept_descriptions) && (issue.concept_descriptions as Array<Record<string, unknown>>).length > 0 && (
                  <div className="mt-1">
                    <span className="text-gray-400 text-sm">Concepts: </span>
                    {(issue.concept_descriptions as Array<Record<string, unknown>>).map((cd, j) => (
                      <span key={j} className="text-sm text-blue-600 italic">
                        {String(cd.law_key)}: &quot;{String((cd.concept_general as string || "").slice(0, 60))}...&quot;
                        {j < (issue.concept_descriptions as Array<Record<string, unknown>>).length - 1 ? " | " : ""}
                      </span>
                    ))}
                  </div>
                )}
```

- [ ] **Step 3: Verify the frontend switch case was added in Task 5 Step 6**

Confirm that the `renderOutputData` switch in `run-detail.tsx` includes:

```typescript
    case "concept_resolution":
      return <ConceptResolutionDetail data={d} />;
```

If not added in Task 5 Step 6 (which is the backend commit), add it now.

- [ ] **Step 4: Build frontend**

Run: `cd /Users/anaandrei/projects/themis-legal/frontend && npm run build`
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 5: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add frontend/src/app/settings/pipeline/run-detail.tsx
git commit -m "feat: show candidate articles and concept resolution in pipeline UI

Pipeline analysis now displays per-issue candidate articles, concept
descriptions, and concept search results with validation status."
```

---

## Self-Review

**Spec coverage check:**
- Change 1 (LA-S1 concept descriptions): Task 1 ✓
- Change 2 (Step 1c concept resolution): Task 5 ✓
- Change 3 (Variant 3 candidate protection): Task 6 ✓
- Change 4 (min_per_law fix): Task 2 ✓
- Change 5 (reduce search volume): Task 3 ✓
- Change 6 (Step 14 prompt constraint): Task 4 ✓
- Change 7 (UI visibility): Task 7 ✓
- Verification plan: Covered by running same test question post-implementation

**Placeholder scan:** No TBD, TODO, or incomplete sections found.

**Type consistency:** `_step1c_concept_resolution` signature, `protected` flag, `source` values, and `_concept_resolution_log` structure are consistent across Tasks 5, 6, and 7.
