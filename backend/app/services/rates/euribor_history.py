"""EURIBOR full DAILY history fetcher (euribor-rates.eu chart JSON API).

Why this exists: the per-year archive pages (``euribor.py``'s
``fetch_euribor_year`` / /euribor-rates-by-year/{year}/) only list the FIRST
business day of each month, so the original backfill produced MONTHLY-sampled
history (~12 rows/year/tenor). Consumers that resolve a rate for an arbitrary
date with a short walk-back window (Exodus loan accrual walks back max 7 days)
then find no fixing for most historical dates and treat the rate as missing —
a variable EURIBOR loan accrues on the spread alone. The site's interactive
charts, however, are fed by a JSON endpoint that serves the COMPLETE daily
series (1999 → today) for every tenor.

Endpoint contract (verified live 2026-07-02):

  GET https://www.euribor-rates.eu/umbraco/api/chartpageapi/highchartsdata
      ?minTicks=<epoch_ms>&maxTicks=<epoch_ms>&series[]=<id>[&series[]=<id>...]

  - Headers: a same-origin ``Referer`` AND ``Sec-Fetch-Mode: cors`` are BOTH
    required — the endpoint returns 401 without them. No cookies/token needed;
    the Themis UA string is accepted.
  - ``series[]``: 1=1M, 2=3M, 3=6M, 4=12M, 5=1W. Max 3 ids per call (4+ → 400).
  - Response: ``[{"Id": 1, "Data": [[epoch_ms, rate_percent], ...]}, ...]``
    ascending by date; business days only; epoch is UTC midnight of the
    fixing date; rate is the percentage as published (e.g. 3.856).
  - CRITICAL: requests spanning MORE than ~2 years are silently DOWNSAMPLED
    to a ~9-day grid. Always fetch in windows of at most 2 calendar years —
    ``iter_history_windows`` below — or the "daily" history comes back sparse
    and quietly reintroduces the original bug.

Failure semantics (money-path data — partial success must be VISIBLE):
``fetch_euribor_history`` returns an ``EuriborHistoryFetchResult`` whose
``failures`` list one entry per failed window×batch request and whose
``sparse_warnings`` flag any PER-TENOR window that came back below daily
density. Callers must treat ``failures`` as errors (the backfill falls back to
the archive pages and reports them); sparse warnings are surfaced in summaries
but don't abort — the stored rows are still correct fixings.
"""
from __future__ import annotations

import datetime
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx
from sqlalchemy.orm import Session

from app.services.rates.robor import ParsedInterestRate, store_interest_rates

logger = logging.getLogger(__name__)

CHART_URL = "https://www.euribor-rates.eu/umbraco/api/chartpageapi/highchartsdata"
CHART_REFERER = "https://www.euribor-rates.eu/en/euribor-charts/"

# Same source tag as the daily scraper (euribor.py) — it IS the same publisher,
# just a different page — so consumers see one uniform EURIBOR source string.
HISTORY_SOURCE = "euribor-rates.eu"

# EURIBOR fixings exist since 1999-01-01 (verified: 1M on 1999-01-01 = 3.254%).
HISTORY_START_YEAR = 1999

# Chart series id → tenor code, matching the tenor codes the rest of the rates
# feed uses (interest_rates.tenor). Discontinued post-2013-reform tenors
# (2W, 2M, 4M, ...) are deliberately absent.
SERIES_TO_TENOR: dict[int, str] = {1: "1M", 2: "3M", 3: "6M", 4: "12M", 5: "1W"}

# ≤3 series per call (endpoint limit) → two batches cover all five tenors.
_SERIES_BATCHES: tuple[tuple[int, ...], ...] = ((1, 2, 3), (4, 5))

# Server downsamples windows longer than ~2 years (verified: 3y → ~9-day grid).
MAX_WINDOW_YEARS = 2

_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Themis rates feed)",
    "Accept": "application/json",
    # Both required — the endpoint 401s without them (verified live).
    "Referer": CHART_REFERER,
    "Sec-Fetch-Mode": "cors",
}


@dataclass
class EuriborHistoryFetchResult:
    """Rows plus machine-readable quality signals.

    ``failures``: one entry per window×batch request that errored (network /
    non-200 / non-JSON). Data for those tenors×dates is simply absent — the
    caller must NOT treat the fetch as fully successful.
    ``sparse_warnings``: per-tenor windows that returned suspiciously few
    points (possible upstream downsampling / dropped series). Data present but
    below daily density.
    """

    rows: list[ParsedInterestRate] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    sparse_warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _epoch_ms(d: datetime.date) -> int:
    """UTC midnight of ``d`` in epoch milliseconds (the endpoint's tick unit)."""
    return int(
        datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).timestamp() * 1000
    )


def iter_history_windows(
    start_year: int, today: datetime.date
) -> list[tuple[datetime.date, datetime.date]]:
    """Contiguous ≤2-calendar-year [from, to] windows from Jan 1 of
    ``start_year`` through ``today``.

    Kept ≤ MAX_WINDOW_YEARS because the upstream endpoint silently
    downsamples longer ranges (see module docstring).
    """
    if start_year > today.year:
        return []
    windows: list[tuple[datetime.date, datetime.date]] = []
    cursor = datetime.date(start_year, 1, 1)
    while cursor <= today:
        window_end = min(datetime.date(cursor.year + MAX_WINDOW_YEARS - 1, 12, 31), today)
        windows.append((cursor, window_end))
        cursor = window_end + datetime.timedelta(days=1)
    return windows


def parse_highcharts_payload(payload: Any) -> list[ParsedInterestRate]:
    """Parse one chart-API JSON payload into ParsedInterestRate rows.

    Pure — no I/O. Tolerant of junk: non-list payloads, unknown series ids,
    malformed points, and non-numeric rates are skipped (the store step is
    idempotent, so partial data is always safe to keep).
    """
    if not isinstance(payload, list):
        return []
    out: list[ParsedInterestRate] = []
    for series in payload:
        if not isinstance(series, dict):
            continue
        tenor = SERIES_TO_TENOR.get(series.get("Id"))  # type: ignore[arg-type]
        if tenor is None:
            continue
        data = series.get("Data")
        if not isinstance(data, list):
            continue
        for point in data:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            ms, rate = point[0], point[1]
            if isinstance(rate, bool) or not isinstance(rate, (int, float)):
                continue
            if isinstance(ms, bool) or not isinstance(ms, (int, float)):
                continue
            date = (
                datetime.datetime.fromtimestamp(ms / 1000.0, tz=datetime.timezone.utc)
                .date()
                .isoformat()
            )
            out.append(
                ParsedInterestRate(
                    date=date, rate_type="EURIBOR", tenor=tenor, rate=float(rate)
                )
            )
    return out


def _tenor_looks_downsampled(
    tenor_rows: int, window: tuple[datetime.date, datetime.date]
) -> bool:
    """Per-tenor guard for the silent-downsampling failure mode.

    A daily series has ~256 business days/year; the downsampled grid has ~40.
    Flag when ONE tenor's window returns fewer than ~40% of the expected
    business days — per tenor, so four dense tenors can't mask a fifth that
    came back sparse or empty. Warning-only: sparse data is still stored
    (idempotent), just loudly reported.
    """
    days = (window[1] - window[0]).days + 1
    if days < 60:  # tiny tail windows (early January) are legitimately small
        return False
    expected_business_days = days * 5 / 7
    return tenor_rows < 0.4 * expected_business_days


def fetch_euribor_history(
    client: httpx.Client | None = None,
    *,
    start_year: int = HISTORY_START_YEAR,
    today: datetime.date | None = None,
    pause_s: float = 0.5,
) -> EuriborHistoryFetchResult:
    """Fetch the complete DAILY EURIBOR series (all 5 tenors) since
    ``start_year``.

    Iterates ≤2-year windows × 2 series-batches (≈28 requests for the full
    1999→today history), pausing ``pause_s`` between requests to stay polite.
    Failures are per-window×batch: an HTTP error skips that request, is
    recorded in ``result.failures``, and the fetch continues — re-running
    fills any gaps (storage is INSERT OR IGNORE).
    """
    if today is None:
        today = datetime.datetime.now(datetime.timezone.utc).date()

    own = client is None
    if own:
        client = httpx.Client(timeout=60.0, follow_redirects=True, headers=_REQUEST_HEADERS)
    assert client is not None

    result = EuriborHistoryFetchResult()
    dedup: dict[tuple[str, str], ParsedInterestRate] = {}
    try:
        windows = iter_history_windows(start_year, today)
        first_request = True
        for window in windows:
            # Per-tenor point counts for THIS window; tenors whose batch
            # failed are excluded from the density check (already failures).
            window_counts: dict[str, int] = {t: 0 for t in SERIES_TO_TENOR.values()}
            failed_series: set[int] = set()

            for batch in _SERIES_BATCHES:
                if not first_request and pause_s > 0:
                    time.sleep(pause_s)
                first_request = False

                params: list[tuple[str, str]] = [
                    ("minTicks", str(_epoch_ms(window[0]))),
                    # End-of-day so a fixing stamped at the window-end midnight
                    # is included regardless of the server's comparison.
                    ("maxTicks", str(_epoch_ms(window[1]) + 86_399_999)),
                ]
                params.extend(("series[]", str(sid)) for sid in batch)

                failure: str | None = None
                payload: Any = None
                try:
                    r = client.get(CHART_URL, params=params, headers=_REQUEST_HEADERS)
                except httpx.RequestError as e:
                    failure = f"{window[0]}..{window[1]} series {batch}: network error {e}"
                else:
                    if r.status_code != 200:
                        failure = f"{window[0]}..{window[1]} series {batch}: HTTP {r.status_code}"
                    else:
                        try:
                            payload = r.json()
                        except ValueError:
                            failure = f"{window[0]}..{window[1]} series {batch}: non-JSON body"

                if failure is not None:
                    logger.error("[rates/euribor-history] %s", failure)
                    result.failures.append(failure)
                    failed_series.update(batch)
                    continue

                for row in parse_highcharts_payload(payload):
                    window_counts[row.tenor] = window_counts.get(row.tenor, 0) + 1
                    dedup[(row.date, row.tenor)] = row

            # Density check per tenor, only for tenors whose request succeeded.
            for sid, tenor in SERIES_TO_TENOR.items():
                if sid in failed_series:
                    continue
                if _tenor_looks_downsampled(window_counts.get(tenor, 0), window):
                    msg = (
                        f"{tenor} {window[0]}..{window[1]}: only "
                        f"{window_counts.get(tenor, 0)} points — upstream may be "
                        "DOWNSAMPLING or dropped the series; daily density NOT "
                        "guaranteed for this window."
                    )
                    logger.warning("[rates/euribor-history] %s", msg)
                    result.sparse_warnings.append(msg)
    finally:
        if own:
            client.close()

    result.rows = sorted(dedup.values(), key=lambda r: (r.date, r.tenor))
    return result


# One history backfill at a time (it's ~28 upstream calls + ~35k inserts).
# In-process guard only, which matches the deployment (single-replica,
# single-process uvicorn). Cross-path overlap with the admin backfill job is
# tolerable by design: writes are additive INSERT OR IGNORE on
# (date, rate_type, tenor) over a WAL SQLite with a 30s busy timeout, so the
# worst case is busy-waiting / a partial tenor chunk that the next idempotent
# run completes — never corruption or duplicates.
_history_backfill_lock = threading.Lock()


def try_acquire_history_backfill_lock() -> bool:
    return _history_backfill_lock.acquire(blocking=False)


def release_history_backfill_lock() -> None:
    _history_backfill_lock.release()


def run_euribor_history_backfill(
    db: Session,
    *,
    start_year: int = HISTORY_START_YEAR,
    fetched: EuriborHistoryFetchResult | None = None,
    fetched_rows: Iterable[ParsedInterestRate] | None = None,
) -> dict[str, Any]:
    """Fetch the daily EURIBOR history and store it additively.

    Storage is ``store_interest_rates`` → INSERT OR IGNORE on
    (date, rate_type, tenor): existing rows (the daily scraper's, or the old
    monthly-sampled archive rows) are left untouched; re-running is safe.

    Fetch failures (per window×batch) are counted in ``errors`` /
    ``error_messages`` so a PARTIAL fetch is never mistaken for a full one;
    per-tenor sparse windows are surfaced in ``sparse_warnings``.

    ``fetched`` / ``fetched_rows`` let tests (and callers that already
    fetched) inject data without network I/O.
    """
    summary: dict[str, Any] = {
        "start_year": start_year,
        "fetched_rows": 0,
        "inserted_rows": 0,
        "tenors": {},
        "sparse_warnings": [],
        "errors": 0,
        "error_messages": [],
    }

    if fetched is None:
        if fetched_rows is not None:
            fetched = EuriborHistoryFetchResult(rows=list(fetched_rows))
        else:
            fetched = fetch_euribor_history(start_year=start_year)

    summary["fetched_rows"] = len(fetched.rows)
    summary["sparse_warnings"] = list(fetched.sparse_warnings)
    if fetched.failures:
        summary["errors"] += len(fetched.failures)
        summary["error_messages"].extend(f"fetch: {f}" for f in fetched.failures)

    by_tenor: dict[str, list[ParsedInterestRate]] = {}
    for row in fetched.rows:
        by_tenor.setdefault(row.tenor, []).append(row)

    for tenor in sorted(by_tenor):
        tenor_rows = by_tenor[tenor]
        try:
            inserted = store_interest_rates(db, tenor_rows, source=HISTORY_SOURCE)
        except Exception as e:
            # Roll back so a failed chunk can't poison the session for the
            # remaining tenors (or the caller's follow-up writes).
            try:
                db.rollback()
            except Exception:  # pragma: no cover — best-effort cleanup
                pass
            summary["errors"] += 1
            summary["error_messages"].append(f"store[{tenor}]: {e}")
            logger.error("[rates/euribor-history] store failed for %s: %s", tenor, e)
            continue
        summary["inserted_rows"] += inserted
        summary["tenors"][tenor] = {
            "fetched": len(tenor_rows),
            "inserted": inserted,
            "from": tenor_rows[0].date,
            "to": tenor_rows[-1].date,
        }
        logger.info(
            "[rates/euribor-history] %s: %d fetched (%s..%s), %d newly inserted",
            tenor, len(tenor_rows), tenor_rows[0].date, tenor_rows[-1].date, inserted,
        )

    return summary
