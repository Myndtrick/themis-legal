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
2. Call `advanced_search(doc_type=document_type, number=law_number, year=law_year)` on legislatie.just.ro
3. Pick best match: exact (doc_type + number + year), then fallback to first result
4. Import via existing `leropa_service.import_law(ver_id, import_history)`
5. Auto-assign the suggestion's `category_id` to the imported law
6. Return `{ law_id: int, title: str }`

**Error cases:**
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
- Success -> parent refreshes library (suggestion disappears since law is now imported)
- Error -> inline error message below suggestion

### `library-page.tsx` changes

- Define `handleImportSuggestion(mappingId, importHistory)` that calls `POST /api/laws/import-suggestion`
- On success, call `fetchData()` to refresh
- Pass handler to `CategoryGroupSection` via prop

## Files to modify

1. `backend/app/routers/laws.py` — new endpoint
2. `frontend/src/app/laws/components/category-group-section.tsx` — wire button + version picker
3. `frontend/src/app/laws/library-page.tsx` — handler + prop passing
