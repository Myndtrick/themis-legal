"""Multi-year backfill of FX + interest rates.

ROBOR's source (curs-valutar-bnr.ro) doesn't expose per-year URLs the same
way BNR / euribor-rates.eu do. The simplest practical approach: call the
"current" page once during backfill — it returns a window of recent dates
which we INSERT OR IGNORE, so we don't double-store. Older ROBOR data is
out of scope until we identify a reliable archive source.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Callable

from app import database as _db
from app.services.rates.bnr_fx import fetch_bnr_year, store_fx_rates
from app.services.rates.euribor import fetch_euribor_year
from app.services.rates.robor import fetch_robor_current, store_interest_rates

logger = logging.getLogger(__name__)


def run_rates_backfill(
    years: int,
    current_year: int | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Backfill `years` years of rates from upstream sources.

    `current_year` is parameterized so tests don't depend on the system clock.
    """
    if current_year is None:
        current_year = datetime.datetime.utcnow().year

    start_year = current_year - years + 1
    year_range = list(range(start_year, current_year + 1))

    summary: dict[str, Any] = {
        "fx_inserted": 0,
        "euribor_inserted": 0,
        "robor_inserted": 0,
        "years_processed": [],
        "errors": 0,
        "error_messages": [],
    }

    db = _db.SessionLocal()
    try:
        # ROBOR: one call up front. curs-valutar-bnr.ro shows recent history
        # in one page; older ROBOR is out of scope.
        try:
            robor = fetch_robor_current()
            summary["robor_inserted"] = store_interest_rates(
                db, robor, source="curs-valutar-bnr.ro"
            )
            logger.info("[backfill] ROBOR: %d rows", summary["robor_inserted"])
        except Exception as e:
            summary["errors"] += 1
            summary["error_messages"].append(f"robor: {e}")
            logger.error("[backfill] ROBOR failed: %s", e)

        for i, year in enumerate(year_range, start=1):
            if on_progress is not None:
                on_progress(i, len(year_range), f"year {year}")

            # BNR FX yearly
            try:
                fx = fetch_bnr_year(year)
                inserted = store_fx_rates(db, fx)
                summary["fx_inserted"] += inserted
                logger.info("[backfill] BNR %d: %d rows", year, inserted)
            except Exception as e:
                summary["errors"] += 1
                summary["error_messages"].append(f"bnr_fx[{year}]: {e}")
                logger.error("[backfill] BNR %d failed: %s", year, e)

            # EURIBOR yearly
            try:
                eur = fetch_euribor_year(year)
                inserted = store_interest_rates(db, eur, source="euribor-rates.eu")
                summary["euribor_inserted"] += inserted
                logger.info("[backfill] EURIBOR %d: %d rows", year, inserted)
            except Exception as e:
                summary["errors"] += 1
                summary["error_messages"].append(f"euribor[{year}]: {e}")
                logger.error("[backfill] EURIBOR %d failed: %s", year, e)

            summary["years_processed"].append(year)
    finally:
        db.close()

    return summary
