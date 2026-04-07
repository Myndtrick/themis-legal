"""User-editable suggestion list endpoints (LawMapping CRUD).

Surface for the "Add law" modal on the library page and the
edit/delete affordances on user-managed suggestions. System-managed
mappings (`source='system'`) are protected: editing them forks them
to user, deleting them is forbidden.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models.category import Category, CategoryGroup, LawMapping
from app.models.law import Law
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


def _serialize_mapping(m: LawMapping, is_imported: bool) -> dict:
    cat = m.category
    group = cat.group if cat else None
    return {
        "id": m.id,
        "title": m.title,
        "law_number": m.law_number,
        "law_year": m.law_year,
        "document_type": m.document_type,
        "celex_number": m.celex_number,
        "source_url": m.source_url,
        "source_ver_id": m.source_ver_id,
        "category_id": m.category_id,
        "category_name": cat.name_en if cat else None,
        "category_slug": cat.slug if cat else None,
        "group_slug": group.slug if group else None,
        "group_name": group.name_en if group else None,
        "group_color": group.color_hex if group else None,
        "source": m.source,
        "is_imported": is_imported,
    }


@router.get("")
def list_mappings(
    group_slug: str | None = None,
    category_id: int | None = None,
    source: Literal["system", "user", "all"] = "all",
    pinned: Literal["true", "false", "all"] = "all",
    q: str | None = None,
    db: Session = Depends(get_db),
):
    query = (
        db.query(LawMapping)
        .options(joinedload(LawMapping.category).joinedload(Category.group))
    )
    if category_id is not None:
        query = query.filter(LawMapping.category_id == category_id)
    if source != "all":
        query = query.filter(LawMapping.source == source)
    if pinned == "true":
        query = query.filter(
            (LawMapping.source_ver_id.isnot(None)) | (LawMapping.celex_number.isnot(None))
        )
    elif pinned == "false":
        query = query.filter(
            LawMapping.source_ver_id.is_(None), LawMapping.celex_number.is_(None)
        )
    if q:
        like = f"%{q}%"
        query = query.filter(LawMapping.title.ilike(like))

    mappings = query.all()
    if group_slug:
        mappings = [
            m for m in mappings
            if m.category and m.category.group and m.category.group.slug == group_slug
        ]

    # Pre-compute imported lookup in one pass.
    ro_keys = {(m.law_number, m.law_year, m.document_type) for m in mappings if m.law_number}
    eu_keys = {m.celex_number for m in mappings if m.celex_number}
    imported_ro: set[tuple] = set()
    imported_eu: set[str] = set()
    if ro_keys:
        rows = db.query(Law.law_number, Law.law_year, Law.document_type).filter(
            Law.law_number.in_({n for n, _, _ in ro_keys})
        ).all()
        imported_ro = {(r[0], r[1], r[2]) for r in rows}
    if eu_keys:
        rows = db.query(Law.celex_number).filter(Law.celex_number.in_(eu_keys)).all()
        imported_eu = {r[0] for r in rows}

    def is_imported(m: LawMapping) -> bool:
        if m.celex_number and m.celex_number in imported_eu:
            return True
        if m.law_number and (m.law_number, m.law_year, m.document_type) in imported_ro:
            return True
        return False

    return [_serialize_mapping(m, is_imported(m)) for m in mappings]


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
