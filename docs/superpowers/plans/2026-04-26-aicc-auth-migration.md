# AICC Auth Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Themis's NextAuth + Google OAuth + local `allowed_emails` allow-list with AICC PKCE auth, in a single hard-cutover PR.

**Architecture:** Frontend keeps the existing pattern (Next.js route handlers expose a bearer token to JS via `/api/token`, which the browser sends to FastAPI). The provider underneath is swapped: `/api/auth/login` → `/auth/authorize`, `/api/auth/callback` → `/auth/token`, tokens stored as httpOnly cookies. Backend swaps JWT decode for an `AiccAuthClient.verify_token()` call against AICC `/auth/me`, gated by a 60-second `cachetools.TTLCache`. Local `User` row is upserted on every cache miss; `User.role` is mirrored from AICC `projectRole` (only `"admin"` → `"admin"`, everything else → `"user"`). `allowed_emails` table dropped. AICC `ProjectMembership` is the gate.

**Tech Stack:** Backend: FastAPI, SQLAlchemy 2.x, pytest, httpx, cachetools, SQLite. Frontend: Next.js 16.2 (read `frontend/AGENTS.md` and `frontend/node_modules/next/dist/docs/` before writing route handlers), React 19, vitest, msw.

**Spec:** `docs/superpowers/specs/2026-04-26-aicc-auth-migration-design.md`

**Pre-implementation manual prep (NOT a code task):**
1. In AICC dashboard → THEMIS project → create auth client `themis-web` with redirect URIs `http://localhost:3000/auth/callback`, `https://<themis-prod-host>/auth/callback`, `https://<themis-staging-host>/auth/callback`. Allowed origins = same hosts. Identity provider: Google.
2. Run `backend/scripts/seed_aicc_memberships.py` (created in Task 16) against the prod DB to populate `ProjectMembership` rows. Verify in dashboard.
3. Generate `AICC_PKCE_COOKIE_SECRET` (`openssl rand -base64 48`) and store in your secrets manager.

Both must be done **before** merging the implementation PR.

---

## File map

### Backend — created
- `backend/app/services/aicc_auth_client.py` — owns `/auth/me` HTTP + LRU cache
- `backend/tests/test_aicc_auth_client.py` — `httpx.MockTransport` unit tests
- `backend/tests/test_auth_dependency.py` — `get_current_user` integration tests
- `backend/scripts/seed_aicc_memberships.py` — one-shot bootstrap script

### Backend — modified
- `backend/app/auth.py` — full rewrite (jwt → AICC)
- `backend/app/models/user.py` — drop `AllowedEmail`, add `aicc_user_id` column
- `backend/app/services/user_service.py` — drop `verify_and_upsert_user`, drop `seed_admin_users`, drop `ADMIN_EMAILS`
- `backend/app/routers/admin.py` — drop `verify-user` and whitelist endpoints; drop `NEXTAUTH_SECRET` import
- `backend/app/main.py` — remove `seed_admin_users` call; add migration (add column + drop table)
- `backend/app/config.py` — drop `NEXTAUTH_SECRET`; add `AICC_AUTH_BASE_URL`, `AICC_AUTH_TTL_SECONDS`
- `backend/pyproject.toml` — add `cachetools`, `httpx`; drop `pyjwt`
- `backend/.env` — drop `NEXTAUTH_SECRET`, add `AICC_AUTH_BASE_URL`, `AICC_AUTH_TTL_SECONDS`

### Frontend — created
- `frontend/src/lib/aicc-auth.ts` — pure helpers: `generatePkceVerifier`, `pkceChallenge`, `buildAuthorizeUrl`, `exchangeCodeForTokens`, `refreshTokens`, `revokeToken`, `fetchAiccMe`
- `frontend/src/lib/aicc-auth.test.ts` — vitest unit tests for the pure helpers
- `frontend/src/lib/cookies.ts` — small helper: `setAuthCookies`, `clearAuthCookies`, `readAuthCookies`, `signPkceCookie`, `verifyPkceCookie`
- `frontend/src/lib/cookies.test.ts` — sign/verify round-trip tests
- `frontend/src/app/api/auth/login/route.ts`
- `frontend/src/app/api/auth/login/route.test.ts`
- `frontend/src/app/api/auth/callback/route.ts`
- `frontend/src/app/api/auth/callback/route.test.ts`
- `frontend/src/app/api/auth/logout/route.ts`
- `frontend/src/app/api/auth/logout/route.test.ts`
- `frontend/src/app/api/me/route.ts`
- `frontend/src/app/api/me/route.test.ts`

### Frontend — modified
- `frontend/src/app/api/token/route.ts` — full rewrite (read AICC cookies, refresh if near expiry)
- `frontend/src/app/api/token/route.test.ts` — created if missing
- `frontend/src/middleware.ts` — replace NextAuth wrapper with cookie presence check
- `frontend/src/app/auth/signin/page.tsx` — simple "Sign in with AICC" button
- `frontend/src/app/user-menu.tsx` — use `/api/me` + `/api/auth/logout` instead of NextAuth hooks
- `frontend/src/lib/api.ts` — on 401, redirect to `/api/auth/login?callbackUrl=<current>`
- `frontend/package.json` — remove `next-auth`
- `frontend/.env.local` — add new vars, drop NEXTAUTH/GOOGLE_*

### Frontend — deleted
- `frontend/src/lib/auth.ts`
- `frontend/src/lib/auth-context.tsx`
- `frontend/src/app/api/auth/[...nextauth]/route.ts` (and its directory)

### Docs — created
- `docs/superpowers/runbooks/2026-04-26-aicc-auth-cutover.md` — cutover & rollback runbook

---

## Pre-flight: dependencies & test scaffolding

### Task 0: Add backend dependencies and remove pyjwt

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Edit pyproject.toml**

In `backend/pyproject.toml`, update the `dependencies` array to add `cachetools` and `httpx` and remove `pyjwt`:

```toml
dependencies = [
    "aiosqlite>=0.22.1",
    "alembic>=1.18.4",
    "anthropic>=0.40.0",
    "apscheduler>=3.11.2",
    "cachetools>=5.5.0",
    "chromadb>=0.6.0",
    "fastapi>=0.135.1",
    "httpx>=0.27.0",
    "leropa",
    "mistralai>=2.1.3",
    "openai>=2.30.0",
    "python-multipart>=0.0.22",
    "sentence-transformers>=3.0",
    "sqlalchemy>=2.0.48",
    "sse-starlette>=2.0",
    "uvicorn>=0.42.0",
]
```

(`pyjwt` removed; `cachetools` and `httpx` added in alphabetical position.)

- [ ] **Step 2: Sync deps**

Run: `cd backend && uv sync`
Expected: success; `cachetools` and `httpx` installed; no `pyjwt` in lock file.

- [ ] **Step 3: Verify pyjwt is gone**

Run: `cd backend && uv pip list | grep -i jwt`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "build(backend): swap pyjwt for cachetools+httpx (AICC auth migration)"
```

---

## Backend: AICC auth client (one well-bounded unit)

### Task 1: `AiccUser` pydantic model + `AiccAuthClient` skeleton

**Files:**
- Create: `backend/app/services/aicc_auth_client.py`
- Create: `backend/tests/test_aicc_auth_client.py`

- [ ] **Step 1: Write the failing test for the model**

Create `backend/tests/test_aicc_auth_client.py`:

```python
"""Unit tests for AiccAuthClient — the only path through which Themis
verifies user tokens against AICC."""
from app.services.aicc_auth_client import AiccUser


def test_aicc_user_parses_full_payload():
    payload = {
        "id": "user-uuid-123",
        "email": "alice@example.com",
        "name": "Alice",
        "avatarUrl": "https://lh3.googleusercontent.com/a/x",
        "role": "user",
        "globalRole": "user",
        "projectRole": "admin",
        "projectId": "project-uuid",
    }
    u = AiccUser.model_validate(payload)
    assert u.id == "user-uuid-123"
    assert u.email == "alice@example.com"
    assert u.name == "Alice"
    assert u.avatar_url == "https://lh3.googleusercontent.com/a/x"
    assert u.project_role == "admin"


def test_aicc_user_handles_nullable_fields():
    payload = {
        "id": "user-uuid-456",
        "email": "bob@example.com",
        "name": None,
        "avatarUrl": None,
        "role": "user",
        "globalRole": "user",
        "projectRole": None,
        "projectId": None,
    }
    u = AiccUser.model_validate(payload)
    assert u.name is None
    assert u.avatar_url is None
    assert u.project_role is None
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `cd backend && uv run pytest tests/test_aicc_auth_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.aicc_auth_client'`.

- [ ] **Step 3: Implement `AiccUser`**

Create `backend/app/services/aicc_auth_client.py`:

```python
"""AICC auth client — single point of contact between Themis backend and the
AICC /auth/me endpoint.

Owns the in-memory LRU cache that keeps per-request /auth/me roundtrips bounded
to once per `ttl_seconds` per active session.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

import httpx
from cachetools import TTLCache
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class AiccUser(BaseModel):
    """Subset of AICC's /auth/me payload that Themis cares about.

    AICC field names use camelCase; we expose snake_case to the rest of the
    codebase via Field aliases.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    email: str
    name: str | None = None
    avatar_url: str | None = Field(default=None, alias="avatarUrl")
    project_role: str | None = Field(default=None, alias="projectRole")
```

- [ ] **Step 4: Run test, verify it passes**

Run: `cd backend && uv run pytest tests/test_aicc_auth_client.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/aicc_auth_client.py backend/tests/test_aicc_auth_client.py
git commit -m "feat(backend): add AiccUser pydantic model"
```

---

### Task 2: `AiccAuthClient.verify_token` happy path + caching

**Files:**
- Modify: `backend/app/services/aicc_auth_client.py`
- Modify: `backend/tests/test_aicc_auth_client.py`

- [ ] **Step 1: Add the failing test for the happy path**

Append to `backend/tests/test_aicc_auth_client.py`:

```python
import httpx
import pytest
from app.services.aicc_auth_client import AiccAuthClient


def _mock_transport(handler):
    """httpx.MockTransport that delegates each request to `handler`."""
    return httpx.MockTransport(handler)


def test_verify_token_returns_user_on_200():
    payload = {
        "id": "u1",
        "email": "alice@example.com",
        "name": "Alice",
        "avatarUrl": None,
        "role": "user",
        "globalRole": "user",
        "projectRole": "admin",
        "projectId": "p1",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/me"
        assert request.headers["Authorization"] == "Bearer access-xyz"
        return httpx.Response(200, json=payload)

    client = AiccAuthClient(
        base_url="https://aicc.test",
        ttl_seconds=60,
        transport=_mock_transport(handler),
    )
    user = client.verify_token("access-xyz")
    assert user is not None
    assert user.email == "alice@example.com"
    assert user.project_role == "admin"


def test_verify_token_caches_result():
    call_count = {"n": 0}
    payload = {
        "id": "u1", "email": "alice@example.com", "name": None,
        "avatarUrl": None, "role": "user", "globalRole": "user",
        "projectRole": None, "projectId": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json=payload)

    client = AiccAuthClient(
        base_url="https://aicc.test",
        ttl_seconds=60,
        transport=_mock_transport(handler),
    )
    client.verify_token("access-xyz")
    client.verify_token("access-xyz")
    assert call_count["n"] == 1, "second call should hit the cache"
```

- [ ] **Step 2: Run, verify the tests fail**

Run: `cd backend && uv run pytest tests/test_aicc_auth_client.py -v`
Expected: 2 PASS (existing) + 2 FAIL with `AttributeError: type object 'AiccAuthClient' has no attribute 'verify_token'` (or `TypeError: AiccAuthClient() takes no arguments`).

- [ ] **Step 3: Implement the class**

Append to `backend/app/services/aicc_auth_client.py`:

```python
class AiccAuthClient:
    """Verifies AICC access tokens via /auth/me with a TTL cache.

    Use one instance per process. Attach to `app.state.aicc_auth` at startup;
    inject into FastAPI dependencies via Depends(get_aicc_client).
    """

    def __init__(
        self,
        base_url: str,
        ttl_seconds: int = 60,
        max_size: int = 1024,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._cache: TTLCache = TTLCache(maxsize=max_size, ttl=ttl_seconds)
        self._http = httpx.Client(base_url=base_url, timeout=5.0, transport=transport)

    @staticmethod
    def _key(access_token: str) -> str:
        return hashlib.sha256(access_token.encode("utf-8")).hexdigest()

    def verify_token(self, access_token: str) -> Optional[AiccUser]:
        """Return the AiccUser for this token, or None if AICC rejects it.

        Raises HTTPException(503) on network errors or 5xx from AICC.
        Never caches a failure; only successful results land in the cache.
        """
        key = self._key(access_token)
        if (cached := self._cache.get(key)) is not None:
            return cached

        try:
            r = self._http.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.RequestError as e:
            logger.error("[aicc-auth] /auth/me request failed: %s", e)
            raise HTTPException(status_code=503, detail="Auth provider unreachable")

        if r.status_code == 401:
            return None

        if r.status_code != 200:
            logger.error(
                "[aicc-auth] /auth/me unexpected %d: %s",
                r.status_code,
                r.text[:200],
            )
            raise HTTPException(status_code=503, detail="Auth provider error")

        user = AiccUser.model_validate(r.json())
        self._cache[key] = user
        return user

    def invalidate(self, access_token: str) -> None:
        """Drop a single entry. Used after explicit logout."""
        self._cache.pop(self._key(access_token), None)

    def close(self) -> None:
        self._http.close()
```

- [ ] **Step 4: Run, verify all tests pass**

Run: `cd backend && uv run pytest tests/test_aicc_auth_client.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/aicc_auth_client.py backend/tests/test_aicc_auth_client.py
git commit -m "feat(backend): AiccAuthClient.verify_token with TTL cache"
```

---

### Task 3: `verify_token` error paths

**Files:**
- Modify: `backend/tests/test_aicc_auth_client.py`

- [ ] **Step 1: Add the failing tests**

Append to `backend/tests/test_aicc_auth_client.py`:

```python
def test_verify_token_returns_none_on_401_and_does_not_cache():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(401, json={"error": "invalid_token"})

    client = AiccAuthClient(
        base_url="https://aicc.test",
        ttl_seconds=60,
        transport=_mock_transport(handler),
    )
    assert client.verify_token("bad-token") is None
    assert client.verify_token("bad-token") is None
    assert call_count["n"] == 2, "401s must NOT be cached"


def test_verify_token_raises_503_on_5xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    client = AiccAuthClient(
        base_url="https://aicc.test",
        ttl_seconds=60,
        transport=_mock_transport(handler),
    )
    with pytest.raises(HTTPException) as exc:
        client.verify_token("any-token")
    assert exc.value.status_code == 503


def test_verify_token_raises_503_on_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure", request=request)

    client = AiccAuthClient(
        base_url="https://aicc.test",
        ttl_seconds=60,
        transport=_mock_transport(handler),
    )
    with pytest.raises(HTTPException) as exc:
        client.verify_token("any-token")
    assert exc.value.status_code == 503


def test_invalidate_drops_cache_entry():
    payload = {
        "id": "u1", "email": "a@x.com", "name": None,
        "avatarUrl": None, "role": "user", "globalRole": "user",
        "projectRole": None, "projectId": None,
    }
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json=payload)

    client = AiccAuthClient(
        base_url="https://aicc.test",
        ttl_seconds=60,
        transport=_mock_transport(handler),
    )
    client.verify_token("t")
    client.invalidate("t")
    client.verify_token("t")
    assert call_count["n"] == 2

# Add this top-level import if not already present
from fastapi import HTTPException
```

(If the `from fastapi import HTTPException` line is already at the top, skip it; otherwise add it next to the other imports.)

- [ ] **Step 2: Run tests, verify they pass (the implementation already covers these)**

Run: `cd backend && uv run pytest tests/test_aicc_auth_client.py -v`
Expected: 8 PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_aicc_auth_client.py
git commit -m "test(backend): cover AiccAuthClient 401, 5xx, network, invalidate paths"
```

---

## Backend: configuration

### Task 4: Replace `NEXTAUTH_SECRET` with AICC auth env vars

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/.env`

- [ ] **Step 1: Edit `backend/app/config.py`**

Replace the line:

```python
NEXTAUTH_SECRET = os.environ.get("NEXTAUTH_SECRET", "dev-secret-change-me")
```

with:

```python
# AICC PKCE auth — backend verifies user tokens via AICC /auth/me.
# Distinct from AICC_BASE_URL (which has /v1 suffix for the AI proxy).
AICC_AUTH_BASE_URL = os.environ.get(
    "AICC_AUTH_BASE_URL",
    "https://aicommandcenter-production-d7b1.up.railway.app",
)
AICC_AUTH_TTL_SECONDS = int(os.environ.get("AICC_AUTH_TTL_SECONDS", "60"))
```

- [ ] **Step 2: Update `backend/.env`**

Open `backend/.env`, remove any `NEXTAUTH_SECRET=...` line, and add:

```
AICC_AUTH_BASE_URL=https://aicommandcenter-production-d7b1.up.railway.app
AICC_AUTH_TTL_SECONDS=60
```

- [ ] **Step 3: Verify nothing still imports `NEXTAUTH_SECRET`**

Run: `cd backend && rg "NEXTAUTH_SECRET"`
Expected: matches only in tests' fixtures, `app/auth.py`, `app/routers/admin.py`. (These will be removed in later tasks.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py backend/.env
git commit -m "config(backend): swap NEXTAUTH_SECRET for AICC_AUTH_BASE_URL/TTL"
```

---

### Task 5: Wire `AiccAuthClient` into FastAPI startup + DI

**Files:**
- Modify: `backend/app/main.py`
- Create section in: `backend/app/auth.py` (the DI provider)

- [ ] **Step 1: Add the DI provider stub**

In `backend/app/auth.py`, REPLACE the entire file content with the following stub. (The full `get_current_user` rewrite happens in Task 6; this stub gives us something importable now.)

```python
"""User authentication: AICC PKCE.

Verifies bearer tokens via AiccAuthClient (which talks to AICC /auth/me with
a TTL cache). On every successful verification, mirrors the AICC user into the
local `users` table so existing FKs and `user.role` checks keep working.
"""
from __future__ import annotations

import datetime
import logging

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.aicc_auth_client import AiccAuthClient

logger = logging.getLogger(__name__)

# Mapping AICC projectRole -> Themis role. Strict by design: only "admin"
# is privileged; any new AICC role is treated as a regular user until we
# explicitly opt it in.
_ROLE_MAP = {"admin": "admin"}


def _map_role(project_role: str | None) -> str:
    return _ROLE_MAP.get((project_role or "").lower(), "user")


def get_aicc_client(request: Request) -> AiccAuthClient:
    """FastAPI dependency: returns the process-singleton AiccAuthClient."""
    client: AiccAuthClient | None = getattr(request.app.state, "aicc_auth", None)
    if client is None:
        raise RuntimeError(
            "AiccAuthClient not initialized. Check app.main:lifespan startup."
        )
    return client


# get_current_user / require_admin are defined in Task 6.
```

- [ ] **Step 2: Add startup wiring in `app/main.py`**

In `backend/app/main.py`, find the `lifespan` async context manager. At the **top** of `lifespan` (before `os.makedirs("data", exist_ok=True)`), add:

```python
    from app.config import AICC_AUTH_BASE_URL, AICC_AUTH_TTL_SECONDS
    from app.services.aicc_auth_client import AiccAuthClient

    app.state.aicc_auth = AiccAuthClient(
        base_url=AICC_AUTH_BASE_URL,
        ttl_seconds=AICC_AUTH_TTL_SECONDS,
    )
    logger.info(
        "AiccAuthClient initialized: base=%s ttl=%ss",
        AICC_AUTH_BASE_URL, AICC_AUTH_TTL_SECONDS,
    )
```

At the **bottom** of `lifespan` (after the `yield` if present, or at the end of cleanup), add:

```python
    # Shutdown: close the AICC HTTP client
    if hasattr(app.state, "aicc_auth"):
        app.state.aicc_auth.close()
```

If `lifespan` does not currently have a `yield`, the FastAPI lifespan must `yield` somewhere. Read the current structure first; insert `yield` before the cleanup block if it's missing.

- [ ] **Step 3: Verify the app boots**

Run: `cd backend && uv run python -c "from app.main import app; print('ok')"`
Expected: `ok` (no import errors).

- [ ] **Step 4: Verify by booting once**

Run: `cd backend && timeout 5 uv run uvicorn app.main:app --port 8765 || true`
Expected: in the captured logs, `AiccAuthClient initialized: base=https://aicommandcenter-production-d7b1.up.railway.app ttl=60s`. The `timeout` will kill the process; that's fine.

- [ ] **Step 5: Commit**

```bash
git add backend/app/auth.py backend/app/main.py
git commit -m "feat(backend): scaffold AICC auth module + wire AiccAuthClient at startup"
```

---

## Backend: User model migration

### Task 6: Add `aicc_user_id` to `User`, drop `AllowedEmail`

**Files:**
- Modify: `backend/app/models/user.py`

- [ ] **Step 1: Edit the model**

REPLACE the entire content of `backend/app/models/user.py` with:

```python
import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    picture: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    aicc_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    last_login: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
```

(The `AllowedEmail` class is removed entirely.)

- [ ] **Step 2: Find and remove all `AllowedEmail` imports**

Run: `cd backend && rg "AllowedEmail" app/`
Note every match — there will be matches in `app/routers/admin.py` and `app/services/user_service.py`. Those will be removed in later tasks; they are expected to break the import right now.

- [ ] **Step 3: Add the on-boot migration**

In `backend/app/main.py`, inside `lifespan()`, locate the existing migration block (the one with `_add_column_if_missing(db, "laws", "source", ...)`). At the END of that block (just before `seed_defaults(db)`), add:

```python
        # AICC auth migration: add aicc_user_id and drop the legacy allowlist.
        # Must run AFTER Base.metadata.create_all (so users exists) and AFTER
        # AllowedEmail is removed from app.models.user (so create_all doesn't
        # recreate the table on the same boot).
        from sqlalchemy import text
        _add_column_if_missing(db, "users", "aicc_user_id", "VARCHAR(64)", None)
        db.execute(text("DROP TABLE IF EXISTS allowed_emails"))
        db.commit()
```

- [ ] **Step 4: Boot and verify schema**

Run: `cd backend && timeout 5 uv run uvicorn app.main:app --port 8765 2>&1 | head -50 || true`
Note: this will fail because `app/services/user_service.py` and `app/routers/admin.py` still reference `AllowedEmail`. That's expected — Tasks 7 and 8 fix it. **Do not commit yet.**

- [ ] **Step 5: Move on to Task 7** before committing this change. (We commit Tasks 6-8 together after the import errors clear.)

---

### Task 7: Strip `AllowedEmail` and `verify_and_upsert_user` from `user_service`

**Files:**
- Modify: `backend/app/services/user_service.py`

- [ ] **Step 1: Replace the file**

REPLACE the entire content of `backend/app/services/user_service.py` with:

```python
"""User helpers.

User identity is fully managed by AICC after the migration. This module is
kept as a placeholder for any future user-related helpers; right now it has
nothing to do.
"""
```

- [ ] **Step 2: Remove the `seed_admin_users(db)` call from `app/main.py`**

In `backend/app/main.py`, find and DELETE these two lines from `lifespan()`:

```python
        from app.services.user_service import seed_admin_users
        seed_admin_users(db)
```

- [ ] **Step 3: Verify nothing else imports the removed symbols**

Run: `cd backend && rg "verify_and_upsert_user|seed_admin_users|ADMIN_EMAILS"`
Expected: no matches in `app/`. Matches inside `tests/` (if any) need to be cleaned up.

- [ ] **Step 4: Don't commit yet** — Task 8 finishes the import cleanup.

---

### Task 8: Strip `verify-user` and whitelist endpoints from `admin.py`

**Files:**
- Modify: `backend/app/routers/admin.py`
- Modify: `backend/app/services/category_service.py` (if it imports `User` directly, no change; just make sure nothing else broke)

- [ ] **Step 1: Edit `app/routers/admin.py`**

In `backend/app/routers/admin.py`:

- DELETE the import `from app.config import NEXTAUTH_SECRET`.
- CHANGE `from app.models.user import AllowedEmail, User` → `from app.models.user import User`.
- DELETE the import line `from app.services.user_service import ADMIN_EMAILS, verify_and_upsert_user`.
- DELETE the entire section starting at `# --- Auth verification (called by NextAuth signIn callback) ---` through the end of the `verify_user` function. This removes:
  - `class VerifyUserRequest`
  - `class VerifyUserResponse`
  - `@router.post("/verify-user", ...)` and the `def verify_user(...)` function
- DELETE the `Annotated, Header` parts of the FastAPI imports if unused after deletions: change `from fastapi import APIRouter, Depends, Header, HTTPException` → `from fastapi import APIRouter, Depends, HTTPException`. Also DELETE `from typing import Annotated` if unused.
- DELETE the entire section starting at `# --- Whitelist management (admin only) ---` through the closing `}` of `remove_from_whitelist`. This removes:
  - `class WhitelistEntry`
  - `class AddEmailRequest`
  - `list_whitelist`, `add_to_whitelist`, `remove_from_whitelist` (3 endpoints)

- [ ] **Step 2: Sanity check the file**

Run: `cd backend && uv run python -c "from app.routers import admin; print(len(admin.router.routes))"`
Expected: a number (the remaining endpoints). No import error.

- [ ] **Step 3: Boot and verify migration**

Run: `cd backend && timeout 6 uv run uvicorn app.main:app --port 8766 2>&1 | tail -40 || true`
Expected: Among the logs, `Added column users.aicc_user_id` (assuming the column doesn't exist yet) and `AiccAuthClient initialized`. No import errors. The `allowed_emails` table is dropped.

- [ ] **Step 4: Confirm schema with sqlite**

Run: `cd backend && uv run python -c "from sqlalchemy import inspect; from app.database import engine; i = inspect(engine); print('users cols:', [c['name'] for c in i.get_columns('users')]); print('allowed_emails exists:', 'allowed_emails' in i.get_table_names())"`
Expected: `users cols: [..., 'aicc_user_id', ...]` and `allowed_emails exists: False`.

- [ ] **Step 5: Commit Tasks 6, 7, 8 together**

```bash
git add backend/app/models/user.py backend/app/services/user_service.py \
        backend/app/routers/admin.py backend/app/main.py
git commit -m "refactor(backend): remove AllowedEmail + verify-user endpoint; add aicc_user_id

User identity now sourced entirely from AICC. Adds nullable users.aicc_user_id
column and drops the allowed_emails table on boot."
```

---

## Backend: `get_current_user` rewrite

### Task 9: TDD — first sign-in creates a `User`

**Files:**
- Create: `backend/tests/test_auth_dependency.py`
- Modify: `backend/app/auth.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_auth_dependency.py`:

```python
"""Tests for get_current_user — the AICC-backed dependency that every
protected endpoint consumes."""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.auth import _map_role, get_current_user
from app.models.user import User
from app.services.aicc_auth_client import AiccUser


def _aicc_user(email="alice@example.com", project_role="admin") -> AiccUser:
    return AiccUser(
        id="aicc-uuid-1",
        email=email,
        name="Alice",
        avatar_url="https://avatar/x",
        project_role=project_role,
    )


def _request_with_bearer(token: str | None):
    """Minimal stand-in for a FastAPI Request object."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = MagicMock()
    req.headers = headers
    return req


@pytest.fixture
def db(tmp_path):
    """Disposable SQLite session with the User table created."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    s = Session()
    yield s
    s.close()


def test_role_map_admin_to_admin():
    assert _map_role("admin") == "admin"
    assert _map_role("ADMIN") == "admin"


def test_role_map_everything_else_to_user():
    assert _map_role("editor") == "user"
    assert _map_role("viewer") == "user"
    assert _map_role(None) == "user"
    assert _map_role("") == "user"
    assert _map_role("anything") == "user"


def test_first_signin_creates_user(db):
    aicc = MagicMock()
    aicc.verify_token.return_value = _aicc_user(project_role="admin")

    user = get_current_user(
        request=_request_with_bearer("tok"),
        token=None,
        db=db,
        aicc=aicc,
    )

    assert user.email == "alice@example.com"
    assert user.role == "admin"
    assert user.aicc_user_id == "aicc-uuid-1"
    assert db.query(User).count() == 1
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd backend && uv run pytest tests/test_auth_dependency.py -v`
Expected: ImportError on `get_current_user` (the stub from Task 5 hasn't defined it yet).

- [ ] **Step 3: Implement `get_current_user`**

In `backend/app/auth.py`, after `get_aicc_client`, ADD:

```python
def _extract_token(request: Request, query_token: str | None) -> str | None:
    """Read bearer token from Authorization header or `?token=` query param.

    The query-param fallback is needed for SSE (EventSource cannot set headers).
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer "):]
    return query_token


def get_current_user(
    request: Request,
    token: str | None = Query(None, alias="token"),
    db: Session = Depends(get_db),
    aicc: AiccAuthClient = Depends(get_aicc_client),
) -> User:
    raw_token = _extract_token(request, token)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    aicc_user = aicc.verify_token(raw_token)
    if aicc_user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    desired_role = _map_role(aicc_user.project_role)
    user = db.query(User).filter(User.email == aicc_user.email).first()
    if user is None:
        user = User(
            email=aicc_user.email,
            name=aicc_user.name,
            picture=aicc_user.avatar_url,
            role=desired_role,
            aicc_user_id=aicc_user.id,
            last_login=datetime.datetime.utcnow(),
        )
        db.add(user)
        logger.info("[auth] created local user from AICC: %s (role=%s)", user.email, desired_role)
    else:
        if user.role != desired_role:
            logger.info("[auth] role change for %s: %s -> %s", user.email, user.role, desired_role)
            user.role = desired_role
        if user.name != aicc_user.name:
            user.name = aicc_user.name
        if user.picture != aicc_user.avatar_url:
            user.picture = aicc_user.avatar_url
        if user.aicc_user_id != aicc_user.id:
            user.aicc_user_id = aicc_user.id
        user.last_login = datetime.datetime.utcnow()

    db.commit()
    db.refresh(user)
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd backend && uv run pytest tests/test_auth_dependency.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/auth.py backend/tests/test_auth_dependency.py
git commit -m "feat(backend): get_current_user verifies via AICC + upserts local user"
```

---

### Task 10: TDD — existing user gets role/name/picture synced

**Files:**
- Modify: `backend/tests/test_auth_dependency.py`

- [ ] **Step 1: Add the failing tests**

Append to `backend/tests/test_auth_dependency.py`:

```python
def test_existing_user_role_synced_from_aicc(db):
    db.add(User(
        email="bob@example.com",
        name="Old Name",
        picture="old-pic",
        role="user",
        aicc_user_id="aicc-uuid-2",
    ))
    db.commit()

    aicc = MagicMock()
    aicc.verify_token.return_value = AiccUser(
        id="aicc-uuid-2",
        email="bob@example.com",
        name="New Name",
        avatar_url="new-pic",
        project_role="admin",  # promoted in AICC
    )

    user = get_current_user(_request_with_bearer("tok"), None, db, aicc)
    assert user.role == "admin"
    assert user.name == "New Name"
    assert user.picture == "new-pic"


def test_existing_user_demoted_when_aicc_strips_admin(db):
    db.add(User(
        email="charlie@example.com",
        role="admin",
        aicc_user_id="aicc-uuid-3",
    ))
    db.commit()

    aicc = MagicMock()
    aicc.verify_token.return_value = AiccUser(
        id="aicc-uuid-3",
        email="charlie@example.com",
        name=None,
        avatar_url=None,
        project_role="viewer",
    )

    user = get_current_user(_request_with_bearer("tok"), None, db, aicc)
    assert user.role == "user"


def test_no_token_raises_401(db):
    aicc = MagicMock()
    with pytest.raises(HTTPException) as exc:
        get_current_user(_request_with_bearer(None), None, db, aicc)
    assert exc.value.status_code == 401
    aicc.verify_token.assert_not_called()


def test_invalid_token_raises_401(db):
    aicc = MagicMock()
    aicc.verify_token.return_value = None
    with pytest.raises(HTTPException) as exc:
        get_current_user(_request_with_bearer("garbage"), None, db, aicc)
    assert exc.value.status_code == 401


def test_query_token_fallback_for_sse(db):
    aicc = MagicMock()
    aicc.verify_token.return_value = _aicc_user()
    req = MagicMock()
    req.headers = {}  # no Authorization header
    user = get_current_user(req, "tok-via-query", db, aicc)
    assert user.email == "alice@example.com"
    aicc.verify_token.assert_called_once_with("tok-via-query")


def test_require_admin_accepts_admin(db):
    from app.auth import require_admin
    admin_user = User(email="x", role="admin")
    assert require_admin(admin_user) is admin_user


def test_require_admin_rejects_non_admin(db):
    from app.auth import require_admin
    plain_user = User(email="x", role="user")
    with pytest.raises(HTTPException) as exc:
        require_admin(plain_user)
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run, verify they pass**

Run: `cd backend && uv run pytest tests/test_auth_dependency.py -v`
Expected: 11 PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_auth_dependency.py
git commit -m "test(backend): cover sync, demotion, 401, query-token, require_admin"
```

---

### Task 11: Confirm full backend test suite still passes

**Files:** none

- [ ] **Step 1: Run the full suite**

Run: `cd backend && uv run pytest -x`
Expected: all green. If anything fails, expect failures only in tests that referenced `NEXTAUTH_SECRET`, `AllowedEmail`, `verify_and_upsert_user`, `seed_admin_users`, or `ADMIN_EMAILS`. Fix each by removing or rewriting against the new auth (minor — they're test fixtures that shouldn't be doing this anymore).

- [ ] **Step 2: If any fixture file mocks the old auth, replace with the AICC mock pattern**

Use this pattern (from `tests/test_auth_dependency.py`):
```python
from unittest.mock import MagicMock
aicc = MagicMock()
aicc.verify_token.return_value = AiccUser(id="x", email="...", project_role="admin")
app.dependency_overrides[get_aicc_client] = lambda: aicc
```

- [ ] **Step 3: Re-run and commit any test fixes**

Run: `cd backend && uv run pytest -x`
Expected: all green.

```bash
git add backend/tests/
git commit -m "test(backend): port remaining auth-touching tests to AICC mock pattern"
```

(If no fixes were needed, skip the commit.)

---

## Frontend: AICC auth client

### Task 12: Pure PKCE helpers + tests

**Files:**
- Create: `frontend/src/lib/aicc-auth.ts`
- Create: `frontend/src/lib/aicc-auth.test.ts`

> **Read first:** `frontend/AGENTS.md` warns the Next.js APIs may differ from your training data. Skim `frontend/node_modules/next/dist/docs/` for `cookies()`, `NextRequest`, `NextResponse`, and `redirect()` before writing the route handlers in later tasks. You don't need it for this task (pure functions only).

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/aicc-auth.test.ts`:

```typescript
import { describe, expect, test } from "vitest";
import {
  base64UrlEncode,
  buildAuthorizeUrl,
  generatePkceVerifier,
  pkceChallenge,
} from "./aicc-auth";

describe("base64UrlEncode", () => {
  test("encodes bytes per RFC 7636 (no padding, URL-safe alphabet)", async () => {
    // Known PKCE test vector from RFC 7636 Appendix B.
    const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
    const challenge = await pkceChallenge(verifier);
    expect(challenge).toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
  });
});

describe("generatePkceVerifier", () => {
  test("produces a 43+ char base64url string with no padding", () => {
    const v = generatePkceVerifier();
    expect(v.length).toBeGreaterThanOrEqual(43);
    expect(v).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  test("produces unique values across calls", () => {
    const a = generatePkceVerifier();
    const b = generatePkceVerifier();
    expect(a).not.toBe(b);
  });
});

describe("buildAuthorizeUrl", () => {
  test("builds an /auth/authorize URL with all required PKCE query params", () => {
    const url = buildAuthorizeUrl({
      baseUrl: "https://aicc.example",
      clientId: "themis-web",
      redirectUri: "https://themis.example/auth/callback",
      state: "state-123",
      codeChallenge: "challenge-abc",
    });
    const parsed = new URL(url);
    expect(parsed.origin + parsed.pathname).toBe("https://aicc.example/auth/authorize");
    expect(parsed.searchParams.get("client_id")).toBe("themis-web");
    expect(parsed.searchParams.get("redirect_uri")).toBe("https://themis.example/auth/callback");
    expect(parsed.searchParams.get("state")).toBe("state-123");
    expect(parsed.searchParams.get("code_challenge")).toBe("challenge-abc");
    expect(parsed.searchParams.get("code_challenge_method")).toBe("S256");
    expect(parsed.searchParams.get("identity_provider")).toBe("google");
  });
});
```

- [ ] **Step 2: Run, verify they fail**

Run: `cd frontend && npm test -- aicc-auth`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the helpers**

Create `frontend/src/lib/aicc-auth.ts`:

```typescript
/**
 * AICC auth client — pure HTTP helpers around AICC's PKCE endpoints.
 *
 * No cookie / session state lives here; route handlers drive that.
 */

export function base64UrlEncode(bytes: Uint8Array): string {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function generatePkceVerifier(): string {
  const buf = new Uint8Array(32);
  crypto.getRandomValues(buf);
  return base64UrlEncode(buf);
}

export async function pkceChallenge(verifier: string): Promise<string> {
  const data = new TextEncoder().encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return base64UrlEncode(new Uint8Array(digest));
}

export interface AuthorizeUrlInput {
  baseUrl: string;
  clientId: string;
  redirectUri: string;
  state: string;
  codeChallenge: string;
  identityProvider?: string;
}

export function buildAuthorizeUrl(input: AuthorizeUrlInput): string {
  const url = new URL(`${input.baseUrl.replace(/\/$/, "")}/auth/authorize`);
  url.searchParams.set("client_id", input.clientId);
  url.searchParams.set("redirect_uri", input.redirectUri);
  url.searchParams.set("state", input.state);
  url.searchParams.set("code_challenge", input.codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("identity_provider", input.identityProvider ?? "google");
  return url.toString();
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  token_type: "Bearer";
  user?: unknown;
}

export async function exchangeCodeForTokens(input: {
  baseUrl: string;
  code: string;
  codeVerifier: string;
}): Promise<TokenResponse> {
  const r = await fetch(`${input.baseUrl.replace(/\/$/, "")}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      grant_type: "authorization_code",
      code: input.code,
      code_verifier: input.codeVerifier,
    }),
  });
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`[aicc-auth] /auth/token exchange failed (${r.status}): ${body}`);
  }
  return r.json();
}

export async function refreshTokens(input: {
  baseUrl: string;
  refreshToken: string;
}): Promise<TokenResponse> {
  const r = await fetch(`${input.baseUrl.replace(/\/$/, "")}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      grant_type: "refresh_token",
      refresh_token: input.refreshToken,
    }),
  });
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`[aicc-auth] /auth/token refresh failed (${r.status}): ${body}`);
  }
  return r.json();
}

export async function revokeToken(input: {
  baseUrl: string;
  accessToken: string;
}): Promise<void> {
  await fetch(`${input.baseUrl.replace(/\/$/, "")}/auth/logout`, {
    method: "POST",
    headers: { Authorization: `Bearer ${input.accessToken}` },
  }).catch((e) => {
    console.error("[aicc-auth] /auth/logout failed:", e);
  });
}

export interface AiccMe {
  id: string;
  email: string;
  name: string | null;
  avatarUrl: string | null;
  projectRole: string | null;
}

export async function fetchAiccMe(input: {
  baseUrl: string;
  accessToken: string;
}): Promise<AiccMe | null> {
  const r = await fetch(`${input.baseUrl.replace(/\/$/, "")}/auth/me`, {
    headers: { Authorization: `Bearer ${input.accessToken}` },
  });
  if (r.status === 401) return null;
  if (!r.ok) {
    throw new Error(`[aicc-auth] /auth/me failed (${r.status})`);
  }
  return r.json();
}
```

- [ ] **Step 4: Run, verify all tests pass**

Run: `cd frontend && npm test -- aicc-auth`
Expected: 4 PASS (1 in `base64UrlEncode`, 2 in `generatePkceVerifier`, 1 in `buildAuthorizeUrl`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/aicc-auth.ts frontend/src/lib/aicc-auth.test.ts
git commit -m "feat(frontend): pure AICC PKCE helpers (verifier, challenge, exchange, refresh)"
```

---

### Task 13: Cookie helpers — sign + verify the short-lived `aicc_pkce` cookie

**Files:**
- Create: `frontend/src/lib/cookies.ts`
- Create: `frontend/src/lib/cookies.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/cookies.test.ts`:

```typescript
import { describe, expect, test } from "vitest";
import { signPkceCookie, verifyPkceCookie } from "./cookies";

const SECRET = "test-secret-at-least-32-bytes-long-aaaaaaaa";

describe("PKCE cookie sign/verify", () => {
  test("verify returns the original payload", async () => {
    const payload = { verifier: "v123", state: "s123", callbackUrl: "/laws" };
    const signed = await signPkceCookie(payload, SECRET);
    const out = await verifyPkceCookie(signed, SECRET);
    expect(out).toEqual(payload);
  });

  test("verify returns null when signature is tampered", async () => {
    const payload = { verifier: "v", state: "s", callbackUrl: "/" };
    const signed = await signPkceCookie(payload, SECRET);
    const tampered = signed.slice(0, -2) + (signed.endsWith("ab") ? "cd" : "ab");
    expect(await verifyPkceCookie(tampered, SECRET)).toBeNull();
  });

  test("verify returns null when wrong secret is used", async () => {
    const payload = { verifier: "v", state: "s", callbackUrl: "/" };
    const signed = await signPkceCookie(payload, SECRET);
    expect(await verifyPkceCookie(signed, "different-secret-xxxxxxxxxxxxxxxxxxxx")).toBeNull();
  });
});
```

- [ ] **Step 2: Run, verify they fail**

Run: `cd frontend && npm test -- cookies`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the helpers**

Create `frontend/src/lib/cookies.ts`:

```typescript
/**
 * Cookie helpers for the AICC auth flow.
 *
 * The `aicc_pkce` cookie carries the PKCE verifier across the redirect to
 * AICC and back. Because it lives on the browser between requests, it must be
 * tamper-evident: we sign it with HMAC-SHA256 over the JSON payload.
 */
import { base64UrlEncode } from "./aicc-auth";

export interface PkceCookiePayload {
  verifier: string;
  state: string;
  callbackUrl: string;
}

async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

function timingSafeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

function b64UrlDecode(s: string): Uint8Array {
  const pad = s.length % 4 === 0 ? "" : "=".repeat(4 - (s.length % 4));
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + pad);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export async function signPkceCookie(payload: PkceCookiePayload, secret: string): Promise<string> {
  const json = JSON.stringify(payload);
  const body = base64UrlEncode(new TextEncoder().encode(json));
  const key = await hmacKey(secret);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body)));
  return `${body}.${base64UrlEncode(sig)}`;
}

export async function verifyPkceCookie(
  cookie: string,
  secret: string,
): Promise<PkceCookiePayload | null> {
  const dot = cookie.indexOf(".");
  if (dot < 0) return null;
  const body = cookie.slice(0, dot);
  const sig = cookie.slice(dot + 1);
  const key = await hmacKey(secret);
  const expected = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body)));
  let actual: Uint8Array;
  try {
    actual = b64UrlDecode(sig);
  } catch {
    return null;
  }
  if (!timingSafeEqual(expected, actual)) return null;
  try {
    const json = new TextDecoder().decode(b64UrlDecode(body));
    return JSON.parse(json) as PkceCookiePayload;
  } catch {
    return null;
  }
}
```

- [ ] **Step 4: Run, verify tests pass**

Run: `cd frontend && npm test -- cookies`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/cookies.ts frontend/src/lib/cookies.test.ts
git commit -m "feat(frontend): HMAC-signed PKCE cookie helpers"
```

---

## Frontend: route handlers

### Task 14: `/api/auth/login` — generate PKCE, set cookie, redirect

**Files:**
- Create: `frontend/src/app/api/auth/login/route.ts`
- Create: `frontend/src/app/api/auth/login/route.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/app/api/auth/login/route.test.ts`:

```typescript
import { describe, expect, test, beforeEach, vi } from "vitest";
import { GET } from "./route";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_AICC_AUTH_BASE_URL", "https://aicc.test");
  vi.stubEnv("NEXT_PUBLIC_AICC_AUTH_CLIENT_ID", "themis-web");
  vi.stubEnv("NEXT_PUBLIC_AICC_AUTH_REDIRECT", "https://themis.test/auth/callback");
  vi.stubEnv("AICC_PKCE_COOKIE_SECRET", "test-secret-at-least-32-bytes-long-aaaaa");
});

function makeReq(url: string): Request {
  return new Request(url);
}

describe("GET /api/auth/login", () => {
  test("redirects to AICC /auth/authorize with PKCE params and sets aicc_pkce cookie", async () => {
    const res = await GET(makeReq("https://themis.test/api/auth/login?callbackUrl=/laws"));
    expect(res.status).toBe(302);

    const location = res.headers.get("location")!;
    const u = new URL(location);
    expect(u.origin + u.pathname).toBe("https://aicc.test/auth/authorize");
    expect(u.searchParams.get("client_id")).toBe("themis-web");
    expect(u.searchParams.get("redirect_uri")).toBe("https://themis.test/auth/callback");
    expect(u.searchParams.get("code_challenge_method")).toBe("S256");
    expect(u.searchParams.get("state")).toBeTruthy();
    expect(u.searchParams.get("code_challenge")).toBeTruthy();

    const setCookie = res.headers.get("set-cookie")!;
    expect(setCookie).toContain("aicc_pkce=");
    expect(setCookie.toLowerCase()).toContain("httponly");
    expect(setCookie.toLowerCase()).toContain("samesite=lax");
    expect(setCookie.toLowerCase()).toContain("path=/");
  });

  test("defaults callbackUrl to / when missing", async () => {
    const res = await GET(makeReq("https://themis.test/api/auth/login"));
    expect(res.status).toBe(302);
    // We can't easily inspect the cookie payload without the secret here,
    // but the response shape (302 + cookie) is enough for this test.
    expect(res.headers.get("set-cookie")).toContain("aicc_pkce=");
  });
});
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd frontend && npm test -- api/auth/login`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the handler**

Create `frontend/src/app/api/auth/login/route.ts`:

```typescript
import {
  buildAuthorizeUrl,
  generatePkceVerifier,
  pkceChallenge,
} from "@/lib/aicc-auth";
import { signPkceCookie } from "@/lib/cookies";

const AICC_AUTH_BASE_URL = process.env.NEXT_PUBLIC_AICC_AUTH_BASE_URL!;
const AICC_AUTH_CLIENT_ID = process.env.NEXT_PUBLIC_AICC_AUTH_CLIENT_ID!;
const AICC_AUTH_REDIRECT = process.env.NEXT_PUBLIC_AICC_AUTH_REDIRECT!;
const PKCE_COOKIE_SECRET = process.env.AICC_PKCE_COOKIE_SECRET!;

const PKCE_COOKIE_MAX_AGE_SECONDS = 5 * 60; // 5 minutes — only needs to survive the AICC roundtrip

function isProdCookie(): boolean {
  // Only production deploys serve over HTTPS. Avoid `Secure` in dev so cookies
  // work on http://localhost.
  return process.env.NODE_ENV === "production";
}

function setCookieHeader(name: string, value: string, maxAgeSeconds: number): string {
  const parts = [
    `${name}=${value}`,
    "Path=/",
    `Max-Age=${maxAgeSeconds}`,
    "HttpOnly",
    "SameSite=Lax",
  ];
  if (isProdCookie()) parts.push("Secure");
  return parts.join("; ");
}

export async function GET(req: Request): Promise<Response> {
  const u = new URL(req.url);
  const callbackUrl = u.searchParams.get("callbackUrl") || "/";

  const verifier = generatePkceVerifier();
  const challenge = await pkceChallenge(verifier);
  const state = crypto.randomUUID();

  const cookieValue = await signPkceCookie(
    { verifier, state, callbackUrl },
    PKCE_COOKIE_SECRET,
  );

  const authorizeUrl = buildAuthorizeUrl({
    baseUrl: AICC_AUTH_BASE_URL,
    clientId: AICC_AUTH_CLIENT_ID,
    redirectUri: AICC_AUTH_REDIRECT,
    state,
    codeChallenge: challenge,
  });

  const headers = new Headers();
  headers.set("Location", authorizeUrl);
  headers.append("Set-Cookie", setCookieHeader("aicc_pkce", cookieValue, PKCE_COOKIE_MAX_AGE_SECONDS));
  return new Response(null, { status: 302, headers });
}
```

- [ ] **Step 4: Run, verify tests pass**

Run: `cd frontend && npm test -- api/auth/login`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api/auth/login/
git commit -m "feat(frontend): /api/auth/login generates PKCE and redirects to AICC"
```

---

### Task 15: `/api/auth/callback` — exchange code, set token cookies, redirect

**Files:**
- Create: `frontend/src/app/api/auth/callback/route.ts`
- Create: `frontend/src/app/api/auth/callback/route.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/app/api/auth/callback/route.test.ts`:

```typescript
import { describe, expect, test, beforeEach, vi } from "vitest";
import { signPkceCookie } from "@/lib/cookies";

const SECRET = "test-secret-at-least-32-bytes-long-aaaaa";
const BASE = "https://aicc.test";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_AICC_AUTH_BASE_URL", BASE);
  vi.stubEnv("AICC_PKCE_COOKIE_SECRET", SECRET);
  vi.unstubAllGlobals();
});

async function makeReqWithCookie(opts: {
  query: string;
  pkceCookie?: string;
}): Promise<Request> {
  const headers = new Headers();
  if (opts.pkceCookie !== undefined) {
    headers.set("cookie", `aicc_pkce=${opts.pkceCookie}`);
  }
  return new Request(`https://themis.test/api/auth/callback?${opts.query}`, { headers });
}

function mockTokenEndpoint(response: { status: number; body: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === `${BASE}/auth/token` && init?.method === "POST") {
        return new Response(JSON.stringify(response.body), { status: response.status });
      }
      throw new Error(`unexpected fetch: ${url}`);
    }),
  );
}

describe("GET /api/auth/callback", () => {
  test("exchanges code, sets aicc_access + aicc_refresh + aicc_access_exp cookies, redirects to callbackUrl", async () => {
    const cookie = await signPkceCookie(
      { verifier: "verifier-abc", state: "state-xyz", callbackUrl: "/laws" },
      SECRET,
    );
    mockTokenEndpoint({
      status: 200,
      body: {
        access_token: "ACCESS",
        refresh_token: "REFRESH",
        expires_in: 900,
        token_type: "Bearer",
      },
    });

    const { GET } = await import("./route");
    const res = await GET(await makeReqWithCookie({
      query: "code=CODE&state=state-xyz",
      pkceCookie: cookie,
    }));

    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toBe("https://themis.test/laws");

    const setCookies = res.headers.getSetCookie();
    const joined = setCookies.join("\n");
    expect(joined).toContain("aicc_access=ACCESS");
    expect(joined).toContain("aicc_refresh=REFRESH");
    expect(joined).toContain("aicc_access_exp=");
    // PKCE cookie cleared
    expect(joined).toMatch(/aicc_pkce=;.*Max-Age=0/i);
  });

  test("returns 400 when state does not match", async () => {
    const cookie = await signPkceCookie(
      { verifier: "v", state: "expected", callbackUrl: "/" },
      SECRET,
    );
    const { GET } = await import("./route");
    const res = await GET(await makeReqWithCookie({
      query: "code=CODE&state=different",
      pkceCookie: cookie,
    }));
    expect(res.status).toBe(400);
  });

  test("returns 400 when aicc_pkce cookie is missing", async () => {
    const { GET } = await import("./route");
    const res = await GET(await makeReqWithCookie({ query: "code=C&state=S" }));
    expect(res.status).toBe(400);
  });

  test("returns 502 when AICC /auth/token returns 5xx", async () => {
    const cookie = await signPkceCookie(
      { verifier: "v", state: "s", callbackUrl: "/" },
      SECRET,
    );
    mockTokenEndpoint({ status: 500, body: { error: "boom" } });
    const { GET } = await import("./route");
    const res = await GET(await makeReqWithCookie({
      query: "code=C&state=s",
      pkceCookie: cookie,
    }));
    expect(res.status).toBe(502);
  });
});
```

- [ ] **Step 2: Run, verify they fail**

Run: `cd frontend && npm test -- api/auth/callback`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the handler**

Create `frontend/src/app/api/auth/callback/route.ts`:

```typescript
import { exchangeCodeForTokens } from "@/lib/aicc-auth";
import { verifyPkceCookie } from "@/lib/cookies";

const AICC_AUTH_BASE_URL = process.env.NEXT_PUBLIC_AICC_AUTH_BASE_URL!;
const PKCE_COOKIE_SECRET = process.env.AICC_PKCE_COOKIE_SECRET!;
const REFRESH_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60; // 30 days

function isProdCookie(): boolean {
  return process.env.NODE_ENV === "production";
}

function buildSetCookie(opts: {
  name: string;
  value: string;
  maxAgeSeconds: number;
  httpOnly?: boolean;
}): string {
  const parts = [
    `${opts.name}=${opts.value}`,
    "Path=/",
    `Max-Age=${opts.maxAgeSeconds}`,
    "SameSite=Lax",
  ];
  if (opts.httpOnly !== false) parts.push("HttpOnly");
  if (isProdCookie()) parts.push("Secure");
  return parts.join("; ");
}

function clearCookieHeader(name: string): string {
  const parts = [`${name}=`, "Path=/", "Max-Age=0", "SameSite=Lax", "HttpOnly"];
  if (isProdCookie()) parts.push("Secure");
  return parts.join("; ");
}

function readPkceCookie(req: Request): string | null {
  const raw = req.headers.get("cookie") ?? "";
  for (const part of raw.split(/;\s*/)) {
    if (part.startsWith("aicc_pkce=")) return part.slice("aicc_pkce=".length);
  }
  return null;
}

export async function GET(req: Request): Promise<Response> {
  const u = new URL(req.url);
  const code = u.searchParams.get("code");
  const state = u.searchParams.get("state");
  const cookieRaw = readPkceCookie(req);

  if (!code || !state || !cookieRaw) {
    console.error("[auth] missing PKCE cookie or query params on callback");
    return new Response("Sign-in session expired, please try again.", { status: 400 });
  }

  const cookie = await verifyPkceCookie(cookieRaw, PKCE_COOKIE_SECRET);
  if (!cookie) {
    console.error("[auth] invalid PKCE cookie signature");
    return new Response("Sign-in session expired, please try again.", { status: 400 });
  }
  if (cookie.state !== state) {
    console.error("[auth] state mismatch: cookie=%s param=%s", cookie.state, state);
    return new Response("Sign-in session expired, please try again.", { status: 400 });
  }

  let tokens;
  try {
    tokens = await exchangeCodeForTokens({
      baseUrl: AICC_AUTH_BASE_URL,
      code,
      codeVerifier: cookie.verifier,
    });
  } catch (e) {
    console.error("[auth] /auth/token exchange failed:", e);
    return new Response("Auth provider error", { status: 502 });
  }

  const expEpochMs = Date.now() + tokens.expires_in * 1000;
  const dest = new URL(cookie.callbackUrl, u.origin).toString();

  const headers = new Headers();
  headers.set("Location", dest);
  headers.append("Set-Cookie", buildSetCookie({
    name: "aicc_access",
    value: tokens.access_token,
    maxAgeSeconds: tokens.expires_in,
  }));
  headers.append("Set-Cookie", buildSetCookie({
    name: "aicc_refresh",
    value: tokens.refresh_token,
    maxAgeSeconds: REFRESH_COOKIE_MAX_AGE_SECONDS,
  }));
  headers.append("Set-Cookie", buildSetCookie({
    name: "aicc_access_exp",
    value: String(expEpochMs),
    maxAgeSeconds: tokens.expires_in,
    httpOnly: false, // JS reads this to know when to refresh
  }));
  headers.append("Set-Cookie", clearCookieHeader("aicc_pkce"));

  return new Response(null, { status: 302, headers });
}
```

- [ ] **Step 4: Run, verify tests pass**

Run: `cd frontend && npm test -- api/auth/callback`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api/auth/callback/
git commit -m "feat(frontend): /api/auth/callback exchanges code and sets token cookies"
```

---

### Task 16: Rewrite `/api/token` — read AICC cookies, refresh near expiry

**Files:**
- Modify: `frontend/src/app/api/token/route.ts`
- Create: `frontend/src/app/api/token/route.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/app/api/token/route.test.ts`:

```typescript
import { describe, expect, test, beforeEach, vi } from "vitest";

const BASE = "https://aicc.test";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_AICC_AUTH_BASE_URL", BASE);
  vi.unstubAllGlobals();
  vi.resetModules();
});

function reqWithCookies(cookies: Record<string, string>): Request {
  const headers = new Headers();
  headers.set("cookie", Object.entries(cookies).map(([k, v]) => `${k}=${v}`).join("; "));
  return new Request("https://themis.test/api/token", { headers });
}

describe("GET /api/token", () => {
  test("returns the cookie's access token when fresh", async () => {
    const exp = Date.now() + 10 * 60 * 1000; // 10 min out
    const { GET } = await import("./route");
    const res = await GET(reqWithCookies({
      aicc_access: "FRESH",
      aicc_access_exp: String(exp),
      aicc_refresh: "REFRESH",
    }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.token).toBe("FRESH");
    expect(body.expiresAt).toBe(exp);
  });

  test("returns 401 when no aicc_access cookie", async () => {
    const { GET } = await import("./route");
    const res = await GET(reqWithCookies({}));
    expect(res.status).toBe(401);
    const body = await res.json();
    expect(body.token).toBeNull();
  });

  test("refreshes token when within 60s of expiry, sets new cookies, returns new token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === `${BASE}/auth/token`) {
          return new Response(JSON.stringify({
            access_token: "NEW_ACCESS",
            refresh_token: "NEW_REFRESH",
            expires_in: 900,
            token_type: "Bearer",
          }), { status: 200 });
        }
        throw new Error("unexpected fetch");
      }),
    );
    const exp = Date.now() + 10 * 1000; // 10s — well within refresh window
    const { GET } = await import("./route");
    const res = await GET(reqWithCookies({
      aicc_access: "OLD",
      aicc_access_exp: String(exp),
      aicc_refresh: "OLD_REFRESH",
    }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.token).toBe("NEW_ACCESS");
    const setCookies = res.headers.getSetCookie().join("\n");
    expect(setCookies).toContain("aicc_access=NEW_ACCESS");
    expect(setCookies).toContain("aicc_refresh=NEW_REFRESH");
  });

  test("clears cookies and returns 401 when refresh fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ error: "invalid_grant" }), { status: 400 })),
    );
    const exp = Date.now() + 10 * 1000;
    const { GET } = await import("./route");
    const res = await GET(reqWithCookies({
      aicc_access: "OLD",
      aicc_access_exp: String(exp),
      aicc_refresh: "EXPIRED_REFRESH",
    }));
    expect(res.status).toBe(401);
    const setCookies = res.headers.getSetCookie().join("\n");
    expect(setCookies).toMatch(/aicc_access=;.*Max-Age=0/i);
    expect(setCookies).toMatch(/aicc_refresh=;.*Max-Age=0/i);
  });
});
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd frontend && npm test -- api/token`
Expected: FAIL — current `/api/token/route.ts` uses NextAuth.

- [ ] **Step 3: Replace `/api/token/route.ts`**

REPLACE `frontend/src/app/api/token/route.ts` with:

```typescript
import { refreshTokens } from "@/lib/aicc-auth";

const AICC_AUTH_BASE_URL = process.env.NEXT_PUBLIC_AICC_AUTH_BASE_URL!;
const REFRESH_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60; // 30 days
const REFRESH_THRESHOLD_MS = 60 * 1000; // refresh when access expires within 60s

function isProdCookie(): boolean {
  return process.env.NODE_ENV === "production";
}

function buildSetCookie(opts: {
  name: string;
  value: string;
  maxAgeSeconds: number;
  httpOnly?: boolean;
}): string {
  const parts = [
    `${opts.name}=${opts.value}`,
    "Path=/",
    `Max-Age=${opts.maxAgeSeconds}`,
    "SameSite=Lax",
  ];
  if (opts.httpOnly !== false) parts.push("HttpOnly");
  if (isProdCookie()) parts.push("Secure");
  return parts.join("; ");
}

function clearCookieHeader(name: string): string {
  const parts = [`${name}=`, "Path=/", "Max-Age=0", "SameSite=Lax", "HttpOnly"];
  if (isProdCookie()) parts.push("Secure");
  return parts.join("; ");
}

function readCookies(req: Request): Record<string, string> {
  const raw = req.headers.get("cookie") ?? "";
  const out: Record<string, string> = {};
  for (const part of raw.split(/;\s*/)) {
    const eq = part.indexOf("=");
    if (eq > 0) out[part.slice(0, eq)] = part.slice(eq + 1);
  }
  return out;
}

// Per-process mutex keyed by hash(refresh_token) so concurrent /api/token
// calls during the refresh window collapse into a single AICC roundtrip.
const inflight = new Map<string, Promise<{ access: string; expEpochMs: number; refresh: string }>>();

async function refreshOnce(refreshToken: string) {
  const key = refreshToken; // sufficient as a key inside a single process
  const existing = inflight.get(key);
  if (existing) return existing;
  const p = (async () => {
    const tokens = await refreshTokens({ baseUrl: AICC_AUTH_BASE_URL, refreshToken });
    return {
      access: tokens.access_token,
      expEpochMs: Date.now() + tokens.expires_in * 1000,
      refresh: tokens.refresh_token,
    };
  })();
  inflight.set(key, p);
  try {
    return await p;
  } finally {
    inflight.delete(key);
  }
}

export async function GET(req: Request): Promise<Response> {
  const cookies = readCookies(req);
  const access = cookies["aicc_access"];
  const refresh = cookies["aicc_refresh"];
  const expRaw = cookies["aicc_access_exp"];

  if (!access || !refresh) {
    return Response.json({ token: null }, { status: 401 });
  }

  const expEpochMs = expRaw ? Number(expRaw) : 0;
  const needsRefresh = !expRaw || expEpochMs - Date.now() < REFRESH_THRESHOLD_MS;

  if (!needsRefresh) {
    return Response.json({ token: access, expiresAt: expEpochMs }, { status: 200 });
  }

  let refreshed;
  try {
    refreshed = await refreshOnce(refresh);
  } catch (e) {
    console.error("[auth] refresh failed:", e);
    const headers = new Headers();
    headers.append("Set-Cookie", clearCookieHeader("aicc_access"));
    headers.append("Set-Cookie", clearCookieHeader("aicc_refresh"));
    headers.append("Set-Cookie", clearCookieHeader("aicc_access_exp"));
    return new Response(JSON.stringify({ token: null }), { status: 401, headers });
  }

  const headers = new Headers();
  headers.append("Set-Cookie", buildSetCookie({
    name: "aicc_access",
    value: refreshed.access,
    maxAgeSeconds: Math.floor((refreshed.expEpochMs - Date.now()) / 1000),
  }));
  headers.append("Set-Cookie", buildSetCookie({
    name: "aicc_refresh",
    value: refreshed.refresh,
    maxAgeSeconds: REFRESH_COOKIE_MAX_AGE_SECONDS,
  }));
  headers.append("Set-Cookie", buildSetCookie({
    name: "aicc_access_exp",
    value: String(refreshed.expEpochMs),
    maxAgeSeconds: Math.floor((refreshed.expEpochMs - Date.now()) / 1000),
    httpOnly: false,
  }));

  return new Response(
    JSON.stringify({ token: refreshed.access, expiresAt: refreshed.expEpochMs }),
    { status: 200, headers },
  );
}
```

- [ ] **Step 4: Run, verify tests pass**

Run: `cd frontend && npm test -- api/token`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api/token/
git commit -m "feat(frontend): /api/token reads AICC cookies + transparently refreshes"
```

---

### Task 17: `/api/auth/logout` — revoke + clear cookies

**Files:**
- Create: `frontend/src/app/api/auth/logout/route.ts`
- Create: `frontend/src/app/api/auth/logout/route.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/app/api/auth/logout/route.test.ts`:

```typescript
import { describe, expect, test, beforeEach, vi } from "vitest";

const BASE = "https://aicc.test";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_AICC_AUTH_BASE_URL", BASE);
  vi.unstubAllGlobals();
  vi.resetModules();
});

function reqWithCookies(cookies: Record<string, string>): Request {
  const headers = new Headers();
  headers.set("cookie", Object.entries(cookies).map(([k, v]) => `${k}=${v}`).join("; "));
  return new Request("https://themis.test/api/auth/logout", { method: "POST", headers });
}

describe("POST /api/auth/logout", () => {
  test("calls AICC /auth/logout, clears cookies, redirects to /auth/signin", async () => {
    const aiccCalls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      aiccCalls.push(`${init?.method ?? "GET"} ${url}`);
      return new Response("{}", { status: 200 });
    }));

    const { POST } = await import("./route");
    const res = await POST(reqWithCookies({ aicc_access: "TOK" }));
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toBe("/auth/signin");
    expect(aiccCalls).toContain(`POST ${BASE}/auth/logout`);

    const setCookies = res.headers.getSetCookie().join("\n");
    expect(setCookies).toMatch(/aicc_access=;.*Max-Age=0/i);
    expect(setCookies).toMatch(/aicc_refresh=;.*Max-Age=0/i);
    expect(setCookies).toMatch(/aicc_access_exp=;.*Max-Age=0/i);
  });

  test("clears cookies even if AICC logout fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("boom"); }));
    const { POST } = await import("./route");
    const res = await POST(reqWithCookies({ aicc_access: "TOK" }));
    expect(res.status).toBe(302);
    expect(res.headers.getSetCookie().join("\n")).toMatch(/aicc_access=;/i);
  });
});
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd frontend && npm test -- api/auth/logout`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the handler**

Create `frontend/src/app/api/auth/logout/route.ts`:

```typescript
import { revokeToken } from "@/lib/aicc-auth";

const AICC_AUTH_BASE_URL = process.env.NEXT_PUBLIC_AICC_AUTH_BASE_URL!;

function isProdCookie(): boolean {
  return process.env.NODE_ENV === "production";
}

function clearCookieHeader(name: string): string {
  const parts = [`${name}=`, "Path=/", "Max-Age=0", "SameSite=Lax", "HttpOnly"];
  if (isProdCookie()) parts.push("Secure");
  return parts.join("; ");
}

function readAccess(req: Request): string | null {
  const raw = req.headers.get("cookie") ?? "";
  for (const part of raw.split(/;\s*/)) {
    if (part.startsWith("aicc_access=")) return part.slice("aicc_access=".length);
  }
  return null;
}

export async function POST(req: Request): Promise<Response> {
  const access = readAccess(req);
  if (access) {
    await revokeToken({ baseUrl: AICC_AUTH_BASE_URL, accessToken: access }).catch((e) => {
      console.error("[auth] revoke failed:", e);
    });
  }
  const headers = new Headers();
  headers.set("Location", "/auth/signin");
  headers.append("Set-Cookie", clearCookieHeader("aicc_access"));
  headers.append("Set-Cookie", clearCookieHeader("aicc_refresh"));
  headers.append("Set-Cookie", clearCookieHeader("aicc_access_exp"));
  return new Response(null, { status: 302, headers });
}
```

- [ ] **Step 4: Run, verify tests pass**

Run: `cd frontend && npm test -- api/auth/logout`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api/auth/logout/
git commit -m "feat(frontend): /api/auth/logout revokes AICC token + clears cookies"
```

---

### Task 18: `/api/me` — return current user profile from cookie

**Files:**
- Create: `frontend/src/app/api/me/route.ts`
- Create: `frontend/src/app/api/me/route.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/app/api/me/route.test.ts`:

```typescript
import { describe, expect, test, beforeEach, vi } from "vitest";

const BASE = "https://aicc.test";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_AICC_AUTH_BASE_URL", BASE);
  vi.unstubAllGlobals();
  vi.resetModules();
});

function reqWithCookies(cookies: Record<string, string>): Request {
  const headers = new Headers();
  headers.set("cookie", Object.entries(cookies).map(([k, v]) => `${k}=${v}`).join("; "));
  return new Request("https://themis.test/api/me", { headers });
}

describe("GET /api/me", () => {
  test("returns user profile from AICC /auth/me when token is present", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === `${BASE}/auth/me`) {
        return new Response(JSON.stringify({
          id: "u1",
          email: "alice@x.com",
          name: "Alice",
          avatarUrl: "pic",
          projectRole: "admin",
        }), { status: 200 });
      }
      throw new Error("unexpected fetch");
    }));
    const { GET } = await import("./route");
    const res = await GET(reqWithCookies({ aicc_access: "TOK" }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({
      email: "alice@x.com",
      name: "Alice",
      picture: "pic",
      role: "admin",
    });
  });

  test("returns 401 when no cookie", async () => {
    const { GET } = await import("./route");
    const res = await GET(reqWithCookies({}));
    expect(res.status).toBe(401);
  });

  test("maps non-admin projectRole to 'user'", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      id: "u1", email: "x@y.com", name: null, avatarUrl: null, projectRole: "viewer",
    }), { status: 200 })));
    const { GET } = await import("./route");
    const res = await GET(reqWithCookies({ aicc_access: "TOK" }));
    const body = await res.json();
    expect(body.role).toBe("user");
  });
});
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd frontend && npm test -- api/me`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the handler**

Create `frontend/src/app/api/me/route.ts`:

```typescript
import { fetchAiccMe } from "@/lib/aicc-auth";

const AICC_AUTH_BASE_URL = process.env.NEXT_PUBLIC_AICC_AUTH_BASE_URL!;

function readAccess(req: Request): string | null {
  const raw = req.headers.get("cookie") ?? "";
  for (const part of raw.split(/;\s*/)) {
    if (part.startsWith("aicc_access=")) return part.slice("aicc_access=".length);
  }
  return null;
}

function mapRole(projectRole: string | null): "admin" | "user" {
  return projectRole?.toLowerCase() === "admin" ? "admin" : "user";
}

export async function GET(req: Request): Promise<Response> {
  const access = readAccess(req);
  if (!access) return Response.json({ error: "unauthenticated" }, { status: 401 });

  let me;
  try {
    me = await fetchAiccMe({ baseUrl: AICC_AUTH_BASE_URL, accessToken: access });
  } catch (e) {
    console.error("[auth] /api/me lookup failed:", e);
    return Response.json({ error: "auth_provider_error" }, { status: 503 });
  }
  if (me === null) {
    return Response.json({ error: "unauthenticated" }, { status: 401 });
  }

  return Response.json({
    email: me.email,
    name: me.name,
    picture: me.avatarUrl,
    role: mapRole(me.projectRole),
  });
}
```

- [ ] **Step 4: Run, verify tests pass**

Run: `cd frontend && npm test -- api/me`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api/me/
git commit -m "feat(frontend): /api/me returns AICC user profile mapped to Themis shape"
```

---

## Frontend: middleware, sign-in page, user menu, api.ts

### Task 19: Replace NextAuth middleware with cookie-presence check

**Files:**
- Modify: `frontend/src/middleware.ts`

- [ ] **Step 1: Replace the file**

REPLACE `frontend/src/middleware.ts` with:

```typescript
import { NextRequest, NextResponse } from "next/server";

export function middleware(req: NextRequest) {
  const { nextUrl } = req;
  const path = nextUrl.pathname;

  const isAuthPage = path.startsWith("/auth");
  const isApiAuth = path.startsWith("/api/auth");
  const isApiToken = path === "/api/token";
  const isApiMe = path === "/api/me";

  const hasAccess = req.cookies.has("aicc_access");

  // Auth-related routes (sign-in page, login/callback handlers, token endpoint)
  // are reachable without auth. Authenticated users visiting /auth/signin get
  // bounced to home.
  if (isAuthPage || isApiAuth || isApiToken || isApiMe) {
    if (hasAccess && isAuthPage) {
      return NextResponse.redirect(new URL("/", nextUrl));
    }
    return NextResponse.next();
  }

  if (!hasAccess) {
    const target = new URL("/api/auth/login", nextUrl);
    target.searchParams.set("callbackUrl", path);
    return NextResponse.redirect(target);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
```

- [ ] **Step 2: Boot the dev server briefly to confirm no import errors**

Run: `cd frontend && timeout 10 npm run dev 2>&1 | head -30 || true`
Expected: Next.js starts (logs `Ready in ...ms` or similar). No errors about missing `auth` from `@/lib/auth`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/middleware.ts
git commit -m "feat(frontend): middleware checks aicc_access cookie instead of NextAuth"
```

---

### Task 20: Sign-in page — single AICC button

**Files:**
- Modify: `frontend/src/app/auth/signin/page.tsx`

- [ ] **Step 1: Replace the file**

REPLACE `frontend/src/app/auth/signin/page.tsx` with:

```typescript
"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

function SignInContent() {
  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get("callbackUrl") || "/";
  const error = searchParams.get("error");

  const loginHref = `/api/auth/login?callbackUrl=${encodeURIComponent(callbackUrl)}`;

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="w-full max-w-sm mx-auto">
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
          <div className="text-center mb-8">
            <h1 className="text-2xl font-bold text-gray-900">
              Themis <span className="text-indigo-600">L&C</span>
            </h1>
            <p className="mt-2 text-sm text-gray-600">Legal & Compliance AI</p>
          </div>

          {error && (
            <div className="mb-6 p-3 rounded-lg bg-red-50 border border-red-200">
              <p className="text-sm text-red-700">
                {error === "access_denied"
                  ? "Access denied. Ask an admin to add you to the Themis project in AICC."
                  : "Sign-in failed. Please try again."}
              </p>
            </div>
          )}

          <a
            href={loginHref}
            className="w-full flex items-center justify-center gap-3 px-4 py-3 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 transition-colors"
          >
            Sign in with AICC
          </a>
        </div>
      </div>
    </div>
  );
}

export default function SignInPage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center bg-background"><p className="text-gray-400">Loading...</p></div>}>
      <SignInContent />
    </Suspense>
  );
}
```

- [ ] **Step 2: Smoke check the dev server again**

Run: `cd frontend && timeout 10 npm run dev 2>&1 | head -30 || true`
Expected: starts cleanly.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/auth/signin/page.tsx
git commit -m "feat(frontend): replace Google sign-in button with AICC login link"
```

---

### Task 21: User menu — read from `/api/me`, post to `/api/auth/logout`

**Files:**
- Modify: `frontend/src/app/user-menu.tsx`

- [ ] **Step 1: Replace the file**

REPLACE `frontend/src/app/user-menu.tsx` with:

```typescript
"use client";

import { useEffect, useState } from "react";

interface Me {
  email: string;
  name: string | null;
  picture: string | null;
  role: "admin" | "user";
}

export function UserMenu() {
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/me")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => { if (alive) setMe(data); })
      .catch(() => { if (alive) setMe(null); });
    return () => { alive = false; };
  }, []);

  if (!me) return null;

  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-gray-600 hidden sm:block">
        {me.name || me.email}
      </span>
      {me.picture && (
        <img src={me.picture} alt="" className="w-8 h-8 rounded-full" />
      )}
      <form action="/api/auth/logout" method="POST">
        <button type="submit" className="text-sm text-gray-500 hover:text-gray-700">
          Sign out
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/user-menu.tsx
git commit -m "feat(frontend): UserMenu uses /api/me + form-POST logout (no NextAuth)"
```

---

### Task 22: `apiFetch` — on 401, redirect to `/api/auth/login`

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Edit the 401 path**

In `frontend/src/lib/api.ts`, REPLACE the `if (!res.ok) { ... throw ... }` block (currently lines ~43-58) with:

```typescript
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") {
      const cb = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = `/api/auth/login?callbackUrl=${cb}`;
      // Throw so callers don't process the redirect as a successful response.
      throw new Error("Session expired, redirecting to sign-in.");
    }
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
    (error as Error & { code?: string; statusCode?: number }).code = errorCode;
    (error as Error & { code?: string; statusCode?: number }).statusCode = res.status;
    throw error;
  }
```

- [ ] **Step 2: Verify the file still compiles**

Run: `cd frontend && npx tsc --noEmit` (or `npm run lint` if a `tsc` script doesn't exist)
Expected: no type errors related to `api.ts`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): apiFetch redirects to AICC login on 401"
```

---

## Frontend: tear out NextAuth

### Task 23: Delete NextAuth files and dependency

**Files:**
- Delete: `frontend/src/lib/auth.ts`
- Delete: `frontend/src/lib/auth-context.tsx`
- Delete: `frontend/src/app/api/auth/[...nextauth]/route.ts` (and the `[...nextauth]` directory)
- Modify: `frontend/package.json`
- Modify: `frontend/.env.local`

- [ ] **Step 1: Find and remove all `auth-context` and `next-auth` imports**

Run: `cd frontend && rg -l "next-auth|@/lib/auth|@/lib/auth-context" src/`
Expected: a list of files that still import these. For each file:
- If it imports the NextAuth `auth` helper or `useSession`/`signIn`/`signOut`, replace with the AICC-equivalent (use `/api/me` for user state, `/api/auth/login` for sign-in, form POST to `/api/auth/logout`).
- If it imports `SessionProvider` from `@/lib/auth-context`, remove the wrapper. The new auth state is per-component via `useEffect + fetch('/api/me')`.

Common files to check: `app/layout.tsx`, any provider/layout that wraps children with `SessionProvider`.

- [ ] **Step 2: Delete the files**

```bash
rm frontend/src/lib/auth.ts
rm frontend/src/lib/auth-context.tsx
rm -r frontend/src/app/api/auth/\[...nextauth\]
```

- [ ] **Step 3: Remove `next-auth` from package.json**

Edit `frontend/package.json`. In the `dependencies` block, REMOVE the line:

```json
    "next-auth": "^5.0.0-beta.30",
```

(Mind the trailing comma — keep the JSON valid.)

- [ ] **Step 4: Reinstall + run tests + boot**

```bash
cd frontend && rm -rf node_modules/.cache && npm install
npm test
timeout 10 npm run dev 2>&1 | head -30 || true
```

Expected:
- `npm install` succeeds; no `next-auth` in `node_modules` after.
- All vitest tests pass.
- Dev server starts cleanly.

- [ ] **Step 5: Update `frontend/.env.local`**

Edit `frontend/.env.local`:
- REMOVE: `NEXTAUTH_SECRET=`, `NEXTAUTH_URL=`, `GOOGLE_CLIENT_ID=`, `GOOGLE_CLIENT_SECRET=` if present.
- ADD:
  ```
  NEXT_PUBLIC_AICC_AUTH_BASE_URL=https://aicommandcenter-production-d7b1.up.railway.app
  NEXT_PUBLIC_AICC_AUTH_CLIENT_ID=themis-web
  NEXT_PUBLIC_AICC_AUTH_REDIRECT=http://localhost:3000/auth/callback
  AICC_PKCE_COOKIE_SECRET=<generate with: openssl rand -base64 48>
  ```

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/.env.local
git rm frontend/src/lib/auth.ts frontend/src/lib/auth-context.tsx
git rm -r 'frontend/src/app/api/auth/[...nextauth]'
# Plus any files modified in Step 1 to drop NextAuth imports:
git add frontend/src/app/layout.tsx  # adjust to actual files touched
git commit -m "refactor(frontend): remove next-auth dependency and NextAuth files"
```

---

## Bootstrap script and runbook

### Task 24: `seed_aicc_memberships.py`

**Files:**
- Create: `backend/scripts/seed_aicc_memberships.py`

- [ ] **Step 1: Inspect AICC's "add ProjectMembership" API**

Read `/Users/radugogoasa/aicommandcenter/docs/integration-guide.md` and `/Users/radugogoasa/aicommandcenter/docs/api/dashboard-api.md` to find the exact endpoint for creating project memberships and the auth required (likely virtual key or session). Note the URL, method, and body shape — write them into the script as literals (no schema-discovery code).

- [ ] **Step 2: Implement the script**

Create `backend/scripts/seed_aicc_memberships.py`:

```python
"""One-shot bootstrap: copy Themis users + admin emails into AICC ProjectMembership.

Usage:
  cd backend
  AICC_KEY=sk-cc-... \
  AICC_BASE_URL=https://aicommandcenter-production-d7b1.up.railway.app \
  AICC_PROJECT_ID=<themis-project-uuid> \
  uv run python scripts/seed_aicc_memberships.py [--dry-run]

Reads:
  - users  (existing Themis users; their role decides projectRole)
  - allowed_emails  (whitelisted but not yet signed in; default projectRole)

Writes (via AICC dashboard API):
  - One ProjectMembership per email, projectRole=admin if Themis user.role==admin.

Idempotent: if AICC returns 409 Conflict on an existing membership, it's logged
and skipped. Safe to re-run.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

import httpx
from sqlalchemy import text

from app.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("seed-aicc")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    aicc_key = os.environ["AICC_KEY"]
    aicc_base = os.environ["AICC_BASE_URL"].rstrip("/")
    project_id = os.environ["AICC_PROJECT_ID"]

    db = SessionLocal()
    try:
        users = db.execute(text("SELECT email, role FROM users")).all()
        try:
            allowed = db.execute(text("SELECT email FROM allowed_emails")).all()
        except Exception:
            allowed = []  # table may already be dropped on re-runs
    finally:
        db.close()

    targets: dict[str, str] = {}  # email -> projectRole
    for email, role in users:
        targets[email.lower()] = "admin" if role == "admin" else "editor"
    for (email,) in allowed:
        targets.setdefault(email.lower(), "editor")

    logger.info("Found %d unique emails to seed", len(targets))

    if args.dry_run:
        for email, role in sorted(targets.items()):
            logger.info("[dry-run] would seed %s as %s", email, role)
        return 0

    # IMPORTANT: replace the URL/body with the real AICC ProjectMembership API
    # discovered in Step 1. The shape below is a placeholder that the engineer
    # MUST validate against /Users/radugogoasa/aicommandcenter/docs/api/dashboard-api.md
    # before running.
    membership_url = f"{aicc_base}/api/v2/projects/{project_id}/members"
    headers = {
        "Authorization": f"Bearer {aicc_key}",
        "Content-Type": "application/json",
    }
    failures = 0
    with httpx.Client(timeout=15.0) as client:
        for email, role in sorted(targets.items()):
            r = client.post(membership_url, headers=headers, json={
                "email": email,
                "projectRole": role,
            })
            if r.status_code in (200, 201):
                logger.info("seeded %s as %s", email, role)
            elif r.status_code == 409:
                logger.info("already exists: %s", email)
            else:
                failures += 1
                logger.error("FAILED %s (status=%d): %s", email, r.status_code, r.text[:200])

    if failures:
        logger.error("%d memberships failed; please inspect AICC dashboard", failures)
        return 1
    logger.info("done; verify in AICC dashboard")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Mark for human review**

The membership API URL/body SHAPE is the engineer's responsibility to validate against the AICC docs **before running**. Add a comment block at the top of the file saying so (the script already includes one).

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/seed_aicc_memberships.py
git commit -m "scripts(backend): one-shot AICC ProjectMembership seeder"
```

---

### Task 25: Cutover runbook

**Files:**
- Create: `docs/superpowers/runbooks/2026-04-26-aicc-auth-cutover.md`

- [ ] **Step 1: Create the runbook**

Create `docs/superpowers/runbooks/2026-04-26-aicc-auth-cutover.md`:

```markdown
# AICC Auth Cutover Runbook

**Date written:** 2026-04-26
**Spec:** `docs/superpowers/specs/2026-04-26-aicc-auth-migration-design.md`
**Plan:**  `docs/superpowers/plans/2026-04-26-aicc-auth-migration.md`

## What this does

Replaces NextAuth + Google OAuth + the local `allowed_emails` allow-list with
AICC PKCE auth. After cutover:

- Users sign in via AICC (Google still under the hood, but routed through AICC).
- The Themis backend verifies tokens by calling AICC `/auth/me` (60 s LRU cache).
- The local `User` row is auto-created on first sign-in; `User.role` mirrors
  AICC `projectRole` (only `"admin"` → `"admin"`).
- The local `allowed_emails` table is dropped. AICC `ProjectMembership` is
  the only access gate.

## T-1 day — bootstrap AICC

1. In the AICC dashboard, on the THEMIS project, create an auth client `themis-web`:
   - Redirect URIs: `http://localhost:3000/auth/callback`,
     `https://<themis-prod>/auth/callback`,
     `https://<themis-staging>/auth/callback`.
   - Allowed origins: same hosts.
   - Identity providers: Google.
2. Validate the Project Membership API URL/body in
   `backend/scripts/seed_aicc_memberships.py` against
   `/Users/radugogoasa/aicommandcenter/docs/api/dashboard-api.md`.
3. Dry-run the seeder:
   ```bash
   cd backend
   AICC_KEY=$(op read ...) AICC_BASE_URL=https://aicommandcenter-production-d7b1.up.railway.app \
     AICC_PROJECT_ID=<themis-project-uuid> \
     uv run python scripts/seed_aicc_memberships.py --dry-run
   ```
4. Live-run it. Verify in the AICC dashboard that every existing user is a
   project member, and admins have `projectRole=admin`.
5. Generate the PKCE cookie secret:
   ```bash
   openssl rand -base64 48
   ```
   Store it as `AICC_PKCE_COOKIE_SECRET` in your secrets manager.

## T-0 — deploy

1. Set the new env vars on Railway:
   - **frontend**: `NEXT_PUBLIC_AICC_AUTH_BASE_URL`,
     `NEXT_PUBLIC_AICC_AUTH_CLIENT_ID=themis-web`,
     `NEXT_PUBLIC_AICC_AUTH_REDIRECT`, `AICC_PKCE_COOKIE_SECRET`.
   - **backend**: `AICC_AUTH_BASE_URL`, `AICC_AUTH_TTL_SECONDS=60`.
   - **remove** from both: `NEXTAUTH_SECRET`, `NEXTAUTH_URL`,
     `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.
2. Deploy **backend first**.
   - Why: any in-flight requests carrying old NextAuth JWTs will start
     getting 401 the moment the new backend is live. If the frontend deploys
     first, every request from the new frontend hits an old backend that
     can't verify AICC tokens — full outage.
   - Watch backend logs: `[aicc-auth] /auth/me request failed`,
     `Added column users.aicc_user_id`, `AiccAuthClient initialized`.
3. Deploy **frontend** immediately after.

## Smoke tests (run in this order)

1. Open the prod URL in a fresh incognito window.
2. You should be redirected to `/auth/signin`. Click "Sign in with AICC".
3. AICC's Google OAuth screen appears; sign in with an admin email.
4. You're redirected back to the home page. The user menu shows your name +
   avatar.
5. Visit `/settings/whitelist`. **NOTE: this page may not exist anymore — the
   whitelist endpoints were removed.** If it loads, it's a stale page route;
   either delete the route or expect a 404.
6. Visit `/settings/schedulers` (admin-gated). It loads. Good.
7. Open a private window and sign in as a non-admin. The home page loads.
   `/settings/schedulers` returns 403.
8. Watch backend logs for 30 minutes after deploy. Look for:
   - `[aicc-auth] /auth/me request failed` (>1/min suggests a problem)
   - `[aicc-auth] /auth/me unexpected` (any occurrence is unexpected)
   - `[auth] role change for ...` (informational)

## Rollback

1. `git revert <merge-commit>` and redeploy.
2. Restore `NEXTAUTH_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` env
   vars on Railway.
3. The leftover `aicc_user_id` column on `users` is nullable and ignored by
   the reverted code — leave it in place.
4. The `allowed_emails` table is empty after rollback. To restore the
   allow-list, restore the table from a pre-cutover DB snapshot (or recreate
   the rows manually based on the AICC ProjectMembership list).
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/runbooks/2026-04-26-aicc-auth-cutover.md
git commit -m "docs: cutover runbook for AICC auth migration"
```

---

## Final verification

### Task 26: Full test suite + manual smoke against the dev AICC client

**Files:** none

- [ ] **Step 1: Backend full suite**

Run: `cd backend && uv run pytest`
Expected: all green.

- [ ] **Step 2: Frontend full suite**

Run: `cd frontend && npm test`
Expected: all green.

- [ ] **Step 3: Frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Frontend lint**

Run: `cd frontend && npm run lint`
Expected: no errors.

- [ ] **Step 5: Manual sign-in against dev AICC**

(Requires the dev `themis-web` AICC auth client to be created with
`http://localhost:3000/auth/callback` as a redirect URI.)

```bash
# Terminal A
cd backend && uv run uvicorn app.main:app --reload --port 8000

# Terminal B
cd frontend && npm run dev
```

Open `http://localhost:3000`. Walk through:
1. Redirected to `/auth/signin`. Click "Sign in with AICC".
2. AICC Google OAuth appears. Sign in.
3. Redirected back to `/`. User menu shows your name.
4. Click "Sign out". Redirected to `/auth/signin`.
5. Open browser devtools → Application → Cookies. After sign-in,
   `aicc_access`, `aicc_refresh`, `aicc_access_exp` are present. After sign-out,
   they're cleared.
6. Open the Network tab and trigger an API call (visit `/laws`). The request
   to FastAPI carries `Authorization: Bearer <aicc-access-token>`.
7. Backend logs show `[auth] created local user from AICC: ...` on first
   sign-in.

If any step fails, fix before proceeding.

## Done criteria

- All backend tests pass.
- All frontend tests pass.
- Frontend type-check + lint pass.
- Manual sign-in works end-to-end against the dev AICC.
- The branch contains exactly the commits listed above.
- The PR description references the spec, plan, and runbook.
- No reference to `NEXTAUTH_SECRET`, `next-auth`, `AllowedEmail`,
  `verify_and_upsert_user`, `seed_admin_users`, `ADMIN_EMAILS`,
  `GOOGLE_CLIENT_ID`, or `GOOGLE_CLIENT_SECRET` remains anywhere in `backend/app/`,
  `backend/scripts/`, `frontend/src/`, `frontend/.env.local`, or `backend/.env`.

  Quick check:
  ```bash
  rg -n "NEXTAUTH_SECRET|next-auth|AllowedEmail|verify_and_upsert_user|seed_admin_users|ADMIN_EMAILS|GOOGLE_CLIENT_ID|GOOGLE_CLIENT_SECRET" \
    backend/app backend/scripts frontend/src backend/.env frontend/.env.local
  ```
  Expected: no output (or only matches in the cutover runbook, which is the
  one place it's allowed to mention them).
