# AICC Embeddings Cutover Runbook

**Date written:** 2026-04-27
**Spec:** `docs/superpowers/specs/2026-04-27-aicc-embeddings-migration-design.md`
**Plan:** `docs/superpowers/plans/2026-04-27-aicc-embeddings-migration.md`

## What this does

Switches Themis search from in-process `sentence-transformers` (MiniLM-L12-v2,
384 dims) to AICC `/v1/embeddings` proxied to Voyage `voyage-3` (1024 dims).
Drops ~600 MB resident RAM. Old collection (`legal_articles`) stays on disk
through cutover for instant rollback.

## T-1 day — verify code is shipped

1. `git log origin/main` should include the AICC embeddings PR merge commit.
2. Confirm Railway redeploy succeeded after merge.
3. Confirm `EMBEDDING_PROVIDER` is **NOT** set in Railway env (default `local`
   keeps current behavior). The PR ships the code only.

## T-0 — cutover (operator-driven, ~30 min)

### Step 1: Announce window
Post in #themis (or wherever): "Themis search briefly degraded for next 30 min while we re-index against a new embedding model. BM25 keyword fallback active during the swap."

### Step 2: Build new collection (no downtime)

From a developer machine with Railway CLI auth:

```bash
cd /path/to/themis/backend
railway run --service Themis-legal -- bash -c '
  cd /app
  EMBEDDING_PROVIDER=aicc \
  EMBEDDING_MODEL_AICC=voyage-3 \
  PYTHONPATH=. uv run python scripts/reindex_with_aicc.py
'
```

This runs the reindex script inside the prod backend container with prod env.
Expected: log lines like `Re-indexing N law versions through AICC...`,
followed by `Reindex finished: M documents indexed into legal_articles_v2;
0 versions failed`. Walltime: 5-15 min depending on Voyage rate limits.

If the script reports failed version IDs, re-run the whole script — it's
idempotent (drops + rebuilds the v2 collection from scratch). If failures
persist after a second run, investigate the AICC virtual key / rate limit
before flipping the env var.

### Step 3: Verify v2 collection populated

Still via `railway run`:

```bash
railway run --service Themis-legal -- bash -c '
  cd /app
  PYTHONPATH=. uv run python -c "
import os
os.environ[\"EMBEDDING_PROVIDER\"] = \"aicc\"
from app.services.chroma_service import get_collection
c = get_collection()
print(\"collection:\", c.name, \"count:\", c.count())
print(\"sample:\", c.peek(2))
"
'
```

Expected: `collection: legal_articles_v2 count: ~12000` (your real article count).
Sample should show ID format `art-XXX` or `anx-XXX`. If count is 0, reindex
failed — investigate before proceeding.

### Step 4: Flip env var
On Railway dashboard for the `Themis-legal` service:
- Add variable: `EMBEDDING_PROVIDER=aicc`
- Save. Railway redeploys (~1 min).

### Step 5: Verify in prod

After redeploy completes, watch backend logs:

```bash
railway logs --service Themis-legal --lines 50
```

Look for: `Embedding provider: aicc (model=voyage-3)`. **Confirm absence
of any `Loading sentence-transformer model` line** (that means the old
path is still being hit).

Run a real search through the UI. Click into an assistant session, ask a
question that exercises retrieval, and confirm the response surfaces
relevant articles.

### Step 6: Verify RAM dropped

In Railway dashboard → `Themis-legal` → metrics. Backend RSS should drop
by ~600 MB within 5 min of redeploy. If you previously set the 3 GB cap,
expect headroom to grow (less risk of OOM).

### Step 7: Mark complete
Update this runbook (timestamp at the top) and post in #themis: cutover done.

## Rollback

Instant rollback: in Railway, set `EMBEDDING_PROVIDER=local` (or remove the
var entirely; default is `local`). Backend redeploys, queries hit the old
`legal_articles` collection again. Old embeddings are still on disk.

## Post-cutover cleanup (separate PR, 1-2 weeks later)

Once new path is proven stable:

1. Delete the old `legal_articles` collection from disk to recover ~30 MB:
   ```bash
   railway run --service Themis-legal -- bash -c '
     cd /app
     PYTHONPATH=. uv run python -c "
   from app.services.chroma_service import get_chroma_client
   client = get_chroma_client()
   client.delete_collection(\"legal_articles\")
   print(\"deleted\")
   "
   '
   ```
2. Remove `sentence-transformers` from `backend/pyproject.toml`. Saves ~470 MB
   in the Docker image.
3. Remove the `EMBEDDING_PROVIDER=local` branch from `chroma_service.py`.
4. Remove `EMBEDDING_MODEL` env var from Railway (used only by the local path).
