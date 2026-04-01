# EU Suggestion Import Routing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix "+ Importa" on EU law suggestions to route through the EUR-Lex import endpoint instead of the Romanian legislatie.just.ro path.

**Architecture:** Frontend detects EU suggestions by the presence of `celex_number` and calls `api.laws.euImport()` instead of `api.laws.importSuggestion()`. Backend exposes `celex_number` in the library data response.

**Tech Stack:** Python/FastAPI (backend), TypeScript/Next.js (frontend)

---

### Task 1: Backend — expose `celex_number` in suggested laws

**Files:**
- Modify: `backend/app/services/category_service.py:594-598`

- [ ] **Step 1: Add `celex_number` to the suggested law dict**

In `backend/app/services/category_service.py`, find the `suggested.append(...)` block inside `get_library_data()` (line ~594) and add `celex_number`:

```python
        if cat:
            suggested.append({
                "id": m.id, "title": m.title, "law_number": m.law_number,
                "celex_number": m.celex_number,
                "category_id": m.category_id, "category_slug": cat.slug,
                "group_slug": cat.group.slug,
            })
```

The only change is adding the `"celex_number": m.celex_number,` line.

- [ ] **Step 2: Verify backend starts cleanly**

Run: `cd backend && python -c "from app.services.category_service import get_library_data; print('OK')"`
Expected: `OK` (no import errors)

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/category_service.py
git commit -m "feat: expose celex_number in suggested law library data"
```

---

### Task 2: Frontend — add `celex_number` to type and route imports

**Files:**
- Modify: `frontend/src/lib/api.ts:87-94`
- Modify: `frontend/src/app/laws/library-page.tsx:166-167`

- [ ] **Step 1: Add `celex_number` to the `SuggestedLaw` interface**

In `frontend/src/lib/api.ts`, find the `SuggestedLaw` interface (line ~87) and add the field:

```typescript
export interface SuggestedLaw {
  id: number;
  title: string;
  law_number: string | null;
  celex_number: string | null;
  category_id: number;
  category_slug: string;
  group_slug: string;
}
```

The only change is adding `celex_number: string | null;` after `law_number`.

- [ ] **Step 2: Branch import call in `startImport()`**

In `frontend/src/app/laws/library-page.tsx`, find the `startImport()` function (line ~153). Replace:

```typescript
    api.laws
      .importSuggestion(suggestion.id, importHistory, controller.signal)
      .then(() => {
```

With:

```typescript
    const importPromise = suggestion.celex_number
      ? api.laws.euImport(suggestion.celex_number, importHistory)
      : api.laws.importSuggestion(suggestion.id, importHistory, controller.signal);

    importPromise
      .then(() => {
```

This routes EU suggestions (those with a `celex_number`) through `POST /api/laws/eu/import` and keeps Romanian suggestions on the existing `POST /api/laws/import-suggestion` path.

- [ ] **Step 3: Verify frontend builds**

Run: `cd frontend && npx next build 2>&1 | tail -5`
Expected: Build succeeds with no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/app/laws/library-page.tsx
git commit -m "feat: route EU suggestion imports through EUR-Lex endpoint"
```

---

### Task 3: Manual verification

- [ ] **Step 1: Start the app and navigate to Legal Library**

Open the Legal Library page. Verify that the EU law suggestions (GDPR, AI Act, DSA, etc.) still appear with the "+ Importa" button.

- [ ] **Step 2: Click "+ Importa" on an EU suggestion (e.g., GDPR)**

Select "Current version only". Verify:
- The import starts (spinner shown)
- The import completes successfully (no "no standard law number" error)
- The imported law appears in the library under the EU law category

- [ ] **Step 3: Verify Romanian suggestions still work**

If any Romanian suggestions are visible, click "+ Importa" on one and verify it still imports correctly through legislatie.just.ro.
