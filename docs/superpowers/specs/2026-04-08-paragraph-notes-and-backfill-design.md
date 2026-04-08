# Paragraph-Level Notes, `text_clean`, and Backfill

**Date:** 2026-04-08
**Status:** Draft
**Part of:** Version diff redesign (Approach B). Spec 1 of 3.
**Followed by:** Spec 2 — note-augmented structural diff backend. Spec 3 — frontend rework.
**Related:** `2026-04-07-version-diff-redesign-design.md` (tokenizer approach — superseded once Spec 2 lands).

## Problem

The current diff between law versions misses real changes and renders chaotic output. Investigation showed three root causes that all live below the diff layer:

1. **Inline modification notes are never stripped from `Article.full_text`.** Romanian laws from legislatie.just.ro embed an official changelog in the body text — strings like `(la 31-03-2026, Articolul 336 […] a fost completat de Punctul 9., Articolul I din OUG nr. 89/2025 […])`. These show up as content in every text-based diff and produce phantom edits and noise.
2. **Paragraph-level amendment notes are silently discarded on import.** Leropa parses notes both at the article level and at the paragraph level (`leropa/parser/paragraph.py:26`, `leropa/parser/note.py`). Each note carries a parsed `date`, `subject`, `law_number`, `monitor_number`, `replaced`, and `replacement`. Our importer (`backend/app/services/leropa_service.py:537-551`) only iterates `art_data["notes"]` — paragraph-level notes are dropped on the floor.
3. **No link from a stored note to the paragraph it modifies.** `amendment_notes` rows reference `article_id` only, so even if we had paragraph-level notes there is no place to attach them.

The diff redesign in Spec 2 needs the missing data to do its job. This spec makes that data exist — in storage, on freshly imported laws, and on the ~100 laws already in production — without touching anything that already works.

## Goal

Enable Spec 2 by making three things true:

- The database can store amendment notes at paragraph granularity, with a stable identity that makes re-runs idempotent.
- Future imports populate paragraph-level notes and a `text_clean` column on articles and paragraphs (the original `full_text` / `text` stripped of inline modification notes).
- Existing law versions in production are backfilled to the same state, with zero risk to already-imported `laws`, `law_versions`, `articles`, `paragraphs`, or `subparagraphs`.

## Non-goals

- No diff changes. The diff endpoint, the diff UI, and the `structured_diff.py` / `article_tokenizer.py` modules are untouched in this spec. Spec 2 owns that.
- No new front-end work. Amendment notes continue to render in the article detail view exactly as they do today.
- No removal of existing article-level notes. Article-level notes stay where they are; paragraph-level notes are added alongside them.
- No re-import of any law. The backfill is read-only with respect to existing content.
- No change to the leropa parser itself. We consume what it already produces.

## Architecture

Three pieces, in order:

```
1. Schema migration                — additive only, ships first
2. Importer change                 — future imports get the new data
3. Backfill job + subject parser   — populates existing data
```

```
backend/
  alembic/versions/
    2026_04_08_paragraph_notes.py        NEW migration
  app/services/
    leropa_service.py                    EDIT — store paragraph notes, write text_clean
    note_subject_parser.py               NEW — note.subject → (article_label, paragraph_label?)
    note_text_cleaner.py                 NEW — strip inline note markup from text
    notes_backfill.py                    NEW — read-only additive backfill job
  app/models/law.py                      EDIT — add columns + relationship
  app/routers/admin.py                   EDIT — POST /admin/backfill/notes endpoint
```

The two new helper modules (`note_subject_parser`, `note_text_cleaner`) are pure: no DB session, no I/O, fully unit-testable against fixtures.

## Schema migration

One Alembic migration. Strictly additive. Safe on Postgres without table rewrite.

```sql
ALTER TABLE amendment_notes
  ADD COLUMN paragraph_id   INTEGER NULL REFERENCES paragraphs(id),
  ADD COLUMN note_source_id VARCHAR(200) NULL;

CREATE INDEX ix_amendment_notes_paragraph_id ON amendment_notes(paragraph_id);
CREATE UNIQUE INDEX ux_amendment_notes_dedupe
  ON amendment_notes(article_id, COALESCE(paragraph_id, 0), COALESCE(note_source_id, ''));

ALTER TABLE articles  ADD COLUMN text_clean TEXT NULL;
ALTER TABLE paragraphs ADD COLUMN text_clean TEXT NULL;
```

`note_source_id` stores the leropa `Note.note_id` (the HTML element id for the note). It is the dedupe key that makes the backfill safely re-runnable: re-importing or re-running the backfill on a version that already has paragraph notes is a no-op because the unique index rejects duplicates.

`paragraph_id` is nullable because article-level notes (the ones we already store) have no paragraph, and because some paragraph-level notes will fail subject parsing in rare edge cases and degrade to article-level.

`text_clean` is nullable because existing rows start out without it. Until the backfill runs, the diff layer (Spec 2) will fall back to `full_text` / `text` if `text_clean` is null. After the backfill runs, every row has both.

The model file gains the new columns and a `paragraph` relationship on `AmendmentNote`. No existing column or constraint is removed or renamed.

## Note subject parser

Leropa's `Note.subject` is freeform Romanian text describing what was modified. Examples seen in the wild:

- `Articolul 336`
- `Alineatul (1) al articolului 336`
- `Litera a) a alineatului (2) al articolului 336`
- `Punctul 9. al articolului I`
- `Articolul 5, alineatul (1), litera c)`

`note_subject_parser.parse(subject: str) -> ParsedSubject` walks a small ordered list of regex patterns and returns:

```python
@dataclass(frozen=True)
class ParsedSubject:
    article_label: str | None       # "336"
    paragraph_label: str | None     # "(1)" — None means article-level
    subparagraph_label: str | None  # "a)" — informational, not used for FK
```

The parser is total: anything it cannot match returns `ParsedSubject(None, None, None)` and the note is attached at article level (current behaviour, no regression). It does not raise.

The pattern set targets ~6–10 forms that cover the overwhelming majority of notes; we add patterns as we find new ones via the dry-run report. Unit tests live in `backend/tests/test_note_subject_parser.py` with one fixture per pattern plus an "unknown" case.

## Note text cleaner

`note_text_cleaner.strip(text: str) -> str` removes inline modification annotations from a piece of article or paragraph text and returns the cleaned version. Inline annotations follow a stable shape: a parenthesised block beginning with `(la <date>,` and ending with the matching closing parenthesis (with depth tracking — they sometimes contain nested parentheses).

The cleaner is conservative: if it cannot find a balanced closing parenthesis it leaves the text untouched rather than mangling it. It also strips trailing whitespace runs left behind by removed annotations. It is not regex-only; balanced-paren handling is a small hand-written scanner.

Unit tests cover: a single inline note, multiple inline notes, nested parentheses inside a note, an unbalanced/malformed note (returned unchanged), text with no notes (returned unchanged), and a real-world fixture from Codul Fiscal art 336.

## Importer change

`leropa_service.py:_import_article` is edited to:

1. Walk `art_data["paragraphs"]` and, for each leropa paragraph, store its `notes` list as `AmendmentNote` rows linked to the corresponding `Paragraph` row we just created. The leropa `note_id` goes into `note_source_id`.
2. Compute `Article.text_clean = note_text_cleaner.strip(art_data["full_text"])` and `Paragraph.text_clean = note_text_cleaner.strip(par["text"])`.
3. Continue to store article-level notes as before. No behaviour change for those.

This is the only edit to the importer. New imports therefore get everything Spec 2 needs from day one.

## Backfill job

A new module `notes_backfill.py`. Pure additive. Never UPDATEs or DELETEs from `laws`, `law_versions`, `articles`, `paragraphs`, `subparagraphs`. Verified by a guardrail (below).

### Contract

```python
def backfill_notes(
    db: Session,
    *,
    law_id: int | None = None,        # None = all laws
    dry_run: bool = True,
    on_progress: Callable[[Progress], None] | None = None,
) -> BackfillReport
```

### Algorithm (per `LawVersion`)

1. Call `fetch_document(version.ver_id)`. Leropa cache is consulted first; on miss it re-fetches from legislatie.just.ro. A short sleep + exponential backoff sits between requests to be polite to the source.
2. Build a lookup `{(article.label, paragraph.label): paragraph_row}` from the existing `Paragraph` rows for this version. Article-only labels go into a parallel `{article.label: article_row}` lookup.
3. For each parsed leropa article and each of its paragraphs, iterate `paragraph["notes"]`:
   - Compute `paragraph_row` via the lookup. If the `(article_label, paragraph_label)` pair does not exist in our DB (parser drift), log a warning and skip. **Never guess.**
   - Use `note_subject_parser.parse(note.subject)` to confirm the subject points at the same paragraph; on mismatch, downgrade to article-level attribution and log.
   - INSERT one `AmendmentNote` row with `article_id = paragraph_row.article_id`, `paragraph_id = paragraph_row.id`, `note_source_id = note.note_id`, and the parsed metadata. The unique index makes the insert a no-op on re-runs.
4. For each leropa article, also iterate `article["notes"]` and insert any whose `note_source_id` is not yet present (catches notes added to the source HTML after the original import).
5. Compute and write `article.text_clean` and `paragraph.text_clean` for any rows where `text_clean IS NULL`. This is an UPDATE but only of new, nullable columns that nothing reads yet — explicitly allowed by the guardrail (see below).
6. Wrap each `LawVersion` in its own transaction. A failure on one version logs and continues to the next.

### Idempotency

Three layers:

1. The `(article_id, COALESCE(paragraph_id,0), COALESCE(note_source_id,''))` unique index rejects duplicate inserts at the DB level.
2. The `text_clean` writes are gated on `IS NULL` so a second run touches nothing.
3. The progress log persists per-version state so a resumed run skips finished versions.

### Dry-run mode

`dry_run=True` (the default) executes the same algorithm but rolls back every transaction after counting. The returned `BackfillReport` includes per-law counts of:

- paragraph notes that would be inserted
- article notes that would be added
- subjects that failed to parse (with samples)
- `(article_label, paragraph_label)` lookups that missed (with samples)
- versions that errored (with the exception)

The first production run is a dry run. We review the report. Then we re-run with `dry_run=False`.

### Guardrail

At the top of `backfill_notes`, a SQLAlchemy event listener registers on the session for the duration of the call:

```python
@event.listens_for(db, "before_flush")
def _assert_additive_only(session, flush_context, instances):
    forbidden = {Law, LawVersion, Article, Paragraph, Subparagraph}
    for obj in session.deleted:
        if type(obj) in forbidden:
            raise BackfillSafetyError(...)
    for obj in session.dirty:
        if type(obj) in forbidden:
            # text_clean writes are the only allowed mutation
            modified = inspect(obj).attrs
            for attr in modified:
                if attr.history.has_changes() and attr.key != "text_clean":
                    raise BackfillSafetyError(...)
```

If any forbidden mutation is attempted, the job aborts the transaction immediately and surfaces the offending object. This is belt-and-braces over the algorithm — the algorithm shouldn't ever produce such a mutation, and the guardrail makes sure of it.

### Trigger

Two triggers, both admin-only:

- `POST /api/admin/backfill/notes` with `{law_id?, dry_run}`. Returns a job id; the work runs in `pipeline_service` so it survives long executions and reports progress through the existing job UI.
- A CLI: `uv run python -m app.cli backfill-notes [--law-id N] [--no-dry-run]`. For local and one-shot operator use.

Neither runs automatically on deploy. The release flow is: ship migration → ship importer change + backfill code → operator triggers dry run → operator reviews → operator triggers real run.

## Production cache persistence

The leropa HTML cache lives at `~/.leropa/{ver_id}.html` (`backend/app/services/fetcher.py:100`). On Railway, `~` is `/root` inside an ephemeral container, so the cache is wiped on every redeploy. The backfill will work without persistent cache — it will just re-fetch from legislatie.just.ro — but a persistent cache makes it cheaper, faster, and less reliant on the source being available.

Action: mount a Railway volume at `/root/.leropa` (or set `LEROPA_CACHE_DIR` to a path on the existing data volume and read it from `fetcher.CACHE_DIR`). This is an infra change documented in the spec but performed during deploy of Spec 1; it does not require code beyond reading an env var if the path needs to be configurable.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Re-running the importer would duplicate rows | Backfill is a separate code path; it never calls `import_law_smart` |
| Source HTML drift between original import and backfill | Backfill never UPDATEs `articles`/`paragraphs` text — only inserts notes and writes the new `text_clean` column |
| Paragraph label collision within an article | Lookup is scoped to `(article.id, paragraph.label)`; on ambiguity, downgrade to article-level and log |
| Subject parser misattributes a note | Subject parser is total, conservative, falls back to article-level; covered by unit tests; reviewed via dry-run report |
| `note_text_cleaner` mangles malformed text | Cleaner returns input unchanged on unbalanced parens; covered by unit tests |
| Rate limiting from legislatie.just.ro | Serial fetch with backoff; persistent cache means a second run is mostly cache hits |
| Long-running job dies mid-run on Railway | Per-version transactions; progress persistence; resumable from last completed version |
| Operator runs the live backfill by accident | `dry_run=True` is the default; the API requires `dry_run=False` to be explicitly set; admin-only endpoint |
| Some pathological note breaks the whole job | Per-version try/except logs and continues; a single bad version never poisons the rest |
| Migration breaks existing queries | Migration is purely additive (new nullable columns + new indexes); no rename/drop |

## Testing

- **Unit:** `note_subject_parser` (one test per pattern + unknown case), `note_text_cleaner` (notes, nested parens, malformed, no-op, real fixture), guardrail behaviour (forbidden UPDATE/DELETE raises).
- **Integration:** `notes_backfill` against a SQLite test DB seeded with one law version that has known paragraph-level notes. Assert: correct rows inserted, idempotency on re-run, dry-run rolls back, guardrail blocks a forced UPDATE.
- **Manual:** dry run on production against one small law (operator-selected), review report, then dry run on all laws, review, then real run.

## Rollout order

1. Open PR with migration + model edits + helpers (`note_subject_parser`, `note_text_cleaner`) + unit tests. Merge. Deploy. Verify schema in production.
2. Open PR with importer edits (`leropa_service.py`) + integration test. Merge. Deploy. New imports now produce paragraph notes and `text_clean`.
3. Open PR with `notes_backfill.py` + admin endpoint + CLI + guardrail + tests. Merge. Deploy.
4. Mount the Railway leropa cache volume.
5. Operator: Postgres backup → dry run on one law → dry run on all laws → review reports → live run on all laws.

After step 5 completes, the database is ready for Spec 2 (the new diff backend).

## Open questions

- **Production database engine.** This spec assumes Postgres. If production is still SQLite the additive ALTERs are still fine (SQLite supports `ADD COLUMN`) but the `CREATE UNIQUE INDEX` with `COALESCE` expression needs verification. Confirm before opening the migration PR.
- **Subject parser pattern set.** The exact regex set should be derived from a sample of real `Note.subject` values from the production DB. The first dry run will surface anything missed; we add patterns and re-run.
- **Cache volume size.** ~100 laws × ~10 versions × ~500 KB HTML ≈ 500 MB. A 1 GB Railway volume is comfortable; confirm during infra step.
