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
    if not sig_header:
        raise HTTPException(status_code=401, detail="missing X-AICC-Signature header")

    provided = sig_header.removeprefix("sha256=").strip()
    body = await request.body()
    expected = hmac.new(
        AICC_SCHEDULER_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(provided, expected):
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
