# Smart Partial Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Speed up pipeline imports by synchronously importing only the needed version + current version, then background-importing the rest.

**Architecture:** Extract shared metadata/history logic from `import_law()` into a reusable helper. New `import_law_smart()` imports 2 versions synchronously, then schedules `import_remaining_versions()` as a one-off APScheduler job. A new `app/scheduler.py` module breaks the circular import between `main.py` and `pipeline_service.py`.

**Tech Stack:** Python, SQLAlchemy, APScheduler, SQLite (WAL mode), ChromaDB

**Spec:** `docs/superpowers/specs/2026-03-24-smart-partial-import-design.md`

---

### Task 1: Create `app/scheduler.py` and update `main.py`

**Files:**
- Create: `backend/app/scheduler.py`
- Modify: `backend/app/main.py:5,18,52-66`

- [ ] **Step 1: Create `backend/app/scheduler.py`**

```python
"""Shared APScheduler instance — importable from any module without circular deps."""

from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
```

- [ ] **Step 2: Update `backend/app/main.py` to import from `app.scheduler`**

Replace line 5 (`from apscheduler.schedulers.background import BackgroundScheduler`) and line 18 (`scheduler = BackgroundScheduler()`) with:

```python
from app.scheduler import scheduler
```

Remove the `from apscheduler...` import. Everything else stays the same — `scheduler.add_job(...)`, `scheduler.start()`, `scheduler.shutdown()` all work unchanged since it's the same object.

- [ ] **Step 3: Verify the app starts**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.main import app; print('OK')"`
Expected: `OK` (no import errors)

- [ ] **Step 4: Commit**

```bash
git add backend/app/scheduler.py backend/app/main.py
git commit -m "refactor: extract scheduler to app/scheduler.py to avoid circular imports"
```

---

### Task 2: Enable SQLite WAL mode

**Files:**
- Modify: `backend/app/database.py:6-10`

- [ ] **Step 1: Add WAL mode event listener in `backend/app/database.py`**

After the `engine = create_engine(...)` block (line 10), add:

```python
from sqlalchemy import event

@event.listens_for(engine, "connect")
def _set_sqlite_wal(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
```

This enables WAL mode on every new connection, allowing concurrent reads during writes.

- [ ] **Step 2: Verify WAL mode is active**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.database import engine; conn = engine.connect(); print(conn.execute(__import__('sqlalchemy').text('PRAGMA journal_mode')).scalar()); conn.close()"`
Expected: `wal`

- [ ] **Step 3: Commit**

```bash
git add backend/app/database.py
git commit -m "feat: enable SQLite WAL mode for concurrent read/write support"
```

---

### Task 3: Extract shared metadata/history logic into `_fetch_law_metadata()`

**Files:**
- Modify: `backend/app/services/leropa_service.py:501-568`

This extracts the duplicated code (fetch document, build history, cross-reference, build date_lookup) into a reusable helper that both `import_law()` and the new `import_law_smart()` will call.

- [ ] **Step 1: Add `_fetch_law_metadata()` helper before `import_law()`**

Insert at line ~499 (before `import_law`):

```python
def _fetch_law_metadata(ver_id: str) -> dict:
    """Fetch document metadata, history list, and date lookup for a law.

    Returns dict with keys: doc, articles_data, books_data, history, date_lookup, ver_id.
    Shared by import_law() and import_law_smart().
    """
    from app.services.fetcher import fetch_document

    result = fetch_document(ver_id)
    doc = result["document"]
    articles_data = result["articles"]
    books_data = result["books"]
    history = doc.get("history", [])

    # Reject documents with no content and no history versions
    if not articles_data and not books_data and not history:
        title = doc.get("title") or f"Document {ver_id}"
        raise ValueError(
            f"This document has no content: '{title}'. "
            f"Try importing a different version (e.g., the republished version)."
        )

    # Build date lookup from the history (consolidated versions)
    date_lookup: dict[str, datetime.date | None] = {}
    for entry in history:
        date_lookup[entry["ver_id"]] = _parse_date(entry.get("date"))

    # Cross-reference the newest history entry to discover newer consolidations
    if history:
        newest_known = history[0]["ver_id"]
        try:
            cross_result = fetch_document(newest_known)
            for entry in cross_result["document"].get("history", []):
                entry_vid = entry["ver_id"]
                if entry_vid not in date_lookup and entry_vid != ver_id:
                    date_lookup[entry_vid] = _parse_date(entry.get("date"))
                    history.append(entry)
        except Exception as e:
            logger.warning(f"Cross-reference failed for {newest_known}: {e}")

    # The forma de baza date is the law's original publication date
    date_lookup[ver_id] = _date_from_list(doc.get("date"))

    return {
        "doc": doc,
        "articles_data": articles_data,
        "books_data": books_data,
        "history": history,
        "date_lookup": date_lookup,
        "ver_id": ver_id,
    }
```

- [ ] **Step 2: Refactor `import_law()` to use `_fetch_law_metadata()`**

Replace lines 517-568 of `import_law()` (from `# First, fetch the document...` through `date_lookup[ver_id] = _date_from_list(...)`) with:

```python
    meta = _fetch_law_metadata(ver_id)
    doc = meta["doc"]
    history = meta["history"]
    date_lookup = meta["date_lookup"]
```

Everything after (the version importing loop, metadata application, etc.) stays the same.

- [ ] **Step 3: Verify `import_law()` still works**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.services.leropa_service import import_law; print('import_law loads OK')"`
Expected: `import_law loads OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/leropa_service.py
git commit -m "refactor: extract _fetch_law_metadata() helper from import_law()"
```

---

### Task 4: Implement `import_law_smart()`

**Files:**
- Modify: `backend/app/services/leropa_service.py` (add function after `_fetch_law_metadata`)

- [ ] **Step 1: Add `_apply_law_metadata()` helper**

Extract lines 636-665 of `import_law()` (metadata application + is_current marking) into a reusable helper. Insert after `_fetch_law_metadata()`:

```python
def _apply_law_metadata(db: Session, law: Law, doc: dict):
    """Apply metadata from the document to the Law record and mark is_current."""
    title = doc.get("title") or law.title
    law_number, law_year = _extract_law_number_and_year(title)
    law.title = title
    law.law_number = law_number
    law.law_year = law_year
    law.document_type = KIND_MAP.get(doc.get("kind", ""), "other")
    law.description = doc.get("description") or law.description
    law.keywords = doc.get("keywords") or law.keywords
    law.issuer = ", ".join(doc.get("issuer") or []) or law.issuer
    law.source_url = doc.get("source") or law.source_url

    # Mark the newest-dated version as current
    all_db_versions = (
        db.query(LawVersion).filter(LawVersion.law_id == law.id).all()
    )
    if all_db_versions:
        dated = [(v, v.date_in_force) for v in all_db_versions if v.date_in_force]
        for v in all_db_versions:
            v.is_current = False
        if dated:
            dated.sort(key=lambda x: x[1], reverse=True)
            dated[0][0].is_current = True
        else:
            all_db_versions[0].is_current = True

    # Auto-detect law status
    if not law.status_override:
        law.status = detect_law_status(db, law)
```

- [ ] **Step 2: Refactor `import_law()` to use `_apply_law_metadata()`**

Replace lines 636-665 in `import_law()` with:

```python
    _apply_law_metadata(db, law, doc)
```

- [ ] **Step 3: Add `import_law_smart()` function**

Insert after `_apply_law_metadata()`:

```python
def import_law_smart(
    db: Session,
    ver_id: str,
    primary_date: str | None = None,
) -> dict:
    """Import only the needed version + current version of a law.

    Used by the Q&A pipeline for fast imports. Returns info needed to
    schedule background import of remaining versions.

    Args:
        db: Database session.
        ver_id: The forma de baza ver_id from legislatie.just.ro.
        primary_date: ISO date string (YYYY-MM-DD) for the version the user needs.
                      If None, only the current version is imported.
    """
    global _stored_article_ids

    logger.info(f"Smart import for ver_id={ver_id}, primary_date={primary_date}")

    meta = _fetch_law_metadata(ver_id)
    doc = meta["doc"]
    history = meta["history"]
    date_lookup = meta["date_lookup"]

    # Build sorted list of (ver_id, date) for all versions with dates
    dated_versions = [
        (vid, d) for vid, d in date_lookup.items() if d is not None
    ]
    dated_versions.sort(key=lambda x: x[1])  # oldest first

    # Identify the current version (newest dated)
    current_vid = None
    if dated_versions:
        current_vid = dated_versions[-1][0]

    # Identify the needed version (newest with date <= primary_date)
    needed_vid = None
    if primary_date and dated_versions:
        pd = datetime.date.fromisoformat(primary_date)
        candidates = [(vid, d) for vid, d in dated_versions if d <= pd]
        if candidates:
            needed_vid = candidates[-1][0]  # newest that fits
        else:
            # All versions are newer than primary_date — import the oldest
            needed_vid = dated_versions[0][0]

    # Deduplicate: if needed == current, or no needed, just import current
    vids_to_import = set()
    if current_vid:
        vids_to_import.add(current_vid)
    if needed_vid:
        vids_to_import.add(needed_vid)
    if not vids_to_import:
        # No dated versions at all — import the forma de baza
        vids_to_import.add(ver_id)

    # Import the selected versions synchronously
    law = None
    for vid in vids_to_import:
        _stored_article_ids = set()
        law, _ = fetch_and_store_version(
            db, vid, law=law,
            override_date=date_lookup.get(vid),
        )

    # Apply metadata
    _apply_law_metadata(db, law, doc)

    # Create notification + audit log
    notification = Notification(
        title=f"Law imported: {law.title}",
        message=(
            f"Imported {len(vids_to_import)} version(s) of "
            f"Legea {law.law_number}/{law.law_year} (remaining versions importing in background)"
        ),
        notification_type="law_update",
    )
    db.add(notification)

    audit = AuditLog(
        action="import_law",
        module="legal_library",
        details=(
            f"Smart import: {law.title} — "
            f"{len(vids_to_import)} sync, {len(date_lookup) - len(vids_to_import)} background"
        ),
    )
    db.add(audit)

    # MUST commit before background job starts (so its session sees these versions)
    db.commit()

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

    _stored_article_ids = set()

    # Build list of remaining ver_ids for background import
    remaining = [vid for vid in date_lookup if vid not in vids_to_import]

    return {
        "law_id": law.id,
        "title": law.title,
        "law_number": law.law_number,
        "law_year": law.law_year,
        "versions_imported": len(vids_to_import),
        "remaining_ver_ids": remaining,
        "date_lookup": {k: v.isoformat() if v else None for k, v in date_lookup.items()},
    }
```

- [ ] **Step 4: Verify it loads**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.services.leropa_service import import_law_smart; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/leropa_service.py
git commit -m "feat: add import_law_smart() for fast 2-version pipeline imports"
```

---

### Task 5: Implement `import_remaining_versions()`

**Files:**
- Modify: `backend/app/services/leropa_service.py` (add function after `import_law_smart`)

- [ ] **Step 1: Add `import_remaining_versions()` function**

```python
def import_remaining_versions(
    law_id: int,
    remaining_ver_ids: list[str],
    date_lookup_iso: dict[str, str | None],
    rate_limit_delay: float = 2.0,
):
    """Background job: import remaining versions of a law.

    Runs in a separate thread via APScheduler. Creates its own DB session.
    Handles SQLite lock contention with retries.
    """
    global _stored_article_ids
    from app.database import SessionLocal
    from sqlalchemy.exc import OperationalError

    logger.info(
        f"Background import starting for law_id={law_id}: "
        f"{len(remaining_ver_ids)} versions"
    )

    db = SessionLocal()
    try:
        law = db.get(Law, law_id)
        if not law:
            logger.error(f"Background import: law_id={law_id} not found")
            return

        # Convert ISO date strings back to date objects
        date_lookup: dict[str, datetime.date | None] = {}
        for vid, iso_str in date_lookup_iso.items():
            date_lookup[vid] = (
                datetime.date.fromisoformat(iso_str) if iso_str else None
            )

        imported_count = 0
        for vid in remaining_ver_ids:
            retries = 0
            while retries < 3:
                try:
                    _stored_article_ids = set()
                    _, version = fetch_and_store_version(
                        db, vid, law=law,
                        rate_limit_delay=rate_limit_delay,
                        override_date=date_lookup.get(vid),
                    )
                    imported_count += 1
                    logger.info(
                        f"Background import: {vid} "
                        f"({imported_count}/{len(remaining_ver_ids)})"
                    )
                    break  # success
                except OperationalError as e:
                    if "database is locked" in str(e):
                        retries += 1
                        wait = 2 ** (retries - 1)  # 1s, 2s, 4s
                        logger.warning(
                            f"SQLite locked, retry {retries}/3 in {wait}s"
                        )
                        db.rollback()
                        time.sleep(wait)
                    else:
                        raise
                except Exception as e:
                    logger.error(f"Background import failed for {vid}: {e}")
                    break

        # Re-mark is_current on newest version
        all_versions = (
            db.query(LawVersion).filter(LawVersion.law_id == law.id).all()
        )
        if all_versions:
            dated = [(v, v.date_in_force) for v in all_versions if v.date_in_force]
            for v in all_versions:
                v.is_current = False
            if dated:
                dated.sort(key=lambda x: x[1], reverse=True)
                dated[0][0].is_current = True

        if not law.status_override:
            law.status = detect_law_status(db, law)

        db.commit()

        # Index new versions into ChromaDB
        try:
            from app.services.chroma_service import index_law_version as chroma_index
            for v in all_versions:
                chroma_index(db, law.id, v.id)
        except Exception as e:
            logger.warning(f"Background ChromaDB indexing failed: {e}")

        # Rebuild BM25/FTS5 index
        try:
            from app.services.bm25_service import rebuild_fts_index
            rebuild_fts_index(db)
        except Exception as e:
            logger.warning(f"Background FTS5 rebuild failed: {e}")

        _stored_article_ids = set()

        logger.info(
            f"Background import complete for law_id={law_id}: "
            f"{imported_count}/{len(remaining_ver_ids)} versions imported"
        )

    except Exception as e:
        logger.exception(f"Background import error for law_id={law_id}: {e}")
    finally:
        db.close()
```

- [ ] **Step 2: Verify it loads**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.services.leropa_service import import_remaining_versions; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/leropa_service.py
git commit -m "feat: add import_remaining_versions() background job"
```

---

### Task 6: Update `resume_pipeline` to use smart import + background scheduling

**Files:**
- Modify: `backend/app/services/pipeline_service.py:312-333`

- [ ] **Step 1: Update the import section in `resume_pipeline()`**

Replace the current import logic (lines 312-333) with:

```python
        # Handle imports if user approved
        for law_key, decision in import_decisions.items():
            if decision in ("import", "import_version"):
                try:
                    law_number, law_year = law_key.split("/")
                    from app.services.leropa_service import import_law_smart, import_remaining_versions
                    from app.services.fetcher import search_legislatie
                    from app.scheduler import scheduler

                    ver_id = search_legislatie(law_number, law_year)
                    if ver_id:
                        yield {"type": "step", "step": 25, "name": "importing", "status": "running",
                               "data": {"importing": law_key}}

                        result = import_law_smart(
                            db, ver_id,
                            primary_date=state.get("primary_date"),
                        )
                        # import_law_smart commits internally
                        state["flags"].append(f"Imported {law_key} from legislatie.just.ro")

                        # Rebuild FTS5 so hybrid retrieval finds the just-imported articles
                        try:
                            from app.services.bm25_service import rebuild_fts_index
                            rebuild_fts_index(db)
                        except Exception as e:
                            logger.warning(f"FTS5 rebuild failed (non-fatal): {e}")

                        # Schedule background import of remaining versions
                        if result.get("remaining_ver_ids"):
                            scheduler.add_job(
                                import_remaining_versions,
                                args=[
                                    result["law_id"],
                                    result["remaining_ver_ids"],
                                    result["date_lookup"],
                                ],
                                trigger="date",
                                id=f"bg_import_{law_key}",
                                replace_existing=True,
                            )
                            state["flags"].append(
                                f"Background: importing {len(result['remaining_ver_ids'])} "
                                f"remaining versions of {law_key}"
                            )

                        yield {"type": "step", "step": 25, "name": "importing", "status": "done",
                               "data": {"imported": law_key}}
                    else:
                        state["flags"].append(f"Could not find {law_key} on legislatie.just.ro — continuing without")
                except Exception as e:
                    logger.warning(f"Failed to import {law_key}: {e}")
                    state["flags"].append(f"Import failed for {law_key}: {str(e)[:100]}")
```

- [ ] **Step 2: Verify the module loads without circular imports**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.services.pipeline_service import resume_pipeline; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: use smart import + background scheduling in resume_pipeline"
```

---

### Task 7: Update `import_law()` to use shared helpers

**Files:**
- Modify: `backend/app/services/leropa_service.py:501-703` (the existing `import_law` function)

This task refactors `import_law()` to use `_fetch_law_metadata()` and `_apply_law_metadata()` so the code isn't duplicated. The behavior stays identical.

- [ ] **Step 1: Refactor `import_law()` to use shared helpers**

The full refactored function should be:

```python
def import_law(
    db: Session,
    ver_id: str,
    import_history: bool = True,
    rate_limit_delay: float = 2.0,
) -> dict:
    """Import a law and optionally all its historical versions.

    This is the main entry point for importing a law from the Legal Library UI.
    Returns a summary dict.
    """
    global _stored_article_ids
    _stored_article_ids = set()

    logger.info(f"Starting import for ver_id={ver_id}")

    meta = _fetch_law_metadata(ver_id)
    doc = meta["doc"]
    history = meta["history"]
    date_lookup = meta["date_lookup"]

    if not import_history and history:
        # Find the newest consolidated version by date
        dated_entries = [
            (entry, _parse_date(entry.get("date")))
            for entry in history
            if entry.get("ver_id") and _parse_date(entry.get("date"))
        ]
        if dated_entries:
            dated_entries.sort(key=lambda x: x[1], reverse=True)
            newest_entry = dated_entries[0][0]
            current_ver_id = newest_entry["ver_id"]
        else:
            current_ver_id = history[0]["ver_id"]

        logger.info(
            f"Importing current version only: {current_ver_id} "
            f"(date={date_lookup.get(current_ver_id)})"
        )
        _stored_article_ids = set()
        law, current_version = fetch_and_store_version(
            db, current_ver_id,
            override_date=date_lookup.get(current_ver_id),
        )
        versions_imported = [current_ver_id]
    else:
        # Import the forma de baza (original text)
        law, base_version = fetch_and_store_version(
            db, ver_id, override_date=date_lookup.get(ver_id)
        )
        versions_imported = [ver_id]

        # Import all consolidated versions
        if history:
            logger.info(f"Importing {len(history)} consolidated versions")
            for entry in history:
                hist_ver_id = entry.get("ver_id")
                if not hist_ver_id or hist_ver_id == ver_id:
                    continue

                try:
                    _stored_article_ids = set()
                    _, hist_version = fetch_and_store_version(
                        db, hist_ver_id, law=law,
                        rate_limit_delay=rate_limit_delay,
                        override_date=date_lookup.get(hist_ver_id),
                    )
                    versions_imported.append(hist_ver_id)
                    logger.info(
                        f"Imported version {hist_ver_id} "
                        f"(date={date_lookup.get(hist_ver_id)}, "
                        f"{len(versions_imported)}/{len(history) + 1})"
                    )
                except Exception as e:
                    logger.error(f"Failed to import version {hist_ver_id}: {e}")
                    continue

    # Apply metadata using shared helper
    _apply_law_metadata(db, law, doc)

    # Create notification
    notification = Notification(
        title=f"Law imported: {law.title}",
        message=f"Imported {len(versions_imported)} version(s) of Legea {law.law_number}/{law.law_year}",
        notification_type="law_update",
    )
    db.add(notification)

    # Audit log
    audit = AuditLog(
        action="import_law",
        module="legal_library",
        details=f"Imported {law.title} with {len(versions_imported)} versions",
    )
    db.add(audit)

    db.commit()

    # Index articles into ChromaDB for semantic search
    try:
        from app.services.chroma_service import index_law_version as chroma_index
        all_db_versions = (
            db.query(LawVersion).filter(LawVersion.law_id == law.id).all()
        )
        for v in all_db_versions:
            chroma_index(db, law.id, v.id)
    except Exception as e:
        logger.warning(f"ChromaDB indexing failed (non-fatal): {e}")

    _stored_article_ids = set()

    return {
        "law_id": law.id,
        "title": law.title,
        "law_number": law.law_number,
        "law_year": law.law_year,
        "versions_imported": len(versions_imported),
        "version_ids": versions_imported,
    }
```

- [ ] **Step 2: Verify it loads**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.services.leropa_service import import_law; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/leropa_service.py
git commit -m "refactor: update import_law() to use shared metadata helpers"
```

---

### Task 8: Manual smoke test

- [ ] **Step 1: Start the backend**

Run: `cd /Users/anaandrei/projects/legalese/backend && uvicorn app.main:app --reload`

- [ ] **Step 2: Verify Legal Library import still works**

Open the Legal Library in the browser, import a small law (e.g., a recent OUG with few versions). Verify it imports fully with all versions.

- [ ] **Step 3: Verify pipeline smart import works**

In the Legal Assistant, ask a question about a law not in the library (e.g., one of the laws that triggered the original bug). When prompted to import, click "import". Verify:
- The response comes back quickly (only 2 versions imported synchronously)
- The flags show "Background: importing N remaining versions..."
- Check the backend logs for "Background import complete" messages
- After a minute, check the Legal Library — all versions should be present

- [ ] **Step 4: Verify edge case — follow-up question**

While background import is still running (or after), ask another question about the same law but a different date. Verify the pipeline finds the needed version (either already imported by background, or imports it synchronously).
