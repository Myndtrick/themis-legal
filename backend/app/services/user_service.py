import datetime
import logging

from sqlalchemy.orm import Session

from app.models.user import AllowedEmail, User

logger = logging.getLogger(__name__)

ADMIN_EMAILS = [
    "radu.gogoasa@gmail.com",
    "aandrei.0705@gmail.com",
]


def seed_admin_users(db: Session) -> None:
    """Seed admin users on startup if they don't exist."""
    for email in ADMIN_EMAILS:
        existing = db.query(User).filter(User.email == email).first()
        if not existing:
            db.add(User(email=email, role="admin"))
            logger.info(f"Seeded admin user: {email}")
    db.commit()


def verify_and_upsert_user(db: Session, email: str, name: str | None, picture: str | None) -> User | None:
    """Check if a user is allowed to sign in. Create/update User row if so.

    Returns the User if allowed, None if rejected.
    """
    # Check if already a user
    user = db.query(User).filter(User.email == email).first()
    if user:
        user.name = name
        user.picture = picture
        user.last_login = datetime.datetime.utcnow()
        db.commit()
        db.refresh(user)
        return user

    # Check whitelist
    allowed = db.query(AllowedEmail).filter(AllowedEmail.email == email).first()
    if not allowed:
        return None

    # Create new user from whitelist
    user = User(email=email, name=name, picture=picture, role="user")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
