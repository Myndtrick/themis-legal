"""verify_caller accepts either a Themis user PKCE token or a shared
RATES_API_TOKEN bearer. Either path → request proceeds. Neither → 401."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


def _request_with(headers: dict | None = None):
    headers = headers or {}
    req = MagicMock()
    req.headers = headers
    return req


def test_no_auth_header_raises_401():
    from app.auth_service import verify_caller
    req = _request_with({})
    with pytest.raises(HTTPException) as exc:
        verify_caller(request=req, db=MagicMock())
    assert exc.value.status_code == 401


def test_service_token_match_returns_caller_dict():
    from app.auth_service import verify_caller
    with patch("app.auth_service.RATES_API_TOKEN", "service-secret-xyz"):
        req = _request_with({"Authorization": "Bearer service-secret-xyz"})
        result = verify_caller(request=req, db=MagicMock())
        assert result["kind"] == "service"


def test_service_token_mismatch_falls_through_to_user_path_and_fails():
    """If service token doesn't match, treat as user PKCE attempt — and that
    will 401 too without a real Themis user setup."""
    from app.auth_service import verify_caller
    aicc_mock = MagicMock()
    aicc_mock.verify_token.return_value = None  # rejects this fake token
    req = _request_with({"Authorization": "Bearer wrong-token"})
    req.app.state.aicc_auth = aicc_mock
    with patch("app.auth_service.RATES_API_TOKEN", "service-secret-xyz"):
        with pytest.raises(HTTPException) as exc:
            verify_caller(request=req, db=MagicMock())
        assert exc.value.status_code == 401


def test_user_pkce_token_path_returns_user_dict(tmp_path):
    """A bearer that's NOT the service token but IS a valid AICC user token."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    import app.models.user  # noqa: F401
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    from app.services.aicc_auth_client import AiccUser
    aicc_mock = MagicMock()
    aicc_mock.verify_token.return_value = AiccUser(
        id="u1", email="alice@example.com", name="Alice",
        avatar_url=None, project_role="admin",
    )
    req = _request_with({"Authorization": "Bearer user-pkce-token"})
    req.app.state.aicc_auth = aicc_mock

    from app.auth_service import verify_caller
    with patch("app.auth_service.RATES_API_TOKEN", "service-secret-xyz"):
        result = verify_caller(request=req, db=db)
    assert result["kind"] == "user"
    assert result["email"] == "alice@example.com"
    db.close()


def test_empty_service_token_disables_service_auth():
    """RATES_API_TOKEN='' must NEVER match — otherwise an attacker sending
    `Authorization: Bearer ` (literal empty) would auth in."""
    from app.auth_service import verify_caller
    aicc_mock = MagicMock()
    aicc_mock.verify_token.return_value = None
    with patch("app.auth_service.RATES_API_TOKEN", ""):
        req = _request_with({"Authorization": "Bearer "})
        req.app.state.aicc_auth = aicc_mock
        with pytest.raises(HTTPException) as exc:
            verify_caller(request=req, db=MagicMock())
        assert exc.value.status_code == 401
