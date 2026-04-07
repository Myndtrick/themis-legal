"""User-editable suggestion list endpoints (LawMapping CRUD).

Surface for the "Add law" modal on the library page and the
edit/delete affordances on user-managed suggestions. System-managed
mappings (`source='system'`) are protected: editing them forks them
to user, deleting them is forbidden.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.category import LawMapping
from app.services.suggestion_service import (
    create_user_mapping_from_url,
    fork_to_user_if_needed,
)

router = APIRouter(
    prefix="/api/law-mappings",
    tags=["law-mappings"],
    dependencies=[Depends(get_current_user)],
)


class CreateMappingRequest(BaseModel):
    url: str
    category_id: int
    title: str | None = None


class UpdateMappingRequest(BaseModel):
    title: str | None = None
    category_id: int | None = None
    law_number: str | None = None
    law_year: int | None = None
    document_type: str | None = None


class MappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    category_id: int
    source: str
    source_url: str | None = None
    source_ver_id: str | None = None
    celex_number: str | None = None
    law_number: str | None = None
    law_year: int | None = None
    document_type: str | None = None


@router.post("", response_model=MappingResponse)
def create_mapping(
    req: CreateMappingRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    existing = (
        db.query(LawMapping)
        .filter(LawMapping.source_url == req.url)
        .first()
    )
    try:
        mapping = create_user_mapping_from_url(
            db,
            url=req.url,
            category_id=req.category_id,
            title=req.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    response.status_code = 200 if existing is not None else 201
    return mapping


@router.put("/{mapping_id}", response_model=MappingResponse)
def update_mapping(
    mapping_id: int,
    req: UpdateMappingRequest,
    db: Session = Depends(get_db),
):
    mapping = (
        db.query(LawMapping).filter(LawMapping.id == mapping_id).first()
    )
    if mapping is None:
        raise HTTPException(status_code=404, detail="Mapping not found")

    fork_to_user_if_needed(mapping)

    if req.title is not None:
        mapping.title = req.title
    if req.category_id is not None:
        mapping.category_id = req.category_id
    if req.law_number is not None:
        mapping.law_number = req.law_number
    if req.law_year is not None:
        mapping.law_year = req.law_year
    if req.document_type is not None:
        mapping.document_type = req.document_type

    db.commit()
    db.refresh(mapping)
    return mapping


@router.delete("/{mapping_id}", status_code=204)
def delete_mapping(mapping_id: int, db: Session = Depends(get_db)):
    mapping = (
        db.query(LawMapping).filter(LawMapping.id == mapping_id).first()
    )
    if mapping is None:
        raise HTTPException(status_code=404, detail="Mapping not found")
    if mapping.source != "user":
        raise HTTPException(
            status_code=403,
            detail="Cannot delete a system-managed mapping",
        )
    db.delete(mapping)
    db.commit()
    return Response(status_code=204)
