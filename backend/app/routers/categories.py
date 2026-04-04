from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter(prefix="/api/laws", tags=["library"], dependencies=[Depends(get_current_user)])


@router.get("/library")
def get_library(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all data needed for the Legal Library page."""
    from app.services.category_service import get_library_data
    return get_library_data(db, user_id=current_user.id)


class CategoryAssignment(BaseModel):
    category_id: int


@router.patch("/{law_id}/category")
def assign_law_category(law_id: int, req: CategoryAssignment, db: Session = Depends(get_db)):
    """Assign a category to a law."""
    from app.services.category_service import assign_category
    try:
        return assign_category(db, law_id, req.category_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/local-search")
def search_local(q: str = "", db: Session = Depends(get_db)):
    """Search imported laws by title or number."""
    if len(q.strip()) < 2:
        return {"results": []}
    from app.services.category_service import local_search
    return {"results": local_search(db, q.strip())}


@router.get("/favorites")
def get_favorites(
    db: Session = Depends(get_db),
    current_user: "User" = Depends(get_current_user),
):
    """Return list of favorited law IDs for the current user."""
    from app.models.favorite import LawFavorite
    rows = db.query(LawFavorite.law_id).filter(
        LawFavorite.user_id == current_user.id
    ).all()
    return {"law_ids": [r[0] for r in rows]}


@router.post("/{law_id}/favorite")
def add_favorite(
    law_id: int,
    db: Session = Depends(get_db),
    current_user: "User" = Depends(get_current_user),
):
    """Add a law to the user's favorites. Idempotent."""
    from app.models.favorite import LawFavorite
    from app.models.law import Law

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    existing = db.query(LawFavorite).filter(
        LawFavorite.user_id == current_user.id,
        LawFavorite.law_id == law_id,
    ).first()
    if not existing:
        db.add(LawFavorite(user_id=current_user.id, law_id=law_id))
        db.commit()
    return {"ok": True}


@router.delete("/{law_id}/favorite")
def remove_favorite(
    law_id: int,
    db: Session = Depends(get_db),
    current_user: "User" = Depends(get_current_user),
):
    """Remove a law from the user's favorites. Idempotent."""
    from app.models.favorite import LawFavorite

    deleted = db.query(LawFavorite).filter(
        LawFavorite.user_id == current_user.id,
        LawFavorite.law_id == law_id,
    ).delete()
    if deleted:
        db.commit()
    return {"ok": True}
