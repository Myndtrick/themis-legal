from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.category import CategoryGroup, Category
from app.models.law import Law

router = APIRouter(prefix="/api/settings/categories", tags=["settings"], dependencies=[Depends(get_current_user)])


@router.get("/")
def list_categories(db: Session = Depends(get_db)):
    """List all categories with law counts for the settings page."""
    groups = db.query(CategoryGroup).order_by(CategoryGroup.sort_order).all()
    result = []
    for g in groups:
        for c in sorted(g.categories, key=lambda x: x.sort_order):
            count = db.query(Law).filter(Law.category_id == c.id).count()
            result.append({
                "id": c.id, "slug": c.slug, "name_ro": c.name_ro,
                "name_en": c.name_en, "description": c.description,
                "group_name": g.name_en, "group_slug": g.slug,
                "group_color": g.color_hex, "law_count": count,
            })
    return result


class NewSubcategoryRequest(BaseModel):
    group_slug: str
    name_ro: str
    name_en: str
    description: str = ""


@router.post("/subcategory")
def add_subcategory(req: NewSubcategoryRequest, db: Session = Depends(get_db)):
    """Add a new subcategory to an existing group."""
    group = db.query(CategoryGroup).filter(CategoryGroup.slug == req.group_slug).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    max_sort = max((c.sort_order for c in group.categories), default=0)
    slug = f"{req.group_slug}.{req.name_en.lower().replace(' ', '_')}"

    existing = db.query(Category).filter(Category.slug == slug).first()
    if existing:
        raise HTTPException(status_code=409, detail="Subcategory already exists")

    cat = Category(
        group_id=group.id, slug=slug, name_ro=req.name_ro,
        name_en=req.name_en, description=req.description,
        sort_order=max_sort + 1,
    )
    db.add(cat)
    db.commit()
    return {"id": cat.id, "slug": cat.slug}
