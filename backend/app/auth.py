import logging

import jwt
from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import NEXTAUTH_SECRET
from app.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)


def _decode_token(token: str) -> dict:
    """Decode and verify a NextAuth JWT."""
    try:
        payload = jwt.decode(token, NEXTAUTH_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def get_current_user(
    request: Request,
    token: str | None = Query(None, alias="token"),
    db: Session = Depends(get_db),
) -> User:
    """Extract and verify JWT from Authorization header or query param.

    Query param is used for SSE connections (EventSource can't set headers).
    """
    auth_header = request.headers.get("Authorization")

    raw_token = None
    if auth_header and auth_header.startswith("Bearer "):
        raw_token = auth_header[7:]
    elif token:
        raw_token = token

    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = _decode_token(raw_token)
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing email")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Dependency that requires the current user to be an admin."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
