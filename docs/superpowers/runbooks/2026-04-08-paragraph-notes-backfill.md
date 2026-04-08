# Runbook: Paragraph-Notes Backfill

**Owner:** Ana
**Spec:** `docs/superpowers/specs/2026-04-08-paragraph-notes-and-backfill-design.md`
**Plan:** `docs/superpowers/plans/2026-04-08-paragraph-notes-and-backfill.md`
**Last reviewed:** 2026-04-08

## What this does

Inserts paragraph-level amendment notes and populates `text_clean` for every existing `LawVersion` in production. Fully additive — never modifies or deletes existing `laws`, `law_versions`, `articles`, `paragraphs`, or `subparagraphs` rows (enforced by a runtime SQLAlchemy `before_flush` guardrail).

## Pre-flight checklist

- [ ] **Migration deployed.** Confirm `paragraph_id`, `note_source_id`, and `text_clean` columns exist in production. From a Railway shell:
  ```bash
  railway run -- sqlite3 /data/themis.db ".schema amendment_notes"
  railway run -- sqlite3 /data/themis.db ".schema articles" | grep text_clean
  railway run -- sqlite3 /data/themis.db ".schema paragraphs" | grep text_clean
  ```
  Each must show the expected new column.

- [ ] **Importer change deployed.** Confirm that any law imported after the deploy populates paragraph-level notes:
  ```bash
  railway run -- sqlite3 /data/themis.db "SELECT COUNT(*) FROM amendment_notes WHERE paragraph_id IS NOT NULL;"
  ```
  This will be 0 before the backfill — that is expected and proves nothing has been written yet. After the backfill it should be > 0.

- [ ] **Snapshot the SQLite file.** This is the rollback safety net.
  ```bash
  railway run -- cp /data/themis.db /data/themis-pre-backfill-$(date +%F).db
  ```
  Optionally download a copy locally:
  ```bash
  railway volume download <volume-id> /data/themis-pre-backfill-YYYY-MM-DD.db ./backups/
  ```

- [ ] **(Recommended) Mount a Railway volume at `/root/.leropa`** so the leropa HTML cache survives container restarts. The backfill works without it but will hit legislatie.just.ro for every fetch. See the spec for sizing (~1 GB).

## Run order

### 1. Dry run on one small law

Pick the smallest law in the library — go to `/laws` and find one with ≤3 versions and a short article list. Note its `id`.

```bash
# Locally, against a downloaded copy of the prod DB:
cd backend
uv run python scripts/backfill_paragraph_notes.py --law-id <ID> --db /path/to/prod-snapshot.db
```

Review the report printed at the end. Expected:
- `versions_processed` equals the law's version count.
- `paragraph_notes_to_insert` is > 0 if the law has any modification history.
- `unknown_paragraph_labels` is small or empty. A handful of warnings is acceptable; many indicate parser drift and need investigation before the full run.
- `errors` is empty.

### 2. Dry run on all laws

```bash
uv run python scripts/backfill_paragraph_notes.py --db /path/to/prod-snapshot.db
```

Read the full report. Expected outcomes:
- `versions_failed == 0`. Any failure means we investigate before going live.
- `unknown_paragraph_labels` count: anything over ~5% of total notes is a red flag — likely a missing pattern in `note_subject_parser` (used by Spec 2) or a parser divergence. Investigate, add patterns, re-run.
- `errors` is empty.

### 3. Live run on production

Either via the admin endpoint:

```bash
curl -X POST https://<your-prod-url>/api/admin/backfill/notes \
     -H "Authorization: Bearer <admin-token>" \
     -H "Content-Type: application/json" \
     -d '{"dry_run": false}'
```

…or via the CLI on a Railway shell:

```bash
railway run -- bash -c "cd backend && uv run python scripts/backfill_paragraph_notes.py --no-dry-run --db /data/themis.db"
```

The endpoint is synchronous; for ~100 laws this may take 10–30 minutes depending on network. If it times out, simply re-run — the job is idempotent and will skip versions that have already been backfilled.

### 4. Verify

From a Railway shell:

```bash
railway run -- sqlite3 /data/themis.db <<'SQL'
-- Should be > 0 after the backfill
SELECT COUNT(*) FROM amendment_notes WHERE paragraph_id IS NOT NULL;

-- Should be roughly equal to the total articles count
SELECT
  (SELECT COUNT(*) FROM articles) AS total_articles,
  (SELECT COUNT(*) FROM articles WHERE text_clean IS NOT NULL) AS articles_with_clean;

-- Should be roughly equal to the total paragraphs count
SELECT
  (SELECT COUNT(*) FROM paragraphs) AS total_paragraphs,
  (SELECT COUNT(*) FROM paragraphs WHERE text_clean IS NOT NULL) AS paragraphs_with_clean;
SQL
```

A small gap between `total_*` and `*_with_clean` is acceptable — those are the rows where `(article.label, paragraph.label)` did not match the freshly-parsed leropa output (parser drift). The dry-run report would have flagged the same labels in `unknown_paragraph_labels`.

## Rollback

The backfill is strictly additive, so rollback is "restore the snapshot from the pre-flight checklist".

```bash
railway run -- cp /data/themis-pre-backfill-YYYY-MM-DD.db /data/themis.db
# then restart the backend service via the Railway dashboard or:
railway redeploy
```

No data is destroyed by re-running the backfill on the restored DB — it remains idempotent.

## Why this is safe to run

- **Read-only on existing content.** The backfill never UPDATEs or DELETEs any row in `laws`, `law_versions`, `articles`, `paragraphs`, or `subparagraphs`. The only mutation it performs on existing rows is writing the new `text_clean` column where it is currently NULL.
- **Guardrail enforced at runtime.** A SQLAlchemy `before_flush` listener installed for the duration of the job aborts immediately with `BackfillSafetyError` if any forbidden mutation is detected. This is belt-and-braces over the algorithm.
- **Per-version transactions.** A failure on one version logs and continues to the next. One bad version cannot poison the rest.
- **Idempotent.** A unique partial index `ux_amendment_notes_dedupe` (on `(article_id, COALESCE(paragraph_id, 0), note_source_id) WHERE note_source_id IS NOT NULL`) blocks duplicate inserts at the DB level. `text_clean` writes are gated on `IS NULL` so they're a no-op on the second pass. Re-running the backfill is safe.
- **Dry-run by default.** Both the endpoint and the CLI default to dry-run mode. The operator must pass `dry_run=false` (endpoint) or `--no-dry-run` (CLI) to actually persist anything.

## What this does NOT do

- It does not change the diff endpoint or any user-visible behaviour. Spec 2 (the new diff backend) is the consumer of the data this backfill produces.
- It does not re-import any law.
- It does not delete or modify any pre-existing amendment note row.
- It does not run automatically on deploy.
