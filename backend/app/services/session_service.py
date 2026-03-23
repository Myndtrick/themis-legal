from __future__ import annotations

import datetime
import uuid

from sqlalchemy.orm import Session

from app.models.assistant import ChatMessage, ChatSession


def create_session(db: Session) -> ChatSession:
    """Create a new chat session."""
    session = ChatSession(
        id=str(uuid.uuid4()),
        created_at=datetime.datetime.utcnow(),
        last_active_at=datetime.datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id: str) -> ChatSession | None:
    return db.query(ChatSession).filter(ChatSession.id == session_id).first()


def list_sessions(db: Session) -> list[ChatSession]:
    return (
        db.query(ChatSession)
        .order_by(ChatSession.last_active_at.desc())
        .all()
    )


def delete_session(db: Session, session_id: str) -> bool:
    session = get_session(db, session_id)
    if not session:
        return False
    db.delete(session)
    db.commit()
    return True


def add_message(
    db: Session,
    session_id: str,
    role: str,
    content: str,
    mode: str | None = None,
    run_id: str | None = None,
    reasoning_data: str | None = None,
) -> ChatMessage:
    """Add a message to a session and update session metadata."""
    msg = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        mode=mode,
        run_id=run_id,
        reasoning_data=reasoning_data,
    )
    db.add(msg)

    # Update session metadata
    session = get_session(db, session_id)
    if session:
        session.last_active_at = datetime.datetime.utcnow()
        session.message_count = (session.message_count or 0) + 1
        # Auto-generate title from first user message
        if not session.title and role == "user":
            session.title = content[:100].strip()

    db.flush()
    return msg


def get_messages(db: Session, session_id: str) -> list[ChatMessage]:
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
        .all()
    )


def build_conversation_context(
    db: Session, session_id: str, max_messages: int = 20
) -> list[dict]:
    """Build message history for pipeline context (session memory)."""
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(max_messages)
        .all()
    )
    messages.reverse()
    return [{"role": msg.role, "content": msg.content} for msg in messages]
