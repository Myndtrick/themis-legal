# Scheduler Settings — Design Spec

**Date:** 2026-04-04
**Status:** Approved

## Overview

Two problems addressed in sequence:

1. **Scheduler reliability** — APScheduler running in-process with no timezone, no misfire handling, and no error visibility. Fixed by configuring UTC timezone, 12-hour misfire grace time, and job event listeners. Admin endpoints added for status and manual triggering. **(Already implemented.)**

2. **Scheduler settings UI** — New "Schedulers" tab in the Settings page to control both version-check schedulers (Romanian laws, EU laws) with persistent configuration.

## Problem 1 — Scheduler Fix (Completed)

### Changes Made

**`backend/app/scheduler.py`:**
- Explicit `timezone=datetime.timezone.utc` on `BackgroundScheduler`
- `EVENT_JOB_EXECUTED` and `EVENT_JOB_ERROR` listeners that log outcomes and track results in `last_run_results` dict

**`backend/app/main.py`:**
- `misfire_grace_time=43200` (12 hours) on both cron jobs — if the server restarts and the job was missed within the last 12 hours, it runs immediately instead of being silently skipped

**`backend/app/routers/admin.py`:**
- `GET /api/admin/scheduler-status` — returns scheduler running state, job list with next run times, last run results
- `POST /api/admin/trigger-discovery/{job_type}` — manually trigger `ro` or `eu` discovery in a background thread

## Problem 2 — Scheduler Settings UI

### New Settings Tab

A new "Schedulers" tab added to the existing Settings page (`settings-tabs.tsx`), alongside Prompts, Pipeline, Categories, etc.

### Layout

Two cards side-by-side, one per scheduler:

- **Left card:** 🇷🇴 Romanian Laws (source: legislatie.just.ro)
- **Right card:** 🇪🇺 EU Laws (source: EU Cellar API)

### Controls Per Card

1. **On/Off Toggle** — top-right of card header. Shows "Enabled"/"Disabled" label. When disabled, the scheduler does not run regardless of other settings.

2. **Frequency Dropdown** — options:
   - Every day
   - Every 3 days
   - Once a week
   - Once a month
   - Defaults: daily for Romanian, weekly for EU

3. **Time Picker** — hour:minute input (24h format) with a "UTC" badge displayed next to it. Defaults: 03:00 for Romanian, 04:00 for EU.

4. **Last Run / Next Run** — read-only info box showing:
   - Last run: datetime in UTC (or "Never" if not yet run)
   - Next run: computed from frequency + time settings, displayed in UTC

5. **Run Now Button** — triggers immediate discovery regardless of schedule. Indigo button at bottom of card.

### Save Behavior

- A **Save Changes** button in the top bar, right-aligned
- An **"Unsaved changes"** amber badge appears when any setting is modified
- Clicking Save persists all changes in a single API call
- Changes take effect immediately: the backend reschedules the APScheduler jobs with the new frequency/time

### Run Now — Progress Feedback

When "Run Now" is clicked:
1. Button changes to disabled "Running..." state
2. A green progress section appears below the card showing:
   - Progress bar with "X / Y laws" count
   - Name of the law currently being checked
3. Frontend polls a status endpoint to get progress updates
4. On completion, shows summary: "Discovery complete — N new versions found · M errors"
5. Progress section remains visible until dismissed or next action

### Backend: Persistent Scheduler Settings

#### New Database Table: `scheduler_settings`

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key: `"ro"` or `"eu"` |
| `enabled` | BOOLEAN | Whether scheduler is active. Default: `true` |
| `frequency` | VARCHAR | One of: `"daily"`, `"every_3_days"`, `"weekly"`, `"monthly"`. Defaults: `"daily"` (ro), `"weekly"` (eu) |
| `time_hour` | INTEGER | Hour in UTC (0-23). Defaults: 3 (ro), 4 (eu) |
| `time_minute` | INTEGER | Minute (0-59). Default: 0 |
| `last_run_at` | DATETIME | When the scheduler last ran successfully (nullable) |
| `last_run_status` | VARCHAR | `"ok"`, `"error"`, or null |
| `last_run_summary` | JSON | Summary dict: `{checked, discovered, errors}` (nullable) |

This table is seeded on startup with default rows for `"ro"` and `"eu"` if they don't exist. Existing data is never deleted or modified during seeding.

#### New API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/scheduler-settings` | Return settings for both schedulers |
| `PUT` | `/api/admin/scheduler-settings` | Save settings for both schedulers (batch). Reschedules APScheduler jobs. |
| `POST` | `/api/admin/trigger-discovery/{job_type}` | Trigger immediate run (already implemented) |
| `GET` | `/api/admin/discovery-progress/{job_type}` | Poll progress during a manual run |

#### Scheduler Reconfiguration

When settings are saved via PUT:
1. Update `scheduler_settings` rows in the database
2. Remove existing APScheduler jobs (`daily_law_update`, `weekly_eu_discovery`)
3. If enabled, re-add them with the new cron expression derived from frequency + time
4. If disabled, do not re-add (job stays removed until re-enabled)

Frequency-to-trigger mapping:
- `daily` → cron trigger: `hour=H, minute=M` (every day)
- `every_3_days` → interval trigger: `days=3`, with `start_date` set to today at H:M UTC (APScheduler's cron `day` field is day-of-month, not interval — must use interval trigger for "every N days")
- `weekly` → cron trigger: `day_of_week='sun', hour=H, minute=M` (every Sunday)
- `monthly` → cron trigger: `day=1, hour=H, minute=M` (1st of each month)

#### Progress Tracking for Manual Runs

The discovery functions (`run_daily_discovery`, `run_eu_weekly_discovery`) need minor changes to report progress to a shared dict that the progress endpoint can read:

```python
# Shared progress state
discovery_progress: dict[str, dict] = {}
# Example: {"ro": {"running": True, "current": 12, "total": 47, "current_law": "Legea nr. 287/2009", "results": None}}
```

The progress endpoint reads this dict. The discovery functions update it as they iterate through laws. The frontend polls this endpoint every 2 seconds while a run is in progress.

#### Startup Behavior

On app startup (`main.py` lifespan):
1. Read `scheduler_settings` from database
2. For each scheduler: if enabled, register the APScheduler job with the configured frequency/time
3. If the table doesn't exist yet or rows are missing, seed defaults and register with default schedule
4. Apply `misfire_grace_time=43200` to all jobs

### Frontend Components

| File | Purpose |
|------|---------|
| `frontend/src/app/settings/schedulers/scheduler-settings.tsx` | Main component: fetches settings, renders two cards, handles save |
| `frontend/src/app/settings/schedulers/scheduler-card.tsx` | Single scheduler card: toggle, frequency, time, last/next run, Run Now |
| `frontend/src/app/settings/schedulers/discovery-progress.tsx` | Progress bar component: polls progress endpoint, shows completion summary |

### Error States

- **Save fails:** Toast/inline error "Failed to save scheduler settings"
- **Run Now fails to start:** Button shows error state, reverts after 3 seconds
- **Discovery errors during run:** Shown in completion summary ("N errors") — not blocking
- **Scheduler disabled:** Card visually muted (lower opacity on controls below toggle), Run Now still available (manual override). "Next run" shows "—" instead of a date.

### What This Does NOT Change

- No changes to existing database tables (laws, law_versions, known_versions, etc.)
- No changes to the discovery logic itself (version_discovery.py, eu_version_discovery.py)
- No data deletion or migration of existing data
- The `scheduler_settings` table is purely additive
