# EU Suggestion Import Routing Design Spec

**Date:** 2026-03-30
**Scope:** Fix "+ Importa" button on EU law suggestions to route through EUR-Lex import instead of Romanian legislatie.just.ro import

---

## Problem

The Legal Library shows EU law suggestions (GDPR, AI Act, DSA, etc.) with a "+ Importa" button. Clicking it calls the Romanian import path (`POST /api/laws/import-suggestion`), which searches legislatie.just.ro — this fails because EU regulations have no Romanian law number, producing the error: "This document cannot be auto-imported because it has no standard law number."

The backend already has a working EU import endpoint (`POST /api/laws/eu/import`) that imports by CELEX number from the EUR-Lex CELLAR API, and `LawMapping` records for EU laws already have `celex_number` populated. The fix is routing the import call correctly.

## Solution: Frontend Routing

Same "+ Importa" button UI for both EU and Romanian suggestions. The frontend detects whether a suggestion is EU (has `celex_number`) and calls the appropriate import endpoint.

### Changes

**1. Backend — `category_service.py` `get_library_data()`**

Include `celex_number` in the suggested law response dict (line ~594):

```python
suggested.append({
    "id": m.id, "title": m.title, "law_number": m.law_number,
    "celex_number": m.celex_number,
    "category_id": m.category_id, "category_slug": cat.slug,
    "group_slug": cat.group.slug,
})
```

**2. Frontend — `api.ts` `SuggestedLaw` interface**

Add `celex_number` field:

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

**3. Frontend — `library-page.tsx` `startImport()`**

Branch import call based on `celex_number`:

```typescript
const importPromise = suggestion.celex_number
  ? api.laws.euImport(suggestion.celex_number, importHistory)
  : api.laws.importSuggestion(suggestion.id, importHistory, controller.signal);
```

### What stays the same

- The "+ Importa" button UI — identical for both EU and Romanian suggestions
- Romanian law import flow — completely untouched
- The EU import endpoint (`POST /api/laws/eu/import`) — already works, just not called from suggestions
- Category assignment — EU import already handles auto-categorization
- The `category-group-section.tsx` component — no changes needed

### Files affected

| File | Change |
|------|--------|
| `backend/app/services/category_service.py` | Add `celex_number` to suggested law dict |
| `frontend/src/lib/api.ts` | Add `celex_number` to `SuggestedLaw` interface |
| `frontend/src/app/laws/library-page.tsx` | Branch `startImport()` based on `celex_number` |

### Scope

3 files, ~5 lines changed. No new endpoints, no new components, no changes to Romanian import flow.
