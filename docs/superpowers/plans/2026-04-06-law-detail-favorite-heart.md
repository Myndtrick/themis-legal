# Favorite Heart on Law Detail Page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a favorite-toggle heart button to the law detail page (`/laws/[id]`), matching the one in the list view.

**Architecture:** Extend the existing `GET /api/laws/{law_id}` backend endpoint with an `is_favorite` boolean for the current user, thread it through the `LawDetail` TypeScript type, and render a reused heart SVG inline next to the `<h1>` title with optimistic toggle against the existing favorite add/remove endpoints.

**Tech Stack:** FastAPI + SQLAlchemy (backend), Next.js + React + TypeScript (frontend).

---

## File Structure

- `backend/app/routers/laws.py` — modify `get_law` (line 867) to accept `current_user` and include `is_favorite` in response.
- `frontend/src/lib/api.ts` — add `is_favorite: boolean` to `LawDetail` interface (line 156).
- `frontend/src/app/laws/[id]/page.tsx` — add favorite state, toggle handler, and heart button inline with title.

No new files. No shared heart component — the SVG is duplicated inline (two use sites only).

---

### Task 1: Backend — include `is_favorite` in `GET /api/laws/{law_id}`

**Files:**
- Modify: `backend/app/routers/laws.py:867-931`

- [ ] **Step 1: Update `get_law` signature and add favorite lookup**

In `backend/app/routers/laws.py`, change the function signature at line 868 from:

```python
@router.get("/{law_id}")
def get_law(law_id: int, db: Session = Depends(get_db)):
    """Get a law with all its versions."""
    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")
```

to:

```python
@router.get("/{law_id}")
def get_law(
    law_id: int,
    db: Session = Depends(get_db),
    current_user: "User" = Depends(get_current_user),
):
    """Get a law with all its versions."""
    from app.models.favorite import LawFavorite
    from app.models.user import User  # noqa: F401

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    is_favorite = db.query(LawFavorite).filter(
        LawFavorite.user_id == current_user.id,
        LawFavorite.law_id == law_id,
    ).first() is not None
```

- [ ] **Step 2: Add `is_favorite` to the response dict**

In the `return { ... }` block (currently lines 898-930), add the new key right after `"category_confidence"`:

```python
        "category_confidence": law.category_confidence,
        "is_favorite": is_favorite,
        "last_checked_at": str(law.last_checked_at) if law.last_checked_at else None,
```

- [ ] **Step 3: Manually verify with curl**

Start the backend (if not running). Then hit the endpoint as an authenticated user (use whichever session cookie / auth mechanism the dev environment uses — same way other endpoints are hit during development):

```bash
curl -s http://localhost:8000/api/laws/1 -b cookies.txt | python -m json.tool | grep is_favorite
```

Expected: `"is_favorite": false,` (or `true` if law 1 is already favorited).

- [ ] **Step 4: Toggle via the existing favorite endpoint and re-check**

```bash
curl -s -X POST http://localhost:8000/api/laws/1/favorite -b cookies.txt
curl -s http://localhost:8000/api/laws/1 -b cookies.txt | python -m json.tool | grep is_favorite
```

Expected: `"is_favorite": true,`

Then clean up:

```bash
curl -s -X DELETE http://localhost:8000/api/laws/1/favorite -b cookies.txt
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/laws.py
git commit -m "feat(backend): include is_favorite in GET /api/laws/{id}"
```

---

### Task 2: Frontend — add `is_favorite` to `LawDetail` type

**Files:**
- Modify: `frontend/src/lib/api.ts:156-181`

- [ ] **Step 1: Add the field to the interface**

In `frontend/src/lib/api.ts`, locate the `LawDetail` interface (line 156) and add `is_favorite` right after `category_confidence`:

```typescript
export interface LawDetail {
  id: number;
  title: string;
  law_number: string;
  law_year: number;
  document_type: string;
  description: string | null;
  keywords: string | null;
  issuer: string | null;
  source_url: string | null;
  status: string;
  status_override: boolean;
  last_checked_at: string | null;
  unimported_version_count: number;
  versions: LawVersionSummary[];
  category: {
    id: number;
    slug: string;
    name_ro: string;
    name_en: string;
    group_name_ro: string;
    group_name_en: string;
    group_color_hex: string;
  } | null;
  category_confidence: string | null;
  is_favorite: boolean;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors. (If there are pre-existing unrelated errors, confirm none reference `LawDetail` or `is_favorite`.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): add is_favorite to LawDetail type"
```

---

### Task 3: Frontend — render heart button on law detail page

**Files:**
- Modify: `frontend/src/app/laws/[id]/page.tsx`

- [ ] **Step 1: Add favorite state and toggle handler**

At the top of the `LawDetailPage` component in `frontend/src/app/laws/[id]/page.tsx`, add a new state and a toggle handler. The existing imports already cover `useState` and `api`.

After the existing `const [loading, setLoading] = useState(true);` line (line 17), add:

```tsx
  const [isFavorite, setIsFavorite] = useState(false);
  const [favoriteBusy, setFavoriteBusy] = useState(false);
```

Change the existing `useEffect` (lines 19-24) to also initialize `isFavorite` from the response:

```tsx
  useEffect(() => {
    api.laws.get(lawId)
      .then((result) => {
        setLaw(result);
        setIsFavorite(result.is_favorite);
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [lawId]);
```

Below the `useEffect`, add the toggle handler:

```tsx
  async function handleToggleFavorite() {
    if (favoriteBusy) return;
    const next = !isFavorite;
    setIsFavorite(next);
    setFavoriteBusy(true);
    try {
      if (next) {
        await api.laws.favoriteAdd(lawId);
      } else {
        await api.laws.favoriteRemove(lawId);
      }
    } catch {
      setIsFavorite(!next);
      alert("Failed to update favorite.");
    } finally {
      setFavoriteBusy(false);
    }
  }
```

- [ ] **Step 2: Render the heart button inline with the title**

Change the existing title line (currently line 68):

```tsx
        <h1 className="text-2xl font-bold text-gray-900">{law.title}</h1>
```

to a flex row containing the title and the heart button:

```tsx
        <div className="flex items-start gap-3">
          <h1 className="text-2xl font-bold text-gray-900 flex-1">{law.title}</h1>
          <button
            onClick={handleToggleFavorite}
            disabled={favoriteBusy}
            className="p-1.5 rounded hover:bg-pink-50 transition-colors flex-shrink-0 disabled:opacity-50"
            title={isFavorite ? "Remove from favorites" : "Add to favorites"}
            aria-label={isFavorite ? "Remove from favorites" : "Add to favorites"}
          >
            {isFavorite ? (
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-6 h-6 text-pink-500">
                <path d="M11.645 20.91l-.007-.003-.022-.012a15.247 15.247 0 01-.383-.218 25.18 25.18 0 01-4.244-3.17C4.688 15.36 2.25 12.174 2.25 8.25 2.25 5.322 4.714 3 7.688 3A5.5 5.5 0 0112 5.052 5.5 5.5 0 0116.313 3c2.973 0 5.437 2.322 5.437 5.25 0 3.925-2.438 7.111-4.739 9.256a25.175 25.175 0 01-4.244 3.17 15.247 15.247 0 01-.383.219l-.022.012-.007.004-.003.001a.752.752 0 01-.704 0l-.003-.001z" />
              </svg>
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-6 h-6 text-gray-400 hover:text-pink-400">
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z" />
              </svg>
            )}
          </button>
        </div>
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors related to this change.

- [ ] **Step 4: Manual smoke test in the browser**

1. Start backend + frontend dev servers.
2. Open a law detail page that is NOT currently favorited. The heart should render outline/gray.
3. Click it. It should immediately flip to filled pink.
4. Navigate back to `/laws`. The same law's row in the list should show a filled pink heart.
5. Click the heart on the detail page again. It should flip back to outline.
6. Reload the detail page. Initial state should match what was last set.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/laws/[id]/page.tsx
git commit -m "feat(frontend): add favorite heart button to law detail page"
```

---

## Self-Review Notes

- Spec coverage: backend `is_favorite` (Task 1), type update (Task 2), UI heart with optimistic toggle and larger size (Task 3). All spec sections covered.
- No placeholders — every step shows actual code.
- Field name `is_favorite` consistent across backend, TypeScript type, and state initialization.
- Method names `favoriteAdd` / `favoriteRemove` match existing `api.ts` exports verified in `frontend/src/lib/api.ts:908-911`.
