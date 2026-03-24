# Legal Library Redesign — Category System & UI Overhaul

## Overview

Redesign the Legal Library page with a category-based organization system, combined local+external search, and a phased rollout across three phases.

**Source spec**: `docs/law_category_mapping_prompt (3).md` — defines the full taxonomy, seed data, and hard rules. This design spec captures architectural decisions and UI behavior agreed during brainstorming. The source spec remains authoritative for taxonomy data and business rules.

---

## Architecture Decision: Client-Side Filtering

All imported laws are returned in a single API call (`GET /api/laws/library`). The frontend handles grouping, filtering, and stat recalculation client-side. This is appropriate because the library is a curated collection unlikely to exceed a few hundred laws.

---

## Phase 1: DB Schema + Seed Data + Library Page Redesign

### 1.1 Database Schema

**New tables** (as defined in source spec Section 1):

- **`category_groups`** — 9 top-level groups. Fields: `id`, `slug`, `name_ro`, `name_en`, `color_hex`, `sort_order`.
- **`categories`** — ~35 subcategories. Fields: `id`, `group_id` (FK → category_groups), `slug` (e.g. `"civil.property"`), `name_ro`, `name_en`, `description`, `is_eu`, `sort_order`.
- **`law_mappings`** — lookup table for pre-filling category during import. Fields: `id`, `title`, `law_number`, `category_id` (FK → categories), `source` (`'seed'`/`'user'`), `created_at`.

**Changes to `laws` table**:
- Add `category_id INTEGER REFERENCES categories(id)` — nullable, NULL = unclassified.
- Add `category_confidence TEXT CHECK (category_confidence IN ('manual', 'unclassified'))`.

**SQLAlchemy models**: `CategoryGroup`, `Category`, `LawMapping`. `Law` gets `category_id`, `category_confidence` fields + relationship to `Category`.

**Migration**: Alembic migration creates tables, seeds groups/categories/mappings (source spec Sections 2–3), sets all existing laws to `category_id = NULL, category_confidence = 'unclassified'`.

### 1.2 API

**`GET /api/laws/library`** — single endpoint returning everything the frontend needs:

```json
{
  "groups": [
    {
      "id": 1, "slug": "constitutional", "name_en": "Constitutional law",
      "name_ro": "Drept constituțional", "color_hex": "#534AB7", "sort_order": 1,
      "categories": [
        { "id": 1, "slug": "constitutional.revision", "name_en": "Constitution & revision",
          "name_ro": "Constituție și revizuire", "law_count": 1 }
      ]
    }
  ],
  "laws": [
    {
      "id": 5, "title": "Constituția din 21.11.1991",
      "law_number": "unknown", "law_year": 1991, "document_type": "law",
      "version_count": 1, "status": "in_force",
      "category_id": 1, "category_group_slug": "constitutional",
      "current_version": { "id": 10, "state": "republished" }
    }
  ],
  "stats": {
    "total_laws": 12, "total_versions": 24, "last_imported": "2026-03-17"
  },
  "suggested_laws": [
    {
      "title": "Legea 287/2009 — Codul Civil", "law_number": "287",
      "category_slug": "civil.general", "group_slug": "civil",
      "already_imported": false
    }
  ]
}
```

**`PATCH /api/laws/{law_id}/category`** — body: `{ "category_id": 5 }`. Sets `category_id` and `category_confidence = 'manual'`. Inserts into `law_mappings` if not already there.

**`GET /api/laws/local-search?q=...`** — searches imported laws by title/number for the combined search dropdown. Returns matches with category info.

### 1.2.1 Duplicate law mappings policy

Several laws in the seed data appear in multiple categories (e.g., Legea 85/2014 in both `civil.procedure` and `commercial.insolvency`). The `law_mappings` table allows multiple rows per `law_number` — each maps to a different category. During import lookup, the first match pre-fills the category selector, but the user can change it. Laws themselves belong to exactly one category (single `category_id` on `laws`).

### 1.3 Frontend — Page Layout

The page has three regions: header (title + search), sidebar (left), and main content (right).

**Header**:
- Title: "Legal Library" with subtitle "Browse Romanian laws with full version history".
- Combined search bar (see Section 1.5).

**Sidebar** (fixed-width, left):
- **CATEGORIES** section:
  - "All laws" item with total count badge (always first, highlighted when active).
  - Expandable category groups — clicking the arrow expands to show subcategories with law counts. Clicking a group name filters main view to that group's laws. Clicking a subcategory filters more narrowly.
  - Only groups with ≥1 imported law shown in the active section.
- **STATUS** section (below a divider):
  - Filters by version `state` field (actual, republished, amended, deprecated) — not law-level `status`.
  - Clickable status filters matching `DocumentState` enum: Actual, Republished, Amended, Deprecated — with counts.
  - Cross-filters with category selection (e.g., Constitutional + Actual).
- **Suggested categories** (below a divider):
  - Collapsed by default, labeled "Sugestii neimportate (N)".
  - Expands to show groups with zero imported laws in muted/italic style.
  - Clicking a suggested group shows its predefined laws from `law_mappings` with individual Import buttons.

**Main content** (right):
- **Stats cards**: Total laws, Total versions, Last imported — update to reflect current category/status filter.
- **Laws grouped by category**: Each group shows its color dot, name, law count, and a "See all →" link.
  - Default: show first 2-3 laws per group.
  - "See all →" expands the section in-place to show all laws in that group.
  - Each law card shows: title, identifier (e.g. "Legea 287/2009"), status badge, version count.
  - Clicking a law card navigates to `/laws/{id}`.
- **Per-category suggestions** (source spec Section 6):
  - When a specific category group is selected and has imported laws, show a "Sugestii pentru această categorie" sub-section below the imported laws.
  - Lists unimported laws from `law_mappings` that belong to this category.
  - Visually distinct: dashed border, reduced opacity.
  - Each has an individual "+ Importă" button. Clicking triggers the full import flow with the category pre-filled in the confirmation modal. The user still sees the modal and must confirm (per hard rule: "always show the confirmation dialog").
  - Never mixed with imported laws.
- **"Necategorizat" section** (bottom, below a dashed divider):
  - Shows laws with `category_confidence = 'unclassified'`.
  - Amber "Fără categorie" badge.
  - Each card has an "Assign category" button opening the category modal.

### 1.4 Frontend — Category Assignment Modal

Reusable modal component used for:
1. Assigning a category to an existing unclassified law (Phase 1).
2. Confirming a category during import (Phase 2).

**Modal contents**:
- Law title (read-only) at the top.
- Search input to filter categories by name.
- Grouped category list: groups as collapsible headers with color dots, subcategories as selectable radio items with description text.
- Pre-filled with matched category from `law_mappings` when available.
- Three buttons: "Confirm" (saves `manual`), "Skip" (keeps `unclassified`), "Cancel".

### 1.5 Frontend — Combined Search

The search bar searches both local library and legislatie.just.ro:

- **As you type (≥3 chars)**: local results appear instantly (debounced ~300ms) at the top of a dropdown.
- **Click Search or press Enter**: external results from legislatie.just.ro load async below a divider, with loading spinner.
- **Dropdown sections**:
  - "IN YOUR LIBRARY (N)" — local matches, clicking navigates to law detail page. Shows category name and status badge.
  - "FROM LEGISLATIE.JUST.RO (N)" — external matches with Import button (version choice dropdown) or "Already imported" badge.
- **Filters button**: opens advanced filters (Act Type, Year, Emitent, dates) — applies only to external search. Sidebar handles local filtering.
- **Paste a URL**: detects legislatie.just.ro links, skips local search, shows direct import option.
- **Dismiss**: clicking outside or clearing search closes the dropdown, library view returns.

---

## Phase 2: Import Flow with Category Confirmation

### 2.1 Updated Import Flow

1. User clicks Import → version choice dropdown (current only / all history) — unchanged.
2. Category assignment modal opens **before** the import is committed:
   - If a match exists in `law_mappings`, the category is pre-filled.
   - Modal buttons per source spec Section 4:
     - **"Confirmă și importă"** → imports the law with `category_confidence = 'manual'`, creates `law_mappings` entry if new.
     - **"Importă fără categorie"** → imports the law with `category_id = NULL, category_confidence = 'unclassified'`.
     - **"Anulează"** → cancels the import entirely. No law is saved.
3. Import only completes when user confirms or skips. Cancel aborts everything.

**Suggested-law imports**: When importing via the "+ Importă" button on per-category suggestions (Section 1.3), the category is pre-filled in the confirmation modal. The modal still appears — the user must confirm or change the category. This upholds hard rule #2: "always show the confirmation dialog."

### 2.2 law_mappings Growth

After manual categorization (Step 5 above), insert into `law_mappings` if not already present:
```sql
INSERT INTO law_mappings (title, law_number, category_id, source)
VALUES ($title, $law_number, $category_id, 'user')
```
Check before inserting — never duplicate (match by (`law_number` or `title ILIKE`) AND `category_id`). The same law may have entries for different categories.

---

## Phase 3: Law Detail Breadcrumb + Settings Page

### 3.1 Law Detail Page

Category breadcrumb above the law title:
```
● Drept fiscal și financiar › Impozite și taxe
```
Color dot from `category_groups.color_hex`. If unclassified, show amber "Necategorizat" badge with clickable "Assign" link opening the category modal.

### 3.2 Settings / Categories Page

Route: `/settings/categories`.

- Table of all categories: group name, subcategory name, description, law count.
- "Reassign" action per law — opens category modal.
- "Add subcategory" — form to add new subcategory to an existing group (name_ro, name_en, description, group).
- Cannot create new top-level groups from UI.
- Categories with 0 laws flagged as "safe to hide" with a toggle to show/hide them from the sidebar.

---

## Hard Rules (from source spec Section 10)

- Never auto-import a law. User must trigger import explicitly.
- Never silently assign a category. Always show the confirmation modal.
- No keyword matching. Only `law_mappings` lookup for pre-fill.
- Always insert into `law_mappings` after manual categorization (unless already there).
- Never duplicate `law_mappings` rows.
- Never mix suggested laws with imported laws in the main list.
- `law_mappings` is the runtime source of truth. Source spec Section 3 is only the initial seed.
- The taxonomy in the seed data is the only allowed set of categories.
- `category_confidence` must always be set on save. Never NULL.
