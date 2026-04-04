# Favorites Feature — Design Spec

## Overview

Add a favorites system to the Legal Library that allows users to bookmark laws for quick access. Favorites are persisted in the backend database (per-user) and surfaced across the UI in four ways.

---

## Feature 1 — Heart Button on Each Law Card

**Component:** `law-card.tsx`

Every law row displays a heart icon button between the version count and the Delete button.

- **Not favorited:** Outline heart (`Heart` icon from lucide-react), gray. Click to add.
- **Favorited:** Filled pink heart (`text-pink-500`). Click to remove.
- Always visible (not hover-only).
- Clicking calls `POST /api/laws/{id}/favorite` or `DELETE /api/laws/{id}/favorite`.
- Optimistic UI: toggle immediately, revert on error.

**Layout (right side of card):**
```
[version count] [new badge?] [heart button] [delete button]
```

---

## Feature 2 — Favorites Section in Sidebar

**Component:** `sidebar.tsx`

Below the existing STATUS section, add a FAVORITES section. It appears only when the current user has at least one favorited law.

- Header: `FAVORITES` (same styling as CATEGORIES / STATUS headers).
- Lists category groups that contain favorited laws, with the count of favorites per group.
- Clicking a category group entry sets the view to favorites filtered by that group.
- A "Show all favorites" link at the bottom navigates to the full favorites view.
- Section is hidden entirely when there are zero favorites.

**Example:**
```
FAVORITES
Civil law              1
Commercial law         2
EU law                 1
Show all favorites
```

---

## Feature 3 — Favorites Page (View)

**Component:** `library-page.tsx` (new view mode within existing page)

When the user clicks "Show all favorites" or a specific favorites category in the sidebar, the main content area switches to a favorites view.

- **No new route.** Uses existing page with a new state: `selectedView: "all" | "favorites"`.
- Shows only favorited laws, grouped by category group (reuses `CategoryGroupSection`).
- Each law row shows a filled pink heart. Clicking it removes the law from favorites and it disappears from the view.
- If a specific category group was clicked in the sidebar favorites section, only that group is shown (via `favoriteCategoryFilter` state).
- Subtitle shows count: "Showing N favorited laws".
- Empty state: "No favorited laws yet. Click the heart icon on any law to add it here."

---

## Feature 4 — Pinned Favorites in Category View

**Component:** `category-group-section.tsx`

When viewing a specific category in the main library, favorited laws are sorted to the top of the list within each category group section.

- Favorited laws appear first, followed by non-favorited laws.
- The filled pink heart icon is the visual distinguisher (no extra label).
- Sort is stable: within favorited and non-favorited groups, original order is preserved.

---

## Backend Design

### Database

**New table: `law_favorites`**

| Column     | Type        | Constraints                          |
|------------|-------------|--------------------------------------|
| id         | INTEGER     | PRIMARY KEY AUTOINCREMENT            |
| user_id    | INTEGER     | FK → users.id, NOT NULL              |
| law_id     | INTEGER     | FK → laws.id, NOT NULL               |
| created_at | DATETIME    | DEFAULT CURRENT_TIMESTAMP            |

- `UNIQUE(user_id, law_id)` — prevents duplicate favorites.
- `ON DELETE CASCADE` on both FKs — if a law or user is deleted, favorites are cleaned up.
- **No existing tables are modified.** This is a pure additive migration.

**Migration approach:** Add to `main.py` lifespan using `CREATE TABLE IF NOT EXISTS`, matching the existing migration pattern. No Alembic.

### Model

**New file:** `backend/app/models/favorite.py`

```python
class LawFavorite(Base):
    __tablename__ = "law_favorites"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    law_id = Column(Integer, ForeignKey("laws.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("user_id", "law_id"),)
```

### API Endpoints

Added to existing `categories.py` router (since it already handles `/api/laws/library`):

| Method | Path                         | Description                              |
|--------|------------------------------|------------------------------------------|
| GET    | `/api/laws/favorites`        | Returns `{ law_ids: number[] }` for current user |
| POST   | `/api/laws/{law_id}/favorite`  | Add law to favorites. Returns `{ ok: true }`. Idempotent. |
| DELETE | `/api/laws/{law_id}/favorite`  | Remove law from favorites. Returns `{ ok: true }`. Idempotent. |

All endpoints require authentication (`get_current_user` dependency).

### Library Endpoint Enhancement

`get_library_data()` in `category_service.py` will accept the current user and include `favorite_law_ids: number[]` in the response. This avoids a separate API call on page load.

**Updated `LibraryData` response:**
```json
{
  "groups": [...],
  "laws": [...],
  "stats": {...},
  "suggested_laws": [...],
  "favorite_law_ids": [1, 5, 12]
}
```

---

## Frontend Design

### State Management

In `library-page.tsx`:
- New state: `favorites: Set<number>` — initialized from `data.favorite_law_ids`.
- New state: `selectedView: "all" | "favorites"` — controls which view is shown.
- New state: `favoriteCategoryFilter: string | null` — when in favorites view, filters to a specific group.
- `toggleFavorite(lawId)` function: optimistically updates `favorites` set, calls API, reverts on error.

### Props Changes

**`LawCard`** gets new props:
- `isFavorite: boolean`
- `onToggleFavorite: (lawId: number) => void`

**`Sidebar`** gets new props:
- `favoriteCounts: Map<string, number>` — group slug → count of favorites
- `selectedView: "all" | "favorites"`
- `favoriteCategoryFilter: string | null`
- `onSelectFavorites: (groupSlug: string | null) => void`

**`CategoryGroupSection`** gets new props:
- `favoriteIds: Set<number>`
- `onToggleFavorite: (lawId: number) => void`

### API Client

Add to `api.ts`:
```typescript
favorites: {
  list: () => apiFetch<{ law_ids: number[] }>("/api/laws/favorites"),
  add: (lawId: number) => apiFetch<{ ok: boolean }>(`/api/laws/${lawId}/favorite`, { method: "POST" }),
  remove: (lawId: number) => apiFetch<{ ok: boolean }>(`/api/laws/${lawId}/favorite`, { method: "DELETE" }),
}
```

Update `LibraryData` interface to include `favorite_law_ids: number[]`.

### Filtering Logic (Favorites View)

When `selectedView === "favorites"`:
1. Filter `data.laws` to only those in `favorites` set.
2. If `favoriteCategoryFilter` is set, further filter by `category_group_slug`.
3. Group and render using existing `CategoryGroupSection` component.

### Sorting Logic (Pinned in Category View)

In `CategoryGroupSection`, when rendering laws:
- Partition into `[favoritedLaws, otherLaws]`.
- Render `[...favoritedLaws, ...otherLaws]`.
- Each `LawCard` receives `isFavorite` to show the correct heart state.

---

## Non-Goals

- No favorite ordering/reordering — favorites are unordered.
- No favorite folders or tags — just a flat list grouped by existing categories.
- No sharing favorites between users.
- No export/import of favorites.
