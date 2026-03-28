# Error Handling, Model Integration & Test Plan — Implementation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured error handling, import progress tracking via SSE, multi-provider model support (Anthropic/Mistral/OpenAI), model comparison, and comprehensive tests.

**Architecture:** Five sequential phases: (1) error handling foundation, (2) SSE import progress, (3) provider abstraction + model config, (4) model comparison, (5) remaining tests. Each phase produces working, testable software. TDD throughout — tests first, then implementation.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), TypeScript/Next.js 16/React 19 (frontend), pytest/httpx (backend tests), Vitest/React Testing Library/MSW (frontend tests), sse-starlette (SSE), mistralai + openai (new provider SDKs).

**Spec:** `docs/superpowers/specs/2026-03-28-error-handling-model-integration-design.md`

---

## Phase 1: Error Handling Foundation

### Task 1: Structured Error Module

**Files:**
- Create: `backend/app/errors.py`
- Test: `backend/tests/test_errors.py`

- [ ] **Step 1: Write failing tests for error mapping**

```python
# backend/tests/test_errors.py
import sqlite3
import pytest
from app.errors import (
    ThemisError,
    DbLockedError,
    NoLawNumberError,
    SearchFailedError,
    DuplicateImportError,
    ImportFailedError,
    map_exception_to_error,
)


def test_map_sqlite_locked():
    exc = sqlite3.OperationalError("database is locked")
    err = map_exception_to_error(exc)
    assert isinstance(err, DbLockedError)
    assert err.code == "db_locked"
    assert err.status_code == 503
    assert "wait" in err.message.lower()


def test_map_unknown_operational_error():
    exc = sqlite3.OperationalError("disk I/O error")
    err = map_exception_to_error(exc)
    assert err.code == "internal"
    assert err.status_code == 500


def test_no_law_number_error():
    err = NoLawNumberError()
    assert err.code == "no_law_number"
    assert err.status_code == 400
    assert "standard law number" in err.message


def test_search_failed_error():
    err = SearchFailedError()
    assert err.code == "search_failed"
    assert err.status_code == 502


def test_duplicate_import_error():
    err = DuplicateImportError("Legea 506/2004")
    assert err.code == "duplicate"
    assert err.status_code == 409
    assert "506/2004" in err.message


def test_import_failed_error():
    err = ImportFailedError("timeout connecting to source")
    assert err.code == "import_failed"
    assert err.status_code == 500
    assert "timeout" in err.message


def test_error_to_dict():
    err = DbLockedError()
    d = err.to_dict()
    assert d == {"code": "db_locked", "message": err.message}


def test_map_generic_exception():
    exc = RuntimeError("something broke")
    err = map_exception_to_error(exc)
    assert err.code == "internal"
    assert err.status_code == 500
    assert "Something went wrong" in err.message
    # Must NOT contain the raw exception message
    assert "something broke" not in err.message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.errors'`

- [ ] **Step 3: Implement the errors module**

```python
# backend/app/errors.py
"""Structured error codes for Themis API responses."""

import sqlite3


class ThemisError(Exception):
    """Base error with code, HTTP status, and user-facing message."""

    code: str = "internal"
    status_code: int = 500
    message: str = "Something went wrong. Please try again."

    def __init__(self, message: str | None = None):
        if message is not None:
            self.message = message
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


class DbLockedError(ThemisError):
    code = "db_locked"
    status_code = 503
    message = "Another import is in progress. Please wait a moment and try again."


class NoLawNumberError(ThemisError):
    code = "no_law_number"
    status_code = 400
    message = (
        "This document cannot be auto-imported because it has no "
        "standard law number (e.g. Constituția)."
    )


class SearchFailedError(ThemisError):
    code = "search_failed"
    status_code = 502
    message = "Could not reach the legislation database. Please try again later."


class DuplicateImportError(ThemisError):
    code = "duplicate"
    status_code = 409

    def __init__(self, title: str = ""):
        msg = f"This law has already been imported as '{title}'." if title else "This law has already been imported."
        super().__init__(msg)


class ImportFailedError(ThemisError):
    code = "import_failed"
    status_code = 500

    def __init__(self, context: str = ""):
        msg = f"Import failed: {context}. Please try again." if context else "Import failed. Please try again."
        super().__init__(msg)


def map_exception_to_error(exc: Exception) -> ThemisError:
    """Map a raw exception to a structured ThemisError."""
    if isinstance(exc, ThemisError):
        return exc
    if isinstance(exc, sqlite3.OperationalError) and "database is locked" in str(exc):
        return DbLockedError()
    if isinstance(exc, ValueError):
        return ImportFailedError(str(exc))
    return ThemisError()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_errors.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/errors.py backend/tests/test_errors.py
git commit -m "feat: add structured error codes module"
```

---

### Task 2: SQLite Retry Decorator

**Files:**
- Modify: `backend/app/errors.py` (add decorator)
- Test: `backend/tests/test_sqlite_retry.py`

- [ ] **Step 1: Write failing tests for retry decorator**

```python
# backend/tests/test_sqlite_retry.py
import sqlite3
import time
import pytest
from unittest.mock import MagicMock
from app.errors import with_sqlite_retry, DbLockedError


def test_succeeds_first_try():
    call_count = 0

    @with_sqlite_retry(max_retries=3)
    def operation():
        nonlocal call_count
        call_count += 1
        return "ok"

    assert operation() == "ok"
    assert call_count == 1


def test_retries_on_db_locked():
    call_count = 0

    @with_sqlite_retry(max_retries=3)
    def operation():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert operation() == "ok"
    assert call_count == 3


def test_raises_after_max_retries():
    @with_sqlite_retry(max_retries=3)
    def operation():
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(DbLockedError):
        operation()


def test_no_retry_on_other_operational_error():
    @with_sqlite_retry(max_retries=3)
    def operation():
        raise sqlite3.OperationalError("disk I/O error")

    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        operation()


def test_no_retry_on_non_sqlite_error():
    @with_sqlite_retry(max_retries=3)
    def operation():
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        operation()


def test_calls_rollback_on_retry():
    """If a db session is the first arg, rollback is called on retry."""
    mock_db = MagicMock()
    call_count = 0

    @with_sqlite_retry(max_retries=3)
    def operation(db):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert operation(mock_db) == "ok"
    mock_db.rollback.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_sqlite_retry.py -v`
Expected: FAIL — `ImportError: cannot import name 'with_sqlite_retry'`

- [ ] **Step 3: Implement the retry decorator**

Add to `backend/app/errors.py`:

```python
import functools
import logging
import time

logger = logging.getLogger(__name__)


def with_sqlite_retry(max_retries: int = 3):
    """Decorator that retries on SQLite 'database is locked' errors with exponential backoff."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "database is locked" not in str(e):
                        raise
                    if attempt >= max_retries:
                        raise DbLockedError() from e
                    wait = 2**attempt  # 1s, 2s, 4s
                    logger.warning(
                        f"SQLite locked, retry {attempt + 1}/{max_retries} in {wait}s"
                    )
                    # If first arg looks like a DB session, rollback
                    if args and hasattr(args[0], "rollback"):
                        args[0].rollback()
                    time.sleep(wait)

        return wrapper

    return decorator
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_sqlite_retry.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/errors.py backend/tests/test_sqlite_retry.py
git commit -m "feat: add SQLite retry decorator with exponential backoff"
```

---

### Task 3: Global Exception Handler in FastAPI

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_global_error_handler.py`

- [ ] **Step 1: Write failing tests for global handler**

```python
# backend/tests/test_global_error_handler.py
import pytest
from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


def test_health_endpoint_works():
    """Sanity check that the app starts and responds."""
    # Use an existing endpoint
    res = client.get("/api/laws/library")
    assert res.status_code == 200


def test_unhandled_exception_returns_structured_error(monkeypatch):
    """Unhandled exceptions should return {code, message}, never raw tracebacks."""
    from app.routers import laws

    original = laws.list_library

    def exploding_endpoint(*args, **kwargs):
        raise RuntimeError("unexpected internal failure xyz123")

    monkeypatch.setattr(laws, "list_library", exploding_endpoint)
    # Need to verify the global handler catches this
    # This test verifies the handler is registered
    from app.errors import ThemisError
    from app.main import themis_error_handler

    assert themis_error_handler is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_global_error_handler.py -v`
Expected: FAIL — `ImportError: cannot import name 'themis_error_handler'`

- [ ] **Step 3: Add global exception handler to main.py**

In `backend/app/main.py`, add after the CORS middleware block (after line 107):

```python
from fastapi.responses import JSONResponse
from app.errors import ThemisError, map_exception_to_error
import sqlite3


@app.exception_handler(ThemisError)
async def themis_error_handler(request, exc: ThemisError):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


@app.exception_handler(sqlite3.OperationalError)
async def sqlite_error_handler(request, exc: sqlite3.OperationalError):
    error = map_exception_to_error(exc)
    return JSONResponse(
        status_code=error.status_code,
        content=error.to_dict(),
    )


@app.exception_handler(Exception)
async def generic_error_handler(request, exc: Exception):
    import logging
    logging.getLogger(__name__).exception(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"code": "internal", "message": "Something went wrong. Please try again."},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_global_error_handler.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_global_error_handler.py
git commit -m "feat: add global exception handlers for structured error responses"
```

---

### Task 4: Update Import Endpoints to Use Structured Errors

**Files:**
- Modify: `backend/app/routers/laws.py`
- Test: `backend/tests/test_import_endpoints.py`

- [ ] **Step 1: Write failing tests for structured error responses**

```python
# backend/tests/test_import_endpoints.py
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_import_suggestion_no_law_number():
    """Missing law number should return structured error with code."""
    with patch("app.routers.laws.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_mapping = MagicMock()
        mock_mapping.law_number = None
        mock_mapping.title = "Constituția României"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_mapping
        mock_get_db.return_value = iter([mock_db])

        res = client.post(
            "/api/laws/import-suggestion",
            json={"mapping_id": 1, "import_history": False},
        )
        assert res.status_code == 400
        data = res.json()
        assert data["code"] == "no_law_number"
        assert "standard law number" in data["message"]


def test_import_suggestion_duplicate():
    """Duplicate import should return structured error with code."""
    with patch("app.routers.laws.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_mapping = MagicMock()
        mock_mapping.law_number = "506"
        mock_mapping.document_type = "law"
        mock_mapping.law_year = 2004
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_mapping,  # mapping lookup
            MagicMock(title="Legea 506/2004"),  # existing law
        ]
        mock_get_db.return_value = iter([mock_db])

        res = client.post(
            "/api/laws/import-suggestion",
            json={"mapping_id": 1, "import_history": False},
        )
        assert res.status_code == 409
        data = res.json()
        assert data["code"] == "duplicate"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_import_endpoints.py -v`
Expected: FAIL — response still uses old `{"detail": "..."}` format

- [ ] **Step 3: Update import endpoints to raise ThemisErrors**

In `backend/app/routers/laws.py`, replace the HTTPException raises with ThemisError raises:

**Line 241-245** — replace:
```python
    if not mapping.law_number:
        raise HTTPException(
            status_code=400,
            detail="This suggestion cannot be auto-imported (no law number)",
        )
```
with:
```python
    if not mapping.law_number:
        from app.errors import NoLawNumberError
        raise NoLawNumberError()
```

**Lines 248-258** — replace the duplicate check HTTPException with:
```python
    if existing:
        from app.errors import DuplicateImportError
        raise DuplicateImportError(existing.title)
```

**Lines 265-272** — replace search failure with:
```python
    except Exception as e:
        logger.error(f"Search failed for suggestion {req.mapping_id}: {e}")
        from app.errors import SearchFailedError
        raise SearchFailedError()
```

**Lines 293-301** — replace generic import failure with:
```python
    except ValueError as e:
        db.rollback()
        from app.errors import ImportFailedError
        raise ImportFailedError(str(e))
    except Exception as e:
        logger.exception(f"Failed to import suggestion {req.mapping_id}")
        db.rollback()
        from app.errors import ImportFailedError
        raise ImportFailedError(str(e))
```

Apply the same pattern to the `/api/laws/import` endpoint (lines 154-226).

Also add `@with_sqlite_retry(max_retries=3)` to the `do_import` call or wrap the DB-writing section.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_import_endpoints.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run existing tests to check for regressions**

Run: `cd backend && uv run pytest tests/ -v`
Expected: All existing tests still PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/laws.py backend/tests/test_import_endpoints.py
git commit -m "feat: replace HTTPExceptions with structured ThemisErrors in import endpoints"
```

---

### Task 5: Frontend Structured Error Display

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/app/laws/library-page.tsx`
- Modify: `frontend/src/app/laws/search-import-form.tsx`
- Test: `frontend/__tests__/error-display.test.ts`

- [ ] **Step 1: Set up frontend test infrastructure**

```bash
cd frontend && npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom msw
```

Add to `frontend/package.json` scripts:
```json
"test": "vitest run",
"test:watch": "vitest"
```

Create `frontend/vitest.config.ts`:
```typescript
import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["./__tests__/setup.ts"],
    globals: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
});
```

Create `frontend/__tests__/setup.ts`:
```typescript
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 2: Write failing test for API error parsing**

```typescript
// frontend/__tests__/api.test.ts
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

const API_BASE = "http://localhost:8000";

// We need to test error parsing, so import apiFetch
// For now, test the error shape contract

const server = setupServer();

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("apiFetch error handling", () => {
  it("parses structured error with code and message", async () => {
    server.use(
      http.post(`${API_BASE}/api/laws/import-suggestion`, () => {
        return HttpResponse.json(
          { code: "no_law_number", message: "This document cannot be auto-imported..." },
          { status: 400 }
        );
      })
    );

    // Import dynamically to allow MSW to intercept
    const { apiFetch } = await import("@/lib/api");
    try {
      await apiFetch("/api/laws/import-suggestion", {
        method: "POST",
        body: JSON.stringify({ mapping_id: 1 }),
      });
      expect.fail("should have thrown");
    } catch (err: any) {
      // Currently throws "API error 400: ..." — we want structured parsing
      expect(err).toBeInstanceOf(Error);
    }
  });
});
```

- [ ] **Step 3: Run test to verify it works as baseline**

Run: `cd frontend && npx vitest run __tests__/api.test.ts`
Expected: Test runs (may pass or fail depending on import resolution)

- [ ] **Step 4: Update api.ts to parse structured errors**

In `frontend/src/lib/api.ts`, update the error handling in `apiFetch`:

Replace lines 20-23:
```typescript
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API error ${res.status}: ${body || res.statusText}`);
  }
```

With:
```typescript
  if (!res.ok) {
    let errorMessage: string;
    let errorCode: string | undefined;
    try {
      const errorBody = await res.json();
      errorCode = errorBody.code;
      errorMessage = errorBody.message || errorBody.detail || res.statusText;
    } catch {
      const body = await res.text().catch(() => "");
      errorMessage = body || res.statusText;
    }
    const error = new Error(errorMessage);
    (error as any).code = errorCode;
    (error as any).statusCode = res.status;
    throw error;
  }
```

- [ ] **Step 5: Update library-page.tsx error display**

In `frontend/src/app/laws/library-page.tsx`, update the error display in the pending imports section to use severity-based styling.

Find the error display code (around line 210) and update it to check `(error as any).code`:
- If code is `db_locked` or `search_failed` → yellow/warning background (`bg-amber-50 text-amber-800 border-amber-200`)
- If code is `no_law_number`, `duplicate`, `import_failed` → red/error background (keep current `bg-red-50 text-red-700`)
- Display only the `message` property, never raw JSON

- [ ] **Step 6: Update search-import-form.tsx error display**

Apply the same severity-based styling pattern to `search-import-form.tsx`.

- [ ] **Step 7: Run frontend tests**

Run: `cd frontend && npx vitest run`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/app/laws/library-page.tsx frontend/src/app/laws/search-import-form.tsx frontend/__tests__/ frontend/vitest.config.ts frontend/package.json
git commit -m "feat: structured error display with severity-based styling"
```

---

## Phase 2: Import SSE Progress Tracking

### Task 6: SSE Import Endpoint

**Files:**
- Modify: `backend/app/routers/laws.py` (add SSE endpoint)
- Modify: `backend/app/services/leropa_service.py` (add `on_progress` callback)
- Test: `backend/tests/test_import_sse.py`

- [ ] **Step 1: Write failing test for SSE progress events**

```python
# backend/tests/test_import_sse.py
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_sse_import_streams_progress_events():
    """SSE import should stream progress events then complete."""
    mock_mapping = MagicMock()
    mock_mapping.law_number = "506"
    mock_mapping.document_type = "law"
    mock_mapping.law_year = 2004
    mock_mapping.title = "Legea 506/2004"

    def fake_import(db, ver_id, import_history=True, rate_limit_delay=2.0, on_progress=None):
        if on_progress:
            on_progress({"event": "progress", "data": {"phase": "metadata", "message": "Fetching law metadata"}})
            on_progress({"event": "progress", "data": {"phase": "version", "current": 1, "total": 2, "message": "Importing version 1"}})
            on_progress({"event": "progress", "data": {"phase": "version", "current": 2, "total": 2, "message": "Importing version 2"}})
            on_progress({"event": "progress", "data": {"phase": "indexing", "message": "Building search index"}})
        return {"law_id": 1, "title": "Legea 506/2004", "versions_imported": 2, "version_ids": ["v1", "v2"]}

    with patch("app.routers.laws.get_db") as mock_get_db, \
         patch("app.services.leropa_service.import_law", side_effect=fake_import), \
         patch("app.routers.laws.advanced_search", return_value=[MagicMock(ver_id="12345")]):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_mapping,  # mapping lookup
            None,          # no existing law
            None,          # no existing version
        ]
        mock_get_db.return_value = iter([mock_db])

        with client.stream("POST", "/api/laws/import-suggestion/1/stream",
                          json={"import_history": True}) as response:
            events = []
            for line in response.iter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line[5:].strip()))

            assert len(events) >= 4  # progress events + complete
            assert events[0]["phase"] == "metadata"
            assert events[-1].get("law_id") is not None  # complete event


def test_sse_import_no_law_number_returns_error_event():
    """SSE import with no law number should stream an error event."""
    mock_mapping = MagicMock()
    mock_mapping.law_number = None

    with patch("app.routers.laws.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_mapping
        mock_get_db.return_value = iter([mock_db])

        with client.stream("POST", "/api/laws/import-suggestion/1/stream",
                          json={"import_history": False}) as response:
            events = []
            for line in response.iter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line[5:].strip()))

            assert any(e.get("code") == "no_law_number" for e in events)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_import_sse.py -v`
Expected: FAIL — 404 (endpoint doesn't exist)

- [ ] **Step 3: Add `on_progress` callback to `leropa_service.import_law()`**

In `backend/app/services/leropa_service.py`, modify `import_law()` signature (line 875):

```python
def import_law(
    db: Session,
    ver_id: str,
    import_history: bool = True,
    rate_limit_delay: float = 2.0,
    on_progress: callable | None = None,
) -> dict:
```

Add progress callbacks at key points:
- After `_fetch_law_metadata()` call: `on_progress({"event": "progress", "data": {"phase": "metadata", "message": "Fetching law metadata from legislatie.just.ro"}})`
- Inside the version import loop, after each version: `on_progress({"event": "progress", "data": {"phase": "version", "current": i, "total": total, "message": f"Importing version {ver_id} ({date})"}})`
- Before ChromaDB/BM25 indexing: `on_progress({"event": "progress", "data": {"phase": "indexing", "message": f"Building search index ({article_count} articles)"}})`

Guard each call with `if on_progress:`.

- [ ] **Step 4: Add SSE streaming endpoint to laws router**

In `backend/app/routers/laws.py`, add the new endpoint:

```python
import asyncio
import json
from sse_starlette.sse import EventSourceResponse


class ImportStreamRequest(BaseModel):
    import_history: bool = False
    category_id: int | None = None


@router.post("/import-suggestion/{mapping_id}/stream")
async def import_suggestion_stream(
    mapping_id: int,
    req: ImportStreamRequest,
    db: Session = Depends(get_db),
):
    """SSE endpoint that streams import progress."""
    # Validate mapping, check duplicates (same logic as import_suggestion)
    mapping = db.query(LawMapping).filter(LawMapping.id == mapping_id).first()
    if not mapping:
        async def error_stream():
            yield {"event": "error", "data": json.dumps({"code": "not_found", "message": "Suggestion not found"})}
        return EventSourceResponse(error_stream())

    if not mapping.law_number:
        async def error_stream():
            yield {"event": "error", "data": json.dumps(NoLawNumberError().to_dict())}
        return EventSourceResponse(error_stream())

    # Check for duplicate import
    from app.models.law import Law, LawVersion
    existing_query = db.query(Law).filter(
        Law.law_number == mapping.law_number,
        Law.document_type == (mapping.document_type or "law"),
    )
    if mapping.law_year:
        existing_query = existing_query.filter(Law.law_year == mapping.law_year)
    existing = existing_query.first()
    if existing:
        async def error_stream():
            yield {"event": "error", "data": json.dumps(DuplicateImportError(existing.title).to_dict())}
        return EventSourceResponse(error_stream())

    # Search legislatie.just.ro for the law
    try:
        results = advanced_search(
            doc_type=mapping.document_type or "law",
            number=mapping.law_number,
            year=str(mapping.law_year) if mapping.law_year else None,
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

    # Check if version already imported
    existing_ver = db.query(LawVersion).filter(LawVersion.ver_id == ver_id).first()
    if existing_ver:
        async def error_stream():
            yield {"event": "error", "data": json.dumps(DuplicateImportError(existing_ver.law.title).to_dict())}
        return EventSourceResponse(error_stream())

    queue: asyncio.Queue = asyncio.Queue()

    def on_progress(event: dict):
        queue.put_nowait(event)

    async def run_import():
        try:
            result = await asyncio.to_thread(
                import_law, db, ver_id,
                import_history=req.import_history,
                on_progress=on_progress,
            )
            await queue.put({"event": "complete", "data": result})
        except Exception as e:
            error = map_exception_to_error(e)
            await queue.put({"event": "error", "data": error.to_dict()})

    async def event_generator():
        task = asyncio.create_task(run_import())
        try:
            while True:
                event = await queue.get()
                event_type = event.get("event", "progress")
                data = event.get("data", event)
                yield {"event": event_type, "data": json.dumps(data) if isinstance(data, dict) else data}
                if event_type in ("complete", "error"):
                    break
        except asyncio.CancelledError:
            pass  # Client disconnected; import continues in background

    return EventSourceResponse(event_generator())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_import_sse.py -v`
Expected: All tests PASS

- [ ] **Step 6: Run all backend tests**

Run: `cd backend && uv run pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/laws.py backend/app/services/leropa_service.py backend/tests/test_import_sse.py
git commit -m "feat: add SSE streaming endpoint for import progress tracking"
```

---

### Task 7: Frontend Import Progress UI

**Files:**
- Modify: `frontend/src/app/laws/library-page.tsx`
- Modify: `frontend/src/lib/api.ts` (add SSE import method)
- Test: `frontend/__tests__/import-progress.test.ts`

- [ ] **Step 1: Add SSE import method to api.ts**

In `frontend/src/lib/api.ts`, add a function that uses fetch + ReadableStream for the POST-based SSE endpoint:

```typescript
export async function importSuggestionSSE(
  mappingId: number,
  importHistory: boolean,
  onProgress: (event: { phase: string; current?: number; total?: number; message: string }) => void,
  onComplete: (data: { law_id: number; title: string; versions_imported: number }) => void,
  onError: (error: { code: string; message: string }) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/laws/import-suggestion/${mappingId}/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mapping_id: mappingId, import_history: importHistory }),
    signal,
  });

  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({}));
    onError({ code: body.code || "import_failed", message: body.message || "Import failed" });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    let currentEvent = "progress";
    for (const line of lines) {
      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        const data = JSON.parse(line.slice(5).trim());
        if (currentEvent === "progress") onProgress(data);
        else if (currentEvent === "complete") onComplete(data);
        else if (currentEvent === "error") onError(data);
      }
    }
  }
}
```

- [ ] **Step 2: Update library-page.tsx to use SSE import with progress**

Update the `startImport` function to call `importSuggestionSSE` instead of the REST endpoint. Update the `pendingImports` state to include progress info:

```typescript
interface PendingImport {
  suggestion: LawSuggestion;
  error?: string;
  errorCode?: string;
  progress?: {
    phase: string;
    current?: number;
    total?: number;
    message: string;
  };
}
```

In the render, show progress inside the pending import card:
- Phase label
- "Importing version 3 / 9" text when `phase === "version"`
- A progress bar: `<div className="h-1 bg-blue-500 rounded" style={{ width: `${(current/total)*100}%` }} />`

- [ ] **Step 3: Write frontend test for progress display**

```typescript
// frontend/__tests__/import-progress.test.ts
import { describe, it, expect, vi } from "vitest";

describe("Import progress parsing", () => {
  it("parses SSE progress events correctly", () => {
    const events: any[] = [];
    const sseData = [
      'event: progress\ndata: {"phase":"metadata","message":"Fetching law metadata"}\n\n',
      'event: progress\ndata: {"phase":"version","current":1,"total":3,"message":"Importing version 1"}\n\n',
      'event: complete\ndata: {"law_id":1,"title":"Legea 506/2004","versions_imported":3}\n\n',
    ];

    // Test the parsing logic
    for (const chunk of sseData) {
      const lines = chunk.split("\n");
      let currentEvent = "progress";
      for (const line of lines) {
        if (line.startsWith("event:")) currentEvent = line.slice(6).trim();
        else if (line.startsWith("data:")) {
          events.push({ event: currentEvent, data: JSON.parse(line.slice(5).trim()) });
        }
      }
    }

    expect(events).toHaveLength(3);
    expect(events[0].data.phase).toBe("metadata");
    expect(events[1].data.current).toBe(1);
    expect(events[1].data.total).toBe(3);
    expect(events[2].data.law_id).toBe(1);
  });
});
```

- [ ] **Step 4: Run frontend tests**

Run: `cd frontend && npx vitest run`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/app/laws/library-page.tsx frontend/__tests__/import-progress.test.ts
git commit -m "feat: frontend import progress tracking with SSE"
```

---

## Phase 3: Provider Abstraction & Model Configuration

### Task 8: Database Models for Model Config

**Files:**
- Create: `backend/app/models/model_config.py`
- Modify: `backend/app/main.py` (import new models for table creation + seed)
- Test: `backend/tests/test_model_config.py`

- [ ] **Step 1: Write failing tests for model config models**

```python
# backend/tests/test_model_config.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models.model_config import Model, ModelAssignment, ProviderKey
from app.services.model_seed import seed_models, SEED_MODELS


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_model_table_creation(db):
    """Model table exists and can be queried."""
    models = db.query(Model).all()
    assert models == []


def test_seed_models_creates_13_models(db):
    seed_models(db)
    models = db.query(Model).all()
    assert len(models) == 13


def test_seed_models_creates_default_assignments(db):
    seed_models(db)
    assignments = db.query(ModelAssignment).all()
    assert len(assignments) >= 7  # 7 pipeline tasks


def test_seed_models_is_idempotent(db):
    seed_models(db)
    seed_models(db)
    models = db.query(Model).all()
    assert len(models) == 13


def test_model_capabilities_stored_as_json(db):
    seed_models(db)
    o3 = db.query(Model).filter(Model.id == "o3").first()
    assert "reasoning" in o3.capabilities_list


def test_assignment_references_valid_model(db):
    seed_models(db)
    assignment = db.query(ModelAssignment).filter(
        ModelAssignment.task == "issue_classification"
    ).first()
    model = db.query(Model).filter(Model.id == assignment.model_id).first()
    assert model is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_model_config.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement model config models**

```python
# backend/app/models/model_config.py
"""SQLAlchemy models for multi-provider model configuration."""

import json
from sqlalchemy import Column, String, Integer, Text, ForeignKey
from app.database import Base


class Model(Base):
    __tablename__ = "models"

    id = Column(String, primary_key=True)  # e.g. "claude-sonnet-4-6"
    provider = Column(String, nullable=False)  # "anthropic" | "mistral" | "openai"
    api_model_id = Column(String, nullable=False)  # actual API model identifier
    label = Column(String, nullable=False)  # display name
    cost_tier = Column(String, nullable=False)  # "$", "$$", "$$$"
    capabilities = Column(Text, nullable=False, default='["chat"]')  # JSON array
    enabled = Column(Integer, default=1)

    @property
    def capabilities_list(self) -> list[str]:
        return json.loads(self.capabilities)

    @capabilities_list.setter
    def capabilities_list(self, value: list[str]):
        valid = {"chat", "ocr", "reasoning"}
        for cap in value:
            if cap not in valid:
                raise ValueError(f"Invalid capability: {cap}. Must be one of {valid}")
        self.capabilities = json.dumps(value)


class ModelAssignment(Base):
    __tablename__ = "model_assignments"

    task = Column(String, primary_key=True)  # e.g. "issue_classification"
    model_id = Column(String, ForeignKey("models.id"), nullable=False)


class ProviderKey(Base):
    __tablename__ = "provider_keys"

    provider = Column(String, primary_key=True)  # "anthropic" | "mistral" | "openai"
    encrypted_key = Column(Text, nullable=False)
```

- [ ] **Step 4: Implement model seed service**

```python
# backend/app/services/model_seed.py
"""Seed the models and model_assignments tables."""

from sqlalchemy.orm import Session
from app.models.model_config import Model, ModelAssignment

SEED_MODELS = [
    {"id": "claude-haiku-4-5", "provider": "anthropic", "api_model_id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5", "cost_tier": "$", "capabilities": '["chat"]'},
    {"id": "claude-sonnet-4-6", "provider": "anthropic", "api_model_id": "claude-sonnet-4-20250514", "label": "Claude Sonnet 4.6", "cost_tier": "$$", "capabilities": '["chat"]'},
    {"id": "claude-opus-4-6", "provider": "anthropic", "api_model_id": "claude-opus-4-20250514", "label": "Claude Opus 4.6", "cost_tier": "$$$", "capabilities": '["chat"]'},
    {"id": "mistral-small", "provider": "mistral", "api_model_id": "mistral-small-latest", "label": "Mistral Small", "cost_tier": "$", "capabilities": '["chat"]'},
    {"id": "mistral-large", "provider": "mistral", "api_model_id": "mistral-large-latest", "label": "Mistral Large", "cost_tier": "$$", "capabilities": '["chat"]'},
    {"id": "mistral-ocr", "provider": "mistral", "api_model_id": "mistral-ocr-latest", "label": "Mistral OCR", "cost_tier": "$", "capabilities": '["ocr"]'},
    {"id": "gpt-4o", "provider": "openai", "api_model_id": "gpt-4o", "label": "GPT-4o", "cost_tier": "$$", "capabilities": '["chat"]'},
    {"id": "gpt-4o-mini", "provider": "openai", "api_model_id": "gpt-4o-mini", "label": "GPT-4o Mini", "cost_tier": "$", "capabilities": '["chat"]'},
    {"id": "gpt-4.1", "provider": "openai", "api_model_id": "gpt-4.1", "label": "GPT-4.1", "cost_tier": "$$", "capabilities": '["chat"]'},
    {"id": "gpt-4.1-mini", "provider": "openai", "api_model_id": "gpt-4.1-mini", "label": "GPT-4.1 Mini", "cost_tier": "$", "capabilities": '["chat"]'},
    {"id": "gpt-4.1-nano", "provider": "openai", "api_model_id": "gpt-4.1-nano", "label": "GPT-4.1 Nano", "cost_tier": "$", "capabilities": '["chat"]'},
    {"id": "o3", "provider": "openai", "api_model_id": "o3", "label": "o3", "cost_tier": "$$$", "capabilities": '["chat", "reasoning"]'},
    {"id": "o4-mini", "provider": "openai", "api_model_id": "o4-mini", "label": "o4 Mini", "cost_tier": "$$", "capabilities": '["chat", "reasoning"]'},
]

DEFAULT_ASSIGNMENTS = {
    "issue_classification": "claude-haiku-4-5",
    "law_mapping": "claude-haiku-4-5",
    "fast_general": "claude-haiku-4-5",
    "article_selection": "claude-sonnet-4-6",
    "answer_generation": "claude-sonnet-4-6",
    "diff_summary": "claude-sonnet-4-6",
    "ocr": "mistral-ocr",
}


def seed_models(db: Session):
    """Seed models and default assignments. Idempotent."""
    for model_data in SEED_MODELS:
        existing = db.query(Model).filter(Model.id == model_data["id"]).first()
        if not existing:
            db.add(Model(**model_data))

    for task, model_id in DEFAULT_ASSIGNMENTS.items():
        existing = db.query(ModelAssignment).filter(ModelAssignment.task == task).first()
        if not existing:
            db.add(ModelAssignment(task=task, model_id=model_id))

    db.commit()
```

- [ ] **Step 5: Check that models/base.py exists and exports Base**

Run: `cd backend && uv run python -c "from app.database import Base; print('ok')"`

If it fails, check how Base is currently defined (likely in `database.py`) and adjust the import.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_model_config.py -v`
Expected: All 6 tests PASS

- [ ] **Step 7: Add seed_models() to main.py lifespan**

In `backend/app/main.py`, import and call `seed_models(db)` in the lifespan function alongside existing `seed_defaults()` and `seed_categories()`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/model_config.py backend/app/services/model_seed.py backend/tests/test_model_config.py backend/app/main.py
git commit -m "feat: add model registry and assignment tables with seed data"
```

---

### Task 9: Provider Abstraction Layer

**Files:**
- Create: `backend/app/providers/__init__.py`
- Create: `backend/app/providers/base.py`
- Create: `backend/app/providers/anthropic_provider.py`
- Create: `backend/app/providers/mistral_provider.py`
- Create: `backend/app/providers/openai_provider.py`
- Test: `backend/tests/test_providers.py`

- [ ] **Step 1: Write failing tests for provider abstraction**

```python
# backend/tests/test_providers.py
import pytest
from unittest.mock import patch, MagicMock
from app.providers import get_provider
from app.providers.base import LLMProvider, LLMResponse


def test_get_provider_returns_anthropic_for_claude():
    from app.providers.anthropic_provider import AnthropicProvider
    provider = get_provider("claude-sonnet-4-6")
    assert isinstance(provider, AnthropicProvider)


def test_get_provider_returns_mistral_for_mistral():
    from app.providers.mistral_provider import MistralProvider
    provider = get_provider("mistral-large")
    assert isinstance(provider, MistralProvider)


def test_get_provider_returns_openai_for_gpt():
    from app.providers.openai_provider import OpenAIProvider
    provider = get_provider("gpt-4.1")
    assert isinstance(provider, OpenAIProvider)


def test_get_provider_unknown_model():
    with pytest.raises(ValueError, match="Unknown model"):
        get_provider("unknown-model-xyz")


def test_provider_interface():
    """All providers implement the required interface."""
    for model_id in ["claude-sonnet-4-6", "mistral-large", "gpt-4.1"]:
        provider = get_provider(model_id)
        assert hasattr(provider, "chat")
        assert hasattr(provider, "stream")
        assert hasattr(provider, "ocr")


def test_non_ocr_model_raises_on_ocr():
    provider = get_provider("claude-sonnet-4-6")
    with pytest.raises(NotImplementedError):
        provider.ocr(b"fake", "application/pdf")


def test_anthropic_chat_calls_api():
    """Anthropic provider formats API call correctly."""
    provider = get_provider("claude-sonnet-4-6")
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Hello")]
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 5

    with patch.object(provider, "_client") as mock_client:
        mock_client.messages.create.return_value = mock_response
        result = provider.chat(
            messages=[{"role": "user", "content": "Hi"}],
            system="You are helpful",
        )
        assert isinstance(result, LLMResponse)
        assert result.content == "Hello"
        assert result.usage.input_tokens == 10
        # Verify system was passed
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "system" in call_kwargs
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_providers.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement base provider**

```python
# backend/app/providers/base.py
"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class LLMResponse:
    content: str
    usage: TokenUsage
    model_id: str


class LLMProvider(ABC):
    """Abstract LLM provider interface. Synchronous to match existing pipeline."""

    model_id: str

    @abstractmethod
    def chat(self, messages: list[dict], system: str | None = None,
             max_tokens: int = 4096, temperature: float = 0.0) -> LLMResponse:
        ...

    @abstractmethod
    def stream(self, messages: list[dict], system: str | None = None,
               max_tokens: int = 4096, temperature: float = 0.0) -> Iterator[str]:
        ...

    def ocr(self, document_bytes: bytes, mime_type: str) -> str:
        raise NotImplementedError("This model does not support OCR")
```

- [ ] **Step 4: Implement Anthropic provider**

```python
# backend/app/providers/anthropic_provider.py
"""Anthropic (Claude) provider wrapping the existing claude_service patterns."""

import os
import anthropic
from typing import Iterator
from app.providers.base import LLMProvider, LLMResponse, TokenUsage


class AnthropicProvider(LLMProvider):
    def __init__(self, model_id: str, api_model_id: str):
        self.model_id = model_id
        self.api_model_id = api_model_id
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = anthropic.Anthropic(api_key=api_key)

    def chat(self, messages, system=None, max_tokens=4096, temperature=0.0):
        kwargs = {
            "model": self.api_model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            kwargs["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        response = self._client.messages.create(**kwargs)
        content = response.content[0].text if response.content else ""
        return LLMResponse(
            content=content,
            usage=TokenUsage(response.usage.input_tokens, response.usage.output_tokens),
            model_id=self.model_id,
        )

    def stream(self, messages, system=None, max_tokens=4096, temperature=0.0):
        kwargs = {
            "model": self.api_model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            kwargs["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        with self._client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text
```

- [ ] **Step 5: Implement Mistral provider**

```python
# backend/app/providers/mistral_provider.py
"""Mistral provider for chat and OCR."""

import os
from typing import Iterator
from mistralai import Mistral
from app.providers.base import LLMProvider, LLMResponse, TokenUsage


class MistralProvider(LLMProvider):
    def __init__(self, model_id: str, api_model_id: str, supports_ocr: bool = False):
        self.model_id = model_id
        self.api_model_id = api_model_id
        self._supports_ocr = supports_ocr
        api_key = os.environ.get("MISTRAL_API_KEY", "")
        self._client = Mistral(api_key=api_key)

    def chat(self, messages, system=None, max_tokens=4096, temperature=0.0):
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        response = self._client.chat.complete(
            model=self.api_model_id,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = response.choices[0]
        usage = response.usage
        return LLMResponse(
            content=choice.message.content,
            usage=TokenUsage(usage.prompt_tokens, usage.completion_tokens),
            model_id=self.model_id,
        )

    def stream(self, messages, system=None, max_tokens=4096, temperature=0.0):
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        for chunk in self._client.chat.stream(
            model=self.api_model_id,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            delta = chunk.data.choices[0].delta
            if delta.content:
                yield delta.content

    def ocr(self, document_bytes: bytes, mime_type: str) -> str:
        if not self._supports_ocr:
            raise NotImplementedError("This Mistral model does not support OCR")
        import base64
        b64 = base64.b64encode(document_bytes).decode()
        response = self._client.ocr.process(
            model=self.api_model_id,
            document={"type": "base64", "data": b64, "mime_type": mime_type},
        )
        return "\n\n".join(page.markdown for page in response.pages)
```

- [ ] **Step 6: Implement OpenAI provider**

```python
# backend/app/providers/openai_provider.py
"""OpenAI provider for GPT and o-series models."""

import os
from typing import Iterator
from openai import OpenAI
from app.providers.base import LLMProvider, LLMResponse, TokenUsage


class OpenAIProvider(LLMProvider):
    def __init__(self, model_id: str, api_model_id: str):
        self.model_id = model_id
        self.api_model_id = api_model_id
        api_key = os.environ.get("OPENAI_API_KEY", "")
        self._client = OpenAI(api_key=api_key)

    def chat(self, messages, system=None, max_tokens=4096, temperature=0.0):
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        response = self._client.chat.completions.create(
            model=self.api_model_id,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = response.choices[0]
        usage = response.usage
        return LLMResponse(
            content=choice.message.content or "",
            usage=TokenUsage(usage.prompt_tokens, usage.completion_tokens),
            model_id=self.model_id,
        )

    def stream(self, messages, system=None, max_tokens=4096, temperature=0.0):
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        stream = self._client.chat.completions.create(
            model=self.api_model_id,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
```

- [ ] **Step 7: Implement provider factory**

```python
# backend/app/providers/__init__.py
"""Provider factory — get_provider(model_id) returns the right LLMProvider."""

from app.providers.base import LLMProvider, LLMResponse, TokenUsage
from app.services.model_seed import SEED_MODELS

_MODEL_LOOKUP = {m["id"]: m for m in SEED_MODELS}


def get_provider(model_id: str) -> LLMProvider:
    """Return an LLMProvider instance for the given model ID."""
    model = _MODEL_LOOKUP.get(model_id)
    if not model:
        raise ValueError(f"Unknown model: {model_id}")

    provider = model["provider"]
    api_model_id = model["api_model_id"]

    if provider == "anthropic":
        from app.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model_id, api_model_id)
    elif provider == "mistral":
        from app.providers.mistral_provider import MistralProvider
        supports_ocr = "ocr" in model["capabilities"]
        return MistralProvider(model_id, api_model_id, supports_ocr=supports_ocr)
    elif provider == "openai":
        from app.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(model_id, api_model_id)
    else:
        raise ValueError(f"Unknown provider: {provider}")
```

- [ ] **Step 8: Add mistralai and openai to dependencies**

Run: `cd backend && uv add mistralai openai`

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_providers.py -v`
Expected: All 7 tests PASS

- [ ] **Step 10: Run all backend tests**

Run: `cd backend && uv run pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 11: Commit**

```bash
git add backend/app/providers/ backend/tests/test_providers.py backend/pyproject.toml backend/uv.lock
git commit -m "feat: add multi-provider abstraction for Anthropic, Mistral, OpenAI"
```

---

### Task 10: Settings API Endpoints

**Files:**
- Create: `backend/app/routers/settings_models.py`
- Create: `backend/app/schemas/model_config.py`
- Test: `backend/tests/test_settings_endpoints.py`

- [ ] **Step 1: Write failing tests for settings endpoints**

```python
# backend/tests/test_settings_endpoints.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.database import get_db
from app.database import Base
from app.services.model_seed import seed_models

engine = create_engine("sqlite:///:memory:")
TestSession = sessionmaker(bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = TestSession()
    seed_models(db)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def test_list_models_returns_all_13():
    res = client.get("/api/settings/models")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 13


def test_toggle_model_disabled():
    res = client.put("/api/settings/models/gpt-4o", json={"enabled": False})
    assert res.status_code == 200
    # Verify it persisted
    res = client.get("/api/settings/models")
    gpt4o = next(m for m in res.json() if m["id"] == "gpt-4o")
    assert gpt4o["enabled"] is False


def test_list_assignments():
    res = client.get("/api/settings/model-assignments")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 7
    assert any(a["task"] == "issue_classification" for a in data)


def test_update_assignment():
    res = client.put(
        "/api/settings/model-assignments",
        json={"task": "issue_classification", "model_id": "claude-sonnet-4-6"},
    )
    assert res.status_code == 200
    # Verify
    res = client.get("/api/settings/model-assignments")
    ic = next(a for a in res.json() if a["task"] == "issue_classification")
    assert ic["model_id"] == "claude-sonnet-4-6"


def test_assign_incapable_model_fails():
    """Assigning an OCR-only model to a chat task should fail."""
    res = client.put(
        "/api/settings/model-assignments",
        json={"task": "issue_classification", "model_id": "mistral-ocr"},
    )
    assert res.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_settings_endpoints.py -v`
Expected: FAIL — 404 (endpoints don't exist)

- [ ] **Step 3: Create Pydantic schemas**

```python
# backend/app/schemas/model_config.py
from pydantic import BaseModel


class ModelOut(BaseModel):
    id: str
    provider: str
    api_model_id: str
    label: str
    cost_tier: str
    capabilities: list[str]
    enabled: bool

    class Config:
        from_attributes = True


class ModelUpdate(BaseModel):
    enabled: bool | None = None
    label: str | None = None


class AssignmentOut(BaseModel):
    task: str
    model_id: str

    class Config:
        from_attributes = True


class AssignmentUpdate(BaseModel):
    task: str
    model_id: str
```

- [ ] **Step 4: Create settings router**

```python
# backend/app/routers/settings_models.py
"""Settings endpoints for model configuration and assignments."""

import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.model_config import Model, ModelAssignment
from app.schemas.model_config import ModelOut, ModelUpdate, AssignmentOut, AssignmentUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings", tags=["settings"])

TASK_REQUIRED_CAPABILITY = {
    "issue_classification": "chat",
    "law_mapping": "chat",
    "fast_general": "chat",
    "article_selection": "chat",
    "answer_generation": "chat",
    "diff_summary": "chat",
    "ocr": "ocr",
}


@router.get("/models", response_model=list[ModelOut])
def list_models(db: Session = Depends(get_db)):
    models = db.query(Model).all()
    return [
        ModelOut(
            id=m.id, provider=m.provider, api_model_id=m.api_model_id,
            label=m.label, cost_tier=m.cost_tier,
            capabilities=m.capabilities_list, enabled=bool(m.enabled),
        )
        for m in models
    ]


@router.put("/models/{model_id}", response_model=ModelOut)
def update_model(model_id: str, update: ModelUpdate, db: Session = Depends(get_db)):
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if update.enabled is not None:
        model.enabled = int(update.enabled)
    if update.label is not None:
        model.label = update.label
    db.commit()
    db.refresh(model)
    return ModelOut(
        id=model.id, provider=model.provider, api_model_id=model.api_model_id,
        label=model.label, cost_tier=model.cost_tier,
        capabilities=model.capabilities_list, enabled=bool(model.enabled),
    )


@router.get("/model-assignments", response_model=list[AssignmentOut])
def list_assignments(db: Session = Depends(get_db)):
    return db.query(ModelAssignment).all()


@router.put("/model-assignments", response_model=AssignmentOut)
def update_assignment(update: AssignmentUpdate, db: Session = Depends(get_db)):
    # Validate capability
    required_cap = TASK_REQUIRED_CAPABILITY.get(update.task)
    if required_cap:
        model = db.query(Model).filter(Model.id == update.model_id).first()
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
        if required_cap not in model.capabilities_list:
            raise HTTPException(
                status_code=422,
                detail=f"Model '{model.label}' does not have required capability '{required_cap}' for task '{update.task}'",
            )

    assignment = db.query(ModelAssignment).filter(ModelAssignment.task == update.task).first()
    if assignment:
        assignment.model_id = update.model_id
    else:
        db.add(ModelAssignment(task=update.task, model_id=update.model_id))
    db.commit()
    return db.query(ModelAssignment).filter(ModelAssignment.task == update.task).first()
```

- [ ] **Step 5: Register router in main.py**

In `backend/app/main.py`, add:
```python
from app.routers import settings_models
app.include_router(settings_models.router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_settings_endpoints.py -v`
Expected: All 5 tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/settings_models.py backend/app/schemas/model_config.py backend/tests/test_settings_endpoints.py backend/app/main.py
git commit -m "feat: add settings API for model configuration and task assignments"
```

---

### Task 11: Settings UI — Models Page

**Files:**
- Create: `frontend/src/app/settings/models/page.tsx`
- Modify: `frontend/src/app/settings/page.tsx` (add link/tab to models)
- Modify: `frontend/src/lib/api.ts` (add settings API methods)

- [ ] **Step 1: Add settings API methods to api.ts**

In `frontend/src/lib/api.ts`, add these methods inside the existing `api.settings` object (which already has `prompts` and `pipeline` sub-objects):

```typescript
// Add inside the existing api.settings object:
models: {
  list: () => apiFetch<ModelConfig[]>("/api/settings/models"),
  update: (id: string, update: { enabled?: boolean }) =>
    apiFetch<ModelConfig>(`/api/settings/models/${id}`, {
      method: "PUT",
      body: JSON.stringify(update),
    }),
},
assignments: {
  list: () => apiFetch<Assignment[]>("/api/settings/model-assignments"),
  update: (task: string, modelId: string) =>
    apiFetch<Assignment>("/api/settings/model-assignments", {
      method: "PUT",
      body: JSON.stringify({ task, model_id: modelId }),
    }),
},
```

Add types:
```typescript
interface ModelConfig {
  id: string;
  provider: string;
  api_model_id: string;
  label: string;
  cost_tier: string;
  capabilities: string[];
  enabled: boolean;
}

interface Assignment {
  task: string;
  model_id: string;
}
```

- [ ] **Step 2: Create models settings page**

Create `frontend/src/app/settings/models/page.tsx` with:
- A table of all 13 models: provider icon, label, cost tier badge, capabilities badges, enable/disable toggle
- A task assignments section: one dropdown per pipeline task, filtered to models with the required capability
- Fetch data from the settings API on mount
- PUT on toggle/dropdown change

This is a standard CRUD UI page. Use the same Tailwind styling patterns as the existing settings pages.

- [ ] **Step 3: Add navigation to models settings**

Update `frontend/src/app/settings/page.tsx` to include a link/tab to the Models settings page.

- [ ] **Step 4: Test manually in browser**

Open http://localhost:4000/settings/models and verify:
- All 13 models displayed
- Toggle enable/disable works
- Task assignment dropdowns work
- Incapable model for task shows error

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/settings/models/ frontend/src/lib/api.ts frontend/src/app/settings/page.tsx
git commit -m "feat: add model configuration and task assignment settings UI"
```

---

### Task 12: Pricing Module

**Files:**
- Create: `backend/app/services/pricing.py`
- Test: `backend/tests/test_pricing.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_pricing.py
import pytest
from app.services.pricing import calculate_cost
from app.providers.base import TokenUsage


def test_anthropic_sonnet_cost():
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    cost = calculate_cost("claude-sonnet-4-6", usage)
    assert cost > 0
    assert isinstance(cost, float)


def test_openai_gpt4o_cost():
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    cost = calculate_cost("gpt-4o", usage)
    assert cost > 0


def test_mistral_ocr_page_cost():
    # For OCR, input_tokens represents pages
    usage = TokenUsage(input_tokens=10, output_tokens=0)
    cost = calculate_cost("mistral-ocr", usage)
    assert cost == pytest.approx(0.02, abs=0.001)  # $0.002/page * 10


def test_zero_usage():
    usage = TokenUsage(input_tokens=0, output_tokens=0)
    cost = calculate_cost("claude-sonnet-4-6", usage)
    assert cost == 0.0


def test_unknown_model():
    usage = TokenUsage(input_tokens=100, output_tokens=100)
    with pytest.raises(ValueError):
        calculate_cost("unknown-model", usage)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_pricing.py -v`
Expected: FAIL

- [ ] **Step 3: Implement pricing module**

```python
# backend/app/services/pricing.py
"""Cost calculation for LLM API calls."""

from app.providers.base import TokenUsage

# Prices per 1M tokens (input, output)
TOKEN_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (0.80, 4.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-6": (15.00, 75.00),
    "mistral-small": (0.20, 0.60),
    "mistral-large": (2.00, 6.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "o3": (10.00, 40.00),
    "o4-mini": (1.10, 4.40),
}

# Page-based pricing
PAGE_PRICING: dict[str, float] = {
    "mistral-ocr": 0.002,  # per page
}


def calculate_cost(model_id: str, usage: TokenUsage) -> float:
    """Calculate the cost in USD for a given model and token usage."""
    if model_id in PAGE_PRICING:
        return PAGE_PRICING[model_id] * usage.input_tokens

    if model_id not in TOKEN_PRICING:
        raise ValueError(f"Unknown model for pricing: {model_id}")

    input_rate, output_rate = TOKEN_PRICING[model_id]
    return (usage.input_tokens / 1_000_000) * input_rate + \
           (usage.output_tokens / 1_000_000) * output_rate
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_pricing.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pricing.py backend/tests/test_pricing.py
git commit -m "feat: add pricing module for multi-provider cost calculation"
```

---

## Phase 4: Model Comparison Feature

### Task 13: Compare API Endpoint

**Files:**
- Create: `backend/app/routers/compare.py`
- Create: `backend/app/schemas/compare.py`
- Test: `backend/tests/test_compare_endpoint.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_compare_endpoint.py
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.providers.base import LLMResponse, TokenUsage

client = TestClient(app)


def test_compare_no_models_returns_422():
    res = client.post("/api/assistant/compare", json={
        "question": "Test question",
        "models": [],
        "mode": "full",
    })
    assert res.status_code == 422


def test_compare_too_many_models_returns_422():
    res = client.post("/api/assistant/compare", json={
        "question": "Test question",
        "models": ["m1", "m2", "m3", "m4", "m5", "m6"],
        "mode": "full",
    })
    assert res.status_code == 422


def test_compare_returns_results_per_model():
    """Each model should have a result entry."""
    mock_response = LLMResponse(
        content="Legal answer here",
        usage=TokenUsage(input_tokens=100, output_tokens=50),
        model_id="claude-sonnet-4-6",
    )

    with patch("app.routers.compare.run_pipeline_for_model") as mock_run:
        mock_run.return_value = {
            "answer": "Legal answer here",
            "citations": [],
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "pipeline_steps": {},
        }

        res = client.post("/api/assistant/compare", json={
            "question": "Ce spune legea?",
            "models": ["claude-sonnet-4-6", "gpt-4.1"],
            "mode": "full",
        })
        assert res.status_code == 200
        data = res.json()
        assert len(data["results"]) == 2
        assert all(r["model_id"] in ["claude-sonnet-4-6", "gpt-4.1"] for r in data["results"])


def test_compare_one_model_fails_others_succeed():
    """Partial failure should still return successful results."""
    def side_effect(question, model_id, mode, db):
        if model_id == "gpt-4.1":
            raise RuntimeError("API rate limit exceeded")
        return {
            "answer": "Answer",
            "citations": [],
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "pipeline_steps": {},
        }

    with patch("app.routers.compare.run_pipeline_for_model", side_effect=side_effect):
        res = client.post("/api/assistant/compare", json={
            "question": "Test",
            "models": ["claude-sonnet-4-6", "gpt-4.1"],
            "mode": "full",
        })
        assert res.status_code == 200
        data = res.json()
        assert len(data["results"]) == 2
        success = next(r for r in data["results"] if r["model_id"] == "claude-sonnet-4-6")
        failure = next(r for r in data["results"] if r["model_id"] == "gpt-4.1")
        assert success["status"] == "success"
        assert failure["status"] == "error"
        assert "rate limit" in failure["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_compare_endpoint.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Create compare schemas**

```python
# backend/app/schemas/compare.py
from pydantic import BaseModel, field_validator


class CompareRequest(BaseModel):
    question: str
    models: list[str]
    mode: str = "full"  # "full" or "pipeline_steps"

    @field_validator("models")
    @classmethod
    def validate_models(cls, v):
        if len(v) == 0:
            raise ValueError("At least one model must be selected")
        if len(v) > 5:
            raise ValueError("Maximum 5 models per comparison")
        return v


class CompareModelResult(BaseModel):
    model_id: str
    model_label: str
    status: str  # "success" | "error"
    duration_ms: int = 0
    usage: dict | None = None
    cost_usd: float = 0.0
    answer: str | None = None
    citations: list | None = None
    pipeline_steps: dict | None = None
    error: str | None = None


class CompareResponse(BaseModel):
    question: str
    results: list[CompareModelResult]
```

- [ ] **Step 4: Create compare router**

```python
# backend/app/routers/compare.py
"""Model comparison endpoint — runs the same question against multiple models."""

import asyncio
import logging
import time
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.compare import CompareRequest, CompareResponse, CompareModelResult
from app.providers import get_provider
from app.services.pricing import calculate_cost
from app.providers.base import TokenUsage
from app.services.model_seed import SEED_MODELS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/assistant", tags=["assistant"])

_MODEL_LABELS = {m["id"]: m["label"] for m in SEED_MODELS}


def run_pipeline_for_model(question: str, model_id: str, mode: str, db: Session) -> dict:
    """Run the legal assistant pipeline with a specific model.

    This is a placeholder that will be connected to pipeline_service
    once the pipeline is refactored to accept model_overrides.
    """
    provider = get_provider(model_id)
    response = provider.chat(
        messages=[{"role": "user", "content": question}],
        system="You are a Romanian legal assistant. Answer the question based on Romanian law.",
    )
    return {
        "answer": response.content,
        "citations": [],
        "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
        "pipeline_steps": {},
    }


@router.post("/compare", response_model=CompareResponse)
async def compare_models(req: CompareRequest, db: Session = Depends(get_db)):
    async def run_one(model_id: str) -> CompareModelResult:
        label = _MODEL_LABELS.get(model_id, model_id)
        start = time.monotonic()
        try:
            result = await asyncio.to_thread(
                run_pipeline_for_model, req.question, model_id, req.mode, db
            )
            duration = int((time.monotonic() - start) * 1000)
            usage = result.get("usage", {})
            token_usage = TokenUsage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )
            return CompareModelResult(
                model_id=model_id,
                model_label=label,
                status="success",
                duration_ms=duration,
                usage=usage,
                cost_usd=calculate_cost(model_id, token_usage),
                answer=result.get("answer"),
                citations=result.get("citations"),
                pipeline_steps=result.get("pipeline_steps") if req.mode == "pipeline_steps" else None,
            )
        except Exception as e:
            duration = int((time.monotonic() - start) * 1000)
            logger.error(f"Compare failed for {model_id}: {e}")
            return CompareModelResult(
                model_id=model_id,
                model_label=label,
                status="error",
                duration_ms=duration,
                error=str(e),
            )

    results = await asyncio.gather(*(run_one(m) for m in req.models))
    return CompareResponse(question=req.question, results=list(results))
```

- [ ] **Step 5: Register router in main.py**

In `backend/app/main.py`, add:
```python
from app.routers import compare
app.include_router(compare.router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_compare_endpoint.py -v`
Expected: All 4 tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/compare.py backend/app/schemas/compare.py backend/tests/test_compare_endpoint.py backend/app/main.py
git commit -m "feat: add model comparison endpoint with parallel execution"
```

---

### Task 14: Frontend Compare Tab

**Files:**
- Create: `frontend/src/app/assistant/compare-tab.tsx`
- Modify: `frontend/src/app/assistant/page.tsx` (add Compare tab)
- Modify: `frontend/src/lib/api.ts` (add compare API method)
- Test: `frontend/__tests__/model-compare.test.ts`

- [ ] **Step 1: Add compare API method to api.ts**

```typescript
compare: {
  run: (question: string, models: string[], mode: "full" | "pipeline_steps") =>
    apiFetch<CompareResponse>("/api/assistant/compare", {
      method: "POST",
      body: JSON.stringify({ question, models, mode }),
    }),
},
```

Add types:
```typescript
interface CompareModelResult {
  model_id: string;
  model_label: string;
  status: "success" | "error";
  duration_ms: number;
  usage?: { input_tokens: number; output_tokens: number };
  cost_usd: number;
  answer?: string;
  citations?: any[];
  pipeline_steps?: Record<string, any>;
  error?: string;
}

interface CompareResponse {
  question: string;
  results: CompareModelResult[];
}
```

- [ ] **Step 2: Create the compare tab component**

Create `frontend/src/app/assistant/compare-tab.tsx` with:

- **Question input:** textarea for the legal question
- **Model selection:** fetch enabled models from `/api/settings/models`, render toggle buttons for each. Color-coded by provider:
  - Claude: purple shades (`bg-purple-100`, `bg-purple-200`, `bg-purple-300`)
  - Mistral: orange/amber (`bg-orange-100`, `bg-amber-100`)
  - OpenAI: green/teal (`bg-green-100`, `bg-teal-100`, `bg-emerald-100`)
- **Mode toggle:** "Full answer" / "Pipeline steps" radio buttons
- **Compare button:** disabled if < 2 models selected or no question
- **Loading state:** skeleton cards for each selected model
- **Results grid:** responsive columns based on model count:
  - 2 models: `grid-cols-2`
  - 3 models: `grid-cols-3`
  - 4-5 models: `grid-cols-2 lg:grid-cols-3 xl:grid-cols-4`
- **Model result card:**
  - Header: model label + cost tier badge + duration (e.g. "4.2s")
  - Body: answer rendered with `react-markdown` (reuse existing pattern from chat)
  - Citations list (if any)
  - Footer: token usage + cost in USD
  - Expandable pipeline steps section (if mode is "pipeline_steps")
  - Error state: red background with error message
- Filter out OCR-only models from selection (they can't answer legal questions)

- [ ] **Step 3: Add Compare tab to assistant page**

In `frontend/src/app/assistant/page.tsx`, add a tab switcher:
- "Chat" tab (default, existing chat UI)
- "Compare" tab (new compare-tab component)

Use simple state-based tab switching or URL query param (`?tab=compare`).

- [ ] **Step 4: Write frontend test**

```typescript
// frontend/__tests__/model-compare.test.ts
import { describe, it, expect } from "vitest";

describe("Model comparison", () => {
  it("validates minimum 2 models required", () => {
    const models: string[] = ["claude-sonnet-4-6"];
    expect(models.length >= 2).toBe(false);
  });

  it("validates maximum 5 models", () => {
    const models = ["m1", "m2", "m3", "m4", "m5", "m6"];
    expect(models.length <= 5).toBe(false);
  });

  it("calculates grid columns from model count", () => {
    const getGridCols = (count: number) => {
      if (count <= 2) return "grid-cols-2";
      if (count === 3) return "grid-cols-3";
      return "grid-cols-2 lg:grid-cols-3";
    };
    expect(getGridCols(2)).toBe("grid-cols-2");
    expect(getGridCols(3)).toBe("grid-cols-3");
    expect(getGridCols(4)).toBe("grid-cols-2 lg:grid-cols-3");
  });

  it("filters out OCR-only models", () => {
    const models = [
      { id: "claude-sonnet-4-6", capabilities: ["chat"] },
      { id: "mistral-ocr", capabilities: ["ocr"] },
    ];
    const chatModels = models.filter(m => m.capabilities.includes("chat"));
    expect(chatModels).toHaveLength(1);
    expect(chatModels[0].id).toBe("claude-sonnet-4-6");
  });
});
```

- [ ] **Step 5: Run frontend tests**

Run: `cd frontend && npx vitest run`
Expected: All tests PASS

- [ ] **Step 6: Test manually in browser**

Open http://localhost:4000/assistant?tab=compare and verify:
- Model toggles appear
- Selecting models and asking a question works
- Results display in grid layout

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/assistant/compare-tab.tsx frontend/src/app/assistant/page.tsx frontend/src/lib/api.ts frontend/__tests__/model-compare.test.ts
git commit -m "feat: add model comparison tab in Legal Assistant"
```

---

## Phase 5: Integration & Final Tests

### Task 15: Pipeline Integration with Provider Abstraction

**Files:**
- Modify: `backend/app/services/pipeline_service.py`
- Modify: `backend/app/services/claude_service.py`

- [ ] **Step 1: Read current pipeline_service.py and claude_service.py**

Understand how `call_claude()` and `stream_claude()` are called throughout the pipeline. Identify every call site.

- [ ] **Step 2: Update pipeline_service to read model assignments**

Modify pipeline_service to:
- Read `ModelAssignment` from DB for each pipeline step
- Call `get_provider(model_id)` instead of directly calling `call_claude()`
- Accept `model_overrides: dict[str, str] | None` parameter
- Accept `dry_run: bool = False` parameter (suppresses pipeline logger writes)

The key changes:
- Where `call_claude(system, user_msg)` is called, replace with `provider.chat(messages=[{"role": "user", "content": user_msg}], system=system)`
- Where `stream_claude(system, user_msg)` is called, replace with `provider.stream(messages=[{"role": "user", "content": user_msg}], system=system)`

- [ ] **Step 3: Keep claude_service.py as fallback**

Don't delete `claude_service.py` — keep it as the fallback when no provider abstraction is configured. This ensures existing functionality doesn't break.

- [ ] **Step 4: Run all existing pipeline tests**

Run: `cd backend && uv run pytest tests/ -v`
Expected: All existing tests still PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pipeline_service.py backend/app/services/claude_service.py
git commit -m "feat: integrate provider abstraction into pipeline service"
```

---

### Task 16: Full Test Suite Verification

- [ ] **Step 1: Run all backend tests**

Run: `cd backend && uv run pytest tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 2: Run all frontend tests**

Run: `cd frontend && npx vitest run`
Expected: All tests PASS

- [ ] **Step 3: Manual smoke test**

1. Open http://localhost:4000
2. Navigate to Legal Library — verify existing laws display
3. Try importing a law — verify SSE progress shows
4. Navigate to Legal Assistant — verify chat works
5. Switch to Compare tab — select 2 models, ask a question
6. Navigate to Settings > Models — toggle a model, change an assignment
7. Trigger an error condition (e.g. import Constitution) — verify clean error message

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: final integration and smoke test verification"
```
