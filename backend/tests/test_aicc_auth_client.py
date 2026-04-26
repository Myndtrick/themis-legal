"""Unit tests for AiccAuthClient — the only path through which Themis
verifies user tokens against AICC."""
import httpx
import pytest
from fastapi import HTTPException

from app.services.aicc_auth_client import AiccAuthClient, AiccUser


def _mock_transport(handler):
    """httpx.MockTransport that delegates each request to `handler`."""
    return httpx.MockTransport(handler)


def test_aicc_user_parses_full_payload():
    payload = {
        "id": "user-uuid-123",
        "email": "alice@example.com",
        "name": "Alice",
        "avatarUrl": "https://lh3.googleusercontent.com/a/x",
        "role": "user",
        "globalRole": "user",
        "projectRole": "admin",
        "projectId": "project-uuid",
    }
    u = AiccUser.model_validate(payload)
    assert u.id == "user-uuid-123"
    assert u.email == "alice@example.com"
    assert u.name == "Alice"
    assert u.avatar_url == "https://lh3.googleusercontent.com/a/x"
    assert u.project_role == "admin"


def test_aicc_user_handles_nullable_fields():
    payload = {
        "id": "user-uuid-456",
        "email": "bob@example.com",
        "name": None,
        "avatarUrl": None,
        "role": "user",
        "globalRole": "user",
        "projectRole": None,
        "projectId": None,
    }
    u = AiccUser.model_validate(payload)
    assert u.name is None
    assert u.avatar_url is None
    assert u.project_role is None


def test_verify_token_returns_user_on_200():
    payload = {
        "id": "u1",
        "email": "alice@example.com",
        "name": "Alice",
        "avatarUrl": None,
        "role": "user",
        "globalRole": "user",
        "projectRole": "admin",
        "projectId": "p1",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/me"
        assert request.headers["Authorization"] == "Bearer access-xyz"
        return httpx.Response(200, json=payload)

    client = AiccAuthClient(
        base_url="https://aicc.test",
        ttl_seconds=60,
        transport=_mock_transport(handler),
    )
    user = client.verify_token("access-xyz")
    assert user is not None
    assert user.email == "alice@example.com"
    assert user.project_role == "admin"


def test_verify_token_caches_result():
    call_count = {"n": 0}
    payload = {
        "id": "u1", "email": "alice@example.com", "name": None,
        "avatarUrl": None, "role": "user", "globalRole": "user",
        "projectRole": None, "projectId": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json=payload)

    client = AiccAuthClient(
        base_url="https://aicc.test",
        ttl_seconds=60,
        transport=_mock_transport(handler),
    )
    client.verify_token("access-xyz")
    client.verify_token("access-xyz")
    assert call_count["n"] == 1, "second call should hit the cache"
