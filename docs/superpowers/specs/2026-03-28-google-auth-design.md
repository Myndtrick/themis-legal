# Google Authentication & Access Control

## Overview

Add Google sign-in to Themis so that only whitelisted users can access the app. Unauthenticated users see a sign-in page. Admins can whitelist new emails via a Settings tab. The backend API is also protected — every request requires a valid JWT.

## Data Model

### `User` table (SQLite)

| Column     | Type         | Notes                          |
|------------|--------------|--------------------------------|
| id         | INTEGER PK   | auto-increment                 |
| email      | TEXT UNIQUE  | Google email                   |
| name       | TEXT         | from Google profile            |
| picture    | TEXT         | avatar URL                     |
| role       | TEXT         | `admin` or `user`              |
| created_at | DATETIME     | first sign-in                  |
| last_login | DATETIME     | updated each sign-in           |

### `AllowedEmail` table (SQLite)

| Column     | Type         | Notes                          |
|------------|--------------|--------------------------------|
| id         | INTEGER PK   | auto-increment                 |
| email      | TEXT UNIQUE  | whitelisted email              |
| added_by   | TEXT         | admin email who added it       |
| created_at | DATETIME     | when added                     |

### Seed data

On startup, seed two admin users if they don't exist:
- `radu.gogoasa@gmail.com` (admin)
- `aandrei.0705@gmail.com` (admin)

### Access logic

A Google sign-in is accepted if the email exists in `User` (returning user) or `AllowedEmail` (new whitelisted user). If in `AllowedEmail` but not `User`, create a `User` row with role `user` on first sign-in. If the email is in neither table, reject with "Access denied."

## Frontend Auth (NextAuth.js)

### Provider

- Google OAuth provider
- Session strategy: JWT (no database sessions)
- JWT payload: `email`, `name`, `picture`, `role`

### NextAuth callbacks

- **signIn callback**: Check email against `User` and `AllowedEmail` tables. Reject if not found. On first sign-in for whitelisted email, create `User` row via backend endpoint.
- **jwt callback**: Attach `role` from the database to the token.
- **session callback**: Expose `role` in the client-side session.

Note: The signIn callback needs to call the backend to check/create the user. Add a dedicated internal endpoint `POST /api/auth/verify-user` that NextAuth calls during sign-in. This endpoint checks the whitelist and returns/creates the user record.

### Middleware (`frontend/src/middleware.ts`)

- Runs on all routes except: `/auth/*`, `/api/auth/*`, `/_next/*`, `/favicon.ico`
- No valid session -> redirect to `/auth/signin`

### Sign-in page (`/auth/signin`)

- Centered layout, app logo ("Themis L&C"), "Sign in with Google" button
- Light gray background matching the app
- Error state: "Access denied. Contact an admin to get access."

### API calls — attaching the token

Update the shared fetch pattern used across the frontend. Files that define `API_BASE` and make fetch calls:
- `src/lib/api.ts`
- `src/lib/use-event-source.ts`
- `src/app/laws/search-import-form.tsx`
- `src/app/settings/categories/categories-table.tsx`
- `src/app/laws/[id]/status-badge.tsx`
- `src/app/laws/components/combined-search.tsx`

Create a shared `fetchWithAuth` wrapper that gets the session token and adds `Authorization: Bearer <token>` header. Replace raw `fetch` calls with this wrapper.

For `use-event-source.ts` (SSE), pass the token as a query parameter since `EventSource` doesn't support custom headers. Backend SSE endpoints accept `?token=<jwt>` as an alternative to the header.

## Backend Protection

### JWT verification dependency

New file: `backend/app/auth.py`

- `get_current_user(request)` — FastAPI dependency
  - Extracts JWT from `Authorization: Bearer <token>` header (or `?token=` query param for SSE)
  - Decodes and verifies using `NEXTAUTH_SECRET` (HS256)
  - Returns `{ email, name, role }` or raises 401
- `require_admin(user)` — depends on `get_current_user`, raises 403 if role != `admin`

### Route protection

Add `get_current_user` as a dependency at the router level for all existing routers:
- `categories.router`
- `laws.router`
- `notifications.router`
- `assistant_router.router`
- `settings_prompts.router`
- `settings_pipeline.router`
- `settings_categories.router`

No per-route changes needed — the router-level dependency protects everything.

### Auth verification endpoint

`POST /api/auth/verify-user` — called by NextAuth signIn callback:
- Input: `{ email, name, picture }`
- Checks if email is in `User` table or `AllowedEmail` table
- If in `User`: update `last_login`, return user with role
- If in `AllowedEmail` only: create `User` with role `user`, return it
- If neither: return 403
- This endpoint is NOT protected by `get_current_user` (it's called during sign-in)
- Protected by a shared secret header (`X-Auth-Secret: <NEXTAUTH_SECRET>`) to prevent abuse

### Admin endpoints

New router: `backend/app/routers/admin.py` with prefix `/api/admin`

- `GET /whitelist` — list all allowed emails (admin only)
- `POST /whitelist` — add email `{ email }` (admin only)
- `DELETE /whitelist/{email}` — remove email (admin only, can't remove admins)

Protected by `require_admin` dependency.

## Admin UI

### Settings page — "Users" tab

New tab in Settings alongside Prompt Management, Pipeline Tracking, Version History, Categories.

Only visible when the logged-in user has `role == "admin"`.

Contents:
- Table of whitelisted/active users showing: email, role (with badge), added by, date added
- Admins shown with "Admin" badge, no delete button
- Regular users have a delete/revoke button
- "Add Email" button at top — opens inline input + confirm button
- Simple, matches existing Settings tab styling

## Environment Variables

| Variable              | Service  | Purpose                                    |
|-----------------------|----------|--------------------------------------------|
| `GOOGLE_CLIENT_ID`    | Frontend | Google OAuth app ID                        |
| `GOOGLE_CLIENT_SECRET`| Frontend | Google OAuth app secret                    |
| `NEXTAUTH_SECRET`     | Both     | Signs/verifies JWTs                        |
| `NEXTAUTH_URL`        | Frontend | Canonical URL (localhost:4000 / Railway)   |

### Google Cloud Console setup (manual)

1. Create project or reuse existing one
2. Enable Google OAuth consent screen
3. Create OAuth 2.0 Client ID (Web application)
4. Authorized redirect URIs:
   - `http://localhost:4000/api/auth/callback/google`
   - `https://themis-frontend-production.up.railway.app/api/auth/callback/google`

## Testing

- Verify unauthenticated requests to any page redirect to `/auth/signin`
- Verify unauthenticated API calls return 401
- Verify sign-in with whitelisted email works and creates session
- Verify sign-in with non-whitelisted email shows "Access denied"
- Verify admin can add/remove emails in Settings > Users
- Verify non-admin cannot see Users tab or call admin endpoints
- Verify SSE (EventSource) connections work with token query param
