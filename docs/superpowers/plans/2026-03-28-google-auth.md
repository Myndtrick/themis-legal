# Google Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Google sign-in with invite-only access control so only whitelisted users can use Themis.

**Architecture:** NextAuth.js handles Google OAuth on the frontend and issues JWT session cookies. The backend verifies JWTs using a shared `NEXTAUTH_SECRET`. Two admin users are seeded on startup. Admins manage a whitelist via a Settings tab.

**Tech Stack:** NextAuth.js v5 (next-auth@5), PyJWT (backend JWT verification), SQLAlchemy (User/AllowedEmail models), Next.js middleware (route protection)

---

## File Structure

### Backend (new files)
- `backend/app/models/user.py` — User and AllowedEmail SQLAlchemy models
- `backend/app/auth.py` — JWT verification dependencies (`get_current_user`, `require_admin`)
- `backend/app/routers/admin.py` — Admin whitelist CRUD + user verification endpoint
- `backend/app/services/user_service.py` — User seeding and whitelist logic
- `backend/tests/test_auth.py` — Auth middleware and admin endpoint tests

### Backend (modified files)
- `backend/app/main.py` — Register user model, add admin router, seed admins on startup
- `backend/app/config.py` — Add `NEXTAUTH_SECRET` config var
- `backend/pyproject.toml` — Add `pyjwt` dependency

### Frontend (new files)
- `frontend/src/app/api/auth/[...nextauth]/route.ts` — NextAuth route handler
- `frontend/src/lib/auth.ts` — NextAuth config (providers, callbacks)
- `frontend/src/middleware.ts` — Route protection middleware
- `frontend/src/app/auth/signin/page.tsx` — Custom sign-in page
- `frontend/src/app/settings/users/users-table.tsx` — Admin whitelist UI
- `frontend/src/lib/auth-context.tsx` — Session provider wrapper

### Frontend (modified files)
- `frontend/src/app/layout.tsx` — Wrap with SessionProvider, add user avatar to header
- `frontend/src/lib/api.ts` — Add auth token to `apiFetch`
- `frontend/src/lib/use-event-source.ts` — Add auth token to SSE fetch calls
- `frontend/src/app/settings/settings-tabs.tsx` — Add "Users" tab (admin only)
- `frontend/src/app/settings/page.tsx` — Render UsersTable for users tab
- `frontend/package.json` — Add `next-auth` dependency

---

### Task 1: Backend — User and AllowedEmail Models

**Files:**
- Create: `backend/app/models/user.py`
- Modify: `backend/app/main.py:9` (add model import for table registration)

- [ ] **Step 1: Create User and AllowedEmail models**

Create `backend/app/models/user.py`:

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
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    last_login: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )


class AllowedEmail(Base):
    __tablename__ = "allowed_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    added_by: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
```

- [ ] **Step 2: Register the model in main.py**

In `backend/app/main.py`, add to the model imports on line 9:

```python
from app.models import assistant, pipeline, prompt, category, user  # noqa: F401 — register models
```

- [ ] **Step 3: Verify tables get created**

Run: `cd backend && uv run python -c "from app.database import Base, engine; from app.models import user; Base.metadata.create_all(bind=engine); print('Tables created OK')"`

Expected: `Tables created OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/user.py backend/app/main.py
git commit -m "feat(auth): add User and AllowedEmail models"
```

---

### Task 2: Backend — User Seeding Service

**Files:**
- Create: `backend/app/services/user_service.py`
- Modify: `backend/app/main.py` (call seed in lifespan)

- [ ] **Step 1: Create user_service.py**

Create `backend/app/services/user_service.py`:

```python
import datetime
import logging

from sqlalchemy.orm import Session

from app.models.user import AllowedEmail, User

logger = logging.getLogger(__name__)

ADMIN_EMAILS = [
    "radu.gogoasa@gmail.com",
    "aandrei.0705@gmail.com",
]


def seed_admin_users(db: Session) -> None:
    """Seed admin users on startup if they don't exist."""
    for email in ADMIN_EMAILS:
        existing = db.query(User).filter(User.email == email).first()
        if not existing:
            db.add(User(email=email, role="admin"))
            logger.info(f"Seeded admin user: {email}")
    db.commit()


def verify_and_upsert_user(db: Session, email: str, name: str | None, picture: str | None) -> User | None:
    """Check if a user is allowed to sign in. Create/update User row if so.

    Returns the User if allowed, None if rejected.
    """
    # Check if already a user
    user = db.query(User).filter(User.email == email).first()
    if user:
        user.name = name
        user.picture = picture
        user.last_login = datetime.datetime.utcnow()
        db.commit()
        db.refresh(user)
        return user

    # Check whitelist
    allowed = db.query(AllowedEmail).filter(AllowedEmail.email == email).first()
    if not allowed:
        return None

    # Create new user from whitelist
    user = User(email=email, name=name, picture=picture, role="user")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
```

- [ ] **Step 2: Call seed in lifespan**

In `backend/app/main.py`, inside the `lifespan` function, after the `backfill_law_mapping_fields(db)` call (around line 48), add:

```python
        from app.services.user_service import seed_admin_users
        seed_admin_users(db)
```

- [ ] **Step 3: Test seeding**

Run: `cd backend && uv run python -c "
from app.database import SessionLocal, Base, engine
from app.models.user import User
Base.metadata.create_all(bind=engine)
from app.services.user_service import seed_admin_users
db = SessionLocal()
seed_admin_users(db)
admins = db.query(User).filter(User.role == 'admin').all()
print(f'Admins: {[u.email for u in admins]}')
db.close()
"`

Expected: `Admins: ['radu.gogoasa@gmail.com', 'aandrei.0705@gmail.com']`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/user_service.py backend/app/main.py
git commit -m "feat(auth): add user seeding service with admin accounts"
```

---

### Task 3: Backend — JWT Verification and Config

**Files:**
- Modify: `backend/pyproject.toml` (add pyjwt)
- Modify: `backend/app/config.py` (add NEXTAUTH_SECRET)
- Create: `backend/app/auth.py`

- [ ] **Step 1: Add pyjwt dependency**

Run: `cd backend && uv add pyjwt`

- [ ] **Step 2: Add NEXTAUTH_SECRET to config**

In `backend/app/config.py`, add after the last line:

```python
NEXTAUTH_SECRET = os.environ.get("NEXTAUTH_SECRET", "dev-secret-change-me")
```

- [ ] **Step 3: Create auth.py with JWT verification**

Create `backend/app/auth.py`:

```python
import logging

import jwt
from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import NEXTAUTH_SECRET
from app.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)


def _decode_token(token: str) -> dict:
    """Decode and verify a NextAuth JWT."""
    try:
        payload = jwt.decode(token, NEXTAUTH_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def get_current_user(
    request: Request,
    token: str | None = Query(None, alias="token"),
    db: Session = Depends(get_db),
) -> User:
    """Extract and verify JWT from Authorization header or query param.

    Query param is used for SSE connections (EventSource can't set headers).
    """
    auth_header = request.headers.get("Authorization")

    raw_token = None
    if auth_header and auth_header.startswith("Bearer "):
        raw_token = auth_header[7:]
    elif token:
        raw_token = token

    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = _decode_token(raw_token)
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing email")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Dependency that requires the current user to be an admin."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
```

- [ ] **Step 4: Verify import works**

Run: `cd backend && uv run python -c "from app.auth import get_current_user, require_admin; print('Auth module OK')"`

Expected: `Auth module OK`

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/config.py backend/app/auth.py
git commit -m "feat(auth): add JWT verification middleware and config"
```

---

### Task 4: Backend — Admin Router and Auth Verification Endpoint

**Files:**
- Create: `backend/app/routers/admin.py`
- Modify: `backend/app/main.py` (register admin router)

- [ ] **Step 1: Create admin router**

Create `backend/app/routers/admin.py`:

```python
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.auth import require_admin, get_current_user
from app.config import NEXTAUTH_SECRET
from app.database import get_db
from app.models.user import AllowedEmail, User
from app.services.user_service import verify_and_upsert_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin"])


# --- Auth verification (called by NextAuth signIn callback) ---

class VerifyUserRequest(BaseModel):
    email: str
    name: str | None = None
    picture: str | None = None


class VerifyUserResponse(BaseModel):
    email: str
    name: str | None
    role: str
    allowed: bool


@router.post("/verify-user", response_model=VerifyUserResponse)
def verify_user(
    body: VerifyUserRequest,
    x_auth_secret: str | None = None,
    db: Session = Depends(get_db),
):
    """Called by NextAuth during sign-in to check if user is allowed."""
    from fastapi import Header

    # This is re-done properly below
    pass


# Re-define properly with Header dependency
@router.post("/verify-user", response_model=VerifyUserResponse, name="verify_user_endpoint")
def _verify_user_impl():
    pass
```

Actually, let me write this cleanly:

Create `backend/app/routers/admin.py`:

```python
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import NEXTAUTH_SECRET
from app.database import get_db
from app.models.user import AllowedEmail, User
from app.services.user_service import ADMIN_EMAILS, verify_and_upsert_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin"])


# --- Auth verification (called by NextAuth signIn callback) ---


class VerifyUserRequest(BaseModel):
    email: str
    name: str | None = None
    picture: str | None = None


class VerifyUserResponse(BaseModel):
    email: str
    name: str | None
    role: str
    allowed: bool


@router.post("/verify-user", response_model=VerifyUserResponse)
def verify_user(
    body: VerifyUserRequest,
    x_auth_secret: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    """Called by NextAuth during sign-in to check if user is allowed.

    Protected by shared secret header, not JWT (since user has no JWT yet).
    """
    if x_auth_secret != NEXTAUTH_SECRET:
        raise HTTPException(status_code=403, detail="Invalid auth secret")

    user = verify_and_upsert_user(db, body.email, body.name, body.picture)
    if not user:
        return VerifyUserResponse(
            email=body.email, name=body.name, role="", allowed=False
        )

    return VerifyUserResponse(
        email=user.email, name=user.name, role=user.role, allowed=True
    )


# --- Whitelist management (admin only) ---


class WhitelistEntry(BaseModel):
    email: str
    added_by: str
    created_at: str
    is_admin: bool


class AddEmailRequest(BaseModel):
    email: str


@router.get("/whitelist", response_model=list[WhitelistEntry])
def list_whitelist(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all users and whitelisted emails."""
    entries: list[WhitelistEntry] = []

    # Add existing users
    users = db.query(User).order_by(User.created_at).all()
    for u in users:
        entries.append(WhitelistEntry(
            email=u.email,
            added_by="system" if u.email in ADMIN_EMAILS else u.email,
            created_at=u.created_at.isoformat(),
            is_admin=u.role == "admin",
        ))

    # Add whitelisted emails not yet signed in
    seen_emails = {e.email for e in entries}
    allowed = db.query(AllowedEmail).order_by(AllowedEmail.created_at).all()
    for a in allowed:
        if a.email not in seen_emails:
            entries.append(WhitelistEntry(
                email=a.email,
                added_by=a.added_by,
                created_at=a.created_at.isoformat(),
                is_admin=False,
            ))

    return entries


@router.post("/whitelist", status_code=201)
def add_to_whitelist(
    body: AddEmailRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Add an email to the whitelist."""
    email = body.email.strip().lower()

    # Check if already exists
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise HTTPException(status_code=409, detail="Email already has access")

    existing_allowed = db.query(AllowedEmail).filter(AllowedEmail.email == email).first()
    if existing_allowed:
        raise HTTPException(status_code=409, detail="Email already whitelisted")

    db.add(AllowedEmail(email=email, added_by=admin.email))
    db.commit()
    return {"email": email, "status": "added"}


@router.delete("/whitelist/{email}")
def remove_from_whitelist(
    email: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Remove an email from the whitelist. Cannot remove admins."""
    # Check if trying to remove an admin
    user = db.query(User).filter(User.email == email).first()
    if user and user.role == "admin":
        raise HTTPException(status_code=400, detail="Cannot remove admin users")

    # Remove from AllowedEmail
    allowed = db.query(AllowedEmail).filter(AllowedEmail.email == email).first()
    if allowed:
        db.delete(allowed)

    # Remove from User table too (revokes access)
    if user:
        db.delete(user)

    db.commit()
    return {"email": email, "status": "removed"}
```

- [ ] **Step 2: Register admin router in main.py**

In `backend/app/main.py`, add the import and router registration:

After the existing router imports (around line 11), add:
```python
from app.routers import admin as admin_router
```

After the last `app.include_router(...)` call (around line 119), add:
```python
app.include_router(admin_router.router)
```

- [ ] **Step 3: Verify router loads**

Run: `cd backend && uv run python -c "from app.routers.admin import router; print(f'Admin router OK: {len(router.routes)} routes')"`

Expected: `Admin router OK: 4 routes` (verify-user, list, add, delete)

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/admin.py backend/app/main.py
git commit -m "feat(auth): add admin router with whitelist CRUD and user verification"
```

---

### Task 5: Backend — Protect All Existing Routes

**Files:**
- Modify: `backend/app/routers/categories.py`
- Modify: `backend/app/routers/laws.py`
- Modify: `backend/app/routers/notifications.py`
- Modify: `backend/app/routers/assistant.py`
- Modify: `backend/app/routers/settings_prompts.py`
- Modify: `backend/app/routers/settings_pipeline.py`
- Modify: `backend/app/routers/settings_categories.py`

- [ ] **Step 1: Add auth dependency to each router**

For each router file, add the import and router-level dependency. The pattern is the same for all:

Add this import at the top of each file:
```python
from app.auth import get_current_user
```

Then change the `APIRouter()` call to include the dependency. For example:

**`backend/app/routers/categories.py`:**
```python
router = APIRouter(prefix="/api/laws", tags=["Categories"], dependencies=[Depends(get_current_user)])
```
(Also add `from fastapi import Depends` if not already imported.)

**`backend/app/routers/laws.py`:**
```python
router = APIRouter(prefix="/api/laws", tags=["Laws"], dependencies=[Depends(get_current_user)])
```

**`backend/app/routers/notifications.py`:**
```python
router = APIRouter(prefix="/api/notifications", tags=["Notifications"], dependencies=[Depends(get_current_user)])
```

**`backend/app/routers/assistant.py`:**
```python
router = APIRouter(prefix="/api/assistant", tags=["Legal Assistant"], dependencies=[Depends(get_current_user)])
```

**`backend/app/routers/settings_prompts.py`:**
```python
router = APIRouter(prefix="/api/settings/prompts", tags=["Settings — Prompts"], dependencies=[Depends(get_current_user)])
```

**`backend/app/routers/settings_pipeline.py`:**
```python
router = APIRouter(prefix="/api/settings/pipeline", tags=["Settings — Pipeline"], dependencies=[Depends(get_current_user)])
```

**`backend/app/routers/settings_categories.py`:**
```python
router = APIRouter(prefix="/api/settings/categories", tags=["Settings — Categories"], dependencies=[Depends(get_current_user)])
```

Check each file's existing `APIRouter()` call — preserve the existing `prefix` and `tags` values, just add `dependencies=[Depends(get_current_user)]`.

- [ ] **Step 2: Keep health endpoint unprotected**

The `/api/health` endpoint in `main.py` is defined directly on the `app` object, not on a router, so it stays unprotected. No changes needed.

- [ ] **Step 3: Verify the app still starts**

Run: `cd backend && uv run python -c "from app.main import app; print(f'App loaded OK: {len(app.routes)} routes')"`

Expected: `App loaded OK: <number> routes` (no import errors)

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/
git commit -m "feat(auth): protect all API routes with JWT verification"
```

---

### Task 6: Frontend — Install NextAuth and Create Auth Config

**Files:**
- Modify: `frontend/package.json` (add next-auth)
- Create: `frontend/src/lib/auth.ts`
- Create: `frontend/src/app/api/auth/[...nextauth]/route.ts`

- [ ] **Step 1: Install next-auth**

Run: `cd frontend && npm install next-auth@5`

- [ ] **Step 2: Create auth config**

Create `frontend/src/lib/auth.ts`:

```typescript
import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
    }),
  ],
  pages: {
    signIn: "/auth/signin",
    error: "/auth/signin",
  },
  callbacks: {
    async signIn({ user }) {
      // Verify with backend that this email is allowed
      try {
        const res = await fetch(`${API_BASE}/api/admin/verify-user`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-auth-secret": process.env.NEXTAUTH_SECRET!,
          },
          body: JSON.stringify({
            email: user.email,
            name: user.name,
            picture: user.image,
          }),
        });
        if (!res.ok) return false;
        const data = await res.json();
        return data.allowed === true;
      } catch (e) {
        console.error("[auth] Failed to verify user:", e);
        return false;
      }
    },
    async jwt({ token, user, account }) {
      if (account && user) {
        // First sign-in: fetch role from backend
        try {
          const res = await fetch(`${API_BASE}/api/admin/verify-user`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "x-auth-secret": process.env.NEXTAUTH_SECRET!,
            },
            body: JSON.stringify({
              email: user.email,
              name: user.name,
              picture: user.image,
            }),
          });
          if (res.ok) {
            const data = await res.json();
            token.role = data.role;
          }
        } catch {
          // Role will be empty — non-critical
        }
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        (session.user as Record<string, unknown>).role = token.role;
      }
      return session;
    },
  },
  secret: process.env.NEXTAUTH_SECRET,
});
```

- [ ] **Step 3: Create NextAuth route handler**

Create `frontend/src/app/api/auth/[...nextauth]/route.ts`:

```typescript
import { handlers } from "@/lib/auth";

export const { GET, POST } = handlers;
```

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/lib/auth.ts frontend/src/app/api/auth/\[...nextauth\]/route.ts
git commit -m "feat(auth): add NextAuth config with Google provider"
```

---

### Task 7: Frontend — Route Protection Middleware

**Files:**
- Create: `frontend/src/middleware.ts`

- [ ] **Step 1: Create middleware**

Create `frontend/src/middleware.ts`:

```typescript
import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";

export default auth((req) => {
  const { nextUrl } = req;

  const isAuthenticated = !!req.auth;
  const isAuthPage = nextUrl.pathname.startsWith("/auth");
  const isApiAuth = nextUrl.pathname.startsWith("/api/auth");

  // Allow auth-related routes
  if (isAuthPage || isApiAuth) {
    // Redirect authenticated users away from sign-in page
    if (isAuthenticated && isAuthPage) {
      return NextResponse.redirect(new URL("/", nextUrl));
    }
    return NextResponse.next();
  }

  // Redirect unauthenticated users to sign-in
  if (!isAuthenticated) {
    const signInUrl = new URL("/auth/signin", nextUrl);
    signInUrl.searchParams.set("callbackUrl", nextUrl.pathname);
    return NextResponse.redirect(signInUrl);
  }

  return NextResponse.next();
});

export const config = {
  matcher: [
    // Match all routes except static files and Next.js internals
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/middleware.ts
git commit -m "feat(auth): add route protection middleware"
```

---

### Task 8: Frontend — Sign-In Page

**Files:**
- Create: `frontend/src/app/auth/signin/page.tsx`

- [ ] **Step 1: Create sign-in page**

Create `frontend/src/app/auth/signin/page.tsx`:

```tsx
"use client";

import { signIn } from "next-auth/react";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

function SignInContent() {
  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get("callbackUrl") || "/";
  const error = searchParams.get("error");

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="w-full max-w-sm mx-auto">
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
          <div className="text-center mb-8">
            <h1 className="text-2xl font-bold text-gray-900">
              Themis <span className="text-indigo-600">L&C</span>
            </h1>
            <p className="mt-2 text-sm text-gray-600">
              Legal & Compliance AI
            </p>
          </div>

          {error && (
            <div className="mb-6 p-3 rounded-lg bg-red-50 border border-red-200">
              <p className="text-sm text-red-700">
                {error === "AccessDenied"
                  ? "Access denied. Contact an admin to get access."
                  : "Something went wrong. Please try again."}
              </p>
            </div>
          )}

          <button
            onClick={() => signIn("google", { callbackUrl })}
            className="w-full flex items-center justify-center gap-3 px-4 py-3 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 transition-colors"
          >
            <svg className="w-5 h-5" viewBox="0 0 24 24">
              <path
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
                fill="#4285F4"
              />
              <path
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                fill="#34A853"
              />
              <path
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                fill="#FBBC05"
              />
              <path
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                fill="#EA4335"
              />
            </svg>
            Sign in with Google
          </button>
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

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/auth/signin/page.tsx
git commit -m "feat(auth): add custom sign-in page"
```

---

### Task 9: Frontend — Session Provider and Layout Integration

**Files:**
- Create: `frontend/src/lib/auth-context.tsx`
- Modify: `frontend/src/app/layout.tsx`

- [ ] **Step 1: Create session provider wrapper**

Create `frontend/src/lib/auth-context.tsx`:

```tsx
"use client";

import { SessionProvider } from "next-auth/react";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>;
}
```

- [ ] **Step 2: Update layout.tsx**

Modify `frontend/src/app/layout.tsx`:

Add import at top:
```typescript
import { AuthProvider } from "@/lib/auth-context";
```

Wrap the `<body>` children with `<AuthProvider>`:

Replace the body content:
```tsx
      <body className="min-h-full flex flex-col bg-gray-50 text-gray-900 antialiased">
        <AuthProvider>
          <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
            {/* ... existing header content stays the same ... */}
          </header>
          <main className="flex-1 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 w-full">
            {children}
          </main>
        </AuthProvider>
      </body>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/auth-context.tsx frontend/src/app/layout.tsx
git commit -m "feat(auth): add SessionProvider to app layout"
```

---

### Task 10: Frontend — Add Auth Token to API Calls

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/use-event-source.ts`

- [ ] **Step 1: Update apiFetch in api.ts**

In `frontend/src/lib/api.ts`, replace the `apiFetch` function and add a helper:

```typescript
import { getSession } from "next-auth/react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getAuthHeaders(): Promise<Record<string, string>> {
  const session = await getSession();
  if (!session) return {};

  // Get the raw JWT token from the session cookie
  // NextAuth stores it as a cookie; we need to pass it to our backend
  const res = await fetch("/api/auth/session");
  const data = await res.json();
  if (data?.accessToken) {
    return { Authorization: `Bearer ${data.accessToken}` };
  }
  return {};
}

export async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  let res: Response;
  try {
    const authHeaders = await getAuthHeaders();
    res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...authHeaders,
        ...options?.headers,
      },
    });
  } catch {
    throw new Error(
      `Cannot reach the backend at ${API_BASE}. Is the server running?`
    );
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API error ${res.status}: ${body || res.statusText}`);
  }
  return res.json();
}
```

**Important note:** NextAuth v5 JWT is stored as an encrypted cookie and is not directly accessible client-side. The simplest approach is to expose the JWT via the session callback. Update `frontend/src/lib/auth.ts` — in the `jwt` callback, after setting `token.role`, also ensure the encoded JWT is available:

In the `session` callback in `auth.ts`, add the token itself:
```typescript
    async session({ session, token }) {
      if (session.user) {
        (session.user as Record<string, unknown>).role = token.role;
      }
      // Expose the encoded JWT for API calls
      (session as Record<string, unknown>).accessToken = token.sub
        ? await encode({ token, secret: process.env.NEXTAUTH_SECRET! })
        : undefined;
      return session;
    },
```

Alternatively, a simpler approach: since the backend and frontend share `NEXTAUTH_SECRET`, the backend can decode the same cookie. But cross-origin cookies won't work between different Railway domains.

**Simpler approach — use a custom `/api/token` endpoint:**

Create `frontend/src/app/api/token/route.ts`:
```typescript
import { auth } from "@/lib/auth";
import { encode } from "next-auth/jwt";

export async function GET() {
  const session = await auth();
  if (!session?.user?.email) {
    return Response.json({ token: null }, { status: 401 });
  }

  const token = await encode({
    token: {
      email: session.user.email,
      name: session.user.name,
      picture: session.user.image,
      role: (session.user as Record<string, unknown>).role,
    },
    secret: process.env.NEXTAUTH_SECRET!,
  });

  return Response.json({ token });
}
```

Then `getAuthHeaders` becomes:
```typescript
let cachedToken: { token: string; expires: number } | null = null;

async function getAuthHeaders(): Promise<Record<string, string>> {
  // Use cached token if still valid (cache for 4 minutes)
  if (cachedToken && cachedToken.expires > Date.now()) {
    return { Authorization: `Bearer ${cachedToken.token}` };
  }

  try {
    const res = await fetch("/api/token");
    if (!res.ok) return {};
    const data = await res.json();
    if (data.token) {
      cachedToken = { token: data.token, expires: Date.now() + 4 * 60 * 1000 };
      return { Authorization: `Bearer ${data.token}` };
    }
  } catch {
    // Not authenticated
  }
  return {};
}
```

- [ ] **Step 2: Update use-event-source.ts**

In `frontend/src/lib/use-event-source.ts`, add the auth token to all SSE fetch calls.

Add at the top of the file:
```typescript
let cachedToken: { token: string; expires: number } | null = null;

async function getAuthToken(): Promise<string | null> {
  if (cachedToken && cachedToken.expires > Date.now()) {
    return cachedToken.token;
  }
  try {
    const res = await fetch("/api/token");
    if (!res.ok) return null;
    const data = await res.json();
    if (data.token) {
      cachedToken = { token: data.token, expires: Date.now() + 4 * 60 * 1000 };
      return data.token;
    }
  } catch {
    return null;
  }
  return null;
}
```

Then in `streamChat`, `streamResume`, and `streamRetry`, add the auth header to the fetch call. For example in `streamChat`:

```typescript
export async function streamChat(
  sessionId: string,
  message: string,
  handlers: SSEHandlers,
  signal?: AbortSignal
): Promise<void> {
  const token = await getAuthToken();
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/assistant/sessions/${sessionId}/messages`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ content: message }),
        signal,
      }
    );
  } catch {
    // ... existing error handling
  }
  // ... rest stays the same
```

Apply the same pattern to `streamResume` and `streamRetry`.

- [ ] **Step 3: Remove duplicate API_BASE from other files**

The files that define their own `API_BASE` and do raw `fetch` calls need the auth token too:

**`frontend/src/app/laws/search-import-form.tsx`** — uses `API_BASE` for a streaming fetch. Add the same `getAuthToken` pattern and include the header.

**`frontend/src/app/laws/[id]/status-badge.tsx`** — uses `API_BASE` for direct fetch. Convert to use `apiFetch` from `@/lib/api` instead.

**`frontend/src/app/settings/categories/categories-table.tsx`** — uses `API_BASE` for direct fetch. Convert to use `apiFetch` from `@/lib/api` instead.

**`frontend/src/app/laws/components/combined-search.tsx`** — uses `API_BASE` for direct fetch. Convert to use `apiFetch` from `@/lib/api` instead.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/use-event-source.ts frontend/src/app/api/token/route.ts frontend/src/app/laws/ frontend/src/app/settings/categories/
git commit -m "feat(auth): add auth token to all API and SSE calls"
```

---

### Task 11: Frontend — Users Tab in Settings

**Files:**
- Create: `frontend/src/app/settings/users/users-table.tsx`
- Modify: `frontend/src/app/settings/settings-tabs.tsx`
- Modify: `frontend/src/app/settings/page.tsx`

- [ ] **Step 1: Create UsersTable component**

Create `frontend/src/app/settings/users/users-table.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

interface WhitelistEntry {
  email: string;
  added_by: string;
  created_at: string;
  is_admin: boolean;
}

export function UsersTable() {
  const [entries, setEntries] = useState<WhitelistEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newEmail, setNewEmail] = useState("");
  const [adding, setAdding] = useState(false);

  const load = async () => {
    try {
      setLoading(true);
      const data = await apiFetch<WhitelistEntry[]>("/api/admin/whitelist");
      setEntries(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const addEmail = async () => {
    if (!newEmail.trim()) return;
    setAdding(true);
    try {
      await apiFetch("/api/admin/whitelist", {
        method: "POST",
        body: JSON.stringify({ email: newEmail.trim().toLowerCase() }),
      });
      setNewEmail("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add");
    } finally {
      setAdding(false);
    }
  };

  const removeEmail = async (email: string) => {
    try {
      await apiFetch(`/api/admin/whitelist/${encodeURIComponent(email)}`, {
        method: "DELETE",
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove");
    }
  };

  if (loading) return <p className="text-gray-400 py-4">Loading users...</p>;

  return (
    <div>
      {error && (
        <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex gap-2 mb-6">
        <input
          type="email"
          value={newEmail}
          onChange={(e) => setNewEmail(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addEmail()}
          placeholder="email@example.com"
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
        />
        <button
          onClick={addEmail}
          disabled={adding || !newEmail.trim()}
          className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {adding ? "Adding..." : "Add Email"}
        </button>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Email</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Role</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Added By</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Date</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.email} className="border-b border-gray-100 last:border-0">
                <td className="px-4 py-3 text-gray-900">{entry.email}</td>
                <td className="px-4 py-3">
                  {entry.is_admin ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-indigo-100 text-indigo-700">
                      Admin
                    </span>
                  ) : (
                    <span className="text-gray-500">User</span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-500">{entry.added_by}</td>
                <td className="px-4 py-3 text-gray-500">
                  {new Date(entry.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3 text-right">
                  {!entry.is_admin && (
                    <button
                      onClick={() => removeEmail(entry.email)}
                      className="text-red-600 hover:text-red-800 text-xs font-medium"
                    >
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add Users tab to settings-tabs.tsx**

In `frontend/src/app/settings/settings-tabs.tsx`, add the users tab to the `TABS` array:

```typescript
const TABS = [
  { id: "prompts", label: "Prompt Management" },
  { id: "pipeline", label: "Pipeline Tracking" },
  { id: "versions", label: "Version History" },
  { id: "categories", label: "Categories" },
  { id: "users", label: "Users" },
] as const;
```

- [ ] **Step 3: Add Users tab content to settings page**

In `frontend/src/app/settings/page.tsx`, add the import:

```typescript
import { UsersTable } from "./users/users-table";
```

And add the tab content after the categories block (around line 53):

```typescript
          if (activeTab === "users") {
            return <UsersTable />;
          }
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/settings/users/users-table.tsx frontend/src/app/settings/settings-tabs.tsx frontend/src/app/settings/page.tsx
git commit -m "feat(auth): add Users tab to Settings for admin whitelist management"
```

---

### Task 12: Frontend — User Avatar in Header

**Files:**
- Modify: `frontend/src/app/layout.tsx`

- [ ] **Step 1: Add user menu to header**

This requires making the header a client component or extracting a `UserMenu` component. Since the layout is a server component, extract a client component.

Create `frontend/src/app/user-menu.tsx`:

```tsx
"use client";

import { signOut, useSession } from "next-auth/react";

export function UserMenu() {
  const { data: session } = useSession();

  if (!session?.user) return null;

  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-gray-600 hidden sm:block">
        {session.user.name || session.user.email}
      </span>
      {session.user.image && (
        <img
          src={session.user.image}
          alt=""
          className="w-8 h-8 rounded-full"
        />
      )}
      <button
        onClick={() => signOut({ callbackUrl: "/auth/signin" })}
        className="text-sm text-gray-500 hover:text-gray-700"
      >
        Sign out
      </button>
    </div>
  );
}
```

In `frontend/src/app/layout.tsx`, import and add to the header:

```typescript
import { UserMenu } from "./user-menu";
```

In the header `<div className="flex h-16 items-center justify-between">`, after the nav `</div>`, add:

```tsx
              <UserMenu />
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/user-menu.tsx frontend/src/app/layout.tsx
git commit -m "feat(auth): add user avatar and sign-out button to header"
```

---

### Task 13: Environment Setup and End-to-End Test

**Files:**
- Modify: `backend/.env` (add NEXTAUTH_SECRET)
- Create: `frontend/.env.local` (add all auth env vars)

- [ ] **Step 1: Add NEXTAUTH_SECRET to backend .env**

Add to `backend/.env` (or the root `.env`):
```
NEXTAUTH_SECRET=dev-secret-change-me-in-production
```

- [ ] **Step 2: Create frontend .env.local**

Create `frontend/.env.local`:
```
NEXT_PUBLIC_API_URL=http://localhost:4001
GOOGLE_CLIENT_ID=<your-google-client-id>
GOOGLE_CLIENT_SECRET=<your-google-client-secret>
NEXTAUTH_SECRET=dev-secret-change-me-in-production
NEXTAUTH_URL=http://localhost:4000
```

The `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` must come from Google Cloud Console. The user needs to:

1. Go to https://console.cloud.google.com/apis/credentials
2. Create OAuth 2.0 Client ID (Web application)
3. Add authorized redirect URI: `http://localhost:4000/api/auth/callback/google`
4. Copy Client ID and Client Secret into `.env.local`

- [ ] **Step 3: Restart servers and test**

Run: Kill existing servers, then restart:
```bash
cd /Users/radugogoasa/Themis
npx concurrently -n backend,frontend -c blue,green \
  "cd backend && uv run uvicorn app.main:app --reload --port 4001" \
  "cd frontend && npx next dev --port 4000"
```

- [ ] **Step 4: Manual test checklist**

1. Open `http://localhost:4000` — should redirect to `/auth/signin`
2. Click "Sign in with Google" — should redirect to Google OAuth
3. Sign in with `radu.gogoasa@gmail.com` — should succeed and redirect to dashboard
4. Open `http://localhost:4001/api/settings/prompts/` without auth header — should return 401
5. Go to Settings > Users tab — should see admin list
6. Add a test email to whitelist — should appear in table
7. Remove the test email — should disappear

- [ ] **Step 5: Commit env template**

```bash
echo "NEXT_PUBLIC_API_URL=http://localhost:4001
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
NEXTAUTH_SECRET=
NEXTAUTH_URL=http://localhost:4000" > frontend/.env.example
git add frontend/.env.example
git commit -m "feat(auth): add frontend env example for Google auth setup"
```

---

### Task 14: Deploy Auth to Railway

**Files:**
- Railway environment variables (both services)

- [ ] **Step 1: Set backend env vars**

Using Railway CLI or dashboard, set on the `Themis-legal` backend service:
```
NEXTAUTH_SECRET=<generate a secure random string>
```

Generate with: `openssl rand -base64 32`

- [ ] **Step 2: Set frontend env vars**

On the `themis-frontend` service:
```
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>
NEXTAUTH_SECRET=<same value as backend>
NEXTAUTH_URL=https://themis-frontend-production.up.railway.app
NEXT_PUBLIC_API_URL=https://themis-legal-production.up.railway.app
```

- [ ] **Step 3: Add production redirect URI to Google Cloud Console**

Add to authorized redirect URIs:
```
https://themis-frontend-production.up.railway.app/api/auth/callback/google
```

- [ ] **Step 4: Deploy both services**

```bash
railway up -d --service Themis-legal /Users/radugogoasa/Themis/backend --path-as-root
railway up -d --service themis-frontend /Users/radugogoasa/Themis/frontend --path-as-root
```

- [ ] **Step 5: Verify production**

1. Open `https://themis-frontend-production.up.railway.app` — should redirect to sign-in
2. Sign in with Google — should work
3. Check Settings > Users — should show admin accounts
