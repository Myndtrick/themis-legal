# Scheduler Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Schedulers" tab to the Settings page that controls both version-check schedulers (Romanian + EU) with persistent configuration, progress feedback on manual runs, and full visibility into scheduler state.

**Architecture:** New `scheduler_settings` SQLite table stores per-scheduler config. Backend endpoints read/write settings and reschedule APScheduler jobs on save. Discovery functions report progress to a shared dict polled by the frontend. Frontend adds a new tab with two side-by-side cards.

**Tech Stack:** FastAPI + SQLAlchemy (backend), Next.js + React + Tailwind (frontend), APScheduler 3.x

---

## File Structure

### Backend (new files)
- `backend/app/models/scheduler_settings.py` — SQLAlchemy model for `scheduler_settings` table
- `backend/app/routers/settings_schedulers.py` — GET/PUT settings, GET progress endpoint
- `backend/app/services/scheduler_config.py` — seed defaults, reschedule logic, progress state

### Backend (modified files)
- `backend/app/main.py` — import new model, register router, load settings on startup
- `backend/app/services/version_discovery.py` — add progress reporting to `run_daily_discovery`
- `backend/app/services/eu_version_discovery.py` — add progress reporting to `run_eu_weekly_discovery`
- `backend/app/routers/admin.py` — update trigger endpoint to use progress-aware wrappers

### Frontend (new files)
- `frontend/src/app/settings/schedulers/scheduler-settings.tsx` — main component with two cards + save
- `frontend/src/app/settings/schedulers/scheduler-card.tsx` — single scheduler card
- `frontend/src/app/settings/schedulers/discovery-progress.tsx` — progress bar + completion summary

### Frontend (modified files)
- `frontend/src/app/settings/settings-tabs.tsx` — add "Schedulers" tab
- `frontend/src/app/settings/page.tsx` — render `SchedulerSettings` for new tab
- `frontend/src/lib/api.ts` — add scheduler settings types + API methods

---

### Task 1: Scheduler Settings Database Model

**Files:**
- Create: `backend/app/models/scheduler_settings.py`

- [ ] **Step 1: Create the model file**

```python
"""SQLAlchemy model for scheduler configuration (persists across restarts)."""

import datetime
from sqlalchemy import Boolean, DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SchedulerSetting(Base):
    __tablename__ = "scheduler_settings"

    id: Mapped[str] = mapped_column(String(10), primary_key=True)  # "ro" or "eu"
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)  # daily, every_3_days, weekly, monthly
    time_hour: Mapped[int] = mapped_column(Integer, default=3)
    time_minute: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    last_run_status: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    last_run_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
```

- [ ] **Step 2: Register the model in main.py**

Add this import near the other model imports at the top of `backend/app/main.py` (around line 11):

```python
from app.models import scheduler_settings  # noqa: F401 — register scheduler_settings table
```

This goes right after the existing `from app.models import model_config` line.

- [ ] **Step 3: Verify the table gets created**

Run:
```bash
cd backend && uv run python -c "
from app.database import Base, engine
from app.models.scheduler_settings import SchedulerSetting
Base.metadata.create_all(bind=engine)
from sqlalchemy import inspect
inspector = inspect(engine)
cols = [c['name'] for c in inspector.get_columns('scheduler_settings')]
print('scheduler_settings columns:', cols)
"
```

Expected: `scheduler_settings columns: ['id', 'enabled', 'frequency', 'time_hour', 'time_minute', 'last_run_at', 'last_run_status', 'last_run_summary']`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/scheduler_settings.py backend/app/main.py
git commit -m "feat: add scheduler_settings database model"
```

---

### Task 2: Scheduler Config Service (seed, reschedule, progress)

**Files:**
- Create: `backend/app/services/scheduler_config.py`

- [ ] **Step 1: Create the service file**

```python
"""Scheduler configuration: seeding defaults, rescheduling jobs, progress tracking."""

import datetime
import logging

from sqlalchemy.orm import Session

from app.models.scheduler_settings import SchedulerSetting
from app.scheduler import scheduler

logger = logging.getLogger(__name__)

# --- Progress tracking for manual runs ---
# Updated by discovery functions, read by the progress endpoint.
discovery_progress: dict[str, dict] = {}

DEFAULTS = {
    "ro": {"frequency": "daily", "time_hour": 3, "time_minute": 0},
    "eu": {"frequency": "weekly", "time_hour": 4, "time_minute": 0},
}


def seed_scheduler_settings(db: Session) -> None:
    """Insert default rows for 'ro' and 'eu' if they don't exist. Never modifies existing rows."""
    for sched_id, defaults in DEFAULTS.items():
        existing = db.query(SchedulerSetting).filter(SchedulerSetting.id == sched_id).first()
        if not existing:
            db.add(SchedulerSetting(
                id=sched_id,
                enabled=True,
                frequency=defaults["frequency"],
                time_hour=defaults["time_hour"],
                time_minute=defaults["time_minute"],
            ))
            logger.info("Seeded scheduler_settings row for '%s'", sched_id)
    db.commit()


def get_all_settings(db: Session) -> list[SchedulerSetting]:
    """Return all scheduler settings rows."""
    return db.query(SchedulerSetting).all()


def _build_trigger_kwargs(frequency: str, hour: int, minute: int) -> tuple[str, dict]:
    """Return (trigger_type, trigger_kwargs) for APScheduler based on frequency.

    Returns:
        ("cron", {...}) or ("interval", {...})
    """
    if frequency == "daily":
        return "cron", {"hour": hour, "minute": minute}
    elif frequency == "every_3_days":
        # interval trigger: every 3 days starting at the configured time today (or tomorrow if past)
        now = datetime.datetime.now(datetime.timezone.utc)
        start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start < now:
            start += datetime.timedelta(days=1)
        return "interval", {"days": 3, "start_date": start}
    elif frequency == "weekly":
        return "cron", {"day_of_week": "sun", "hour": hour, "minute": minute}
    elif frequency == "monthly":
        return "cron", {"day": 1, "hour": hour, "minute": minute}
    else:
        raise ValueError(f"Unknown frequency: {frequency}")


def schedule_jobs(db: Session) -> None:
    """Read settings from DB and register/remove APScheduler jobs accordingly.

    Called on startup and after saving settings.
    """
    from app.main import run_update_check, run_eu_update_check

    job_map = {
        "ro": {"id": "daily_law_update", "func": run_update_check},
        "eu": {"id": "weekly_eu_discovery", "func": run_eu_update_check},
    }

    settings = {s.id: s for s in get_all_settings(db)}

    for sched_id, job_info in job_map.items():
        job_id = job_info["id"]

        # Remove existing job if present
        existing_job = scheduler.get_job(job_id)
        if existing_job:
            scheduler.remove_job(job_id)

        setting = settings.get(sched_id)
        if not setting or not setting.enabled:
            logger.info("Scheduler '%s' is disabled — job removed", sched_id)
            continue

        trigger_type, trigger_kwargs = _build_trigger_kwargs(
            setting.frequency, setting.time_hour, setting.time_minute
        )

        scheduler.add_job(
            job_info["func"],
            trigger_type,
            id=job_id,
            replace_existing=True,
            misfire_grace_time=43200,
            **trigger_kwargs,
        )
        logger.info(
            "Scheduled '%s': trigger=%s, kwargs=%s",
            job_id,
            trigger_type,
            trigger_kwargs,
        )


def compute_next_run(setting: SchedulerSetting) -> str | None:
    """Compute the next run time for a scheduler setting by checking the APScheduler job."""
    job_ids = {"ro": "daily_law_update", "eu": "weekly_eu_discovery"}
    job_id = job_ids.get(setting.id)
    if not job_id:
        return None
    job = scheduler.get_job(job_id)
    if not job or not job.next_run_time:
        return None
    return job.next_run_time.isoformat()
```

- [ ] **Step 2: Verify imports work**

Run:
```bash
cd backend && uv run python -c "
from app.services.scheduler_config import seed_scheduler_settings, discovery_progress, _build_trigger_kwargs
trigger, kwargs = _build_trigger_kwargs('daily', 3, 0)
print(f'daily -> {trigger}: {kwargs}')
trigger, kwargs = _build_trigger_kwargs('every_3_days', 2, 30)
print(f'every_3_days -> {trigger}: {kwargs}')
trigger, kwargs = _build_trigger_kwargs('weekly', 4, 0)
print(f'weekly -> {trigger}: {kwargs}')
trigger, kwargs = _build_trigger_kwargs('monthly', 1, 0)
print(f'monthly -> {trigger}: {kwargs}')
print('OK')
"
```

Expected: four lines showing correct trigger types and kwargs, then `OK`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/scheduler_config.py
git commit -m "feat: add scheduler config service with seeding, rescheduling, and progress tracking"
```

---

### Task 3: Add Progress Reporting to Discovery Functions

**Files:**
- Modify: `backend/app/services/version_discovery.py` (the `run_daily_discovery` function)
- Modify: `backend/app/services/eu_version_discovery.py` (the `run_eu_weekly_discovery` function)

- [ ] **Step 1: Add progress reporting to `run_daily_discovery`**

In `backend/app/services/version_discovery.py`, add the import at the top of the file (with the other imports):

```python
from app.services.scheduler_config import discovery_progress
```

Then modify the `run_daily_discovery` function. Find the line:

```python
        laws = db.query(Law).all()
        logger.info("Starting daily version discovery for %d law(s)", len(laws))
```

Replace the entire `for law in laws:` loop (from after the logger.info line through to the `time.sleep(rate_limit_delay)` at the end of the loop) with:

```python
        total = len(laws)
        discovery_progress["ro"] = {"running": True, "current": 0, "total": total, "current_law": "", "results": None}

        for i, law in enumerate(laws):
            discovery_progress["ro"]["current"] = i + 1
            discovery_progress["ro"]["current_law"] = law.title or f"Law {law.id}"
            results["checked"] += 1

            try:
                new_count = discover_versions_for_law(db, law)
                results["discovered"] += new_count

                if new_count > 0:
                    notification = Notification(
                        title=f"New version(s) found: {law.title}",
                        message=(
                            f"{new_count} new version(s) discovered for "
                            f"Legea {law.law_number}/{law.law_year}."
                        ),
                        notification_type="law_update",
                    )
                    db.add(notification)
                    db.commit()

            except Exception as exc:
                logger.exception(
                    "Unexpected error during discovery for law %s: %s", law.id, exc
                )
                results["errors"] += 1

            time.sleep(rate_limit_delay)
```

Then, right after the audit log commit (after `db.commit()` at the end of the try block), add:

```python
        discovery_progress["ro"] = {"running": False, "current": total, "total": total, "current_law": "", "results": results}
```

And in the `except Exception:` block (the outer one that catches `run_daily_discovery failed`), add before the `db.rollback()`:

```python
        discovery_progress["ro"] = {"running": False, "current": 0, "total": 0, "current_law": "", "results": results}
```

- [ ] **Step 2: Add progress reporting to `run_eu_weekly_discovery`**

In `backend/app/services/eu_version_discovery.py`, add the import at the top:

```python
from app.services.scheduler_config import discovery_progress
```

Then modify the `run_eu_weekly_discovery` function. Find the line:

```python
        eu_laws = db.query(Law).filter(Law.source == "eu").all()
```

After the existing variable initializations (`checked = 0`, `discovered = 0`, `errors = 0`), add:

```python
        total = len(eu_laws)
        discovery_progress["eu"] = {"running": True, "current": 0, "total": total, "current_law": "", "results": None}
```

Then replace the `for law in eu_laws:` loop with:

```python
        for i, law in enumerate(eu_laws):
            discovery_progress["eu"]["current"] = i + 1
            discovery_progress["eu"]["current_law"] = law.title or f"Law {law.id}"
            try:
                new = discover_eu_versions_for_law(db, law)
                discovered += new
                checked += 1
                if rate_limit_delay:
                    time.sleep(rate_limit_delay)
            except Exception as e:
                logger.error(f"EU version discovery failed for law {law.id} ({law.celex_number}): {e}")
                errors += 1
                db.rollback()
```

Right before the `return` statement, add:

```python
        results = {"checked": checked, "discovered": discovered, "errors": errors}
        discovery_progress["eu"] = {"running": False, "current": total, "total": total, "current_law": "", "results": results}
```

- [ ] **Step 3: Verify the modified functions still import correctly**

Run:
```bash
cd backend && uv run python -c "
from app.services.version_discovery import run_daily_discovery
from app.services.eu_version_discovery import run_eu_weekly_discovery
from app.services.scheduler_config import discovery_progress
print('discovery_progress keys:', list(discovery_progress.keys()))
print('OK')
"
```

Expected: `discovery_progress keys: []` then `OK`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/version_discovery.py backend/app/services/eu_version_discovery.py
git commit -m "feat: add progress reporting to discovery functions"
```

---

### Task 4: Scheduler Settings API Endpoints

**Files:**
- Create: `backend/app/routers/settings_schedulers.py`
- Modify: `backend/app/main.py` (register the router)

- [ ] **Step 1: Create the router file**

```python
"""Settings endpoints for scheduler configuration."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models.scheduler_settings import SchedulerSetting
from app.models.user import User
from app.services.scheduler_config import (
    compute_next_run,
    discovery_progress,
    get_all_settings,
    schedule_jobs,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


# --- Response models ---

class SchedulerSettingOut(BaseModel):
    id: str
    enabled: bool
    frequency: str
    time_hour: int
    time_minute: int
    last_run_at: str | None
    last_run_status: str | None
    last_run_summary: dict | None
    next_run_utc: str | None


class SchedulerSettingUpdate(BaseModel):
    enabled: bool
    frequency: str = Field(pattern=r"^(daily|every_3_days|weekly|monthly)$")
    time_hour: int = Field(ge=0, le=23)
    time_minute: int = Field(ge=0, le=59)


class SchedulerSettingsBatch(BaseModel):
    ro: SchedulerSettingUpdate
    eu: SchedulerSettingUpdate


class DiscoveryProgressOut(BaseModel):
    running: bool
    current: int
    total: int
    current_law: str
    results: dict | None


# --- Endpoints ---

@router.get("/scheduler-settings", response_model=list[SchedulerSettingOut])
def list_scheduler_settings(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Return settings for both schedulers."""
    settings = get_all_settings(db)
    return [
        SchedulerSettingOut(
            id=s.id,
            enabled=s.enabled,
            frequency=s.frequency,
            time_hour=s.time_hour,
            time_minute=s.time_minute,
            last_run_at=s.last_run_at.isoformat() if s.last_run_at else None,
            last_run_status=s.last_run_status,
            last_run_summary=s.last_run_summary,
            next_run_utc=compute_next_run(s),
        )
        for s in settings
    ]


@router.put("/scheduler-settings")
def save_scheduler_settings(
    batch: SchedulerSettingsBatch,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Save settings for both schedulers and reschedule APScheduler jobs."""
    for sched_id, update in [("ro", batch.ro), ("eu", batch.eu)]:
        setting = db.query(SchedulerSetting).filter(SchedulerSetting.id == sched_id).first()
        if not setting:
            raise HTTPException(status_code=404, detail=f"Scheduler '{sched_id}' not found")
        setting.enabled = update.enabled
        setting.frequency = update.frequency
        setting.time_hour = update.time_hour
        setting.time_minute = update.time_minute

    db.commit()

    # Reschedule APScheduler jobs with new settings
    schedule_jobs(db)

    logger.info("Scheduler settings saved and jobs rescheduled")
    return {"status": "ok"}


@router.get("/discovery-progress/{job_type}", response_model=DiscoveryProgressOut)
def get_discovery_progress(
    job_type: str,
    admin: User = Depends(require_admin),
):
    """Poll progress during a manual discovery run."""
    if job_type not in ("ro", "eu"):
        raise HTTPException(status_code=400, detail="job_type must be 'ro' or 'eu'")

    progress = discovery_progress.get(job_type)
    if not progress:
        return DiscoveryProgressOut(running=False, current=0, total=0, current_law="", results=None)

    return DiscoveryProgressOut(**progress)
```

- [ ] **Step 2: Register the router in main.py**

In `backend/app/main.py`, add this import near the other router imports (around line 16):

```python
from app.routers import settings_schedulers
```

Then find the line where routers are included (search for `app.include_router`). Add:

```python
    app.include_router(settings_schedulers.router)
```

right after the existing `app.include_router(admin_router.router)` line.

- [ ] **Step 3: Verify endpoints register**

Run:
```bash
cd backend && uv run python -c "
from app.main import app
routes = [(r.path, r.methods) for r in app.routes if hasattr(r, 'methods')]
for path, methods in sorted(routes):
    if 'scheduler' in path or 'discovery-progress' in path:
        print(f'{methods} {path}')
"
```

Expected output:
```
{'GET'} /api/admin/discovery-progress/{job_type}
{'GET'} /api/admin/scheduler-settings
{'PUT'} /api/admin/scheduler-settings
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/settings_schedulers.py backend/app/main.py
git commit -m "feat: add scheduler settings API endpoints"
```

---

### Task 5: Update Startup to Use DB Settings and Seed Defaults

**Files:**
- Modify: `backend/app/main.py` (lifespan function)

- [ ] **Step 1: Update the lifespan to seed settings and use them for scheduling**

In `backend/app/main.py`, find the lifespan function. In the `try` block (around line 105, after `seed_known_versions_from_imported`), add:

```python
        from app.services.scheduler_config import seed_scheduler_settings
        seed_scheduler_settings(db)
```

Then replace the entire scheduler registration block (from `# Schedule daily update check at 3:00 AM UTC` through `scheduler.start()` and the logger.info line) with:

```python
    # Load scheduler settings from DB and register jobs
    from app.services.scheduler_config import schedule_jobs
    from app.database import SessionLocal as _SessionLocal
    _sched_db = _SessionLocal()
    try:
        schedule_jobs(_sched_db)
    finally:
        _sched_db.close()
    scheduler.start()
    logger.info("Scheduler started with DB-configured jobs")
```

- [ ] **Step 2: Verify startup works**

Run:
```bash
cd backend && uv run python -c "
import asyncio
from app.main import lifespan, app

async def test():
    async with lifespan(app):
        from app.scheduler import scheduler
        jobs = scheduler.get_jobs()
        for j in jobs:
            print(f'  Job: {j.id}, next_run: {j.next_run_time}')
        print(f'Total jobs: {len(jobs)}')

asyncio.run(test())
"
```

Expected: Two jobs listed (`daily_law_update` and `weekly_eu_discovery`) with next run times.

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: load scheduler settings from database on startup"
```

---

### Task 6: Update Admin Trigger to Record Run Results in DB

**Files:**
- Modify: `backend/app/routers/admin.py`

- [ ] **Step 1: Update `trigger_discovery` to save results to scheduler_settings**

Replace the entire `trigger_discovery` function in `backend/app/routers/admin.py` with:

```python
@router.post("/trigger-discovery/{job_type}")
def trigger_discovery(
    job_type: str,
    admin: User = Depends(require_admin),
):
    """Manually trigger a version discovery check. job_type: 'ro' or 'eu'."""
    if job_type not in ("ro", "eu"):
        raise HTTPException(status_code=400, detail="job_type must be 'ro' or 'eu'")

    from app.services.scheduler_config import discovery_progress

    # Prevent concurrent runs
    progress = discovery_progress.get(job_type)
    if progress and progress.get("running"):
        raise HTTPException(status_code=409, detail=f"{job_type} discovery is already running")

    def _run(jtype: str):
        import datetime as _dt
        from app.database import SessionLocal
        from app.models.scheduler_settings import SchedulerSetting

        if jtype == "ro":
            from app.services.version_discovery import run_daily_discovery
            results = run_daily_discovery()
        else:
            from app.services.eu_version_discovery import run_eu_weekly_discovery
            results = run_eu_weekly_discovery()

        # Persist run results in scheduler_settings
        db = SessionLocal()
        try:
            setting = db.query(SchedulerSetting).filter(SchedulerSetting.id == jtype).first()
            if setting:
                setting.last_run_at = _dt.datetime.now(_dt.timezone.utc)
                setting.last_run_status = "ok" if results.get("errors", 0) == 0 else "error"
                setting.last_run_summary = results
                db.commit()
        finally:
            db.close()

    thread = threading.Thread(target=_run, args=(job_type,), name=f"manual_{job_type}_discovery", daemon=True)
    thread.start()

    label = "Romanian law version discovery" if job_type == "ro" else "EU law version discovery"
    logger.info("Manually triggered %s", label)
    return {"status": "started", "job_type": job_type, "label": label}
```

- [ ] **Step 2: Also update the scheduled job wrappers in main.py to persist results**

In `backend/app/main.py`, replace `run_update_check` and `run_eu_update_check`:

```python
def run_update_check():
    """Scheduled job: discover new versions for all laws (metadata only)."""
    import datetime as _dt
    from app.services.version_discovery import run_daily_discovery
    from app.database import SessionLocal
    from app.models.scheduler_settings import SchedulerSetting

    logger.info("Running scheduled version discovery...")
    results = run_daily_discovery()
    logger.info(
        f"Version discovery complete: {results['checked']} checked, "
        f"{results['discovered']} new versions discovered, {results['errors']} errors"
    )

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


def run_eu_update_check():
    """Scheduled job: discover new consolidated versions for all EU laws."""
    import datetime as _dt
    from app.services.eu_version_discovery import run_eu_weekly_discovery
    from app.database import SessionLocal
    from app.models.scheduler_settings import SchedulerSetting

    logger.info("Running scheduled EU version discovery...")
    results = run_eu_weekly_discovery()
    logger.info(f"EU discovery complete: {results}")

    db = SessionLocal()
    try:
        setting = db.query(SchedulerSetting).filter(SchedulerSetting.id == "eu").first()
        if setting:
            setting.last_run_at = _dt.datetime.now(_dt.timezone.utc)
            setting.last_run_status = "ok" if results.get("errors", 0) == 0 else "error"
            setting.last_run_summary = results
            db.commit()
    finally:
        db.close()
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/admin.py backend/app/main.py
git commit -m "feat: persist scheduler run results to database"
```

---

### Task 7: Frontend API Types and Methods

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add types**

In `frontend/src/lib/api.ts`, add these interfaces after the `HealthStats` interface (around line 545):

```typescript
// --- Settings: Scheduler types ---

export interface SchedulerSettingData {
  id: string;
  enabled: boolean;
  frequency: string;
  time_hour: number;
  time_minute: number;
  last_run_at: string | null;
  last_run_status: string | null;
  last_run_summary: { checked: number; discovered: number; errors: number } | null;
  next_run_utc: string | null;
}

export interface SchedulerSettingsUpdate {
  ro: { enabled: boolean; frequency: string; time_hour: number; time_minute: number };
  eu: { enabled: boolean; frequency: string; time_hour: number; time_minute: number };
}

export interface DiscoveryProgress {
  running: boolean;
  current: number;
  total: number;
  current_law: string;
  results: { checked: number; discovered: number; errors: number } | null;
}
```

- [ ] **Step 2: Add API methods**

In the `api` object, inside the `settings` group (after the `assignments` block, around line 980), add:

```typescript
    schedulers: {
      list: () => apiFetch<SchedulerSettingData[]>("/api/admin/scheduler-settings"),
      save: (update: SchedulerSettingsUpdate) =>
        apiFetch<{ status: string }>("/api/admin/scheduler-settings", {
          method: "PUT",
          body: JSON.stringify(update),
        }),
      triggerDiscovery: (jobType: "ro" | "eu") =>
        apiFetch<{ status: string; job_type: string }>(`/api/admin/trigger-discovery/${jobType}`, {
          method: "POST",
        }),
      progress: (jobType: "ro" | "eu") =>
        apiFetch<DiscoveryProgress>(`/api/admin/discovery-progress/${jobType}`),
    },
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add scheduler settings types and API methods to frontend"
```

---

### Task 8: Discovery Progress Component

**Files:**
- Create: `frontend/src/app/settings/schedulers/discovery-progress.tsx`

- [ ] **Step 1: Create the progress component**

```typescript
"use client";

import { useEffect, useRef, useState } from "react";
import { api, type DiscoveryProgress } from "@/lib/api";

interface Props {
  jobType: "ro" | "eu";
  onComplete: () => void;
}

export function DiscoveryProgressPanel({ jobType, onComplete }: Props) {
  const [progress, setProgress] = useState<DiscoveryProgress | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const completedRef = useRef(false);

  useEffect(() => {
    intervalRef.current = setInterval(async () => {
      try {
        const p = await api.settings.schedulers.progress(jobType);
        setProgress(p);

        if (!p.running && !completedRef.current) {
          completedRef.current = true;
          if (intervalRef.current) clearInterval(intervalRef.current);
          // Wait a moment so user can see the completed state before refreshing
          setTimeout(onComplete, 2000);
        }
      } catch {
        // Ignore polling errors
      }
    }, 2000);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [jobType, onComplete]);

  if (!progress) {
    return (
      <div className="border-t border-gray-200 bg-gray-50 px-4 py-3">
        <div className="text-xs text-gray-500">Starting discovery...</div>
      </div>
    );
  }

  if (progress.running) {
    const pct = progress.total > 0 ? (progress.current / progress.total) * 100 : 0;
    return (
      <div className="border-t border-gray-200 bg-green-50 px-4 py-3">
        <div className="flex justify-between items-center mb-1.5">
          <div className="text-xs font-medium text-green-800">Running discovery...</div>
          <div className="text-xs text-gray-500">
            {progress.current} / {progress.total} laws
          </div>
        </div>
        <div className="bg-green-200 rounded h-1.5 overflow-hidden">
          <div
            className="bg-green-600 h-full rounded transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
        {progress.current_law && (
          <div className="text-[10px] text-gray-500 mt-1.5 truncate">
            Checking: {progress.current_law}
          </div>
        )}
      </div>
    );
  }

  // Completed
  const r = progress.results;
  return (
    <div className="border-t border-gray-200 bg-green-50 px-4 py-3">
      <div className="flex justify-between items-center">
        <div className="text-xs font-medium text-green-800">✓ Discovery complete</div>
        <div className="text-xs text-gray-500">{r?.checked ?? 0} checked</div>
      </div>
      {r && (
        <div className="text-xs text-green-700 mt-1">
          {r.discovered} new version{r.discovered !== 1 ? "s" : ""} found · {r.errors} error{r.errors !== 1 ? "s" : ""}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/settings/schedulers/discovery-progress.tsx
git commit -m "feat: add discovery progress polling component"
```

---

### Task 9: Scheduler Card Component

**Files:**
- Create: `frontend/src/app/settings/schedulers/scheduler-card.tsx`

- [ ] **Step 1: Create the card component**

```typescript
"use client";

import { useCallback, useState } from "react";
import { api, type SchedulerSettingData } from "@/lib/api";
import { DiscoveryProgressPanel } from "./discovery-progress";

const FREQUENCY_OPTIONS = [
  { value: "daily", label: "Every day" },
  { value: "every_3_days", label: "Every 3 days" },
  { value: "weekly", label: "Once a week" },
  { value: "monthly", label: "Once a month" },
];

interface Props {
  setting: SchedulerSettingData;
  label: string;
  emoji: string;
  source: string;
  onChange: (field: string, value: boolean | string | number) => void;
  onRefresh: () => void;
}

export function SchedulerCard({ setting, label, emoji, source, onChange, onRefresh }: Props) {
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const jobType = setting.id as "ro" | "eu";

  const handleRunNow = async () => {
    setRunError(null);
    try {
      await api.settings.schedulers.triggerDiscovery(jobType);
      setRunning(true);
    } catch (e: any) {
      setRunError(e.message || "Failed to start");
      setTimeout(() => setRunError(null), 3000);
    }
  };

  const handleComplete = useCallback(() => {
    setRunning(false);
    onRefresh();
  }, [onRefresh]);

  const formatTime = (hour: number, minute: number) =>
    `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;

  return (
    <div className="flex-1 border border-gray-200 rounded-xl bg-white overflow-hidden">
      <div className="p-4">
        {/* Header with toggle */}
        <div className="flex justify-between items-center mb-4">
          <div>
            <div className="font-semibold text-gray-900">
              {emoji} {label}
            </div>
            <div className="text-xs text-gray-500 mt-0.5">Source: {source}</div>
          </div>
          <div className="flex items-center gap-1.5">
            <span className={`text-xs font-medium ${setting.enabled ? "text-green-600" : "text-gray-400"}`}>
              {setting.enabled ? "Enabled" : "Disabled"}
            </span>
            <button
              onClick={() => onChange("enabled", !setting.enabled)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                setting.enabled ? "bg-indigo-600" : "bg-gray-200"
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                  setting.enabled ? "translate-x-6" : "translate-x-1"
                }`}
              />
            </button>
          </div>
        </div>

        {/* Controls — dimmed when disabled */}
        <div className={setting.enabled ? "" : "opacity-40 pointer-events-none"}>
          {/* Frequency */}
          <div className="mb-3">
            <label className="block text-xs font-medium text-gray-700 mb-1">Frequency</label>
            <select
              value={setting.frequency}
              onChange={(e) => onChange("frequency", e.target.value)}
              className="w-full border border-gray-300 rounded-md px-2.5 py-1.5 text-sm bg-white text-gray-900"
            >
              {FREQUENCY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Time */}
          <div className="mb-4">
            <label className="block text-xs font-medium text-gray-700 mb-1">Time of day</label>
            <div className="flex items-center gap-2">
              <input
                type="time"
                value={formatTime(setting.time_hour, setting.time_minute)}
                onChange={(e) => {
                  const [h, m] = e.target.value.split(":").map(Number);
                  onChange("time_hour", h);
                  onChange("time_minute", m);
                }}
                className="border border-gray-300 rounded-md px-2.5 py-1.5 text-sm bg-white text-gray-900"
              />
              <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">UTC</span>
            </div>
          </div>
        </div>

        {/* Last / Next run */}
        <div className="bg-gray-50 rounded-lg px-3 py-2.5 mb-3">
          <div className="flex justify-between mb-1">
            <span className="text-xs text-gray-500">Last run</span>
            <span className="text-xs text-gray-900 font-medium">
              {setting.last_run_at
                ? new Date(setting.last_run_at).toLocaleString("en-GB", { timeZone: "UTC", dateStyle: "short", timeStyle: "short" }) + " UTC"
                : "Never"}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-xs text-gray-500">Next run</span>
            <span className="text-xs text-indigo-600 font-medium">
              {!setting.enabled
                ? "—"
                : setting.next_run_utc
                  ? new Date(setting.next_run_utc).toLocaleString("en-GB", { timeZone: "UTC", dateStyle: "short", timeStyle: "short" }) + " UTC"
                  : "—"}
            </span>
          </div>
        </div>

        {/* Run Now */}
        <button
          onClick={handleRunNow}
          disabled={running}
          className={`w-full rounded-md py-2 text-sm font-medium text-white transition-colors ${
            running
              ? "bg-gray-400 cursor-not-allowed"
              : "bg-indigo-600 hover:bg-indigo-700"
          }`}
        >
          {running ? "Running..." : "▶ Run Now"}
        </button>
        {runError && (
          <div className="text-xs text-red-600 mt-1.5">{runError}</div>
        )}
      </div>

      {/* Progress panel */}
      {running && (
        <DiscoveryProgressPanel jobType={jobType} onComplete={handleComplete} />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/settings/schedulers/scheduler-card.tsx
git commit -m "feat: add scheduler card component with toggle, frequency, time, run now"
```

---

### Task 10: Main Scheduler Settings Component

**Files:**
- Create: `frontend/src/app/settings/schedulers/scheduler-settings.tsx`

- [ ] **Step 1: Create the main component**

```typescript
"use client";

import { useEffect, useState, useCallback } from "react";
import { api, type SchedulerSettingData } from "@/lib/api";
import { SchedulerCard } from "./scheduler-card";

const LABELS: Record<string, { label: string; emoji: string; source: string }> = {
  ro: { label: "Romanian Laws", emoji: "🇷🇴", source: "legislatie.just.ro" },
  eu: { label: "EU Laws", emoji: "🇪🇺", source: "EU Cellar API" },
};

export function SchedulerSettings() {
  const [settings, setSettings] = useState<SchedulerSettingData[]>([]);
  const [original, setOriginal] = useState<SchedulerSettingData[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const fetchSettings = useCallback(async () => {
    try {
      const data = await api.settings.schedulers.list();
      setSettings(data);
      setOriginal(data);
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load scheduler settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const isDirty = JSON.stringify(settings) !== JSON.stringify(original);

  const handleChange = (id: string, field: string, value: boolean | string | number) => {
    setSettings((prev) =>
      prev.map((s) => (s.id === id ? { ...s, [field]: value } : s))
    );
    setSaveSuccess(false);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const ro = settings.find((s) => s.id === "ro")!;
      const eu = settings.find((s) => s.id === "eu")!;
      await api.settings.schedulers.save({
        ro: { enabled: ro.enabled, frequency: ro.frequency, time_hour: ro.time_hour, time_minute: ro.time_minute },
        eu: { enabled: eu.enabled, frequency: eu.frequency, time_hour: eu.time_hour, time_minute: eu.time_minute },
      });
      // Refresh to get updated next_run_utc
      await fetchSettings();
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (e: any) {
      setError(e.message || "Failed to save scheduler settings");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="py-8 text-sm text-gray-400">Loading scheduler settings...</div>;
  }

  return (
    <div>
      {/* Header with Save */}
      <div className="flex justify-between items-center mb-5">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Version Check Schedulers</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Configure automatic checks for new law versions
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isDirty && (
            <span className="text-xs text-amber-600 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded">
              ● Unsaved changes
            </span>
          )}
          {saveSuccess && (
            <span className="text-xs text-green-600 bg-green-50 border border-green-200 px-2 py-0.5 rounded">
              ✓ Saved
            </span>
          )}
          <button
            onClick={handleSave}
            disabled={!isDirty || saving}
            className={`px-4 py-1.5 text-sm font-medium rounded-md text-white transition-colors ${
              isDirty && !saving
                ? "bg-indigo-600 hover:bg-indigo-700"
                : "bg-gray-300 cursor-not-allowed"
            }`}
          >
            {saving ? "Saving..." : "Save Changes"}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg border border-red-200 mb-4 text-sm">
          {error}
        </div>
      )}

      {/* Two cards side-by-side */}
      <div className="flex gap-5">
        {settings.map((s) => {
          const meta = LABELS[s.id] || { label: s.id, emoji: "", source: "" };
          return (
            <SchedulerCard
              key={s.id}
              setting={s}
              label={meta.label}
              emoji={meta.emoji}
              source={meta.source}
              onChange={(field, value) => handleChange(s.id, field, value)}
              onRefresh={fetchSettings}
            />
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/settings/schedulers/scheduler-settings.tsx
git commit -m "feat: add main scheduler settings component with save and dirty tracking"
```

---

### Task 11: Wire Up the Schedulers Tab in Settings

**Files:**
- Modify: `frontend/src/app/settings/settings-tabs.tsx`
- Modify: `frontend/src/app/settings/page.tsx`

- [ ] **Step 1: Add the tab to settings-tabs.tsx**

In `frontend/src/app/settings/settings-tabs.tsx`, add `"schedulers"` to the TABS array. Find:

```typescript
  { id: "users", label: "Users" },
] as const;
```

Replace with:

```typescript
  { id: "users", label: "Users" },
  { id: "schedulers", label: "Schedulers" },
] as const;
```

- [ ] **Step 2: Add the tab content to page.tsx**

In `frontend/src/app/settings/page.tsx`, add the import at the top:

```typescript
import { SchedulerSettings } from "./schedulers/scheduler-settings";
```

Then find the block:

```typescript
          if (activeTab === "users") {
            return <UsersTable />;
          }

          return null;
```

Replace with:

```typescript
          if (activeTab === "users") {
            return <UsersTable />;
          }

          if (activeTab === "schedulers") {
            return <SchedulerSettings />;
          }

          return null;
```

- [ ] **Step 3: Verify the frontend compiles**

Run:
```bash
cd frontend && npx next build 2>&1 | tail -20
```

Expected: Build succeeds with no errors related to scheduler components.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/settings/settings-tabs.tsx frontend/src/app/settings/page.tsx
git commit -m "feat: wire up Schedulers tab in Settings page"
```

---

### Task 12: End-to-End Verification

- [ ] **Step 1: Start the backend**

Run:
```bash
cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 &
sleep 3
```

- [ ] **Step 2: Verify scheduler-settings endpoint returns defaults**

Run:
```bash
curl -s http://localhost:8000/api/admin/scheduler-settings | python3 -m json.tool
```

Expected: JSON array with two objects (`id: "ro"` and `id: "eu"`) showing default frequencies and times.

Note: This endpoint requires admin auth. If it returns 401, test via the frontend UI instead.

- [ ] **Step 3: Verify the frontend renders the Schedulers tab**

Start the frontend and navigate to `/settings?tab=schedulers`. Verify:
- Two cards appear side-by-side (Romanian Laws and EU Laws)
- Toggle, frequency dropdown, time picker, last/next run info, and Run Now button are visible
- Save Changes button is disabled until you make a change
- Changing a setting shows "Unsaved changes" badge

- [ ] **Step 4: Test save flow**

Change the Romanian frequency to "Every 3 days", click Save Changes. Verify:
- "Saved" confirmation appears
- Next run time updates to reflect the new frequency

- [ ] **Step 5: Test Run Now flow**

Click Run Now on Romanian Laws. Verify:
- Progress bar appears with law count and current law name
- Progress updates every 2 seconds
- On completion, shows summary with discovered versions and errors
- Settings refresh to show updated last run time

- [ ] **Step 6: Clean up and commit**

Stop the backend server. Final commit if any fixes were needed:

```bash
git add -A
git commit -m "fix: end-to-end verification adjustments"
```

---

Plan complete and saved to `docs/superpowers/plans/2026-04-04-scheduler-settings.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?