# AICC Auth Cutover Runbook

**Date written:** 2026-04-26
**Spec:** `docs/superpowers/specs/2026-04-26-aicc-auth-migration-design.md`
**Plan:** `docs/superpowers/plans/2026-04-26-aicc-auth-migration.md`

## What this does

Replaces NextAuth + Google OAuth + the local `allowed_emails` allow-list with
AICC PKCE auth. After cutover:

- Users sign in via AICC (Google still under the hood, but routed through AICC).
- The Themis backend verifies tokens by calling AICC `/auth/me` (60 s LRU cache).
- The local `User` row is auto-created on first sign-in; `User.role` mirrors
  AICC `projectRole` (only `"admin"` → `"admin"`, everything else → `"user"`).
- The local `allowed_emails` table is dropped. AICC `ProjectMembership` is
  the only access gate.

## T-1 day — bootstrap AICC

1. In the AICC dashboard, on the THEMIS project, create an auth client `themis-web`:
   - Redirect URIs:
     - `http://localhost:4000/api/auth/callback` (dev)
     - `https://<themis-prod>/api/auth/callback`
     - `https://<themis-staging>/api/auth/callback` (if any)
   - Allowed origins: same hosts.
   - Identity providers: Google.
2. Generate the PKCE cookie secret:
   ```bash
   openssl rand -base64 48
   ```
   Store it as `AICC_PKCE_COOKIE_SECRET` in your secrets manager.
3. Dump current Themis users + admins to seed AICC ProjectMembership:
   ```bash
   cd backend
   PYTHONPATH=. uv run python scripts/seed_aicc_memberships.py --format=json > /tmp/themis-members.json
   ```
4. Bulk-import `/tmp/themis-members.json` via the AICC dashboard
   (Project → THEMIS → Members → Import). Verify in dashboard:
   every current Themis admin has `projectRole=admin`. Everyone else
   gets `projectRole=editor`.

## T-0 — deploy

1. Set the new env vars on Railway:
   - **frontend**: `NEXT_PUBLIC_AICC_AUTH_BASE_URL`,
     `NEXT_PUBLIC_AICC_AUTH_CLIENT_ID=themis-web`,
     `NEXT_PUBLIC_AICC_AUTH_REDIRECT=https://<themis-prod>/api/auth/callback`,
     `AICC_PKCE_COOKIE_SECRET`.
   - **backend**: `AICC_AUTH_BASE_URL=https://aicommandcenter-production-d7b1.up.railway.app`,
     `AICC_AUTH_TTL_SECONDS=60`.
   - **remove** from both: `NEXTAUTH_SECRET`, `NEXTAUTH_URL`,
     `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.
2. Deploy **backend first**.
   - Why: any in-flight requests carrying old NextAuth JWTs will start
     getting 401 the moment the new backend is live. If the frontend deploys
     first, every request from the new frontend hits an old backend that
     can't verify AICC tokens — full outage.
   - Watch backend logs for: `AiccAuthClient initialized: base=… ttl=60s`,
     `Added column users.aicc_user_id`. The `allowed_emails` table is dropped
     silently via `DROP TABLE IF EXISTS`.
3. Deploy **frontend** immediately after.

## Smoke tests (run in this order)

1. Open the prod URL in a fresh incognito window.
2. You should be redirected to `/auth/signin`. Click "Sign in with AICC".
3. AICC's Google OAuth screen appears; sign in with an admin email.
4. You're redirected back to the home page. The user menu shows your name +
   avatar.
5. Visit any admin-gated settings page (e.g. `/settings/schedulers`). It
   loads. Good.
6. Open a private window and sign in as a non-admin. The home page loads.
   `/settings/schedulers` returns 403.
7. Watch backend logs for 30 minutes after deploy. Look for:
   - `[aicc-auth] /auth/me request failed` (>1/min suggests a problem)
   - `[aicc-auth] /auth/me unexpected` (any occurrence is unexpected)
   - `[auth] role change for ...` (informational)
   - `[auth] created local user from AICC: ...` (expected on first
     sign-in for each user)

## Rollback

1. `git revert <merge-commit>` and redeploy.
2. Restore `NEXTAUTH_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` env
   vars on Railway.
3. The leftover `aicc_user_id` column on `users` is nullable and ignored by
   the reverted code — leave it in place.
4. The `allowed_emails` table is empty after rollback. To restore the
   allow-list, restore the table from a pre-cutover DB snapshot (or recreate
   the rows manually based on the AICC ProjectMembership list).
