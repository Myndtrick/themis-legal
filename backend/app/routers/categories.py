from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/api/laws", tags=["library"])


@router.get("/library")
def get_library(db: Session = Depends(get_db)):
    """Return all data needed for the Legal Library page."""
    from app.services.category_service import get_library_data
    return get_library_data(db)


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
