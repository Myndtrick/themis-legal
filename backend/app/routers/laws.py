import difflib
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.law import Article, Law, LawVersion, StructuralElement
from app.models.category import LawMapping

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/laws", tags=["laws"])


class ImportRequest(BaseModel):
    ver_id: str
    import_history: bool = True


class ImportSuggestionRequest(BaseModel):
    mapping_id: int
    import_history: bool = False


# LawMapping.document_type stores English keys; advanced_search expects
# Romanian abbreviated keys or numeric codes from legislatie.just.ro.
_DOC_TYPE_TO_SEARCH_CODE = {
    "law": "1",
    "emergency_ordinance": "18",
    "government_ordinance": "13",
    "government_resolution": "2",
    "decree": "3",
    "constitution": "22",
    "regulation": "12",
    "directive": "113",
}


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


@router.get("/advanced-search")
def advanced_search_endpoint(
    keyword: str = "",
    doc_type: str = "",
    number: str = "",
    year: str = "",
    emitent: str = "",
    date_from: str = "",
    date_to: str = "",
    include_repealed: str = "only_in_force",
    db: Session = Depends(get_db),
):
    """Advanced search on legislatie.just.ro with structured filters."""
    from app.services.search_service import advanced_search

    if not any([keyword, doc_type, number, year, emitent, date_from, date_to]):
        raise HTTPException(status_code=400, detail="At least one search parameter is required")

    try:
        results = advanced_search(
            keyword=keyword,
            doc_type=doc_type,
            number=number,
            year=year,
            emitent=emitent,
            date_from=date_from,
            date_to=date_to,
            include_repealed=include_repealed,
        )
    except Exception as e:
        logger.error(f"Advanced search failed: {e}")
        raise HTTPException(status_code=502, detail=f"Search failed: {str(e)}")

    # Cross-reference with local DB to flag already-imported laws
    enriched = []
    for r in results:
        already_imported = False
        local_law_id = None

        # Primary: check LawVersion.ver_id
        existing_version = (
            db.query(LawVersion)
            .filter(LawVersion.ver_id == r.ver_id)
            .first()
        )
        if existing_version:
            already_imported = True
            local_law_id = existing_version.law_id
        else:
            # Secondary: check Law.source_url
            source_url = f"https://legislatie.just.ro/Public/DetaliiDocument/{r.ver_id}"
            existing_law = db.query(Law).filter(Law.source_url == source_url).first()
            if existing_law:
                already_imported = True
                local_law_id = existing_law.id

        enriched.append({
            **r.to_dict(),
            "already_imported": already_imported,
            "local_law_id": local_law_id,
        })

    return {"results": enriched, "total": len(enriched)}


@router.get("/filter-options")
def get_filter_options():
    """Return dropdown options (doc types + emitents) scraped from legislatie.just.ro."""
    from app.services.filter_options import get_filter_options
    return get_filter_options()


@router.get("/emitents")
def get_emitents(q: str = ""):
    """Autocomplete emitent (issuer) names."""
    from app.services.filter_options import search_emitents
    return {"emitents": search_emitents(q)}


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

    # Check if already imported (either this ver_id directly, or as a main page
    # whose history versions are already stored)
    existing = db.query(LawVersion).filter(LawVersion.ver_id == ver_id).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"This law is already imported as '{existing.law.title}'",
        )

    # Also check by source_url — the main page ver_id may differ from stored
    # version ver_ids, but the source_url will match.
    source_url = f"https://legislatie.just.ro/Public/DetaliiDocument/{ver_id}"
    existing_law = db.query(Law).filter(Law.source_url == source_url).first()
    if existing_law:
        raise HTTPException(
            status_code=409,
            detail=f"This law is already imported as '{existing_law.title}'",
        )

    try:
        result = do_import(db, ver_id, import_history=req.import_history)

        # Look up suggested category from law_mappings.
        # Match priority:
        #   1. Exact (document_type + law_number + law_year)
        #   2. Partial (law_number + law_year, ignore document_type)
        #   3. Partial (document_type + law_number, ignore year)
        #   4. law_number only (single candidate)
        law_number = result.get("law_number")
        law_year = result.get("law_year")
        doc_type = result.get("document_type")
        mapping = None
        if law_number and law_number != "unknown":
            candidates = db.query(LawMapping).filter(
                LawMapping.law_number == law_number
            ).all()
            if len(candidates) == 1:
                mapping = candidates[0]
            elif candidates:
                # Try exact match: document_type + law_number + law_year
                if doc_type and law_year:
                    for c in candidates:
                        if c.document_type == doc_type and c.law_year == law_year:
                            mapping = c
                            break
                # Fallback: law_number + law_year (ignore document_type)
                if not mapping and law_year:
                    for c in candidates:
                        if c.law_year == law_year:
                            mapping = c
                            break
                # Fallback: document_type + law_number (ignore year)
                if not mapping and doc_type:
                    matches = [c for c in candidates if c.document_type == doc_type]
                    if len(matches) == 1:
                        mapping = matches[0]
        if mapping:
            result["suggested_category_id"] = mapping.category_id

        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to import ver_id={ver_id}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


@router.post("/import-suggestion")
def import_suggestion(req: ImportSuggestionRequest, db: Session = Depends(get_db)):
    """Import a law from a suggestion (LawMapping) by searching legislatie.just.ro."""
    from app.services.search_service import advanced_search
    from app.services.leropa_service import import_law as do_import

    # 1. Look up mapping
    mapping = db.query(LawMapping).filter(LawMapping.id == req.mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    # 2. Validate law_number exists
    if not mapping.law_number:
        raise HTTPException(
            status_code=400,
            detail="This suggestion cannot be auto-imported (no law number)",
        )

    # 3. Check if already imported by law_number (+ document_type/year if available)
    existing_query = db.query(Law).filter(Law.law_number == mapping.law_number)
    if mapping.document_type:
        existing_query = existing_query.filter(Law.document_type == mapping.document_type)
    if mapping.law_year:
        existing_query = existing_query.filter(Law.law_year == mapping.law_year)
    existing = existing_query.first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"This law is already imported as '{existing.title}'",
        )

    # 4. Search legislatie.just.ro
    doc_type_code = _DOC_TYPE_TO_SEARCH_CODE.get(mapping.document_type or "", "")
    year_str = str(mapping.law_year) if mapping.law_year else ""

    try:
        results = advanced_search(
            doc_type=doc_type_code,
            number=mapping.law_number,
            year=year_str,
        )
    except Exception as e:
        logger.error(f"Search failed for suggestion {req.mapping_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Search failed: {str(e)}")

    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"No results found on legislatie.just.ro for {mapping.title}",
        )

    # 5. Pick best match — first result (search is already filtered by type+number+year)
    best = results[0]
    ver_id = best.ver_id

    # 6. Check if this ver_id is already imported
    existing_ver = db.query(LawVersion).filter(LawVersion.ver_id == ver_id).first()
    if existing_ver:
        raise HTTPException(
            status_code=409,
            detail=f"This law is already imported as '{existing_ver.law.title}'",
        )

    # 7. Import
    try:
        result = do_import(db, ver_id, import_history=req.import_history)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to import suggestion {req.mapping_id} (ver_id={ver_id})")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")

    # 8. Auto-assign category
    law = db.query(Law).filter(Law.id == result["law_id"]).first()
    if law:
        law.category_id = mapping.category_id
        db.commit()

    return {
        "law_id": result["law_id"],
        "title": result.get("title", mapping.title),
    }


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
            "status": law.status,
            "status_override": law.status_override,
        }
        for law in laws
    ]


@router.get("/{law_id}")
def get_law(law_id: int, db: Session = Depends(get_db)):
    """Get a law with all its versions."""
    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    category_info = None
    if law.category_id and law.category:
        cat = law.category
        category_info = {
            "id": cat.id,
            "slug": cat.slug,
            "name_ro": cat.name_ro,
            "name_en": cat.name_en,
            "group_name_ro": cat.group.name_ro,
            "group_name_en": cat.group.name_en,
            "group_color_hex": cat.group.color_hex,
        }

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
        "status": law.status,
        "status_override": law.status_override,
        "category": category_info,
        "category_confidence": law.category_confidence,
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
                children = build_element_tree(el.id)
                # Skip empty structural elements (no articles, no non-empty children)
                if not el_articles and not children:
                    continue
                result.append({
                    "id": el.id,
                    "type": el.element_type,
                    "number": el.number,
                    "title": el.title,
                    "description": el.description,
                    "children": children,
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


@router.post("/{law_id}/check-updates")
def check_law_updates(law_id: int, db: Session = Depends(get_db)):
    """Check a single law for new versions on legislatie.just.ro."""
    from app.services.fetcher import fetch_document
    from app.services.leropa_service import fetch_and_store_version
    import app.services.leropa_service as _ls

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    current = (
        db.query(LawVersion)
        .filter(LawVersion.law_id == law.id, LawVersion.is_current == True)
        .first()
    )
    if not current:
        raise HTTPException(status_code=400, detail="No current version found for this law")

    try:
        result = fetch_document(current.ver_id, use_cache=False)
        doc = result["document"]

        next_ver = doc.get("next_ver")
        if next_ver:
            existing = db.query(LawVersion).filter(LawVersion.ver_id == next_ver).first()
            if existing:
                return {"has_update": False, "message": "This law is up to date."}

            _ls._stored_article_ids = set()
            _, new_version = fetch_and_store_version(db, next_ver, law=law)

        else:
            history = doc.get("history", [])
            stored_ver_ids = {
                v.ver_id
                for v in db.query(LawVersion).filter(LawVersion.law_id == law.id).all()
            }
            new_versions = [h for h in history if h["ver_id"] not in stored_ver_ids]

            if not new_versions:
                return {"has_update": False, "message": "This law is up to date."}

            for entry in new_versions:
                _ls._stored_article_ids = set()
                fetch_and_store_version(db, entry["ver_id"], law=law)

        # Update is_current flags
        all_versions = (
            db.query(LawVersion).filter(LawVersion.law_id == law.id).all()
        )
        dated = [(v, v.date_in_force) for v in all_versions if v.date_in_force]
        if dated:
            dated.sort(key=lambda x: x[1], reverse=True)
            for v in all_versions:
                v.is_current = False
            dated[0][0].is_current = True

        # Re-evaluate law status if not manually overridden
        if not law.status_override:
            from app.services.leropa_service import detect_law_status
            law.status = detect_law_status(db, law)

        db.commit()
        return {"has_update": True, "message": "New version found and imported!"}

    except Exception as e:
        logger.exception(f"Error checking updates for law {law_id}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Update check failed: {str(e)}")


@router.delete("/{law_id}")
def delete_law(law_id: int, db: Session = Depends(get_db)):
    """Delete a law and all its versions."""
    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    title = law.title
    version_count = len(law.versions)

    # Clean up ChromaDB index
    try:
        from app.services.chroma_service import remove_law_articles

        remove_law_articles(db, law_id)
    except Exception as e:
        logger.warning(f"ChromaDB cleanup failed (non-fatal): {e}")

    db.delete(law)
    db.commit()
    return {
        "message": f"Deleted '{title}' with {version_count} version(s)",
    }


@router.delete("/{law_id}/versions/old")
def delete_old_versions(law_id: int, db: Session = Depends(get_db)):
    """Delete all non-current versions of a law, keeping only the current one."""
    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    old_versions = [v for v in law.versions if not v.is_current]
    if not old_versions:
        return {"message": "No old versions to delete", "deleted_count": 0}

    for version in old_versions:
        db.delete(version)
    db.commit()

    return {
        "message": f"Deleted {len(old_versions)} old version(s) of '{law.title}'",
        "deleted_count": len(old_versions),
    }


class StatusUpdateRequest(BaseModel):
    status: str
    override: bool = True


@router.patch("/{law_id}/status")
def update_law_status(law_id: int, req: StatusUpdateRequest, db: Session = Depends(get_db)):
    """Update the status of a law (admin override)."""
    from app.services.leropa_service import detect_law_status

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    valid_statuses = {"in_force", "repealed", "partially_repealed", "superseded", "unknown"}
    if req.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    if req.override:
        law.status = req.status
        law.status_override = True
    else:
        # Reset to auto-detection
        law.status_override = False
        law.status = detect_law_status(db, law)

    db.commit()
    return {"status": law.status, "status_override": law.status_override}


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
