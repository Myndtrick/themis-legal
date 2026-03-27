# Version Discovery & Import — Legal Library Design

## Problem

The Legal Library currently auto-imports law versions as they are discovered. This conflates two distinct operations: **knowing a version exists** and **having its full text locally**. The result is that every discovered version triggers a full extraction, the user has no control over what gets imported, and the pipeline cannot distinguish between "we don't have this version" and "this version doesn't exist."

This design separates version **discovery** (lightweight metadata) from version **import** (full structural extraction), giving the user explicit control over what lives in their library while ensuring the system always knows what officially exists.

### Three distinct concepts

| Concept | Definition | Storage |
|---|---|---|
| **Officially exists** | A version published by the legislature on legislatie.just.ro | `KnownVersion` table |
| **Known to the system** | The system has discovered this version via daily checking | `KnownVersion` row with `discovered_at` |
| **Imported locally** | Full text extracted and available for Q&A pipeline | `LawVersion` row with articles/structure |

These three states must remain distinguishable in the data model, the UI, and the pipeline logic.

## Design

### A. UX Structure — Law Detail Page

The law detail page gains a **Versions** section below the existing header/metadata:

```
+---------------------------------------------------+
|  Legea 31/1990 -- Legea societatilor              |
|  Category: Drept comercial  |  Status: actual     |
|                                                    |
|  Last checked: 27 Mar 2026, 03:15                 |
|  * 2 versions not imported                        |
+---------------------------------------------------+
|  Versions                     [Import all missing] |
|                                                    |
|  # v2025-09-15  |  In force: 15 Sep 2025          |
|    CURRENT - IMPORTED                              |
|                                                    |
|  o v2025-03-01  |  In force: 01 Mar 2025          |
|    NOT IMPORTED                        [Import]    |
|                                                    |
|  o v2024-12-06  |  In force: 06 Dec 2024          |
|    NOT IMPORTED                        [Import]    |
|                                                    |
|  # v2024-06-15  |  In force: 15 Jun 2024          |
|    IMPORTED                                        |
|                                                    |
|  ... (older versions collapsed, expandable)        |
+---------------------------------------------------+
```

#### Key UX details

- **"Last checked"** — always visible in the law header. Shows the date of the last successful check against legislatie.just.ro.
- **Versions list** — ordered newest first. Each row shows:
  - Version identifier (`ver_id`)
  - Date in force
  - Two independent badges:
    - **CURRENT** (green) — this is the current official version
    - **IMPORTED** (blue) / **NOT IMPORTED** (grey) — whether full text exists locally
- **Import controls** — per-version `[Import]` button for unimported versions, plus a bulk `[Import all missing]` at the section top.
- **Law card badge** — on the library list page, laws with unimported newly discovered versions show a badge: "1 new version available."
- **Older versions** — if a law has many versions (some Romanian codes have 50+), collapse versions older than 2 years behind a "Show older versions" expander.
- **Import all confirmation** — for laws with many unimported versions, "Import all missing" shows a count and confirmation dialog: "Import 47 versions? This may take several minutes."

### B. Data Model Changes

#### 1. New `KnownVersion` table

```
known_versions
  id              serial PRIMARY KEY
  law_id          integer NOT NULL  -> laws.id
  ver_id          varchar UNIQUE    -- legislatie.just.ro identifier
  date_in_force   date NOT NULL
  is_current      boolean DEFAULT false  -- is this the current official version?
  discovered_at   timestamp NOT NULL     -- when our system first saw this version

  UNIQUE(law_id, ver_id)
```

This table is **append-mostly**: new rows when versions are discovered, updates only to `is_current` when a newer version appears.

#### 2. New field on `Law`

```
laws
  + last_checked_at  timestamp, nullable  -- null means "never checked"
```

Updated only on successful checks. Stays unchanged on failures (silent retry).

#### 3. Linking `KnownVersion` to `LawVersion`

No explicit FK between the two tables. They link through matching `ver_id`:

- `KnownVersion.ver_id` = "this version exists officially"
- `LawVersion.ver_id` = "this version is imported with full text"
- A version is **imported** if a `LawVersion` row exists with the same `ver_id`
- A version is **not imported** if only the `KnownVersion` row exists

Key queries:

- **All known versions with import status:** `LEFT JOIN law_versions ON known_versions.ver_id = law_versions.ver_id`
- **Unimported versions:** `KnownVersion WHERE ver_id NOT IN (SELECT ver_id FROM law_versions WHERE law_id = ?)`
- **"New versions available" count (for badge):** count of unimported known versions where `discovered_at` > last time user viewed the law

#### What stays the same

- `LawVersion` is untouched — keeps its existing structure with full article hierarchy
- `Article`, `Paragraph`, etc. still FK to `LawVersion`
- The import process remains identical: fetch from leropa, parse structure, write to `LawVersion` + child tables
- After import, the `KnownVersion` row already exists — the JOIN just starts matching

### C. Daily Version Discovery

The daily checker evolves from the current `update_checker.py` into a **two-phase** job that discovers versions without importing them.

#### Phase 1: Discover versions (all laws)

For each law in the database that has a `ver_id` (sourced from legislatie.just.ro):

1. Fetch the document's `history` list from leropa
2. For each version in the history:
   - If a `KnownVersion` row with that `ver_id` already exists -> skip
   - If new -> insert into `KnownVersion` with `discovered_at = now()`
3. Determine which version is current (first in history list = newest) -> update `is_current` flags across all `KnownVersion` rows for this law
4. Update `law.last_checked_at = now()`

#### Phase 2: Notify (only for new discoveries)

For any `KnownVersion` rows just inserted that have **no matching `LawVersion`**:
- Create the notification/badge data: "1 new version available" on the law card

#### What it does NOT do

- Does **not** import any text. No articles, no structural parsing.
- Does **not** modify `LawVersion` at all.
- Does **not** alert on failure — if legislatie.just.ro is unreachable for a specific law, it silently skips that law and leaves `last_checked_at` unchanged.

#### Scheduling

- Runs once daily (e.g., 03:00 local time via cron or celery beat)
- Processes laws in parallel (batches of 5-10 to avoid hammering the source)
- Expected duration: ~2-5 minutes for the full library (metadata pages only, not full documents)

#### Relationship to existing `update_checker.py`

The current `update_checker.py` both discovers AND auto-imports new versions. Under this design:
- Discovery logic moves to this new daily job (writes `KnownVersion` only)
- Auto-import behavior is **removed** — importing only happens on explicit user action
- `update_checker.py` gets refactored or replaced

### D. "Last Checked" — Storage and Display

#### Storage

- `law.last_checked_at` — nullable `timestamp with time zone` on the `Law` model
- Set to `now()` only after a **successful** history fetch from legislatie.just.ro
- Starts as `null` for newly added laws (means "never checked")
- Never reset or cleared — always reflects the last successful check

#### Display

**On the law detail page**, shown as human-readable time:

| Condition | Display |
|---|---|
| Less than 24h ago | "Last checked: today at 03:15" |
| 1-7 days ago | "Last checked: 2 days ago" |
| Older than 7 days | "Last checked: 19 Mar 2026" |
| Never checked | "Not yet checked" (grey text) |

**On the law card (library list):**
- Not shown — the card already has the "new version available" badge as the actionable signal
- `last_checked_at` is a detail for the law detail page only

#### Staleness logic

No hard "stale" warning in the UI for the check timestamp itself. The system checks daily, so under normal operation `last_checked_at` is always within ~24 hours. If it drifts (server down for days), the date simply shows an older timestamp. This aligns with silent failure handling — no separate warning state needed.

### E. Pipeline Version-Awareness vs Imported-Status

The Q&A pipeline must never silently use stale data. This section describes how the pipeline uses both `KnownVersion` and `LawVersion` to make informed decisions.

#### At Step 2 (Law Mapping): check both tables

When the pipeline identifies applicable laws, `check_laws_in_db()` expands to query both tables. For each candidate law, the pipeline now determines:

- **What's official** — from `KnownVersion`: which versions exist, which is current
- **What's imported** — from `LawVersion`: which versions have full text locally
- **The gap** — any official versions (especially the current one) that aren't imported

This produces a `version_status` per law:

| Status | Meaning |
|---|---|
| `up_to_date` | Current official version is imported |
| `stale` | Current official version exists in `KnownVersion` but is NOT imported; an older version is imported |
| `missing` | Law has no imported versions at all |
| `not_checked` | Law has no `KnownVersion` rows yet (`last_checked_at` is null) — treat same as current behavior |

#### At Step 2.5 (Early Relevance Gate): pause on stale PRIMARY laws

| Status + Role | Pipeline behavior |
|---|---|
| `up_to_date` (any role) | Proceed normally |
| `stale` + PRIMARY | **Pause** — show user the version gap, offer import |
| `stale` + SECONDARY | Proceed with imported version, flag it |
| `missing` (any role) | Pause (existing behavior) |
| `not_checked` (any role) | Proceed with imported version, add disclaimer |

**Pause message (Romanian):**

> "Am verificat versiunile legilor aplicabile. Legea {law_number}/{law_year} are o versiune mai noua pe legislatie.just.ro (din {official_latest_date}) fata de cea din biblioteca dumneavoastra (din {db_latest_date}). Doriti sa actualizam?"

User decisions on pause:

| Decision | Behavior |
|---|---|
| **Import** | Import the newer version (full extraction via existing `import_law_smart` flow), then resume from Step 3 |
| **Continue anyway** | Proceed with stale version, flag in reasoning, cap confidence |

#### At Step 7 (Answer Generation): version-aware disclaimers

The answer prompt receives version context. When stale versions are used, the generated answer must include:

> **Nota:** Acest raspuns se bazeaza pe versiunea din {db_latest_date} a Legii {law_number}/{law_year}. O versiune mai recenta (din {official_latest_date}) este disponibila pe legislatie.just.ro dar nu a fost importata in biblioteca. Recomandam verificarea cu versiunea actualizata.

When `not_checked`: disclaimer that version currency could not be verified against the official source.

When `up_to_date`: no disclaimer needed.

#### Confidence scoring

- Answer based on `stale` version (user chose to skip import) -> confidence capped at MEDIUM
- Answer based on `not_checked` law -> confidence capped at MEDIUM
- `up_to_date` -> no cap applied

#### What the pipeline never does

- Never imports versions on its own — importing is always a user action
- Never silently assumes the imported version is current — always checks `KnownVersion`
- Never blocks on SECONDARY laws being stale — only flags them

#### Relationship to existing version-currency-verification spec

The existing `2026-03-26-version-currency-verification.md` spec describes a real-time check against legislatie.just.ro during pipeline execution (Step 2a). With this new design:

- The **daily checker** populates `KnownVersion` with fresh metadata
- The **pipeline** reads from `KnownVersion` (a local DB query) instead of making live HTTP requests to legislatie.just.ro
- This is **faster** (DB query vs HTTP) and **more reliable** (no dependency on external source during Q&A)
- The real-time check from the existing spec becomes a **fallback** for laws where `last_checked_at` is null or very old (>7 days), rather than the primary mechanism

### F. Edge Cases

#### 1. Law added manually (no `ver_id`)

Laws without a legislatie.just.ro identifier cannot be checked. `last_checked_at` stays null, `KnownVersion` stays empty. Pipeline treats as `not_checked` with disclaimer. UI shows "Not yet checked."

#### 2. legislatie.just.ro changes `ver_id` format

If the source changes how version IDs are structured, old `KnownVersion.ver_id` entries won't match new ones. Mitigation: the daily checker matches on `law_id + date_in_force` as a fallback when `ver_id` doesn't match any existing row, and logs a warning for manual review.

#### 3. A law is repealed / abrogated

The history list may stop growing. The daily checker still runs, updates `last_checked_at`, but discovers nothing new. The current version's `is_current` stays true. Capturing abrogation status is a future enhancement.

#### 4. Version imported before discovery

If a `LawVersion` exists (from old auto-import or manual import) but the daily checker hasn't run yet, there's no matching `KnownVersion` row.

Resolution — both:
- **Migration at deploy:** seed `KnownVersion` from existing `LawVersion` rows for clean initial state
- **Natural backfill:** when the daily checker first runs for this law, it discovers all versions including the already-imported one — the JOIN starts matching

#### 5. Multiple versions with the same `date_in_force`

Rare but possible (e.g., a correction published the same day). The `ver_id` is the true unique identifier, not the date. The UI shows both, distinguished by `ver_id`.

#### 6. User imports a version, then a newer one appears next day

The imported version stays imported. The new version appears as "NOT IMPORTED" with the "CURRENT" badge. The law card gets the "new version available" badge. Pipeline flags this law as `stale` at query time. No data is lost or overwritten.

#### 7. Very large version history (50+ versions)

Some codes (e.g., Codul fiscal) have dozens of consolidations. The daily checker writes all of them to `KnownVersion` — just metadata, so storage is trivial (~100 bytes per row). The UI collapses older versions. "Import all missing" shows a count and confirmation dialog.

#### 8. Race condition: user imports while daily checker runs

The daily checker only writes `KnownVersion`. Import only writes `LawVersion` + child tables. They touch different tables, so no conflict. The JOIN resolves correctly regardless of ordering.

## Summary of changes by file

| File | Change |
|---|---|
| `backend/app/models/law.py` | Add `KnownVersion` model, add `last_checked_at` to `Law` |
| `backend/app/services/update_checker.py` | Refactor: write to `KnownVersion` instead of auto-importing; add notification logic |
| `backend/app/services/law_mapping.py` | Extend `check_laws_in_db()` to query `KnownVersion` and produce `version_status` |
| `backend/app/services/pipeline_service.py` | Use `version_status` in Step 2.5 pause logic; pass stale info to Step 7; extend confidence scoring |
| `backend/prompts/LA-S7-answer-qa.txt` | Add stale version disclaimer instructions |
| `frontend/src/app/laws/[id]/page.tsx` (or equivalent) | New Versions section on law detail page |
| `frontend/src/app/laws/law-card.tsx` | Add "new version available" badge |
| `frontend/src/app/assistant/import-prompt.tsx` | Add `stale` display state |
| `frontend/src/app/assistant/reasoning-panel.tsx` | Add version status row |
| Migration script | Create `known_versions` table, add `last_checked_at` column, seed from existing `LawVersion` rows |
