# Per-Law Check Log — Design

**Date:** 2026-04-08
**Status:** Approved (pending spec review)
**Builds on:** `2026-04-08-scheduler-activity-log-design.md`

## Goal

Record every per-law update check (`POST /api/laws/{law_id}/check-updates`)
into a new append-only table, and surface it in two places:

1. **Settings → Schedulers** — a new full-width section "Per-law update
   checks" below the two scheduler cards, showing the last 20 checks
   across both sources combined.
2. **Law detail page** — a new section "Recent update checks" showing the
   last 20 checks for that specific law.

## Non-goals

- No edit, delete, or export affordances. Logs are append-only and
  read-only from the UI.
- No retention/pruning. Volume is expected to be modest; revisit if
  growth becomes a concern.
- **No "View all" link in v1.** The Settings section shows last 20
  combined, full stop. We can add pagination later if needed.
- No changes to the existing scheduler activity log table or UI.
- No changes to existing tables.

## Data model

New SQLAlchemy model `LawCheckLog` in
`backend/app/models/law_check_log.py`, mapped to a new table
`law_check_logs`. Created via `Base.metadata.create_all()` on startup
(matching the project's existing additive pattern).

| Column          | Type                            | Notes                                       |
|-----------------|---------------------------------|---------------------------------------------|
| `id`            | Integer, PK, autoincrement      |                                             |
| `law_id`        | Integer, FK → laws.id, not null | Indexed                                     |
| `source`        | String(8), not null             | `"ro"` or `"eu"` — denormalized from `Law.source` to avoid a join in the combined feed |
| `checked_at`    | DateTime(tz=True), not null     | UTC, indexed                                |
| `user_id`       | Integer, FK → users.id, nullable| The triggering user; nullable for safety    |
| `new_versions`  | Integer, not null, default 0    | Number of new KnownVersion rows discovered  |
| `status`        | String(16), not null            | `"ok"` or `"error"`                         |
| `error_message` | String(512), nullable           | First 512 chars of the exception, if any    |

Indexes:
- `(checked_at DESC)` for the combined feed query
- `(law_id, checked_at DESC)` for the per-law history query

The `source` denormalization is intentional — the combined feed query
needs to filter and group by source without joining `laws`, and `Law.source`
never changes for a given law so denormalization is safe.

## Insertion: one helper, one call site

A new service module
`backend/app/services/law_check_log_service.py` exposes:

```python
def record_check(
    db,
    law: Law,
    user_id: int | None,
    new_versions: int,
    status: str,
    error_message: str | None = None,
) -> None
```

Best-effort like `scheduler_log_service.record_run`: a logging failure is
logged at WARNING level and swallowed. Rollback attempted.

It is called inside `check_law_updates` in `backend/app/routers/laws.py`
on both the success and exception paths:

- Success: `record_check(db, law, user.id if user else None, new_count, "ok")`
- Exception: `record_check(db, law, user.id if user else None, 0, "error", str(e)[:512])`

### Auth — no contract change

The laws router already enforces auth at the router level
(`backend/app/routers/laws.py:23` — `APIRouter(..., dependencies=[Depends(get_current_user)])`),
so `check_law_updates` already requires a logged-in user. Capturing
`user_id` is purely additive: we add an explicit
`current_user: User = Depends(get_current_user)` parameter to the
function signature so the body can read `current_user.id`. No callers
break, no 401s for anyone who could already call this endpoint.

The `user_id` column on `LawCheckLog` is still nullable for
forward-compat (e.g., a deleted user, or a future system-triggered call
path) — but in practice every row written today will have a non-null
user.

## API

Two new admin/user-readable endpoints, both read-only.

### 1. Combined feed (admin-only)

Added to `backend/app/routers/settings_schedulers.py`:

```
GET /api/admin/law-check-logs?limit=20
```

- `limit`: optional, default 20, capped at 200
- Admin-only via existing `require_admin` dependency
- Returns rows ordered by `checked_at DESC`, regardless of source/law
- Each row joins the `laws` table (for title / law_number / law_year) and
  the `users` table (for the triggering user's email or display name)

Response shape:

```json
[
  {
    "id": 42,
    "law_id": 17,
    "source": "ro",
    "law_label": "Legea 31/1990 — Legea societăților",
    "checked_at": "2026-04-08T14:22:03Z",
    "user_email": "ana@example.com",
    "new_versions": 1,
    "status": "ok",
    "error_message": null
  }
]
```

### 2. Per-law history

Added to `backend/app/routers/laws.py`:

```
GET /api/laws/{law_id}/check-logs?limit=20
```

- `limit`: optional, default 20, capped at 200
- Requires `Depends(get_current_user)` (same baseline as the rest of the
  laws router — any logged-in user who can see the law can see its check
  history)
- 404 if `law_id` does not exist
- Returns rows ordered by `checked_at DESC`, scoped to that one law

Response shape (note: no `law_label`/`source` since they are constant):

```json
[
  {
    "id": 42,
    "checked_at": "2026-04-08T14:22:03Z",
    "user_email": "ana@example.com",
    "new_versions": 1,
    "status": "ok",
    "error_message": null
  }
]
```

Frontend client methods added to `frontend/src/lib/api.ts`:
- `api.settings.schedulers.listLawCheckLogs(limit?)`
- `api.laws.listCheckLogs(lawId, limit?)`

## UI

### Settings → Schedulers

Modified file:
`frontend/src/app/settings/schedulers/scheduler-settings.tsx`.

A new section is appended below the two-card grid (full width):

```
─── Per-law update checks ─────────────────────────────────
 Time             Source  Law                 New  By
 Apr 8 14:22      RO      Legea 31/1990         1  ana
 Apr 8 11:05      EU      Reg 2016/679          0  ana
 ...
```

- New component
  `frontend/src/app/settings/schedulers/law-check-log-table.tsx`
- Columns: **Time** (local), **Source** (badge, RO/EU), **Law** (number/year
  truncated), **New** (number, gray when 0), **By** (user email — first
  segment before @, truncated)
- An **Errors** column is shown only when at least one row in the loaded
  set has `status="error"`; otherwise hidden to keep the table compact
- Empty state: "No per-law checks recorded yet."
- Error state: "Couldn't load per-law check log."
- Refetched on mount only (no polling, no parent-driven refresh — manual
  per-law checks happen on the law detail page, not on Settings, so
  cross-page refresh is not needed)

### Law detail page

Modified file: `frontend/src/app/laws/[id]/page.tsx`.

A new "Recent update checks" section is added near the existing
`update-banner` block.

- New component
  `frontend/src/app/laws/[id]/check-history-section.tsx`
- Columns: **Time** (local), **New**, **Result** (ok ✓ / error with
  hover-tooltip showing `error_message`), **By**
- Empty state: "No update checks recorded yet."
- Refetched on mount AND immediately after the user clicks "Check for
  updates" in the existing `update-banner.tsx` (so the new row appears
  without a page reload). Coordination uses a small `refreshKey` prop
  bumped from a parent state, mirroring the SchedulerCard pattern.

## Read-only enforcement

- No mutating endpoints (no POST/PUT/DELETE for `law-check-logs` or
  `check-logs`)
- No edit/delete affordances in either UI
- `error_message` is rendered as plain text only (no HTML, no link)

## Error handling

- API: 404 for unknown `law_id` on the per-law endpoint; 401 for missing
  auth on either endpoint; 200 + empty array for empty result sets
- Helper: insert failure logged at WARNING and swallowed; the underlying
  per-law check still returns its result to the caller
- Frontend: fetch failure shows an inline "Couldn't load…" message in the
  affected section, leaving the rest of the page functional

## Testing

Backend:
- Unit test: `record_check` writes a row with the expected fields for
  both `ok` and `error` paths
- API test: combined feed returns rows in descending `checked_at` order,
  caps at 200, requires admin
- API test: per-law endpoint scopes to the requested law, returns 404 for
  missing law, requires auth
- Integration: a successful `POST /api/laws/{id}/check-updates` writes a
  matching `LawCheckLog` row visible in both the combined feed and the
  per-law endpoint
- Integration: a failing `POST /api/laws/{id}/check-updates` writes a
  `LawCheckLog` row with `status="error"` and an `error_message`

Frontend:
- `tsc --noEmit` clean
- Manual smoke test: trigger a per-law check from a law detail page,
  confirm the new row appears in both (a) the law's "Recent update
  checks" section and (b) the Settings → Schedulers "Per-law update
  checks" section after navigating there
