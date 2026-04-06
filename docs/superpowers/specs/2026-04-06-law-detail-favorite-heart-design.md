# Favorite heart button on law detail page

## Goal

Add a favorite-toggle heart button to each law's detail page (`/laws/[id]`), matching the heart button that already exists in the laws list view.

## Current state

- Favorites backend exists: `POST /api/laws/{id}/favorite`, `DELETE /api/laws/{id}/favorite`, model `LawFavorite` in `backend/app/models/favorite.py`.
- The laws list (`frontend/src/app/laws/components/law-card.tsx:126-142`) already renders the heart SVG with outline/filled variants and optimistic toggle.
- The library page (`frontend/src/app/laws/library-page.tsx`) holds a `Set<number>` of favorite ids fetched via the library endpoint and passes it down.
- The detail page (`frontend/src/app/laws/[id]/page.tsx`) fetches `LawDetail` via `api.laws.get(id)` and has no favorite UI.
- The `LawDetail` Pydantic/TypeScript type has no `is_favorite` field.

## Design

### Backend

In the `GET /api/laws/{id}` handler, add an `is_favorite: bool` field to the response schema. Populate it by checking whether a `LawFavorite` row exists for `(current_user.id, law_id)`. The current user is already available in that route (same pattern used by the library endpoint in `backend/app/services/category_service.py:638-654`).

### Frontend — types

Add `is_favorite: boolean` to the `LawDetail` interface in `frontend/src/lib/api.ts:156`.

### Frontend — detail page UI

In `frontend/src/app/laws/[id]/page.tsx`:

1. Add a local `isFavorite` state initialized from `law.is_favorite` once the law loads.
2. Add an `onToggleFavorite` handler that:
   - Optimistically flips local state.
   - Calls `api.laws.favoriteAdd` or `favoriteRemove`.
   - On failure, reverts local state and shows an alert (matching the list view's behavior).
3. Render the heart button inline next to the `<h1>` title (the `<h1>` at line 68). Use `flex items-center gap-3` on the title row so the heart sits to the right of the title text. Use `w-6 h-6` sized SVGs (larger than the list view's `w-4 h-4`).
4. Reuse the exact SVG paths from `law-card.tsx:132-140` (both filled and outline variants).

### What is NOT changing

- No new shared component is extracted. The SVG is duplicated inline — if a third site needs it later, that's the moment to extract.
- No changes to the list view, sidebar, or library-page favorites logic.
- No localStorage or client-side caching.
- No change to the favorite add/remove API surface.

## Files touched

- `backend/app/routers/laws.py` (or wherever `GET /api/laws/{id}` is defined) and its response schema — add `is_favorite`.
- `frontend/src/lib/api.ts` — add `is_favorite` to `LawDetail`.
- `frontend/src/app/laws/[id]/page.tsx` — add heart button, state, and toggle handler.

## Testing

Manual verification:

1. Open a law's detail page — heart renders outline if not favorited, filled pink if favorited.
2. Click heart — it flips, list view reflects the change on next visit.
3. Reload detail page — initial state matches backend.
