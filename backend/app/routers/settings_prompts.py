from __future__ import annotations

import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.prompt import PromptVersion
from app.schemas.prompts import (
    PromptDetail,
    PromptDiff,
    PromptSummary,
    PromptVersionSummary,
    ProposeChangeRequest,
)
from app.services.prompt_service import PROMPT_MANIFEST, get_all_active_prompts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings/prompts", tags=["Settings — Prompts"], dependencies=[Depends(get_current_user)])


@router.get("/", response_model=list[PromptSummary])
def list_prompts(db: Session = Depends(get_db)):
    """List all prompts with their current active version."""
    return get_all_active_prompts(db)


@router.get("/{prompt_id}", response_model=PromptDetail)
def get_prompt(prompt_id: str, db: Session = Depends(get_db)):
    """Get the current active prompt text."""
    version = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.status == "ACTIVE",
        )
        .order_by(PromptVersion.version_number.desc())
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_id} not found")

    desc = PROMPT_MANIFEST.get(prompt_id, {}).get("desc", prompt_id)
    return PromptDetail(
        prompt_id=version.prompt_id,
        description=desc,
        version_number=version.version_number,
        status=version.status,
        prompt_text=version.prompt_text,
        created_at=version.created_at.isoformat(),
        created_by=version.created_by,
        modification_note=version.modification_note,
    )


@router.get("/{prompt_id}/versions", response_model=list[PromptVersionSummary])
def get_version_history(prompt_id: str, db: Session = Depends(get_db)):
    """Get full version history for a prompt."""
    versions = (
        db.query(PromptVersion)
        .filter(PromptVersion.prompt_id == prompt_id)
        .order_by(PromptVersion.version_number.desc())
        .all()
    )
    if not versions:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_id} not found")

    return [
        PromptVersionSummary(
            version_number=v.version_number,
            status=v.status,
            created_at=v.created_at.isoformat(),
            created_by=v.created_by,
            modification_note=v.modification_note,
        )
        for v in versions
    ]


@router.get("/{prompt_id}/versions/{version_number}", response_model=PromptDetail)
def get_specific_version(
    prompt_id: str, version_number: int, db: Session = Depends(get_db)
):
    """Get the text of a specific prompt version."""
    version = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.version_number == version_number,
        )
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    desc = PROMPT_MANIFEST.get(prompt_id, {}).get("desc", prompt_id)
    return PromptDetail(
        prompt_id=version.prompt_id,
        description=desc,
        version_number=version.version_number,
        status=version.status,
        prompt_text=version.prompt_text,
        created_at=version.created_at.isoformat(),
        created_by=version.created_by,
        modification_note=version.modification_note,
    )


@router.post("/{prompt_id}/propose", response_model=PromptDiff)
def propose_change(
    prompt_id: str, req: ProposeChangeRequest, db: Session = Depends(get_db)
):
    """Propose a change to a prompt. Creates a PENDING version.

    No change takes effect without explicit approval.
    """
    # Get the current active version
    current = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.status == "ACTIVE",
        )
        .order_by(PromptVersion.version_number.desc())
        .first()
    )
    if not current:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_id} not found")

    # Check for existing pending version
    existing_pending = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.status == "PENDING",
        )
        .first()
    )
    if existing_pending:
        # Remove old pending version
        db.delete(existing_pending)
        db.flush()

    # Create new pending version
    new_version = PromptVersion(
        prompt_id=prompt_id,
        version_number=current.version_number + 1,
        prompt_text=req.proposed_text,
        status="PENDING",
        created_by=req.source,
        modification_note=req.modification_note,
    )
    db.add(new_version)
    db.commit()
    db.refresh(new_version)

    return PromptDiff(
        prompt_id=prompt_id,
        current_version=current.version_number,
        proposed_version=new_version.version_number,
        current_text=current.prompt_text,
        proposed_text=new_version.prompt_text,
        modification_note=req.modification_note,
        pending_version_id=new_version.id,
    )


@router.post("/{prompt_id}/approve/{version_number}")
def approve_change(
    prompt_id: str, version_number: int, db: Session = Depends(get_db)
):
    """Approve a pending prompt change. Makes it the new ACTIVE version."""
    pending = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.version_number == version_number,
            PromptVersion.status == "PENDING",
        )
        .first()
    )
    if not pending:
        raise HTTPException(status_code=404, detail="Pending version not found")

    # Deactivate all current active versions
    active_versions = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.status == "ACTIVE",
        )
        .all()
    )
    for v in active_versions:
        v.status = "INACTIVE"

    # Activate the pending version
    pending.status = "ACTIVE"
    pending.approved_at = datetime.datetime.utcnow()
    pending.approved_by = "user"
    db.commit()

    return {
        "prompt_id": prompt_id,
        "new_active_version": version_number,
        "status": "approved",
    }


@router.post("/{prompt_id}/discard/{version_number}")
def discard_change(
    prompt_id: str, version_number: int, db: Session = Depends(get_db)
):
    """Discard a pending prompt change."""
    pending = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.version_number == version_number,
            PromptVersion.status == "PENDING",
        )
        .first()
    )
    if not pending:
        raise HTTPException(status_code=404, detail="Pending version not found")

    db.delete(pending)
    db.commit()

    return {"prompt_id": prompt_id, "discarded_version": version_number, "status": "discarded"}


@router.post("/{prompt_id}/restore/{version_number}")
def restore_version(
    prompt_id: str, version_number: int, db: Session = Depends(get_db)
):
    """Restore an old version as a new PENDING version (goes through approval).

    This does NOT delete any version — it creates a new version with the old text.
    """
    old_version = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.version_number == version_number,
        )
        .first()
    )
    if not old_version:
        raise HTTPException(status_code=404, detail="Version not found")

    # Get the current highest version number
    max_version = (
        db.query(PromptVersion.version_number)
        .filter(PromptVersion.prompt_id == prompt_id)
        .order_by(PromptVersion.version_number.desc())
        .first()
    )
    next_version = (max_version[0] + 1) if max_version else 1

    # Remove any existing pending
    existing_pending = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.status == "PENDING",
        )
        .first()
    )
    if existing_pending:
        db.delete(existing_pending)
        db.flush()

    # Create a new pending version with the old text
    restored = PromptVersion(
        prompt_id=prompt_id,
        version_number=next_version,
        prompt_text=old_version.prompt_text,
        status="PENDING",
        created_by="restore",
        modification_note=f"Restored from v{version_number}",
    )
    db.add(restored)
    db.commit()
    db.refresh(restored)

    current = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.status == "ACTIVE",
        )
        .order_by(PromptVersion.version_number.desc())
        .first()
    )

    return PromptDiff(
        prompt_id=prompt_id,
        current_version=current.version_number if current else 0,
        proposed_version=next_version,
        current_text=current.prompt_text if current else "",
        proposed_text=old_version.prompt_text,
        modification_note=f"Restored from v{version_number}",
        pending_version_id=restored.id,
    )
