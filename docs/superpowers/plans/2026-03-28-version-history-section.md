# Version History Section Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current scattered version UI on the law detail page with a unified version history section containing an update banner, imported versions table, and unimported versions table.

**Architecture:** Backend gets a new `diff_summary` JSON column on `LawVersion` plus a helper function to compute it. A backfill startup hook populates existing rows. The frontend replaces `VersionsSection`, the inline versions list, and `CheckUpdatesButton` with three new components matching the design mockups.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), Next.js 16/React 19/Tailwind CSS 4 (frontend), SQLite (database)

---

## File Map

### Backend
| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `backend/app/models/law.py:85-109` | Add `diff_summary` JSON column to `LawVersion` |
| Modify | `backend/app/routers/laws.py:400-410` | Include `diff_summary` in version response |
| Modify | `backend/app/routers/laws.py:460-498` | Compute diff summary after single-version import |
| Modify | `backend/app/routers/laws.py:501-553` | Compute diff summaries after bulk import |
| Create | `backend/app/services/diff_summary.py` | Standalone diff summary computation function |
| Create | `backend/scripts/backfill_diff_summaries.py` | One-time backfill script |
| Modify | `backend/app/main.py:42-56` | Add backfill call on startup |
| Create | `backend/tests/test_diff_summary.py` | Tests for diff summary computation |

### Frontend
| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `frontend/src/lib/api.ts:145-152` | Add `diff_summary` to `LawVersionSummary` type |
| Modify | `frontend/src/app/laws/[id]/page.tsx` | Remove inline versions list and CheckUpdatesButton, wire new section |
| Rewrite | `frontend/src/app/laws/[id]/versions-section.tsx` | Orchestrator: banner + imported table + unimported table |
| Create | `frontend/src/app/laws/[id]/update-banner.tsx` | Update banner with auto-check and 1h cache |
| Create | `frontend/src/app/laws/[id]/imported-versions-table.tsx` | Imported versions table with collapse |
| Create | `frontend/src/app/laws/[id]/unimported-versions-table.tsx` | Unimported versions table with import actions |
| Delete | `frontend/src/app/laws/[id]/check-updates-button.tsx` | Absorbed into update-banner |

---

## Task 1: Add `diff_summary` column to LawVersion model

**Files:**
- Modify: `backend/app/models/law.py:85-109`

- [ ] **Step 1: Add the JSON import and column**

In `backend/app/models/law.py`, add `JSON` to the SQLAlchemy imports on line 4, then add the `diff_summary` column to `LawVersion`:

```python
# line 4 — add JSON to existing import
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
```

```python
# Inside class LawVersion, after is_current (line 98), add:
    diff_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
```

- [ ] **Step 2: Verify the app starts and the column is created**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.database import Base, engine; from app.models.law import LawVersion; Base.metadata.create_all(bind=engine); print('OK')"`

Expected: `OK` (SQLite adds the column via `create_all` since it uses `CREATE TABLE IF NOT EXISTS` — but for existing tables, SQLite won't add new columns automatically).

Since SQLite `create_all` doesn't alter existing tables, we also need a one-time `ALTER TABLE` statement. Add this to the startup in a later task.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/law.py
git commit -m "feat: add diff_summary JSON column to LawVersion model"
```

---

## Task 2: Create diff summary computation service

**Files:**
- Create: `backend/app/services/diff_summary.py`
- Create: `backend/tests/test_diff_summary.py`

- [ ] **Step 1: Write the test file**

Create `backend/tests/test_diff_summary.py`:

```python
"""Tests for diff summary computation."""
import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.law import Article, Law, LawVersion


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def law_with_two_versions(db):
    """Create a law with two versions, each having articles."""
    law = Law(title="Test Law", law_number="1", law_year=2025)
    db.add(law)
    db.flush()

    v1 = LawVersion(
        law_id=law.id,
        ver_id="100",
        date_in_force=datetime.date(2025, 1, 1),
        state="actual",
        is_current=False,
    )
    db.add(v1)
    db.flush()

    # v1 articles: art 1, art 2, art 3
    for num, text in [("1", "First article text"), ("2", "Second article"), ("3", "Third article")]:
        db.add(Article(law_version_id=v1.id, article_number=num, full_text=text, order_index=int(num)))
    db.flush()

    v2 = LawVersion(
        law_id=law.id,
        ver_id="200",
        date_in_force=datetime.date(2025, 6, 1),
        state="actual",
        is_current=True,
    )
    db.add(v2)
    db.flush()

    # v2 articles: art 1 (modified), art 2 (unchanged), art 4 (added), art 3 removed
    for num, text in [("1", "First article text AMENDED"), ("2", "Second article"), ("4", "Brand new article")]:
        db.add(Article(law_version_id=v2.id, article_number=num, full_text=text, order_index=int(num)))
    db.flush()

    return law, v1, v2


def test_compute_diff_summary(db, law_with_two_versions):
    from app.services.diff_summary import compute_diff_summary

    law, v1, v2 = law_with_two_versions
    result = compute_diff_summary(db, v2)

    assert result == {"modified": 1, "added": 1, "removed": 1}


def test_compute_diff_summary_no_predecessor(db):
    """First version should return None (no predecessor to diff against)."""
    from app.services.diff_summary import compute_diff_summary

    law = Law(title="Test", law_number="2", law_year=2025)
    db.add(law)
    db.flush()

    v1 = LawVersion(
        law_id=law.id, ver_id="300",
        date_in_force=datetime.date(2025, 1, 1),
        state="actual", is_current=True,
    )
    db.add(v1)
    db.flush()

    result = compute_diff_summary(db, v1)
    assert result is None


def test_compute_diff_summary_identical_versions(db):
    """Two identical versions should have all zeros."""
    from app.services.diff_summary import compute_diff_summary

    law = Law(title="Test", law_number="3", law_year=2025)
    db.add(law)
    db.flush()

    v1 = LawVersion(law_id=law.id, ver_id="400", date_in_force=datetime.date(2025, 1, 1), state="actual")
    db.add(v1)
    db.flush()
    db.add(Article(law_version_id=v1.id, article_number="1", full_text="Same text", order_index=0))
    db.flush()

    v2 = LawVersion(law_id=law.id, ver_id="500", date_in_force=datetime.date(2025, 6, 1), state="actual")
    db.add(v2)
    db.flush()
    db.add(Article(law_version_id=v2.id, article_number="1", full_text="Same text", order_index=0))
    db.flush()

    result = compute_diff_summary(db, v2)
    assert result == {"modified": 0, "added": 0, "removed": 0}


def test_backfill_diff_summaries(db, law_with_two_versions):
    """Backfill should populate diff_summary for all versions."""
    from app.services.diff_summary import backfill_diff_summaries

    law, v1, v2 = law_with_two_versions
    count = backfill_diff_summaries(db)

    assert count == 1  # Only v2 gets a summary (v1 has no predecessor)
    db.refresh(v2)
    assert v2.diff_summary == {"modified": 1, "added": 1, "removed": 1}
    db.refresh(v1)
    assert v1.diff_summary is None
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -m pytest tests/test_diff_summary.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.diff_summary'`

- [ ] **Step 3: Implement the service**

Create `backend/app/services/diff_summary.py`:

```python
"""Compute and store article-level diff summaries between consecutive law versions."""
import logging

from sqlalchemy.orm import Session

from app.models.law import Article, Law, LawVersion

logger = logging.getLogger(__name__)


def compute_diff_summary(db: Session, version: LawVersion) -> dict | None:
    """Compute diff summary for a version against its predecessor.

    Returns {"modified": N, "added": N, "removed": N} or None if no predecessor.
    The predecessor is the version of the same law with the closest earlier date_in_force.
    """
    if not version.date_in_force:
        return None

    # Find the previous version (closest earlier date)
    prev = (
        db.query(LawVersion)
        .filter(
            LawVersion.law_id == version.law_id,
            LawVersion.id != version.id,
            LawVersion.date_in_force < version.date_in_force,
        )
        .order_by(LawVersion.date_in_force.desc())
        .first()
    )

    if not prev:
        return None

    # Get articles for both versions
    arts_prev = {
        a.article_number: a.full_text
        for a in db.query(Article).filter(Article.law_version_id == prev.id).all()
    }
    arts_curr = {
        a.article_number: a.full_text
        for a in db.query(Article).filter(Article.law_version_id == version.id).all()
    }

    all_numbers = set(arts_prev.keys()) | set(arts_curr.keys())

    modified = 0
    added = 0
    removed = 0

    for num in all_numbers:
        in_prev = num in arts_prev
        in_curr = num in arts_curr
        if in_prev and not in_curr:
            removed += 1
        elif in_curr and not in_prev:
            added += 1
        elif arts_prev[num].strip() != arts_curr[num].strip():
            modified += 1

    return {"modified": modified, "added": added, "removed": removed}


def backfill_diff_summaries(db: Session) -> int:
    """Compute diff_summary for all LawVersion rows that don't have one yet.

    Returns the number of versions updated.
    """
    # Get all versions ordered by law and date, where diff_summary is null
    versions = (
        db.query(LawVersion)
        .filter(LawVersion.diff_summary.is_(None))
        .order_by(LawVersion.law_id, LawVersion.date_in_force)
        .all()
    )

    count = 0
    for v in versions:
        summary = compute_diff_summary(db, v)
        if summary is not None:
            v.diff_summary = summary
            count += 1

    db.flush()
    return count
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -m pytest tests/test_diff_summary.py -v`

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/diff_summary.py backend/tests/test_diff_summary.py
git commit -m "feat: add diff summary computation service with tests"
```

---

## Task 3: Add startup migration and backfill hook

**Files:**
- Modify: `backend/app/main.py:42-56`

Since SQLite's `create_all` doesn't add columns to existing tables, we need an `ALTER TABLE` on startup. This is the same pattern used elsewhere in the codebase.

- [ ] **Step 1: Add migration and backfill to startup**

In `backend/app/main.py`, inside the `lifespan` function's `try` block (after the existing seed calls, around line 54), add:

```python
        # Add diff_summary column if it doesn't exist (SQLite migration)
        from sqlalchemy import inspect, text
        inspector = inspect(engine)
        columns = [c["name"] for c in inspector.get_columns("law_versions")]
        if "diff_summary" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE law_versions ADD COLUMN diff_summary JSON"))
            logger.info("Added diff_summary column to law_versions")

        # Backfill diff summaries for existing versions
        from app.services.diff_summary import backfill_diff_summaries
        backfilled = backfill_diff_summaries(db)
        if backfilled:
            db.commit()
            logger.info(f"Backfilled diff_summary for {backfilled} versions")
```

- [ ] **Step 2: Verify the app starts successfully**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "import asyncio; from app.main import app; print('OK')"`

Expected: `OK` (no import errors)

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: add diff_summary column migration and backfill on startup"
```

---

## Task 4: Include `diff_summary` in API responses and compute on import

**Files:**
- Modify: `backend/app/routers/laws.py:400-410` (GET law detail — version response)
- Modify: `backend/app/routers/laws.py:460-498` (single import)
- Modify: `backend/app/routers/laws.py:501-553` (bulk import)

- [ ] **Step 1: Add `diff_summary` to the GET law detail response**

In `backend/app/routers/laws.py`, in the `get_law` function, modify the version dict (around line 400-410). Change from:

```python
        "versions": [
            {
                "id": v.id,
                "ver_id": v.ver_id,
                "date_in_force": str(v.date_in_force) if v.date_in_force else None,
                "date_imported": str(v.date_imported),
                "state": v.state,
                "is_current": v.is_current,
            }
            for v in sorted(law.versions, key=lambda v: v.date_in_force or "", reverse=True)
        ],
```

To:

```python
        "versions": [
            {
                "id": v.id,
                "ver_id": v.ver_id,
                "date_in_force": str(v.date_in_force) if v.date_in_force else None,
                "date_imported": str(v.date_imported),
                "state": v.state,
                "is_current": v.is_current,
                "diff_summary": v.diff_summary,
            }
            for v in sorted(law.versions, key=lambda v: v.date_in_force or "", reverse=True)
        ],
```

- [ ] **Step 2: Compute diff summary after single-version import**

In the `import_known_version` function (around line 496, after `db.commit()`), add diff summary computation. Insert before the return statement:

```python
    # Compute diff summary for the new version (and update the next version if it exists)
    from app.services.diff_summary import compute_diff_summary
    new_version.diff_summary = compute_diff_summary(db, new_version)

    # Also recompute the version right after this one (if any), since its predecessor changed
    next_ver = (
        db.query(LawVersion)
        .filter(
            LawVersion.law_id == law_id,
            LawVersion.id != new_version.id,
            LawVersion.date_in_force > new_version.date_in_force if new_version.date_in_force else False,
        )
        .order_by(LawVersion.date_in_force.asc())
        .first()
    )
    if next_ver:
        next_ver.diff_summary = compute_diff_summary(db, next_ver)

    db.commit()
```

- [ ] **Step 3: Compute diff summaries after bulk import**

In the `import_all_missing` function (around line 551, after `db.commit()`), add:

```python
    # Backfill diff summaries for all versions of this law
    from app.services.diff_summary import backfill_diff_summaries
    backfilled = backfill_diff_summaries(db)
    if backfilled:
        db.commit()
```

- [ ] **Step 4: Verify no syntax errors**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.routers.laws import router; print('OK')"`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/laws.py
git commit -m "feat: include diff_summary in API response, compute on import"
```

---

## Task 5: Update frontend `LawVersionSummary` type

**Files:**
- Modify: `frontend/src/lib/api.ts:145-152`

- [ ] **Step 1: Add `diff_summary` to the type**

In `frontend/src/lib/api.ts`, change `LawVersionSummary` from:

```typescript
export interface LawVersionSummary {
  id: number;
  ver_id: string;
  date_in_force: string | null;
  date_imported: string;
  state: string;
  is_current: boolean;
}
```

To:

```typescript
export interface LawVersionSummary {
  id: number;
  ver_id: string;
  date_in_force: string | null;
  date_imported: string;
  state: string;
  is_current: boolean;
  diff_summary: { modified: number; added: number; removed: number } | null;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add diff_summary to LawVersionSummary type"
```

---

## Task 6: Create the UpdateBanner component

**Files:**
- Create: `frontend/src/app/laws/[id]/update-banner.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/app/laws/[id]/update-banner.tsx`:

```tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { KnownVersionData } from "@/lib/api";

interface UpdateBannerProps {
  lawId: number;
  lastCheckedAt: string | null;
  importedVerIds: Set<string>;
  knownVersions: KnownVersionData[] | null;
  onVersionImported: (verId: string, lawVersionId: number) => void;
  onKnownVersionsLoaded: (versions: KnownVersionData[]) => void;
}

function formatCheckedTime(lastCheckedAt: string | null): string {
  if (!lastCheckedAt) return "Never checked";
  const checked = new Date(lastCheckedAt);
  const now = new Date();
  const diffMs = now.getTime() - checked.getTime();
  const diffHours = diffMs / (1000 * 60 * 60);
  const diffDays = diffMs / (1000 * 60 * 60 * 24);

  if (diffHours < 1) {
    const mm = checked.getMinutes().toString().padStart(2, "0");
    const hh = checked.getHours().toString().padStart(2, "0");
    return `Last checked: today, ${hh}:${mm}`;
  }
  if (diffHours < 24) {
    const hh = checked.getHours().toString().padStart(2, "0");
    const mm = checked.getMinutes().toString().padStart(2, "0");
    return `Last checked: today, ${hh}:${mm}`;
  }
  if (diffDays <= 7) {
    const days = Math.floor(diffDays);
    return `Last checked: ${days} day${days !== 1 ? "s" : ""} ago`;
  }
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `Last checked: ${checked.getDate()} ${months[checked.getMonth()]} ${checked.getFullYear()}`;
}

function shouldAutoCheck(lastCheckedAt: string | null): boolean {
  if (!lastCheckedAt) return true;
  const checked = new Date(lastCheckedAt);
  const now = new Date();
  return now.getTime() - checked.getTime() > 60 * 60 * 1000; // 1 hour
}

export default function UpdateBanner({
  lawId,
  lastCheckedAt,
  importedVerIds,
  knownVersions,
  onVersionImported,
  onKnownVersionsLoaded,
}: UpdateBannerProps) {
  const [dismissed, setDismissed] = useState(false);
  const [checking, setChecking] = useState(false);
  const [importing, setImporting] = useState(false);
  const [checkedAt, setCheckedAt] = useState(lastCheckedAt);

  // Auto-check on mount if stale
  useEffect(() => {
    if (!shouldAutoCheck(lastCheckedAt)) return;
    setChecking(true);
    api.laws
      .checkUpdates(lawId)
      .then(() => api.laws.getKnownVersions(lawId))
      .then((data) => {
        onKnownVersionsLoaded(data.versions);
        setCheckedAt(data.last_checked_at);
      })
      .catch(() => {})
      .finally(() => setChecking(false));
  }, [lawId, lastCheckedAt, onKnownVersionsLoaded]);

  const unimported = knownVersions
    ? knownVersions.filter((v) => !importedVerIds.has(v.ver_id))
    : [];

  // Find the latest unimported version (newest by date)
  const latestUnimported = unimported.length > 0
    ? unimported.reduce((a, b) => (a.date_in_force > b.date_in_force ? a : b))
    : null;

  // Compute the version number for display (ordinal position in all known versions)
  const allSortedAsc = knownVersions
    ? [...knownVersions].sort((a, b) => a.date_in_force.localeCompare(b.date_in_force))
    : [];
  const latestVersionNumber = latestUnimported
    ? allSortedAsc.findIndex((v) => v.ver_id === latestUnimported.ver_id) + 1
    : 0;

  async function handleImportLatest() {
    if (!latestUnimported) return;
    setImporting(true);
    try {
      const res = await api.laws.importKnownVersion(lawId, latestUnimported.ver_id);
      onVersionImported(latestUnimported.ver_id, res.law_version_id);
    } catch {
      alert("Failed to import version. Please try again.");
    } finally {
      setImporting(false);
    }
  }

  const checkedText = formatCheckedTime(checkedAt);

  if (checking) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 flex items-center gap-3">
        <div className="w-5 h-5 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" />
        <span className="text-sm text-gray-600">Checking legislatie.just.ro for updates...</span>
      </div>
    );
  }

  // Up to date
  if (unimported.length === 0 || dismissed) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 flex items-start gap-3">
        <svg className="w-5 h-5 text-green-600 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <div>
          <p className="text-sm font-medium text-green-800">No new versions</p>
          <p className="text-sm text-gray-500">{checkedText} &middot; All available versions are imported</p>
        </div>
      </div>
    );
  }

  // New versions available
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 flex items-start justify-between gap-4">
      <div className="flex items-start gap-3">
        <svg className="w-5 h-5 text-amber-600 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
        </svg>
        <div>
          <p className="text-sm font-medium text-amber-800">
            {unimported.length} new version{unimported.length !== 1 ? "s" : ""} available
          </p>
          <p className="text-sm text-amber-700/70">
            {checkedText} &middot; {unimported.length} version{unimported.length !== 1 ? "s" : ""} not yet imported
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={handleImportLatest}
          disabled={importing}
          className="px-3 py-1.5 text-sm font-medium text-white bg-amber-600 rounded-md hover:bg-amber-700 disabled:bg-amber-300 transition-colors"
        >
          {importing ? "Importing..." : `Import latest version (v${latestVersionNumber})`}
        </button>
        <button
          onClick={() => setDismissed(true)}
          className="px-3 py-1.5 text-sm font-medium text-amber-700 bg-white border border-amber-300 rounded-md hover:bg-amber-100 transition-colors"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/laws/[id]/update-banner.tsx
git commit -m "feat: add UpdateBanner component with auto-check and 1h cache"
```

---

## Task 7: Create the ImportedVersionsTable component

**Files:**
- Create: `frontend/src/app/laws/[id]/imported-versions-table.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/app/laws/[id]/imported-versions-table.tsx`:

```tsx
"use client";

import { useState } from "react";
import type { LawVersionSummary } from "@/lib/api";

interface ImportedVersionsTableProps {
  lawId: number;
  versions: LawVersionSummary[];
}

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "Unknown";
  const d = new Date(dateStr);
  return `${d.getDate().toString().padStart(2, "0")} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export default function ImportedVersionsTable({ lawId, versions }: ImportedVersionsTableProps) {
  const [showAll, setShowAll] = useState(false);

  if (versions.length === 0) return null;

  // Sort by date ascending to assign version numbers, then reverse for display
  const sortedAsc = [...versions].sort((a, b) =>
    (a.date_in_force || "").localeCompare(b.date_in_force || "")
  );
  const versionNumberMap = new Map<number, number>();
  sortedAsc.forEach((v, i) => versionNumberMap.set(v.id, i + 1));

  const sortedDesc = [...sortedAsc].reverse();
  const visible = showAll ? sortedDesc : sortedDesc.slice(0, 3);
  const hiddenCount = sortedDesc.length - 3;

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100">
        <svg className="w-5 h-5 text-blue-600" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <h3 className="text-base font-semibold text-gray-900">Imported versions</h3>
        <span className="text-xs text-gray-500 bg-gray-100 rounded-full px-2.5 py-0.5">
          {versions.length} version{versions.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[70px_120px_1fr_150px_160px] gap-2 px-5 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide border-b border-gray-100">
        <div>Ver.</div>
        <div>Date</div>
        <div>Changes vs previous version</div>
        <div>Status</div>
        <div></div>
      </div>

      {/* Rows */}
      {visible.map((version, idx) => {
        const vNum = versionNumberMap.get(version.id) ?? 0;
        const isOlder = showAll && idx >= 3;
        return (
          <div
            key={version.id}
            className={`grid grid-cols-[70px_120px_1fr_150px_160px] gap-2 items-center px-5 py-3 border-b border-gray-50 ${
              isOlder ? "opacity-60" : ""
            }`}
          >
            <div className="text-sm font-bold text-gray-900">v{vNum}</div>
            <div className="text-sm text-gray-500">{formatDate(version.date_in_force)}</div>
            <div className="flex items-center gap-1.5 flex-wrap">
              {version.diff_summary ? (
                <>
                  {version.diff_summary.modified > 0 && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
                      {version.diff_summary.modified} modified
                    </span>
                  )}
                  {version.diff_summary.added > 0 && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700">
                      {version.diff_summary.added} added
                    </span>
                  )}
                  {version.diff_summary.removed > 0 && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700">
                      {version.diff_summary.removed} removed
                    </span>
                  )}
                  {version.diff_summary.modified === 0 && version.diff_summary.added === 0 && version.diff_summary.removed === 0 && (
                    <span className="text-xs text-gray-400">No changes</span>
                  )}
                </>
              ) : (
                <span className="text-xs text-gray-400">&mdash;</span>
              )}
            </div>
            <div>
              {version.is_current ? (
                <span className="text-sm font-medium text-green-700">Current version</span>
              ) : (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500">
                  Imported
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 justify-end">
              <a
                href={`/laws/${lawId}/versions/${version.id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="px-3 py-1 text-sm font-medium text-blue-600 bg-blue-50 border border-blue-200 rounded-md hover:bg-blue-100 transition-colors"
              >
                Read
              </a>
              <a
                href={`/laws/${lawId}#diff-selector`}
                className="px-3 py-1 text-sm font-medium text-blue-600 bg-blue-50 border border-blue-200 rounded-md hover:bg-blue-100 transition-colors"
              >
                Compare
              </a>
            </div>
          </div>
        );
      })}

      {/* Show all / collapse toggle */}
      {hiddenCount > 0 && (
        <button
          onClick={() => setShowAll((prev) => !prev)}
          className="w-full py-3 text-sm text-gray-500 hover:text-gray-700 hover:bg-gray-50 transition-colors flex items-center justify-center gap-2 border-t border-gray-100"
        >
          {showAll ? (
            "Hide older versions"
          ) : (
            <>
              {hiddenCount} older version{hiddenCount !== 1 ? "s" : ""} &mdash; Show all
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
              </svg>
            </>
          )}
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/laws/[id]/imported-versions-table.tsx
git commit -m "feat: add ImportedVersionsTable component with collapse"
```

---

## Task 8: Create the UnimportedVersionsTable component

**Files:**
- Create: `frontend/src/app/laws/[id]/unimported-versions-table.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/app/laws/[id]/unimported-versions-table.tsx`:

```tsx
"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { KnownVersionData } from "@/lib/api";

interface UnimportedVersionsTableProps {
  lawId: number;
  versions: KnownVersionData[];
  allKnownVersions: KnownVersionData[];
  onVersionImported: (verId: string, lawVersionId: number) => void;
}

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return `${d.getDate().toString().padStart(2, "0")} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export default function UnimportedVersionsTable({
  lawId,
  versions,
  allKnownVersions,
  onVersionImported,
}: UnimportedVersionsTableProps) {
  const [importing, setImporting] = useState<Set<string>>(new Set());

  if (versions.length === 0) return null;

  // Version numbers based on ordinal position in ALL known versions (sorted asc by date)
  const allSortedAsc = [...allKnownVersions].sort((a, b) =>
    a.date_in_force.localeCompare(b.date_in_force)
  );
  const versionNumberMap = new Map<string, number>();
  allSortedAsc.forEach((v, i) => versionNumberMap.set(v.ver_id, i + 1));

  // Sort unimported newest first for display
  const sortedDesc = [...versions].sort((a, b) =>
    b.date_in_force.localeCompare(a.date_in_force)
  );

  async function handleImport(verId: string) {
    setImporting((prev) => new Set(prev).add(verId));
    try {
      const res = await api.laws.importKnownVersion(lawId, verId);
      onVersionImported(verId, res.law_version_id);
    } catch {
      alert(`Failed to import version. Please try again.`);
    } finally {
      setImporting((prev) => {
        const next = new Set(prev);
        next.delete(verId);
        return next;
      });
    }
  }

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/50">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-amber-200/50">
        <svg className="w-5 h-5 text-amber-600" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
        </svg>
        <h3 className="text-base font-semibold text-gray-900">Not imported from legislatie.just.ro</h3>
        <span className="text-xs text-amber-700 bg-amber-100 rounded-full px-2.5 py-0.5">
          {versions.length} version{versions.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[70px_120px_1fr_150px_120px] gap-2 px-5 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide border-b border-amber-200/30">
        <div>Ver.</div>
        <div>Date</div>
        <div>Changes vs previous version</div>
        <div>Status</div>
        <div></div>
      </div>

      {/* Rows */}
      {sortedDesc.map((version) => {
        const vNum = versionNumberMap.get(version.ver_id) ?? 0;
        const isImporting = importing.has(version.ver_id);
        return (
          <div
            key={version.ver_id}
            className="grid grid-cols-[70px_120px_1fr_150px_120px] gap-2 items-center px-5 py-3 border-b border-amber-200/20"
          >
            <div className="text-sm font-bold text-gray-900">v{vNum}</div>
            <div className="text-sm text-gray-500">{formatDate(version.date_in_force)}</div>
            <div>
              <span className="text-xs text-gray-400">&mdash;</span>
            </div>
            <div>
              <span className="text-sm text-amber-700">Not imported</span>
            </div>
            <div className="flex justify-end">
              <button
                onClick={() => handleImport(version.ver_id)}
                disabled={isImporting}
                className="px-3 py-1 text-sm font-medium text-amber-700 bg-white border border-amber-300 rounded-md hover:bg-amber-100 disabled:bg-gray-100 disabled:text-gray-400 transition-colors"
              >
                {isImporting ? "Importing..." : "+ Import"}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/laws/[id]/unimported-versions-table.tsx
git commit -m "feat: add UnimportedVersionsTable component"
```

---

## Task 9: Rewrite VersionsSection as orchestrator

**Files:**
- Rewrite: `frontend/src/app/laws/[id]/versions-section.tsx`

- [ ] **Step 1: Rewrite the component**

Replace the entire contents of `frontend/src/app/laws/[id]/versions-section.tsx` with:

```tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { KnownVersionData, LawVersionSummary } from "@/lib/api";
import UpdateBanner from "./update-banner";
import ImportedVersionsTable from "./imported-versions-table";
import UnimportedVersionsTable from "./unimported-versions-table";

interface VersionsSectionProps {
  lawId: number;
  lastCheckedAt: string | null;
  versions: LawVersionSummary[];
}

export default function VersionsSection({
  lawId,
  lastCheckedAt,
  versions: initialVersions,
}: VersionsSectionProps) {
  const router = useRouter();
  const [versions, setVersions] = useState<LawVersionSummary[]>(initialVersions);
  const [knownVersions, setKnownVersions] = useState<KnownVersionData[] | null>(null);
  const [loading, setLoading] = useState(true);

  const importedVerIds = new Set(versions.map((v) => v.ver_id));

  // Load known versions on mount
  useEffect(() => {
    api.laws
      .getKnownVersions(lawId)
      .then((data) => setKnownVersions(data.versions))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [lawId]);

  const handleKnownVersionsLoaded = useCallback((loaded: KnownVersionData[]) => {
    setKnownVersions(loaded);
  }, []);

  const handleVersionImported = useCallback((_verId: string, _lawVersionId: number) => {
    // Refresh the page to get updated versions list with diff_summary from server
    router.refresh();
  }, [router]);

  const unimportedVersions = knownVersions
    ? knownVersions.filter((v) => !importedVerIds.has(v.ver_id))
    : [];

  return (
    <div className="space-y-4 mt-8">
      <UpdateBanner
        lawId={lawId}
        lastCheckedAt={lastCheckedAt}
        importedVerIds={importedVerIds}
        knownVersions={knownVersions}
        onVersionImported={handleVersionImported}
        onKnownVersionsLoaded={handleKnownVersionsLoaded}
      />

      <ImportedVersionsTable lawId={lawId} versions={versions} />

      {!loading && knownVersions && unimportedVersions.length > 0 && (
        <UnimportedVersionsTable
          lawId={lawId}
          versions={unimportedVersions}
          allKnownVersions={knownVersions}
          onVersionImported={handleVersionImported}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/laws/[id]/versions-section.tsx
git commit -m "feat: rewrite VersionsSection as orchestrator for version history"
```

---

## Task 10: Update the law detail page and clean up

**Files:**
- Modify: `frontend/src/app/laws/[id]/page.tsx`
- Delete: `frontend/src/app/laws/[id]/check-updates-button.tsx`

- [ ] **Step 1: Rewrite the law detail page**

Replace the entire contents of `frontend/src/app/laws/[id]/page.tsx` with:

```tsx
import Link from "next/link";
import { api } from "@/lib/api";
import DiffSelector from "./diff-selector";
import DeleteVersionsButton from "./delete-versions-button";
import StatusBadge from "./status-badge";
import VersionsSection from "./versions-section";

export default async function LawDetailPage(props: PageProps<"/laws/[id]">) {
  const { id } = await props.params;
  const lawId = parseInt(id, 10);

  let law;
  try {
    law = await api.laws.get(lawId);
  } catch {
    return (
      <div className="text-center py-12">
        <h2 className="text-xl font-medium text-gray-900">Law not found</h2>
        <Link href="/laws" className="text-blue-600 hover:underline mt-2 inline-block">
          Back to Legal Library
        </Link>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6">
        <Link
          href="/laws"
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          &larr; Back to Legal Library
        </Link>
      </div>

      <div className="mb-8">
        {law.category ? (
          <div className="flex items-center gap-2 text-sm mb-2">
            <div
              className="w-2.5 h-2.5 rounded-full"
              style={{ backgroundColor: law.category.group_color_hex }}
            />
            <span className="text-gray-500">{law.category.group_name_en}</span>
            <span className="text-gray-300">&rsaquo;</span>
            <span className="text-gray-700">{law.category.name_en}</span>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-sm mb-2">
            <span className="bg-amber-100 text-amber-700 px-2 py-0.5 rounded text-xs">Uncategorized</span>
          </div>
        )}
        <h1 className="text-2xl font-bold text-gray-900">{law.title}</h1>
        <p className="text-gray-600 mt-1">
          Legea {law.law_number}/{law.law_year}
        </p>
        {law.description && (
          <p className="text-sm text-gray-500 mt-2">{law.description}</p>
        )}
        {law.issuer && (
          <p className="text-sm text-gray-500 mt-1">Issuer: {law.issuer}</p>
        )}
        <div className="mt-3 flex items-center gap-4">
          <StatusBadge
            lawId={law.id}
            initialStatus={law.status}
            initialOverride={law.status_override}
          />
          <DeleteVersionsButton
            lawId={law.id}
            oldVersionCount={law.versions.filter((v) => !v.is_current).length}
          />
        </div>
      </div>

      <div id="diff-selector">
        <DiffSelector lawId={law.id} versions={law.versions} />
      </div>

      <VersionsSection
        lawId={law.id}
        lastCheckedAt={law.last_checked_at}
        versions={law.versions}
      />
    </div>
  );
}
```

Key changes:
- Removed `CheckUpdatesButton` import and usage
- Removed the inline versions list (`law.versions.map(...)` block)
- `VersionsSection` now receives `versions` instead of `importedVerIds`
- Added `id="diff-selector"` to the DiffSelector wrapper for anchor links
- Moved `DeleteVersionsButton` next to `StatusBadge`
- Changed "Necategorizat" to "Uncategorized" (English UI)

- [ ] **Step 2: Delete the old CheckUpdatesButton file**

```bash
rm frontend/src/app/laws/[id]/check-updates-button.tsx
```

- [ ] **Step 3: Verify the frontend compiles**

Run: `cd /Users/anaandrei/projects/legalese/frontend && npx next build 2>&1 | tail -20`

Expected: Build succeeds with no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/laws/[id]/page.tsx frontend/src/app/laws/[id]/versions-section.tsx
git rm frontend/src/app/laws/[id]/check-updates-button.tsx
git commit -m "feat: update law detail page with unified version history section"
```

---

## Task 11: End-to-end verification

- [ ] **Step 1: Run backend tests**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -m pytest tests/test_diff_summary.py -v`

Expected: All tests pass.

- [ ] **Step 2: Start the backend and verify the API**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.routers.laws import router; print('Router OK')"`

Expected: `Router OK`

- [ ] **Step 3: Build the frontend**

Run: `cd /Users/anaandrei/projects/legalese/frontend && npx next build 2>&1 | tail -20`

Expected: Build succeeds.

- [ ] **Step 4: Manual verification checklist**

Start both backend and frontend, navigate to a law detail page, and verify:
- Update banner appears (green if up-to-date, amber if new versions exist)
- Imported versions table shows with version numbers, dates, change pills, status
- Only 3 most recent shown, "Show all" expands with faded older rows
- "Read" opens version in new tab
- "Compare" scrolls to diff selector
- Unimported versions panel appears only when relevant
- "+ Import" imports a version and moves it to the imported table
