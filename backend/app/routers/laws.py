import difflib
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.law import Article, Law, LawVersion, StructuralElement

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/laws", tags=["laws"])


class ImportRequest(BaseModel):
    ver_id: str
    import_history: bool = True


@router.get("/search")
def search_external(q: str):
    """Search legislatie.just.ro for laws matching a query."""
    from app.services.search_service import search_laws

    if len(q.strip()) < 2:
        return []

    try:
        results = search_laws(q.strip(), max_results=10)
        return [r.to_dict() for r in results]
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=502, detail=f"Search failed: {str(e)}")


@router.post("/import")
def import_law(req: ImportRequest, db: Session = Depends(get_db)):
    """Import a law from legislatie.just.ro by ver_id.

    The ver_id can be:
    - A numeric ID like "267625"
    - A full URL like "https://legislatie.just.ro/Public/DetaliiDocument/267625"
    """
    from app.services.leropa_service import import_law as do_import

    # Extract ver_id from URL if needed
    ver_id = req.ver_id.strip()
    url_match = re.search(r"DetaliiDocument/(\d+)", ver_id)
    if url_match:
        ver_id = url_match.group(1)

    if not ver_id.isdigit():
        raise HTTPException(
            status_code=400,
            detail="Invalid ver_id. Provide a numeric ID or a legislatie.just.ro URL.",
        )

    # Check if already imported
    existing = db.query(LawVersion).filter(LawVersion.ver_id == ver_id).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"This version is already imported as part of '{existing.law.title}'",
        )

    try:
        result = do_import(db, ver_id, import_history=req.import_history)
        return result
    except Exception as e:
        logger.exception(f"Failed to import ver_id={ver_id}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


@router.get("/")
def list_laws(db: Session = Depends(get_db)):
    """List all stored laws."""
    laws = db.query(Law).order_by(Law.law_year.desc(), Law.law_number).all()
    return [
        {
            "id": law.id,
            "title": law.title,
            "law_number": law.law_number,
            "law_year": law.law_year,
            "document_type": law.document_type,
            "description": law.description,
            "version_count": len(law.versions),
            "current_version": next(
                (
                    {
                        "id": v.id,
                        "ver_id": v.ver_id,
                        "date_in_force": str(v.date_in_force) if v.date_in_force else None,
                        "state": v.state,
                    }
                    for v in law.versions
                    if v.is_current
                ),
                None,
            ),
        }
        for law in laws
    ]


@router.get("/{law_id}")
def get_law(law_id: int, db: Session = Depends(get_db)):
    """Get a law with all its versions."""
    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")
    return {
        "id": law.id,
        "title": law.title,
        "law_number": law.law_number,
        "law_year": law.law_year,
        "document_type": law.document_type,
        "description": law.description,
        "keywords": law.keywords,
        "issuer": law.issuer,
        "source_url": law.source_url,
        "versions": [
            {
                "id": v.id,
                "ver_id": v.ver_id,
                "date_in_force": str(v.date_in_force) if v.date_in_force else None,
                "date_imported": str(v.date_imported),
                "state": v.state,
                "is_current": v.is_current,
            }
            for v in sorted(law.versions, key=lambda v: v.date_in_force or "", reverse=True)
        ],
    }


@router.get("/{law_id}/versions/{version_id}")
def get_law_version(law_id: int, version_id: int, db: Session = Depends(get_db)):
    """Get a specific version of a law with full structure."""
    version = (
        db.query(LawVersion)
        .filter(LawVersion.id == version_id, LawVersion.law_id == law_id)
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    law = version.law

    # Build structural hierarchy
    elements = (
        db.query(StructuralElement)
        .filter(StructuralElement.law_version_id == version_id)
        .order_by(StructuralElement.order_index)
        .all()
    )

    articles = (
        db.query(Article)
        .filter(Article.law_version_id == version_id)
        .options(joinedload(Article.paragraphs), joinedload(Article.amendment_notes))
        .order_by(Article.order_index)
        .all()
    )

    def build_element_tree(parent_id=None):
        result = []
        for el in elements:
            if el.parent_id == parent_id:
                el_articles = [a for a in articles if a.structural_element_id == el.id]
                result.append({
                    "id": el.id,
                    "type": el.element_type,
                    "number": el.number,
                    "title": el.title,
                    "description": el.description,
                    "children": build_element_tree(el.id),
                    "articles": [serialize_article(a, law) for a in el_articles],
                })
        return result

    # Articles not attached to any structural element
    orphan_articles = [a for a in articles if a.structural_element_id is None]

    return {
        "id": version.id,
        "ver_id": version.ver_id,
        "date_in_force": str(version.date_in_force) if version.date_in_force else None,
        "state": version.state,
        "is_current": version.is_current,
        "law": {
            "id": law.id,
            "title": law.title,
            "law_number": law.law_number,
            "law_year": law.law_year,
        },
        "structure": build_element_tree(),
        "articles": [serialize_article(a, law) for a in orphan_articles],
    }


def serialize_article(article: Article, law: Law) -> dict:
    version = article.law_version
    citation = f"Art. {article.article_number}, Legea {law.law_number}/{law.law_year}"
    if version.date_in_force:
        citation += f", versiunea în vigoare din {version.date_in_force}"

    return {
        "id": article.id,
        "article_number": article.article_number,
        "label": article.label,
        "full_text": article.full_text,
        "citation": citation,
        "paragraphs": [
            {
                "id": p.id,
                "paragraph_number": p.paragraph_number,
                "label": p.label,
                "text": p.text,
                "subparagraphs": [
                    {"id": sp.id, "label": sp.label, "text": sp.text}
                    for sp in sorted(p.subparagraphs, key=lambda x: x.order_index)
                ],
            }
            for p in sorted(article.paragraphs, key=lambda x: x.order_index)
        ],
        "amendment_notes": [
            {
                "id": n.id,
                "text": n.text,
                "date": n.date,
                "subject": n.subject,
                "original_text": n.original_text,
                "replacement_text": n.replacement_text,
            }
            for n in article.amendment_notes
        ],
    }


@router.get("/{law_id}/diff")
def diff_versions(
    law_id: int,
    version_a: int,
    version_b: int,
    db: Session = Depends(get_db),
):
    """Compare two versions of a law, article by article.

    version_a and version_b are LawVersion IDs.
    Returns a list of article-level changes.
    """
    ver_a = (
        db.query(LawVersion)
        .filter(LawVersion.id == version_a, LawVersion.law_id == law_id)
        .first()
    )
    ver_b = (
        db.query(LawVersion)
        .filter(LawVersion.id == version_b, LawVersion.law_id == law_id)
        .first()
    )
    if not ver_a or not ver_b:
        raise HTTPException(status_code=404, detail="Version not found")

    articles_a = (
        db.query(Article)
        .filter(Article.law_version_id == version_a)
        .order_by(Article.order_index)
        .all()
    )
    articles_b = (
        db.query(Article)
        .filter(Article.law_version_id == version_b)
        .order_by(Article.order_index)
        .all()
    )

    # Index by article_number
    map_a = {a.article_number: a for a in articles_a}
    map_b = {b.article_number: b for b in articles_b}

    all_numbers = sorted(
        set(map_a.keys()) | set(map_b.keys()),
        key=lambda x: (len(x), x),
    )

    changes = []
    for num in all_numbers:
        art_a = map_a.get(num)
        art_b = map_b.get(num)

        if art_a and not art_b:
            changes.append({
                "article_number": num,
                "change_type": "removed",
                "text_a": art_a.full_text,
                "text_b": None,
                "diff_html": None,
            })
        elif art_b and not art_a:
            changes.append({
                "article_number": num,
                "change_type": "added",
                "text_a": None,
                "text_b": art_b.full_text,
                "diff_html": None,
            })
        elif art_a and art_b:
            if art_a.full_text.strip() == art_b.full_text.strip():
                changes.append({
                    "article_number": num,
                    "change_type": "unchanged",
                    "text_a": art_a.full_text,
                    "text_b": art_b.full_text,
                    "diff_html": None,
                })
            else:
                # Generate word-level diff
                diff_html = _word_diff(art_a.full_text, art_b.full_text)
                changes.append({
                    "article_number": num,
                    "change_type": "modified",
                    "text_a": art_a.full_text,
                    "text_b": art_b.full_text,
                    "diff_html": diff_html,
                })

    summary = {
        "added": sum(1 for c in changes if c["change_type"] == "added"),
        "removed": sum(1 for c in changes if c["change_type"] == "removed"),
        "modified": sum(1 for c in changes if c["change_type"] == "modified"),
        "unchanged": sum(1 for c in changes if c["change_type"] == "unchanged"),
    }

    return {
        "law_id": law_id,
        "version_a": {
            "id": ver_a.id,
            "ver_id": ver_a.ver_id,
            "date_in_force": str(ver_a.date_in_force) if ver_a.date_in_force else None,
        },
        "version_b": {
            "id": ver_b.id,
            "ver_id": ver_b.ver_id,
            "date_in_force": str(ver_b.date_in_force) if ver_b.date_in_force else None,
        },
        "summary": summary,
        "changes": changes,
    }


def _word_diff(text_a: str, text_b: str) -> str:
    """Generate a word-level diff as HTML with <ins> and <del> tags."""
    words_a = text_a.split()
    words_b = text_b.split()
    matcher = difflib.SequenceMatcher(None, words_a, words_b)

    parts = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            parts.append(" ".join(words_a[i1:i2]))
        elif op == "delete":
            parts.append(f'<del>{" ".join(words_a[i1:i2])}</del>')
        elif op == "insert":
            parts.append(f'<ins>{" ".join(words_b[j1:j2])}</ins>')
        elif op == "replace":
            parts.append(f'<del>{" ".join(words_a[i1:i2])}</del>')
            parts.append(f'<ins>{" ".join(words_b[j1:j2])}</ins>')
    return " ".join(parts)
