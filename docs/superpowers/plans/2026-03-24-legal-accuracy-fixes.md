# Legal Accuracy Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 14 identified risks where Themis L&C could misrepresent Romanian law, apply wrong versions, miss exceptions, or give users false confidence.

**Architecture:** All fixes modify existing backend pipeline code (`pipeline_service.py`, services, models) and frontend display components. No new services or architectural changes. The pipeline stays 7 steps; we add a date extraction substep (1b), expand existing steps, and improve data quality.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, SQLite, ChromaDB, sentence-transformers, Next.js (TypeScript), Tailwind CSS.

**Spec:** `docs/superpowers/specs/2026-03-24-legal-accuracy-fixes-design.md`

**Note on testing:** This project has no test suite. Steps labeled "Verify" describe manual verification via the running app or Python REPL rather than automated tests. Each task ends with a commit.

---

## Task 1: C1 — Restore date extraction in the pipeline

**Files:**
- Modify: `backend/app/services/pipeline_service.py:422-476` (Step 1 function + new Step 1b)
- Modify: `backend/app/services/pipeline_service.py:89-124` (pipeline entry — wire Step 1b)

- [ ] **Step 1: Add `_step1b_date_extraction` function**

Add after `_step1_issue_classification` (after line 476 in `pipeline_service.py`):

```python
def _step1b_date_extraction(state: dict, db: Session) -> dict:
    """Extract temporal context from the question using Claude."""
    prompt_text, prompt_ver = load_prompt("LA-S2", db)

    user_msg = (
        f"Today's date: {state['today']}\n\n"
        f"QUESTION: {state['question']}"
    )

    result = call_claude(
        system=prompt_text,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=512,
    )

    log_api_call(
        db, state["run_id"], "date_extraction",
        result["tokens_in"], result["tokens_out"], result["duration"], result["model"],
    )

    parsed = _extract_json(result["content"])

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
        # Fallback: keep today's date (already set in Step 1)
        state["flags"].append("No specific date detected — using current law versions")

    log_step(
        db, state["run_id"], "date_extraction", 15, "done",
        result["duration"],
        prompt_id="LA-S2", prompt_version=prompt_ver,
        input_summary=state["question"][:200],
        output_summary=f"primary_date={state.get('primary_date')}",
        output_data=parsed,
    )

    return state
```

- [ ] **Step 2: Wire Step 1b into the pipeline**

In `run_pipeline()`, after the Step 1 yield block (around line 124), add:

```python
        # Step 1b: Date Extraction (Claude)
        yield _step_event(15, "date_extraction", "running")
        t0 = time.time()
        state = _step1b_date_extraction(state, db)
        yield _step_event(15, "date_extraction", "done", {
            "primary_date": state.get("primary_date"),
        }, time.time() - t0)
```

- [ ] **Step 3: Remove the hardcoded date line**

In `_step1_issue_classification` (line 466), change:

```python
    # Use today as the primary date (date extraction removed as separate step)
    state["primary_date"] = state["today"]
```

to:

```python
    # Default to today — will be overridden by Step 1b date extraction
    state["primary_date"] = state["today"]
```

- [ ] **Step 4: Verify**

Start the backend, send a question like "Ce prevedea Legea 31/1990 in 2018 despre capitalul social minim?" — check the pipeline logs to confirm Step 1b runs and `primary_date` is set to a 2018 date, and Step 3 selects a 2018 version.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat(C1): restore date extraction in pipeline via Step 1b"
```

---

## Task 2: C3 — Expand domain-to-law mapping and handle unknown domains

**Files:**
- Modify: `backend/app/services/law_mapping.py:11-78` (add domain entries)
- Modify: `backend/app/services/pipeline_service.py:487-550` (Step 2 — secondary domain merge)

- [ ] **Step 1: Add missing domain entries to `DOMAIN_LAW_MAP`**

In `law_mapping.py`, add these entries to the `DOMAIN_LAW_MAP` dict after the `criminal_procedure` entry:

```python
    "real_estate": {
        "primary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — property rights (Book III)"},
        ],
        "secondary": [
            {"law_number": "7", "law_year": 1996, "reason": "Legea cadastrului și publicității imobiliare"},
        ],
        "connected": [],
    },
    "data_protection": {
        "primary": [
            {"law_number": "190", "law_year": 2018, "reason": "Legea privind protecția datelor personale (GDPR)"},
        ],
        "secondary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — privacy rights"},
        ],
        "connected": [],
    },
    "procedural": {
        "primary": [
            {"law_number": "134", "law_year": 2010, "reason": "Codul de Procedură Civilă"},
        ],
        "secondary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — applies subsidiarily"},
        ],
        "connected": [],
    },
    "eu_law": {
        "primary": [],
        "secondary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — general framework"},
        ],
        "connected": [],
    },
    "other": {
        "primary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — general gap-filler"},
        ],
        "secondary": [],
        "connected": [],
    },
```

- [ ] **Step 2: Add secondary domain support in Step 2**

In `_step2_law_mapping` in `pipeline_service.py`, after the primary mapping call, add secondary domain merge:

```python
    # If classifier returned a secondary domain, merge its laws too
    secondary_domain = state.get("secondary_domain")
    if secondary_domain and secondary_domain != state.get("legal_domain"):
        secondary_mapping = map_laws_to_question(secondary_domain, db)
        # Merge into primary mapping, deduplicating by (law_number, law_year)
        existing_keys = set()
        for tier_laws in mapping.values():
            for law in tier_laws:
                existing_keys.add((law["law_number"], law["law_year"]))

        # map_laws_to_question returns keys: tier1_primary, tier2_secondary, tier3_connected
        for tier_key in ["tier1_primary", "tier2_secondary", "tier3_connected"]:
            for law in secondary_mapping.get(tier_key, []):
                if (law["law_number"], law["law_year"]) not in existing_keys:
                    # Demote secondary domain's primary laws to our secondary tier
                    target_tier = "tier2_secondary" if tier_key == "tier1_primary" else tier_key
                    mapping.setdefault(target_tier, []).append(law)
                    existing_keys.add((law["law_number"], law["law_year"]))
```

- [ ] **Step 3: Read `secondary_domain` from Step 1 classification output**

In `_step1_issue_classification`, after line 463 (after the `entity_types` assignment), add:

```python
    state["secondary_domain"] = parsed.get("secondary_domain")
```

- [ ] **Step 4: Update LA-S1 prompt to output `secondary_domain`**

In `backend/prompts/LA-S1-issue-classifier.txt`, add `secondary_domain` to the output JSON format instruction. In the JSON schema section, add:

```
"secondary_domain": "string or null — if the question spans two legal domains, specify the secondary one here (same values as legal_domain). null if the question fits a single domain."
```

- [ ] **Step 5: Verify**

Test with a real estate question — confirm retrieval is no longer empty. Test with domain "other" — confirm Civil Code is used as fallback.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/law_mapping.py backend/app/services/pipeline_service.py \
    backend/prompts/LA-S1-issue-classifier.txt
git commit -m "feat(C3): add missing domain mappings and secondary domain support"
```

---

## Task 3: C4 — Remove reranker 512-char truncation

**Files:**
- Modify: `backend/app/services/reranker_service.py:41`

- [ ] **Step 1: Remove the truncation**

Change line 41 from:

```python
    pairs = [(question, art["text"][:512]) for art in articles]
```

to:

```python
    pairs = [(question, art["text"]) for art in articles]
```

- [ ] **Step 2: Verify**

The reranker is a fallback path — it runs when Claude article selection fails. To test: temporarily make Step 6 Claude call fail (e.g., wrong prompt ID), run a query, confirm reranker fallback works without errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/reranker_service.py
git commit -m "fix(C4): remove 512-char truncation from reranker — let tokenizer handle limits"
```

---

## Task 4: H0 — Increase Step 6 article preview from 500 to 1500 chars

**Files:**
- Modify: `backend/app/services/pipeline_service.py:1129`

- [ ] **Step 1: Increase preview and add truncation indicator**

Change lines 1128-1134 from:

```python
    for art in raw:
        text_preview = art.get("text", "")[:500]
        summary = (
            f"[ID:{art['article_id']}] Art. {art.get('article_number', '?')}, "
            f"Legea {art.get('law_number', '?')}/{art.get('law_year', '?')} — "
            f"{text_preview}"
        )
```

to:

```python
    for art in raw:
        full_text = art.get("text", "")
        text_preview = full_text[:1500]
        if len(full_text) > 1500:
            text_preview += f" [...truncated, full text: {len(full_text)} chars]"
        summary = (
            f"[ID:{art['article_id']}] Art. {art.get('article_number', '?')}, "
            f"Legea {art.get('law_number', '?')}/{art.get('law_year', '?')} — "
            f"{text_preview}"
        )
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "fix(H0): increase Step 6 article preview to 1500 chars with truncation indicator"
```

---

## Task 5: H1 — Flag abrogated articles

**Files:**
- Modify: `backend/app/models/law.py:123-147` (Article model — add `is_abrogated`)
- Modify: `backend/app/services/leropa_service.py` (detect abrogation on import)
- Modify: `backend/app/services/chroma_service.py:79-89` (add `is_abrogated` to ChromaDB metadata)
- Modify: `backend/app/services/pipeline_service.py:1128-1134` (Step 6 — prefix abrogated articles)
- Create: `backend/scripts/backfill_abrogated.py` (one-time migration)

- [ ] **Step 1: Add `is_abrogated` field to Article model**

In `backend/app/models/law.py`, add to the `Article` class after line 136 (`order_index`):

```python
    is_abrogated: Mapped[bool] = mapped_column(Boolean, default=False)
```

- [ ] **Step 2: Run the SQLite migration**

```bash
cd /Users/anaandrei/projects/legalese/backend
python -c "
import sqlite3
conn = sqlite3.connect('data/themis.db')
conn.execute('ALTER TABLE articles ADD COLUMN is_abrogated BOOLEAN DEFAULT 0')
conn.commit()
conn.close()
print('Migration done')
"
```

- [ ] **Step 3: Create backfill script**

Create `backend/scripts/backfill_abrogated.py`:

```python
"""One-time backfill: scan article full_text for abrogation patterns."""
import re
import sqlite3

ABROGATION_PATTERNS = [
    r"^\s*\(?\s*[Aa]brogat",
    r"^\s*\(?\s*[Aa]brogat[ăa]\)",
    r"^\s*[Aa]rt\.\s*\d+.*[Aa]brogat",
]

def backfill(db_path: str = "data/themis.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, full_text FROM articles")
    updated = 0
    for art_id, text in cursor.fetchall():
        if not text:
            continue
        for pattern in ABROGATION_PATTERNS:
            if re.search(pattern, text[:200]):
                cursor.execute(
                    "UPDATE articles SET is_abrogated = 1 WHERE id = ?", (art_id,)
                )
                updated += 1
                break
    conn.commit()
    conn.close()
    print(f"Marked {updated} articles as abrogated")

if __name__ == "__main__":
    backfill()
```

- [ ] **Step 4: Run the backfill**

```bash
cd /Users/anaandrei/projects/legalese/backend
python scripts/backfill_abrogated.py
```

- [ ] **Step 5: Detect abrogation on import**

In `backend/app/services/leropa_service.py`, in the function that creates Article records (around lines 446-453 where `Article(...)` is constructed), add abrogation detection. Add `import re` at the top of the file if not already present. Then change the Article construction:

```python
    full_text = art_data.get("full_text", "")
    is_abrogated = bool(re.search(r"^\s*\(?\s*[Aa]brogat", full_text[:200]))

    article = Article(
        law_version_id=version.id,
        structural_element_id=parent.id if parent else None,
        article_number=art_data.get("label", "?"),
        label=art_data.get("label"),
        full_text=full_text,
        order_index=order_index,
        is_abrogated=is_abrogated,
    )
```

Note: the function parameter is `version: LawVersion`, so use `version.id` (matching the existing code).

- [ ] **Step 6: Add `is_abrogated` to ChromaDB metadata**

In `backend/app/services/chroma_service.py`, in `index_law_version()` (line 79-89 metadata dict), add:

```python
            "is_abrogated": str(getattr(article, 'is_abrogated', False)),
```

- [ ] **Step 7: Mark abrogated articles in Step 6 summaries**

In `_step6_select_articles` (around line 1129), update the summary building:

```python
    for art in raw:
        full_text = art.get("text", "")
        text_preview = full_text[:1500]
        if len(full_text) > 1500:
            text_preview += f" [...truncated, full text: {len(full_text)} chars]"
        abrogated_prefix = "[ABROGATED] " if art.get("is_abrogated") else ""
        summary = (
            f"{abrogated_prefix}[ID:{art['article_id']}] Art. {art.get('article_number', '?')}, "
            f"Legea {art.get('law_number', '?')}/{art.get('law_year', '?')} — "
            f"{text_preview}"
        )
```

- [ ] **Step 8: Pass `is_abrogated` through retrieval results**

In `bm25_service.py`, in the `search_bm25` result building (around line 183-194), add to the result dict:

```python
            "is_abrogated": getattr(art, 'is_abrogated', False),
```

In `chroma_service.py`, in `query_articles` result building (around line 167-177), add:

```python
                "is_abrogated": meta.get("is_abrogated", "False") == "True",
```

- [ ] **Step 9: Mark abrogated articles in Step 7 context**

In `_step7_answer_generation` (around line 1497-1507), update the article context building:

```python
        for i, art in enumerate(retrieved, 1):
            abrogated_tag = " [ABROGATED — this article has been repealed]" if art.get("is_abrogated") else ""
            articles_context += (
                f"[Article {i}]{abrogated_tag} {art.get('law_title', '')} "
```

- [ ] **Step 10: Verify**

Check the database for abrogated articles: `SELECT COUNT(*) FROM articles WHERE is_abrogated = 1`. Run a query that involves a law with known abrogated articles — confirm they're marked `[ABROGATED]` in the pipeline log.

- [ ] **Step 11: Commit**

```bash
git add backend/app/models/law.py backend/app/services/leropa_service.py \
    backend/app/services/chroma_service.py backend/app/services/bm25_service.py \
    backend/app/services/pipeline_service.py backend/scripts/backfill_abrogated.py
git commit -m "feat(H1): flag abrogated articles in model, retrieval, and pipeline context"
```

---

## Task 6: H2 — Remove amendment notes from search indexes

**Files:**
- Modify: `backend/app/services/chroma_service.py:67-78` (remove amendment concatenation from indexing)
- Modify: `backend/app/services/bm25_service.py:57-68` (remove amendment concatenation from FTS index)

**Prerequisite verified:** `full_text` in the database IS the consolidated text from legislatie.just.ro (see `leropa_service.py:451`). Amendment notes are supplementary metadata, not the operative text. Safe to remove from indexes.

- [ ] **Step 1: Remove amendment concatenation from ChromaDB indexing**

In `chroma_service.py`, replace lines 67-78:

```python
        # Build searchable text: article text + amendment notes
        # Amendment notes often contain critical information (e.g., new minimum
        # capital requirements) that isn't in the article text itself.
        text_parts = [article.full_text]
        if article.amendment_notes:
            for note in article.amendment_notes:
                if note.text and note.text.strip():
                    text_parts.append(f"[Amendment: {note.text.strip()}]")

        doc_id = f"art-{article.id}"
        ids.append(doc_id)
        documents.append("\n".join(text_parts))
```

with:

```python
        # Index only the consolidated article text — amendment metadata
        # is stored in DB metadata fields, not in the searchable document.
        # This prevents amendment notes from polluting semantic search results.
        doc_id = f"art-{article.id}"
        ids.append(doc_id)
        documents.append(article.full_text)
```

- [ ] **Step 2: Add amendment metadata to ChromaDB metadata fields**

In the metadatas dict (around line 79-89), add:

```python
            "amendment_count": str(len(article.amendment_notes)) if article.amendment_notes else "0",
```

- [ ] **Step 3: Remove amendment concatenation from BM25 FTS index**

In `bm25_service.py`, in `ensure_fts_index()` (lines 57-68), replace:

```python
    # Also fetch amendment notes
    cursor.execute("SELECT article_id, text FROM amendment_notes")
    notes_by_article = {}
    for article_id, text in cursor.fetchall():
        if text:
            notes_by_article.setdefault(article_id, []).append(text)

    for art_id, full_text, law_version_id in articles:
        parts = [full_text or ""]
        for note_text in notes_by_article.get(art_id, []):
            parts.append(note_text)
        combined = " ".join(parts)
```

with:

```python
    for art_id, full_text, law_version_id in articles:
        combined = full_text or ""
```

- [ ] **Step 4: Re-index both ChromaDB and BM25**

```bash
cd /Users/anaandrei/projects/legalese/backend
python -c "
from app.database import SessionLocal
from app.services.chroma_service import index_all
from app.services.bm25_service import rebuild_fts_index

db = SessionLocal()
print('Re-indexing ChromaDB...')
count = index_all(db)
print(f'ChromaDB: {count} articles indexed')
print('Rebuilding BM25 FTS index...')
rebuild_fts_index(db)
print('Done')
db.close()
"
```

- [ ] **Step 5: Verify**

Run a test query and confirm retrieval still works. Check that searching for a specific amending law number no longer pulls in the amended article (unless the article text itself mentions that law).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/chroma_service.py backend/app/services/bm25_service.py
git commit -m "fix(H2): remove amendment notes from search indexes — index only consolidated text"
```

---

## Task 7: C2 — Cross-law cross-reference resolution

**Files:**
- Modify: `backend/app/services/article_expander.py:75-101` (add cross-law resolution)
- Modify: `backend/app/services/legal_aliases.py:13-145` (add code abbreviations)

- [ ] **Step 1: Add code abbreviation aliases to `legal_aliases.py`**

Add a new dict at the end of `legal_aliases.py` (before `expand_query`):

```python
# Maps abbreviated code references found in cross-references to (law_number, law_year)
CODE_ABBREVIATIONS: dict[str, tuple[str, int]] = {
    "c.civ.": ("287", 2009),
    "cod civ.": ("287", 2009),
    "codul civil": ("287", 2009),
    "c.pen.": ("286", 2009),
    "cod pen.": ("286", 2009),
    "codul penal": ("286", 2009),
    "c.proc.civ.": ("134", 2010),
    "cod procedura civila": ("134", 2010),
    "codul de procedura civila": ("134", 2010),
    "c.proc.pen.": ("135", 2010),
    "cod procedura penala": ("135", 2010),
    "codul de procedura penala": ("135", 2010),
    "c.fisc.": ("227", 2015),
    "codul fiscal": ("227", 2015),
    "c.muncii": ("53", 2003),
    "codul muncii": ("53", 2003),
    "c.proc.fisc.": ("207", 2015),
    "codul de procedura fiscala": ("207", 2015),
    "legea societatilor": ("31", 1990),
    "legea societatilor comerciale": ("31", 1990),
}
```

- [ ] **Step 2: Update `expand_articles` to accept pipeline state**

Modify the `expand_articles` function signature in `article_expander.py` (line 16-20). The function currently returns `tuple[list[int], dict]` — keep that return type:

```python
def expand_articles(
    db: Session,
    article_ids: list[int],
    neighbor_range: int = 2,
    selected_versions: dict | None = None,
    primary_date: str | None = None,
) -> tuple[list[int], dict]:
```

Pass the new args through but keep existing logic unchanged. Add a call to the new cross-law function:

```python
        xrefs = _extract_cross_references(db, article)
        expanded.update(xrefs)

        # Cross-law references (art. N din Codul Civil, etc.)
        cross_law_refs = _extract_cross_law_references(
            db, article, selected_versions or {}, primary_date
        )
        expanded.update(cross_law_refs)
```

- [ ] **Step 3: Implement `_extract_cross_law_references`**

Add to `article_expander.py`:

```python
def _extract_cross_law_references(
    db: Session,
    article: Article,
    selected_versions: dict,
    primary_date: str | None,
) -> list[int]:
    """Parse cross-references to articles in OTHER laws and resolve them."""
    from app.services.legal_aliases import CODE_ABBREVIATIONS
    from app.models.law import Law, LawVersion

    text = article.full_text or ""
    for note in article.amendment_notes:
        if note.text:
            text += " " + note.text

    article_ids = []

    # Pattern: "art. N din Legea nr. M/YYYY"
    for match in re.finditer(
        r"art\.\s*(\d+(?:\^\d+)?)\s+din\s+(?:Legea|legea)\s+(?:nr\.\s*)?(\d+)/(\d{4})",
        text, re.IGNORECASE
    ):
        ref_num, law_num, law_year = match.group(1), match.group(2), int(match.group(3))
        aid = _resolve_cross_law_article(db, ref_num, law_num, law_year, selected_versions, primary_date)
        if aid:
            article_ids.append(aid)

    # Pattern: "art. N C.civ." / "art. N Codul Civil" etc.
    for match in re.finditer(
        r"art\.\s*(\d+(?:\^\d+)?)\s+(?:din\s+)?([A-Za-zăîâșțĂÎÂȘȚ][A-Za-zăîâșțĂÎÂȘȚ\s.]+?)(?=[,;.\s\)\]]|$)",
        text, re.IGNORECASE
    ):
        ref_num = match.group(1)
        law_ref = match.group(2).strip().lower().rstrip(".")

        # Check if it matches a known code abbreviation
        for abbrev, (law_num, law_year) in CODE_ABBREVIATIONS.items():
            if law_ref == abbrev or law_ref.startswith(abbrev):
                aid = _resolve_cross_law_article(
                    db, ref_num, law_num, law_year, selected_versions, primary_date
                )
                if aid:
                    article_ids.append(aid)
                break

    return article_ids


def _resolve_cross_law_article(
    db: Session,
    article_number: str,
    law_number: str,
    law_year: int,
    selected_versions: dict,
    primary_date: str | None,
) -> int | None:
    """Resolve a cross-law article reference to a specific article ID."""
    from app.models.law import Law, LawVersion

    # Check if this law already has a version selected by the pipeline
    version_key = f"{law_number}/{law_year}"
    version_info = selected_versions.get(version_key)

    if version_info:
        law_version_id = version_info["law_version_id"]
    else:
        # Look up the law and find the right version
        law = (
            db.query(Law)
            .filter(Law.law_number == law_number, Law.law_year == law_year)
            .first()
        )
        if not law:
            return None

        # Use primary_date for version selection (same logic as Step 3)
        if primary_date:
            version = (
                db.query(LawVersion)
                .filter(LawVersion.law_id == law.id)
                .filter(LawVersion.date_in_force <= primary_date)
                .order_by(LawVersion.date_in_force.desc())
                .first()
            )
        else:
            version = None

        if not version:
            # Fallback to current version
            version = (
                db.query(LawVersion)
                .filter(LawVersion.law_id == law.id, LawVersion.is_current == True)
                .first()
            )
        if not version:
            return None
        law_version_id = version.id

    # Find the referenced article
    ref_art = (
        db.query(Article)
        .filter(
            Article.law_version_id == law_version_id,
            Article.article_number == article_number,
        )
        .first()
    )
    return ref_art.id if ref_art else None
```

- [ ] **Step 4: Update the caller in `pipeline_service.py`**

In `_step5_expand` (line 1001, around the call to `expand_articles`), pass the new arguments. Preserve the existing tuple unpacking:

```python
    expanded_ids, expansion_details = expand_articles(
        db, raw_ids,
        selected_versions=state.get("selected_versions", {}),
        primary_date=state.get("primary_date"),
    )
```

- [ ] **Step 5: Verify**

Find an article in the database that references another law (e.g., an article in Legea 31/1990 that says "art. 1270 din Codul Civil"). Run a query that retrieves that article and check if the Civil Code article also appears in the expanded set.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/article_expander.py backend/app/services/legal_aliases.py \
    backend/app/services/pipeline_service.py
git commit -m "feat(C2): resolve cross-law article references using date-aware version selection"
```

---

## Task 8: H3 — Surface version fallback warnings in the main answer

**Files:**
- Modify: `backend/prompts/LA-S7-answer-qa.txt` (add version warning instruction)
- Modify: `backend/prompts/LA-S7-M2-answer-memo.txt` (same)
- Modify: `backend/prompts/LA-S7-M3-answer-comparison.txt` (same)
- Modify: `backend/prompts/LA-S7-M4-answer-compliance.txt` (same)
- Modify: `backend/prompts/LA-S7-M5-answer-checklist.txt` (same)
- Modify: `frontend/src/app/assistant/answer-detail.tsx:89-91`

- [ ] **Step 1: Add version warning instruction to all LA-S7 prompts**

In each of the 5 LA-S7 prompt files, add this instruction near the version_logic field description:

```
IMPORTANT: If the FLAGS AND WARNINGS section mentions version fallback (e.g., "No version found for [date], using current version"), you MUST explain this prominently in the version_logic field. State clearly: which version was actually used, that it may not match the user's intended date, and what this means for the answer's reliability. Do NOT bury this — it affects how much the user should trust the answer.
```

- [ ] **Step 2: Surface version_logic prominently when it contains warnings**

In `frontend/src/app/assistant/answer-detail.tsx`, replace the simple `version_logic` Section (around line 90):

```tsx
          <Section title="Version Logic" content={s?.version_logic} />
```

with a version that highlights warnings:

```tsx
          {s?.version_logic && (
            <div className="mb-3">
              <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Version Logic</h4>
              <div className={`text-sm leading-relaxed prose prose-sm max-w-none ${
                s.version_logic.toLowerCase().includes("fallback") ||
                s.version_logic.toLowerCase().includes("no version found") ||
                s.version_logic.toLowerCase().includes("nu s-a gasit")
                  ? "bg-amber-50 border border-amber-200 rounded-lg p-2 text-amber-900"
                  : "text-gray-700"
              }`}>
                <ReactMarkdown>{s.version_logic}</ReactMarkdown>
              </div>
            </div>
          )}
```

- [ ] **Step 3: Commit**

```bash
git add backend/prompts/LA-S7-answer-qa.txt backend/prompts/LA-S7-M2-answer-memo.txt \
    backend/prompts/LA-S7-M3-answer-comparison.txt backend/prompts/LA-S7-M4-answer-compliance.txt \
    backend/prompts/LA-S7-M5-answer-checklist.txt frontend/src/app/assistant/answer-detail.tsx
git commit -m "fix(H3): surface version fallback warnings prominently in answer and UI"
```

---

## Task 9: H4 — Strengthen `[General]` and `[Unverified]` source labels

**Files:**
- Modify: `frontend/src/app/assistant/answer-detail.tsx:100-113` (sources display)
- Modify: `backend/prompts/LA-S7-answer-qa.txt` (add General qualifier instruction)

- [ ] **Step 1: Add warning indicators to source labels in the frontend**

In `answer-detail.tsx`, update the sources rendering (around lines 100-113). Replace:

```tsx
                  <div key={i} className="flex items-start gap-2 text-xs text-gray-600">
                    <span className={`shrink-0 px-1.5 py-0.5 rounded font-medium ${LABEL_COLORS[src.label] || "bg-gray-100 text-gray-500"}`}>
                      {src.label}
                    </span>
                    <span className="flex-1">{src.statement}</span>
```

with:

```tsx
                  <div key={i} className="flex items-start gap-2 text-xs text-gray-600">
                    <span
                      className={`shrink-0 px-1.5 py-0.5 rounded font-medium ${LABEL_COLORS[src.label] || "bg-gray-100 text-gray-500"}`}
                      title={
                        src.label === "General"
                          ? "This information comes from AI training data, not from verified law text. It may be outdated or incorrect."
                          : src.label === "Unverified"
                          ? "This claim could not be verified against current law text. Do not rely on it without manual verification."
                          : src.label === "DB"
                          ? "Verified against law text in the Legal Library."
                          : undefined
                      }
                    >
                      {src.label === "General" ? "⚠ General" : src.label === "Unverified" ? "⛔ Unverified" : src.label}
                    </span>
                    <span className="flex-1">{src.statement}</span>
```

- [ ] **Step 2: Add qualifier instruction to LA-S7 prompts**

In `backend/prompts/LA-S7-answer-qa.txt`, in the source labeling rules section, add:

```
When you cite [General] sources, the statement field MUST include a qualifier such as "Conform cunoștințelor juridice generale (neverificat din textul legii actuale)" or "Based on general legal knowledge (not verified against current law text)". This prevents users from treating AI training knowledge as equivalent to verified law text.
```

Apply the same addition to all other LA-S7 variants.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/assistant/answer-detail.tsx \
    backend/prompts/LA-S7-answer-qa.txt backend/prompts/LA-S7-M2-answer-memo.txt \
    backend/prompts/LA-S7-M3-answer-comparison.txt backend/prompts/LA-S7-M4-answer-compliance.txt \
    backend/prompts/LA-S7-M5-answer-checklist.txt
git commit -m "fix(H4): add warning indicators to General/Unverified sources in UI and prompts"
```

---

## Task 10: M1 — Expand BM25 synonym groups

**Files:**
- Modify: `backend/app/services/bm25_service.py:92-106`

- [ ] **Step 1: Add new synonym expansions**

In `bm25_service.py`, expand the `_BM25_EXPANSIONS` dict (after line 106):

```python
    # --- Employment law terms ---
    "concediu": ["concediul", "concedii", "concediilor", "zile libere", "vacanta"],
    "angajat": ["angajatul", "angajati", "angajatii", "angajatilor", "salariat", "salariatul"],
    "salariat": ["salariatul", "salariati", "salariatii", "salariatilor", "angajat", "angajatul"],
    "angajator": ["angajatorul", "angajatorii", "angajatorilor", "patronat", "patron"],
    # --- Contract / obligation terms ---
    "reziliere": ["rezilierea", "rezilierii", "desfacere", "incetare"],
    "rezolutiune": ["rezolutiunea", "rezolutiunii", "desfiintare"],
    "locatar": ["locatarul", "locatarului", "chirias", "chiriasul"],
    "chirias": ["chiriasul", "chiriasului", "locatar", "locatarul"],
    # --- Property / finance terms ---
    "dobanda": ["dobanzii", "dobanzi", "rata dobanzii", "dobanda legala"],
    "ipoteca": ["ipotecii", "ipoteci", "garantie", "garantia", "drept de garantie"],
    "garantie": ["garantiei", "garantii", "ipoteca", "cautiune", "fidejusiune"],
    # --- Inheritance terms ---
    "mostenire": ["mostenirea", "mostenirii", "succesiune", "succesiunea", "legat"],
    "succesiune": ["succesiunea", "succesiunii", "mostenire", "mostenirea", "testament"],
    # --- Representation terms ---
    "procura": ["procurii", "procuri", "imputernicire", "mandat"],
    "imputernicire": ["imputernicirea", "imputernicirii", "procura", "mandat"],
    # --- Liability terms ---
    "raspundere": ["raspunderea", "raspunderii", "responsabilitate", "culpa", "prejudiciu"],
    "prejudiciu": ["prejudiciul", "prejudiciului", "daune", "despagubire", "despagubiri"],
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/bm25_service.py
git commit -m "feat(M1): expand BM25 synonym groups from 13 to 30+ for better recall"
```

---

## Task 11: M2 — Add more entity types to targeted search

**Files:**
- Modify: `backend/app/services/pipeline_service.py:866-870` (`_ENTITY_KEYWORDS` dict)

- [ ] **Step 1: Add new entity keyword groups**

Expand the `_ENTITY_KEYWORDS` dict:

```python
_ENTITY_KEYWORDS: dict[str, list[str]] = {
    "SRL": ["raspundere limitata", "asociati", "parte sociala", "parti sociale"],
    "SA": ["actiuni", "actionar", "societate pe actiuni", "capital social", "adunarea generala"],
    "PFA": ["persoana fizica autorizata", "activitate independenta"],
    "SCS": ["comandita simpla", "comanditar", "comanditat"],
    "SNC": ["nume colectiv", "raspundere nelimitata", "solidara"],
    "SCA": ["comandita pe actiuni", "comanditari", "actionari comandita"],
    "ONG": ["asociatie", "organizatie neguvernamentala", "scop nepatrimonial", "act constitutiv asociatie"],
    "ASOCIATIE": ["asociatie", "asociatii", "scop nepatrimonial", "membri asociatie"],
    "FUNDATIE": ["fundatie", "fundatii", "patrimoniu afectat", "scop nepatrimonial fundatie"],
    "COOPERATIVA": ["cooperativa", "cooperative", "membri cooperatori", "parti sociale cooperativa"],
}
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat(M2): add SCS, SNC, SCA, ONG, ASOCIATIE, FUNDATIE, COOPERATIVA entity types"
```

---

## Task 12: M3 — Make the disclaimer more visible

**Files:**
- Modify: `frontend/src/app/assistant/message-bubble.tsx:155-157`

- [ ] **Step 1: Update disclaimer styling**

Change lines 155-157 from:

```tsx
        <div className="mt-2 text-[10px] text-gray-400 leading-tight">
          Analiza juridica preliminara asistata de AI — necesita revizuire umana.
        </div>
```

to:

```tsx
        <div className="mt-3 px-2 py-1.5 bg-gray-50 border border-gray-200 rounded text-xs text-gray-600 leading-snug">
          ⚖ Analiza juridica preliminara asistata de AI — necesita revizuire umana. Aceasta nu constituie consultanta juridica.
        </div>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/assistant/message-bubble.tsx
git commit -m "fix(M3): make AI disclaimer more visible — larger text, border, background"
```

---

## Task 13: M4 — Increase conversation history context in Step 1

**Files:**
- Modify: `backend/app/services/pipeline_service.py:428`

- [ ] **Step 1: Increase truncation from 200 to 500 chars**

Change line 428 from:

```python
            f"[{m['role']}]: {m['content'][:200]}" for m in state["session_context"][-5:]
```

to:

```python
            f"[{m['role']}]: {m['content'][:500]}" for m in state["session_context"][-5:]
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "fix(M4): increase conversation history context from 200 to 500 chars per message"
```

---

## Task 14: Final verification and re-index

- [ ] **Step 1: Re-index ChromaDB to include all metadata changes**

```bash
cd /Users/anaandrei/projects/legalese/backend
python -c "
from app.database import SessionLocal
from app.services.chroma_service import index_all
from app.services.bm25_service import rebuild_fts_index

db = SessionLocal()
print('Final re-index: ChromaDB...')
count = index_all(db)
print(f'ChromaDB: {count} articles')
print('Final re-index: BM25 FTS...')
rebuild_fts_index(db)
print('Done')
db.close()
"
```

- [ ] **Step 2: Run a comprehensive test**

Start the app, ask several questions that exercise the different fixes:
1. A question with a past date (C1): "Ce prevedea Codul Civil in 2015 despre rezilierea contractelor?"
2. A real estate question (C3): "Ce trebuie verificat la cumpararea unui apartament?"
3. A question about a law that references another (C2): check logs for cross-law references
4. Check an answer with `[General]` sources (H4): verify warning indicators
5. Check the disclaimer visibility (M3)

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: final re-index after legal accuracy fixes"
```
