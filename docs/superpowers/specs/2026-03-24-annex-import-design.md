# Annex Import & Search

## Problem

When a law is imported via leropa, annexes are parsed by the library but discarded by our import pipeline. Annex content (tables, forms, specifications, schedules) is lost and unavailable for Q&A search.

## Approach

Store annexes as simple text blobs — no paragraph/subparagraph parsing, no structural hierarchy. Annexes are too varied in format (tables, forms, lists) to warrant deep parsing. Amendment notes from leropa are appended directly into the text body.

## Data Model

New `Annex` table in `law.py`:

| Field | Type | Description |
|---|---|---|
| `id` | int PK | Auto-increment |
| `law_version_id` | FK → law_versions.id | Parent version |
| `source_id` | str | Original HTML id from leropa parser |
| `title` | str | e.g. "Anexa nr. 1 — Model de contract" |
| `full_text` | text | Entire annex body as plain text |
| `order_index` | int | Position among annexes in the document |

Relationships (both sides, following existing Article pattern):
- `LawVersion.annexes: Mapped[list["Annex"]]` with `cascade="all, delete-orphan"`
- `Annex.law_version: Mapped["LawVersion"]` with `back_populates="annexes"`

No sub-tables for paragraphs or amendment notes — notes are concatenated into `full_text`.

## Import Changes

### fetcher.py — Afis fallback fix

The Afis fallback (line 149-164) currently merges only `articles` and `books` from the Afis page. Add `result["annexes"] = afis_result.get("annexes", [])` so large codes (Codul Fiscal, etc.) also get their annexes.

### leropa_service.py — fetch_and_store_version()

After `_store_orphan_articles()`, call `_store_annexes(db, version, result.get("annexes", []))`.

The `result["annexes"]` list comes from leropa's `parse_html()` and contains dicts with keys: `annex_id`, `title`, `text`, `notes`.

### _store_annexes() (new function)

```python
def _store_annexes(db, version, annexes_data):
    for idx, anx in enumerate(annexes_data):
        text = anx.get("text", "") or ""
        # Append amendment notes to text body
        for note in anx.get("notes", []):
            note_text = note.get("text", "")
            if note_text and note_text.strip():
                text += f"\n[Modificare: {note_text.strip()}]"

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

### import_law()

No extra change needed — `fetch_and_store_version` handles its own fetch and now stores annexes for each version automatically.

## Search Indexing

### ChromaDB (chroma_service.py)

In `index_law_version()`, after indexing articles, also query and index annexes:

- `doc_id`: `f"anx-{annex.id}"`
- `document`: `annex.full_text`
- `metadata`: same fields as articles, plus:
  - `doc_type: "annex"` (articles get `doc_type: "article"`)
  - `annex_title: annex.title`
  - `article_number`: use annex title (for display compatibility)
  - `is_abrogated: "False"`, `amendment_count: "0"` (not applicable to annexes)

In `remove_law_articles()`: also query `Annex.id` from DB and delete `anx-{id}` IDs from ChromaDB.

In `query_articles()`: add `doc_type` from metadata to the returned dict. Existing article results get `doc_type: "article"` (default if not present in metadata, for backwards compat with already-indexed data).

### BM25 (bm25_service.py)

Create a parallel FTS5 table `annexes_fts`:

```sql
CREATE VIRTUAL TABLE annexes_fts USING fts5(
    annex_text,
    law_version_id UNINDEXED,
    annex_db_id UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
)
```

Note: `annex_db_id` is the Annex table PK (integer), not the HTML source ID string.

In `search_bm25()`: query both `articles_fts` and `annexes_fts` with the same FTS query and limit, concatenate results. Annex results include `doc_type: "annex"` in the returned dict. The downstream reranker will sort combined results by relevance.

In `ensure_fts_index()` and `rebuild_fts_index()`: handle `annexes_fts` alongside `articles_fts`.

## RAG Context (pipeline_service.py)

When formatting retrieved results for the Claude prompt, branch on `doc_type`:

- **Articles** (existing): `[Article {i}] ... Art. {number} ...`
- **Annexes** (new): `[Annex {i}] {law_title} ({law_number}/{law_year}), {annex_title}, version {date}\n{text}`

The `doc_type` field propagates from search results through reranking and deduplication to the formatting loop.

## Out of Scope

- No paragraph/subparagraph parsing inside annexes
- No cross-reference expansion from/to annexes
- No annex-specific expander logic
- No frontend changes
- No separate amendment note tracking (notes appended to text)

## Migration

Alembic migration to create the `annexes` table. Existing imported laws won't have annexes — they'd need to be re-imported to pick them up.
