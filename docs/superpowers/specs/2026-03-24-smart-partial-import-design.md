# Smart Partial Import — Design Spec

**Date:** 2026-03-24
**Goal:** Speed up pipeline imports by only synchronously importing the 2 versions needed (requested date + current), then background-importing the rest.

---

## Problem

When the pipeline imports a law during Q&A, it imports ALL historical versions synchronously (`import_history=True`). For laws like Legea 31/1990 this can mean 30+ versions, each requiring an HTTP request + parse + store + embed. The user waits minutes for an answer.

## Solution

### Synchronous Path (blocks pipeline)

New function `import_law_smart(db, ver_id, primary_date)` in `leropa_service.py`:

1. Fetch document metadata + full history list (1 HTTP request to legislatie.just.ro)
2. Cross-reference newest history entry to discover all versions (existing logic)
3. Build `date_lookup` mapping ver_id → date (existing logic)
4. Identify 2 versions to import now:
   - **Needed version**: newest history entry with `date <= primary_date`
   - **Current version**: newest history entry overall
   - If these are the same version, import only 1
   - If no version matches `primary_date` (all versions are newer), import the oldest + current
   - If a history entry has no date (`date_in_force` would be None), skip it for date matching — `law_mapping.py` requires `date_in_force` to be set for version-specific queries
5. Import those via `fetch_and_store_version` (already handles duplicates by `ver_id`)
6. Reset `_stored_article_ids = set()` before each `fetch_and_store_version` call (this module-global set tracks deduplication within a single import session)
7. Apply law metadata (title, number, year, type, etc.)
8. Mark the newest-dated version as `is_current=True`
9. Create notification + audit log
10. Commit the transaction — **must happen before background job is scheduled** so the background job's separate DB session can see the committed versions and skip duplicates
11. Index imported versions into ChromaDB
12. Return: `{ law_id, needed_version_id, remaining_ver_ids: [...], date_lookup: {...} }`

Note: for laws with no history (only forma de baza), `remaining_ver_ids` will be empty and no background job is scheduled. This degenerates to importing a single version, which is expected.

### Background Path (fire-and-forget)

New function `import_remaining_versions(law_id, ver_id_list, date_lookup)` in `leropa_service.py`:

1. Create own DB session via `SessionLocal()` (cannot reuse the pipeline's session across threads)
2. Re-query the `Law` object from own session: `law = db.query(Law).get(law_id)` (ORM objects cannot cross session boundaries)
3. For each ver_id in the list:
   - Reset `_stored_article_ids = set()` before each call (thread-safety: this module-global set would corrupt if shared with a concurrent foreground import)
   - Call `fetch_and_store_version(db, ver_id, law=law, override_date=date_lookup.get(ver_id), rate_limit_delay=2.0)` — skips if already exists
4. Re-mark `is_current` on the newest version
5. Re-detect law status
6. Commit
7. Index new versions into ChromaDB
8. Rebuild BM25/FTS5 index
9. Close DB session in `finally` block

Scheduled via APScheduler `scheduler.add_job(fn, trigger="date")` (runs once, immediately, in background thread).

### Scheduler Access (avoiding circular imports)

The scheduler lives in `app/main.py`. Importing it directly from `pipeline_service.py` would create a circular import (`main → routers → services → main`).

Solution: create `backend/app/scheduler.py` that owns the `BackgroundScheduler` instance. Both `main.py` and `pipeline_service.py` import from it.

```python
# app/scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
scheduler = BackgroundScheduler()
```

Update `main.py` to import from `app.scheduler` instead of creating its own.

### SQLite Write Contention

SQLite serializes writes. The background import thread may conflict with foreground writes. Mitigations:

1. Enable WAL mode at startup: `PRAGMA journal_mode=WAL` — allows concurrent reads during writes, reduces lock contention
2. Add retry logic in the background function: catch `OperationalError: database is locked`, retry with exponential backoff (3 retries, 1s/2s/4s delays)
3. The 2s rate_limit_delay between version imports naturally reduces contention

### Pipeline Integration

In `resume_pipeline` (`pipeline_service.py`), replace:
```python
from app.services.leropa_service import import_law as do_import
...
do_import(db, ver_id, import_history=True)
db.commit()
```
With:
```python
from app.services.leropa_service import import_law_smart, import_remaining_versions
from app.scheduler import scheduler
...
result = import_law_smart(db, ver_id, primary_date=state.get("primary_date"))
# import_law_smart commits internally

# Schedule background import of remaining versions
if result.get("remaining_ver_ids"):
    scheduler.add_job(
        import_remaining_versions,
        args=[result["law_id"], result["remaining_ver_ids"], result["date_lookup"]],
        trigger="date",  # run once, now
        id=f"bg_import_{law_key}",
        replace_existing=True,
    )
```

### Edge Case: Follow-up Before Background Finishes

No special handling needed. The pipeline always:
1. Runs `_step2_law_mapping` which checks DB for version availability
2. If the needed version is there (background already imported it) → uses it
3. If not → triggers `import_law_smart` again for that date, which imports just what's needed
4. `fetch_and_store_version` skips duplicates by `ver_id`

## Files Changed

1. **`backend/app/scheduler.py`** — New file, owns the `BackgroundScheduler` instance
2. **`backend/app/services/leropa_service.py`** — Add `import_law_smart()` and `import_remaining_versions()`
3. **`backend/app/services/pipeline_service.py`** — Update `resume_pipeline` to use smart import + schedule background
4. **`backend/app/main.py`** — Import scheduler from `app.scheduler` instead of creating locally
5. **`backend/app/database.py`** — Add WAL mode pragma at engine creation

## What Does NOT Change

- Manual import from Legal Library still uses `import_law(import_history=True)` — user explicitly chose full import
- The existing `import_law()` function is untouched
- Pipeline gate logic (already fixed in this session) stays the same
- Frontend — no changes needed
