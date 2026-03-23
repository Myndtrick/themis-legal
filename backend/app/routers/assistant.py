from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.database import get_db
from app.schemas.assistant import (
    CreateSessionResponse,
    MessageRequest,
    MessageResponse,
    ResumeRequest,
    SessionDetailResponse,
    SessionSummary,
)
from app.services.session_service import (
    add_message,
    build_conversation_context,
    create_session,
    delete_session,
    get_messages,
    get_session,
    list_sessions,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["Legal Assistant"])


@router.post("/sessions", response_model=CreateSessionResponse)
def create_new_session(db: Session = Depends(get_db)):
    """Create a new chat session."""
    session = create_session(db)
    return CreateSessionResponse(
        id=session.id,
        title=session.title,
        created_at=session.created_at.isoformat(),
        last_active_at=session.last_active_at.isoformat(),
        message_count=session.message_count,
    )


@router.get("/sessions", response_model=list[SessionSummary])
def list_all_sessions(db: Session = Depends(get_db)):
    """List all chat sessions, most recent first."""
    sessions = list_sessions(db)
    return [
        SessionSummary(
            id=s.id,
            title=s.title,
            last_active_at=s.last_active_at.isoformat(),
            message_count=s.message_count,
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
def get_session_detail(session_id: str, db: Session = Depends(get_db)):
    """Get a session with all its messages."""
    session = get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = get_messages(db, session_id)
    return SessionDetailResponse(
        id=session.id,
        title=session.title,
        created_at=session.created_at.isoformat(),
        last_active_at=session.last_active_at.isoformat(),
        message_count=session.message_count,
        messages=[
            MessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                mode=m.mode,
                run_id=m.run_id,
                reasoning_data=m.reasoning_data,
                created_at=m.created_at.isoformat(),
            )
            for m in messages
        ],
    )


@router.post("/sessions/{session_id}/messages")
def send_message(
    session_id: str,
    req: MessageRequest,
    db: Session = Depends(get_db),
):
    """Send a message and get a streamed response via SSE.

    The pipeline runs step-by-step, streaming events:
      event: step    — pipeline step progress
      event: pause   — pipeline needs user input (import permission)
      event: token   — answer text chunk
      event: done    — final structured response
      event: error   — pipeline error
    """
    session = get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Store the user message
    add_message(db, session_id, "user", req.content)
    db.commit()

    # Build conversation context (session memory)
    context = build_conversation_context(db, session_id)

    def event_generator():
        from app.services.pipeline_service import run_pipeline

        # Use a fresh DB session for the generator (the original may close)
        from app.database import SessionLocal

        gen_db = SessionLocal()
        try:
            final_content = ""
            final_mode = None
            final_run_id = None
            final_reasoning = None

            for event in run_pipeline(req.content, context, gen_db):
                event_type = event.get("type", "unknown")

                if event_type == "token":
                    yield {
                        "event": "token",
                        "data": json.dumps({"text": event["text"]}, ensure_ascii=False),
                    }
                elif event_type == "step":
                    yield {
                        "event": "step",
                        "data": json.dumps(event, ensure_ascii=False),
                    }
                elif event_type == "pause":
                    yield {
                        "event": "pause",
                        "data": json.dumps(event, ensure_ascii=False),
                    }
                    # Store a partial assistant message
                    add_message(
                        gen_db, session_id, "assistant",
                        event.get("message", "Import needed"),
                        run_id=event.get("run_id"),
                    )
                    gen_db.commit()
                    return
                elif event_type == "done":
                    final_content = event.get("content", "")
                    final_mode = event.get("mode")
                    final_run_id = event.get("run_id")
                    final_reasoning = event.get("reasoning")
                    final_structured = event.get("structured")
                    final_confidence = event.get("confidence")
                    final_flags = event.get("flags", [])

                    yield {
                        "event": "done",
                        "data": json.dumps({
                            "content": final_content,
                            "structured": final_structured,
                            "mode": final_mode,
                            "run_id": final_run_id,
                            "confidence": final_confidence,
                            "flags": final_flags,
                            "reasoning": final_reasoning,
                        }, ensure_ascii=False),
                    }
                elif event_type == "error":
                    yield {
                        "event": "error",
                        "data": json.dumps({
                            "error": event.get("error", "Unknown error"),
                            "run_id": event.get("run_id"),
                        }, ensure_ascii=False),
                    }
                    return

            # Store the final assistant message
            if final_content:
                add_message(
                    gen_db, session_id, "assistant",
                    final_content,
                    mode=final_mode,
                    run_id=final_run_id,
                    reasoning_data=json.dumps({
                        "structured": final_structured,
                        "reasoning": final_reasoning,
                        "confidence": final_confidence,
                        "flags": final_flags,
                    }, ensure_ascii=False) if final_reasoning else None,
                )
                gen_db.commit()

        except Exception as e:
            logger.exception("Error in SSE event generator")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}, ensure_ascii=False),
            }
        finally:
            gen_db.close()

    return EventSourceResponse(event_generator())


@router.post("/sessions/{session_id}/resume")
def resume_paused_pipeline(
    session_id: str,
    req: ResumeRequest,
    db: Session = Depends(get_db),
):
    """Resume a paused pipeline after user responds to import request.

    The user sends import decisions: {law_key: "import" | "skip"}.
    If "import", the law should be imported first via /api/laws/import.
    Then call this endpoint to resume the pipeline from Step 6.
    """
    session = get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    def event_generator():
        from app.services.pipeline_service import resume_pipeline
        from app.database import SessionLocal

        gen_db = SessionLocal()
        try:
            final_content = ""
            final_mode = None
            final_run_id = req.run_id
            final_reasoning = None

            for event in resume_pipeline(req.run_id, req.decisions, gen_db):
                event_type = event.get("type", "unknown")

                if event_type == "token":
                    yield {
                        "event": "token",
                        "data": json.dumps({"text": event["text"]}, ensure_ascii=False),
                    }
                elif event_type == "step":
                    yield {
                        "event": "step",
                        "data": json.dumps(event, ensure_ascii=False),
                    }
                elif event_type == "done":
                    final_content = event.get("content", "")
                    final_mode = event.get("mode")
                    final_reasoning = event.get("reasoning")
                    final_structured = event.get("structured")
                    final_confidence = event.get("confidence")
                    final_flags = event.get("flags", [])

                    yield {
                        "event": "done",
                        "data": json.dumps({
                            "content": final_content,
                            "structured": final_structured,
                            "mode": final_mode,
                            "run_id": final_run_id,
                            "confidence": final_confidence,
                            "flags": final_flags,
                            "reasoning": final_reasoning,
                        }, ensure_ascii=False),
                    }
                elif event_type == "error":
                    yield {
                        "event": "error",
                        "data": json.dumps({
                            "error": event.get("error", "Unknown error"),
                            "run_id": final_run_id,
                        }, ensure_ascii=False),
                    }
                    return

            # Store the final assistant message
            if final_content:
                add_message(
                    gen_db, session_id, "assistant",
                    final_content,
                    mode=final_mode,
                    run_id=final_run_id,
                    reasoning_data=json.dumps({
                        "structured": final_structured,
                        "reasoning": final_reasoning,
                        "confidence": final_confidence,
                        "flags": final_flags,
                    }, ensure_ascii=False) if final_reasoning else None,
                )
                gen_db.commit()

        except Exception as e:
            logger.exception("Error in resume SSE generator")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}, ensure_ascii=False),
            }
        finally:
            gen_db.close()

    return EventSourceResponse(event_generator())


@router.delete("/sessions/{session_id}")
def delete_chat_session(session_id: str, db: Session = Depends(get_db)):
    """Delete a chat session and all its messages."""
    if not delete_session(db, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"message": "Session deleted"}
