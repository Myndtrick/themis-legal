"""AICC auth client — single point of contact between Themis backend and the
AICC /auth/me endpoint.

Owns the in-memory LRU cache that keeps per-request /auth/me roundtrips bounded
to once per `ttl_seconds` per active session.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

import httpx
from cachetools import TTLCache
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class AiccUser(BaseModel):
    """Subset of AICC's /auth/me payload that Themis cares about.

    AICC field names use camelCase; we expose snake_case to the rest of the
    codebase via Field aliases.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    email: str
    name: str | None = None
    avatar_url: str | None = Field(default=None, alias="avatarUrl")
    project_role: str | None = Field(default=None, alias="projectRole")


class AiccAuthClient:
    """Verifies AICC access tokens via /auth/me with a TTL cache.

    Use one instance per process. Attach to `app.state.aicc_auth` at startup;
    inject into FastAPI dependencies via Depends(get_aicc_client).
    """

    def __init__(
        self,
        base_url: str,
        ttl_seconds: int = 60,
        max_size: int = 1024,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._cache: TTLCache = TTLCache(maxsize=max_size, ttl=ttl_seconds)
        self._http = httpx.Client(base_url=base_url, timeout=5.0, transport=transport)

    @staticmethod
    def _key(access_token: str) -> str:
        return hashlib.sha256(access_token.encode("utf-8")).hexdigest()

    def verify_token(self, access_token: str) -> Optional[AiccUser]:
        """Return the AiccUser for this token, or None if AICC rejects it.

        Raises HTTPException(503) on network errors or 5xx from AICC.
        Never caches a failure; only successful results land in the cache.
        """
        key = self._key(access_token)
        if (cached := self._cache.get(key)) is not None:
            return cached

        try:
            r = self._http.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.RequestError as e:
            logger.error("[aicc-auth] /auth/me request failed: %s", e)
            raise HTTPException(status_code=503, detail="Auth provider unreachable")

        if r.status_code == 401:
            return None

        if r.status_code != 200:
            logger.error(
                "[aicc-auth] /auth/me unexpected %d: %s",
                r.status_code,
                r.text[:200],
            )
            raise HTTPException(status_code=503, detail="Auth provider error")

        user = AiccUser.model_validate(r.json())
        self._cache[key] = user
        return user

    def invalidate(self, access_token: str) -> None:
        """Drop a single entry. Used after explicit logout."""
        self._cache.pop(self._key(access_token), None)

    def close(self) -> None:
        self._http.close()
