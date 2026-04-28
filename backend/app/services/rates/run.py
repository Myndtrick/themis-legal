"""Orchestrate the daily rates update.

Called from:
  - The AICC scheduler webhook handler (POST /internal/scheduler/rates-update).
  - Tests (directly).

Each fetcher is wrapped in its own try/except so one source's outage doesn't
block the others. Errors are counted; fully-failing runs still return a
result dict so the scheduler can log a non-empty summary.
"""
from __future__ import annotations

import logging
from typing import Any

from app import database as _db
from app.services.rates.bnr_fx import fetch_bnr_daily, store_fx_rates
from app.services.rates.euribor import fetch_euribor_current
from app.services.rates.robor import fetch_robor_current, store_interest_rates

logger = logging.getLogger(__name__)


def run_rates_update_check() -> dict[str, Any]:
    """Fetch + store rates from BNR, ROBOR, and EURIBOR sources.

    Returns a summary dict suitable for logging via scheduler_log_service.
    """
    summary: dict[str, Any] = {
        "fx_inserted": 0,
        "robor_inserted": 0,
        "euribor_inserted": 0,
        "errors": 0,
        "error_messages": [],
    }

    db = _db.SessionLocal()
    try:
        # BNR FX
        try:
            fx = fetch_bnr_daily()
            summary["fx_inserted"] = store_fx_rates(db, fx)
            logger.info("[rates] BNR FX: %d new rows", summary["fx_inserted"])
        except Exception as e:
            summary["errors"] += 1
            summary["error_messages"].append(f"bnr_fx: {e}")
            logger.error("[rates] BNR FX failed: %s", e)

        # ROBOR
        try:
            robor = fetch_robor_current()
            summary["robor_inserted"] = store_interest_rates(db, robor, source="curs-valutar-bnr.ro")
            logger.info("[rates] ROBOR: %d new rows", summary["robor_inserted"])
        except Exception as e:
            summary["errors"] += 1
            summary["error_messages"].append(f"robor: {e}")
            logger.error("[rates] ROBOR failed: %s", e)

        # EURIBOR
        try:
            eur = fetch_euribor_current()
            summary["euribor_inserted"] = store_interest_rates(db, eur, source="euribor-rates.eu")
            logger.info("[rates] EURIBOR: %d new rows", summary["euribor_inserted"])
        except Exception as e:
            summary["errors"] += 1
            summary["error_messages"].append(f"euribor: {e}")
            logger.error("[rates] EURIBOR failed: %s", e)
    finally:
        db.close()

    return summary
