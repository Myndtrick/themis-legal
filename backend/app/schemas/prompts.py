from __future__ import annotations

from pydantic import BaseModel


class PromptSummary(BaseModel):
    prompt_id: str
    description: str
    version_number: int
    status: str
    modified_at: str | None = None


class PromptDetail(BaseModel):
    prompt_id: str
    description: str
    version_number: int
    status: str
    prompt_text: str
    created_at: str
    created_by: str
    modification_note: str | None = None


class PromptVersionSummary(BaseModel):
    version_number: int
    status: str
    created_at: str
    created_by: str
    modification_note: str | None = None


class ProposeChangeRequest(BaseModel):
    proposed_text: str
    modification_note: str
    source: str = "direct_edit"  # "direct_edit" | "chat_modification"


class PromptDiff(BaseModel):
    prompt_id: str
    current_version: int
    proposed_version: int
    current_text: str
    proposed_text: str
    modification_note: str
    pending_version_id: int
