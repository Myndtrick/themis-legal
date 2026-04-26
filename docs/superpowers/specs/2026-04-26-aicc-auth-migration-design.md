# AICC Auth Migration — Design Spec

**Date:** 2026-04-26
**Status:** Approved (brainstorm), pending implementation plan
**Scope:** Replace Themis's NextAuth + Google OAuth + local allow-list with AICC PKCE auth.

## Goals

- AICC is the single source of truth for user identity and project membership.
- Themis backend code keeps working with `user.role == "admin"` checks; the AICC integration is invisible to route handlers.
- No leftover allow-list in Themis (AICC `ProjectMembership` is the gate).
- Hard cutover: one PR, no feature flag, no compatibility shim.

## Non-Goals

- Cross-app SSO between Themis and other Myndtrick apps (separate cookie scopes; needs a different design).
- API keys / programmatic access for end users (use AICC virtual keys if needed later).
- Self-service "manage my sessions" UI (AICC dashboard handles per-session revoke).

## Decisions Locked In

| # | Decision | Rationale |
|---|---|---|
| Q1 | Hybrid: AICC owns identity; local `User` row auto-created on first login | Preserves existing FKs (favorites, sessions). |
| Q2 | Backend `/auth/me` lookup with **60-second** in-memory LRU cache, keyed by `sha256(access_token)` | AICC tokens are opaque, so per-request `/auth/me` is the only verification option. 60 s caps the AICC roundtrip cost; role-change staleness ≤ 60 s is acceptable. |
| Q3 | AICC `projectRole` is the source of truth, mirrored to local `User.role` on cache miss | Single place to manage admins; backend code stays simple (`user.role` keeps working). |
| Q4 | Hard cutover; `allowed_emails` table removed; AICC `ProjectMembership` is the gate | Tiny user base, one-time re-login is acceptable, eliminates duplicated source of truth. |
| Q5 | Full-page redirect login (no popup, no `@aicc/sdk` for auth) | Simpler, no popup-blocker issues. SDK's auth namespace stores tokens in `localStorage`, contradicting AICC's own best-practices doc. |

Wire protocol unchanged: frontend → backend uses `Authorization: Bearer <access_token>`; httpOnly cookies hold the tokens; the existing `/api/token` route exposes the access token to JS briefly.

Role mapping: AICC `projectRole == "admin"` → Themis `role = "admin"`; everything else → `"user"`. Strict by design — adding a new AICC role in the future will not accidentally elevate a Themis user.

## Architecture

```
┌─────────┐       ┌─────────────────────┐       ┌──────────────┐       ┌─────────────┐
│ Browser │  ⇄   │ Themis Next.js      │  ⇄   │ Themis FastAPI│  ⇄   │   AICC      │
│         │       │ (frontend + edge)   │       │  (backend)    │       │             │
└─────────┘       └─────────────────────┘       └──────────────┘       └─────────────┘
```

### Frontend (Next.js) — new pieces

| File | Purpose |
|---|---|
| `lib/aicc-auth.ts` | Pure functions wrapping AICC HTTP: `loginUrl()`, `exchangeCode()`, `refresh()`, `logout()`. |
| `app/api/auth/login/route.ts` | Generate PKCE verifier + state, set short-lived signed `aicc_pkce` cookie, 302 to AICC `/auth/authorize`. |
| `app/api/auth/callback/route.ts` | Receive `?code&state`, validate state, exchange via `/auth/token`, set `aicc_access` + `aicc_refresh` httpOnly cookies, redirect to `callbackUrl`. |
| `app/api/auth/logout/route.ts` | POST AICC `/auth/logout`, clear cookies, 302 to `/auth/signin`. |
| `app/api/token/route.ts` | **Rewritten.** Read `aicc_access` cookie; if expiring within 60 s, refresh via `/auth/token` using `aicc_refresh`; return `{ token, expiresAt }`. Per-session mutex prevents concurrent refresh. |
| `app/api/me/route.ts` | Server endpoint returning `{ email, name, picture, role }` for the signed-in user (used by the user menu and admin gates in the UI). |
| `middleware.ts` | Same shape as today: redirect unauthenticated requests to `/api/auth/login?callbackUrl=…`. Now checks for `aicc_access` cookie presence. |
| `app/auth/signin/page.tsx` | Replaced with a "Sign in with AICC" button that hits `/api/auth/login`. |

### Frontend — removed

- `lib/auth.ts` (NextAuth config)
- `lib/auth-context.tsx`
- `next-auth` package + `next-auth/providers/google` imports

### Backend (FastAPI) — changed pieces

| File | Change |
|---|---|
| `app/services/aicc_auth_client.py` | **New.** Owns `/auth/me` HTTP + `cachetools.TTLCache(maxsize=1024, ttl=60)`. |
| `app/auth.py` | Rewritten. `get_current_user` extracts bearer (or `?token=` for SSE), calls `AiccAuthClient.verify_token`, upserts local `User`, mirrors role/name/picture from AICC, returns User. `require_admin` unchanged. |
| `app/routers/admin.py` | Remove `verify-user` endpoint and allowed-email endpoints. |
| `app/models/user.py` | Remove `AllowedEmail`. Add nullable `users.aicc_user_id VARCHAR(64)`. |
| `app/config.py` | Add `AICC_AUTH_BASE_URL`, `AICC_AUTH_TTL_SECONDS`. Remove `NEXTAUTH_SECRET`. |

### Backend — `AiccAuthClient` interface

```python
class AiccUser(BaseModel):
    id: str
    email: str
    name: str | None
    avatar_url: str | None
    project_role: str | None  # "admin" | "editor" | "viewer" | ...

class AiccAuthClient:
    def __init__(self, base_url: str, ttl_seconds: int = 60, max_size: int = 1024): ...
    async def verify_token(self, access_token: str) -> AiccUser | None: ...
    def invalidate(self, access_token: str) -> None: ...
```

- One instance per process, attached to `app.state` at startup.
- 401 from AICC → return `None` (auth fails clean).
- Network / 5xx → raise `HTTPException(503, "Auth provider unreachable")`. Never silently downgrade access by treating an outage as "unauthenticated".
- **Only successful results are cached.** Failures must not be cached, to prevent cache-poisoning by spamming garbage tokens.

### Backend — `get_current_user` upsert behavior

On every cache miss (≤ once per 60 s per session per process):

1. Look up `User` by email returned from AICC.
2. If absent: create a new `User` with email, name, picture, mapped role, `aicc_user_id`, `last_login=now()`.
3. If present: sync `name`, `picture`, `role` (mapped), `aicc_user_id`, `last_login` from AICC; commit.
4. Return the local `User` row.

`db.commit()` runs unconditionally to update `last_login`. This is cheap.

## Sign-in & Token Lifecycle

### A. First sign-in (cold visit to a protected page)

```
1. Browser → GET /laws (no aicc_access cookie)
2. middleware → 302 /api/auth/login?callbackUrl=/laws
3. /api/auth/login:
     - generate verifier (32 random bytes, base64url)
     - generate state (uuid)
     - challenge = base64url(sha256(verifier))
     - set aicc_pkce cookie (httpOnly, SameSite=Lax, 5 min TTL):
         signed({ verifier, state, callbackUrl })
     - 302 to AICC /auth/authorize with client_id, redirect_uri, state,
       code_challenge, code_challenge_method=S256, identity_provider=google
4. AICC → Google OAuth → AICC issues authorization code
5. AICC → 302 /auth/callback?code=...&state=...
6. /api/auth/callback:
     - read + verify aicc_pkce cookie
     - assert state matches; clear aicc_pkce cookie
     - POST AICC /auth/token { grant_type, code, code_verifier }
     - set cookies:
         aicc_access     (httpOnly, Secure, SameSite=Lax, maxAge=expires_in)
         aicc_refresh    (httpOnly, Secure, SameSite=Lax, maxAge=30d)
         aicc_access_exp (NOT httpOnly — JS reads to know when to refresh)
     - 302 callbackUrl
7. Browser → GET /laws (with aicc_access cookie)
8. Page calls api.x() → getAuthToken() → GET /api/token → returns access token
9. fetch(FastAPI) with Authorization: Bearer <aicc_access>
10. FastAPI get_current_user → AiccCache miss → AICC /auth/me →
    upsert User → cache → return
```

### B. Returning visit, access token fresh

Same as A from step 7. AICC roundtrip happens at most once per 60 s per active session per backend process.

### C. Access token near-expiry, refresh token valid

`/api/token` sees `aicc_access_exp - now < 60 s` (or `aicc_access` cookie missing) →
POST AICC `/auth/token { grant_type: refresh_token, refresh_token: aicc_refresh }` →
set new cookies (both tokens are rotated by AICC) → return new access token.
Transparent to client code.

### D. Refresh token expired or revoked

`/auth/token` returns 4xx → `/api/token` clears all auth cookies, returns 401 →
frontend `apiFetch` catches the 401, redirects to `/api/auth/login?callbackUrl=<current>`.

### E. Logout

Browser → POST `/api/auth/logout` →
POST AICC `/auth/logout` with current access token →
clear `aicc_access`, `aicc_refresh`, `aicc_access_exp` →
302 to `/auth/signin`.

Backend cache is not actively invalidated; the entry expires within 60 s.

### F. SSE auth

`?token=<access_token>` query param, same as today. Frontend gets the token via
`getAuthToken()` → `/api/token` cookie indirection. Backend `get_current_user`
already supports the query-param fallback.

Caveat: access tokens leak into URL paths and access logs. Implementation must
ensure log scrubbing removes `?token=…`.

### G. Concurrent refresh race

Two simultaneous API calls during near-expiry could each trigger a refresh.
Mitigation: per-session in-memory mutex inside `/api/token` (keyed by cookie
hash) so only one refresh runs at a time. ~10 LOC, worth it.

## Configuration

### New env vars (frontend)

```
NEXT_PUBLIC_AICC_AUTH_BASE_URL  = https://aicommandcenter-production-d7b1.up.railway.app
NEXT_PUBLIC_AICC_AUTH_CLIENT_ID = themis-web
NEXT_PUBLIC_AICC_AUTH_REDIRECT  = https://<themis-host>/auth/callback
AICC_PKCE_COOKIE_SECRET         = <random 32+ bytes>   # signs the aicc_pkce cookie
```

### New env vars (backend)

```
AICC_AUTH_BASE_URL    = https://aicommandcenter-production-d7b1.up.railway.app
AICC_AUTH_TTL_SECONDS = 60
```

`AICC_AUTH_BASE_URL` is distinct from `AICC_BASE_URL` (the proxy URL, which has the `/v1` suffix).

### Removed env vars

```
NEXTAUTH_SECRET         (frontend + backend)
GOOGLE_CLIENT_ID        (frontend)
GOOGLE_CLIENT_SECRET    (frontend)
```

`AICC_KEY` (virtual key for the AI proxy) is unchanged — it's a separate concern.

## Database Migration

Themis uses on-boot additive migrations via `Base.metadata.create_all` + a
local `_add_column_if_missing` helper inside `app/main.py:lifespan`. There is
no Alembic. The migration plugs into the same place:

```python
# in lifespan(), inside the existing try block:
_add_column_if_missing(db, "users", "aicc_user_id", "VARCHAR(64)", None)
db.execute(text("DROP TABLE IF EXISTS allowed_emails"))
db.commit()
```

The `AllowedEmail` model class must be removed from `app/models/user.py`
**before** the `DROP TABLE` runs, so `Base.metadata.create_all` doesn't try
to recreate the table on the same boot.

`aicc_user_id` is nullable and backfilled lazily on next sign-in. No data
migration required.

Rollback (if needed): revert the code; the empty `allowed_emails` table
must be re-seeded manually from a pre-cutover snapshot. The leftover
`aicc_user_id` column is harmless under the reverted code.

## AICC Bootstrap (manual prep before merging the PR)

In the AICC dashboard, on the **THEMIS** project:

1. Create an auth client `themis-web`:
   - Redirect URIs:
     - `http://localhost:3000/auth/callback` (dev)
     - `https://<themis-prod-host>/auth/callback`
     - `https://<themis-staging-host>/auth/callback` (if any)
   - Allowed origins (CORS): same hosts (origins only).
   - Identity providers: Google.
2. Add `ProjectMembership` rows for every email currently in `allowed_emails`. Set `projectRole=admin` for users who currently have Themis `role="admin"`; default for everyone else.
   - A one-shot script (`backend/scripts/seed_aicc_memberships.py`) reads the local DB and emits the AICC API calls.

The PR is mergeable only once both items are done.

## Cutover Runbook

To be saved as `docs/superpowers/runbooks/2026-04-26-aicc-auth-cutover.md`.

```
T-1 day:
  - Create AICC auth client `themis-web` with all redirect URIs.
  - Run scripts/seed_aicc_memberships.py against prod DB.
  - Verify in dashboard: every current user is a member; admins have projectRole=admin.

T-0 (deploy):
  - Set new env vars on Railway (frontend + backend).
  - Deploy backend first.
    Expected: any in-flight NextAuth-bearing requests get 401 during the gap
    until frontend deploys. Acceptable for a small admin-tool user base.
  - Deploy frontend.
  - Smoke: sign out, sign in as admin, hit /settings (admin-gated).
  - Smoke: sign in as non-admin, verify 403 on admin pages, 200 on /laws.
  - Watch backend logs for [aicc-auth] errors for 30 min.

Rollback:
  - git revert merge commit; redeploy.
  - Restore NEXTAUTH_SECRET / GOOGLE_* env vars.
  - The new aicc_user_id column on users is nullable and harmless when reverted.
  - allowed_emails table will be empty; rebuild from a pre-cutover snapshot if needed.
```

The deploy ordering (backend first) is deliberate. The reverse ordering would briefly route AICC tokens at a backend that still expects NextAuth JWTs, breaking everyone for the duration.

## Error Handling

| Failure | Where caught | User sees | Logged as |
|---|---|---|---|
| AICC unreachable on `/auth/me` | `AiccAuthClient.verify_token` | 503 → toast "Auth provider unreachable, retrying…" | `[aicc-auth] /auth/me request failed: <err>` |
| AICC `/auth/me` returns 401 | `AiccAuthClient.verify_token` returns `None` | 401 → frontend redirects to `/api/auth/login?callbackUrl=<current>` | `[auth] token rejected by AICC for request %s` |
| AICC `/auth/me` returns 5xx | `AiccAuthClient.verify_token` raises 503 | 503 → toast | `[aicc-auth] /auth/me unexpected %d: %s` |
| `/auth/token` refresh returns 4xx | `/api/token` route handler | Cookies cleared; 401 → frontend redirects to login | `[auth] refresh failed: <err>` |
| AICC `/auth/token` returns 5xx | `/api/token` route handler | 503 to JS → toast; cookies preserved | `[auth] refresh upstream error: <err>` |
| Sign-in returns `error=access_denied` (not a project member) | `/api/auth/callback` | Error page: "You don't have access to Themis. Ask an admin to add you." | `[auth] callback error: access_denied for state=%s` |
| State mismatch on callback | `/api/auth/callback` | Error page: "Sign-in session expired, please try again." | `[auth] state mismatch: cookie=%s param=%s` |
| Missing `aicc_pkce` cookie on callback | `/api/auth/callback` | Same | `[auth] missing PKCE cookie on callback` |
| Concurrent refresh contention | `/api/token` mutex | Transparent | `[auth] refresh contention: waited %dms` |
| Garbage / forged token attempt | `verify_token` returns `None`, not cached | 401 | `[auth] token rejected by AICC` |

## Edge Cases

- **Concurrent sign-ins from two browsers** — independent flows, independent tokens.
- **User's role changes in AICC mid-session** — Themis sees it within 60 s of TTL expiry.
- **User removed from project mid-session** — within 60 s, next `/auth/me` returns 401, user kicked to login.
- **Server clock drift** — token expiry is enforced by AICC (opaque tokens, no local decode). `aicc_access_exp` cookie is only an early-refresh hint.
- **Multiple browser tabs** — share cookies; refresh in one tab updates all. Per-session mutex prevents thundering-herd refresh.
- **Existing users with `role="admin"` not seeded into AICC as `projectRole=admin`** — get demoted to `"user"` on first sign-in. The bootstrap step explicitly seeds admin memberships to prevent this.
- **`/internal/scheduler/*` webhook endpoints** — unaffected; they use HMAC, not bearer tokens.

## Testing Strategy

### Backend

- `tests/test_aicc_auth_client.py` (`httpx.MockTransport`):
  - happy path returns + caches `AiccUser`
  - 401 returns `None`, not cached
  - 5xx raises 503
  - network error raises 503
  - cache hit avoids second HTTP call
  - TTL expiry forces re-fetch
- `tests/test_auth_dependency.py` (patched `AiccAuthClient`):
  - first sign-in creates `User` with mapped role
  - existing user's role/name/picture/last_login synced from AICC
  - missing token → 401
  - invalid token → 401
  - `require_admin` accepts admin, rejects user
- `tests/test_admin_router.py` — assert `verify-user` and allowed-email endpoints are removed.

### Frontend

- `app/api/auth/login/route.test.ts` — verifier+state generated, PKCE cookie set, redirect URL constructed correctly (assert exact query params).
- `app/api/auth/callback/route.test.ts` — happy path + state mismatch + missing cookie + AICC token endpoint failure (mocked with `msw`).
- `app/api/token/route.test.ts` — fresh access cookie returned; near-expiry triggers refresh; refresh failure clears cookies and returns 401; concurrent calls serialize through mutex.
- `lib/aicc-auth.test.ts` — verifier/challenge generation against fixed RFC vectors.
- Manual end-to-end during cutover (sign in, sign out, role denied, mid-session expiry).

### Out of scope

- Real PKCE round-trips against production AICC (verified manually during cutover).
- Real Google OAuth (AICC owns it).

## Implementation Notes

- **Next.js version:** `frontend/AGENTS.md` warns that Themis runs a
  non-standard Next.js build with breaking changes from training-data
  conventions. Before writing route handlers, middleware, or cookie code,
  read `frontend/node_modules/next/dist/docs/` for the relevant APIs.
- **Cookie attributes in dev vs prod:** `Secure` cookies fail over plain
  HTTP. Dev (`localhost:3000`) needs `Secure=false`; prod needs
  `Secure=true`. Drive this from `NODE_ENV` or an explicit env var; do not
  hard-code.
- **`/api/me` caching:** Returns the same data every request within a
  Next.js request lifetime. Within one Server Component render tree, cache
  it via `React.cache()` so multiple consumers don't hit the cookie + the
  AICC roundtrip more than once.
