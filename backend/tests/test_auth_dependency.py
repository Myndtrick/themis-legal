"""Tests for get_current_user — the AICC-backed dependency that every
protected endpoint consumes."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.auth import _map_role, get_current_user, require_admin
from app.models.user import User
from app.services.aicc_auth_client import AiccUser


def _aicc_user(email="alice@example.com", project_role="admin", aicc_id="aicc-uuid-1") -> AiccUser:
    return AiccUser(
        id=aicc_id,
        email=email,
        name="Alice",
        avatar_url="https://avatar/x",
        project_role=project_role,
    )


def _request_with_bearer(token: str | None, aicc_mock=None):
    """Minimal stand-in for a FastAPI Request object.

    Tests pass an aicc_mock to attach to request.app.state.aicc_auth so that
    get_current_user can resolve the client without a real lifespan.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = MagicMock()
    req.headers = headers
    req.app.state.aicc_auth = aicc_mock
    return req


@pytest.fixture
def db(tmp_path):
    """Disposable SQLite session with the User table created."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    s = Session()
    yield s
    s.close()


def test_role_map_admin_to_admin():
    assert _map_role("admin") == "admin"
    assert _map_role("ADMIN") == "admin"


def test_role_map_everything_else_to_user():
    assert _map_role("editor") == "user"
    assert _map_role("viewer") == "user"
    assert _map_role(None) == "user"
    assert _map_role("") == "user"
    assert _map_role("anything") == "user"


def test_first_signin_creates_user(db):
    aicc = MagicMock()
    aicc.verify_token.return_value = _aicc_user(project_role="admin")

    user = get_current_user(
        request=_request_with_bearer("tok", aicc_mock=aicc),
        token=None,
        db=db,
    )

    assert user.email == "alice@example.com"
    assert user.role == "admin"
    assert user.aicc_user_id == "aicc-uuid-1"
    assert db.query(User).count() == 1


def test_existing_user_role_synced_from_aicc(db):
    db.add(User(
        email="bob@example.com",
        name="Old Name",
        picture="old-pic",
        role="user",
        aicc_user_id="aicc-uuid-2",
    ))
    db.commit()

    aicc = MagicMock()
    aicc.verify_token.return_value = AiccUser(
        id="aicc-uuid-2",
        email="bob@example.com",
        name="New Name",
        avatar_url="new-pic",
        project_role="admin",  # promoted in AICC
    )

    user = get_current_user(_request_with_bearer("tok", aicc_mock=aicc), None, db)
    assert user.role == "admin"
    assert user.name == "New Name"
    assert user.picture == "new-pic"


def test_existing_user_demoted_when_aicc_strips_admin(db):
    db.add(User(
        email="charlie@example.com",
        role="admin",
        aicc_user_id="aicc-uuid-3",
    ))
    db.commit()

    aicc = MagicMock()
    aicc.verify_token.return_value = AiccUser(
        id="aicc-uuid-3",
        email="charlie@example.com",
        name=None,
        avatar_url=None,
        project_role="viewer",
    )

    user = get_current_user(_request_with_bearer("tok", aicc_mock=aicc), None, db)
    assert user.role == "user"


def test_no_token_raises_401(db):
    aicc = MagicMock()
    with pytest.raises(HTTPException) as exc:
        get_current_user(_request_with_bearer(None, aicc_mock=aicc), None, db)
    assert exc.value.status_code == 401
    aicc.verify_token.assert_not_called()


def test_invalid_token_raises_401(db):
    aicc = MagicMock()
    aicc.verify_token.return_value = None
    with pytest.raises(HTTPException) as exc:
        get_current_user(_request_with_bearer("garbage", aicc_mock=aicc), None, db)
    assert exc.value.status_code == 401


def test_query_token_fallback_for_sse(db):
    aicc = MagicMock()
    aicc.verify_token.return_value = _aicc_user()
    req = MagicMock()
    req.headers = {}  # no Authorization header
    req.app.state.aicc_auth = aicc
    user = get_current_user(req, "tok-via-query", db)
    assert user.email == "alice@example.com"
    aicc.verify_token.assert_called_once_with("tok-via-query")


def test_require_admin_accepts_admin():
    admin_user = User(email="x", role="admin")
    assert require_admin(admin_user) is admin_user


def test_require_admin_rejects_non_admin():
    plain_user = User(email="x", role="user")
    with pytest.raises(HTTPException) as exc:
        require_admin(plain_user)
    assert exc.value.status_code == 403
