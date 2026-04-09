import datetime
import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from collections import defaultdict

from sqlalchemy.orm import Session, subqueryload

from app.auth import get_current_user
from app.database import get_db
from app.errors import NoLawNumberError, DuplicateImportError, SearchFailedError, ImportFailedError
from app.models.law import AmendmentNote, Annex, Article, KnownVersion, Law, LawVersion, Paragraph, StructuralElement, Subparagraph
from app.models.category import LawMapping
from app.models.user import User
from app.database import SessionLocal
from app.services.version_discovery import _recalculate_current_version

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/laws", tags=["laws"], dependencies=[Depends(get_current_user)])


class ImportRequest(BaseModel):
    ver_id: str
    import_history: bool = True


class ImportSuggestionRequest(BaseModel):
    mapping_id: int
    import_history: bool = False


class ImportStreamRequest(BaseModel):
    import_history: bool = False
    category_id: int | None = None


class EUImportRequest(BaseModel):
    celex_number: str
    import_history: bool = True


class LawCheckLogRowOut(BaseModel):
    id: int
    checked_at: str
    user_email: str | None
    new_versions: int
    status: str
    error_message: str | None


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
def search_laws_endpoint(q: str, source: str | None = None, db: Session = Depends(get_db)):
    """Search laws from external sources. source: 'ro', 'eu', or None (both)."""
    results = []

    if source != "eu":
        from app.services.search_service import search_laws
        ro_results = search_laws(q)
        for r in ro_results:
            d = r.to_dict()
            d["source"] = "ro"
            results.append(d)

    if source != "ro":
        from app.services.eu_cellar_service import search_eu_legislation
        eu_results = search_eu_legislation(keyword=q)
        for r in eu_results:
            existing = db.query(Law).filter(Law.celex_number == r.celex).first()
            r.already_imported = existing is not None
            d = r.to_dict()
            d["source"] = "eu"
            results.append(d)

    return results


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
    source: str | None = None,
    db: Session = Depends(get_db),
):
    """Advanced search on legislatie.just.ro with structured filters."""
    if source == "eu":
        from app.services.eu_cellar_service import search_eu_legislation
        eu_results = search_eu_legislation(keyword=keyword, doc_type=doc_type, year=year, number=number)
        for r in eu_results:
            existing = db.query(Law).filter(Law.celex_number == r.celex).first()
            r.already_imported = existing is not None
        return {"results": [r.to_dict() for r in eu_results], "total": len(eu_results)}

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


@router.get("/eu/search")
def eu_search(
    keyword: str | None = None,
    doc_type: str | None = None,
    year: str | None = None,
    number: str | None = None,
    in_force_only: bool = False,
    db: Session = Depends(get_db),
):
    """Search EU legislation via CELLAR SPARQL."""
    from app.services.eu_cellar_service import search_eu_legislation
    results = search_eu_legislation(
        keyword=keyword, doc_type=doc_type, year=year,
        number=number, in_force_only=in_force_only,
    )
    for r in results:
        existing = db.query(Law).filter(Law.celex_number == r.celex).first()
        r.already_imported = existing is not None
    return [r.to_dict() for r in results]


@router.post("/eu/import")
def eu_import(req: EUImportRequest, db: Session = Depends(get_db)):
    """Import an EU law by CELEX number (legacy synchronous endpoint).

    Kept for callers that don't yet use the job-based variant. New UI flows
    should use POST /eu/import/job below — it survives page navigation.
    """
    from app.services.eu_cellar_service import import_eu_law
    existing = db.query(Law).filter(Law.celex_number == req.celex_number).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Already imported as law_id={existing.id}")
    try:
        result = import_eu_law(db, req.celex_number, import_history=req.import_history)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"EU import failed for {req.celex_number}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class EUImportJobRequest(BaseModel):
    celex_number: str
    import_history: bool = True
    category_id: int | None = None


@router.post("/eu/import/job")
def eu_import_as_job(req: EUImportJobRequest, db: Session = Depends(get_db)):
    """Start an EU law import as a background job.

    Mirrors `/api/laws/import/job` but for CELLAR. Returns `{job_id}` and
    runs the import in the JobService thread pool, so a page refresh in the
    middle of importing a 12-version regulation is no longer destructive.
    """
    from app.services import job_service

    celex = req.celex_number.strip()
    if not celex:
        raise HTTPException(status_code=400, detail="celex_number is required")

    existing = db.query(Law).filter(Law.celex_number == celex).first()
    if existing:
        raise DuplicateImportError(existing.title)

    if job_service.has_active(
        db, kind="import_eu_law", entity_kind="law_pending", entity_id=celex
    ):
        raise HTTPException(
            status_code=409, detail="Import already in progress for this CELEX"
        )

    job_id = job_service.submit(
        kind="import_eu_law",
        params={
            "celex_number": celex,
            "import_history": req.import_history,
            "category_id": req.category_id,
        },
        runner=_run_import_eu_law_job,
        entity_kind="law_pending",
        entity_id=celex,
        db=db,
    )
    return {"job_id": job_id}


def _run_import_eu_law_job(db: Session, job_id: str, params: dict):
    """JobService runner for EU law imports.

    Wraps eu_cellar_service.import_eu_law and bridges its on_progress events
    to update_progress() so the frontend polling effect can show phase /
    current / total. Final result (law_id, etc.) goes into result_json.
    """
    from app.services.eu_cellar_service import import_eu_law
    from app.services import job_service

    celex: str = params["celex_number"]
    import_history: bool = params.get("import_history", True)
    category_id: int | None = params.get("category_id")

    def _on_progress(event: dict):
        try:
            job_service.update_progress(
                db,
                job_id,
                phase=event.get("message") or event.get("phase"),
                current=event.get("current"),
                total=event.get("total"),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to push progress for job %s", job_id)

    result = import_eu_law(
        db,
        celex,
        import_history=import_history,
        on_progress=_on_progress,
    )

    # Auto-assign category if explicitly provided.
    if category_id and isinstance(result, dict) and result.get("law_id"):
        law = db.query(Law).filter(Law.id == result["law_id"]).first()
        if law:
            law.category_id = category_id
            law.category_confidence = "high"
            db.commit()

    # Re-tag the job to point at the law that was just created so the law
    # detail page can find this job by entity_id afterwards.
    if isinstance(result, dict) and result.get("law_id"):
        job_service.update_progress(
            db,
            job_id,
            phase="done",
            entity_kind="law",
            entity_id=result["law_id"],
        )
    return result


@router.get("/eu/filter-options")
def eu_filter_options():
    """Return available EU document type filters."""
    return {
        "doc_types": [
            {"value": "directive", "label": "Directive"},
            {"value": "regulation", "label": "Regulation"},
            {"value": "eu_decision", "label": "Decision"},
            {"value": "treaty", "label": "Treaty"},
        ]
    }


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
        raise DuplicateImportError(existing.law.title)

    # Also check by source_url — the main page ver_id may differ from stored
    # version ver_ids, but the source_url will match.
    source_url = f"https://legislatie.just.ro/Public/DetaliiDocument/{ver_id}"
    existing_law = db.query(Law).filter(Law.source_url == source_url).first()
    if existing_law:
        raise DuplicateImportError(existing_law.title)

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
        raise ImportFailedError(str(e))
    except Exception as e:
        logger.exception(f"Failed to import ver_id={ver_id}")
        db.rollback()
        raise ImportFailedError(str(e))


class DirectImportJobRequest(BaseModel):
    ver_id: str
    import_history: bool = True
    category_id: int | None = None


def _resolve_suggested_category_id(db: Session, result: dict) -> int | None:
    """Match an imported law against existing LawMapping suggestions.

    Match priority:
      1. Exact (document_type + law_number + law_year)
      2. Partial (law_number + law_year, ignore document_type)
      3. Partial (document_type + law_number, ignore year)
      4. law_number only when there is a single candidate
    """
    law_number = result.get("law_number")
    law_year = result.get("law_year")
    doc_type = result.get("document_type")
    if not law_number or law_number == "unknown":
        return None
    candidates = (
        db.query(LawMapping).filter(LawMapping.law_number == law_number).all()
    )
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0].category_id
    if doc_type and law_year:
        for c in candidates:
            if c.document_type == doc_type and c.law_year == law_year:
                return c.category_id
    if law_year:
        for c in candidates:
            if c.law_year == law_year:
                return c.category_id
    if doc_type:
        matches = [c for c in candidates if c.document_type == doc_type]
        if len(matches) == 1:
            return matches[0].category_id
    return None


@router.post("/import/job")
def import_law_as_job(req: DirectImportJobRequest, db: Session = Depends(get_db)):
    """Start a direct law import as a background job.

    Returns `{job_id}` immediately. The actual import runs in the JobService
    thread pool — frontend polls /api/jobs/{job_id} for progress and result.
    This is the resumable replacement for the old /import/stream SSE endpoint.
    """
    from app.services import job_service

    logger.info(
        "/import/job called with ver_id=%s history=%s cat=%s",
        req.ver_id, req.import_history, req.category_id,
    )

    # ver_id parsing — accept either bare digits or a legislatie.just.ro URL
    ver_id = req.ver_id.strip()
    url_match = re.search(r"DetaliiDocument/(\d+)", ver_id)
    if url_match:
        ver_id = url_match.group(1)

    if not ver_id.isdigit():
        raise HTTPException(
            status_code=400,
            detail="Invalid ver_id. Provide a numeric ID or a legislatie.just.ro URL.",
        )

    # Pre-flight duplicate checks. We do these inside the request handler so
    # the user gets a synchronous 4xx instead of having to poll a job to find
    # out their import was a no-op.
    existing = db.query(LawVersion).filter(LawVersion.ver_id == ver_id).first()
    if existing:
        raise DuplicateImportError(existing.law.title)
    source_url = f"https://legislatie.just.ro/Public/DetaliiDocument/{ver_id}"
    existing_law = db.query(Law).filter(Law.source_url == source_url).first()
    if existing_law:
        raise DuplicateImportError(existing_law.title)

    # Same-ver_id concurrency guard. Without this, double-clicks could spin up
    # two parallel imports of the same law.
    if job_service.has_active(db, kind="import_law", entity_kind="law_pending", entity_id=ver_id):
        raise HTTPException(status_code=409, detail="Import already in progress for this ver_id")

    job_id = job_service.submit(
        kind="import_law",
        params={
            "ver_id": ver_id,
            "import_history": req.import_history,
            "category_id": req.category_id,
        },
        runner=_run_import_law_job,
        entity_kind="law_pending",
        entity_id=ver_id,
        db=db,
    )
    return {"job_id": job_id}


def _run_import_law_job(db: Session, job_id: str, params: dict):
    """JobService runner for direct law imports.

    Wraps leropa_service.import_law and bridges its on_progress events to
    update_progress() so the frontend can poll for status.
    """
    from app.services.leropa_service import import_law as do_import
    from app.services import job_service

    ver_id: str = params["ver_id"]
    import_history: bool = params.get("import_history", True)
    category_id: int | None = params.get("category_id")

    def _on_progress(event: dict):
        # leropa_service emits {"event": "progress", "data": {phase, current, total, message, ...}}
        data = event.get("data", {}) if isinstance(event, dict) else {}
        phase = data.get("phase")
        msg = data.get("message")
        # Prefer the human message, fall back to the phase name
        display = msg or phase
        try:
            job_service.update_progress(
                db,
                job_id,
                phase=display,
                current=data.get("current"),
                total=data.get("total"),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to push progress for job %s", job_id)

    result = do_import(db, ver_id, import_history=import_history, on_progress=_on_progress)

    # Auto-assign category if explicitly provided.
    if category_id:
        law = db.query(Law).filter(Law.id == result["law_id"]).first()
        if law:
            law.category_id = category_id
            law.category_confidence = "high"
            db.commit()
    else:
        suggested = _resolve_suggested_category_id(db, result)
        if suggested:
            result["suggested_category_id"] = suggested

    # Re-tag the job to point at the law that was just created so the law
    # detail page can find this job by entity_id afterwards (and so refresh-
    # then-mount can pick it up while it's finishing post-import bookkeeping).
    job_service.update_progress(
        db,
        job_id,
        phase="done",
        entity_kind="law",
        entity_id=result["law_id"],
    )
    return result


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
        raise NoLawNumberError()

    # 3. Check if already imported by law_number (+ document_type/year if available)
    existing_query = db.query(Law).filter(Law.law_number == mapping.law_number)
    if mapping.document_type:
        existing_query = existing_query.filter(Law.document_type == mapping.document_type)
    if mapping.law_year:
        existing_query = existing_query.filter(Law.law_year == mapping.law_year)
    existing = existing_query.first()
    if existing:
        raise DuplicateImportError(existing.title)

    # 4. Resolve ver_id — pinned mappings skip the search entirely
    if mapping.source_ver_id:
        ver_id = mapping.source_ver_id
    else:
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
            raise SearchFailedError()

        if not results:
            raise HTTPException(
                status_code=404,
                detail=f"No results found on legislatie.just.ro for {mapping.title}",
            )

        # Pick best match — first result (search is filtered by type+number+year)
        ver_id = results[0].ver_id

    # 6. Check if this ver_id is already imported
    existing_ver = db.query(LawVersion).filter(LawVersion.ver_id == ver_id).first()
    if existing_ver:
        raise DuplicateImportError(existing_ver.law.title)

    # 7. Import
    try:
        result = do_import(db, ver_id, import_history=req.import_history)
    except ValueError as e:
        db.rollback()
        raise ImportFailedError(str(e))
    except Exception as e:
        logger.exception(f"Failed to import suggestion {req.mapping_id} (ver_id={ver_id})")
        db.rollback()
        raise ImportFailedError(str(e))

    # 8. Auto-assign category
    law = db.query(Law).filter(Law.id == result["law_id"]).first()
    if law:
        law.category_id = mapping.category_id
        law.category_confidence = "high"
        db.commit()

    # Pin-on-import: remember the resolved ver_id so future imports skip search
    if not mapping.source_ver_id and ver_id:
        mapping.source_ver_id = str(ver_id)
        db.commit()

    return {
        "law_id": result["law_id"],
        "title": result.get("title", mapping.title),
    }


@router.post("/import-suggestion/{mapping_id}/job")
def import_suggestion_as_job(
    mapping_id: int,
    req: ImportStreamRequest,
    db: Session = Depends(get_db),
):
    """Import a suggestion (LawMapping) as a background job.

    Returns `{job_id}`. The runner resolves the ver_id (skipping search if the
    mapping is pinned), runs `import_law`, and applies pin-on-import.
    Frontend polls /api/jobs/{job_id} for progress.
    """
    from app.services import job_service
    from app.services.search_service import advanced_search
    from app.errors import SearchFailedError

    # Validate mapping (synchronous → user gets a clean 4xx instead of polling
    # a job that just failed).
    mapping = db.query(LawMapping).filter(LawMapping.id == mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if not mapping.law_number:
        raise NoLawNumberError()

    existing_query = db.query(Law).filter(Law.law_number == mapping.law_number)
    if mapping.document_type:
        existing_query = existing_query.filter(Law.document_type == mapping.document_type)
    if mapping.law_year:
        existing_query = existing_query.filter(Law.law_year == mapping.law_year)
    existing = existing_query.first()
    if existing:
        raise DuplicateImportError(existing.title)

    if mapping.source_ver_id:
        ver_id = str(mapping.source_ver_id)
        resolved_from_search = False
    else:
        doc_type_code = _DOC_TYPE_TO_SEARCH_CODE.get(mapping.document_type or "", "")
        year_str = str(mapping.law_year) if mapping.law_year else ""
        try:
            results = advanced_search(
                doc_type=doc_type_code,
                number=mapping.law_number,
                year=year_str,
            )
        except Exception as e:
            logger.error("Search failed for suggestion %s: %s", mapping_id, e)
            raise SearchFailedError()
        if not results:
            raise HTTPException(
                status_code=404,
                detail=f"No results found on legislatie.just.ro for {mapping.title}",
            )
        ver_id = str(results[0].ver_id)
        resolved_from_search = True

    existing_ver = db.query(LawVersion).filter(LawVersion.ver_id == ver_id).first()
    if existing_ver:
        raise DuplicateImportError(existing_ver.law.title)

    if job_service.has_active(db, kind="import_suggestion", entity_kind="mapping", entity_id=mapping_id):
        raise HTTPException(status_code=409, detail="Import already in progress for this suggestion")

    job_id = job_service.submit(
        kind="import_suggestion",
        params={
            "mapping_id": mapping_id,
            "ver_id": ver_id,
            "import_history": req.import_history,
            "resolved_from_search": resolved_from_search,
        },
        runner=_run_import_suggestion_job,
        entity_kind="mapping",
        entity_id=mapping_id,
        db=db,
    )
    return {"job_id": job_id}


def _run_import_suggestion_job(db: Session, job_id: str, params: dict):
    """JobService runner for /import-suggestion/{id}/job."""
    from app.services.leropa_service import import_law as do_import
    from app.services import job_service

    mapping_id: int = params["mapping_id"]
    ver_id: str = params["ver_id"]
    import_history: bool = params.get("import_history", False)
    resolved_from_search: bool = params.get("resolved_from_search", False)

    def _on_progress(event: dict):
        data = event.get("data", {}) if isinstance(event, dict) else {}
        try:
            job_service.update_progress(
                db,
                job_id,
                phase=data.get("message") or data.get("phase"),
                current=data.get("current"),
                total=data.get("total"),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to push progress for job %s", job_id)

    result = do_import(db, ver_id, import_history=import_history, on_progress=_on_progress)

    # Pin-on-import: remember the resolved ver_id so future imports skip search.
    if resolved_from_search and ver_id:
        m = db.query(LawMapping).filter(LawMapping.id == mapping_id).first()
        if m and not m.source_ver_id:
            m.source_ver_id = str(ver_id)
            db.commit()

    return result


class BulkImportRequest(BaseModel):
    import_history: bool = False


@router.post("/import-all-suggestions/job")
def import_all_suggestions_as_job(
    req: BulkImportRequest, db: Session = Depends(get_db)
):
    """Bulk-import every unimported suggested law as a single background job.

    Returns `{job_id, total}`. The runner walks the suggestion list and
    accumulates per-item outcomes in the job's `result_json`. Frontend polls
    /api/jobs/{job_id} for live progress and the final summary.
    """
    from app.services import job_service
    from app.services.category_service import get_unimported_suggestions

    if job_service.has_active(db, kind="import_all_suggestions"):
        raise HTTPException(
            status_code=409, detail="Bulk import already in progress"
        )

    suggestions = get_unimported_suggestions(db)
    suggestion_data = [
        {
            "id": m.id,
            "title": m.title,
            "law_number": m.law_number,
            "law_year": m.law_year,
            "document_type": m.document_type,
            "category_id": m.category_id,
            "source_ver_id": m.source_ver_id,
        }
        for m in suggestions
    ]

    job_id = job_service.submit(
        kind="import_all_suggestions",
        params={"import_history": req.import_history, "suggestions": suggestion_data},
        runner=_run_import_all_suggestions_job,
        db=db,
    )
    return {"job_id": job_id, "total": len(suggestion_data)}


def _run_import_all_suggestions_job(db: Session, job_id: str, params: dict):
    """JobService runner for bulk suggestion import.

    Iterates the snapshotted suggestion list, importing each one in a fresh
    SessionLocal so a single failure can't poison the runner's session.
    Updates the Job row's progress between items and returns a structured
    summary that the frontend reads from `result_json`.
    """
    import time as _time
    from app.database import SessionLocal
    from app.services import job_service
    from app.services.search_service import advanced_search
    from app.services.leropa_service import import_law as do_import
    from app.models.category import LawMapping as _LM

    suggestion_data: list[dict] = params.get("suggestions", [])
    import_history: bool = params.get("import_history", False)
    total = len(suggestion_data)

    imported = 0
    failed = 0
    skipped = 0
    items: list[dict] = []  # per-item outcomes for the final result_json

    job_service.update_progress(db, job_id, phase="starting", current=0, total=total)

    for i, mapping in enumerate(suggestion_data):
        title = mapping["title"]
        job_service.update_progress(
            db,
            job_id,
            phase=f"Importing: {title}",
            current=i + 1,
            total=total,
        )

        if not mapping["law_number"]:
            failed += 1
            items.append({"title": title, "status": "error", "error": "No law number"})
            continue

        max_retries = 2
        outcome: dict | None = None
        for attempt in range(max_retries + 1):
            import_db = SessionLocal()
            try:
                existing_query = import_db.query(Law).filter(
                    Law.law_number == mapping["law_number"]
                )
                if mapping["document_type"]:
                    existing_query = existing_query.filter(
                        Law.document_type == mapping["document_type"]
                    )
                if mapping["law_year"]:
                    existing_query = existing_query.filter(
                        Law.law_year == mapping["law_year"]
                    )
                if existing_query.first():
                    skipped += 1
                    outcome = {"title": title, "status": "skipped", "reason": "Already imported"}
                    break

                if mapping["source_ver_id"]:
                    ver_id = str(mapping["source_ver_id"])
                    resolved_from_search = False
                else:
                    doc_type_code = _DOC_TYPE_TO_SEARCH_CODE.get(
                        mapping["document_type"] or "", ""
                    )
                    year_str = str(mapping["law_year"]) if mapping["law_year"] else ""
                    results = advanced_search(
                        doc_type=doc_type_code,
                        number=mapping["law_number"],
                        year=year_str,
                    )
                    if not results:
                        failed += 1
                        outcome = {
                            "title": title,
                            "status": "error",
                            "error": "Not found on legislatie.just.ro",
                        }
                        break
                    ver_id = str(results[0].ver_id)
                    resolved_from_search = True

                existing_ver = (
                    import_db.query(LawVersion)
                    .filter(LawVersion.ver_id == ver_id)
                    .first()
                )
                if existing_ver:
                    skipped += 1
                    outcome = {
                        "title": title,
                        "status": "skipped",
                        "reason": "Version already imported",
                    }
                    break

                result = do_import(import_db, ver_id, import_history=import_history)

                law = import_db.query(Law).filter(Law.id == result["law_id"]).first()
                if law:
                    law.category_id = mapping["category_id"]
                    law.category_confidence = "high"
                    import_db.commit()

                if resolved_from_search:
                    m = import_db.query(_LM).filter(_LM.id == mapping["id"]).first()
                    if m and not m.source_ver_id:
                        m.source_ver_id = ver_id
                        import_db.commit()

                imported += 1
                outcome = {
                    "title": title,
                    "status": "imported",
                    "law_id": result["law_id"],
                }
                break

            except Exception as e:  # noqa: BLE001
                import_db.rollback()
                is_db_locked = "database is locked" in str(e)
                if is_db_locked and attempt < max_retries:
                    logger.warning(
                        "DB locked for %s, retrying (%d/%d)…",
                        title, attempt + 1, max_retries,
                    )
                    import_db.close()
                    _time.sleep(5)
                    continue
                failed += 1
                logger.error("Bulk import failed for %s: %s", title, e)
                outcome = {"title": title, "status": "error", "error": str(e)[:200]}
                break
            finally:
                import_db.close()

        if outcome is not None:
            items.append(outcome)

    return {
        "total": total,
        "imported": imported,
        "failed": failed,
        "skipped": skipped,
        "items": items,
    }


@router.get("/new-versions")
def get_new_versions(db: Session = Depends(get_db)):
    """Return laws that have newer KnownVersions than their latest imported LawVersion.

    For each law, returns only the latest unimported version (the newest by date
    that is more recent than the highest imported version).
    """
    from sqlalchemy import func as sa_func

    # Get the max imported date_in_force per law
    latest_imported = (
        db.query(
            LawVersion.law_id,
            sa_func.max(LawVersion.date_in_force).label("max_date"),
        )
        .group_by(LawVersion.law_id)
        .subquery()
    )

    # Get all known versions that are newer than the latest imported version
    newer = (
        db.query(KnownVersion)
        .join(latest_imported, KnownVersion.law_id == latest_imported.c.law_id)
        .filter(KnownVersion.date_in_force > latest_imported.c.max_date)
        .filter(
            ~KnownVersion.ver_id.in_(
                db.query(LawVersion.ver_id)
            )
        )
        .all()
    )

    # Group by law_id and return all new versions per law
    from itertools import groupby
    from operator import attrgetter

    newer_sorted = sorted(newer, key=attrgetter("law_id"))
    results = []
    for law_id, group in groupby(newer_sorted, key=attrgetter("law_id")):
        versions = sorted(group, key=attrgetter("date_in_force"))
        law = db.query(Law).filter(Law.id == law_id).first()
        if not law:
            continue
        latest_date = max(v.date_in_force for v in versions)
        # Total known versions for this law (to compute version numbers)
        total_known = (
            db.query(KnownVersion)
            .filter(KnownVersion.law_id == law_id)
            .count()
        )
        # These new versions are the last N in chronological order
        version_number_offset = total_known - len(versions)
        results.append({
            "law_id": law.id,
            "title": law.title,
            "description": law.description,
            "law_number": law.law_number,
            "law_year": law.law_year,
            "source": getattr(law, "source", "ro"),
            "version_number_offset": version_number_offset,
            "versions": [
                {
                    "ver_id": v.ver_id,
                    "date_in_force": str(v.date_in_force),
                    "is_latest": v.date_in_force == latest_date,
                }
                for i, v in enumerate(versions)
            ],
        })

    return {"new_versions": results}


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
            "issuer": law.issuer,
            "category_id": law.category_id,
            "category_group_slug": law.category.group.slug if law.category else None,
            "category_confidence": law.category_confidence,
            "source": getattr(law, "source", "ro"),
            "unimported_version_count": db.query(KnownVersion).filter(
                KnownVersion.law_id == law.id,
                KnownVersion.ver_id.notin_(
                    db.query(LawVersion.ver_id).filter(LawVersion.law_id == law.id)
                ),
            ).count(),
        }
        for law in laws
    ]


@router.get("/{law_id}")
def get_law(
    law_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a law with all its versions."""
    from app.models.favorite import LawFavorite

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    is_favorite = db.query(LawFavorite).filter(
        LawFavorite.user_id == current_user.id,
        LawFavorite.law_id == law_id,
    ).first() is not None

    # Self-heal: fix is_current flags and backfill missing dates from KnownVersion
    _recalculate_current_version(db, law_id)

    # Backfill missing diff summaries for this law's versions
    from app.services.diff_summary import compute_diff_summary
    for v in law.versions:
        if v.diff_summary is None and v.date_in_force is not None:
            v.diff_summary = compute_diff_summary(db, v)

    db.commit()

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
        "is_favorite": is_favorite,
        "last_checked_at": str(law.last_checked_at) if law.last_checked_at else None,
        "unimported_version_count": db.query(KnownVersion).filter(
            KnownVersion.law_id == law.id,
            KnownVersion.ver_id.notin_(
                db.query(LawVersion.ver_id).filter(LawVersion.law_id == law.id)
            ),
        ).count(),
        "versions": [
            {
                "id": v.id,
                "ver_id": v.ver_id,
                "date_in_force": str(v.date_in_force) if v.date_in_force else None,
                "date_imported": str(v.date_imported),
                "state": v.state,
                "is_current": v.is_current,
                "diff_summary": v.diff_summary,
            }
            for v in sorted(law.versions, key=lambda v: str(v.date_in_force) if v.date_in_force else "", reverse=True)
        ],
    }


@router.get("/{law_id}/known-versions")
def get_known_versions(law_id: int, db: Session = Depends(get_db)):
    """Get all known versions for a law, with import status."""
    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    known = (
        db.query(KnownVersion)
        .filter(KnownVersion.law_id == law_id)
        .order_by(KnownVersion.date_in_force.desc())
        .all()
    )

    # Get imported ver_ids for this law
    imported_ver_ids = {
        row[0]
        for row in db.query(LawVersion.ver_id)
        .filter(LawVersion.law_id == law_id)
        .all()
    }

    return {
        "law_id": law_id,
        "last_checked_at": str(law.last_checked_at) if law.last_checked_at else None,
        "versions": [
            {
                "id": kv.id,
                "ver_id": kv.ver_id,
                "date_in_force": str(kv.date_in_force),
                "is_current": kv.is_current,
                "is_imported": kv.ver_id in imported_ver_ids,
                "discovered_at": str(kv.discovered_at),
            }
            for kv in known
        ],
        "unimported_count": sum(
            1 for kv in known if kv.ver_id not in imported_ver_ids
        ),
    }


class ImportKnownVersionRequest(BaseModel):
    ver_id: str


@router.post("/{law_id}/known-versions/import")
def import_known_version(law_id: int, req: ImportKnownVersionRequest, db: Session = Depends(get_db)):
    """Import a specific known version (full text extraction)."""
    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    # Verify it's a known version for this law
    kv = (
        db.query(KnownVersion)
        .filter(KnownVersion.law_id == law_id, KnownVersion.ver_id == req.ver_id)
        .first()
    )
    if not kv:
        raise HTTPException(status_code=404, detail="Version not found in known versions")

    # Check if already imported
    existing = db.query(LawVersion).filter(LawVersion.ver_id == req.ver_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="This version is already imported")

    if law.source == "eu":
        from app.services.eu_cellar_service import import_eu_known_version
        # EUContentUnavailableError is a ThemisError handled globally with code
        new_version = import_eu_known_version(db, law, req.ver_id)
    else:
        from app.services.leropa_service import fetch_and_store_version
        import app.services.leropa_service as _ls
        _ls._stored_article_ids = set()
        _, new_version = fetch_and_store_version(
            db, req.ver_id, law=law, override_date=kv.date_in_force,
        )

    # Update is_current based on KnownVersion source of truth (LegislatieJust)
    _recalculate_current_version(db, law_id)

    db.commit()

    # Compute diff summary for the new version (and update the next version if it exists)
    from app.services.diff_summary import compute_diff_summary
    new_version.diff_summary = compute_diff_summary(db, new_version)

    # Also recompute the version right after this one (if any), since its predecessor changed
    next_ver = (
        db.query(LawVersion)
        .filter(
            LawVersion.law_id == law_id,
            LawVersion.id != new_version.id,
            LawVersion.date_in_force > new_version.date_in_force if new_version.date_in_force else False,
        )
        .order_by(LawVersion.date_in_force.asc())
        .first()
    )
    if next_ver:
        next_ver.diff_summary = compute_diff_summary(db, next_ver)

    db.commit()

    return {"status": "imported", "ver_id": req.ver_id, "law_version_id": new_version.id}


class ImportKnownVersionsBatchRequest(BaseModel):
    ver_ids: list[str]


@router.post("/{law_id}/known-versions/import-batch/job")
def import_known_versions_batch_as_job(
    law_id: int,
    req: ImportKnownVersionsBatchRequest,
    db: Session = Depends(get_db),
):
    """Submit a batch of known-version imports for a single law as a background job.

    Replaces the frontend's previous pattern of awaiting `/known-versions/import`
    in a loop on the client. That pattern persisted half-finished entries to
    localStorage and lost them on refresh; running the same loop in JobService
    means the import survives refresh and the polling effect drives progress.
    """
    from app.services import job_service

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    ver_ids = [v.strip() for v in req.ver_ids if v and v.strip()]
    if not ver_ids:
        raise HTTPException(status_code=400, detail="ver_ids is required")

    # All ver_ids must belong to this law's known versions, otherwise the
    # frontend gave us junk and we should fail synchronously.
    known_set = {
        row[0]
        for row in db.query(KnownVersion.ver_id)
        .filter(KnownVersion.law_id == law_id, KnownVersion.ver_id.in_(ver_ids))
        .all()
    }
    missing = [v for v in ver_ids if v not in known_set]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown ver_ids for this law: {','.join(missing)}",
        )

    if job_service.has_active(
        db,
        kind="import_known_versions_batch",
        entity_kind="law",
        entity_id=law_id,
    ):
        raise HTTPException(
            status_code=409,
            detail="Another batch import is already in progress for this law",
        )

    job_id = job_service.submit(
        kind="import_known_versions_batch",
        params={"law_id": law_id, "ver_ids": ver_ids},
        runner=_run_import_known_versions_batch_job,
        entity_kind="law",
        entity_id=law_id,
        db=db,
    )
    return {"job_id": job_id, "total": len(ver_ids)}


def _run_import_known_versions_batch_job(db: Session, job_id: str, params: dict):
    """JobService runner: sequentially import a list of known versions for one law.

    Order is whatever the caller submitted — the frontend sends oldest-first so
    diffs compute correctly. Per-version progress is pushed to the job row so
    the polling effect's progress bar advances.

    Failure model:
      - EUContentUnavailableError on a single version → record as a permanent
        skip and continue with the next one. The skip list is returned in the
        job result so the frontend can surface them as non-retriable failed
        rows after the job completes.
      - Any other exception → stop the batch and raise. The exception bubbles
        up to JobService._run_job which marks the job failed and persists the
        message; the frontend already renders job.error.message in the failed
        list.
    """
    from app.services import job_service
    from app.errors import EUContentUnavailableError

    law_id: int = params["law_id"]
    ver_ids: list[str] = params["ver_ids"]
    total = len(ver_ids)

    law = db.query(Law).filter(Law.id == law_id).first()
    if law is None:
        raise ValueError(f"Law {law_id} not found")

    job_service.update_progress(
        db, job_id, phase="version", current=0, total=total
    )

    imported = 0
    skipped: list[dict] = []

    for ver_id in ver_ids:
        kv = (
            db.query(KnownVersion)
            .filter(KnownVersion.law_id == law_id, KnownVersion.ver_id == ver_id)
            .first()
        )
        if kv is None:
            raise ValueError(f"Known version {ver_id} not found for law {law_id}")

        # Already imported? Treat as success and advance the counter.
        existing = (
            db.query(LawVersion).filter(LawVersion.ver_id == ver_id).first()
        )
        if existing is not None:
            imported += 1
            job_service.update_progress(db, job_id, current=imported)
            continue

        try:
            if law.source == "eu":
                from app.services.eu_cellar_service import import_eu_known_version

                import_eu_known_version(db, law, ver_id)
            else:
                from app.services.leropa_service import fetch_and_store_version
                import app.services.leropa_service as _ls

                _ls._stored_article_ids = set()
                fetch_and_store_version(
                    db, ver_id, law=law, override_date=kv.date_in_force
                )

            _recalculate_current_version(db, law_id)
            db.commit()
            imported += 1
            job_service.update_progress(db, job_id, current=imported)
        except EUContentUnavailableError as e:
            # CELLAR has nothing for this version yet — non-retriable, skip.
            db.rollback()
            skipped.append(
                {"ver_id": ver_id, "error": str(e), "permanent": True}
            )
            continue
        except Exception as e:
            # Transient/unknown — stop the batch and surface the message with
            # the partial-progress count so the user knows where it died.
            db.rollback()
            raise RuntimeError(
                f"{e} (imported {imported}/{total})"
            ) from e

    # Backfill diffs once at the end so version order is stable. Scoped to
    # this law — a global scan would block on the SQLite writer lock when
    # two batch jobs run in parallel and leave them stuck in `running`.
    from app.services.diff_summary import backfill_diff_summaries

    backfilled = backfill_diff_summaries(db, law_id=law_id)
    if backfilled:
        db.commit()

    return {"imported": imported, "total": total, "skipped": skipped}


@router.post("/{law_id}/known-versions/import-all")
def import_all_missing(law_id: int, db: Session = Depends(get_db)):
    """Import all known versions that aren't imported yet."""
    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    imported_ver_ids = {
        row[0]
        for row in db.query(LawVersion.ver_id)
        .filter(LawVersion.law_id == law_id)
        .all()
    }

    missing = (
        db.query(KnownVersion)
        .filter(
            KnownVersion.law_id == law_id,
            KnownVersion.ver_id.notin_(imported_ver_ids) if imported_ver_ids else True,
        )
        .order_by(KnownVersion.date_in_force.asc())
        .all()
    )

    if not missing:
        return {"status": "nothing_to_import", "imported": 0}

    imported_count = 0
    errors = []

    if law.source == "eu":
        import time as _time
        from app.services.eu_cellar_service import import_eu_known_version
        for i, kv in enumerate(missing):
            try:
                if i > 0:
                    _time.sleep(2.0)  # rate-limit CELLAR API
                import_eu_known_version(db, law, kv.ver_id)
                imported_count += 1
            except Exception as e:
                logger.error(f"Failed to import EU version {kv.ver_id}: {e}")
                errors.append({"ver_id": kv.ver_id, "error": str(e)[:200]})
    else:
        from app.services.leropa_service import fetch_and_store_version
        import app.services.leropa_service as _ls
        for kv in missing:
            try:
                _ls._stored_article_ids = set()
                fetch_and_store_version(db, kv.ver_id, law=law, override_date=kv.date_in_force)
                imported_count += 1
            except Exception as e:
                logger.error(f"Failed to import version {kv.ver_id}: {e}")
                errors.append({"ver_id": kv.ver_id, "error": str(e)[:200]})

    # Update is_current based on KnownVersion source of truth
    _recalculate_current_version(db, law_id)

    db.commit()

    # Backfill diff summaries for all versions of this law
    from app.services.diff_summary import backfill_diff_summaries
    backfilled = backfill_diff_summaries(db, law_id=law_id)
    if backfilled:
        db.commit()

    return {"status": "done", "imported": imported_count, "errors": errors}


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
        .options(
            subqueryload(Article.paragraphs).subqueryload(Paragraph.subparagraphs),
            subqueryload(Article.amendment_notes),
        )
        .order_by(Article.order_index)
        .all()
    )

    # Pre-index articles and elements for O(1) lookups
    articles_by_element = defaultdict(list)
    orphan_articles = []
    for a in articles:
        if a.structural_element_id is None:
            orphan_articles.append(a)
        else:
            articles_by_element[a.structural_element_id].append(a)

    children_by_parent = defaultdict(list)
    for el in elements:
        children_by_parent[el.parent_id].append(el)

    def build_element_tree(parent_id=None):
        result = []
        for el in children_by_parent.get(parent_id, []):
            el_articles = articles_by_element.get(el.id, [])
            children = build_element_tree(el.id)
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

    # Annexes
    annexes = (
        db.query(Annex)
        .filter(Annex.law_version_id == version_id)
        .order_by(Annex.order_index)
        .all()
    )

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
        "annexes": [
            {
                "id": anx.id,
                "source_id": anx.source_id,
                "title": anx.title,
                "full_text": anx.full_text,
                "order_index": anx.order_index,
            }
            for anx in annexes
        ],
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
def check_law_updates(
    law_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Refresh KnownVersion entries for a single law from legislatie.just.ro.

    Discovery only: writes/updates KnownVersion rows and re-derives
    LawVersion.is_current. Does NOT import any version text — that's the
    user's job via the Import buttons in the law-detail page.
    """
    from app.services.version_discovery import discover_versions_for_law
    from app.services.law_check_log_service import record_check

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    try:
        new_count = discover_versions_for_law(db, law)
    except Exception as e:
        logger.exception(f"Error checking updates for law {law_id}")
        db.rollback()
        record_check(
            db,
            law=law,
            user_id=current_user.id,
            new_versions=0,
            status="error",
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=f"Update check failed: {str(e)}")

    record_check(
        db,
        law=law,
        user_id=current_user.id,
        new_versions=new_count,
        status="ok",
    )

    return {
        "discovered": new_count,
        "last_checked_at": str(law.last_checked_at) if law.last_checked_at else None,
    }


@router.get("/{law_id}/check-logs", response_model=list[LawCheckLogRowOut])
def list_law_check_logs_for_law(
    law_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Return the per-law update check history, newest first."""
    from app.models.law_check_log import LawCheckLog

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    capped = max(1, min(limit, 200))

    rows = (
        db.query(LawCheckLog, User)
        .outerjoin(User, User.id == LawCheckLog.user_id)
        .filter(LawCheckLog.law_id == law_id)
        .order_by(LawCheckLog.checked_at.desc())
        .limit(capped)
        .all()
    )

    return [
        LawCheckLogRowOut(
            id=log.id,
            checked_at=log.checked_at.isoformat(),
            user_email=user.email if user else None,
            new_versions=log.new_versions,
            status=log.status,
            error_message=log.error_message,
        )
        for (log, user) in rows
    ]


def _bulk_delete_versions(db: Session, version_ids: list[int]):
    """Bulk-delete law versions and all children using raw SQL (leaf tables first)."""
    if not version_ids:
        return

    # Subparagraphs (leaf) — via paragraph → article → version
    db.query(Subparagraph).filter(
        Subparagraph.paragraph_id.in_(
            db.query(Paragraph.id).filter(
                Paragraph.article_id.in_(
                    db.query(Article.id).filter(Article.law_version_id.in_(version_ids))
                )
            )
        )
    ).delete(synchronize_session=False)

    # AmendmentNotes — via article → version
    db.query(AmendmentNote).filter(
        AmendmentNote.article_id.in_(
            db.query(Article.id).filter(Article.law_version_id.in_(version_ids))
        )
    ).delete(synchronize_session=False)

    # Paragraphs — via article → version
    db.query(Paragraph).filter(
        Paragraph.article_id.in_(
            db.query(Article.id).filter(Article.law_version_id.in_(version_ids))
        )
    ).delete(synchronize_session=False)

    # Articles
    db.query(Article).filter(Article.law_version_id.in_(version_ids)).delete(synchronize_session=False)

    # StructuralElements — null out self-referential FK, then delete all
    db.query(StructuralElement).filter(
        StructuralElement.law_version_id.in_(version_ids)
    ).update({StructuralElement.parent_id: None}, synchronize_session=False)
    db.query(StructuralElement).filter(StructuralElement.law_version_id.in_(version_ids)).delete(synchronize_session=False)

    # Annexes
    db.query(Annex).filter(Annex.law_version_id.in_(version_ids)).delete(synchronize_session=False)

    # LawVersions themselves
    db.query(LawVersion).filter(LawVersion.id.in_(version_ids)).delete(synchronize_session=False)


def _run_delete_law_job(db: Session, job_id: str, params: dict):
    """JobService runner for full-law deletion.

    Identical body to the old _background_delete_law helper but with progress
    checkpoints written to the Job row so the UI can show "Deleting…" state
    while the long-running cascade runs.
    """
    from app.services import job_service

    law_id: int = params["law_id"]
    title: str = params.get("title", "")

    # ChromaDB cleanup is best-effort.
    job_service.update_progress(db, job_id, phase="Cleaning vector index")
    try:
        from app.services.chroma_service import remove_law_articles
        remove_law_articles(db, law_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("ChromaDB cleanup failed (non-fatal): %s", e)

    version_ids = [
        v.id for v in db.query(LawVersion.id).filter(LawVersion.law_id == law_id).all()
    ]
    job_service.update_progress(
        db, job_id, phase=f"Deleting {len(version_ids)} version(s)", total=len(version_ids), current=0
    )
    _bulk_delete_versions(db, version_ids)
    job_service.update_progress(db, job_id, current=len(version_ids))

    # KnownVersions
    db.query(KnownVersion).filter(KnownVersion.law_id == law_id).delete(synchronize_session=False)

    # The law itself
    db.query(Law).filter(Law.id == law_id).delete(synchronize_session=False)

    db.commit()
    logger.info("Delete-law job completed for '%s' (id=%s)", title, law_id)
    return {"law_id": law_id, "title": title, "deleted_versions": len(version_ids)}


def _run_delete_single_version_job(db: Session, job_id: str, params: dict):
    """JobService runner for deleting a single LawVersion."""
    from app.services import job_service

    law_id: int = params["law_id"]
    version_id: int = params["version_id"]
    job_service.update_progress(db, job_id, phase="Deleting version")
    _bulk_delete_versions(db, [version_id])
    _recalculate_current_version(db, law_id)
    db.commit()
    logger.info(
        "Delete-version job completed: version_id=%s law_id=%s", version_id, law_id
    )
    return {"law_id": law_id, "version_id": version_id}


def _run_delete_old_versions_job(db: Session, job_id: str, params: dict):
    """JobService runner for deleting all non-current versions of a law."""
    from app.services import job_service

    law_id: int = params["law_id"]
    version_ids: list[int] = params["version_ids"]
    count = len(version_ids)
    job_service.update_progress(db, job_id, phase=f"Deleting {count} old version(s)", total=count, current=0)
    _bulk_delete_versions(db, version_ids)
    db.commit()
    job_service.update_progress(db, job_id, current=count)
    logger.info("Delete-old-versions job completed for law_id=%s (%d)", law_id, count)
    return {"law_id": law_id, "deleted_count": count}


@router.delete("/{law_id}")
def delete_law(law_id: int, db: Session = Depends(get_db)):
    """Delete a law and all its versions as a background job.

    Returns `{message, job_id, deleted_count}`. Frontend can poll
    /api/jobs/{job_id} (or look up active jobs by entity_kind=law&entity_id=…)
    to surface "Deleting…" state and detect completion across page refreshes.
    """
    from app.services import job_service

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    if job_service.has_active(db, entity_kind="law", entity_id=law_id):
        raise HTTPException(status_code=409, detail="An operation is already running for this law")

    title = law.title
    version_count = len(law.versions)

    job_id = job_service.submit(
        kind="delete_law",
        params={"law_id": law_id, "title": title},
        runner=_run_delete_law_job,
        entity_kind="law",
        entity_id=law_id,
        db=db,
    )

    return {
        "message": f"Deleting '{title}' with {version_count} version(s)…",
        "job_id": job_id,
    }


@router.delete("/{law_id}/versions/{version_id}")
def delete_single_version(law_id: int, version_id: int, db: Session = Depends(get_db)):
    """Delete a single version of a law as a background job."""
    from app.services import job_service

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    version = db.query(LawVersion).filter(
        LawVersion.id == version_id, LawVersion.law_id == law_id
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    if job_service.has_active(db, entity_kind="law", entity_id=law_id):
        raise HTTPException(status_code=409, detail="An operation is already running for this law")

    ver_id = version.ver_id
    job_id = job_service.submit(
        kind="delete_version",
        params={"law_id": law_id, "version_id": version_id},
        runner=_run_delete_single_version_job,
        entity_kind="law",
        entity_id=law_id,
        db=db,
    )

    return {
        "message": f"Deleting version '{ver_id}' of '{law.title}'…",
        "job_id": job_id,
    }


@router.delete("/{law_id}/versions/old")
def delete_old_versions(law_id: int, db: Session = Depends(get_db)):
    """Delete all non-current versions of a law as a background job."""
    from app.services import job_service

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    old_versions = [v for v in law.versions if not v.is_current]
    if not old_versions:
        return {"message": "No old versions to delete", "deleted_count": 0}

    version_ids = [v.id for v in old_versions]
    count = len(version_ids)

    if job_service.has_active(db, entity_kind="law", entity_id=law_id):
        raise HTTPException(status_code=409, detail="An operation is already running for this law")

    job_id = job_service.submit(
        kind="delete_old_versions",
        params={"law_id": law_id, "version_ids": version_ids},
        runner=_run_delete_old_versions_job,
        entity_kind="law",
        entity_id=law_id,
        db=db,
    )

    return {
        "message": f"Deleting {count} old version(s) of '{law.title}'…",
        "deleted_count": count,
        "job_id": job_id,
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
    """Compare two versions of a law as a structural tree.

    version_a and version_b are LawVersion IDs. Returns a hierarchical
    article → paragraph diff. Articles whose text_clean is identical are
    emitted as 'unchanged' so the frontend can still show their summary line.
    """
    from sqlalchemy.orm import selectinload
    from app.services.structured_diff import diff_articles

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

    def _load_articles(version_id: int) -> list[Article]:
        return (
            db.query(Article)
            .filter(Article.law_version_id == version_id)
            .options(
                selectinload(Article.paragraphs).selectinload(
                    Paragraph.amendment_notes
                ),
                selectinload(Article.amendment_notes),
            )
            .order_by(Article.order_index)
            .all()
        )

    articles_a = _load_articles(version_a)
    articles_b = _load_articles(version_b)

    article_entries = diff_articles(articles_a, articles_b)

    summary = {
        "added": sum(1 for e in article_entries if e["change_type"] == "added"),
        "removed": sum(1 for e in article_entries if e["change_type"] == "removed"),
        "modified": sum(1 for e in article_entries if e["change_type"] == "modified"),
        "unchanged": sum(1 for e in article_entries if e["change_type"] == "unchanged"),
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
        "articles": article_entries,
    }
