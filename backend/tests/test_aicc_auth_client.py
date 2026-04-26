"""Unit tests for AiccAuthClient — the only path through which Themis
verifies user tokens against AICC."""
from app.services.aicc_auth_client import AiccUser


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
