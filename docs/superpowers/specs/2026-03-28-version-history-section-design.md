# Version History Section — Design Spec

## Overview

Replace the current `VersionsSection` + inline versions list + `CheckUpdatesButton` on the law detail page with a single unified **Version History** section. Three parts: update banner, imported versions table, unimported versions table.

All UI text in English.

---

## Part 1 — Update Banner

Always visible at the top of the version history section.

### Auto-check on page load

- Frontend reads `last_checked_at` from the law detail response.
- If null or older than 1 hour: call the discover/known-versions endpoint to refresh.
- Otherwise: use existing `KnownVersion` data (no network call to legislatie.just.ro).

### States

**New versions available** (unimported known versions exist):
- Amber background (`bg-amber-50 border-amber-200`).
- Text: "{N} new version(s) available".
- Subtitle: "Last checked: {time} · {N} version(s) not yet imported".
- Two buttons:
  - "Import latest version (v{X})" — imports the newest unimported version, updates state inline.
  - "Dismiss" — hides the amber banner for this page session (reappears on next load or manual check).

**Up to date** (all known versions are imported):
- Neutral background (`bg-gray-50 border-gray-200`) with green check icon.
- Text: "No new versions".
- Subtitle: "Last checked: {time} · All available versions are imported".

---

## Part 2 — Imported Versions Table

Shows only versions that exist as `LawVersion` records (fully imported with content).

### Layout

Panel with header: "Imported versions" + badge showing count (e.g. "59 versions"). Blue check icon in header.

Table columns:
| Column | Content |
|--------|---------|
| Ver. | Version number: v1 (oldest) through vN (newest), assigned ordinally by `date_in_force` |
| Date | Published date formatted as "15 Jan 2026" |
| Changes vs previous version | Colored pills: "{N} modified" (blue bg), "{N} added" (green bg), "{N} removed" (red bg). Only show non-zero counts. v1 has no pills. |
| Status | "Current version" (green text) for `is_current=true`, "Imported" (gray badge) for rest |
| Actions | "Read" button, "Compare" button |

### Collapse behavior

- Show only the 3 most recent versions by default.
- If more exist: show a divider row "{X} older versions — Show all" with a down arrow button.
- Clicking expands all older rows with `opacity-60` styling.
- Expanded state toggles to "Hide older versions".

### Actions

- **Read**: Opens `/laws/[id]/versions/[versionId]` in a new tab (`target="_blank"`).
- **Compare**: Scrolls to the `DiffSelector` component on the same page (it remains on the law detail page above the version history section).

---

## Part 3 — Unimported Versions Table

Only visible when unimported `KnownVersion` records exist. Hidden when all are imported.

### Layout

Panel with header: "Not imported from legislatie.just.ro" + badge showing count. Warning icon (amber) in header. Amber-tinted background (`bg-amber-50/50`).

Table columns — same as Part 2, except:
| Column | Content |
|--------|---------|
| Ver. | Version number (continues the ordinal sequence from imported versions) |
| Date | Published date |
| Changes vs previous version | Show pills only if the previous version is imported (diff can be computed). Otherwise leave blank. |
| Status | "Not imported" (amber text) |
| Actions | "+ Import" button (amber outline) |

### Import behavior

- Clicking "+ Import" calls `POST /api/laws/{lawId}/known-versions/import` with `{ ver_id }`.
- On success: remove row from unimported table, add to imported table, update counts. No full page reload.
- When the last unimported version is imported, hide this panel entirely.

---

## Backend Changes

### New DB column

Add `diff_summary` to `LawVersion`:
- Type: JSON (nullable).
- Schema: `{"modified": int, "added": int, "removed": int}` or `null`.
- `null` means: either v1 (no predecessor) or not yet computed.

### Compute diff summary on import

After `fetch_and_store_version` completes successfully:
1. Find the previous version (by `date_in_force`, same law).
2. If a previous version exists, run the existing diff logic (same as `/api/laws/{id}/diff` endpoint) to get article-level changes.
3. Store only the summary counts (`modified`, `added`, `removed`) in `diff_summary`.
4. Also update the *next* version's `diff_summary` if it exists and was computed against a different predecessor (edge case: importing an intermediate version).

### Backfill script

One-time migration/script:
- For each law, iterate versions ordered by `date_in_force`.
- For each consecutive pair, compute diff summary and store.
- Can be run as a standalone management command.

### API response changes

Add `diff_summary` to `LawVersionSummary` in the `/api/laws/{id}` response:
```json
{
  "id": 42,
  "ver_id": "267625",
  "date_in_force": "2026-01-15",
  "date_imported": "2026-01-20T10:00:00",
  "state": "actual",
  "is_current": true,
  "diff_summary": {"modified": 5, "added": 2, "removed": 0}
}
```

No new endpoints needed. All existing endpoints reused.

---

## Frontend Changes

### Delete

- `CheckUpdatesButton` component — functionality absorbed into the update banner.

### Rewrite

- `VersionsSection` → complete rewrite as the new unified version history component.

### Remove from page.tsx

- The inline versions list (the `<div>` with `law.versions.map(...)`) — replaced by the imported versions table.
- The `CheckUpdatesButton` from the header area.
- The `DeleteVersionsButton` — keep as-is, move into the new section header or keep in its current location.

### New sub-components (all within `laws/[id]/`)

- `update-banner.tsx` — The amber/neutral banner with auto-check logic.
- `imported-versions-table.tsx` — Table of imported versions with collapse.
- `unimported-versions-table.tsx` — Table of unimported versions with import actions.

### Styling reference (from design images)

- Panels: white background, rounded border, subtle shadow.
- Table rows: no visible grid lines, clean spacing, hover highlight.
- Pills: small rounded badges with colored backgrounds (blue for modified, green for added, red for removed).
- Buttons: outlined style, rounded, color-matched to context (blue for Read/Compare, amber for Import).
- Current version row: slightly highlighted.
- Version numbers: bold, left-aligned.

---

## What stays the same

- `/laws/[id]/diff` page and `DiffSelector` component — untouched.
- `/laws/[id]/versions/[versionId]` page — untouched.
- `StatusBadge` component — stays in page header.
- `DeleteVersionsButton` — stays on page.
- All existing backend endpoints — reused as-is.
- `KnownVersion` model and discovery logic — reused as-is.

---

## Data flow summary

```
Page loads
  → Fetch law detail (has versions + last_checked_at)
  → If last_checked_at > 1h ago: call discover endpoint (background)
  → Fetch known versions
  → Render:
      Banner (compare known vs imported counts)
      Imported table (from law.versions + diff_summary)
      Unimported table (known versions where is_imported=false)
```
