# Annex Import & Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import annexes from Romanian legal documents alongside articles, index them for hybrid search, and include them in RAG context for Q&A.

**Architecture:** New `Annex` model stored per `LawVersion`, populated during import from leropa's `parse_html()` output. Indexed in both ChromaDB (semantic) and BM25 FTS5 (keyword). Results flow through the existing merge/rerank/format pipeline with a `doc_type` discriminator.

**Tech Stack:** SQLAlchemy (SQLite), ChromaDB, SQLite FTS5, leropa parser

**Spec:** `docs/superpowers/specs/2026-03-24-annex-import-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/app/models/law.py` | Add `Annex` model |
| Modify | `backend/app/services/fetcher.py` | Merge annexes in Afis fallback |
| Modify | `backend/app/services/leropa_service.py` | Store annexes during import |
| Modify | `backend/app/services/chroma_service.py` | Index/remove/query annexes in ChromaDB |
| Modify | `backend/app/services/bm25_service.py` | Index/search annexes in FTS5 |
| Modify | `backend/app/services/pipeline_service.py` | Format annex results in RAG context |

---

### Task 1: Add Annex Model

**Files:**
- Modify: `backend/app/models/law.py:1-201`

- [ ] **Step 1: Add Annex class to law.py**

Add after the `AmendmentNote` class (line 200), and add the `annexes` relationship to `LawVersion`:

```python
# In LawVersion class (around line 93), add relationship:
    annexes: Mapped[list["Annex"]] = relationship(
        back_populates="law_version", cascade="all, delete-orphan"
    )
```

```python
# After AmendmentNote class, add:
class Annex(Base):
    __tablename__ = "annexes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    law_version_id: Mapped[int] = mapped_column(
        ForeignKey("law_versions.id"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    law_version: Mapped["LawVersion"] = relationship(back_populates="annexes")
```

- [ ] **Step 2: Add Annex to the model imports in leropa_service.py**

In `backend/app/services/leropa_service.py` line 11-18, add `Annex` to the import:

```python
from app.models.law import (
    AmendmentNote,
    Annex,
    Article,
    ...
)
```

- [ ] **Step 3: Verify the table gets created**

Run: `cd backend && python -c "from app.database import engine, Base; from app.models.law import Annex; Base.metadata.create_all(bind=engine); print('OK')"`

Expected: `OK` — the `annexes` table is created via `create_all`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/law.py backend/app/services/leropa_service.py
git commit -m "feat: add Annex model linked to LawVersion"
```

---

### Task 2: Fix Afis Fallback to Merge Annexes

**Files:**
- Modify: `backend/app/services/fetcher.py:149-164`

- [ ] **Step 1: Add annexes merge in the Afis fallback block**

In `fetcher.py`, after line 162 (`result["books"] = afis_result["books"]`), add:

```python
                    result["annexes"] = afis_result.get("annexes", [])
```

This ensures large codes (Codul Fiscal, etc.) that use the Afis page also get their annexes.

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/fetcher.py
git commit -m "fix: merge annexes from Afis fallback page during import"
```

---

### Task 3: Store Annexes During Import

**Files:**
- Modify: `backend/app/services/leropa_service.py:156-237` (fetch_and_store_version)

- [ ] **Step 1: Add `_store_annexes` function**

Add after `_store_orphan_articles` (around line 428):

```python
def _store_annexes(
    db: Session,
    version: LawVersion,
    annexes_data: list[dict],
) -> None:
    """Store annexes as flat text blobs. Amendment notes appended to text."""
    for idx, anx in enumerate(annexes_data):
        text = anx.get("text", "") or ""
        # Append amendment notes directly into the text body
        for note in anx.get("notes", []):
            note_text = note.get("text", "")
            if note_text and note_text.strip():
                text += f"\n[Modificare: {note_text.strip()}]"

        if not text.strip():
            continue  # Skip empty annexes

        annex = Annex(
            law_version_id=version.id,
            source_id=anx.get("annex_id", f"anx_{idx}"),
            title=anx.get("title", f"Anexa {idx + 1}"),
            full_text=text,
            order_index=idx,
        )
        db.add(annex)
    db.flush()
```

- [ ] **Step 2: Call `_store_annexes` in `fetch_and_store_version`**

In `fetch_and_store_version()`, after `_store_orphan_articles` call (line 234) and before `db.flush()` (line 236), add:

```python
    # Store annexes
    _store_annexes(db, version, result.get("annexes", []))
```

Note: `result` is already in scope (from `fetch_document` at line 175). The existing `db.flush()` at line 236 can be kept as-is since `_store_annexes` also flushes.

- [ ] **Step 3: Verify by running a quick import test**

Run: `cd backend && python -c "
from app.database import SessionLocal, engine, Base
from app.models.law import Annex
Base.metadata.create_all(bind=engine)
db = SessionLocal()
count = db.query(Annex).count()
print(f'Annex table exists, {count} rows')
db.close()
"`

Expected: `Annex table exists, 0 rows`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/leropa_service.py
git commit -m "feat: store annexes during law import"
```

---

### Task 4: Index Annexes in ChromaDB

**Files:**
- Modify: `backend/app/services/chroma_service.py:47-128`

- [ ] **Step 1: Update `index_law_version` to also index annexes**

After the existing article indexing loop (after line 93, before the return), add annex indexing:

```python
    # Index annexes
    from app.models.law import Annex as AnnexModel
    annexes = (
        db.query(AnnexModel).filter(AnnexModel.law_version_id == law_version_id).all()
    )
    anx_ids, anx_documents, anx_metadatas = [], [], []
    for annex in annexes:
        if not annex.full_text or not annex.full_text.strip():
            continue
        doc_id = f"anx-{annex.id}"
        anx_ids.append(doc_id)
        anx_documents.append(annex.full_text)
        anx_metadatas.append({
            "law_id": law.id,
            "law_version_id": version.id,
            "article_id": annex.id,
            "law_number": law.law_number,
            "law_year": str(law.law_year),
            "law_title": law.title[:200],
            "article_number": annex.title[:100],
            "date_in_force": str(version.date_in_force) if version.date_in_force else "",
            "is_current": str(version.is_current),
            "is_abrogated": "False",
            "amendment_count": "0",
            "doc_type": "annex",
            "annex_title": annex.title[:200],
        })

    for i in range(0, len(anx_ids), batch_size):
        collection.upsert(
            ids=anx_ids[i : i + batch_size],
            documents=anx_documents[i : i + batch_size],
            metadatas=anx_metadatas[i : i + batch_size],
        )

    logger.info(
        f"Indexed {len(ids)} articles + {len(anx_ids)} annexes for "
        f"{law.law_number}/{law.law_year} version {version.id}"
    )
    return len(ids) + len(anx_ids)
```

Update the existing log line (line 95-98) to be replaced by the new combined log above.

- [ ] **Step 2: Update `remove_law_articles` to also remove annexes**

In `remove_law_articles()` (line 113-127), after querying article IDs, also query and remove annex IDs:

```python
def remove_law_articles(db: Session, law_id: int):
    """Remove all articles and annexes for a law from ChromaDB."""
    collection = get_collection()
    articles = (
        db.query(Article.id)
        .join(LawVersion)
        .filter(LawVersion.law_id == law_id)
        .all()
    )
    from app.models.law import Annex as AnnexModel
    annexes = (
        db.query(AnnexModel.id)
        .join(LawVersion)
        .filter(LawVersion.law_id == law_id)
        .all()
    )
    ids = [f"art-{a.id}" for a in articles] + [f"anx-{a.id}" for a in annexes]
    if ids:
        batch_size = 500
        for i in range(0, len(ids), batch_size):
            collection.delete(ids=ids[i : i + batch_size])
    logger.info(f"Removed {len(ids)} items from ChromaDB for law_id={law_id}")
```

- [ ] **Step 3: Update `query_articles` to include `doc_type` in results**

In `query_articles()` (line 158-175), add `doc_type` to the returned dict:

```python
            articles.append({
                "article_id": meta["article_id"],
                "law_number": meta["law_number"],
                "law_year": meta["law_year"],
                "law_title": meta.get("law_title", ""),
                "article_number": meta["article_number"],
                "date_in_force": meta.get("date_in_force", ""),
                "is_current": meta.get("is_current", ""),
                "text": results["documents"][0][i],
                "is_abrogated": meta.get("is_abrogated", "False") == "True",
                "distance": results["distances"][0][i],
                "doc_type": meta.get("doc_type", "article"),
                "annex_title": meta.get("annex_title", ""),
            })
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/chroma_service.py
git commit -m "feat: index and search annexes in ChromaDB"
```

---

### Task 5: Index Annexes in BM25 FTS5

**Files:**
- Modify: `backend/app/services/bm25_service.py` — rewrite 3 functions completely

- [ ] **Step 1: Rewrite `ensure_fts_index` to handle both tables**

Replace the entire `ensure_fts_index` function (lines 14-67) with:

```python
def ensure_fts_index(db: Session):
    """Create the FTS5 virtual tables if they don't exist, then populate."""
    import sqlite3
    db_url = str(db.get_bind().url)
    db_path = db_url.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if both tables exist and have data
    articles_ready = False
    annexes_ready = False

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='articles_fts'"
    )
    if cursor.fetchone():
        cursor.execute("SELECT COUNT(*) FROM articles_fts")
        articles_ready = cursor.fetchone()[0] > 0
        if not articles_ready:
            cursor.execute("DROP TABLE articles_fts")
            conn.commit()

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='annexes_fts'"
    )
    if cursor.fetchone():
        cursor.execute("SELECT COUNT(*) FROM annexes_fts")
        annexes_ready = cursor.fetchone()[0] > 0
        if not annexes_ready:
            cursor.execute("DROP TABLE annexes_fts")
            conn.commit()

    if articles_ready and annexes_ready:
        conn.close()
        return

    # Create and populate articles FTS5
    if not articles_ready:
        logger.info("Creating FTS5 index for articles...")
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
                article_text,
                law_version_id UNINDEXED,
                article_id UNINDEXED,
                tokenize='unicode61 remove_diacritics 2'
            )
        """)
        cursor.execute("""
            SELECT a.id, a.full_text, a.law_version_id
            FROM articles a
        """)
        articles = cursor.fetchall()
        for art_id, full_text, law_version_id in articles:
            combined = full_text or ""
            cursor.execute(
                "INSERT INTO articles_fts(rowid, article_text, law_version_id, article_id) VALUES (?, ?, ?, ?)",
                (art_id, combined, law_version_id, art_id),
            )
        conn.commit()
        logger.info(f"FTS5 articles index created with {len(articles)} articles")

    # Create and populate annexes FTS5
    if not annexes_ready:
        logger.info("Creating FTS5 index for annexes...")
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS annexes_fts USING fts5(
                annex_text,
                law_version_id UNINDEXED,
                annex_db_id UNINDEXED,
                tokenize='unicode61 remove_diacritics 2'
            )
        """)
        cursor.execute("""
            SELECT a.id, a.full_text, a.law_version_id
            FROM annexes a
        """)
        annexes = cursor.fetchall()
        for anx_id, full_text, law_version_id in annexes:
            combined = full_text or ""
            cursor.execute(
                "INSERT INTO annexes_fts(rowid, annex_text, law_version_id, annex_db_id) VALUES (?, ?, ?, ?)",
                (anx_id, combined, law_version_id, anx_id),
            )
        conn.commit()
        logger.info(f"FTS5 annexes index created with {len(annexes)} annexes")

    conn.close()
```

- [ ] **Step 2: Rewrite `rebuild_fts_index` to drop both tables**

Replace the entire function (lines 70-79) with:

```python
def rebuild_fts_index(db: Session):
    """Drop and recreate the FTS5 index."""
    import sqlite3
    db_url = str(db.get_bind().url)
    db_path = db_url.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE IF EXISTS articles_fts")
    conn.execute("DROP TABLE IF EXISTS annexes_fts")
    conn.commit()
    conn.close()
    ensure_fts_index(db)
```

- [ ] **Step 3: Rewrite `search_bm25` to search both tables**

Replace the entire function (lines 122-210) with:

```python
def search_bm25(
    db: Session,
    query: str,
    law_version_ids: list[int] | None = None,
    limit: int = 15,
) -> list[dict]:
    """Search articles and annexes using BM25 ranking.
    FTS5 with remove_diacritics handles ă/â/î/ș/ț automatically.
    """
    import re
    words = re.findall(r"[a-zA-ZăîâșțĂÎÂȘȚ]{3,}", query)
    if not words:
        return []

    # Expand abbreviations and synonyms for better recall
    expanded = list(words)
    for w in words:
        wl = w.lower()
        for key, synonyms in _BM25_EXPANSIONS.items():
            if wl == key or wl.startswith(key):
                expanded.extend(synonyms)
                break

    fts_query = " OR ".join(expanded)

    import sqlite3
    db_url = str(db.get_bind().url)
    db_path = db_url.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    rows = []
    anx_rows = []
    try:
        # Search articles
        if law_version_ids:
            placeholders = ",".join("?" * len(law_version_ids))
            sql = f"""
                SELECT article_id, law_version_id, rank
                FROM articles_fts
                WHERE articles_fts MATCH ?
                AND law_version_id IN ({placeholders})
                ORDER BY rank
                LIMIT ?
            """
            params = [fts_query] + law_version_ids + [limit]
        else:
            sql = """
                SELECT article_id, law_version_id, rank
                FROM articles_fts
                WHERE articles_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """
            params = [fts_query, limit]

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        # Search annexes
        if law_version_ids:
            placeholders = ",".join("?" * len(law_version_ids))
            anx_sql = f"""
                SELECT annex_db_id, law_version_id, rank
                FROM annexes_fts
                WHERE annexes_fts MATCH ?
                AND law_version_id IN ({placeholders})
                ORDER BY rank
                LIMIT ?
            """
            anx_params = [fts_query] + law_version_ids + [limit]
        else:
            anx_sql = """
                SELECT annex_db_id, law_version_id, rank
                FROM annexes_fts
                WHERE annexes_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """
            anx_params = [fts_query, limit]

        cursor.execute(anx_sql, anx_params)
        anx_rows = cursor.fetchall()
    except Exception as e:
        logger.warning(f"FTS5 search failed: {e}")
    finally:
        conn.close()

    # Build article results
    results = []
    for article_id, law_version_id, rank in rows:
        art = db.query(Article).filter(Article.id == article_id).first()
        if not art:
            continue
        law = art.law_version.law
        version = art.law_version

        text_parts = [art.full_text]
        for note in art.amendment_notes:
            if note.text and note.text.strip():
                text_parts.append(f"[Amendment: {note.text.strip()}]")

        results.append({
            "article_id": art.id,
            "law_number": law.law_number,
            "law_year": str(law.law_year),
            "law_title": law.title[:200],
            "article_number": art.article_number,
            "date_in_force": str(version.date_in_force) if version.date_in_force else "",
            "is_current": str(version.is_current),
            "text": "\n".join(text_parts),
            "is_abrogated": getattr(art, 'is_abrogated', False),
            "bm25_rank": rank,
            "source": "bm25",
            "doc_type": "article",
        })

    # Build annex results
    from app.models.law import Annex as AnnexModel
    for anx_db_id, law_version_id, rank in anx_rows:
        anx = db.query(AnnexModel).filter(AnnexModel.id == anx_db_id).first()
        if not anx:
            continue
        law = anx.law_version.law
        version = anx.law_version

        results.append({
            "article_id": anx.id,
            "law_number": law.law_number,
            "law_year": str(law.law_year),
            "law_title": law.title[:200],
            "article_number": anx.title[:100],
            "date_in_force": str(version.date_in_force) if version.date_in_force else "",
            "is_current": str(version.is_current),
            "text": anx.full_text,
            "is_abrogated": False,
            "bm25_rank": rank,
            "source": "bm25",
            "doc_type": "annex",
            "annex_title": anx.title,
        })

    return results
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/bm25_service.py
git commit -m "feat: index and search annexes in BM25 FTS5"
```

---

### Task 6: Format Annexes in RAG Context

**Files:**
- Modify: `backend/app/services/pipeline_service.py:1380-1396`

- [ ] **Step 1: Update the deduplication to handle annex doc_type**

In the merge/dedup loop (line 952-961), the `seen_ids` set uses `art["article_id"]`. Since annex IDs could collide with article IDs (both are integer PKs), prefix the key:

```python
        # Merge and deduplicate
        for art in bm25_results + semantic_results:
            doc_type = art.get("doc_type", "article")
            aid = f"{doc_type}:{art['article_id']}"
            if aid not in seen_ids:
                seen_ids.add(aid)
                art["tier"] = tier_key
                art["role"] = TIER_TO_ROLE.get(tier_key, "SECONDARY")
                all_articles.append(art)
            else:
                duplicates_removed += 1
```

- [ ] **Step 2: Update article context formatting to handle annexes**

In the RAG context building section (line 1384-1396), branch on `doc_type`:

```python
        for i, art in enumerate(retrieved, 1):
            doc_type = art.get("doc_type", "article")
            role_tag = f"[{art.get('role', 'SECONDARY')}] " if art.get("role") else ""
            abrogated_tag = " [ABROGATED — this article has been repealed]" if art.get("is_abrogated") else ""

            if doc_type == "annex":
                articles_context += (
                    f"[Annex {i}] {role_tag}{art.get('law_title', '')} "
                    f"({art.get('law_number', '')}/{art.get('law_year', '')}), "
                    f"{art.get('annex_title', art.get('article_number', ''))}"
                )
            else:
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

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: format annexes in RAG context for Q&A pipeline"
```

---

### Task 7: Smoke Test

- [ ] **Step 1: Restart the backend and verify startup**

Run: `cd backend && python -c "from app.models.law import Annex; print('Import OK')"`

Expected: `Import OK`

- [ ] **Step 2: Verify the annexes table exists in SQLite**

Run: `cd backend && python -c "
import sqlite3
conn = sqlite3.connect('data/themis.db')
cursor = conn.cursor()
cursor.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='annexes'\")
print('annexes table:', cursor.fetchone())
conn.close()
"`

Expected: `annexes table: ('annexes',)`

- [ ] **Step 3: Commit all remaining changes (if any unstaged)**

```bash
git add -A
git status
# Only commit if there are changes
```
