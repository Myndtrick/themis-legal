"""Load the committed ROBOR seed (scripts/seeds/robor_history.csv.gz) into the
interest_rates table. Standard-library only (no openpyxl), so it runs in the
prod container.

Why this exists: the live daily scraper (robor.py / curs-valutar-bnr.ro) only
exposes a ~5-month rolling window, so ROBOR before Themis started running was
missing — and variable-rate loan accrual (Exodus) fell back to spread-only for
those pre-coverage months. This loads the full BNR interactive-database history
(since Aug 1995) so there are no coverage gaps.

Idempotent: store_interest_rates does INSERT OR IGNORE on
(date, rate_type, tenor), so re-running is safe and dates already captured by
the daily scraper are left untouched. Imported rows are tagged source="bnr.ro".

The seed is produced from the BNR .xlsx export by scripts/build_robor_seed.py.

Usage (from backend/):
    python -m scripts.load_robor_seed                       # default seed path
    python -m scripts.load_robor_seed scripts/seeds/robor_history.csv.gz
In the prod container:
    uv run python -m scripts.load_robor_seed
"""
from __future__ import annotations

import sys
from pathlib import Path

from app import database as _db
from app.services.rates.bnr_bdi import read_seed_csv_gz
from app.services.rates.robor import store_interest_rates

DEFAULT_SEED = Path(__file__).resolve().parent / "seeds" / "robor_history.csv.gz"
SOURCE = "bnr.ro"


def main(seed_path: str) -> int:
    rows = read_seed_csv_gz(seed_path)
    if not rows:
        print(f"[load-seed] no rows in {seed_path!r}", file=sys.stderr)
        return 1
    dates = sorted({r.date for r in rows})
    print(
        f"[load-seed] {len(rows)} ROBOR rows across {len(dates)} dates "
        f"({dates[0]} -> {dates[-1]})"
    )
    db = _db.SessionLocal()
    try:
        inserted = store_interest_rates(db, rows, source=SOURCE)
    finally:
        db.close()
    print(f"[load-seed] inserted {inserted} new rows (existing left untouched)")
    return 0


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_SEED)
    raise SystemExit(main(path))
