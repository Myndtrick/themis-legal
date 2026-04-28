"""Webhook endpoints called by AICC Scheduler on a cron schedule.

AICC POSTs to these URLs at the configured times. Each request is signed with
HMAC-SHA256 over the raw body using AICC_SCHEDULER_SECRET, in the
X-AICC-Signature header.

Responses return immediately after scheduling the work as a BackgroundTask so
AICC never sees a timeout — actual job success/failure is recorded in the
SchedulerRunLog table and visible in the Themis admin UI.
"""
from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.config import AICC_SCHEDULER_SECRET

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/scheduler", tags=["Internal Scheduler"])


async def _verify_signature(request: Request) -> None:
    if not AICC_SCHEDULER_SECRET:
        logger.error("AICC_SCHEDULER_SECRET is not configured")
        raise HTTPException(status_code=500, detail="scheduler secret not configured")

    sig_header = request.headers.get("X-AICC-Signature", "")
    body = await request.body()

    # TEMP diagnostic — log ALL headers + body preview on EVERY incoming
    # webhook so we can reverse-engineer AICC's signing format. Remove after
    # verification passes in production.
    all_headers = {k: v for k, v in request.headers.items() if k.lower().startswith(("x-", "content-"))}
    logger.warning(
        "AICC webhook arrived: path=%s headers=%s body_len=%d body_preview=%r",
        request.url.path, all_headers, len(body), body[:200],
    )

    if not sig_header:
        logger.warning("No X-AICC-Signature header present (available headers logged above)")
        raise HTTPException(status_code=401, detail="missing X-AICC-Signature header")

    provided = sig_header.removeprefix("sha256=").strip()
    expected_from_scheduler_secret = hmac.new(
        AICC_SCHEDULER_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    logger.warning(
        "Signature check: provided=%s expected(scheduler_secret)=%s match=%s",
        provided, expected_from_scheduler_secret,
        hmac.compare_digest(provided, expected_from_scheduler_secret),
    )

    if not hmac.compare_digest(provided, expected_from_scheduler_secret):
        logger.warning("HMAC signature mismatch on scheduler webhook")
        raise HTTPException(status_code=401, detail="invalid signature")


@router.post("/ro-update")
async def ro_update(request: Request, background_tasks: BackgroundTasks):
    """AICC cron: Romanian daily law-version discovery."""
    await _verify_signature(request)
    from app.main import run_update_check

    background_tasks.add_task(run_update_check)
    logger.info("AICC scheduler webhook accepted: ro-update")
    return {"status": "accepted", "job": "ro-update"}


@router.post("/eu-update")
async def eu_update(request: Request, background_tasks: BackgroundTasks):
    """AICC cron: EU weekly consolidated-version discovery."""
    await _verify_signature(request)
    from app.main import run_eu_update_check

    background_tasks.add_task(run_eu_update_check)
    logger.info("AICC scheduler webhook accepted: eu-update")
    return {"status": "accepted", "job": "eu-update"}


@router.post("/rates-update")
async def rates_update(request: Request, background_tasks: BackgroundTasks):
    """AICC cron: daily FX (BNR) + ROBOR + EURIBOR rates ingest."""
    await _verify_signature(request)

    def _run_and_log():
        from app.database import SessionLocal
        from app.services.rates.run import run_rates_update_check
        from app.services.scheduler_log_service import record_run

        results = run_rates_update_check()
        db = SessionLocal()
        try:
            record_run(db, "rates", results, "scheduled")
        finally:
            db.close()

    background_tasks.add_task(_run_and_log)
    logger.info("AICC scheduler webhook accepted: rates-update")
    return {"status": "accepted", "job": "rates-update"}
