"""Auth dependency for endpoints that accept either a Themis user PKCE
bearer (existing get_current_user path) OR a shared service-token bearer
(for service-to-service callers like Exodus).

Returns a small dict describing the caller. Routes that need to know who
made the call can inspect the result; routes that just need access control
can ignore it.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import RATES_API_TOKEN
from app.database import get_db

logger = logging.getLogger(__name__)


def _extract_bearer(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer "):].strip()
    return None


def verify_caller(request: Request, db: Session = Depends(get_db)) -> dict:
    """Accept service token OR Themis user PKCE token. Return a caller dict.

    Order of checks:
      1. If RATES_API_TOKEN is configured AND the bearer matches → service caller.
      2. Otherwise, fall through to get_current_user (user PKCE).

    Raises 401 if neither path authenticates.
    """
    token = _extract_bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Service-token path: only when token is configured (non-empty).
    # Constant-time compare to avoid leaking the token via response timing.
    if RATES_API_TOKEN and hmac.compare_digest(token, RATES_API_TOKEN):
        return {"kind": "service", "name": "rates-api-service"}

    # User-PKCE fallback: delegate to the existing user dependency. Any
    # exception from get_current_user (typically 401) propagates.
    from app.auth import get_current_user
    user = get_current_user(request=request, token=None, db=db)
    return {
        "kind": "user",
        "user_id": user.id,
        "email": user.email,
        "role": user.role,
    }
