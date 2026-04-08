# Scheduler Activity Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every RO/EU scheduler run (scheduled or manual) into a new `scheduler_run_logs` table and display the last 20 runs as a read-only table inside each scheduler card.

**Architecture:** New SQLAlchemy model created via `Base.metadata.create_all()` (no Alembic). One helper `record_run()` invoked at the three existing places that already write `SchedulerSetting.last_run_*`. New admin GET endpoint for listing. New React subcomponent rendered inside `SchedulerCard`.

**Tech Stack:** FastAPI + SQLAlchemy (SQLite, additive `create_all`), pytest with FastAPI `TestClient`, React + TypeScript client component.

**Spec:** `docs/superpowers/specs/2026-04-08-scheduler-activity-log-design.md`

---

## File Structure

**Create (backend):**
- `backend/app/models/scheduler_run_log.py` — `SchedulerRunLog` model
- `backend/app/services/scheduler_log_service.py` — `record_run()` helper
- `backend/tests/test_scheduler_run_log.py` — service + endpoint tests

**Modify (backend):**
- `backend/app/main.py` — import the new model so `create_all` registers it; call `record_run()` in `run_update_check` and `run_eu_update_check`
- `backend/app/routers/admin.py` — call `record_run()` in `_make_discovery_runner` inner `_runner`
- `backend/app/routers/settings_schedulers.py` — add `GET /scheduler-logs` endpoint

**Create (frontend):**
- `frontend/src/app/settings/schedulers/scheduler-activity-table.tsx` — small read-only table component

**Modify (frontend):**
- `frontend/src/lib/api.ts` — add `SchedulerRunLogData` interface and `api.settings.schedulers.listLogs()` method
- `frontend/src/app/settings/schedulers/scheduler-card.tsx` — render `<SchedulerActivityTable />` inside the card; refetch its data on mount and after `handleComplete`

---

## Task 1: Create the `SchedulerRunLog` model

**Files:**
- Create: `backend/app/models/scheduler_run_log.py`
- Modify: `backend/app/main.py` (add import next to other model imports near line 14)

- [ ] **Step 1: Write the model file**

```python
# backend/app/models/scheduler_run_log.py
"""Append-only log of scheduler runs (RO + EU version discovery)."""

import datetime
from sqlalchemy import DateTime, Integer, JSON, String, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SchedulerRunLog(Base):
    """One row per scheduler run, written by scheduler_log_service.record_run."""

    __tablename__ = "scheduler_run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scheduler_id: Mapped[str] = mapped_column(String(8), nullable=False, index=True)  # "ro" | "eu"
    ran_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)  # "scheduled" | "manual"
    status: Mapped[str] = mapped_column(String(16), nullable=False)   # "ok" | "error"
    laws_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_versions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)

    __table_args__ = (
        Index("ix_scheduler_run_logs_sched_ran", "scheduler_id", "ran_at"),
    )
```

- [ ] **Step 2: Register the model so `create_all` picks it up**

In `backend/app/main.py`, find the block around lines 12–15 that imports models for `Base.metadata` registration. Add:

```python
from app.models.scheduler_run_log import SchedulerRunLog  # noqa: F401  (registers table)
```

Place it next to the other model imports of the same kind.

- [ ] **Step 3: Verify the table is created**

Run:

```bash
cd backend && python -c "
from app.database import Base, engine
import app.models.scheduler_run_log  # noqa
Base.metadata.create_all(bind=engine)
from sqlalchemy import inspect
print('scheduler_run_logs' in inspect(engine).get_table_names())
"
```

Expected output: `True`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/scheduler_run_log.py backend/app/main.py
git commit -m "feat(backend): add SchedulerRunLog model for scheduler activity log"
```

---

## Task 2: `record_run` helper + unit test

**Files:**
- Create: `backend/app/services/scheduler_log_service.py`
- Create: `backend/tests/test_scheduler_run_log.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_scheduler_run_log.py
"""Tests for scheduler_log_service.record_run and GET /api/admin/scheduler-logs."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.scheduler_run_log import SchedulerRunLog
from app.services import scheduler_log_service


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def test_record_run_inserts_row_with_expected_fields(db):
    results = {"checked": 142, "discovered": 3, "errors": 0, "extra": "kept"}

    scheduler_log_service.record_run(db, "ro", results, "scheduled")

    rows = db.query(SchedulerRunLog).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.scheduler_id == "ro"
    assert row.trigger == "scheduled"
    assert row.status == "ok"
    assert row.laws_checked == 142
    assert row.new_versions == 3
    assert row.errors == 0
    assert row.summary_json == results
    assert row.ran_at is not None


def test_record_run_marks_error_status_when_errors_present(db):
    scheduler_log_service.record_run(
        db, "eu", {"checked": 50, "discovered": 0, "errors": 2}, "manual"
    )
    row = db.query(SchedulerRunLog).one()
    assert row.status == "error"
    assert row.trigger == "manual"
    assert row.scheduler_id == "eu"


def test_record_run_swallows_db_failures(db, monkeypatch, caplog):
    """A logging failure must not break the discovery run."""
    def boom(*a, **kw):
        raise RuntimeError("db is down")

    monkeypatch.setattr(db, "add", boom)

    # Should not raise
    scheduler_log_service.record_run(db, "ro", {"checked": 1, "discovered": 0, "errors": 0}, "scheduled")
    assert any("scheduler_run_log" in r.message or "db is down" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd backend && pytest tests/test_scheduler_run_log.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.scheduler_log_service'` (or AttributeError on `record_run`).

- [ ] **Step 3: Implement the helper**

```python
# backend/app/services/scheduler_log_service.py
"""Append rows to scheduler_run_logs. Best-effort: never raises."""

import datetime as _dt
import logging

from sqlalchemy.orm import Session

from app.models.scheduler_run_log import SchedulerRunLog

logger = logging.getLogger(__name__)


def record_run(db: Session, scheduler_id: str, results: dict, trigger: str) -> None:
    """Insert one scheduler_run_logs row.

    Best-effort: a logging failure is logged at WARNING level and swallowed
    so it cannot break the discovery run that called us.

    Args:
        db: SQLAlchemy session (caller-owned; this function commits on it).
        scheduler_id: "ro" or "eu".
        results: Dict returned by run_daily_discovery / run_eu_weekly_discovery.
                 Expected keys: checked, discovered, errors. Stored in full as
                 summary_json for future debugging.
        trigger: "scheduled" or "manual".
    """
    try:
        errors = int(results.get("errors", 0) or 0)
        row = SchedulerRunLog(
            scheduler_id=scheduler_id,
            ran_at=_dt.datetime.now(_dt.timezone.utc),
            trigger=trigger,
            status="ok" if errors == 0 else "error",
            laws_checked=int(results.get("checked", 0) or 0),
            new_versions=int(results.get("discovered", 0) or 0),
            errors=errors,
            summary_json=results,
        )
        db.add(row)
        db.commit()
    except Exception as e:  # noqa: BLE001 - intentional swallow
        logger.warning("Failed to write scheduler_run_log row: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
cd backend && pytest tests/test_scheduler_run_log.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scheduler_log_service.py backend/tests/test_scheduler_run_log.py
git commit -m "feat(backend): add scheduler_log_service.record_run helper"
```

---

## Task 3: Wire helper into the three call sites

**Files:**
- Modify: `backend/app/main.py` (`run_update_check` ~line 50, `run_eu_update_check` ~line 73)
- Modify: `backend/app/routers/admin.py` (`_make_discovery_runner` inner `_runner`, after the existing `db.commit()` ~line 257)

- [ ] **Step 1: Add `record_run` to `run_update_check`**

In `backend/app/main.py`, find:

```python
def run_update_check():
    """Scheduled job: discover new versions for all laws (metadata only)."""
    import datetime as _dt
    from app.services.version_discovery import run_daily_discovery
    from app.database import SessionLocal
    from app.models.scheduler_settings import SchedulerSetting
    ...
    db = SessionLocal()
    try:
        setting = db.query(SchedulerSetting).filter(SchedulerSetting.id == "ro").first()
        if setting:
            setting.last_run_at = _dt.datetime.now(_dt.timezone.utc)
            setting.last_run_status = "ok" if results.get("errors", 0) == 0 else "error"
            setting.last_run_summary = results
            db.commit()
    finally:
        db.close()
```

After the `db.commit()` (still inside the `try`), add:

```python
        from app.services.scheduler_log_service import record_run
        record_run(db, "ro", results, "scheduled")
```

- [ ] **Step 2: Add `record_run` to `run_eu_update_check`**

In the same file, mirror the change in `run_eu_update_check`. After the `db.commit()` inside its `try` block:

```python
        from app.services.scheduler_log_service import record_run
        record_run(db, "eu", results, "scheduled")
```

- [ ] **Step 3: Add `record_run` to the manual runner in admin.py**

In `backend/app/routers/admin.py`, find `_make_discovery_runner` → inner `_runner`, around lines 250–259:

```python
        setting = db.query(SchedulerSetting).filter(SchedulerSetting.id == job_type).first()
        if setting:
            setting.last_run_at = _dt.datetime.now(_dt.timezone.utc)
            setting.last_run_status = "ok" if results.get("errors", 0) == 0 else "error"
            setting.last_run_summary = results
            db.commit()

        return results
```

Add the helper call between the `db.commit()` and `return results`:

```python
        from app.services.scheduler_log_service import record_run
        record_run(db, job_type, results, "manual")

        return results
```

- [ ] **Step 4: Smoke-check the imports**

```bash
cd backend && python -c "
import app.main
import app.routers.admin
print('imports ok')
"
```

Expected output: `imports ok`

- [ ] **Step 5: Run the existing test suite for the touched modules**

```bash
cd backend && pytest tests/test_scheduler_run_log.py -v
```

Expected: 3 passed (no regressions).

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/app/routers/admin.py
git commit -m "feat(backend): record scheduler runs to activity log at all 3 call sites"
```

---

## Task 4: `GET /api/admin/scheduler-logs` endpoint

**Files:**
- Modify: `backend/app/routers/settings_schedulers.py` (add response model + endpoint)
- Modify: `backend/tests/test_scheduler_run_log.py` (add endpoint tests)

- [ ] **Step 1: Write the failing endpoint tests**

Append to `backend/tests/test_scheduler_run_log.py`:

```python
import datetime as _dt
from fastapi.testclient import TestClient

from app.auth import require_admin, get_current_user
from app.database import get_db
from app.main import app as fastapi_app
from app.models.user import User


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_admin():
        return User(id=1, email="admin@example.com", role="admin")

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[require_admin] = override_admin
    fastapi_app.dependency_overrides[get_current_user] = override_admin
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


def _seed_logs(db):
    base = _dt.datetime(2026, 4, 8, 9, 0, 0, tzinfo=_dt.timezone.utc)
    for i in range(5):
        db.add(SchedulerRunLog(
            scheduler_id="ro",
            ran_at=base + _dt.timedelta(hours=i),
            trigger="scheduled" if i % 2 == 0 else "manual",
            status="ok",
            laws_checked=100 + i,
            new_versions=i,
            errors=0,
            summary_json={"checked": 100 + i, "discovered": i, "errors": 0},
        ))
    db.add(SchedulerRunLog(
        scheduler_id="eu",
        ran_at=base,
        trigger="scheduled",
        status="error",
        laws_checked=10,
        new_versions=0,
        errors=1,
        summary_json={"checked": 10, "discovered": 0, "errors": 1},
    ))
    db.commit()


def test_list_scheduler_logs_returns_rows_descending(client, db):
    _seed_logs(db)
    res = client.get("/api/admin/scheduler-logs?scheduler_id=ro")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 5
    timestamps = [r["ran_at"] for r in rows]
    assert timestamps == sorted(timestamps, reverse=True)
    assert rows[0]["laws_checked"] == 104
    assert rows[0]["new_versions"] == 4
    assert "summary_json" not in rows[0]


def test_list_scheduler_logs_respects_limit(client, db):
    _seed_logs(db)
    res = client.get("/api/admin/scheduler-logs?scheduler_id=ro&limit=2")
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_list_scheduler_logs_filters_by_scheduler_id(client, db):
    _seed_logs(db)
    res = client.get("/api/admin/scheduler-logs?scheduler_id=eu")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "error"
    assert rows[0]["errors"] == 1


def test_list_scheduler_logs_rejects_bad_scheduler_id(client):
    res = client.get("/api/admin/scheduler-logs?scheduler_id=fr")
    assert res.status_code == 400


def test_list_scheduler_logs_caps_limit_at_200(client, db):
    _seed_logs(db)
    res = client.get("/api/admin/scheduler-logs?scheduler_id=ro&limit=9999")
    assert res.status_code == 200  # accepted, just capped
    assert len(res.json()) <= 200


def test_list_scheduler_logs_empty_returns_empty_array(client):
    res = client.get("/api/admin/scheduler-logs?scheduler_id=ro")
    assert res.status_code == 200
    assert res.json() == []
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```bash
cd backend && pytest tests/test_scheduler_run_log.py -v -k list_scheduler_logs
```

Expected: 6 failed (404 — endpoint missing).

- [ ] **Step 3: Implement the endpoint**

In `backend/app/routers/settings_schedulers.py`, add the response model near the other response models (after line 34):

```python
class SchedulerRunLogOut(BaseModel):
    id: int
    scheduler_id: str
    ran_at: str
    trigger: str
    status: str
    laws_checked: int
    new_versions: int
    errors: int
```

Add to the imports near the top:

```python
from app.models.scheduler_run_log import SchedulerRunLog
```

Add the endpoint at the bottom of the file, after `save_scheduler_settings`:

```python
@router.get("/scheduler-logs", response_model=list[SchedulerRunLogOut])
def list_scheduler_logs(
    scheduler_id: str,
    limit: int = 20,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Return the most recent scheduler runs, newest first.

    Read-only. summary_json is intentionally omitted from the response —
    it stays in the DB for future drilldowns.
    """
    if scheduler_id not in ("ro", "eu"):
        raise HTTPException(status_code=400, detail="scheduler_id must be 'ro' or 'eu'")

    capped = max(1, min(limit, 200))

    rows = (
        db.query(SchedulerRunLog)
        .filter(SchedulerRunLog.scheduler_id == scheduler_id)
        .order_by(SchedulerRunLog.ran_at.desc())
        .limit(capped)
        .all()
    )
    return [
        SchedulerRunLogOut(
            id=r.id,
            scheduler_id=r.scheduler_id,
            ran_at=r.ran_at.isoformat(),
            trigger=r.trigger,
            status=r.status,
            laws_checked=r.laws_checked,
            new_versions=r.new_versions,
            errors=r.errors,
        )
        for r in rows
    ]
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
cd backend && pytest tests/test_scheduler_run_log.py -v
```

Expected: all tests pass (3 service tests + 6 endpoint tests = 9 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/settings_schedulers.py backend/tests/test_scheduler_run_log.py
git commit -m "feat(backend): add GET /api/admin/scheduler-logs endpoint"
```

---

## Task 5: Frontend API client

**Files:**
- Modify: `frontend/src/lib/api.ts` (add type ~line 631; add method ~line 1011)

- [ ] **Step 1: Add the response type**

After the `SchedulerSettingsUpdate` interface (around line 636), add:

```typescript
export interface SchedulerRunLogData {
  id: number;
  scheduler_id: string;
  ran_at: string;
  trigger: "scheduled" | "manual";
  status: "ok" | "error";
  laws_checked: number;
  new_versions: number;
  errors: number;
}
```

- [ ] **Step 2: Add the client method**

In the `api.settings.schedulers` namespace (around lines 1000–1012), add `listLogs` after `triggerDiscovery`:

```typescript
      triggerDiscovery: (jobType: "ro" | "eu") =>
        apiFetch<{ status: string; job_type: string; job_id: string }>(
          `/api/admin/trigger-discovery/${jobType}`,
          { method: "POST" }
        ),
      listLogs: (schedulerId: "ro" | "eu", limit = 20) =>
        apiFetch<SchedulerRunLogData[]>(
          `/api/admin/scheduler-logs?scheduler_id=${schedulerId}&limit=${limit}`
        ),
```

- [ ] **Step 3: Type-check the frontend**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): add api.settings.schedulers.listLogs client"
```

---

## Task 6: `SchedulerActivityTable` component

**Files:**
- Create: `frontend/src/app/settings/schedulers/scheduler-activity-table.tsx`

- [ ] **Step 1: Write the component**

```tsx
// frontend/src/app/settings/schedulers/scheduler-activity-table.tsx
"use client";

import { useEffect, useState } from "react";
import { api, type SchedulerRunLogData } from "@/lib/api";

interface Props {
  schedulerId: "ro" | "eu";
  /** Bumped by the parent after a manual run completes; triggers a refetch. */
  refreshKey: number;
}

export function SchedulerActivityTable({ schedulerId, refreshKey }: Props) {
  const [rows, setRows] = useState<SchedulerRunLogData[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api.settings.schedulers
      .listLogs(schedulerId, 20)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load activity");
      });
    return () => {
      cancelled = true;
    };
  }, [schedulerId, refreshKey]);

  const formatTime = (iso: string) =>
    new Date(iso).toLocaleString(undefined, {
      dateStyle: "short",
      timeStyle: "short",
    });

  return (
    <div className="border-t border-gray-100 px-4 py-3">
      <div className="text-xs font-semibold text-gray-700 mb-2">Recent activity</div>
      {error && <div className="text-xs text-red-600">{error}</div>}
      {!error && rows === null && (
        <div className="text-xs text-gray-400">Loading…</div>
      )}
      {!error && rows !== null && rows.length === 0 && (
        <div className="text-xs text-gray-400">No runs recorded yet.</div>
      )}
      {!error && rows !== null && rows.length > 0 && (
        <div className="max-h-60 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="text-gray-500 sticky top-0 bg-white">
              <tr>
                <th className="text-left font-medium py-1 pr-2">Time</th>
                <th className="text-left font-medium py-1 pr-2">Trigger</th>
                <th className="text-right font-medium py-1 pr-2">Checked</th>
                <th className="text-right font-medium py-1 pr-2">New</th>
                <th className="text-right font-medium py-1">Errors</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-gray-100">
                  <td className="py-1 pr-2 text-gray-900">{formatTime(r.ran_at)}</td>
                  <td className="py-1 pr-2">
                    <span
                      className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${
                        r.trigger === "manual"
                          ? "bg-amber-100 text-amber-700"
                          : "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {r.trigger === "manual" ? "manual" : "auto"}
                    </span>
                  </td>
                  <td className="py-1 pr-2 text-right text-gray-900">{r.laws_checked}</td>
                  <td className="py-1 pr-2 text-right text-gray-900">{r.new_versions}</td>
                  <td
                    className={`py-1 text-right font-medium ${
                      r.errors > 0 ? "text-red-600" : "text-gray-400"
                    }`}
                  >
                    {r.errors}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors. (Component is unused at this point — TS will not warn since it's exported.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/settings/schedulers/scheduler-activity-table.tsx
git commit -m "feat(frontend): add SchedulerActivityTable component"
```

---

## Task 7: Render activity table inside `SchedulerCard`

**Files:**
- Modify: `frontend/src/app/settings/schedulers/scheduler-card.tsx`

- [ ] **Step 1: Add `refreshKey` state and bump it on completion**

In `frontend/src/app/settings/schedulers/scheduler-card.tsx`, near the other `useState` calls (after line 26), add:

```tsx
  const [activityRefreshKey, setActivityRefreshKey] = useState(0);
```

Update `handleComplete` (lines 64–68) to also bump the key:

```tsx
  const handleComplete = useCallback(() => {
    setRunning(false);
    setActiveJobId(null);
    setActivityRefreshKey((k) => k + 1);
    onRefresh();
  }, [onRefresh]);
```

- [ ] **Step 2: Import and render the activity table**

Add to the imports at the top of the file:

```tsx
import { SchedulerActivityTable } from "./scheduler-activity-table";
```

In the JSX, find the closing of the live progress block (after the `{running && <DiscoveryProgressPanel ... />}` block, line 186) and insert the activity table **inside** the outer card `<div>` (just before the closing `</div>` of the card root):

```tsx
      {/* Recent activity log */}
      <SchedulerActivityTable schedulerId={jobType} refreshKey={activityRefreshKey} />
```

The final JSX shape of the card should look like:

```tsx
return (
  <div className="flex-1 border border-gray-200 rounded-xl bg-white overflow-hidden">
    <div className="p-4">
      {/* ...header, controls, last/next, Run Now button... */}
    </div>

    {/* Progress panel */}
    {running && (
      <DiscoveryProgressPanel
        jobType={jobType}
        jobId={activeJobId}
        onComplete={handleComplete}
      />
    )}

    {/* Recent activity log */}
    <SchedulerActivityTable schedulerId={jobType} refreshKey={activityRefreshKey} />
  </div>
);
```

- [ ] **Step 3: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Manual smoke test**

Start the backend and frontend, navigate to **Settings → Schedulers** as an admin user. Verify:

1. The "Recent activity" section appears below each scheduler card (RO and EU)
2. With no logs, the empty state "No runs recorded yet." renders
3. Click **Run Now** on RO. After the progress panel completes, a new row with `manual` badge appears at the top of the RO activity table. Counts (Checked / New / Errors) match the run results
4. Repeat for EU
5. Browser devtools network tab: confirm `GET /api/admin/scheduler-logs?scheduler_id=ro&limit=20` returns 200 with the expected payload shape (no `summary_json` key)
6. There are no edit/delete buttons or row actions

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/settings/schedulers/scheduler-card.tsx
git commit -m "feat(frontend): render scheduler activity table inside each card"
```

---

## Verification Checklist (run before declaring done)

- [ ] `cd backend && pytest tests/test_scheduler_run_log.py -v` → all 9 tests pass
- [ ] `cd frontend && npx tsc --noEmit` → no errors
- [ ] Manual smoke test (Task 7 Step 4) passes for both RO and EU
- [ ] No new files in `backend/app/models/__init__.py` or other model registries (the import in `main.py` is the only registration site, matching project convention)
- [ ] No edits to `backend/app/models/scheduler_settings.py` (existing scheduler-settings table is untouched)
- [ ] No DELETE/PUT/POST endpoints added for scheduler-logs

---

## Spec ↔ Plan Coverage

| Spec section                          | Implemented in |
|---------------------------------------|----------------|
| Data model `SchedulerRunLog`          | Task 1         |
| `record_run` helper                   | Task 2         |
| Insertion at 3 call sites             | Task 3         |
| `GET /api/admin/scheduler-logs`       | Task 4         |
| `listLogs` client method + type       | Task 5         |
| `SchedulerActivityTable` component    | Task 6         |
| Card integration + refresh-on-finish  | Task 7         |
| Read-only enforcement (no mutations)  | Tasks 4 + 6 (no mutating endpoints, no UI affordances) |
| Best-effort logging (swallow errors)  | Task 2         |
| Backend tests                         | Tasks 2 + 4    |
| Manual end-to-end test                | Task 7 Step 4  |
