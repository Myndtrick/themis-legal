# Rates Feed (FX + Interest Rates) — Design Spec

**Date:** 2026-04-28
**Status:** Approved (brainstorm), pending implementation plan
**Scope:** Daily fetch + storage + REST API for Romanian FX rates (BNR), ROBOR, and EURIBOR. Mirror exodus-live's existing data model and API surface so Exodus can switch source URL with no other changes.

## Goals

- Daily ingest of EUR/RON, USD/RON (and all other BNR currencies — same code path), ROBOR (all tenors), EURIBOR (all tenors).
- 7-year historical backfill on first deploy (or as much as the upstream sources expose).
- Clean REST API for Exodus to pull current + historical rates: `GET /api/rates/exchange`, `GET /api/rates/interest`.
- Cron driven by AICC Scheduler (consistent with Themis's other scheduled tasks: `themis-ro-daily-law-update`, `themis-eu-weekly-law-update`).
- Resilient to upstream outages: errors logged, daily run keeps going, missing days backfill on next run.

## Non-Goals

- Building a UI in Themis to view rates (data-only feature; UI lives in Exodus).
- Computing derived metrics (averages, percentiles, FX cross-rates). Just raw daily fixings.
- Pushing to Exodus on change (Exodus polls).
- Multi-source reconciliation. Each source is the single source of truth for its rate type.

## Decisions Locked In

| # | Decision | Rationale |
|---|---|---|
| Q1 | API auth: same as other Themis endpoints (auth-gated). Endpoints accept either a Themis user PKCE bearer (existing `get_current_user`) OR a shared secret bearer for service-to-service callers like Exodus. | "Same as other endpoints" for human users; shared secret is the pragmatic adapter for service callers since PKCE doesn't fit. |
| Q2 | Schedule: `0 12 * * 1-5` (12:00 UTC, Mon–Fri) | After BNR's daily fixing publication (~13:00 EET = 11:00 UTC standard / 10:00 UTC summer). Skips weekends — BNR doesn't fix on weekends. |
| Q3 | Backfill: 7 years on first run, or as much as upstream serves. | Covers virtually all contracts Exodus would historically reference. BNR yearly XML goes back ~20 years; ROBOR/EURIBOR HTML pages go back several years. |

## Architecture

```
┌────────────────────┐    cron    ┌────────────────────────────┐    HTTPS    ┌───────────────────────┐
│  AICC Scheduler    │───────────▶│ Themis backend             │────────────▶│ BNR / curs-valutar... │
│  themis-rates-     │   webhook  │  /internal/scheduler/      │   GET XML/  │ / euribor-rates.eu    │
│  daily-update      │  HMAC sig  │  rates-update              │   HTML       │                       │
└────────────────────┘            └────────────────────────────┘             └───────────────────────┘
                                          │
                                          │ INSERT OR IGNORE
                                          ▼
                                  ┌──────────────────────┐
                                  │ exchange_rates       │   Exodus / future consumers
                                  │ interest_rates       │   ◀───── GET /api/rates/{exchange,interest}
                                  └──────────────────────┘    Bearer <RATES_API_TOKEN> or PKCE
```

### Components

#### Tables (SQLite, on existing volume)

```sql
CREATE TABLE IF NOT EXISTS exchange_rates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  currency TEXT NOT NULL,
  rate REAL NOT NULL,
  multiplier INTEGER DEFAULT 1,
  source TEXT DEFAULT 'BNR',
  fetched_at TEXT DEFAULT (datetime('now')),
  UNIQUE(date, currency, source)
);
CREATE INDEX IF NOT EXISTS idx_exchange_rates_date ON exchange_rates(date);
CREATE INDEX IF NOT EXISTS idx_exchange_rates_currency ON exchange_rates(currency);

CREATE TABLE IF NOT EXISTS interest_rates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  rate_type TEXT NOT NULL,         -- 'ROBOR' | 'EURIBOR'
  tenor TEXT NOT NULL,             -- 'ON' | '1W' | '1M' | '3M' | '6M' | '12M'
  rate REAL NOT NULL,
  source TEXT NOT NULL,
  fetched_at TEXT DEFAULT (datetime('now')),
  UNIQUE(date, rate_type, tenor)
);
CREATE INDEX IF NOT EXISTS idx_interest_rates_date ON interest_rates(date);
CREATE INDEX IF NOT EXISTS idx_interest_rates_type ON interest_rates(rate_type);
```

Schema mirrors exodus-live exactly. Migration applied via the existing on-boot helper in `app/main.py:lifespan` (the same pattern that added `users.aicc_user_id`).

#### Fetcher services (new)

Three independent fetchers, each focused and testable in isolation:

- `app/services/rates/bnr_fx.py` — BNR daily + yearly XML. `parse_bnr_xml(xml: str) -> list[ParsedFxRate]`, `fetch_bnr_daily()`, `fetch_bnr_year(year: int)`, `store_fx_rates(db, rates) -> int`.
- `app/services/rates/robor.py` — `curs-valutar-bnr.ro/robor` HTML. Mirrors exodus-live's parser.
- `app/services/rates/euribor.py` — `euribor-rates.eu` HTML. Mirrors exodus-live's parser.

Each follows the same shape:
```python
@dataclass
class ParsedRate:
    date: str         # YYYY-MM-DD
    ...
def parse_*(content: str) -> list[ParsedRate]
def fetch_*() -> list[ParsedRate]      # current
def fetch_*_year(year: int) -> ...     # backfill
def store_*(db, rates) -> int          # INSERT OR IGNORE, returns inserted count
```

#### Scheduler webhook (new)

`app/routers/internal_scheduler.py` already has `ro-update` and `eu-update` handlers. Add `rates-update`:

```python
@router.post("/rates-update")
async def rates_update(request: Request, background_tasks: BackgroundTasks):
    await _verify_signature(request)  # existing HMAC check
    from app.main import run_rates_update_check
    background_tasks.add_task(run_rates_update_check)
    return {"status": "accepted", "job": "rates-update"}
```

`app/main.py:run_rates_update_check()` — calls all three fetchers, logs to `scheduler_run_log` (existing infrastructure, same pattern as `run_update_check` for ro-update).

#### Public API (new)

`app/routers/rates.py`:

```
GET /api/rates/exchange?currency=EUR&from=YYYY-MM-DD&to=YYYY-MM-DD&limit=N
GET /api/rates/interest?rate_type=ROBOR&tenor=3M&from=...&to=...&limit=N
```

Same query semantics as exodus-live. All params optional (default behavior: latest 30 rows).

Auth: a single `Depends(verify_caller)` that accepts:
- A Themis user PKCE token (delegates to `get_current_user`), OR
- A shared service-token bearer (matches `RATES_API_TOKEN` env var)

If neither matches → 401.

#### Admin backfill endpoint (new)

`POST /api/admin/rates/backfill?years=7` — admin-only. Kicks a background `Job` (existing infrastructure):

```python
@router.post("/rates/backfill")
def trigger_rates_backfill(years: int = 7, admin: User = Depends(require_admin)):
    job = job_service.enqueue("rates_backfill", payload={"years": years})
    return {"job_id": job.id}
```

Job worker:
1. For each year Y in (current_year - years + 1) ... current_year:
   - Fetch BNR yearly XML for Y, store. Continue on 404.
   - Fetch EURIBOR yearly page for Y, store. Continue on 404.
   - Fetch ROBOR for date range Jan-1-Y to Dec-31-Y. Continue on 404.
2. Update job progress after each year.

ROBOR's curs-valutar-bnr.ro doesn't expose yearly URLs the same way; backfill uses a date-range query. Expect ~5 years of ROBOR coverage; older years return empty (acceptable — log and continue).

### Configuration

#### New env vars (backend)

```
RATES_API_TOKEN=<random 32+ bytes>   # Shared secret for Exodus / service callers
```

Generated via `openssl rand -base64 48`. Set on Railway. Mirror to Exodus's env as `THEMIS_RATES_API_TOKEN`.

#### AICC scheduler task (manual setup, post-merge)

In AICC dashboard → THEMIS → Scheduler → Add task:

| Field | Value |
|---|---|
| Name | `themis-rates-daily-update` |
| Cron | `0 12 * * 1-5` |
| Enabled | ✅ |
| Handler type | `remote` |
| Handler ref | `https://themis-legal-production.up.railway.app/internal/scheduler/rates-update` |
| Timeout (ms) | `60000` |
| Retry: max attempts | `3` |
| Retry: backoff (ms) | `2000` |
| Retry: strategy | `exponential` |

## Error Handling

| Failure | Handler | Behavior |
|---|---|---|
| BNR XML 5xx / timeout | fetcher catches, logs `[rates] BNR fetch failed: ...`, returns `[]` | Daily run continues to next fetcher; nothing stored for FX |
| ROBOR / EURIBOR HTML parse fails | parser logs warning, returns parsed-so-far | Partial data stored; missing rows backfill next day |
| Insert hits UNIQUE constraint | `INSERT OR IGNORE` swallows, returns `0` newly inserted | Idempotent re-runs |
| `_verify_signature` fails on webhook | existing 401 path | Same as ro-update / eu-update |
| Backfill year out of range | `404 Not Found` from upstream → fetcher returns `[]` | Logged, year skipped |

## Testing Strategy

### Unit tests
- `tests/rates/test_bnr_fx.py`:
  - parse_bnr_xml: single-day feed, multi-day yearly feed, malformed XML, missing fields
  - store_fx_rates: idempotent (re-run = 0 newly inserted), commits, respects multiplier
- `tests/rates/test_robor.py`:
  - parse_robor_html: snapshot-fixture-based for the table on curs-valutar-bnr.ro
- `tests/rates/test_euribor.py`:
  - parse_euribor_html: same pattern
- `tests/rates/test_api_endpoints.py`:
  - GET /api/rates/exchange — filters by currency/from/to/limit
  - GET /api/rates/interest — filters by rate_type/tenor/from/to/limit
  - 401 with no auth, 200 with user PKCE token, 200 with `RATES_API_TOKEN` bearer
- `tests/rates/test_scheduler_webhook.py`:
  - signed POST → 200, run_rates_update_check called

### Integration / smoke
- One end-to-end test that hits BNR (actual network, marked slow / skipped in CI) to confirm the parser still works against real upstream XML. Run manually after deploy and during quarterly review.

### Out of scope
- Real ROBOR / EURIBOR parser regression tests are fixture-based; if upstream HTML changes, tests still pass but live data might break. Backstop: alert if `run_rates_update_check` records `0` new inserts for 3+ consecutive runs.

## File Map

### Created
- `backend/app/models/rates.py` — `ExchangeRate`, `InterestRate` SQLAlchemy models
- `backend/app/services/rates/__init__.py`
- `backend/app/services/rates/bnr_fx.py`
- `backend/app/services/rates/robor.py`
- `backend/app/services/rates/euribor.py`
- `backend/app/services/rates/run.py` — `run_rates_update_check()` orchestrates the three fetchers
- `backend/app/routers/rates.py` — public API endpoints
- `backend/app/auth_service_token.py` (or fold into `auth.py`) — `verify_caller` dependency that accepts user OR service-token
- `backend/tests/rates/test_bnr_fx.py`
- `backend/tests/rates/test_robor.py`
- `backend/tests/rates/test_euribor.py`
- `backend/tests/rates/test_api_endpoints.py`
- `backend/tests/rates/test_scheduler_webhook.py`
- `backend/tests/rates/fixtures/bnr_daily.xml`
- `backend/tests/rates/fixtures/bnr_yearly.xml`
- `backend/tests/rates/fixtures/robor.html`
- `backend/tests/rates/fixtures/euribor.html`
- `docs/superpowers/runbooks/2026-04-28-rates-feed-cutover.md`

### Modified
- `backend/app/main.py` — lifespan: `Base.metadata.create_all` picks up new models; on-boot migration ensures indices
- `backend/app/routers/internal_scheduler.py` — new `rates-update` endpoint
- `backend/app/routers/admin.py` — new `rates/backfill` endpoint
- `backend/app/services/job_service.py` — register `rates_backfill` job kind
- `backend/pyproject.toml` — add `beautifulsoup4` (HTML parsing for ROBOR / EURIBOR)
- `backend/.env` (gitignored) — add `RATES_API_TOKEN`

## Cutover (post-merge runbook)

1. Generate `RATES_API_TOKEN`: `openssl rand -base64 48`. Set on Railway `Themis-legal` service.
2. Deploy backend (auto via merge).
3. Smoke check: `curl -H "Authorization: Bearer $RATES_API_TOKEN" https://themis-legal-production.up.railway.app/api/rates/exchange?limit=1` → expect `[]` (empty until backfill).
4. Trigger backfill: `curl -X POST -H "Authorization: Bearer $RATES_API_TOKEN" "https://themis-legal-production.up.railway.app/api/admin/rates/backfill?years=7"`. Returns `{"job_id": ...}`. Poll job status. Expect ~10-20 min walltime, ~1-2k FX rows + several thousand interest-rate rows total.
5. Add the AICC scheduler task `themis-rates-daily-update` (config above).
6. Click "RUN NOW" on the new task once. Verify webhook arrives in Themis backend logs (`[search]`-style log line `[rates-update] inserted N FX, M ROBOR, K EURIBOR rates`).
7. Set `THEMIS_RATES_API_TOKEN` on Exodus's Railway service to the same secret. Update Exodus's rates-pulling code to point at `https://themis-legal-production.up.railway.app/api/rates/{exchange,interest}` instead of querying its own DB.

## Done Criteria

- All unit tests pass.
- `Base.metadata.create_all` creates the two tables on next boot.
- Manual smoke after deploy: empty endpoints respond 200 with `[]` (auth works).
- Backfill job completes for 7 years; row counts visible in admin UI.
- AICC scheduler task fires daily at 12:00 UTC; scheduler activity log shows successful runs.
- Exodus's rates calls succeed against Themis with shared bearer token.
