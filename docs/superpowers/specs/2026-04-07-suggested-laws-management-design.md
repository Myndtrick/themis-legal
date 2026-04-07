# Suggested Laws Management — Design

**Date:** 2026-04-07
**Status:** Draft

## Problem

The "Sugestii pentru această categorie" (suggested laws) lists in the legal library are powered by ~150 hardcoded rows in `backend/app/services/category_service.py::seed_category_taxonomy`, written into the `law_mappings` table on first boot. There is no UI to edit them. Two consequences:

1. **Adding or removing a suggestion requires a code change**, a redeploy, and a destructive seed re-run on existing databases (which today does not re-run anyway, so edits don't propagate).
2. **The Romanian import flow guesses.** When a user clicks "+ Importa" on a suggestion, `routers/laws.py::import_suggestion` runs `advanced_search(doc_type, number, year)` against legislatie.just.ro and picks `results[0]`. This fails when the search returns zero results (republished documents, search-code mismatches) or, worse, picks the wrong document silently. EU imports are pinned by CELEX and don't have this problem.

We need a settings UI that lets users curate the suggestion list (add, edit, delete) and lets them pin each entry to an exact source document, eliminating the guess.

## Goals

- A new **Settings → Suggestions** tab with a sortable, filterable table of every `LawMapping` row
- Add / edit / delete entries via a modal
- Pin RO entries to a specific `legislatie.just.ro` document by pasting a URL — backend extracts `ver_id`
- Pin EU entries to a specific EUR-Lex document by pasting a URL — backend extracts `CELEX`
- Source tracking: distinguish `system` (seed-loaded) from `user` (created or edited via UI); future seed updates only touch `system` rows
- Import flow uses the pinned identifier when present, falls back to today's search behavior when absent

## Non-goals

- No auto-import on save. Adding to the suggestion list and importing are two separate actions.
- No bulk-edit UI. Add/edit/delete one at a time.
- No reordering. The table is sorted by group/category/title.
- No category management — that lives in the existing Categories tab.
- No multi-version pinning. One pinned identifier per mapping.

## Schema changes

`law_mappings` table — add two columns:

| Column | Type | Notes |
|---|---|---|
| `source_url` | TEXT NULL | The full URL the user pasted, kept for display / "open in source" |
| `source_ver_id` | VARCHAR(50) NULL | Extracted legislatie.just `ver_id`. EU rows leave this NULL and use the existing `celex_number` column. |

The existing `source` column (already present, default `"user"`) gets a vocabulary change:

| Old value | New value | Meaning |
|---|---|---|
| `seed` | `system` | Created by `seed_category_taxonomy`. Future seed runs may insert/refresh. |
| `user` | `user` | Created or edited via the settings UI. Seed runs never touch these. |

**Migration (one-time, on startup):** `UPDATE law_mappings SET source='system' WHERE source='seed'`. The seed loader is updated to write `source='system'` going forward and to **skip rows that already exist** (matched by `category_id + law_number + law_year + document_type` for RO, or `category_id + celex_number` for EU), so re-running it never clobbers user edits.

## URL extraction

Two pure functions in a new module `backend/app/services/source_url.py`:

```python
def extract_ver_id(url: str) -> str | None:
    """Extract a legislatie.just.ro ver_id from a DetaliiDocument(Afis) URL.
    Regex: legislatie\.just\.ro/Public/DetaliiDocument(?:Afis)?/(\d+)
    """

def extract_celex(url: str) -> str | None:
    """Extract a CELEX number from an EUR-Lex URL.
    Two paths:
      1. legal-content URLs:  [?&]uri=CELEX[:%3A]+([0-9A-Z]+)
      2. ELI URLs:            /eli/(reg|dir|dec)/(\d+)/(\d+)/oj
                              → reconstruct as 3{year}{R|L|D}{number:04d}
    """
```

These are deterministic, regex-only, no network calls. Mapped from URL host:

| Host | Extractor | Stored in |
|---|---|---|
| `legislatie.just.ro` | `extract_ver_id` | `source_ver_id` |
| `eur-lex.europa.eu` | `extract_celex` | `celex_number` |

Anything else returns "URL not recognized" and the user can save anyway (the row just stays unpinned).

## API endpoints

All under `/api/settings/law-mappings`. Authentication: same admin guard as other settings endpoints.

### `GET /api/settings/law-mappings`
List every mapping. Query params for filtering: `group_slug`, `category_id`, `source` (`system|user|all`), `pinned` (`true|false|all`), `q` (full-text title match). Returns:
```json
[
  {
    "id": 1,
    "title": "Legea 287/2009 — Codul Civil",
    "law_number": "287",
    "law_year": 2009,
    "document_type": "law",
    "celex_number": null,
    "source_url": "https://legislatie.just.ro/Public/DetaliiDocument/109884",
    "source_ver_id": "109884",
    "category_id": 12,
    "category_name": "general",
    "group_slug": "civil",
    "group_name": "Civil",
    "source": "system",
    "is_imported": true
  },
  ...
]
```

### `POST /api/settings/law-mappings`
Create a new mapping. Body fields: `category_id`, `title`, `law_number?`, `law_year?`, `document_type?`, `source_url?`, `source_ver_id?`, `celex_number?`. Always inserted with `source='user'`. Returns the created row.

### `PATCH /api/settings/law-mappings/{id}`
Update any field. **Side effect:** if the row's current `source` is `system`, it flips to `user` automatically (the user has forked it and their edits are now protected from future seed runs). Returns the updated row.

### `DELETE /api/settings/law-mappings/{id}`
Hard delete. Allowed for both `system` and `user` rows. (System rows that were deleted will not be re-created by the seed loader thanks to skip-if-exists — but see "Reset" below for an explicit re-add path.)

### `POST /api/settings/law-mappings/probe-url`
Body: `{ "url": "..." }`. Dispatches by hostname, runs the appropriate extractor, optionally fetches the document title from the source for confirmation. Returns:
```json
{
  "kind": "ro" | "eu" | "unknown",
  "identifier": "109884" | "32016R0679" | null,
  "title": "Legea 287/2009 — Codul Civil" | null,
  "error": null | "URL host not recognized" | "Could not extract identifier"
}
```
Title fetch is best-effort: failures return `title: null` with no error. The user can save without a title preview.

## Import flow change

In `backend/app/routers/laws.py::import_suggestion` and `import_suggestion_stream`, after looking up the mapping:

```python
if mapping.source_ver_id:
    # Pinned — skip the search entirely
    ver_id = mapping.source_ver_id
else:
    # Fall back to today's behavior
    results = advanced_search(doc_type=..., number=..., year=...)
    if not results:
        raise NoResultsError(...)
    ver_id = results[0].ver_id

# Then existing duplicate check + do_import as today
```

EU import (`/eu/import`) is unchanged — it already uses `celex_number` directly, which is exactly the pinned-identifier pattern.

## Frontend

### New tab in `frontend/src/app/settings/`

Add `"suggestions"` to `TabId` in `settings-tabs.tsx`. Wire it up in `settings/page.tsx` to render a new `<SuggestionsTable />` component.

### `frontend/src/app/settings/suggestions/suggestions-table.tsx`

Top-level component for the tab. Responsibilities:
- Fetch list via `GET /api/settings/law-mappings`
- Render filter controls (group, category, source, pinned, search)
- Render the table
- Open the add/edit modal

Table columns: source badge, group dot+name, document type, number, year, title (truncated), pinned status (`ver 109884` / `CELEX 32016R0679` / `⚠ none`), actions menu (`⋯`).

Source badge: small pill — `system` (gray) or `user` (blue).

### `frontend/src/app/settings/suggestions/suggestion-form-modal.tsx`

Add/edit modal. Single component for both modes (create vs edit). Fields:
- Group (select) — drives which categories appear and which URL host is expected
- Category (select)
- Document type (select — same options as the legal library search bar; see `DEFAULT_ACT_TYPES` in `search-import-form.tsx:36`)
- Number (text)
- Year (number)
- Title (text)
- Source URL (text) — paste box

When the user pastes a URL and the input loses focus (or after a short debounce), call `POST /probe-url`. Render one of:
- ✓ Detected `ver_id 109884` — "Legea 287/2009..."
- ✓ Detected CELEX `32016R0679` — "Regulation (EU) 2016/679..."
- ⚠ URL not recognized (still allows save)
- ⚠ Could not extract identifier (still allows save)

Save button is always enabled when required fields are filled. Pinning is optional.

## Edit semantics — system vs user

| Action | system row | user row |
|---|---|---|
| View in table | ✓ | ✓ |
| Edit | flips to `user` on save | stays `user` |
| Delete | allowed | allowed |
| Future seed re-run | may insert/refresh (but skip-if-exists protects rows still matching) | never touched |

The "flip on edit" rule is the user's mental model: *if I touched it, it's mine.* This protects edits from being overwritten by future seed updates while still letting the seed bring in new defaults for installs that haven't customized them.

## Failure modes and edge cases

- **Pasted URL points to a different document than the form fields describe.** We don't validate this — the form fields and the pinned URL are independent. The form fields drive search/display; the pinned ver_id drives import. If they disagree, the import will succeed but the resulting law's title may not match the mapping's title. Acceptable: titles are display-only metadata; the imported law is what was pinned.
- **Pinned ver_id no longer exists upstream.** The import will fail with `do_import` raising. The user sees the error in the existing import error UI and can update the URL.
- **Probe endpoint can't fetch title.** Non-fatal. The user sees the identifier but no title preview.
- **User deletes a system row, then re-runs the seed.** The seed's skip-if-exists check is on `(category_id, law_number, law_year, document_type)` — so a deleted row *would* be re-inserted as `system` on the next seed run. This is intentional: deleting a default and not wanting it back is rare; if needed, the user can edit-then-delete (the edit creates a `user` row; deleting that row leaves no matching `(cat, num, year, type)` tuple to skip, so the system row reappears on next seed). If this becomes a problem we can add a `tombstones` table later. **Out of scope for v1.**
- **Two mappings with the same `(category_id, law_number, law_year, document_type)`.** Allowed today (no unique constraint). The skip-if-exists logic uses `EXISTS` rather than upsert to avoid imposing a constraint we'd then have to migrate. The dedup logic in `category_service.py::get_unimported_suggestions` already handles this for the library view.

## Testing

- Unit tests for `extract_ver_id` and `extract_celex` covering: legal-content URL, URL-encoded colon, extra query params, PDF variant, ELI reg/dir/dec reconstruction, malformed input, wrong host
- API tests for each CRUD endpoint
- API test for the probe endpoint with each URL shape and the "host not recognized" path
- API test for `PATCH` on a `system` row → confirms `source` flips to `user`
- Integration test: create a user mapping with a pinned `source_ver_id`, call `import_suggestion`, confirm `advanced_search` is **not** called and the pinned ver_id is passed to `do_import`
- Integration test: create a user mapping with no pin, call `import_suggestion`, confirm fallback search runs
- Seed loader test: run seed twice on a fresh DB, confirm no duplicates and that a manually edited row's edits survive the second run
- Frontend: render the table with mixed system/user rows, open add modal, paste a legislatie.just URL, confirm probe is called and identifier is displayed; same for an EUR-Lex URL

## Files touched

**Backend**
- `backend/app/models/category.py` — add `source_url`, `source_ver_id` columns
- `backend/migrations/` (or wherever schema migrations live) — add columns + rename `seed`→`system`
- `backend/app/services/source_url.py` — **new**, the two extractors
- `backend/app/services/category_service.py::seed_category_taxonomy` — write `source='system'`, skip-if-exists
- `backend/app/routers/settings_law_mappings.py` — **new**, CRUD + probe endpoints
- `backend/app/routers/laws.py::import_suggestion` and `import_suggestion_stream` — branch on `source_ver_id`
- `backend/app/main.py` — register the new router
- `backend/tests/` — new test files for the above

**Frontend**
- `frontend/src/lib/api.ts` — add types and fetch helpers for the new endpoints
- `frontend/src/app/settings/settings-tabs.tsx` — add `"suggestions"` tab id
- `frontend/src/app/settings/page.tsx` — render the new tab
- `frontend/src/app/settings/suggestions/suggestions-table.tsx` — **new**
- `frontend/src/app/settings/suggestions/suggestion-form-modal.tsx` — **new**

## Open questions

None at design time — all questions raised during brainstorming have been resolved:
- EU pinning UX matches RO (URL paste + extraction)
- Source vocabulary: `system` / `user` with edit-flips-to-user
- No auto-import on save
