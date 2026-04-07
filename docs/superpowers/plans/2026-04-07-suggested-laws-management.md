# Suggested Laws Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded suggestion-list seed with a user-editable Settings → Suggestions tab, and let users pin each entry to an exact source document (legislatie.just.ro `ver_id` or EUR-Lex `CELEX`) so imports stop guessing.

**Architecture:** Two new columns on `law_mappings` (`source_url`, `source_ver_id`) plus a vocabulary change on the existing `source` column (`seed` → `system`). A new pure-Python `source_url` module extracts identifiers from URLs via regex. A new `settings_law_mappings` router exposes CRUD + a `probe-url` endpoint. The existing `import_suggestion` flow branches: if `source_ver_id` is set, skip `advanced_search` entirely. Frontend gets a new Settings tab, table, and add/edit modal.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, pytest (backend); Next.js App Router, React, Tailwind (frontend).

**Spec:** `docs/superpowers/specs/2026-04-07-suggested-laws-management-design.md`

---

## File Structure

**Backend — new files:**
- `backend/app/services/source_url.py` — pure regex extractors for legislatie.just.ro and EUR-Lex
- `backend/app/routers/settings_law_mappings.py` — CRUD + probe endpoints
- `backend/tests/test_source_url.py` — unit tests for the extractors
- `backend/tests/test_settings_law_mappings.py` — API tests for the router
- `backend/tests/test_import_suggestion_pinned.py` — integration test for the import branching

**Backend — modified files:**
- `backend/app/models/category.py` — add `source_url`, `source_ver_id` columns
- `backend/app/main.py` — additive migrations + register new router + rename `source='seed'`→`'system'`
- `backend/app/services/category_service.py` — `seed_categories` writes `source='system'` and skip-if-exists
- `backend/app/routers/laws.py` — `import_suggestion` and `import_suggestion_stream` branch on `source_ver_id`

**Frontend — new files:**
- `frontend/src/app/settings/suggestions/suggestions-table.tsx` — table + filter controls
- `frontend/src/app/settings/suggestions/suggestion-form-modal.tsx` — add/edit modal with URL paste

**Frontend — modified files:**
- `frontend/src/lib/api.ts` — add types and fetch helpers
- `frontend/src/app/settings/settings-tabs.tsx` — add `"suggestions"` tab
- `frontend/src/app/settings/page.tsx` — render the new tab

---

## Task 1: URL extraction module (TDD)

**Files:**
- Create: `backend/app/services/source_url.py`
- Test: `backend/tests/test_source_url.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_source_url.py
from app.services.source_url import extract_ver_id, extract_celex, probe_url


class TestExtractVerId:
    def test_basic_detalii_document(self):
        assert extract_ver_id("https://legislatie.just.ro/Public/DetaliiDocument/109884") == "109884"

    def test_detalii_document_afis(self):
        assert extract_ver_id("https://legislatie.just.ro/Public/DetaliiDocumentAfis/132456") == "132456"

    def test_with_query_params(self):
        assert extract_ver_id("https://legislatie.just.ro/Public/DetaliiDocument/109884?foo=bar") == "109884"

    def test_wrong_host(self):
        assert extract_ver_id("https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32016R0679") is None

    def test_malformed(self):
        assert extract_ver_id("not a url") is None

    def test_empty(self):
        assert extract_ver_id("") is None


class TestExtractCelex:
    def test_legal_content_basic(self):
        assert extract_celex("https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32016R0679") == "32016R0679"

    def test_legal_content_url_encoded_colon(self):
        assert extract_celex("https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32016R0679") == "32016R0679"

    def test_legal_content_extra_params(self):
        assert extract_celex("https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679&qid=12345") == "32016R0679"

    def test_legal_content_pdf_variant(self):
        assert extract_celex("https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32016R0679") == "32016R0679"

    def test_eli_regulation(self):
        # /eli/reg/2016/679/oj → 32016R0679
        assert extract_celex("https://eur-lex.europa.eu/eli/reg/2016/679/oj") == "32016R0679"

    def test_eli_directive(self):
        # /eli/dir/2011/83/oj → 32011L0083
        assert extract_celex("https://eur-lex.europa.eu/eli/dir/2011/83/oj") == "32011L0083"

    def test_eli_decision(self):
        # /eli/dec/2020/1234/oj → 32020D1234
        assert extract_celex("https://eur-lex.europa.eu/eli/dec/2020/1234/oj") == "32020D1234"

    def test_wrong_host(self):
        assert extract_celex("https://legislatie.just.ro/Public/DetaliiDocument/109884") is None

    def test_malformed(self):
        assert extract_celex("not a url") is None


class TestProbeUrl:
    def test_ro_url(self):
        result = probe_url("https://legislatie.just.ro/Public/DetaliiDocument/109884")
        assert result["kind"] == "ro"
        assert result["identifier"] == "109884"
        assert result["error"] is None

    def test_eu_url(self):
        result = probe_url("https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32016R0679")
        assert result["kind"] == "eu"
        assert result["identifier"] == "32016R0679"
        assert result["error"] is None

    def test_unknown_host(self):
        result = probe_url("https://example.com/foo")
        assert result["kind"] == "unknown"
        assert result["identifier"] is None
        assert result["error"] == "URL host not recognized"

    def test_known_host_no_identifier(self):
        result = probe_url("https://eur-lex.europa.eu/homepage.html")
        assert result["kind"] == "eu"
        assert result["identifier"] is None
        assert result["error"] == "Could not extract identifier"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_source_url.py -v`
Expected: ImportError — `app.services.source_url` does not exist.

- [ ] **Step 3: Implement the module**

```python
# backend/app/services/source_url.py
"""Extract source-document identifiers from public URLs.

Two pure regex-based extractors:
- legislatie.just.ro → ver_id (numeric document id)
- eur-lex.europa.eu  → CELEX number (e.g. 32016R0679)

No network calls. Used by the suggested-laws settings UI to pin a
LawMapping row to an exact source document.
"""
from __future__ import annotations

import re
from typing import TypedDict
from urllib.parse import urlparse


_VER_ID_RE = re.compile(
    r"legislatie\.just\.ro/Public/DetaliiDocument(?:Afis)?/(\d+)",
    re.IGNORECASE,
)

# Matches CELEX in legal-content URLs. Handles both ":" and "%3A" (URL-encoded).
_CELEX_RE = re.compile(
    r"[?&]uri=CELEX(?::|%3A)([0-9A-Z]+)",
    re.IGNORECASE,
)

# ELI URL: /eli/reg|dir|dec/<year>/<number>/oj
_ELI_RE = re.compile(
    r"/eli/(reg|dir|dec)/(\d{4})/(\d+)(?:/|$)",
    re.IGNORECASE,
)

_ELI_TYPE_LETTER = {"reg": "R", "dir": "L", "dec": "D"}


def extract_ver_id(url: str) -> str | None:
    """Extract a legislatie.just.ro document ver_id from a URL."""
    if not url:
        return None
    m = _VER_ID_RE.search(url)
    return m.group(1) if m else None


def extract_celex(url: str) -> str | None:
    """Extract a CELEX number from an EUR-Lex URL.

    Supports both `legal-content/?uri=CELEX:...` and ELI URLs
    (`/eli/reg|dir|dec/<year>/<number>/oj`), reconstructing CELEX
    from ELI parts when needed.
    """
    if not url:
        return None
    m = _CELEX_RE.search(url)
    if m:
        return m.group(1).upper()
    m = _ELI_RE.search(url)
    if m:
        kind, year, number = m.group(1).lower(), m.group(2), m.group(3)
        letter = _ELI_TYPE_LETTER[kind]
        return f"3{year}{letter}{int(number):04d}"
    return None


class ProbeResult(TypedDict):
    kind: str  # "ro" | "eu" | "unknown"
    identifier: str | None
    title: str | None
    error: str | None


def probe_url(url: str) -> ProbeResult:
    """Dispatch a URL to the appropriate extractor by hostname.

    Returns a ProbeResult describing what was found. Title fetching
    is left to the caller (this function is pure and offline).
    """
    if not url:
        return {"kind": "unknown", "identifier": None, "title": None,
                "error": "URL host not recognized"}
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return {"kind": "unknown", "identifier": None, "title": None,
                "error": "URL host not recognized"}

    if host.endswith("legislatie.just.ro"):
        ver_id = extract_ver_id(url)
        return {
            "kind": "ro",
            "identifier": ver_id,
            "title": None,
            "error": None if ver_id else "Could not extract identifier",
        }
    if host.endswith("eur-lex.europa.eu"):
        celex = extract_celex(url)
        return {
            "kind": "eu",
            "identifier": celex,
            "title": None,
            "error": None if celex else "Could not extract identifier",
        }
    return {"kind": "unknown", "identifier": None, "title": None,
            "error": "URL host not recognized"}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_source_url.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/source_url.py backend/tests/test_source_url.py
git commit -m "feat(backend): add source_url module for extracting ver_id and CELEX from URLs"
```

---

## Task 2: Add columns to LawMapping model

**Files:**
- Modify: `backend/app/models/category.py`
- Modify: `backend/app/main.py` (additive migration in `lifespan`)

- [ ] **Step 1: Add the new columns to the model**

In `backend/app/models/category.py`, add to the `LawMapping` class after the existing `celex_number` column:

```python
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ver_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

- [ ] **Step 2: Add the migration to lifespan**

In `backend/app/main.py`, find the existing block of `_add_column_if_missing` calls (around line 102-107) and add:

```python
        _add_column_if_missing(db, "law_mappings", "source_url", "TEXT", None)
        _add_column_if_missing(db, "law_mappings", "source_ver_id", "VARCHAR(50)", None)
```

Then immediately below the column-add block, add the source vocabulary rename (one-time, idempotent):

```python
        from sqlalchemy import text as _sql_text
        db.execute(_sql_text("UPDATE law_mappings SET source='system' WHERE source='seed'"))
        db.commit()
```

- [ ] **Step 3: Boot the backend and verify the migration ran**

Run: `cd backend && python -c "from app.database import SessionLocal, engine; from app.main import lifespan; import asyncio; from fastapi import FastAPI; app = FastAPI(); asyncio.run(lifespan(app).__aenter__())"`

Expected: no errors. Then verify columns exist:

```bash
cd backend && python -c "
from sqlalchemy import inspect
from app.database import engine
cols = [c['name'] for c in inspect(engine).get_columns('law_mappings')]
assert 'source_url' in cols, cols
assert 'source_ver_id' in cols, cols
print('OK:', cols)
"
```

Expected: prints `OK: [...]` with both columns present.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/category.py backend/app/main.py
git commit -m "feat(backend): add source_url and source_ver_id columns to law_mappings"
```

---

## Task 3: Seed loader writes 'system' and skips existing rows

**Files:**
- Modify: `backend/app/services/category_service.py`

- [ ] **Step 1: Update the seed loader**

In `backend/app/services/category_service.py::seed_categories`, find the loop near line 298:

```python
    for cat_slug, title, law_number, law_year, document_type in mappings_data:
        m = LawMapping(
            title=title,
            law_number=law_number,
            law_year=law_year,
            document_type=document_type,
            category_id=cat_map[cat_slug],
            source="seed",
        )
        db.add(m)
```

Replace with:

```python
    for cat_slug, title, law_number, law_year, document_type in mappings_data:
        cat_id = cat_map[cat_slug]
        # Skip if a matching mapping already exists (so re-seeding never
        # clobbers user edits or creates duplicates).
        existing = db.query(LawMapping).filter(
            LawMapping.category_id == cat_id,
            LawMapping.law_number == law_number,
            LawMapping.law_year == law_year,
            LawMapping.document_type == document_type,
        ).first()
        if existing:
            continue
        m = LawMapping(
            title=title,
            law_number=law_number,
            law_year=law_year,
            document_type=document_type,
            category_id=cat_id,
            source="system",
        )
        db.add(m)
```

Note: the outer `seed_categories` function still has its early-return guard (`if existing groups: return`) which means this loop only runs on a truly fresh DB today. The skip-if-exists logic above is defensive — it makes the loop safe to run on a non-empty DB, which we'll need for the new admin "Reload defaults" path (out of scope here, but the logic costs us nothing).

- [ ] **Step 2: Boot the backend and confirm seed still works**

Run: `cd backend && python -m pytest tests/ -k "seed or category" -v`
Expected: all existing seed/category tests still pass.

If no such tests exist, manually verify by deleting `data/themis.db` and booting once, then querying:

```bash
cd backend && python -c "
from app.database import SessionLocal
from app.models.category import LawMapping
db = SessionLocal()
n = db.query(LawMapping).filter(LawMapping.source == 'system').count()
seed = db.query(LawMapping).filter(LawMapping.source == 'seed').count()
print(f'system={n} seed={seed}')
assert n > 0
assert seed == 0
"
```

Expected: `system=<some number > 100>` and `seed=0`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/category_service.py
git commit -m "feat(backend): seed law_mappings with source='system' and skip-if-exists"
```

---

## Task 4: Settings router — list endpoint (TDD)

**Files:**
- Create: `backend/app/routers/settings_law_mappings.py`
- Create: `backend/tests/test_settings_law_mappings.py`
- Modify: `backend/app/main.py` (register router)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_settings_law_mappings.py
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models.category import LawMapping, Category, CategoryGroup


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Use whatever the project's existing test-auth fixture is.

    The other test files in tests/ already authenticate against the
    settings routes — copy that pattern here. If there is no shared
    fixture, create a fresh user via the user_service helpers and
    issue a token via app.auth.
    """
    from app.auth import create_access_token
    from app.services.user_service import get_or_create_admin_user
    db = SessionLocal()
    try:
        user = get_or_create_admin_user(db, email="test-mappings@example.com")
        token = create_access_token({"sub": user.email})
    finally:
        db.close()
    return {"Authorization": f"Bearer {token}"}


def test_list_returns_seeded_mappings(client, auth_headers):
    res = client.get("/api/settings/law-mappings", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)
    assert len(body) > 0
    row = body[0]
    assert "id" in row
    assert "title" in row
    assert "source" in row
    assert "category_name" in row
    assert "group_slug" in row


def test_list_filter_by_source(client, auth_headers):
    res = client.get("/api/settings/law-mappings?source=system", headers=auth_headers)
    assert res.status_code == 200
    assert all(r["source"] == "system" for r in res.json())


def test_list_filter_by_group(client, auth_headers):
    res = client.get("/api/settings/law-mappings?group_slug=civil", headers=auth_headers)
    assert res.status_code == 200
    assert all(r["group_slug"] == "civil" for r in res.json())
```

If `get_or_create_admin_user` does not exist, look at how other test files in `backend/tests/` get auth and copy that approach instead.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_settings_law_mappings.py::test_list_returns_seeded_mappings -v`
Expected: 404 — the route doesn't exist yet.

- [ ] **Step 3: Create the router with the list endpoint**

```python
# backend/app/routers/settings_law_mappings.py
"""CRUD + URL probe for law_mappings (suggested laws). Admin-only."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models.category import Category, CategoryGroup, LawMapping
from app.models.law import Law
from app.services.source_url import probe_url

router = APIRouter(
    prefix="/api/settings/law-mappings",
    tags=["settings"],
    dependencies=[Depends(get_current_user)],
)


def _serialize(m: LawMapping, is_imported: bool) -> dict:
    cat = m.category
    group = cat.group if cat else None
    return {
        "id": m.id,
        "title": m.title,
        "law_number": m.law_number,
        "law_year": m.law_year,
        "document_type": m.document_type,
        "celex_number": m.celex_number,
        "source_url": m.source_url,
        "source_ver_id": m.source_ver_id,
        "category_id": m.category_id,
        "category_name": cat.name_en if cat else None,
        "category_slug": cat.slug if cat else None,
        "group_slug": group.slug if group else None,
        "group_name": group.name_en if group else None,
        "group_color": group.color_hex if group else None,
        "source": m.source,
        "is_imported": is_imported,
    }


@router.get("")
def list_mappings(
    group_slug: str | None = None,
    category_id: int | None = None,
    source: Literal["system", "user", "all"] = "all",
    pinned: Literal["true", "false", "all"] = "all",
    q: str | None = None,
    db: Session = Depends(get_db),
):
    query = (
        db.query(LawMapping)
        .options(joinedload(LawMapping.category).joinedload(Category.group))
    )
    if category_id is not None:
        query = query.filter(LawMapping.category_id == category_id)
    if source != "all":
        query = query.filter(LawMapping.source == source)
    if pinned == "true":
        query = query.filter(
            (LawMapping.source_ver_id.isnot(None)) | (LawMapping.celex_number.isnot(None))
        )
    elif pinned == "false":
        query = query.filter(
            LawMapping.source_ver_id.is_(None), LawMapping.celex_number.is_(None)
        )
    if q:
        like = f"%{q}%"
        query = query.filter(LawMapping.title.ilike(like))

    mappings = query.all()
    if group_slug:
        mappings = [m for m in mappings if m.category and m.category.group and m.category.group.slug == group_slug]

    # Pre-compute imported lookup in one pass
    law_numbers = {(m.law_number, m.law_year, m.document_type) for m in mappings if m.law_number}
    celex_numbers = {m.celex_number for m in mappings if m.celex_number}
    imported_ro = set()
    imported_eu = set()
    if law_numbers:
        rows = db.query(Law.law_number, Law.law_year, Law.document_type).filter(
            Law.law_number.in_({n for n, _, _ in law_numbers})
        ).all()
        imported_ro = {(r[0], r[1], r[2]) for r in rows}
    if celex_numbers:
        rows = db.query(Law.celex_number).filter(Law.celex_number.in_(celex_numbers)).all()
        imported_eu = {r[0] for r in rows}

    def is_imported(m: LawMapping) -> bool:
        if m.celex_number and m.celex_number in imported_eu:
            return True
        if m.law_number and (m.law_number, m.law_year, m.document_type) in imported_ro:
            return True
        return False

    return [_serialize(m, is_imported(m)) for m in mappings]
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, add to the imports near line 16:

```python
from app.routers import settings_law_mappings
```

And below the existing `app.include_router(settings_schedulers.router)` line:

```python
app.include_router(settings_law_mappings.router)
```

- [ ] **Step 5: Run the list tests**

Run: `cd backend && python -m pytest tests/test_settings_law_mappings.py -v`
Expected: the three list tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/settings_law_mappings.py backend/app/main.py backend/tests/test_settings_law_mappings.py
git commit -m "feat(backend): add GET /api/settings/law-mappings list endpoint"
```

---

## Task 5: Create endpoint (TDD)

**Files:**
- Modify: `backend/app/routers/settings_law_mappings.py`
- Modify: `backend/tests/test_settings_law_mappings.py`

- [ ] **Step 1: Add the failing tests**

Append to `backend/tests/test_settings_law_mappings.py`:

```python
def test_create_user_mapping(client, auth_headers):
    db = SessionLocal()
    cat = db.query(Category).first()
    cat_id = cat.id
    db.close()

    res = client.post(
        "/api/settings/law-mappings",
        headers=auth_headers,
        json={
            "category_id": cat_id,
            "title": "Test law 999/2099",
            "law_number": "999",
            "law_year": 2099,
            "document_type": "law",
            "source_url": "https://legislatie.just.ro/Public/DetaliiDocument/999999",
            "source_ver_id": "999999",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["title"] == "Test law 999/2099"
    assert body["source"] == "user"
    assert body["source_ver_id"] == "999999"


def test_create_requires_category_id(client, auth_headers):
    res = client.post(
        "/api/settings/law-mappings",
        headers=auth_headers,
        json={"title": "missing category"},
    )
    assert res.status_code == 422


def test_create_rejects_invalid_category(client, auth_headers):
    res = client.post(
        "/api/settings/law-mappings",
        headers=auth_headers,
        json={"category_id": 999999, "title": "bad cat"},
    )
    assert res.status_code == 404
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && python -m pytest tests/test_settings_law_mappings.py::test_create_user_mapping -v`
Expected: 404 or 405 — POST not implemented.

- [ ] **Step 3: Add the create endpoint**

Add to `backend/app/routers/settings_law_mappings.py`:

```python
class CreateMappingRequest(BaseModel):
    category_id: int
    title: str
    law_number: str | None = None
    law_year: int | None = None
    document_type: str | None = None
    celex_number: str | None = None
    source_url: str | None = None
    source_ver_id: str | None = None


@router.post("")
def create_mapping(req: CreateMappingRequest, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == req.category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    m = LawMapping(
        title=req.title,
        law_number=req.law_number,
        law_year=req.law_year,
        document_type=req.document_type,
        celex_number=req.celex_number,
        source_url=req.source_url,
        source_ver_id=req.source_ver_id,
        category_id=req.category_id,
        source="user",
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    # reload with category eager so _serialize works
    m = (
        db.query(LawMapping)
        .options(joinedload(LawMapping.category).joinedload(Category.group))
        .filter(LawMapping.id == m.id)
        .first()
    )
    return _serialize(m, is_imported=False)
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && python -m pytest tests/test_settings_law_mappings.py -v -k create`
Expected: all three create tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/settings_law_mappings.py backend/tests/test_settings_law_mappings.py
git commit -m "feat(backend): add POST /api/settings/law-mappings endpoint"
```

---

## Task 6: Patch endpoint with system→user flip (TDD)

**Files:**
- Modify: `backend/app/routers/settings_law_mappings.py`
- Modify: `backend/tests/test_settings_law_mappings.py`

- [ ] **Step 1: Add the failing tests**

```python
def test_patch_user_mapping(client, auth_headers):
    db = SessionLocal()
    m = LawMapping(
        title="patchme", law_number="1", law_year=2000, document_type="law",
        category_id=db.query(Category).first().id, source="user",
    )
    db.add(m); db.commit(); mid = m.id; db.close()

    res = client.patch(
        f"/api/settings/law-mappings/{mid}",
        headers=auth_headers,
        json={"title": "patched"},
    )
    assert res.status_code == 200
    assert res.json()["title"] == "patched"
    assert res.json()["source"] == "user"


def test_patch_system_row_flips_to_user(client, auth_headers):
    db = SessionLocal()
    m = LawMapping(
        title="seeded", law_number="2", law_year=2001, document_type="law",
        category_id=db.query(Category).first().id, source="system",
    )
    db.add(m); db.commit(); mid = m.id; db.close()

    res = client.patch(
        f"/api/settings/law-mappings/{mid}",
        headers=auth_headers,
        json={"title": "edited by user"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "edited by user"
    assert body["source"] == "user"


def test_patch_404(client, auth_headers):
    res = client.patch("/api/settings/law-mappings/9999999", headers=auth_headers, json={"title": "x"})
    assert res.status_code == 404
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && python -m pytest tests/test_settings_law_mappings.py -v -k patch`
Expected: 404/405 — PATCH not implemented.

- [ ] **Step 3: Add the patch endpoint**

```python
class PatchMappingRequest(BaseModel):
    category_id: int | None = None
    title: str | None = None
    law_number: str | None = None
    law_year: int | None = None
    document_type: str | None = None
    celex_number: str | None = None
    source_url: str | None = None
    source_ver_id: str | None = None


@router.patch("/{mapping_id}")
def patch_mapping(mapping_id: int, req: PatchMappingRequest, db: Session = Depends(get_db)):
    m = db.query(LawMapping).filter(LawMapping.id == mapping_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mapping not found")

    data = req.model_dump(exclude_unset=True)
    if "category_id" in data:
        cat = db.query(Category).filter(Category.id == data["category_id"]).first()
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found")
    for k, v in data.items():
        setattr(m, k, v)

    # Edit-flips-system-to-user
    if m.source == "system":
        m.source = "user"

    db.commit()
    m = (
        db.query(LawMapping)
        .options(joinedload(LawMapping.category).joinedload(Category.group))
        .filter(LawMapping.id == mapping_id)
        .first()
    )
    return _serialize(m, is_imported=False)
```

- [ ] **Step 4: Run the patch tests**

Run: `cd backend && python -m pytest tests/test_settings_law_mappings.py -v -k patch`
Expected: all three patch tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/settings_law_mappings.py backend/tests/test_settings_law_mappings.py
git commit -m "feat(backend): add PATCH endpoint with system→user flip semantics"
```

---

## Task 7: Delete endpoint (TDD)

**Files:**
- Modify: `backend/app/routers/settings_law_mappings.py`
- Modify: `backend/tests/test_settings_law_mappings.py`

- [ ] **Step 1: Add the failing tests**

```python
def test_delete_mapping(client, auth_headers):
    db = SessionLocal()
    m = LawMapping(
        title="delme", law_number="3", law_year=2002, document_type="law",
        category_id=db.query(Category).first().id, source="user",
    )
    db.add(m); db.commit(); mid = m.id; db.close()

    res = client.delete(f"/api/settings/law-mappings/{mid}", headers=auth_headers)
    assert res.status_code == 200

    db = SessionLocal()
    assert db.query(LawMapping).filter(LawMapping.id == mid).first() is None
    db.close()


def test_delete_404(client, auth_headers):
    res = client.delete("/api/settings/law-mappings/9999999", headers=auth_headers)
    assert res.status_code == 404
```

- [ ] **Step 2: Run them — expect failure**

Run: `cd backend && python -m pytest tests/test_settings_law_mappings.py -v -k delete`

- [ ] **Step 3: Add the endpoint**

```python
@router.delete("/{mapping_id}")
def delete_mapping(mapping_id: int, db: Session = Depends(get_db)):
    m = db.query(LawMapping).filter(LawMapping.id == mapping_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mapping not found")
    db.delete(m)
    db.commit()
    return {"ok": True}
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && python -m pytest tests/test_settings_law_mappings.py -v -k delete`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/settings_law_mappings.py backend/tests/test_settings_law_mappings.py
git commit -m "feat(backend): add DELETE /api/settings/law-mappings/{id} endpoint"
```

---

## Task 8: Probe-URL endpoint (TDD)

**Files:**
- Modify: `backend/app/routers/settings_law_mappings.py`
- Modify: `backend/tests/test_settings_law_mappings.py`

- [ ] **Step 1: Add the failing tests**

```python
def test_probe_ro_url(client, auth_headers):
    res = client.post(
        "/api/settings/law-mappings/probe-url",
        headers=auth_headers,
        json={"url": "https://legislatie.just.ro/Public/DetaliiDocument/109884"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["kind"] == "ro"
    assert body["identifier"] == "109884"
    assert body["error"] is None


def test_probe_eu_url(client, auth_headers):
    res = client.post(
        "/api/settings/law-mappings/probe-url",
        headers=auth_headers,
        json={"url": "https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32016R0679"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["kind"] == "eu"
    assert body["identifier"] == "32016R0679"


def test_probe_unknown_host(client, auth_headers):
    res = client.post(
        "/api/settings/law-mappings/probe-url",
        headers=auth_headers,
        json={"url": "https://example.com/foo"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["kind"] == "unknown"
    assert body["identifier"] is None
    assert body["error"] == "URL host not recognized"
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && python -m pytest tests/test_settings_law_mappings.py -v -k probe`

- [ ] **Step 3: Add the endpoint**

```python
class ProbeUrlRequest(BaseModel):
    url: str


@router.post("/probe-url")
def probe_url_endpoint(req: ProbeUrlRequest):
    return probe_url(req.url)
```

Note: `probe_url` is already imported at the top of the file from Task 4. Title fetching is intentionally not implemented in v1 — the spec says it's best-effort and acceptable to return `title: null`.

- [ ] **Step 4: Run the tests**

Run: `cd backend && python -m pytest tests/test_settings_law_mappings.py -v -k probe`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/settings_law_mappings.py backend/tests/test_settings_law_mappings.py
git commit -m "feat(backend): add POST /probe-url endpoint"
```

---

## Task 9: Import flow uses pinned ver_id (TDD)

**Files:**
- Modify: `backend/app/routers/laws.py`
- Create: `backend/tests/test_import_suggestion_pinned.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_import_suggestion_pinned.py
"""When a LawMapping has source_ver_id set, import_suggestion must
skip advanced_search and pass that ver_id straight to do_import."""
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models.category import LawMapping, Category


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    from app.auth import create_access_token
    from app.services.user_service import get_or_create_admin_user
    db = SessionLocal()
    try:
        user = get_or_create_admin_user(db, email="test-pinned@example.com")
        token = create_access_token({"sub": user.email})
    finally:
        db.close()
    return {"Authorization": f"Bearer {token}"}


def _make_mapping(source_ver_id: str | None) -> int:
    db = SessionLocal()
    m = LawMapping(
        title="Pinned test law",
        law_number="42",
        law_year=2099,
        document_type="law",
        category_id=db.query(Category).first().id,
        source="user",
        source_ver_id=source_ver_id,
    )
    db.add(m); db.commit(); mid = m.id; db.close()
    return mid


def test_pinned_import_skips_search(client, auth_headers):
    mid = _make_mapping(source_ver_id="555555")

    with patch("app.services.search_service.advanced_search") as mock_search, \
         patch("app.services.leropa_service.import_law") as mock_import:
        mock_import.return_value = {"law_id": 1, "title": "ok"}
        # Force the duplicate check to find nothing
        with patch("sqlalchemy.orm.Query.first", side_effect=[
            # mapping lookup, duplicate check, ver_id duplicate check, law lookup
            None, None, None, None,
        ]):
            pass  # too brittle — use real DB instead
        # Simpler: rely on real DB. Just patch search and import.
        res = client.post(
            "/api/laws/import-suggestion",
            headers=auth_headers,
            json={"mapping_id": mid, "import_history": False},
        )

    # The mock for advanced_search must NOT have been called
    assert mock_search.call_count == 0
    # do_import was called with the pinned ver_id
    assert mock_import.called
    args, kwargs = mock_import.call_args
    # Signature: do_import(db, ver_id, import_history=...)
    assert args[1] == "555555"


def test_unpinned_import_falls_back_to_search(client, auth_headers):
    mid = _make_mapping(source_ver_id=None)

    fake_result = MagicMock()
    fake_result.ver_id = "888888"
    with patch("app.services.search_service.advanced_search", return_value=[fake_result]) as mock_search, \
         patch("app.services.leropa_service.import_law", return_value={"law_id": 2, "title": "ok"}) as mock_import:
        res = client.post(
            "/api/laws/import-suggestion",
            headers=auth_headers,
            json={"mapping_id": mid, "import_history": False},
        )

    assert mock_search.called
    assert mock_import.called
    args, kwargs = mock_import.call_args
    assert args[1] == "888888"
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && python -m pytest tests/test_import_suggestion_pinned.py -v`
Expected: `test_pinned_import_skips_search` FAILS — `advanced_search` is currently always called.

- [ ] **Step 3: Modify `import_suggestion` to branch on source_ver_id**

In `backend/app/routers/laws.py`, find `import_suggestion` (starts around line 435). Replace the section from `# 4. Search legislatie.just.ro` through `ver_id = best.ver_id`:

```python
    # 4. Resolve ver_id — pinned mappings skip the search entirely
    if mapping.source_ver_id:
        ver_id = mapping.source_ver_id
    else:
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
            raise SearchFailedError()

        if not results:
            raise HTTPException(
                status_code=404,
                detail=f"No results found on legislatie.just.ro for {mapping.title}",
            )

        # Pick best match — first result (search is filtered by type+number+year)
        ver_id = results[0].ver_id
```

Apply the analogous change to `import_suggestion_stream` (starts around line 513). Find the block from `# Search legislatie.just.ro` (line 548) through `ver_id = str(results[0].ver_id)` and replace with:

```python
    # Resolve ver_id — pinned mappings skip the search entirely
    if mapping.source_ver_id:
        ver_id = str(mapping.source_ver_id)
    else:
        doc_type_code = _DOC_TYPE_TO_SEARCH_CODE.get(mapping.document_type or "", "")
        year_str = str(mapping.law_year) if mapping.law_year else ""
        try:
            results = advanced_search(
                doc_type=doc_type_code,
                number=mapping.law_number,
                year=year_str,
            )
        except Exception as e:
            logger.error(f"Search failed for suggestion {mapping_id}: {e}")
            async def error_stream():
                yield {"event": "error", "data": json.dumps(SearchFailedError().to_dict())}
            return EventSourceResponse(error_stream())

        if not results:
            async def error_stream():
                yield {"event": "error", "data": json.dumps({"code": "not_found", "message": f"No results found on legislatie.just.ro for {mapping.title}"})}
            return EventSourceResponse(error_stream())

        ver_id = str(results[0].ver_id)
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && python -m pytest tests/test_import_suggestion_pinned.py -v`
Expected: both tests PASS.

Also run the existing import-suggestion tests to confirm no regressions:

Run: `cd backend && python -m pytest tests/ -k "import_suggestion or import-suggestion" -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/laws.py backend/tests/test_import_suggestion_pinned.py
git commit -m "feat(backend): import_suggestion skips search when source_ver_id is pinned"
```

---

## Task 10: Frontend API types and helpers

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add the types and fetch helpers**

Find the existing `export const api = { ... }` export in `frontend/src/lib/api.ts` and locate a good spot near the other settings helpers. Add the following types near the other interfaces (e.g., near `SuggestedLaw`):

```typescript
export interface LawMappingRow {
  id: number;
  title: string;
  law_number: string | null;
  law_year: number | null;
  document_type: string | null;
  celex_number: string | null;
  source_url: string | null;
  source_ver_id: string | null;
  category_id: number;
  category_name: string | null;
  category_slug: string | null;
  group_slug: string | null;
  group_name: string | null;
  group_color: string | null;
  source: "system" | "user";
  is_imported: boolean;
}

export interface ProbeUrlResult {
  kind: "ro" | "eu" | "unknown";
  identifier: string | null;
  title: string | null;
  error: string | null;
}

export interface CreateMappingPayload {
  category_id: number;
  title: string;
  law_number?: string | null;
  law_year?: number | null;
  document_type?: string | null;
  celex_number?: string | null;
  source_url?: string | null;
  source_ver_id?: string | null;
}

export type PatchMappingPayload = Partial<CreateMappingPayload>;
```

Then add to the `api` object (find the existing `api.laws = { ... }` style block and add a new `lawMappings` namespace; if the file uses individual exports instead, follow that pattern):

```typescript
export const lawMappingsApi = {
  list: (params: {
    group_slug?: string;
    category_id?: number;
    source?: "system" | "user" | "all";
    pinned?: "true" | "false" | "all";
    q?: string;
  } = {}) => {
    const qs = new URLSearchParams();
    if (params.group_slug) qs.set("group_slug", params.group_slug);
    if (params.category_id != null) qs.set("category_id", String(params.category_id));
    if (params.source) qs.set("source", params.source);
    if (params.pinned) qs.set("pinned", params.pinned);
    if (params.q) qs.set("q", params.q);
    const suffix = qs.toString() ? `?${qs}` : "";
    return apiFetch<LawMappingRow[]>(`/api/settings/law-mappings${suffix}`);
  },
  create: (payload: CreateMappingPayload) =>
    apiFetch<LawMappingRow>("/api/settings/law-mappings", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  patch: (id: number, payload: PatchMappingPayload) =>
    apiFetch<LawMappingRow>(`/api/settings/law-mappings/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  delete: (id: number) =>
    apiFetch<{ ok: true }>(`/api/settings/law-mappings/${id}`, {
      method: "DELETE",
    }),
  probeUrl: (url: string) =>
    apiFetch<ProbeUrlResult>("/api/settings/law-mappings/probe-url", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
};
```

- [ ] **Step 2: Type-check the frontend**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors. (There may be pre-existing errors in the project; the important thing is that nothing related to `LawMappingRow`/`lawMappingsApi` fails.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): add law-mappings API types and fetch helpers"
```

---

## Task 11: Add Suggestions tab to Settings nav

**Files:**
- Modify: `frontend/src/app/settings/settings-tabs.tsx`
- Modify: `frontend/src/app/settings/page.tsx`

- [ ] **Step 1: Add the tab id**

In `frontend/src/app/settings/settings-tabs.tsx`, update the `TABS` array. Insert after the `categories` entry:

```typescript
  { id: "categories", label: "Categories" },
  { id: "suggestions", label: "Suggestions" },
  { id: "models", label: "Models" },
```

- [ ] **Step 2: Wire up the tab in the page**

In `frontend/src/app/settings/page.tsx`, add an import near the other settings imports:

```typescript
import { SuggestionsTable } from "./suggestions/suggestions-table";
```

Add a new branch in the tab switch (after the `categories` branch):

```typescript
          if (activeTab === "suggestions") {
            return <SuggestionsTable />;
          }
```

- [ ] **Step 3: Verify the import doesn't break the build yet**

Don't run the dev server yet — `SuggestionsTable` doesn't exist. We'll create it in the next task. For now, just confirm the file edits look right by reading back `settings-tabs.tsx` and `page.tsx`.

- [ ] **Step 4: Commit (with placeholder note)**

We'll commit this together with the table component in Task 12 to keep the build green between commits.

---

## Task 12: Suggestions table component

**Files:**
- Create: `frontend/src/app/settings/suggestions/suggestions-table.tsx`

- [ ] **Step 1: Create the component**

```typescript
// frontend/src/app/settings/suggestions/suggestions-table.tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { lawMappingsApi, LawMappingRow } from "@/lib/api";
import { SuggestionFormModal } from "./suggestion-form-modal";

const DOC_TYPE_LABELS: Record<string, string> = {
  law: "LEGE",
  emergency_ordinance: "OUG",
  government_ordinance: "OG",
  government_resolution: "HG",
  decree: "DECRET",
  constitution: "CONSTITUȚIE",
  code: "COD",
  regulation: "REG",
  directive: "DIR",
};

export function SuggestionsTable() {
  const [rows, setRows] = useState<LawMappingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [groupFilter, setGroupFilter] = useState<string>("");
  const [sourceFilter, setSourceFilter] = useState<"all" | "system" | "user">("all");
  const [pinnedFilter, setPinnedFilter] = useState<"all" | "true" | "false">("all");
  const [search, setSearch] = useState("");

  const [editing, setEditing] = useState<LawMappingRow | null>(null);
  const [creating, setCreating] = useState(false);

  const fetchRows = useCallback(async () => {
    setLoading(true);
    try {
      const data = await lawMappingsApi.list({
        group_slug: groupFilter || undefined,
        source: sourceFilter,
        pinned: pinnedFilter,
        q: search || undefined,
      });
      setRows(data);
    } catch {
      /* silent */
    }
    setLoading(false);
  }, [groupFilter, sourceFilter, pinnedFilter, search]);

  useEffect(() => {
    fetchRows();
  }, [fetchRows]);

  async function handleDelete(id: number) {
    if (!confirm("Delete this suggestion?")) return;
    try {
      await lawMappingsApi.delete(id);
      fetchRows();
    } catch {
      /* silent */
    }
  }

  const groupSlugs = Array.from(new Set(rows.map((r) => r.group_slug).filter(Boolean))) as string[];

  function pinnedLabel(r: LawMappingRow): { text: string; ok: boolean } {
    if (r.source_ver_id) return { text: `ver ${r.source_ver_id}`, ok: true };
    if (r.celex_number) return { text: `CELEX ${r.celex_number}`, ok: true };
    return { text: "⚠ none", ok: false };
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Suggested Laws</h2>
        <button
          onClick={() => setCreating(true)}
          className="text-sm bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700"
        >
          + Add suggestion
        </button>
      </div>

      <p className="text-xs text-gray-500 mb-3">
        Curated list shown as &quot;Sugestii&quot; in the legal library. {rows.length} entries.
      </p>

      <div className="flex flex-wrap gap-3 mb-4 text-sm">
        <select
          value={groupFilter}
          onChange={(e) => setGroupFilter(e.target.value)}
          className="rounded-md border border-gray-300 px-2 py-1.5"
        >
          <option value="">All groups</option>
          {groupSlugs.map((g) => (
            <option key={g} value={g}>{g}</option>
          ))}
        </select>
        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value as "all" | "system" | "user")}
          className="rounded-md border border-gray-300 px-2 py-1.5"
        >
          <option value="all">All sources</option>
          <option value="system">System</option>
          <option value="user">User</option>
        </select>
        <select
          value={pinnedFilter}
          onChange={(e) => setPinnedFilter(e.target.value as "all" | "true" | "false")}
          className="rounded-md border border-gray-300 px-2 py-1.5"
        >
          <option value="all">All pin states</option>
          <option value="true">Pinned</option>
          <option value="false">Unpinned</option>
        </select>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search title..."
          className="rounded-md border border-gray-300 px-2 py-1.5 flex-1 min-w-[200px]"
        />
      </div>

      {loading ? (
        <div className="text-gray-400 py-4">Loading...</div>
      ) : (
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-3 py-2.5 font-semibold text-gray-600">Src</th>
                <th className="px-3 py-2.5 font-semibold text-gray-600">Group</th>
                <th className="px-3 py-2.5 font-semibold text-gray-600">Type</th>
                <th className="px-3 py-2.5 font-semibold text-gray-600">Nr</th>
                <th className="px-3 py-2.5 font-semibold text-gray-600">Year</th>
                <th className="px-3 py-2.5 font-semibold text-gray-600">Title</th>
                <th className="px-3 py-2.5 font-semibold text-gray-600">Pinned</th>
                <th className="px-3 py-2.5 font-semibold text-gray-600 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((r) => {
                const pin = pinnedLabel(r);
                return (
                  <tr key={r.id}>
                    <td className="px-3 py-2">
                      <span className={`text-xs px-1.5 py-0.5 rounded ${
                        r.source === "system"
                          ? "bg-gray-100 text-gray-600"
                          : "bg-blue-100 text-blue-700"
                      }`}>
                        {r.source}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <span className="flex items-center gap-1.5">
                        {r.group_color && (
                          <span
                            className="w-2 h-2 rounded-full inline-block"
                            style={{ backgroundColor: r.group_color }}
                          />
                        )}
                        {r.group_name}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {r.document_type ? (DOC_TYPE_LABELS[r.document_type] || r.document_type) : "—"}
                    </td>
                    <td className="px-3 py-2">{r.law_number || "—"}</td>
                    <td className="px-3 py-2">{r.law_year || "—"}</td>
                    <td className="px-3 py-2 max-w-md truncate" title={r.title}>{r.title}</td>
                    <td className="px-3 py-2 text-xs">
                      <span className={pin.ok ? "text-green-700" : "text-amber-700"}>
                        {pin.text}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        onClick={() => setEditing(r)}
                        className="text-xs text-blue-600 hover:underline mr-2"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => handleDelete(r.id)}
                        className="text-xs text-red-600 hover:underline"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {(creating || editing) && (
        <SuggestionFormModal
          mode={creating ? "create" : "edit"}
          row={editing}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={() => {
            setCreating(false);
            setEditing(null);
            fetchRows();
          }}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify the file compiles (after Task 13 creates the modal)**

Skip for now — the modal import won't resolve yet.

- [ ] **Step 3: Don't commit yet**

We'll commit Tasks 11, 12, 13 together at the end of Task 13 once everything builds.

---

## Task 13: Suggestion form modal

**Files:**
- Create: `frontend/src/app/settings/suggestions/suggestion-form-modal.tsx`

- [ ] **Step 1: Fetch the categories list (we need it for the dropdowns)**

Check whether `/api/settings/categories` already returns categories with group info — yes (verified during planning). The existing `apiFetch<{...}[]>("/api/settings/categories")` call from `categories-table.tsx` returns rows with `id`, `slug`, `name_en`, `group_slug`, `group_name`, `group_color`. Reuse the same endpoint.

- [ ] **Step 2: Create the modal**

```typescript
// frontend/src/app/settings/suggestions/suggestion-form-modal.tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { apiFetch, lawMappingsApi, LawMappingRow, ProbeUrlResult, CreateMappingPayload } from "@/lib/api";

interface CategoryRow {
  id: number;
  slug: string;
  name_en: string;
  group_slug: string;
  group_name: string;
  group_color: string;
}

const DOC_TYPES = [
  { value: "law", label: "LEGE" },
  { value: "emergency_ordinance", label: "ORDONANȚĂ DE URGENȚĂ" },
  { value: "government_ordinance", label: "ORDONANȚĂ" },
  { value: "government_resolution", label: "HOTĂRÂRE" },
  { value: "decree", label: "DECRET" },
  { value: "constitution", label: "CONSTITUȚIE" },
  { value: "code", label: "COD" },
  { value: "regulation", label: "REGULAMENT (UE)" },
  { value: "directive", label: "DIRECTIVĂ (UE)" },
];

interface Props {
  mode: "create" | "edit";
  row: LawMappingRow | null;
  onClose: () => void;
  onSaved: () => void;
}

export function SuggestionFormModal({ mode, row, onClose, onSaved }: Props) {
  const [categories, setCategories] = useState<CategoryRow[]>([]);
  const [groupSlug, setGroupSlug] = useState<string>(row?.group_slug || "");
  const [categoryId, setCategoryId] = useState<number | "">(row?.category_id || "");
  const [docType, setDocType] = useState<string>(row?.document_type || "");
  const [lawNumber, setLawNumber] = useState<string>(row?.law_number || "");
  const [lawYear, setLawYear] = useState<string>(row?.law_year ? String(row.law_year) : "");
  const [title, setTitle] = useState<string>(row?.title || "");
  const [sourceUrl, setSourceUrl] = useState<string>(row?.source_url || "");
  const [probe, setProbe] = useState<ProbeUrlResult | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<CategoryRow[]>("/api/settings/categories").then(setCategories).catch(() => { /* silent */ });
  }, []);

  // Initial probe for edit mode
  useEffect(() => {
    if (row?.source_url) {
      lawMappingsApi.probeUrl(row.source_url).then(setProbe).catch(() => { /* silent */ });
    }
  }, [row]);

  // Debounced probe when URL changes
  const runProbe = useCallback(async (url: string) => {
    if (!url.trim()) {
      setProbe(null);
      return;
    }
    try {
      setProbe(await lawMappingsApi.probeUrl(url));
    } catch {
      setProbe(null);
    }
  }, []);

  useEffect(() => {
    const handle = setTimeout(() => runProbe(sourceUrl), 400);
    return () => clearTimeout(handle);
  }, [sourceUrl, runProbe]);

  const filteredCategories = groupSlug
    ? categories.filter((c) => c.group_slug === groupSlug)
    : categories;
  const groupSlugs = Array.from(new Set(categories.map((c) => c.group_slug)));

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (categoryId === "" || !title.trim()) {
      setError("Category and title are required");
      return;
    }
    setSaving(true);
    setError(null);
    const payload: CreateMappingPayload = {
      category_id: Number(categoryId),
      title: title.trim(),
      law_number: lawNumber.trim() || null,
      law_year: lawYear ? Number(lawYear) : null,
      document_type: docType || null,
      source_url: sourceUrl.trim() || null,
      source_ver_id: probe?.kind === "ro" ? probe.identifier : null,
      celex_number: probe?.kind === "eu" ? probe.identifier : null,
    };
    try {
      if (mode === "create") {
        await lawMappingsApi.create(payload);
      } else if (row) {
        await lawMappingsApi.patch(row.id, payload);
      }
      onSaved();
    } catch (err) {
      setError((err as Error).message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <form
        onSubmit={handleSave}
        className="bg-white rounded-lg shadow-xl max-w-lg w-full max-h-[90vh] overflow-y-auto"
      >
        <div className="p-5 border-b">
          <h3 className="text-lg font-semibold">
            {mode === "create" ? "Add suggestion" : "Edit suggestion"}
          </h3>
        </div>

        <div className="p-5 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <label className="text-sm">
              <div className="text-xs font-semibold text-gray-600 mb-1">Group</div>
              <select
                value={groupSlug}
                onChange={(e) => {
                  setGroupSlug(e.target.value);
                  setCategoryId("");
                }}
                className="w-full rounded-md border border-gray-300 px-2 py-2 bg-white"
              >
                <option value="">Select...</option>
                {groupSlugs.map((g) => (
                  <option key={g} value={g}>{g}</option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <div className="text-xs font-semibold text-gray-600 mb-1">Category</div>
              <select
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : "")}
                required
                className="w-full rounded-md border border-gray-300 px-2 py-2 bg-white"
              >
                <option value="">Select...</option>
                {filteredCategories.map((c) => (
                  <option key={c.id} value={c.id}>{c.name_en}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <label className="text-sm col-span-2">
              <div className="text-xs font-semibold text-gray-600 mb-1">Document type</div>
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-2 py-2 bg-white"
              >
                <option value="">—</option>
                {DOC_TYPES.map((d) => (
                  <option key={d.value} value={d.value}>{d.label}</option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <div className="text-xs font-semibold text-gray-600 mb-1">Year</div>
              <input
                type="number"
                value={lawYear}
                onChange={(e) => setLawYear(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-2 py-2"
              />
            </label>
          </div>

          <label className="text-sm block">
            <div className="text-xs font-semibold text-gray-600 mb-1">Number</div>
            <input
              type="text"
              value={lawNumber}
              onChange={(e) => setLawNumber(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-2 py-2"
            />
          </label>

          <label className="text-sm block">
            <div className="text-xs font-semibold text-gray-600 mb-1">Title</div>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              className="w-full rounded-md border border-gray-300 px-2 py-2"
            />
          </label>

          <div className="border-t pt-3 mt-2">
            <div className="text-xs font-semibold text-gray-600 mb-1">
              Pin to source (recommended)
            </div>
            <input
              type="text"
              value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
              placeholder="Paste a legislatie.just.ro or eur-lex.europa.eu URL"
              className="w-full rounded-md border border-gray-300 px-2 py-2 text-sm"
            />
            {probe && (
              <div className="mt-1.5 text-xs">
                {probe.error ? (
                  <span className="text-amber-700">⚠ {probe.error}</span>
                ) : probe.kind === "ro" ? (
                  <span className="text-green-700">✓ Detected ver_id {probe.identifier}</span>
                ) : probe.kind === "eu" ? (
                  <span className="text-green-700">✓ Detected CELEX {probe.identifier}</span>
                ) : null}
              </div>
            )}
          </div>

          {error && <div className="text-xs text-red-600">{error}</div>}
        </div>

        <div className="p-5 border-t flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-gray-600 px-3 py-1.5"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="text-sm bg-blue-600 text-white px-3 py-1.5 rounded-md disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}
```

- [ ] **Step 3: Type-check the frontend**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors related to the new files.

- [ ] **Step 4: Manual smoke test**

Run: `cd frontend && npm run dev`

Visit `http://localhost:3000/settings?tab=suggestions`. Verify:
1. The table loads with seeded rows (all marked `system`)
2. Filters work (group, source, pinned, search)
3. Click "+ Add suggestion" → modal opens → fill in fields → paste a legislatie.just URL → see "✓ Detected ver_id ..." → Save → row appears in table marked `user`
4. Click Edit on a `system` row → change the title → Save → row's source flips to `user`
5. Click Delete → confirms → row disappears
6. Paste an EUR-Lex URL in the modal → see "✓ Detected CELEX ..."
7. Paste an unknown URL → see "⚠ URL host not recognized"

- [ ] **Step 5: Commit Tasks 11, 12, 13 together**

```bash
git add frontend/src/app/settings/settings-tabs.tsx \
        frontend/src/app/settings/page.tsx \
        frontend/src/app/settings/suggestions/suggestions-table.tsx \
        frontend/src/app/settings/suggestions/suggestion-form-modal.tsx
git commit -m "feat(frontend): add Settings → Suggestions tab with CRUD and URL pinning"
```

---

## Task 14: End-to-end verification

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all tests pass, including the new ones from Tasks 1, 4-9. Any pre-existing failures unrelated to this work are acceptable but should be noted in the PR.

- [ ] **Step 2: Run the full frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Manual end-to-end import test**

With the dev server running:
1. In Settings → Suggestions, edit a real seeded row (e.g., "Codul Civil") and paste its real legislatie.just.ro URL. Save.
2. Confirm the row is now marked `user` and shows `ver <id>` in the Pinned column.
3. Go to the Laws library, find that suggestion in the "Sugestii" section, click "+ Importa" → Current version only.
4. Confirm the import succeeds and the imported law title matches the pinned ver_id.
5. Optional: tail backend logs and confirm `advanced_search` was NOT called for this import.

- [ ] **Step 4: Final commit (if any docs or CHANGELOG updates)**

If the project tracks notable changes anywhere (CHANGELOG.md, release notes), add an entry. Otherwise skip.
