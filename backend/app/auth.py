"""User authentication: AICC PKCE.

Verifies bearer tokens via AiccAuthClient (which talks to AICC /auth/me with
a TTL cache). On every successful verification, mirrors the AICC user into the
local `users` table so existing FKs and `user.role` checks keep working.
"""
from __future__ import annotations

import datetime
import logging

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.aicc_auth_client import AiccAuthClient

logger = logging.getLogger(__name__)

# Mapping AICC projectRole -> Themis role. Strict by design: only "admin"
# is privileged; any new AICC role is treated as a regular user until we
# explicitly opt it in.
_ROLE_MAP = {"admin": "admin"}


def _map_role(project_role: str | None) -> str:
    return _ROLE_MAP.get((project_role or "").lower(), "user")


def _resolve_aicc_client(request: Request) -> AiccAuthClient:
    """Internal: fetch the process-singleton AiccAuthClient from app.state.

    Tests can override this by setting `app.state.aicc_auth` directly, or by
    using `app.dependency_overrides[get_current_user]` for full bypass.
    """
    client: AiccAuthClient | None = getattr(request.app.state, "aicc_auth", None)
    if client is None:
        raise RuntimeError(
            "AiccAuthClient not initialized. Check app.main:lifespan startup."
        )
    return client


def get_aicc_client(request: Request) -> AiccAuthClient:
    """FastAPI dependency: returns the process-singleton AiccAuthClient.

    Kept as a public helper for routes that need the client directly.
    `get_current_user` does NOT depend on this — it resolves the client
    internally so that requests without a token can short-circuit to 401
    before touching app.state.
    """
    return _resolve_aicc_client(request)


def _extract_token(request: Request, query_token: str | None) -> str | None:
    """Read bearer token from Authorization header or `?token=` query param.

    The query-param fallback is needed for SSE (EventSource cannot set headers).
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer "):]
    return query_token


def get_current_user(
    request: Request,
    token: str | None = Query(None, alias="token"),
    db: Session = Depends(get_db),
) -> User:
    raw_token = _extract_token(request, token)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Resolve the AICC client lazily — only after we know there's a token to
    # verify. This keeps unauthed requests from crashing when app.state isn't
    # populated (e.g. tests using TestClient(app) without the lifespan context
    # manager). Tests that DO want to verify behavior past this point should
    # set `app.state.aicc_auth` to a mock before issuing the request.
    aicc = _resolve_aicc_client(request)
    aicc_user = aicc.verify_token(raw_token)
    if aicc_user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    desired_role = _map_role(aicc_user.project_role)
    user = db.query(User).filter(User.email == aicc_user.email).first()
    if user is None:
        user = User(
            email=aicc_user.email,
            name=aicc_user.name,
            picture=aicc_user.avatar_url,
            role=desired_role,
            aicc_user_id=aicc_user.id,
            last_login=datetime.datetime.utcnow(),
        )
        db.add(user)
        logger.info("[auth] created local user from AICC: %s (role=%s)", user.email, desired_role)
    else:
        if user.role != desired_role:
            logger.info("[auth] role change for %s: %s -> %s", user.email, user.role, desired_role)
            user.role = desired_role
        if user.name != aicc_user.name:
            user.name = aicc_user.name
        if user.picture != aicc_user.avatar_url:
            user.picture = aicc_user.avatar_url
        if user.aicc_user_id != aicc_user.id:
            user.aicc_user_id = aicc_user.id
        user.last_login = datetime.datetime.utcnow()

    db.commit()
    db.refresh(user)
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
