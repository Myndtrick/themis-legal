"""Tests for the BNR interactive-database (Baza de date interactivă) historical
ROBOR import parser.

The export ("ROBID - ROBOR - serii zilnice", verified 2026-05-31) has:
  - metadata rows 1-4, then a header row whose first cell is "Data",
  - two sub-header rows ("(% p.a.)" units; "BBZ_*" codes) with an empty date,
  - data rows: date (YYYY-MM-DD), then floats; missing values are "-".
Header columns interleave ROBID <tenor> ... then ROBOR <tenor> ...

We import ROBOR ONLY, and only the tenors consumers expect (ON, 1W, 1M, 3M,
6M, 12M) — ROBID, tomorrow-next, and 9M are skipped (matches robor.py).
"""
from __future__ import annotations

import datetime

from app.services.rates.bnr_bdi import parse_bnr_bdi_rows

# Column order mirrors the real export (a representative subset of ROBID cols
# plus the full ROBOR block including the skipped tomorrow-next + 9M).
_HEADER = (
    "Data",
    "ROBID overnight",
    "ROBID 1 lună",
    "ROBOR overnight",
    "ROBOR tomorrow next",
    "ROBOR 1 săptămână",
    "ROBOR 1 lună",
    "ROBOR 3 luni",
    "ROBOR 6 luni",
    "ROBOR 9 luni",
    "ROBOR 12 luni",
)


def _sheet():
    return [
        ("Nume clasa statistica:", "ROBID - ROBOR - serii zilnice"),
        ("Nota:", "serii disponibile începând din august 1995"),
        (),  # blank
        _HEADER,
        (None, " (% p.a.)", " (% p.a.)", " (% p.a.)", " (% p.a.)", " (% p.a.)",
         " (% p.a.)", " (% p.a.)", " (% p.a.)", " (% p.a.)", " (% p.a.)"),  # units row
        (None, "BBZ_BIDON", "BBZ_BID1M", "BBZ_BORON", "BBZ_BORTM", "BBZ_BOR1W",
         "BBZ_BOR1M", "BBZ_BOR3M", "BBZ_BOR6M", "BBZ_BOR9M", "BBZ_BOR12M"),  # codes row
        # date, ROBID-ON, ROBID-1M, ROBOR-ON, ROBOR-TN, 1W, 1M, 3M, 6M, 9M, 12M
        ("2026-05-29", 5.30, 5.40, 5.63, 5.64, 5.71, 5.75, 5.84, 5.91, "-", 5.97),
        # second row: datetime date + comma-decimal 1W string + missing 9M
        (datetime.datetime(2026, 5, 28), 5.31, 5.41, 5.64, 5.65, "5,72", 5.76, 5.85, 5.92, "-", 5.98),
    ]


def test_imports_only_robor_six_tenors_skipping_robid_tn_and_9m():
    rows = parse_bnr_bdi_rows(_sheet())
    # 2 dates × 6 ROBOR tenors (ON, 1W, 1M, 3M, 6M, 12M).
    assert len(rows) == 12
    assert {r.rate_type for r in rows} == {"ROBOR"}
    assert {r.tenor for r in rows} == {"ON", "1W", "1M", "3M", "6M", "12M"}
    by = {(r.date, r.tenor): r.rate for r in rows}
    assert by[("2026-05-29", "ON")] == 5.63
    assert by[("2026-05-29", "1W")] == 5.71
    assert by[("2026-05-29", "1M")] == 5.75
    assert by[("2026-05-29", "3M")] == 5.84
    assert by[("2026-05-29", "6M")] == 5.91
    assert by[("2026-05-29", "12M")] == 5.97
    # tomorrow-next (5.64) and 9M ("-") must NOT appear.
    assert ("2026-05-29", "TN") not in by
    assert ("2026-05-29", "9M") not in by


def test_normalizes_datetime_dates_and_comma_decimals():
    rows = parse_bnr_bdi_rows(_sheet())
    by = {(r.date, r.tenor): r.rate for r in rows}
    # datetime(2026,5,28) -> "2026-05-28"; "5,72" -> 5.72
    assert by[("2026-05-28", "1W")] == 5.72
    assert by[("2026-05-28", "3M")] == 5.85

def test_skips_missing_dash_values():
    rows = parse_bnr_bdi_rows(_sheet())
    # 9M is "-" on both rows → never emitted.
    assert all(r.tenor != "9M" for r in rows)


def test_returns_empty_without_a_header_row():
    assert parse_bnr_bdi_rows([("just", "metadata"), (), ("more", "junk")]) == []


def test_seed_csv_gz_roundtrip(tmp_path):
    """The gzipped-CSV seed (built locally) is read back stdlib-only in prod."""
    import csv
    import gzip

    from app.services.rates.bnr_bdi import SEED_CSV_FIELDS, read_seed_csv_gz

    p = tmp_path / "seed.csv.gz"
    with gzip.open(p, "wt", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(SEED_CSV_FIELDS)
        w.writerow(["2025-05-05", "ROBOR", "3M", "5.9"])
        w.writerow(["2025-05-05", "ROBOR", "6M", "6.0"])
    rows = read_seed_csv_gz(str(p))
    assert len(rows) == 2
    by = {(r.date, r.tenor): r.rate for r in rows}
    assert by[("2025-05-05", "3M")] == 5.9
    assert by[("2025-05-05", "6M")] == 6.0
    assert all(r.rate_type == "ROBOR" for r in rows)
