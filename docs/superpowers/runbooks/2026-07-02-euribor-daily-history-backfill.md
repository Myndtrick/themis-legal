# EURIBOR Daily-History Backfill Runbook

**Spec context:** `docs/superpowers/specs/2026-04-28-rates-feed-design.md`
**Prior art:** ROBOR dense-history seed (`scripts/load_robor_seed.py`, commit `d63800c`)

## The problem this fixes

The original EURIBOR backfill used the per-year archive pages
(`/euribor-rates-by-year/{year}/`), which list only the **first business day of
each month** — so `interest_rates` held ~12 EURIBOR rows/year/tenor
(monthly-sampled), while the daily scraper only densified data from ~2026-05
onward. Exodus loan accrual resolves a rate for an arbitrary date with a
**7-day walk-back**; against monthly samples most historical dates found
nothing → sentinel rate 0 → EURIBOR-indexed loans accrued on the spread alone.

## The fix

`app/services/rates/euribor_history.py` fetches the **complete daily series
(1999 → today, all 5 tenors: 1W/1M/3M/6M/12M)** from the same publisher's chart
JSON API:

```
GET https://www.euribor-rates.eu/umbraco/api/chartpageapi/highchartsdata
    ?minTicks=<epoch_ms>&maxTicks=<epoch_ms>&series[]=<id>   (≤3 ids/call)
Headers: Referer: <same-origin page> + Sec-Fetch-Mode: cors   (401 without both)
Series ids: 1=1M, 2=3M, 3=6M, 4=12M, 5=1W
```

**Windows must stay ≤ 2 years** — longer ranges are silently downsampled to a
~9-day grid by the server (the fetcher iterates 2-year windows and logs a
warning if a window comes back suspiciously sparse).

Wired into:
- `POST /api/rates/backfill-history?start_year=1999` — service-token ONLY
  (`RATES_API_TOKEN`; user PKCE tokens get 403 — humans use the admin path),
  synchronous, returns the per-tenor summary INCLUDING `errors`/
  `error_messages` (failed window×batch requests — a partial fetch is never
  a silent success) and `sparse_warnings` (per-tenor windows below daily
  density). Additive only: `INSERT OR IGNORE` on `(date, rate_type, tenor)`;
  concurrent calls 409. Records a `scheduler_run_log` row (`rates`, manual).
- `run_rates_backfill` (admin `POST /api/admin/rates/backfill`) — fetches the
  dense history first; ONLY a clean fetch (rows + zero failures) skips the
  monthly-sampled year pages, otherwise the fallback still runs and the
  failures land in the job summary.
- `GET /api/rates/health` — now returns `euribor_tenors` (per-tenor row_count /
  latest_date / age_days) so sparse-tenor regressions are visible at a glance.

The daily scheduler job (`rates-update`) is **unchanged** — the current-rates
page it scrapes has carried all 5 tenors daily all along.

## Running the backfill (prod)

```bash
curl -sS -X POST -H "Authorization: Bearer $RATES_API_TOKEN" \
  "https://themis-legal-production.up.railway.app/api/rates/backfill-history?start_year=1999"
```

Expect ~1–2 min walltime (≈28 upstream calls, throttled 0.5 s apart) and a
summary like:

```json
{"start_year": 1999, "fetched_rows": 35000, "inserted_rows": 34400,
 "tenors": {"1M": {"fetched": 7000, "inserted": 6880, "from": "1999-01-01", "to": "2026-06-30"}, ...},
 "errors": 0, "error_messages": []}
```

Re-running is safe (idempotent; second run inserts ~0).

## Verification

```bash
# Per-tenor density at a glance (no auth):
curl -sS https://themis-legal-production.up.railway.app/api/rates/health

# Exodus's exact request shape for a EURIBOR_1M loan:
curl -sS -H "Authorization: Bearer $RATES_API_TOKEN" \
  "https://themis-legal-production.up.railway.app/api/rates/interest?rate_type=EURIBOR&tenor=1M&from=2024-02-20&to=2025-02-27&limit=10000"
# → ~265 business-day rows (was ~13 monthly samples before the backfill).
```

## Rollback

Nothing to roll back structurally: the change adds rows and endpoints, and the
stored daily rows are correct published fixings from the same source as the
daily scraper. If the chart endpoint ever breaks upstream, the backfill
degrades to the old per-year fallback and logs `[backfill] EURIBOR daily
history failed` / the fetcher logs `[rates/euribor-history]` warnings.
