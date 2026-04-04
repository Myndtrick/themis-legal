# Favorites Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backend-persisted favorites system so users can bookmark laws and access them via heart buttons, a sidebar section, a favorites view, and pinned sorting.

**Architecture:** New `law_favorites` SQLite table with per-user FK. Three new API endpoints (list/add/remove). The existing `/api/laws/library` endpoint returns `favorite_law_ids` in its response. Frontend state in `library-page.tsx` with props threaded to `Sidebar`, `CategoryGroupSection`, and `LawCard`.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite (backend); Next.js, React, TypeScript (frontend). No new dependencies — heart icon rendered with inline SVG.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `backend/app/models/favorite.py` | `LawFavorite` SQLAlchemy model |
| Modify | `backend/app/main.py:11` | Register the new model import |
| Modify | `backend/app/routers/categories.py` | Add 3 favorite endpoints |
| Modify | `backend/app/services/category_service.py:540-644` | Accept `user_id`, return `favorite_law_ids` |
| Modify | `frontend/src/lib/api.ts:131-140,867,812-907` | Add `favorite_law_ids` to `LibraryData`, add `favorites` API methods |
| Modify | `frontend/src/app/laws/components/law-card.tsx:12-17,115-168` | Add heart button, new props |
| Modify | `frontend/src/app/laws/components/sidebar.tsx:6-14,70-202` | Add FAVORITES section, new props |
| Modify | `frontend/src/app/laws/components/category-group-section.tsx:25-37,166-169` | Accept `favoriteIds`, sort + pass to LawCard |
| Modify | `frontend/src/app/laws/library-page.tsx:16-25,122-142,566-732` | Add favorites state, view mode, wire everything |

---

### Task 1: Backend Model & Migration

**Files:**
- Create: `backend/app/models/favorite.py`
- Modify: `backend/app/main.py:11`

- [ ] **Step 1: Create the LawFavorite model**

Create `backend/app/models/favorite.py`:

```python
from __future__ import annotations

import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LawFavorite(Base):
    __tablename__ = "law_favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    law_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("laws.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

    __table_args__ = (UniqueConstraint("user_id", "law_id"),)
```

- [ ] **Step 2: Register the model in main.py**

In `backend/app/main.py`, add the import on line 11 alongside the other model imports:

Change:
```python
from app.models import assistant, pipeline, prompt, category, user  # noqa: F401 — register models
```
To:
```python
from app.models import assistant, pipeline, prompt, category, user, favorite  # noqa: F401 — register models
```

This ensures `Base.metadata.create_all()` on line 93 picks up the new table. The `CREATE TABLE IF NOT EXISTS` semantics of `create_all` mean existing tables are untouched.

- [ ] **Step 3: Verify the migration is safe**

Run the backend to confirm the table is created without affecting existing data:

```bash
cd backend && python -c "
from app.database import engine, Base
from app.models import favorite  # noqa
from sqlalchemy import inspect
Base.metadata.create_all(bind=engine)
inspector = inspect(engine)
cols = [c['name'] for c in inspector.get_columns('law_favorites')]
print('law_favorites columns:', cols)
# Verify laws table is untouched
law_cols = [c['name'] for c in inspector.get_columns('laws')]
print('laws columns (should be unchanged):', law_cols)
"
```

Expected: `law_favorites columns: ['id', 'user_id', 'law_id', 'created_at']` and the `laws` columns list unchanged.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/favorite.py backend/app/main.py
git commit -m "feat: add LawFavorite model and register for auto-migration"
```

---

### Task 2: Backend API Endpoints

**Files:**
- Modify: `backend/app/routers/categories.py`

- [ ] **Step 1: Add the three favorite endpoints**

Append the following to the end of `backend/app/routers/categories.py` (after the `search_local` function at line 38):

```python
@router.get("/favorites")
def get_favorites(
    db: Session = Depends(get_db),
    current_user: "User" = Depends(get_current_user),
):
    """Return list of favorited law IDs for the current user."""
    from app.models.favorite import LawFavorite
    rows = db.query(LawFavorite.law_id).filter(
        LawFavorite.user_id == current_user.id
    ).all()
    return {"law_ids": [r[0] for r in rows]}


@router.post("/{law_id}/favorite")
def add_favorite(
    law_id: int,
    db: Session = Depends(get_db),
    current_user: "User" = Depends(get_current_user),
):
    """Add a law to the user's favorites. Idempotent."""
    from app.models.favorite import LawFavorite
    from app.models.law import Law

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    existing = db.query(LawFavorite).filter(
        LawFavorite.user_id == current_user.id,
        LawFavorite.law_id == law_id,
    ).first()
    if not existing:
        db.add(LawFavorite(user_id=current_user.id, law_id=law_id))
        db.commit()
    return {"ok": True}


@router.delete("/{law_id}/favorite")
def remove_favorite(
    law_id: int,
    db: Session = Depends(get_db),
    current_user: "User" = Depends(get_current_user),
):
    """Remove a law from the user's favorites. Idempotent."""
    from app.models.favorite import LawFavorite

    deleted = db.query(LawFavorite).filter(
        LawFavorite.user_id == current_user.id,
        LawFavorite.law_id == law_id,
    ).delete()
    if deleted:
        db.commit()
    return {"ok": True}
```

Note: `get_current_user` is already imported on line 5. Add the `User` type import for the type hint:

At the top of the file, after the existing imports, add:

```python
from app.models.user import User
```

- [ ] **Step 2: Update the library endpoint to include favorites**

The `get_library` endpoint on line 11 needs to pass the current user so `get_library_data` can return `favorite_law_ids`. Change it from:

```python
@router.get("/library")
def get_library(db: Session = Depends(get_db)):
    """Return all data needed for the Legal Library page."""
    from app.services.category_service import get_library_data
    return get_library_data(db)
```

To:

```python
@router.get("/library")
def get_library(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all data needed for the Legal Library page."""
    from app.services.category_service import get_library_data
    return get_library_data(db, user_id=current_user.id)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/categories.py
git commit -m "feat: add favorite API endpoints (list/add/remove)"
```

---

### Task 3: Backend — Include Favorites in Library Data

**Files:**
- Modify: `backend/app/services/category_service.py:540,637-644`

- [ ] **Step 1: Update get_library_data to accept user_id and return favorite_law_ids**

In `backend/app/services/category_service.py`, change the function signature on line 540 from:

```python
def get_library_data(db: Session) -> dict:
```

To:

```python
def get_library_data(db: Session, user_id: int | None = None) -> dict:
```

Then, just before the `return` statement on line 637, add the favorites query:

```python
    # 5. Favorites for the current user
    favorite_law_ids = []
    if user_id is not None:
        from app.models.favorite import LawFavorite
        favorite_law_ids = [
            r[0] for r in db.query(LawFavorite.law_id)
            .filter(LawFavorite.user_id == user_id)
            .all()
        ]
```

And update the return dict on line 637 from:

```python
    return {
        "groups": groups_out, "laws": laws_out,
        "stats": {
            "total_laws": len(laws), "total_versions": total_versions,
            "last_imported": str(last_imported.date()) if last_imported else None,
        },
        "suggested_laws": suggested,
    }
```

To:

```python
    return {
        "groups": groups_out, "laws": laws_out,
        "stats": {
            "total_laws": len(laws), "total_versions": total_versions,
            "last_imported": str(last_imported.date()) if last_imported else None,
        },
        "suggested_laws": suggested,
        "favorite_law_ids": favorite_law_ids,
    }
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/category_service.py
git commit -m "feat: include favorite_law_ids in library data response"
```

---

### Task 4: Frontend API Client Updates

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add favorite_law_ids to LibraryData interface**

In `frontend/src/lib/api.ts`, update the `LibraryData` interface (line 131) from:

```typescript
export interface LibraryData {
  groups: CategoryGroupData[];
  laws: LibraryLaw[];
  stats: {
    total_laws: number;
    total_versions: number;
    last_imported: string | null;
  };
  suggested_laws: SuggestedLaw[];
}
```

To:

```typescript
export interface LibraryData {
  groups: CategoryGroupData[];
  laws: LibraryLaw[];
  stats: {
    total_laws: number;
    total_versions: number;
    last_imported: string | null;
  };
  suggested_laws: SuggestedLaw[];
  favorite_law_ids: number[];
}
```

- [ ] **Step 2: Add favorites API methods**

In the `api.laws` object (after the `euFilterOptions` method around line 906), add:

```typescript
    favoriteAdd: (lawId: number) =>
      apiFetch<{ ok: boolean }>(`/api/laws/${lawId}/favorite`, { method: "POST" }),
    favoriteRemove: (lawId: number) =>
      apiFetch<{ ok: boolean }>(`/api/laws/${lawId}/favorite`, { method: "DELETE" }),
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add favorites to API client and LibraryData interface"
```

---

### Task 5: Heart Button on LawCard

**Files:**
- Modify: `frontend/src/app/laws/components/law-card.tsx:12-17,115-168`

- [ ] **Step 1: Add new props to LawCardProps interface**

Change the interface (line 12) from:

```typescript
interface LawCardProps {
  law: LibraryLaw;
  showAssignButton?: boolean;
  onAssign?: (lawId: number) => void;
  onDelete?: () => void;
}
```

To:

```typescript
interface LawCardProps {
  law: LibraryLaw;
  showAssignButton?: boolean;
  onAssign?: (lawId: number) => void;
  onDelete?: () => void;
  isFavorite?: boolean;
  onToggleFavorite?: (lawId: number) => void;
}
```

- [ ] **Step 2: Destructure new props in component**

Update the component function signature (line 45) from:

```typescript
export default function LawCard({ law, showAssignButton, onAssign, onDelete }: LawCardProps) {
```

To:

```typescript
export default function LawCard({ law, showAssignButton, onAssign, onDelete, isFavorite, onToggleFavorite }: LawCardProps) {
```

- [ ] **Step 3: Add heart button in the actions area**

In the right-side actions `div` (line 115), add the heart button after the "new" badge and before the `showAssignButton` block. Insert this between the unimported_version_count badge (line 123) and the `showAssignButton` conditional (line 124):

```tsx
        {onToggleFavorite && (
          <button
            onClick={(e) => { e.preventDefault(); onToggleFavorite(law.id); }}
            className="p-1 rounded hover:bg-pink-50 transition-colors"
            title={isFavorite ? "Remove from favorites" : "Add to favorites"}
          >
            {isFavorite ? (
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4 text-pink-500">
                <path d="M11.645 20.91l-.007-.003-.022-.012a15.247 15.247 0 01-.383-.218 25.18 25.18 0 01-4.244-3.17C4.688 15.36 2.25 12.174 2.25 8.25 2.25 5.322 4.714 3 7.688 3A5.5 5.5 0 0112 5.052 5.5 5.5 0 0116.313 3c2.973 0 5.437 2.322 5.437 5.25 0 3.925-2.438 7.111-4.739 9.256a25.175 25.175 0 01-4.244 3.17 15.247 15.247 0 01-.383.219l-.022.012-.007.004-.003.001a.752.752 0 01-.704 0l-.003-.001z" />
              </svg>
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4 text-gray-400 hover:text-pink-400">
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z" />
              </svg>
            )}
          </button>
        )}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/laws/components/law-card.tsx
git commit -m "feat: add heart favorite button to LawCard component"
```

---

### Task 6: CategoryGroupSection — Sorting & Favorite Props

**Files:**
- Modify: `frontend/src/app/laws/components/category-group-section.tsx:25-37,166-169`

- [ ] **Step 1: Add favorite props to the interface**

Update the `CategoryGroupSectionProps` interface (line 25) from:

```typescript
interface CategoryGroupSectionProps {
  groupSlug: string;
  groupName: string;
  colorHex: string;
  laws: LibraryLaw[];
  suggestedLaws: SuggestedLaw[];
  pendingImports?: PendingImportEntry[];
  defaultExpanded?: boolean;
  onAssign?: (lawId: number) => void;
  onDelete?: () => void;
  onImportSuggestion?: (mappingId: number, importHistory: boolean) => void;
  onDismissPendingError?: (mappingId: number) => void;
}
```

To:

```typescript
interface CategoryGroupSectionProps {
  groupSlug: string;
  groupName: string;
  colorHex: string;
  laws: LibraryLaw[];
  suggestedLaws: SuggestedLaw[];
  pendingImports?: PendingImportEntry[];
  defaultExpanded?: boolean;
  onAssign?: (lawId: number) => void;
  onDelete?: () => void;
  onImportSuggestion?: (mappingId: number, importHistory: boolean) => void;
  onDismissPendingError?: (mappingId: number) => void;
  favoriteIds?: Set<number>;
  onToggleFavorite?: (lawId: number) => void;
}
```

- [ ] **Step 2: Destructure new props**

Update the destructured props (line 41) to include `favoriteIds` and `onToggleFavorite`:

From:
```typescript
}: CategoryGroupSectionProps) {
```

Add `favoriteIds = new Set<number>(), onToggleFavorite` to the destructuring, between `onDismissPendingError` and the closing brace.

The full destructuring becomes:
```typescript
export default function CategoryGroupSection({
  groupSlug,
  groupName,
  colorHex,
  laws,
  suggestedLaws,
  pendingImports = [],
  defaultExpanded = false,
  onAssign,
  onDelete,
  onImportSuggestion,
  onDismissPendingError,
  favoriteIds = new Set<number>(),
  onToggleFavorite,
}: CategoryGroupSectionProps) {
```

- [ ] **Step 3: Sort laws so favorites appear first**

After line 74 (`const totalCount = ...`), before `const visibleLaws`, add sorting:

```typescript
  // Sort: favorited laws first (stable sort preserves original order within groups)
  const sortedLaws = favoriteIds.size > 0
    ? [...laws].sort((a, b) => {
        const aFav = favoriteIds.has(a.id) ? 0 : 1;
        const bFav = favoriteIds.has(b.id) ? 0 : 1;
        return aFav - bFav;
      })
    : laws;
```

Then update `visibleLaws` and `hasMore` to use `sortedLaws`:

Change:
```typescript
  const visibleLaws = expanded ? laws : laws.slice(0, PREVIEW_COUNT);
  const hasMore = laws.length > PREVIEW_COUNT;
```

To:
```typescript
  const visibleLaws = expanded ? sortedLaws : sortedLaws.slice(0, PREVIEW_COUNT);
  const hasMore = sortedLaws.length > PREVIEW_COUNT;
```

- [ ] **Step 4: Pass favorite props to LawCard**

Update the LawCard rendering (line 167-169) from:

```tsx
        {visibleLaws.map((law) => (
          <LawCard key={law.id} law={law} onAssign={onAssign} onDelete={onDelete} />
        ))}
```

To:

```tsx
        {visibleLaws.map((law) => (
          <LawCard
            key={law.id}
            law={law}
            onAssign={onAssign}
            onDelete={onDelete}
            isFavorite={favoriteIds.has(law.id)}
            onToggleFavorite={onToggleFavorite}
          />
        ))}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/laws/components/category-group-section.tsx
git commit -m "feat: sort favorited laws to top and pass favorite props to LawCard"
```

---

### Task 7: Sidebar — Favorites Section

**Files:**
- Modify: `frontend/src/app/laws/components/sidebar.tsx:6-14,70-202`

- [ ] **Step 1: Add new props to SidebarProps**

Update the `SidebarProps` interface (line 6) from:

```typescript
interface SidebarProps {
  groups: CategoryGroupData[];
  laws: LibraryLaw[];
  selectedGroup: string | null;
  selectedCategory: string | null;
  selectedStatus: string | null;
  onSelectGroup: (slug: string | null) => void;
  onSelectCategory: (slug: string | null) => void;
  onSelectStatus: (status: string | null) => void;
}
```

To:

```typescript
interface SidebarProps {
  groups: CategoryGroupData[];
  laws: LibraryLaw[];
  selectedGroup: string | null;
  selectedCategory: string | null;
  selectedStatus: string | null;
  onSelectGroup: (slug: string | null) => void;
  onSelectCategory: (slug: string | null) => void;
  onSelectStatus: (status: string | null) => void;
  favoriteCounts: Map<string, number>;
  selectedView: "all" | "favorites";
  favoriteCategoryFilter: string | null;
  onSelectFavorites: (groupSlug: string | null) => void;
}
```

- [ ] **Step 2: Destructure new props**

Add the new props to the destructuring in the function signature (line 24). Add after `onSelectStatus`:

```typescript
  favoriteCounts,
  selectedView,
  favoriteCategoryFilter,
  onSelectFavorites,
```

- [ ] **Step 3: Add FAVORITES section in the JSX**

After the SUGGESTED CATEGORIES section (before the closing `</div>` on line 202), add the FAVORITES section:

```tsx
      {/* FAVORITES */}
      {favoriteCounts.size > 0 && (
        <div className="border-t border-gray-200 mt-3 pt-3">
          <div className="text-[10px] font-bold text-gray-500 tracking-wider mb-2">
            FAVORITES
          </div>
          {Array.from(favoriteCounts.entries()).map(([groupSlug, count]) => {
            const group = groups.find((g) => g.slug === groupSlug);
            if (!group) return null;
            const isSelected = selectedView === "favorites" && favoriteCategoryFilter === groupSlug;
            return (
              <button
                key={groupSlug}
                onClick={() => onSelectFavorites(groupSlug)}
                className={`w-full text-left px-2 py-1.5 rounded flex justify-between items-center ${
                  isSelected ? "font-semibold text-gray-900 bg-pink-50" : "hover:bg-gray-50 text-gray-700"
                }`}
              >
                <span>{group.name_en}</span>
                <span className="text-xs text-gray-400">{count}</span>
              </button>
            );
          })}
          <button
            onClick={() => onSelectFavorites(null)}
            className={`w-full text-left px-2 py-1.5 text-xs rounded ${
              selectedView === "favorites" && !favoriteCategoryFilter
                ? "font-semibold text-pink-700 bg-pink-50"
                : "text-pink-600 hover:text-pink-700 hover:bg-pink-50"
            }`}
          >
            Show all favorites
          </button>
        </div>
      )}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/laws/components/sidebar.tsx
git commit -m "feat: add FAVORITES section to sidebar"
```

---

### Task 8: Library Page — State, Toggle, Favorites View

**Files:**
- Modify: `frontend/src/app/laws/library-page.tsx`

This is the largest task. It wires everything together.

- [ ] **Step 1: Add new state variables**

After the existing filter state declarations (line 24, after `selectedStatus`), add:

```typescript
  // Favorites
  const [favorites, setFavorites] = useState<Set<number>>(new Set());
  const [selectedView, setSelectedView] = useState<"all" | "favorites">("all");
  const [favoriteCategoryFilter, setFavoriteCategoryFilter] = useState<string | null>(null);
```

- [ ] **Step 2: Initialize favorites from library data**

In the `fetchData` callback (line 107), after `setData(result)`, add initialization:

Change:
```typescript
    try {
      const result = await api.laws.library();
      setData(result);
      setError(null);
    }
```

To:
```typescript
    try {
      const result = await api.laws.library();
      setData(result);
      setFavorites(new Set(result.favorite_law_ids));
      setError(null);
    }
```

- [ ] **Step 3: Add toggleFavorite function**

After the `fetchData` callback, add the toggle function:

```typescript
  const toggleFavorite = useCallback(async (lawId: number) => {
    const wasFavorite = favorites.has(lawId);
    // Optimistic update
    setFavorites((prev) => {
      const next = new Set(prev);
      if (wasFavorite) {
        next.delete(lawId);
      } else {
        next.add(lawId);
      }
      return next;
    });
    try {
      if (wasFavorite) {
        await api.laws.favoriteRemove(lawId);
      } else {
        await api.laws.favoriteAdd(lawId);
      }
    } catch {
      // Revert on error
      setFavorites((prev) => {
        const next = new Set(prev);
        if (wasFavorite) {
          next.add(lawId);
        } else {
          next.delete(lawId);
        }
        return next;
      });
    }
  }, [favorites]);
```

- [ ] **Step 4: Add favoriteCounts memo**

After the existing `useMemo` blocks (around line 190, after `classifiedLaws`), add:

```typescript
  // Compute favorite counts by group slug for sidebar
  const favoriteCounts = useMemo(() => {
    if (!data) return new Map<string, number>();
    const counts = new Map<string, number>();
    for (const law of data.laws) {
      if (favorites.has(law.id) && law.category_group_slug) {
        counts.set(law.category_group_slug, (counts.get(law.category_group_slug) || 0) + 1);
      }
    }
    return counts;
  }, [data, favorites]);
```

- [ ] **Step 5: Add onSelectFavorites handler**

After the `toggleFavorite` function, add:

```typescript
  function handleSelectFavorites(groupSlug: string | null) {
    setSelectedView("favorites");
    setFavoriteCategoryFilter(groupSlug);
    // Clear regular filters
    setSelectedGroup(null);
    setSelectedCategory(null);
    setSelectedStatus(null);
  }
```

- [ ] **Step 6: Update Sidebar props**

In the JSX, update the `<Sidebar>` component (line 639) to pass the new props. Change:

```tsx
        <Sidebar
          groups={data.groups}
          laws={data.laws}
          selectedGroup={selectedGroup}
          selectedCategory={selectedCategory}
          selectedStatus={selectedStatus}
          onSelectGroup={setSelectedGroup}
          onSelectCategory={setSelectedCategory}
          onSelectStatus={setSelectedStatus}
        />
```

To:

```tsx
        <Sidebar
          groups={data.groups}
          laws={data.laws}
          selectedGroup={selectedGroup}
          selectedCategory={selectedCategory}
          selectedStatus={selectedStatus}
          onSelectGroup={(slug) => { setSelectedView("all"); setSelectedGroup(slug); }}
          onSelectCategory={(slug) => { setSelectedView("all"); setSelectedCategory(slug); }}
          onSelectStatus={(status) => { setSelectedView("all"); setSelectedStatus(status); }}
          favoriteCounts={favoriteCounts}
          selectedView={selectedView}
          favoriteCategoryFilter={favoriteCategoryFilter}
          onSelectFavorites={handleSelectFavorites}
        />
```

- [ ] **Step 7: Pass favoriteIds and onToggleFavorite to CategoryGroupSection**

Update each `<CategoryGroupSection>` rendering (there are two in the JSX — the active groups around line 669 and the suggested-only groups around line 697). For each, add these two props:

```tsx
                  favoriteIds={favorites}
                  onToggleFavorite={toggleFavorite}
```

For the first one (active groups), the full component becomes:
```tsx
                <CategoryGroupSection
                  key={g.slug}
                  groupSlug={g.slug}
                  groupName={g.name_en}
                  colorHex={g.color_hex}
                  laws={laws}
                  suggestedLaws={suggestions}
                  pendingImports={pending}
                  defaultExpanded={!!selectedGroup || pending.length > 0}
                  onAssign={setAssigningLawId}
                  onDelete={fetchData}
                  onImportSuggestion={handleImportSuggestion}
                  onDismissPendingError={dismissPendingError}
                  favoriteIds={favorites}
                  onToggleFavorite={toggleFavorite}
                />
```

For the second one (suggested-only), add the same two props.

- [ ] **Step 8: Add favorites view rendering**

In the main content area (inside `<div className="flex-1 p-5">` around line 651), wrap the existing content in a conditional on `selectedView`. After `<StatsCards>`, add the favorites view before the existing grouped law sections.

Add this block right after the `<StatsCards>` component:

```tsx
          {selectedView === "favorites" ? (
            /* FAVORITES VIEW */
            <>
              <div className="mb-4">
                <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5 text-pink-500">
                    <path d="M11.645 20.91l-.007-.003-.022-.012a15.247 15.247 0 01-.383-.218 25.18 25.18 0 01-4.244-3.17C4.688 15.36 2.25 12.174 2.25 8.25 2.25 5.322 4.714 3 7.688 3A5.5 5.5 0 0112 5.052 5.5 5.5 0 0116.313 3c2.973 0 5.437 2.322 5.437 5.25 0 3.925-2.438 7.111-4.739 9.256a25.175 25.175 0 01-4.244 3.17 15.247 15.247 0 01-.383.219l-.022.012-.007.004-.003.001a.752.752 0 01-.704 0l-.003-.001z" />
                  </svg>
                  Favorites
                </h2>
                <p className="text-sm text-gray-500">
                  Showing {favorites.size} favorited law{favorites.size !== 1 ? "s" : ""}
                </p>
              </div>
              {favorites.size === 0 ? (
                <div className="text-center py-12">
                  <h3 className="text-lg font-medium text-gray-900 mb-2">No favorited laws yet</h3>
                  <p className="text-gray-600">Click the heart icon on any law to add it here.</p>
                </div>
              ) : (
                data.groups
                  .filter((g) => {
                    if (favoriteCategoryFilter && g.slug !== favoriteCategoryFilter) return false;
                    return data.laws.some((l) => favorites.has(l.id) && l.category_group_slug === g.slug);
                  })
                  .map((g) => {
                    const favLaws = data.laws.filter(
                      (l) => favorites.has(l.id) && l.category_group_slug === g.slug
                    );
                    return (
                      <CategoryGroupSection
                        key={g.slug}
                        groupSlug={g.slug}
                        groupName={g.name_en}
                        colorHex={g.color_hex}
                        laws={favLaws}
                        suggestedLaws={[]}
                        pendingImports={[]}
                        defaultExpanded={true}
                        onDelete={fetchData}
                        favoriteIds={favorites}
                        onToggleFavorite={toggleFavorite}
                      />
                    );
                  })
              )}
            </>
          ) : (
            /* NORMAL VIEW — wrap existing content */
            <>
```

Then close the fragment and ternary after the existing `UnclassifiedSection` (line 730):

```tsx
            </>
          )}
```

This wraps the existing grouped law sections, empty state, and unclassified section inside the `<>...</>` of the else branch.

- [ ] **Step 9: Also pass favorites to UnclassifiedSection's LawCards**

The `UnclassifiedSection` renders `LawCard` components. We need to update it too. Read `frontend/src/app/laws/components/unclassified-section.tsx` and add `favoriteIds` and `onToggleFavorite` props, threading them to LawCard, following the same pattern as CategoryGroupSection.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/app/laws/library-page.tsx frontend/src/app/laws/components/unclassified-section.tsx
git commit -m "feat: wire favorites state, toggle, view mode, and sidebar integration"
```

---

### Task 9: Final Verification

- [ ] **Step 1: Start backend and verify table creation**

```bash
cd backend && python -m uvicorn app.main:app --reload
```

Check logs for no errors. The `law_favorites` table should be created silently.

- [ ] **Step 2: Start frontend and test all features**

```bash
cd frontend && npm run dev
```

Test manually:
1. Click heart on a law — it should fill pink
2. Refresh page — favorite should persist
3. Check sidebar — FAVORITES section should appear with counts
4. Click "Show all favorites" — should show only favorited laws
5. Click a category in FAVORITES — should filter to that category
6. In normal view, check that favorited laws sort to top in their group
7. Click filled heart to unfavorite — law should disappear from favorites view

- [ ] **Step 3: Verify no data loss**

```bash
cd backend && python -c "
from app.database import SessionLocal
from app.models.law import Law, LawVersion
db = SessionLocal()
law_count = db.query(Law).count()
version_count = db.query(LawVersion).count()
print(f'Laws: {law_count}, Versions: {version_count}')
db.close()
"
```

Confirm counts match the stats shown in the UI before the change.

- [ ] **Step 4: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: address any issues found during verification"
```
