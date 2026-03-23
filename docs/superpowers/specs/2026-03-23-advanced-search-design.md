# Advanced Search — Law Discovery & Import

## Overview

Enhance the Legal Library's import flow with structured filters and keyword search against legislatie.just.ro. Replaces the current single-input import form with an advanced search UI integrated into the `/laws` page.

## Goals

- Allow users to discover laws using structured filters (act type, number, year, emitent, date range, status)
- Allow keyword search across law titles and content on the source
- Combine filters and keywords in a single search
- Detect already-imported laws in search results
- Track the legal status of acts (in_force, repealed, etc.) separately from version history
- Auto-detect status on import with manual admin override

## Non-Goals

- Internal full-text search of already-imported laws (separate feature)
- Auto-detection of partially_repealed or superseded status (manual-only for now)
- Pagination of search results (hard cap at 20 results from legislatie.just.ro per query)

---

## Section 1: Data Model Changes

### New fields on `Law` model

```python
class LawStatus(str, Enum):
    in_force = "in_force"
    repealed = "repealed"
    partially_repealed = "partially_repealed"
    superseded = "superseded"
    unknown = "unknown"

# On Law:
status = Column(String, default="unknown")
status_override = Column(Boolean, default=False)  # True = manually set by admin
```

- `status` — the current legal status of the act itself, independent of version history
- `status_override` — when True, auto-detection logic will not overwrite the status on future update checks

### Auto-detection logic (runs during import)

- Check the state of the newest version: `"D"` (deprecated) → `repealed`, `"A"` (actual) → `in_force`
- If no version has state info → `unknown`
- `partially_repealed` and `superseded` are manual-only for now
- `superseded` is for laws replaced by a newer law covering the same domain (e.g., old Commercial Code superseded by the Civil Code). Distinct from `repealed`, which means explicitly abrogated.

### Migration

Add both columns to the `laws` table. Backfill existing laws by checking their current version's state.

---

## Section 2: Backend API — Advanced Search Endpoint

### New endpoint: `GET /api/laws/advanced-search`

Separate from the existing `/api/laws/search` (which stays for backward compatibility).

### Query parameters

| Parameter | Type | Maps to legislatie.just.ro field |
|-----------|------|----------------------------------|
| `keyword` | string | `TitleText` + `ContentText_First` (two queries merged) |
| `doc_type` | string | `DocumentType` (using existing `DOC_TYPE_MAP`) |
| `number` | string | `DocumentNumber` |
| `year` | string | Combined with number as `{number}-{year}` |
| `emitent` | string | `EmitentAct` |
| `date_from` | string (YYYY-MM-DD) | `ActInForceOnDateTextFrom` |
| `date_to` | string (YYYY-MM-DD) | `DataSemnariiTextTo` (signing date upper bound, sent as form field) |
| `include_repealed` | string: `only_in_force` / `all` / `only_repealed` | Controls `ActInForceOnDateTextFrom` |

### Search logic

1. Build form data directly from structured parameters — no query parsing needed
2. If `keyword` is provided with no other filters → search title first, then content as fallback
3. If `keyword` + filters → single POST combining all fields
4. For `only_in_force`: set `ActInForceOnDateTextFrom` to today's date
5. For `all`: leave the date field empty
6. For `only_repealed`: search without date filter, then post-filter by re-searching WITH today's date and removing matches. **Limitation:** this is best-effort and limited to the top 20 results from each query. If a law falls outside the top 20 in either query, it may be misclassified. This is acceptable for a discovery tool — the user can refine filters to narrow results.
7. Each result is cross-referenced against the local DB to flag "already imported":
   - Primary match: check `LawVersion.ver_id` against the result's `ver_id`, join to `Law` to get `local_law_id`
   - Secondary match: derive `source_url` from `ver_id` and check against `Law.source_url`
   - If either matches, set `already_imported = true` and populate `local_law_id`

### Response shape

```json
{
  "results": [
    {
      "ver_id": "798",
      "title": "LEGE nr. 31 din 16 noiembrie 1990 privind societățile comerciale",
      "doc_type": "LEGE",
      "number": "31",
      "date": "16/11/1990",
      "date_iso": "1990-11-16",
      "issuer": "Parlamentul",
      "description": "...",
      "already_imported": true,
      "local_law_id": 5
    }
  ],
  "total": 12
}
```

- `date` — display string as parsed from the source
- `date_iso` — ISO 8601 parsed date (nullable, used for `date_to` filtering and frontend sorting)
- `total` — `len(results)` after all filtering; no server-side pagination

---

## Section 3: Backend — Emitent Autocomplete Endpoint

### New endpoint: `GET /api/laws/emitents`

### Query parameter: `q` (string, min 2 chars)

### Logic

1. Maintain a static list of common emitents as pinned suggestions:
   - Parlamentul României
   - Guvernul României
   - Ministerul Finanțelor
   - Banca Națională a României (BNR)
   - Autoritatea de Supraveghere Financiară (ASF)
   - ANAF
   - Ministerul Justiției
   - Oficiul Național de Prevenire și Combatere a Spălării Banilor (ONPCSB)
   - Comisia Europeană / Parlamentul European
2. When `q` is provided, filter the pinned list (case-insensitive, partial match)
3. Additionally, query legislatie.just.ro's search form and collect unique issuers from results
4. Merge: pinned matches first, then source-discovered issuers, deduplicated

### Fallback

If scraping issuers from the source proves unreliable, fall back to the static list only.

### Response

```json
{
  "emitents": [
    "Parlamentul României",
    "Guvernul României",
    "Banca Națională a României (BNR)"
  ]
}
```

---

## Section 4: Frontend — Search UI Component

### Replace `import-form.tsx` with `search-import-form.tsx`

Integrated into the `/laws` page. No new routes.

### Component structure

```
SearchImportForm
├── KeywordBar          — always visible: text input + Search button
├── AdvancedFilters     — collapsible panel, toggled by "Advanced Filters" link
│   ├── ActTypeDropdown     — static options (Lege, OUG, HG, Ordin, Regulament, Directivă EU, Decizie)
│   ├── LawNumberInput      — numbers only
│   ├── YearInput            — 4 digits only
│   ├── EmitentAutocomplete  — calls /api/laws/emitents?q=...
│   ├── DateFromPicker       — date input
│   ├── DateToPicker         — date input
│   ├── StatusFilter         — "In force" (default) / "All" / "Only repealed"
│   └── ClearFiltersButton
├── ResultsTable        — shown after search
│   ├── ResultsHeader   — count + "Import history" checkbox
│   └── ResultRow[]     — doc type badge, title, number, date, issuer, Import/View button
└── ImportFeedback      — success/error messages per row
```

### Behavior

- Pressing Enter in keyword bar or clicking Search triggers the search
- Advanced filters are collapsed by default, state preserved during the session
- Search button sends all active filters (keyword + any expanded filters) in one request
- Results replace any previous results
- Each row has an Import button (or View if already imported)
- Import button shows a spinner on that row while importing, then switches to View on success
- "Import all historical versions" checkbox applies to all imports in that session
- Clear Filters resets all fields including keyword, but does NOT clear results
- EmitentAutocomplete uses 500ms debounce (matching existing import form pattern) with loading indicator
- The old `import-form.tsx` file is deleted and its import in `page.tsx` is replaced with `search-import-form.tsx`

---

## Section 5: Status Management — Admin Override

### Law detail page (`/laws/{id}`)

- Display current status as a color-coded badge:
  - Green: in_force
  - Red: repealed
  - Yellow: partially_repealed
  - Gray: unknown
- "Edit" button opens inline dropdown to change status
- When manually changed, sets `status_override = True`
- "Manually set" label appears next to overridden statuses, with "Reset to auto" option

### New endpoint: `PATCH /api/laws/{law_id}/status`

```json
{
  "status": "repealed",
  "override": true
}
```

Setting `"override": false` resets to auto-detection mode (the "Reset to auto" UI action). This immediately re-runs auto-detection from the newest version's state and updates the status in the same request, so the user sees the result right away.

### Update checker integration

The existing daily update checker (`update_checker.py`) gets a small addition: after importing new versions, if `status_override` is False, re-evaluate the law's status from the newest version's state.

---

## Technical Notes

### legislatie.just.ro form field mapping

The source's search form supports these fields directly:
- `TitleText` — title keyword search
- `ContentText_First` — content keyword search
- `DocumentType` — act type (numeric codes in `DOC_TYPE_MAP`)
- `DocumentNumber` — law number (format: `{number}-{year}`)
- `EmitentAct` — issuer name
- `ActInForceOnDateTextFrom` — acts in force on/after a date
- `DataSemnariiTextFrom/To` — signing date range
- `DataPublicariiTextFrom/To` — publication date range

### Status auto-detection reliability

| Status | Method | Reliability |
|--------|--------|-------------|
| in_force | Newest version state = "A" | High |
| repealed | Newest version state = "D" | Medium-High |
| partially_repealed | Manual only | N/A |
| superseded | Manual only | N/A |

### Code changes required

- **`_do_search` in `search_service.py`** — must be extended with new parameters: `emitent: str = ""`, `date_from: str = ""`, `date_to: str = ""`. These map to the `EmitentAct`, `ActInForceOnDateTextFrom`, and `DataSemnariiTextTo` form fields which are currently hardcoded as empty strings.
- **`_parse_search_results`** — add `date_iso` field by parsing the `DD/MM/YYYY` date string into ISO format.
- **`import_law()` in `leropa_service.py`** — add status auto-detection at the end of the import flow.
- **`/api/laws/search` endpoint** — unchanged, stays for backward compatibility.
- **Current law list on `/laws`** — stays below the new search form.

### Act type codes for dropdown

Complete mapping from dropdown labels to legislatie.just.ro `DocumentType` codes:

| Dropdown label | Code | Notes |
|---------------|------|-------|
| Lege | 1 | |
| OUG | 18 | |
| HG | 2 | |
| Ordin | 5 | |
| Decizie | 17 | |
| Regulament | — | No known code; search by title keyword "regulament" instead |
| Directivă EU | — | No known code; search by title keyword "directiva" instead |

For Regulament and Directivă EU: when selected, set `DocumentType` to empty and prepend the type name to the `TitleText` field as a keyword.
