from __future__ import annotations

from pydantic import BaseModel


class CreateSessionResponse(BaseModel):
    id: str
    title: str | None = None
    created_at: str
    last_active_at: str
    message_count: int = 0


class SessionSummary(BaseModel):
    id: str
    title: str | None = None
    last_active_at: str
    message_count: int


class MessageRequest(BaseModel):
    content: str


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    mode: str | None = None
    run_id: str | None = None
    reasoning_data: str | None = None
    created_at: str


class SessionDetailResponse(BaseModel):
    id: str
    title: str | None = None
    created_at: str
    last_active_at: str
    message_count: int
    messages: list[MessageResponse]


class ResumeRequest(BaseModel):
    run_id: str
    decisions: dict[str, str]  # law_key -> "import" | "skip"
