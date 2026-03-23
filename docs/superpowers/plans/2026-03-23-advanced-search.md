# Advanced Search — Law Discovery & Import — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured filters and keyword search for discovering and importing laws from legislatie.just.ro, with law status tracking and admin override.

**Architecture:** Extend the existing search service with structured parameters, add a new `/api/laws/advanced-search` endpoint, replace the frontend import form with a collapsible advanced search UI, and add `status`/`status_override` fields to the Law model with auto-detection on import.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, Next.js (app router), TypeScript, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-03-23-advanced-search-design.md`

---

## File Structure

### Backend — Modified files
- `backend/app/models/law.py` — add `LawStatus` enum, `status` + `status_override` columns to `Law`
- `backend/app/services/search_service.py` — extend `_do_search` with `emitent`, `date_from`, `date_to` params; add `_parse_date_to_iso`; add `advanced_search` function
- `backend/app/services/leropa_service.py` — add `detect_law_status` helper; call it at end of `import_law`
- `backend/app/routers/laws.py` — add `/advanced-search`, `/emitents`, `PATCH /{law_id}/status` endpoints; add `status`/`status_override` to list and detail responses
- `backend/app/services/update_checker.py` — add status re-evaluation after importing new versions

### Backend — New files
- `backend/app/services/emitent_service.py` — static emitent list + autocomplete logic

### Frontend — New files
- `frontend/src/app/laws/search-import-form.tsx` — replaces `import-form.tsx`
- `frontend/src/app/laws/[id]/status-badge.tsx` — status badge + edit dropdown

### Frontend — Modified files
- `frontend/src/app/laws/page.tsx` — swap import to `search-import-form`
- `frontend/src/lib/api.ts` — add `advancedSearch`, `emitents`, `updateStatus` API functions; add `status`/`status_override` to interfaces
- `frontend/src/app/laws/[id]/page.tsx` — add status badge

### Frontend — Deleted files
- `frontend/src/app/laws/import-form.tsx` — replaced by `search-import-form.tsx`

---

## Task 1: Add `status` and `status_override` to Law model

**Files:**
- Modify: `backend/app/models/law.py`

- [ ] **Step 1: Add LawStatus enum and new columns**

In `backend/app/models/law.py`, add after the `DocumentState` enum:

```python
class LawStatus(str, enum.Enum):
    IN_FORCE = "in_force"
    REPEALED = "repealed"
    PARTIALLY_REPEALED = "partially_repealed"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"
```

Add to the `Law` class, after `source_url`:

```python
status: Mapped[str] = mapped_column(String(50), default="unknown")
status_override: Mapped[bool] = mapped_column(Boolean, default=False)
```

- [ ] **Step 2: Verify the app starts and the migration runs**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.database import Base, engine; Base.metadata.create_all(bind=engine); print('OK')"`

Expected: `OK` (SQLAlchemy will add the new columns via `create_all` since this uses SQLite)

**Note:** SQLite `create_all` does NOT add columns to existing tables. If the database already has data, you need to manually add the columns:

```bash
cd /Users/anaandrei/projects/legalese/backend
python -c "
from app.database import engine
with engine.connect() as conn:
    import sqlalchemy
    try:
        conn.execute(sqlalchemy.text('ALTER TABLE laws ADD COLUMN status VARCHAR(50) DEFAULT \"unknown\"'))
        conn.execute(sqlalchemy.text('ALTER TABLE laws ADD COLUMN status_override BOOLEAN DEFAULT 0'))
        conn.commit()
        print('Columns added')
    except Exception as e:
        print(f'Columns may already exist: {e}')
"
```

- [ ] **Step 3: Backfill existing laws**

```bash
cd /Users/anaandrei/projects/legalese/backend
python -c "
from app.database import SessionLocal
from app.models.law import Law, LawVersion
db = SessionLocal()
laws = db.query(Law).all()
for law in laws:
    current = next((v for v in law.versions if v.is_current), None)
    if current:
        if current.state == 'deprecated':
            law.status = 'repealed'
        elif current.state == 'actual':
            law.status = 'in_force'
        else:
            law.status = 'unknown'
    else:
        law.status = 'unknown'
    law.status_override = False
db.commit()
db.close()
print(f'Backfilled {len(laws)} laws')
"
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/law.py
git commit -m "feat: add status and status_override fields to Law model"
```

---

## Task 2: Add status auto-detection to import flow

**Files:**
- Modify: `backend/app/services/leropa_service.py`

- [ ] **Step 1: Add `detect_law_status` helper**

Add at the top of `leropa_service.py`, after the imports:

```python
def detect_law_status(db: Session, law: Law) -> str:
    """Auto-detect law status from the newest version's state.

    Returns one of: 'in_force', 'repealed', 'unknown'.
    """
    current = (
        db.query(LawVersion)
        .filter(LawVersion.law_id == law.id, LawVersion.is_current == True)
        .first()
    )
    if not current:
        return "unknown"
    if current.state == "deprecated":
        return "repealed"
    if current.state == "actual":
        return "in_force"
    return "unknown"
```

- [ ] **Step 2: Call it at the end of `import_law`, before the commit**

In `import_law`, after the `is_current` logic and before creating the notification, add:

```python
    # Auto-detect law status from the newest version
    if not law.status_override:
        law.status = detect_law_status(db, law)
```

- [ ] **Step 3: Verify import still works**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -m uvicorn app.main:app --port 8000`

Test with a curl or the existing frontend that import still works and the status field gets set.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/leropa_service.py
git commit -m "feat: auto-detect law status on import"
```

---

## Task 3: Extend `_do_search` with new parameters

**Files:**
- Modify: `backend/app/services/search_service.py`

- [ ] **Step 1: Add `emitent`, `date_from`, `date_to` parameters to `_do_search`**

Update the `_do_search` function signature and form_data:

```python
def _do_search(
    session: requests.Session,
    token: str,
    title_text: str = "",
    content_text: str = "",
    doc_type: str = "",
    doc_number: str = "",
    emitent: str = "",
    date_from: str = "",
    date_to: str = "",
) -> list[SearchResult]:
```

Update the form_data dict inside `_do_search`:

```python
    form_data = {
        "__RequestVerificationToken": token,
        "TitleText": title_text,
        "ContentText_First": content_text,
        "opContentText_Second": "SI",
        "ContentText_Second": "",
        "opContentText_Third": "SI",
        "ContentText_Third": "",
        "opContentText_Fourth": "SI",
        "ContentText_Fourth": "",
        "DocumentType": doc_type,
        "DocumentNumber": doc_number,
        "DataSemnariiTextFrom": "",
        "DataSemnariiTextTo": date_to,
        "PublishedInName": "",
        "PublishedInNumber": "",
        "DataPublicariiTextFrom": "",
        "DataPublicariiTextTo": "",
        "ActInForceOnDateTextFrom": date_from,
        "EmitentAct": emitent,
        "actiontype": "Căutare",
    }
```

- [ ] **Step 2: Add `date_iso` to SearchResult and parsing**

Add `date_iso` field to the `SearchResult` dataclass:

```python
@dataclass
class SearchResult:
    ver_id: str
    title: str
    description: str
    doc_type: str
    number: str
    date: str
    issuer: str
    date_iso: str | None = None
```

Add a helper function before `_parse_search_results`:

```python
def _parse_date_to_iso(date_str: str) -> str | None:
    """Convert DD/MM/YYYY to YYYY-MM-DD."""
    if not date_str:
        return None
    try:
        parts = date_str.strip().split("/")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
    except (ValueError, IndexError):
        pass
    return None
```

In `_parse_search_results`, when creating each `SearchResult`, add:

```python
        results.append(SearchResult(
            ver_id=ver_id,
            title=title,
            description=description,
            doc_type=doc_type,
            number=number,
            date=date,
            issuer=issuer,
            date_iso=_parse_date_to_iso(date),
        ))
```

- [ ] **Step 3: Verify existing search still works**

Run the backend server and test the existing `/api/laws/search?q=legea 31` endpoint to confirm it still returns results.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/search_service.py
git commit -m "feat: extend _do_search with emitent, date_from, date_to params and date_iso"
```

---

## Task 4: Add `advanced_search` function in search service

**Files:**
- Modify: `backend/app/services/search_service.py`

- [ ] **Step 1: Add the `advanced_search` function**

Add at the end of `search_service.py`:

```python
# Map dropdown labels to legislatie.just.ro DocumentType codes
ADVANCED_DOC_TYPE_MAP = {
    "lege": "1",
    "oug": "18",
    "hg": "2",
    "ordin": "5",
    "decizie": "17",
    # Regulament and Directivă EU have no codes — handled via title keyword
}

# Types that have no numeric code and use title keyword instead
TITLE_KEYWORD_TYPES = {"regulament", "directiva_eu"}


def advanced_search(
    keyword: str = "",
    doc_type: str = "",
    number: str = "",
    year: str = "",
    emitent: str = "",
    date_from: str = "",
    date_to: str = "",
    include_repealed: str = "only_in_force",
    max_results: int = 20,
) -> list[SearchResult]:
    """Search legislatie.just.ro with structured filters.

    Args:
        keyword: Free-text search (title + content)
        doc_type: Act type key (e.g. "lege", "oug", "hg", "regulament", "directiva_eu")
        number: Law number
        year: Law year (4 digits)
        emitent: Issuer name
        date_from: YYYY-MM-DD, maps to ActInForceOnDateTextFrom
        date_to: YYYY-MM-DD, maps to DataSemnariiTextTo
        include_repealed: "only_in_force" | "all" | "only_repealed"
        max_results: Max results to return
    """
    from datetime import date as date_type

    session, token = _get_session_and_token()

    # Build document number
    doc_number = ""
    if number:
        doc_number = f"{number}-{year}" if year else number

    # Resolve doc_type code
    resolved_doc_type = ADVANCED_DOC_TYPE_MAP.get(doc_type.lower(), "") if doc_type else ""
    title_prefix = ""
    if doc_type.lower() in TITLE_KEYWORD_TYPES:
        # No numeric code — prepend type name to title search
        label_map = {"regulament": "regulament", "directiva_eu": "directiva"}
        title_prefix = label_map.get(doc_type.lower(), "")
        resolved_doc_type = ""

    # Build title text
    title_text = keyword
    if title_prefix:
        title_text = f"{title_prefix} {keyword}".strip()

    # Convert YYYY-MM-DD dates to DD.MM.YYYY for legislatie.just.ro
    def _to_ro_date(iso_date: str) -> str:
        """Convert YYYY-MM-DD to DD.MM.YYYY."""
        if not iso_date:
            return ""
        parts = iso_date.split("-")
        if len(parts) == 3:
            return f"{parts[2]}.{parts[1]}.{parts[0]}"
        return iso_date

    ro_date_to = _to_ro_date(date_to)

    # Handle include_repealed via date_from
    if include_repealed == "only_in_force":
        effective_date_from = _to_ro_date(date_from) if date_from else date_type.today().strftime("%d.%m.%Y")
    elif include_repealed == "only_repealed":
        # First search unfiltered, then subtract in-force results later
        effective_date_from = _to_ro_date(date_from) if date_from else ""
    else:  # "all"
        effective_date_from = _to_ro_date(date_from) if date_from else ""

    all_results: list[SearchResult] = []
    seen_ids: set[str] = set()

    def _add_results(results: list[SearchResult]):
        for r in results:
            if r.ver_id not in seen_ids:
                seen_ids.add(r.ver_id)
                all_results.append(r)

    # Primary search: title
    if title_text or resolved_doc_type or doc_number or emitent or effective_date_from or date_to:
        results = _do_search(
            session, token,
            title_text=title_text,
            doc_type=resolved_doc_type,
            doc_number=doc_number,
            emitent=emitent,
            date_from=effective_date_from,
            date_to=ro_date_to,
        )
        _add_results(results)

    # Fallback: content search if keyword provided and title search had few results
    if keyword and len(all_results) < max_results:
        token = _refresh_token(session)
        results = _do_search(
            session, token,
            content_text=keyword,
            doc_type=resolved_doc_type,
            doc_number=doc_number,
            emitent=emitent,
            date_from=effective_date_from,
            date_to=ro_date_to,
        )
        _add_results(results)

    # Handle "only_repealed": requires a second search to find what IS in force,
    # then subtract from the unfiltered results
    if include_repealed == "only_repealed":
        # Re-run the same search but with today's date as in-force filter
        token = _refresh_token(session)
        today_str = date_type.today().strftime("%d.%m.%Y")
        in_force_results = _do_search(
            session, token,
            title_text=title_text,
            doc_type=resolved_doc_type,
            doc_number=doc_number,
            emitent=emitent,
            date_from=today_str,
            date_to=ro_date_to,
        )
        in_force_ids = {r.ver_id for r in in_force_results}
        all_results = [r for r in all_results if r.ver_id not in in_force_ids]

    return all_results[:max_results]
```

- [ ] **Step 2: Verify by calling it directly**

```bash
cd /Users/anaandrei/projects/legalese/backend
python -c "
from app.services.search_service import advanced_search
results = advanced_search(keyword='societati', doc_type='lege', include_repealed='all')
for r in results[:3]:
    print(f'{r.doc_type} {r.number} {r.date} - {r.title}')
print(f'Total: {len(results)}')
"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/search_service.py
git commit -m "feat: add advanced_search function with structured filters"
```

---

## Task 5: Add emitent service

**Files:**
- Create: `backend/app/services/emitent_service.py`

- [ ] **Step 1: Create the emitent service**

```python
"""Emitent (issuer) autocomplete service."""

PINNED_EMITENTS = [
    "Parlamentul României",
    "Guvernul României",
    "Ministerul Finanțelor",
    "Banca Națională a României (BNR)",
    "Autoritatea de Supraveghere Financiară (ASF)",
    "ANAF",
    "Ministerul Justiției",
    "Oficiul Național de Prevenire și Combatere a Spălării Banilor (ONPCSB)",
    "Comisia Europeană / Parlamentul European",
]


def search_emitents(query: str) -> list[str]:
    """Return emitents matching the query.

    Filters the pinned list by case-insensitive partial match.
    Returns all pinned emitents if query is empty.
    """
    if not query or len(query) < 2:
        return PINNED_EMITENTS

    q_lower = query.lower()
    return [e for e in PINNED_EMITENTS if q_lower in e.lower()]
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/emitent_service.py
git commit -m "feat: add emitent autocomplete service"
```

---

## Task 6: Add backend API endpoints

**Files:**
- Modify: `backend/app/routers/laws.py`

- [ ] **Step 1: Add `advanced-search` endpoint**

**IMPORTANT:** Add these endpoints BEFORE the `/{law_id}` route (after `search_external`). FastAPI matches routes in order — if placed after `/{law_id}`, "advanced-search" will be parsed as a `law_id` integer and fail with 422.

Add after the existing `search_external` function:

```python
@router.get("/advanced-search")
def advanced_search_endpoint(
    keyword: str = "",
    doc_type: str = "",
    number: str = "",
    year: str = "",
    emitent: str = "",
    date_from: str = "",
    date_to: str = "",
    include_repealed: str = "only_in_force",
    db: Session = Depends(get_db),
):
    """Advanced search on legislatie.just.ro with structured filters."""
    from app.services.search_service import advanced_search

    try:
        results = advanced_search(
            keyword=keyword,
            doc_type=doc_type,
            number=number,
            year=year,
            emitent=emitent,
            date_from=date_from,
            date_to=date_to,
            include_repealed=include_repealed,
        )
    except Exception as e:
        logger.error(f"Advanced search failed: {e}")
        raise HTTPException(status_code=502, detail=f"Search failed: {str(e)}")

    # Cross-reference with local DB to flag already-imported laws
    enriched = []
    for r in results:
        already_imported = False
        local_law_id = None

        # Primary: check LawVersion.ver_id
        existing_version = (
            db.query(LawVersion)
            .filter(LawVersion.ver_id == r.ver_id)
            .first()
        )
        if existing_version:
            already_imported = True
            local_law_id = existing_version.law_id
        else:
            # Secondary: check Law.source_url
            source_url = f"https://legislatie.just.ro/Public/DetaliiDocument/{r.ver_id}"
            existing_law = db.query(Law).filter(Law.source_url == source_url).first()
            if existing_law:
                already_imported = True
                local_law_id = existing_law.id

        enriched.append({
            **r.to_dict(),
            "already_imported": already_imported,
            "local_law_id": local_law_id,
        })

    return {"results": enriched, "total": len(enriched)}
```

- [ ] **Step 2: Add `emitents` endpoint**

Add after the advanced search endpoint:

```python
@router.get("/emitents")
def get_emitents(q: str = ""):
    """Autocomplete emitent (issuer) names."""
    from app.services.emitent_service import search_emitents
    return {"emitents": search_emitents(q)}
```

- [ ] **Step 3: Add `PATCH /{law_id}/status` endpoint**

Add after the `delete_old_versions` function:

```python
class StatusUpdateRequest(BaseModel):
    status: str
    override: bool = True


@router.patch("/{law_id}/status")
def update_law_status(law_id: int, req: StatusUpdateRequest, db: Session = Depends(get_db)):
    """Update the status of a law (admin override)."""
    from app.services.leropa_service import detect_law_status

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    valid_statuses = {"in_force", "repealed", "partially_repealed", "superseded", "unknown"}
    if req.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    if req.override:
        law.status = req.status
        law.status_override = True
    else:
        # Reset to auto-detection
        law.status_override = False
        law.status = detect_law_status(db, law)

    db.commit()
    return {"status": law.status, "status_override": law.status_override}
```

- [ ] **Step 4: Add `status` and `status_override` to list and detail responses**

In `list_laws`, add to the return dict per law (after `"current_version"`):

```python
            "status": law.status,
            "status_override": law.status_override,
```

In `get_law`, add to the return dict (after `"source_url"`):

```python
        "status": law.status,
        "status_override": law.status_override,
```

- [ ] **Step 5: Verify endpoints work**

Start the backend and test:

```bash
curl "http://localhost:8000/api/laws/emitents?q=BNR"
curl "http://localhost:8000/api/laws/advanced-search?keyword=societati&doc_type=lege&include_repealed=all"
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/laws.py
git commit -m "feat: add advanced-search, emitents, and status endpoints"
```

---

## Task 7: Add status re-evaluation to update checker

**Files:**
- Modify: `backend/app/services/update_checker.py`

- [ ] **Step 1: Add status re-evaluation after importing new versions**

At the top of `update_checker.py`, add the import:

```python
from app.services.leropa_service import detect_law_status
```

After the `is_current` update logic (after `dated[0][0].is_current = True`, around line 126), add:

```python
                # Re-evaluate law status if not manually overridden
                if not law.status_override:
                    law.status = detect_law_status(db, law)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/update_checker.py
git commit -m "feat: re-evaluate law status on update check"
```

---

## Task 8: Update frontend API client and types

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add new interfaces and API functions**

Add `status` and `status_override` to `LawSummary`:

```typescript
export interface LawSummary {
  id: number;
  title: string;
  law_number: string;
  law_year: number;
  document_type: string;
  description: string | null;
  version_count: number;
  status: string;
  status_override: boolean;
  current_version: {
    id: number;
    ver_id: string;
    date_in_force: string | null;
    state: string;
  } | null;
}
```

Add `status` and `status_override` to `LawDetail`:

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
  versions: LawVersionSummary[];
}
```

Add new interfaces after `DiffResult`:

```typescript
export interface AdvancedSearchResult {
  ver_id: string;
  title: string;
  doc_type: string;
  number: string;
  date: string;
  date_iso: string | null;
  issuer: string;
  description: string;
  already_imported: boolean;
  local_law_id: number | null;
}

export interface AdvancedSearchResponse {
  results: AdvancedSearchResult[];
  total: number;
}

export interface EmitentsResponse {
  emitents: string[];
}
```

Add new API functions to `api.laws`:

```typescript
    advancedSearch: (params: Record<string, string>) => {
      const query = new URLSearchParams(params).toString();
      return apiFetch<AdvancedSearchResponse>(`/api/laws/advanced-search?${query}`);
    },
    emitents: (q: string) =>
      apiFetch<EmitentsResponse>(`/api/laws/emitents?q=${encodeURIComponent(q)}`),
    updateStatus: (id: number, status: string, override: boolean) =>
      apiFetch<{ status: string; status_override: boolean }>(
        `/api/laws/${id}/status`,
        {
          method: "PATCH",
          body: JSON.stringify({ status, override }),
        }
      ),
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add advanced search types and API functions"
```

---

## Task 9: Build the search-import-form component

**Files:**
- Create: `frontend/src/app/laws/search-import-form.tsx`
- Delete: `frontend/src/app/laws/import-form.tsx`
- Modify: `frontend/src/app/laws/page.tsx`

**Important:** Before writing this component, read the Next.js docs in `node_modules/next/dist/docs/` per `AGENTS.md` instructions to check for any API changes.

- [ ] **Step 1: Create `search-import-form.tsx`**

Create `frontend/src/app/laws/search-import-form.tsx` with:

```tsx
"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface SearchResult {
  ver_id: string;
  title: string;
  doc_type: string;
  number: string;
  date: string;
  date_iso: string | null;
  issuer: string;
  description: string;
  already_imported: boolean;
  local_law_id: number | null;
}

const ACT_TYPES = [
  { label: "All types", value: "" },
  { label: "Lege", value: "lege" },
  { label: "OUG", value: "oug" },
  { label: "HG", value: "hg" },
  { label: "Ordin", value: "ordin" },
  { label: "Regulament", value: "regulament" },
  { label: "Directivă EU", value: "directiva_eu" },
  { label: "Decizie", value: "decizie" },
];

const STATUS_OPTIONS = [
  { label: "In force only", value: "only_in_force" },
  { label: "All (incl. repealed)", value: "all" },
  { label: "Only repealed", value: "only_repealed" },
];

const DOC_TYPE_COLORS: Record<string, string> = {
  LEGE: "bg-blue-100 text-blue-800",
  OUG: "bg-amber-100 text-amber-800",
  HG: "bg-indigo-100 text-indigo-800",
  ORDIN: "bg-purple-100 text-purple-800",
  DECIZIE: "bg-teal-100 text-teal-800",
};

export default function SearchImportForm() {
  const router = useRouter();

  // Search state
  const [keyword, setKeyword] = useState("");
  const [docType, setDocType] = useState("");
  const [lawNumber, setLawNumber] = useState("");
  const [year, setYear] = useState("");
  const [emitent, setEmitent] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [includeRepealed, setIncludeRepealed] = useState("only_in_force");
  const [showFilters, setShowFilters] = useState(false);

  // Results state
  const [results, setResults] = useState<SearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Import state
  const [importHistory, setImportHistory] = useState(true);
  const [importingIds, setImportingIds] = useState<Set<string>>(new Set());
  const [importedIds, setImportedIds] = useState<Map<string, number>>(new Map());
  const [importErrors, setImportErrors] = useState<Map<string, string>>(new Map());

  // Emitent autocomplete
  const [emitentSuggestions, setEmitentSuggestions] = useState<string[]>([]);
  const [showEmitentDropdown, setShowEmitentDropdown] = useState(false);
  const emitentTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const emitentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (emitentRef.current && !emitentRef.current.contains(e.target as Node)) {
        setShowEmitentDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const fetchEmitents = useCallback(async (q: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/laws/emitents?q=${encodeURIComponent(q)}`);
      if (res.ok) {
        const data = await res.json();
        setEmitentSuggestions(data.emitents);
        setShowEmitentDropdown(true);
      }
    } catch {
      // Silently fail
    }
  }, []);

  function handleEmitentChange(value: string) {
    setEmitent(value);
    if (emitentTimeout.current) clearTimeout(emitentTimeout.current);
    emitentTimeout.current = setTimeout(() => fetchEmitents(value), 500);
  }

  async function handleSearch(e?: React.FormEvent) {
    e?.preventDefault();
    setSearching(true);
    setSearchError(null);

    const params = new URLSearchParams();
    if (keyword) params.set("keyword", keyword);
    if (docType) params.set("doc_type", docType);
    if (lawNumber) params.set("number", lawNumber);
    if (year) params.set("year", year);
    if (emitent) params.set("emitent", emitent);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    params.set("include_repealed", includeRepealed);

    try {
      const res = await fetch(`${API_BASE}/api/laws/advanced-search?${params}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Search failed (${res.status})`);
      }
      const data = await res.json();
      setResults(data.results);
      setTotal(data.total);
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : "Search failed");
      setResults([]);
      setTotal(0);
    } finally {
      setSearching(false);
    }
  }

  async function handleImport(verId: string) {
    setImportingIds((prev) => new Set(prev).add(verId));
    setImportErrors((prev) => {
      const next = new Map(prev);
      next.delete(verId);
      return next;
    });

    try {
      const res = await fetch(`${API_BASE}/api/laws/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ver_id: verId, import_history: importHistory }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Import failed");
      }
      setImportedIds((prev) => new Map(prev).set(verId, data.law_id));
      router.refresh();
    } catch (err) {
      setImportErrors((prev) => {
        const next = new Map(prev);
        next.set(verId, err instanceof Error ? err.message : "Import failed");
        return next;
      });
    } finally {
      setImportingIds((prev) => {
        const next = new Set(prev);
        next.delete(verId);
        return next;
      });
    }
  }

  function handleClearFilters() {
    setKeyword("");
    setDocType("");
    setLawNumber("");
    setYear("");
    setEmitent("");
    setDateFrom("");
    setDateTo("");
    setIncludeRepealed("only_in_force");
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6 mb-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Search & Import Laws</h2>

      {/* Keyword bar */}
      <form onSubmit={handleSearch} className="space-y-3">
        <div className="flex gap-3">
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder='Search by keyword, name, or topic...'
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            disabled={searching}
          />
          <button
            type="submit"
            disabled={searching}
            className="rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
          >
            {searching ? "Searching..." : "Search"}
          </button>
        </div>

        {/* Advanced filters toggle */}
        <button
          type="button"
          onClick={() => setShowFilters(!showFilters)}
          className="text-sm text-blue-600 hover:text-blue-800 flex items-center gap-1"
        >
          <span className="text-xs">{showFilters ? "▲" : "▼"}</span>
          Advanced Filters
        </button>

        {/* Collapsible filters */}
        {showFilters && (
          <div className="p-4 bg-gray-50 rounded-lg space-y-3">
            <div className="grid grid-cols-3 gap-3">
              {/* Act Type */}
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Act Type</label>
                <select
                  value={docType}
                  onChange={(e) => setDocType(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
                >
                  {ACT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>

              {/* Law Number */}
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Law Number</label>
                <input
                  type="text"
                  value={lawNumber}
                  onChange={(e) => setLawNumber(e.target.value.replace(/\D/g, ""))}
                  placeholder="e.g. 31"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>

              {/* Year */}
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Year</label>
                <input
                  type="text"
                  value={year}
                  onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))}
                  placeholder="e.g. 1990"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              {/* Emitent */}
              <div ref={emitentRef} className="relative">
                <label className="block text-xs font-semibold text-gray-600 mb-1">Emitent</label>
                <input
                  type="text"
                  value={emitent}
                  onChange={(e) => handleEmitentChange(e.target.value)}
                  onFocus={() => fetchEmitents(emitent)}
                  placeholder="Search issuers..."
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
                {showEmitentDropdown && emitentSuggestions.length > 0 && (
                  <div className="absolute z-50 w-full mt-1 bg-white rounded-md border border-gray-200 shadow-lg max-h-48 overflow-y-auto">
                    {emitentSuggestions.map((e) => (
                      <button
                        key={e}
                        type="button"
                        onClick={() => {
                          setEmitent(e);
                          setShowEmitentDropdown(false);
                        }}
                        className="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 border-b border-gray-50 last:border-b-0"
                      >
                        {e}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Date From */}
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">In Force From</label>
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>

              {/* Date To */}
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Signed Before</label>
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
            </div>

            <div className="flex items-center justify-between">
              {/* Status filter */}
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Status</label>
                <select
                  value={includeRepealed}
                  onChange={(e) => setIncludeRepealed(e.target.value)}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
                >
                  {STATUS_OPTIONS.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>

              {/* Clear filters */}
              <button
                type="button"
                onClick={handleClearFilters}
                className="text-sm text-gray-500 hover:text-gray-700 border border-gray-300 rounded-md px-3 py-1.5"
              >
                Clear Filters
              </button>
            </div>
          </div>
        )}
      </form>

      {/* Search error */}
      {searchError && (
        <div className="mt-4 rounded-md bg-red-50 border border-red-200 p-3">
          <p className="text-sm text-red-700">{searchError}</p>
        </div>
      )}

      {/* Results */}
      {results.length > 0 && (
        <div className="mt-4 border border-gray-200 rounded-lg overflow-hidden">
          {/* Results header */}
          <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
            <span className="text-sm text-gray-600">{total} result{total !== 1 ? "s" : ""} found</span>
            <label className="text-sm text-gray-700 flex items-center gap-2">
              <input
                type="checkbox"
                checked={importHistory}
                onChange={(e) => setImportHistory(e.target.checked)}
                className="rounded border-gray-300"
              />
              Import all historical versions
            </label>
          </div>

          {/* Result rows */}
          {results.map((r) => {
            const isImporting = importingIds.has(r.ver_id);
            const justImported = importedIds.has(r.ver_id);
            const isAlreadyImported = r.already_imported || justImported;
            const localId = r.local_law_id || importedIds.get(r.ver_id);
            const error = importErrors.get(r.ver_id);
            const colorClass = DOC_TYPE_COLORS[r.doc_type] || "bg-gray-100 text-gray-600";

            return (
              <div key={r.ver_id} className="px-4 py-3 border-b border-gray-100 last:border-b-0">
                <div className="flex items-center justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${colorClass}`}>
                        {r.doc_type || "DOC"}
                      </span>
                      <span className="text-sm font-semibold text-gray-900">
                        nr. {r.number} din {r.date}
                      </span>
                    </div>
                    <p className="text-sm text-gray-600 truncate">{r.description || r.title}</p>
                    {r.issuer && (
                      <p className="text-xs text-gray-400 mt-0.5">Emitent: {r.issuer}</p>
                    )}
                    {error && (
                      <p className="text-xs text-red-600 mt-1">{error}</p>
                    )}
                  </div>
                  <div className="ml-4 shrink-0">
                    {isAlreadyImported ? (
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-green-600 bg-green-50 px-2 py-1 rounded">
                          Imported
                        </span>
                        {localId && (
                          <a
                            href={`/laws/${localId}`}
                            className="text-sm text-blue-600 hover:text-blue-800 font-medium"
                          >
                            View
                          </a>
                        )}
                      </div>
                    ) : (
                      <button
                        onClick={() => handleImport(r.ver_id)}
                        disabled={isImporting}
                        className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                      >
                        {isImporting ? "Importing..." : "Import"}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* No results message — shown after any search attempt with no results */}
      {!searching && results.length === 0 && total === 0 && searchError === null && (keyword || docType || lawNumber || year || emitent || dateFrom || dateTo) && (
        <div className="mt-4 text-center py-6 text-sm text-gray-500">
          No results found. Try different filters or keywords.
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Update `page.tsx` to use the new component**

In `frontend/src/app/laws/page.tsx`, change line 3:

```typescript
import SearchImportForm from "./search-import-form";
```

And change line 29:

```tsx
      <SearchImportForm />
```

- [ ] **Step 3: Delete `import-form.tsx`**

```bash
rm frontend/src/app/laws/import-form.tsx
```

- [ ] **Step 4: Verify the page loads**

Start both backend and frontend, navigate to `/laws`, confirm the new search form renders.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/laws/search-import-form.tsx frontend/src/app/laws/page.tsx
git rm frontend/src/app/laws/import-form.tsx
git commit -m "feat: replace import form with advanced search UI"
```

---

## Task 10: Add status badge to law detail page

**Files:**
- Create: `frontend/src/app/laws/[id]/status-badge.tsx`
- Modify: `frontend/src/app/laws/[id]/page.tsx`

- [ ] **Step 1: Create `status-badge.tsx`**

```tsx
"use client";

import { useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const STATUS_CONFIG: Record<string, { label: string; className: string }> = {
  in_force: { label: "In Force", className: "bg-green-100 text-green-700" },
  repealed: { label: "Repealed", className: "bg-red-100 text-red-700" },
  partially_repealed: { label: "Partially Repealed", className: "bg-yellow-100 text-yellow-700" },
  superseded: { label: "Superseded", className: "bg-orange-100 text-orange-700" },
  unknown: { label: "Unknown", className: "bg-gray-100 text-gray-500" },
};

const STATUS_OPTIONS = ["in_force", "repealed", "partially_repealed", "superseded", "unknown"];

interface StatusBadgeProps {
  lawId: number;
  initialStatus: string;
  initialOverride: boolean;
}

export default function StatusBadge({ lawId, initialStatus, initialOverride }: StatusBadgeProps) {
  const [status, setStatus] = useState(initialStatus);
  const [override, setOverride] = useState(initialOverride);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);

  const config = STATUS_CONFIG[status] || STATUS_CONFIG.unknown;

  async function handleStatusChange(newStatus: string) {
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/api/laws/${lawId}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus, override: true }),
      });
      if (res.ok) {
        const data = await res.json();
        setStatus(data.status);
        setOverride(data.status_override);
      }
    } catch {
      // Silently fail
    } finally {
      setSaving(false);
      setEditing(false);
    }
  }

  async function handleResetToAuto() {
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/api/laws/${lawId}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, override: false }),
      });
      if (res.ok) {
        const data = await res.json();
        setStatus(data.status);
        setOverride(data.status_override);
      }
    } catch {
      // Silently fail
    } finally {
      setSaving(false);
      setEditing(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold ${config.className}`}>
        {config.label}
      </span>

      {override && (
        <span className="text-xs text-gray-400 italic">Manually set</span>
      )}

      {!editing ? (
        <button
          onClick={() => setEditing(true)}
          className="text-xs text-blue-600 hover:text-blue-800"
        >
          Edit
        </button>
      ) : (
        <div className="flex items-center gap-2">
          <select
            value={status}
            onChange={(e) => handleStatusChange(e.target.value)}
            disabled={saving}
            className="text-xs rounded border border-gray-300 px-2 py-1"
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>{STATUS_CONFIG[s]?.label || s}</option>
            ))}
          </select>
          {override && (
            <button
              onClick={handleResetToAuto}
              disabled={saving}
              className="text-xs text-gray-500 hover:text-gray-700"
            >
              Reset to auto
            </button>
          )}
          <button
            onClick={() => setEditing(false)}
            className="text-xs text-gray-400 hover:text-gray-600"
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add status badge to law detail page**

In `frontend/src/app/laws/[id]/page.tsx`, add the import:

```typescript
import StatusBadge from "./status-badge";
```

Inside the existing `<div className="mt-3">` that contains `CheckUpdatesButton` (around line 47-49), add the StatusBadge alongside it:

```tsx
        <div className="mt-3 flex items-center gap-4">
          <StatusBadge
            lawId={law.id}
            initialStatus={law.status}
            initialOverride={law.status_override}
          />
          <CheckUpdatesButton lawId={law.id} />
        </div>
```

This replaces the existing `<div className="mt-3"><CheckUpdatesButton lawId={law.id} /></div>` block.

- [ ] **Step 3: Verify the status badge works**

Navigate to a law detail page, confirm the badge shows and the edit dropdown works.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/laws/\[id\]/status-badge.tsx frontend/src/app/laws/\[id\]/page.tsx
git commit -m "feat: add status badge with admin override to law detail page"
```

---

## Task 11: End-to-end verification

- [ ] **Step 1: Test the complete flow**

1. Start backend: `cd backend && python -m uvicorn app.main:app --port 8000`
2. Start frontend: `cd frontend && npm run dev`
3. Navigate to `/laws`
4. Test keyword search: type "societati" → click Search → verify results appear
5. Test advanced filters: expand filters, select "OUG" type → Search → verify filtered results
6. Test combined: keyword "banci" + type "OUG" → Search → verify combined results
7. Test emitent autocomplete: type "BNR" in emitent field → verify dropdown
8. Test import: click Import on a result → verify it imports and shows "Imported" + "View"
9. Test status badge: navigate to the imported law → verify status badge shows → test Edit/Reset
10. Test "Already imported" detection: search again for the same law → verify it shows "Imported"

- [ ] **Step 2: Commit any fixes**

If any issues found, fix and commit individually.
