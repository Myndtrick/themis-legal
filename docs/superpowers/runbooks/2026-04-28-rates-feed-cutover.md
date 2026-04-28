# Rates Feed Cutover Runbook

**Spec:** `docs/superpowers/specs/2026-04-28-rates-feed-design.md`
**Plan:** `docs/superpowers/plans/2026-04-28-rates-feed.md`

## What this enables

Daily ingest of FX rates (BNR), ROBOR, and EURIBOR into Themis, with REST
read endpoints for Exodus / other consumers, on AICC's scheduler.

## After PR merges

### Step 1 — backend env: RATES_API_TOKEN

Generate a shared service token:
```bash
openssl rand -base64 48
```

On Railway `Themis-legal` service → Variables → add:
```
RATES_API_TOKEN=<the value from openssl>
```

(Backend redeploys; ~1 min.)

### Step 2 — smoke check the API responds with 401

```bash
curl -s -o /dev/null -w "no-auth: %{http_code}\n" \
  https://themis-legal-production.up.railway.app/api/rates/exchange
```
Expect: `no-auth: 401` (auth gate is up).

```bash
curl -s -o /dev/null -w "with-token: %{http_code}\n" \
  -H "Authorization: Bearer <RATES_API_TOKEN>" \
  https://themis-legal-production.up.railway.app/api/rates/exchange?limit=1
```
Expect: `with-token: 200` and an empty body (no rows yet).

### Step 3 — kick the backfill

The backfill endpoint requires admin auth, not the service token.
Sign in to Themis as an admin, then from the browser DevTools console:

```js
const r = await fetch('/api/admin/rates/backfill?years=7', {
  method: 'POST',
  headers: { Authorization: `Bearer ${aicc_access_cookie}` },
});
console.log(await r.json());
```

Or via railway ssh:
```bash
railway ssh --service Themis-legal -- bash -c '
  cd /app && PYTHONPATH=. /app/.venv/bin/python -c "
from app.services.rates.backfill import run_rates_backfill
import json
r = run_rates_backfill(years=7)
print(json.dumps(r, default=str))
"'
```

Expect: ~10-20 min walltime; result like
```json
{"fx_inserted": 1800, "euribor_inserted": 1500, "robor_inserted": 250, "years_processed": [...], "errors": 0}
```

### Step 4 — register the AICC scheduler task

Either via dashboard (THEMIS project → Scheduler → + ADD TASK) or via API:

```bash
railway run --service Themis-legal -- bash -c 'curl -sS -X POST \
  -H "Authorization: Bearer $AICC_KEY" -H "Content-Type: application/json" \
  -d "{
    \"name\":\"themis-rates-daily-update\",
    \"cron\":\"0 12 * * 1-5\",
    \"enabled\":true,
    \"handlerType\":\"remote\",
    \"handlerRef\":\"https://themis-legal-production.up.railway.app/internal/scheduler/rates-update\",
    \"handlerConfig\":{\"timeoutMs\":60000,\"payload\":{},\"idempotent\":true},
    \"retryPolicy\":{\"maxAttempts\":3,\"backoffMs\":2000,\"backoffStrategy\":\"exponential\"}
  }" \
  "https://aicommandcenter-production-d7b1.up.railway.app/api/v2/projects/edacc097-1001-489b-a50b-0724ce7514e1/tasks"'
```

### Step 5 — RUN NOW the new task once

In AICC dashboard, click "RUN NOW" on `themis-rates-daily-update`. Expect:
- `lastResult: success` within ~30 sec.
- Backend log: `AICC scheduler webhook accepted: rates-update`.
- Then within ~10 sec: `[rates] BNR FX: N new rows`, `[rates] ROBOR: M new rows`, `[rates] EURIBOR: K new rows`.
- `scheduler_run_log` table gets a row with `id='rates'`.

### Step 6 — give Exodus the token

Add to Exodus's Railway env:
```
THEMIS_RATES_BASE_URL=https://themis-legal-production.up.railway.app
THEMIS_RATES_API_TOKEN=<same value as Themis>
```

Update Exodus's rates-pulling code to point at the Themis URL with the
`Authorization: Bearer ${THEMIS_RATES_API_TOKEN}` header.

## Rollback

If anything's wrong:
1. Disable the AICC scheduler task (toggle off in dashboard).
2. The endpoints stay live (no code revert needed); they just return whatever
   was already in the tables.
3. To fully back out: `git revert <merge-commit>` and redeploy.
