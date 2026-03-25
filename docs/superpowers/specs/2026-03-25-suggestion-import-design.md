# Suggestion Import Flow

## Problem

The "+ Importa" buttons on law suggestions in the Legal Library do nothing — the button in `category-group-section.tsx` has no onClick handler.

## Solution

Auto-search legislatie.just.ro when clicking Import on a suggestion, let user pick version type, import, and auto-assign category.

## Backend

### New endpoint: `POST /api/laws/import-suggestion`

**Request:** `{ mapping_id: int, import_history: bool }`

**Flow:**
1. Look up `LawMapping` by ID to get `document_type`, `law_number`, `law_year`
2. Validate: if `law_number` is None, return 400 "This suggestion cannot be auto-imported (no law number)"
3. Check if law already imported (match by `law_number` + `document_type`) — return 409 if so
4. Normalize `document_type` to lowercase before passing to `advanced_search` (LawMapping stores uppercase like "LEGE", search expects lowercase "lege")
5. Convert `law_year` (int | None) to str for `advanced_search`
6. Call `advanced_search(doc_type=document_type.lower(), number=law_number, year=str(law_year))` on legislatie.just.ro
7. Pick best match: exact (doc_type + number + year), then fallback to first result
8. Import via existing `leropa_service.import_law(ver_id, import_history)` — reuse the same duplicate-detection and error-handling logic from the existing import endpoint
9. Auto-assign the suggestion's `category_id` to the imported law in the same endpoint (update `law.category_id` directly, no separate API call)
10. Return `{ law_id: int, title: str }`

**Note on suggestion cleanup:** LawMappings are not deleted after import. The library page's `get_library_data()` already filters out imported laws from suggestions by matching `law_number`. After import + refresh, the suggestion disappears naturally.

**Timeouts:** Use same timeout pattern as existing import — history imports can take minutes.

**Error cases:**
- `400` if mapping has no `law_number`
- `404` if mapping not found
- `404` if no results from legislatie.just.ro search
- `409` if law already imported
- Standard import errors propagated

## Frontend

### `CategoryGroupSection` changes

- Add `onImportSuggestion: (suggestionId: number, importHistory: boolean) => Promise<void>` prop
- Local state per suggestion: `idle | picking | importing | error`
- Button click -> show version picker dropdown ("Current version only" / "All historical versions")
- User picks -> call parent handler -> loading spinner on button
- For history imports, show "This may take a few minutes..." indicator
- Success -> parent refreshes library (suggestion disappears since law is now imported)
- Error -> inline error message below suggestion

### `library-page.tsx` changes

- Define `handleImportSuggestion(mappingId, importHistory)` that calls `POST /api/laws/import-suggestion`
- Use 10-minute timeout for history imports, 2-minute for current-only (same as CombinedSearch)
- On success, call `fetchData()` to refresh
- Pass handler to `CategoryGroupSection` via prop

## Files to modify

1. `backend/app/routers/laws.py` — new endpoint
2. `frontend/src/app/laws/components/category-group-section.tsx` — wire button + version picker
3. `frontend/src/app/laws/library-page.tsx` — handler + prop passing
