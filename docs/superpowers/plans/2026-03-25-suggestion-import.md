# Suggestion Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the "+ Importa" button on law suggestions to auto-search legislatie.just.ro, import the law, and auto-assign its category.

**Architecture:** New backend endpoint `POST /api/laws/import-suggestion` handles the full flow: lookup mapping -> search legislatie.just.ro -> import -> assign category. Frontend adds version picker dropdown to suggestion buttons and calls this endpoint via a new `api.laws.importSuggestion()` method, passed down from `library-page.tsx`.

**Tech Stack:** FastAPI (backend), React/Next.js (frontend), SQLAlchemy, legislatie.just.ro search via `search_service.advanced_search`

**Spec:** `docs/superpowers/specs/2026-03-25-suggestion-import-design.md`

---

### Task 1: Backend — Add `POST /api/laws/import-suggestion` endpoint

**Files:**
- Modify: `backend/app/routers/laws.py:18-21` (add new Pydantic model after `ImportRequest`)
- Modify: `backend/app/routers/laws.py:207` (add new endpoint after the existing `/import` endpoint block)

**Note:** `Law` and `LawVersion` are already imported at line 10 of this file. `LawMapping` is already imported at line 11. No new imports needed at module scope.

- [ ] **Step 1: Add the request model**

In `backend/app/routers/laws.py`, after the existing `ImportRequest` class (line 21), add:

```python
class ImportSuggestionRequest(BaseModel):
    mapping_id: int
    import_history: bool = False


# LawMapping.document_type stores English keys; advanced_search expects
# Romanian abbreviated keys or numeric codes from legislatie.just.ro.
_DOC_TYPE_TO_SEARCH_CODE = {
    "law": "1",
    "emergency_ordinance": "18",
    "government_ordinance": "13",
    "government_resolution": "2",
    "decree": "3",
    "constitution": "22",
    "regulation": "12",
    "directive": "113",
}
```

- [ ] **Step 2: Add the endpoint**

In `backend/app/routers/laws.py`, after the `import_law` endpoint (after line 206), add:

```python
@router.post("/import-suggestion")
def import_suggestion(req: ImportSuggestionRequest, db: Session = Depends(get_db)):
    """Import a law from a suggestion (LawMapping) by searching legislatie.just.ro."""
    from app.services.search_service import advanced_search
    from app.services.leropa_service import import_law as do_import

    # 1. Look up mapping
    mapping = db.query(LawMapping).filter(LawMapping.id == req.mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    # 2. Validate law_number exists
    if not mapping.law_number:
        raise HTTPException(
            status_code=400,
            detail="This suggestion cannot be auto-imported (no law number)",
        )

    # 3. Check if already imported by law_number (+ document_type/year if available)
    existing_query = db.query(Law).filter(Law.law_number == mapping.law_number)
    if mapping.document_type:
        existing_query = existing_query.filter(Law.document_type == mapping.document_type)
    if mapping.law_year:
        existing_query = existing_query.filter(Law.law_year == mapping.law_year)
    existing = existing_query.first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"This law is already imported as '{existing.title}'",
        )

    # 4. Search legislatie.just.ro
    doc_type_code = _DOC_TYPE_TO_SEARCH_CODE.get(mapping.document_type or "", "")
    year_str = str(mapping.law_year) if mapping.law_year else ""

    try:
        results = advanced_search(
            doc_type=doc_type_code,
            number=mapping.law_number,
            year=year_str,
        )
    except Exception as e:
        logger.error(f"Search failed for suggestion {req.mapping_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Search failed: {str(e)}")

    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"No results found on legislatie.just.ro for {mapping.title}",
        )

    # 5. Pick best match — first result (search is already filtered by type+number+year)
    best = results[0]
    ver_id = best.ver_id

    # 6. Check if this ver_id is already imported
    existing_ver = db.query(LawVersion).filter(LawVersion.ver_id == ver_id).first()
    if existing_ver:
        raise HTTPException(
            status_code=409,
            detail=f"This law is already imported as '{existing_ver.law.title}'",
        )

    # 7. Import
    try:
        result = do_import(db, ver_id, import_history=req.import_history)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to import suggestion {req.mapping_id} (ver_id={ver_id})")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")

    # 8. Auto-assign category
    law = db.query(Law).filter(Law.id == result["law_id"]).first()
    if law:
        law.category_id = mapping.category_id
        db.commit()

    return {
        "law_id": result["law_id"],
        "title": result.get("title", mapping.title),
    }
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/laws.py
git commit -m "feat: add POST /api/laws/import-suggestion endpoint"
```

---

### Task 2: Frontend — Add `importSuggestion` to the API client

**Files:**
- Modify: `frontend/src/lib/api.ts` (add new method to `api.laws` object, after `assignCategory`)

- [ ] **Step 1: Add the API method**

In `frontend/src/lib/api.ts`, inside the `api.laws` object, add after the `assignCategory` method:

```typescript
importSuggestion: (mappingId: number, importHistory: boolean, signal?: AbortSignal) =>
  apiFetch<{ law_id: number; title: string }>("/api/laws/import-suggestion", {
    method: "POST",
    body: JSON.stringify({ mapping_id: mappingId, import_history: importHistory }),
    signal,
  }),
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add importSuggestion to API client"
```

---

### Task 3: Frontend — Wire suggestion button with version picker in CategoryGroupSection

**Files:**
- Modify: `frontend/src/app/laws/components/category-group-section.tsx:7-16` (add prop to interface)
- Modify: `frontend/src/app/laws/components/category-group-section.tsx:20-29` (destructure new prop)
- Modify: `frontend/src/app/laws/components/category-group-section.tsx:30` (add state after existing useState)
- Modify: `frontend/src/app/laws/components/category-group-section.tsx:74-92` (wire button)

- [ ] **Step 1: Add the prop and local state**

Update the interface (line 7-16) to add the new prop:

```typescript
interface CategoryGroupSectionProps {
  groupSlug: string;
  groupName: string;
  colorHex: string;
  laws: LibraryLaw[];
  suggestedLaws: SuggestedLaw[];
  defaultExpanded?: boolean;
  onAssign?: (lawId: number) => void;
  onDelete?: () => void;
  onImportSuggestion?: (mappingId: number, importHistory: boolean) => Promise<void>;
}
```

Add `onImportSuggestion` to the props destructuring (line 20-29).

- [ ] **Step 2: Add local state and useRef for click-outside**

Update the import line (line 3) to include `useRef` and `useEffect`:

```typescript
import { useState, useRef, useEffect } from "react";
```

After the existing `useState` on line 30, add:

```typescript
const [pickingId, setPickingId] = useState<number | null>(null);
const [importingIds, setImportingIds] = useState<Set<number>>(new Set());
const [errorMap, setErrorMap] = useState<Record<number, string>>({});
const pickerRef = useRef<HTMLDivElement>(null);

// Close version picker on outside click
useEffect(() => {
  if (pickingId === null) return;
  function handleClick(e: MouseEvent) {
    if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
      setPickingId(null);
    }
  }
  document.addEventListener("mousedown", handleClick);
  return () => document.removeEventListener("mousedown", handleClick);
}, [pickingId]);
```

- [ ] **Step 3: Add the import handler**

After the state/effect declarations, add:

```typescript
async function handleSuggestionImport(id: number, importHistory: boolean) {
  setPickingId(null);
  setImportingIds((prev) => new Set(prev).add(id));
  setErrorMap((prev) => { const next = { ...prev }; delete next[id]; return next; });
  try {
    await onImportSuggestion?.(id, importHistory);
  } catch (err) {
    setErrorMap((prev) => ({
      ...prev,
      [id]: err instanceof Error ? err.message : "Import failed",
    }));
  } finally {
    setImportingIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }
}
```

- [ ] **Step 4: Replace the static button with the version picker**

Replace the suggestion rendering block (lines 80-90) with:

```tsx
{suggestedLaws.map((s) => {
  const isImporting = importingIds.has(s.id);
  return (
    <div key={s.id} className="border border-dashed border-gray-200 rounded-lg p-3 mb-1.5 opacity-60">
      <div className="flex justify-between items-center">
        <div className="text-sm text-gray-600">{s.title}</div>
        <div ref={pickingId === s.id ? pickerRef : undefined} className="relative flex-shrink-0 ml-3">
          {isImporting ? (
            <span className="text-xs text-gray-400 px-2.5 py-1">
              Importing...
            </span>
          ) : (
            <button
              onClick={() => setPickingId(pickingId === s.id ? null : s.id)}
              className="text-xs border border-blue-500 text-blue-600 px-2.5 py-1 rounded hover:bg-blue-50"
            >
              + Importa
            </button>
          )}
          {pickingId === s.id && !isImporting && (
            <div className="absolute right-0 top-full mt-1 z-50 bg-white rounded-lg border border-gray-200 shadow-lg p-3 w-52">
              <p className="text-xs text-gray-500 mb-2">What to import?</p>
              <button
                onClick={() => handleSuggestionImport(s.id, false)}
                className="w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-blue-50 text-gray-700"
              >
                Current version only
              </button>
              <button
                onClick={() => handleSuggestionImport(s.id, true)}
                className="w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-blue-50 text-gray-700"
              >
                All historical versions
              </button>
              <button
                onClick={() => setPickingId(null)}
                className="w-full text-left px-3 py-1 text-xs rounded-md hover:bg-gray-50 text-gray-400 mt-1"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      </div>
      {errorMap[s.id] && (
        <p className="text-xs text-red-600 mt-1">{errorMap[s.id]}</p>
      )}
    </div>
  );
})}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/laws/components/category-group-section.tsx
git commit -m "feat: wire suggestion import button with version picker dropdown"
```

---

### Task 4: Frontend — Add handler in library-page.tsx and pass prop down

**Files:**
- Modify: `frontend/src/app/laws/library-page.tsx:4` (add `api` import if not present — already imported)
- Modify: `frontend/src/app/laws/library-page.tsx:95-103` (add handler after existing `handleAssign`)
- Modify: `frontend/src/app/laws/library-page.tsx:162-173` (pass new prop to `CategoryGroupSection`)

- [ ] **Step 1: Add the import handler**

In `frontend/src/app/laws/library-page.tsx`, after `handleAssign` (after line 103), add:

```typescript
async function handleImportSuggestion(mappingId: number, importHistory: boolean) {
  const controller = new AbortController();
  const timeoutMs = importHistory ? 600_000 : 120_000;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    await api.laws.importSuggestion(mappingId, importHistory, controller.signal);
    clearTimeout(timer);
    fetchData();
  } catch (err) {
    clearTimeout(timer);
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Import timed out — try importing current version only.");
    }
    throw err;
  }
}
```

- [ ] **Step 2: Pass the prop to CategoryGroupSection**

In the `CategoryGroupSection` JSX (lines 162-173), add the `onImportSuggestion` prop:

```tsx
<CategoryGroupSection
  key={g.slug}
  groupSlug={g.slug}
  groupName={g.name_en}
  colorHex={g.color_hex}
  laws={laws}
  suggestedLaws={suggestions}
  defaultExpanded={!!selectedGroup}
  onAssign={setAssigningLawId}
  onDelete={fetchData}
  onImportSuggestion={handleImportSuggestion}
/>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/laws/library-page.tsx
git commit -m "feat: add suggestion import handler and pass to CategoryGroupSection"
```

---

### Task 5: Manual smoke test

- [ ] **Step 1: Start backend and frontend**

Ensure both servers are running.

- [ ] **Step 2: Test the flow**

1. Go to `localhost:3000/laws`
2. Expand a category group that has suggestions
3. Click "+ Importa" on a suggestion
4. Verify the version picker dropdown appears
5. Click outside the dropdown — verify it closes
6. Click "+ Importa" again, then click "Current version only"
7. Verify the button shows "Importing..."
8. After import completes, verify the page refreshes and the suggestion disappears
9. Verify the imported law appears in the correct category group

- [ ] **Step 3: Test error cases**

1. Try importing a suggestion that's already imported — should show 409 error inline
2. Check browser console for any errors

- [ ] **Step 4: Final commit if any fixes needed**
