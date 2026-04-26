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
