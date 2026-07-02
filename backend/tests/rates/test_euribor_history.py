"""EURIBOR daily-history fetcher (chart JSON API) tests.

Endpoint contract verified live 2026-07-02:
  GET /umbraco/api/chartpageapi/highchartsdata?minTicks=..&maxTicks=..&series[]=..
  Headers Referer + Sec-Fetch-Mode: cors required (401 otherwise).
  Response: [{"Id": <series>, "Data": [[epoch_ms_utc_midnight, rate_pct], ...]}]
  Windows longer than ~2 years are silently DOWNSAMPLED — the fetcher must
  iterate ≤2-year windows.

Failure semantics under test: fetch returns EuriborHistoryFetchResult; failed
window×batch requests land in .failures (partial ≠ success), per-tenor sparse
windows land in .sparse_warnings (one sparse tenor can't hide behind four
dense ones).
"""
from __future__ import annotations

import datetime

import httpx
import pytest


# ── window iteration ─────────────────────────────────────────────────────


def test_windows_cover_full_range_contiguously_and_max_2y():
    from app.services.rates.euribor_history import MAX_WINDOW_YEARS, iter_history_windows

    today = datetime.date(2026, 7, 2)
    windows = iter_history_windows(1999, today)

    assert windows[0][0] == datetime.date(1999, 1, 1)
    assert windows[-1][1] == today
    # Contiguous: each window starts the day after the previous one ends.
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
        assert next_start == prev_end + datetime.timedelta(days=1)
    # None spans more than MAX_WINDOW_YEARS calendar years.
    for start, end in windows:
        assert end.year - start.year < MAX_WINDOW_YEARS
    # 1999..2026 in 2-year windows = 14.
    assert len(windows) == 14


def test_windows_empty_when_start_year_in_future():
    from app.services.rates.euribor_history import iter_history_windows

    assert iter_history_windows(2027, datetime.date(2026, 7, 2)) == []


# ── payload parsing ──────────────────────────────────────────────────────

# 1704153600000 = 2024-01-02T00:00:00Z (verified sample from the live API).
_PAYLOAD = [
    {"Id": 1, "Data": [[1704153600000, 3.856], [1704240000000, 3.865]]},
    {"Id": 5, "Data": [[1704153600000, 3.902]]},
]


def test_parse_maps_series_ids_to_tenors_and_epochs_to_dates():
    from app.services.rates.euribor_history import parse_highcharts_payload

    rows = parse_highcharts_payload(_PAYLOAD)
    by = {(r.date, r.tenor): r.rate for r in rows}
    assert by[("2024-01-02", "1M")] == 3.856
    assert by[("2024-01-03", "1M")] == 3.865
    assert by[("2024-01-02", "1W")] == 3.902
    assert all(r.rate_type == "EURIBOR" for r in rows)


def test_parse_skips_unknown_series_and_junk_points():
    from app.services.rates.euribor_history import parse_highcharts_payload

    payload = [
        {"Id": 99, "Data": [[1704153600000, 1.0]]},        # unknown series id
        {"Id": 1, "Data": [[1704153600000], "junk", None,  # malformed points
                           [1704240000000, None],          # null rate
                           [1704240000000, True],          # bool rate (guard)
                           [1704326400000, 3.858]]},       # valid
        "not-a-dict",
        {"Id": 2},                                          # missing Data
    ]
    rows = parse_highcharts_payload(payload)
    assert len(rows) == 1
    assert rows[0].date == "2024-01-04"
    assert rows[0].tenor == "1M"
    assert rows[0].rate == 3.858


def test_parse_empty_on_non_list():
    from app.services.rates.euribor_history import parse_highcharts_payload

    assert parse_highcharts_payload(None) == []
    assert parse_highcharts_payload({"Id": 1}) == []
    assert parse_highcharts_payload("garbage") == []


# ── downsampling heuristic (per tenor) ───────────────────────────────────


def test_downsampled_tenor_detected_and_daily_tenor_passes():
    from app.services.rates.euribor_history import _tenor_looks_downsampled

    full_year = (datetime.date(2024, 1, 1), datetime.date(2024, 12, 31))
    # ~9-day grid: ~40 points/year for one tenor — must be flagged.
    assert _tenor_looks_downsampled(40, full_year) is True
    # Daily: ~256 points/year — must pass.
    assert _tenor_looks_downsampled(256, full_year) is False
    # Tiny tail window (a few days) is legitimately small — never flagged.
    tiny = (datetime.date(2026, 1, 1), datetime.date(2026, 1, 5))
    assert _tenor_looks_downsampled(3, tiny) is False


# ── fetch orchestration (mock transport) ─────────────────────────────────


def _daily_payload_for_series(series_ids: list[str], start_ms: int, points: int) -> list[dict]:
    """Dense fake series: `points` consecutive days from start_ms."""
    day_ms = 86_400_000
    return [
        {
            "Id": int(sid),
            "Data": [[start_ms + i * day_ms, 2.0 + int(sid) / 10] for i in range(points)],
        }
        for sid in series_ids
    ]


_JAN1_2025_MS = 1735689600000  # 2025-01-01T00:00:00Z


def test_fetch_sends_required_headers_windows_and_series_batches():
    from app.services.rates.euribor_history import CHART_REFERER, fetch_euribor_history

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        series = request.url.params.get_list("series[]")
        # Dense enough that no sparse warning fires (window ≈ 548 days).
        return httpx.Response(
            200, json=_daily_payload_for_series(series, _JAN1_2025_MS, 400)
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = fetch_euribor_history(
        client, start_year=2025, today=datetime.date(2026, 7, 2), pause_s=0
    )
    client.close()

    # One ≤2y window (2025-01-01..2026-07-02) × two series batches = 2 calls.
    assert len(seen) == 2
    for req in seen:
        assert req.headers["Referer"] == CHART_REFERER
        assert req.headers["Sec-Fetch-Mode"] == "cors"
        assert int(req.url.params["maxTicks"]) > int(req.url.params["minTicks"])
    assert seen[0].url.params.get_list("series[]") == ["1", "2", "3"]
    assert seen[1].url.params.get_list("series[]") == ["4", "5"]

    # All five tenors parsed; clean fetch → no failures, no sparse warnings.
    assert {r.tenor for r in result.rows} == {"1M", "3M", "6M", "12M", "1W"}
    assert result.failures == []
    assert result.sparse_warnings == []
    assert result.ok


def test_fetch_records_failed_batch_and_keeps_going():
    from app.services.rates.euribor_history import fetch_euribor_history

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500)
        series = request.url.params.get_list("series[]")
        return httpx.Response(
            200, json=_daily_payload_for_series(series, _JAN1_2025_MS, 400)
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = fetch_euribor_history(
        client, start_year=2025, today=datetime.date(2026, 7, 2), pause_s=0
    )
    client.close()

    # First batch (1M/3M/6M) failed → only the second batch's tenors present,
    # and the failure is machine-readable (partial ≠ success).
    assert {r.tenor for r in result.rows} == {"12M", "1W"}
    assert len(result.failures) == 1
    assert "HTTP 500" in result.failures[0]
    assert not result.ok
    # Tenors of the FAILED batch are not double-reported as sparse.
    assert result.sparse_warnings == []


def test_fetch_flags_single_sparse_tenor_among_dense_ones():
    """Four dense tenors must not mask one sparse/empty tenor (per-tenor check)."""
    from app.services.rates.euribor_history import fetch_euribor_history

    def handler(request: httpx.Request) -> httpx.Response:
        series = request.url.params.get_list("series[]")
        payload = []
        for sid in series:
            points = 30 if sid == "5" else 400  # 1W comes back downsampled
            payload.extend(_daily_payload_for_series([sid], _JAN1_2025_MS, points))
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = fetch_euribor_history(
        client, start_year=2025, today=datetime.date(2026, 7, 2), pause_s=0
    )
    client.close()

    assert result.failures == []
    assert len(result.sparse_warnings) == 1
    assert result.sparse_warnings[0].startswith("1W ")


def test_fetch_dedupes_overlapping_dates_across_windows():
    from app.services.rates.euribor_history import fetch_euribor_history

    def handler(request: httpx.Request) -> httpx.Response:
        # Every window returns the SAME point → must appear exactly once.
        return httpx.Response(200, json=[{"Id": 1, "Data": [[1704153600000, 3.856]]}])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = fetch_euribor_history(
        client, start_year=2023, today=datetime.date(2026, 7, 2), pause_s=0
    )
    client.close()

    assert len(result.rows) == 1
    assert result.rows[0].date == "2024-01-02"


def test_fetch_returns_failures_on_network_error():
    from app.services.rates.euribor_history import fetch_euribor_history

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = fetch_euribor_history(
        client, start_year=2026, today=datetime.date(2026, 7, 2), pause_s=0
    )
    client.close()
    assert result.rows == []
    # One window × two batches, both failed.
    assert len(result.failures) == 2
    assert not result.ok


# ── run_euribor_history_backfill (storage + idempotency) ─────────────────


@pytest.fixture
def db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    import app.models.rates  # noqa: F401

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_run_backfill_stores_rows_and_is_idempotent(db):
    from app.services.rates.euribor_history import (
        HISTORY_SOURCE,
        run_euribor_history_backfill,
    )
    from app.services.rates.robor import ParsedInterestRate
    from app.models.rates import InterestRate

    rows = [
        ParsedInterestRate(date="2024-01-02", rate_type="EURIBOR", tenor="1M", rate=3.856),
        ParsedInterestRate(date="2024-01-03", rate_type="EURIBOR", tenor="1M", rate=3.865),
        ParsedInterestRate(date="2024-01-02", rate_type="EURIBOR", tenor="3M", rate=3.921),
    ]

    first = run_euribor_history_backfill(db, start_year=2024, fetched_rows=rows)
    assert first["fetched_rows"] == 3
    assert first["inserted_rows"] == 3
    assert first["errors"] == 0
    assert first["sparse_warnings"] == []
    assert first["tenors"]["1M"] == {
        "fetched": 2, "inserted": 2, "from": "2024-01-02", "to": "2024-01-03",
    }
    assert first["tenors"]["3M"]["inserted"] == 1

    stored = db.query(InterestRate).all()
    assert len(stored) == 3
    assert all(r.source == HISTORY_SOURCE for r in stored)

    # Re-run: INSERT OR IGNORE → nothing new, nothing broken.
    second = run_euribor_history_backfill(db, start_year=2024, fetched_rows=rows)
    assert second["fetched_rows"] == 3
    assert second["inserted_rows"] == 0
    assert second["errors"] == 0
    assert db.query(InterestRate).count() == 3


def test_run_backfill_surfaces_fetch_failures_and_sparse_warnings(db):
    """A PARTIAL fetch must never present as a clean success (Codex P1)."""
    from app.services.rates.euribor_history import (
        EuriborHistoryFetchResult,
        run_euribor_history_backfill,
    )
    from app.services.rates.robor import ParsedInterestRate

    fetched = EuriborHistoryFetchResult(
        rows=[
            ParsedInterestRate(date="2024-01-02", rate_type="EURIBOR", tenor="1M", rate=3.856),
        ],
        failures=["2015-01-01..2016-12-31 series (1, 2, 3): HTTP 500"],
        sparse_warnings=["1W 2024-01-01..2024-12-31: only 30 points — ..."],
    )

    summary = run_euribor_history_backfill(db, start_year=2015, fetched=fetched)
    assert summary["inserted_rows"] == 1          # good rows still stored
    assert summary["errors"] == 1                 # but the failure is visible
    assert any("HTTP 500" in m for m in summary["error_messages"])
    assert summary["sparse_warnings"] == fetched.sparse_warnings


def test_run_backfill_preserves_existing_rows(db):
    """Rows already captured (daily scraper / old monthly archive) are left
    untouched — the history load only FILLS gaps."""
    from sqlalchemy import text

    from app.services.rates.euribor_history import run_euribor_history_backfill
    from app.services.rates.robor import ParsedInterestRate
    from app.models.rates import InterestRate

    db.execute(
        text(
            "INSERT INTO interest_rates (date, rate_type, tenor, rate, source, fetched_at) "
            "VALUES ('2024-01-02', 'EURIBOR', '1M', 3.856, 'euribor-rates.eu', datetime('now'))"
        )
    )
    db.commit()

    rows = [
        ParsedInterestRate(date="2024-01-02", rate_type="EURIBOR", tenor="1M", rate=3.856),
        ParsedInterestRate(date="2024-01-03", rate_type="EURIBOR", tenor="1M", rate=3.865),
    ]
    summary = run_euribor_history_backfill(db, start_year=2024, fetched_rows=rows)
    assert summary["inserted_rows"] == 1  # only the missing day
    assert db.query(InterestRate).count() == 2
