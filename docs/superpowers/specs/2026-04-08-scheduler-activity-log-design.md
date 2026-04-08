# Scheduler Activity Log — Design

**Date:** 2026-04-08
**Status:** Approved (pending spec review)

## Goal

Record every run of the RO and EU version-discovery schedulers (both
automatically scheduled and manually triggered via "Run Now") into a new
database table, and surface the last 20 runs of each scheduler as a
read-only table inside its card on Settings → Schedulers.

## Non-goals

- No edit, delete, or export affordances. Logs are append-only and
  read-only from the UI.
- No retention/pruning logic. Volume is ~1 row per scheduler per scheduled
  run plus occasional manual triggers — negligible growth.
- No drilldown UI for the full `summary_json` payload in this iteration.
  The column is stored for future debugging use.
- No changes to existing tables or to the existing `SchedulerSetting`
  last-run fields. Those continue to work as before.

## Data model

New SQLAlchemy model `SchedulerRunLog` in
`backend/app/models/scheduler_run_log.py`, mapped to a new table
`scheduler_run_logs`. Created via `Base.metadata.create_all()` on startup
(matching the project's existing additive pattern — no Alembic).

| Column         | Type                           | Notes                                       |
|----------------|--------------------------------|---------------------------------------------|
| `id`           | Integer, PK, autoincrement     |                                             |
| `scheduler_id` | String(8), not null, indexed   | `"ro"` or `"eu"`                            |
| `ran_at`       | DateTime(tz=True), not null    | UTC, indexed                                |
| `trigger`      | String(16), not null           | `"scheduled"` or `"manual"`                 |
| `status`       | String(16), not null           | `"ok"` or `"error"`                         |
| `laws_checked` | Integer, not null, default 0   | From `results["checked"]`                   |
| `new_versions` | Integer, not null, default 0   | From `results["discovered"]`                |
| `errors`       | Integer, not null, default 0   | From `results["errors"]`                    |
| `summary_json` | JSON, nullable                 | Full results dict, stored for future use    |

Composite index `(scheduler_id, ran_at DESC)` to back the listing query.

The model is imported in `backend/app/main.py` alongside the other models
so `Base.metadata.create_all(bind=engine)` picks it up on startup.

## Insertion: one helper, three call sites

A small service module
`backend/app/services/scheduler_log_service.py` exposes:

```python
def record_run(db, scheduler_id: str, results: dict, trigger: str) -> None
```

It builds a `SchedulerRunLog` from the `results` dict that
`run_daily_discovery` and `run_eu_weekly_discovery` already return
(`checked`, `discovered`, `errors`), commits, and returns.

It is called immediately after the existing
`SchedulerSetting.last_run_*` write at three locations:

1. `backend/app/main.py` — `run_update_check()` (RO scheduled)
   → `record_run(db, "ro", results, "scheduled")`
2. `backend/app/main.py` — `run_eu_update_check()` (EU scheduled)
   → `record_run(db, "eu", results, "scheduled")`
3. `backend/app/routers/admin.py` — `_make_discovery_runner()` inner
   `_runner` (both RO and EU manual)
   → `record_run(db, job_type, results, "manual")`

Both the scheduled path and the manual path already converge on writing
the SchedulerSetting last-run fields, so the same single helper covers
both triggers cleanly without restructuring the discovery code.

The helper is best-effort: if the insert fails, it logs a warning but
does not raise — a logging failure must not break the discovery run
itself.

## API

Added to `backend/app/routers/settings_schedulers.py` (existing admin
router with prefix `/api/admin`, admin-auth dependency):

```
GET /api/admin/scheduler-logs?scheduler_id={ro|eu}&limit={int}
```

- `scheduler_id`: required, must be `"ro"` or `"eu"` (400 otherwise)
- `limit`: optional integer, default `20`, capped at `200`
- Admin-only (matches existing routes in the file)
- Response: JSON array, ordered by `ran_at DESC`:

```json
[
  {
    "id": 42,
    "ran_at": "2026-04-08T09:00:03Z",
    "trigger": "scheduled",
    "status": "ok",
    "laws_checked": 142,
    "new_versions": 3,
    "errors": 0
  }
]
```

`summary_json` is intentionally **not** included in the list response —
it stays in the DB for future drilldowns and keeps the payload small.

No POST, PUT, or DELETE endpoints. The table is read-only by API
contract, not just by UI convention.

A corresponding client method is added to
`frontend/src/lib/api.ts` under the existing
`api.settings.schedulers` namespace:

```ts
api.settings.schedulers.listLogs(schedulerId: "ro" | "eu", limit?: number)
```

## UI

Modified file: `frontend/src/app/settings/schedulers/scheduler-card.tsx`.

A new "Recent activity" section is appended **inside** each scheduler
card, below the existing live progress panel. Layout option **A** from
brainstorming: the table lives inside the card and is vertically
scrollable (max-height ~240px) so the two-card grid layout stays intact.

Section structure:

- Section header: "Recent activity" (matches existing card section
  styling)
- Table columns:
  - **Time** — `ran_at` formatted in the user's local timezone
  - **Trigger** — small badge: "auto" for `scheduled`, "manual" for
    `manual`
  - **Checked** — `laws_checked`
  - **New** — `new_versions`
  - **Errors** — `errors`, rendered red when `> 0`
- Empty state: "No runs recorded yet."
- Container: `max-h-60 overflow-y-auto` so it scrolls instead of pushing
  the page

### Data fetching

- Fetch on card mount via `api.settings.schedulers.listLogs(jobType, 20)`
- Refetch when the existing `DiscoveryProgressPanel` reports completion
  of a manual run (so the new row appears immediately after "Run Now")
- No background polling. The card already reflects scheduled runs via
  `last_run_at`; the activity table is allowed to be stale until the
  next mount or manual trigger.

### Read-only enforcement

- No edit, delete, or row-action affordances rendered
- No mutating API endpoints exist
- The model has no UI delete path and no admin override

## Error handling

- API: invalid `scheduler_id` → 400; unauthenticated/non-admin → 401/403
  via existing dependency; empty result set → empty array (200)
- Helper: insert failure logged at WARNING level, swallowed; the
  discovery run's success/failure is unaffected
- Frontend: fetch failure renders an inline "Couldn't load activity"
  message inside the section, leaving the rest of the card functional

## Testing

- Backend unit test: calling `record_run` writes a row with the expected
  fields for both `scheduled` and `manual` triggers
- Backend API test: `GET /api/admin/scheduler-logs` returns rows in
  descending `ran_at` order, respects `limit`, rejects bad
  `scheduler_id`, requires admin auth
- Manual end-to-end check: trigger "Run Now" for RO, confirm a new row
  with `trigger="manual"` appears in the card's activity table after the
  progress panel completes
