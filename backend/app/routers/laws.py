import asyncio
import datetime
import json
import logging
import re
import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from collections import defaultdict

from sqlalchemy.orm import Session, subqueryload
from sse_starlette.sse import EventSourceResponse

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
    """Import an EU law by CELEX number."""
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


class DirectImportStreamRequest(BaseModel):
    ver_id: str
    import_history: bool = True
    category_id: int | None = None


@router.post("/import/stream")
async def import_law_stream(req: DirectImportStreamRequest, db: Session = Depends(get_db)):
    """SSE endpoint that streams import progress for a direct law import by ver_id."""
    from app.services.leropa_service import import_law as do_import
    from app.errors import DuplicateImportError, ImportFailedError, map_exception_to_error

    logger.info(f"[SSE] /import/stream called with ver_id={req.ver_id}, history={req.import_history}, cat={req.category_id}")

    # Extract ver_id from URL if needed
    ver_id = req.ver_id.strip()
    url_match = re.search(r"DetaliiDocument/(\d+)", ver_id)
    if url_match:
        ver_id = url_match.group(1)

    if not ver_id.isdigit():
        async def error_stream():
            yield {"event": "error", "data": json.dumps({"code": "invalid_input", "message": "Invalid ver_id"})}
        return EventSourceResponse(error_stream())

    # Check duplicates
    existing = db.query(LawVersion).filter(LawVersion.ver_id == ver_id).first()
    if existing:
        async def error_stream():
            yield {"event": "error", "data": json.dumps(DuplicateImportError(existing.law.title).to_dict())}
        return EventSourceResponse(error_stream())

    source_url = f"https://legislatie.just.ro/Public/DetaliiDocument/{ver_id}"
    existing_law = db.query(Law).filter(Law.source_url == source_url).first()
    if existing_law:
        async def error_stream():
            yield {"event": "error", "data": json.dumps(DuplicateImportError(existing_law.title).to_dict())}
        return EventSourceResponse(error_stream())

    import queue as thread_queue

    category_id = req.category_id

    # Use a thread-safe queue since on_progress is called from asyncio.to_thread
    tq: thread_queue.Queue = thread_queue.Queue()

    def on_progress(event: dict):
        tq.put(event)

    async def run_import():
        try:
            result = await asyncio.to_thread(
                do_import, db, ver_id,
                import_history=req.import_history,
                on_progress=on_progress,
            )
            # Auto-assign category if provided
            if category_id:
                law = db.query(Law).filter(Law.id == result["law_id"]).first()
                if law:
                    law.category_id = category_id
                    law.category_confidence = "high"
                    db.commit()

            # Look up suggested category from law_mappings (same logic as /import)
            if not category_id:
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
                        if doc_type and law_year:
                            for c in candidates:
                                if c.document_type == doc_type and c.law_year == law_year:
                                    mapping = c
                                    break
                        if not mapping and law_year:
                            for c in candidates:
                                if c.law_year == law_year:
                                    mapping = c
                                    break
                        if not mapping and doc_type:
                            matches = [c for c in candidates if c.document_type == doc_type]
                            if len(matches) == 1:
                                mapping = matches[0]
                if mapping:
                    result["suggested_category_id"] = mapping.category_id

            tq.put({"event": "complete", "data": result})
        except Exception as e:
            error = map_exception_to_error(e)
            tq.put({"event": "error", "data": error.to_dict()})

    async def event_generator():
        task = asyncio.create_task(run_import())
        try:
            while True:
                # Poll the thread-safe queue every 0.5s
                while tq.empty():
                    await asyncio.sleep(0.5)
                event = tq.get_nowait()
                event_type = event.get("event", "progress")
                data = event.get("data", event)
                logger.info(f"[SSE] Yielding event: {event_type}")
                yield {"event": event_type, "data": json.dumps(data) if isinstance(data, dict) else data}
                if event_type in ("complete", "error"):
                    break
        except asyncio.CancelledError:
            logger.info("[SSE] Client disconnected (CancelledError)")
        except Exception as e:
            logger.error(f"[SSE] Generator error: {e}")

    return EventSourceResponse(event_generator(), ping=15)


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
        raise SearchFailedError()

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

    return {
        "law_id": result["law_id"],
        "title": result.get("title", mapping.title),
    }


@router.post("/import-suggestion/{mapping_id}/stream")
async def import_suggestion_stream(
    mapping_id: int,
    req: ImportStreamRequest,
    db: Session = Depends(get_db),
):
    """SSE endpoint that streams import progress."""
    from app.services.search_service import advanced_search
    from app.services.leropa_service import import_law as do_import
    from app.errors import NoLawNumberError, DuplicateImportError, SearchFailedError, map_exception_to_error

    # Validate mapping
    mapping = db.query(LawMapping).filter(LawMapping.id == mapping_id).first()
    if not mapping:
        async def error_stream():
            yield {"event": "error", "data": json.dumps({"code": "not_found", "message": "Suggestion not found"})}
        return EventSourceResponse(error_stream())

    if not mapping.law_number:
        async def error_stream():
            yield {"event": "error", "data": json.dumps(NoLawNumberError().to_dict())}
        return EventSourceResponse(error_stream())

    # Check for duplicate
    existing_query = db.query(Law).filter(Law.law_number == mapping.law_number)
    if mapping.document_type:
        existing_query = existing_query.filter(Law.document_type == mapping.document_type)
    if mapping.law_year:
        existing_query = existing_query.filter(Law.law_year == mapping.law_year)
    existing = existing_query.first()
    if existing:
        async def error_stream():
            yield {"event": "error", "data": json.dumps(DuplicateImportError(existing.title).to_dict())}
        return EventSourceResponse(error_stream())

    # Search legislatie.just.ro
    doc_type_code = _DOC_TYPE_TO_SEARCH_CODE.get(mapping.document_type or "", "")
    year_str = str(mapping.law_year) if mapping.law_year else ""
    try:
        results = advanced_search(
            doc_type=doc_type_code,
            number=mapping.law_number,
            year=year_str,
        )
    except Exception as e:
        logger.error(f"Search failed for suggestion {mapping_id}: {e}")
        async def error_stream():
            yield {"event": "error", "data": json.dumps(SearchFailedError().to_dict())}
        return EventSourceResponse(error_stream())

    if not results:
        async def error_stream():
            yield {"event": "error", "data": json.dumps({"code": "not_found", "message": f"No results found on legislatie.just.ro for {mapping.title}"})}
        return EventSourceResponse(error_stream())

    ver_id = str(results[0].ver_id)

    # Check if version already imported
    existing_ver = db.query(LawVersion).filter(LawVersion.ver_id == ver_id).first()
    if existing_ver:
        async def error_stream():
            yield {"event": "error", "data": json.dumps(DuplicateImportError(existing_ver.law.title).to_dict())}
        return EventSourceResponse(error_stream())

    queue: asyncio.Queue = asyncio.Queue()

    def on_progress(event: dict):
        queue.put_nowait(event)

    async def run_import():
        try:
            result = await asyncio.to_thread(
                do_import, db, ver_id,
                import_history=req.import_history,
                on_progress=on_progress,
            )
            await queue.put({"event": "complete", "data": result})
        except Exception as e:
            error = map_exception_to_error(e)
            await queue.put({"event": "error", "data": error.to_dict()})

    async def event_generator():
        task = asyncio.create_task(run_import())
        try:
            while True:
                event = await queue.get()
                event_type = event.get("event", "progress")
                data = event.get("data", event)
                yield {"event": event_type, "data": json.dumps(data) if isinstance(data, dict) else data}
                if event_type in ("complete", "error"):
                    break
        except asyncio.CancelledError:
            pass  # Client disconnected; import continues in background

    return EventSourceResponse(event_generator())


class BulkImportRequest(BaseModel):
    import_history: bool = False


@router.post("/import-all-suggestions/stream")
async def import_all_suggestions_stream(req: BulkImportRequest, db: Session = Depends(get_db)):
    """Import all unimported suggested laws sequentially, streaming progress via SSE."""
    from app.services.search_service import advanced_search
    from app.services.leropa_service import import_law as do_import
    from app.services.category_service import get_unimported_suggestions

    import_history = req.import_history
    suggestions = get_unimported_suggestions(db)

    # Extract plain dicts before closing session — ORM objects detach after commit/rollback
    suggestion_data = [
        {
            "title": m.title,
            "law_number": m.law_number,
            "law_year": m.law_year,
            "document_type": m.document_type,
            "category_id": m.category_id,
        }
        for m in suggestions
    ]
    total = len(suggestion_data)
    db.close()  # Release the request session; we'll use fresh sessions per import

    if total == 0:
        async def empty_stream():
            yield {"event": "complete", "data": json.dumps({"imported": 0, "failed": 0, "total": 0})}
        return EventSourceResponse(empty_stream())

    queue: asyncio.Queue = asyncio.Queue()

    async def run_all():
        from app.database import SessionLocal

        imported = 0
        failed = 0
        for i, mapping in enumerate(suggestion_data):
            await queue.put({"event": "progress", "data": {
                "current": i + 1, "total": total,
                "title": mapping["title"], "status": "importing",
            }})

            if not mapping["law_number"]:
                failed += 1
                await queue.put({"event": "item_error", "data": {
                    "title": mapping["title"], "error": "No law number",
                }})
                continue

            max_retries = 2
            for attempt in range(max_retries + 1):
                import_db = SessionLocal()
                try:
                    # Check if already imported
                    existing_query = import_db.query(Law).filter(Law.law_number == mapping["law_number"])
                    if mapping["document_type"]:
                        existing_query = existing_query.filter(Law.document_type == mapping["document_type"])
                    if mapping["law_year"]:
                        existing_query = existing_query.filter(Law.law_year == mapping["law_year"])
                    if existing_query.first():
                        await queue.put({"event": "item_skip", "data": {
                            "title": mapping["title"], "reason": "Already imported",
                        }})
                        break

                    doc_type_code = _DOC_TYPE_TO_SEARCH_CODE.get(mapping["document_type"] or "", "")
                    year_str = str(mapping["law_year"]) if mapping["law_year"] else ""
                    results = advanced_search(
                        doc_type=doc_type_code,
                        number=mapping["law_number"],
                        year=year_str,
                    )
                    if not results:
                        failed += 1
                        await queue.put({"event": "item_error", "data": {
                            "title": mapping["title"], "error": "Not found on legislatie.just.ro",
                        }})
                        break

                    ver_id = str(results[0].ver_id)
                    existing_ver = import_db.query(LawVersion).filter(LawVersion.ver_id == ver_id).first()
                    if existing_ver:
                        await queue.put({"event": "item_skip", "data": {
                            "title": mapping["title"], "reason": "Version already imported",
                        }})
                        break

                    result = await asyncio.to_thread(do_import, import_db, ver_id, import_history=import_history)

                    # Auto-assign category
                    law = import_db.query(Law).filter(Law.id == result["law_id"]).first()
                    if law:
                        law.category_id = mapping["category_id"]
                        law.category_confidence = "high"
                        import_db.commit()

                    imported += 1
                    await queue.put({"event": "item_done", "data": {
                        "title": mapping["title"], "law_id": result["law_id"],
                    }})
                    break

                except Exception as e:
                    import_db.rollback()
                    is_db_locked = "database is locked" in str(e)
                    if is_db_locked and attempt < max_retries:
                        logger.warning(f"DB locked for {mapping['title']}, retrying ({attempt + 1}/{max_retries})...")
                        import_db.close()
                        await asyncio.sleep(5)
                        continue
                    failed += 1
                    logger.error(f"Bulk import failed for {mapping['title']}: {e}")
                    await queue.put({"event": "item_error", "data": {
                        "title": mapping["title"], "error": str(e)[:200],
                    }})
                    break
                finally:
                    import_db.close()

        await queue.put({"event": "complete", "data": {
            "imported": imported, "failed": failed, "total": total,
        }})

    async def event_generator():
        task = asyncio.create_task(run_all())
        try:
            while True:
                event = await queue.get()
                event_type = event["event"]
                data = event["data"]
                yield {"event": event_type, "data": json.dumps(data)}
                if event_type == "complete":
                    break
        except asyncio.CancelledError:
            pass

    return EventSourceResponse(event_generator())


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
    backfilled = backfill_diff_summaries(db)
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
def check_law_updates(law_id: int, db: Session = Depends(get_db)):
    """Refresh KnownVersion entries for a single law from legislatie.just.ro.

    Discovery only: writes/updates KnownVersion rows and re-derives
    LawVersion.is_current. Does NOT import any version text — that's the
    user's job via the Import buttons in the law-detail page.
    """
    from app.services.version_discovery import discover_versions_for_law

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    try:
        new_count = discover_versions_for_law(db, law)
    except Exception as e:
        logger.exception(f"Error checking updates for law {law_id}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Update check failed: {str(e)}")

    return {
        "discovered": new_count,
        "last_checked_at": str(law.last_checked_at) if law.last_checked_at else None,
    }


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


def _background_delete_law(law_id: int, title: str):
    """Run full law deletion in a background thread with its own DB session."""
    db = SessionLocal()
    try:
        # ChromaDB cleanup
        try:
            from app.services.chroma_service import remove_law_articles
            remove_law_articles(db, law_id)
        except Exception as e:
            logger.warning(f"ChromaDB cleanup failed (non-fatal): {e}")

        version_ids = [v.id for v in db.query(LawVersion.id).filter(LawVersion.law_id == law_id).all()]
        _bulk_delete_versions(db, version_ids)

        # KnownVersions
        db.query(KnownVersion).filter(KnownVersion.law_id == law_id).delete(synchronize_session=False)

        # The law itself
        db.query(Law).filter(Law.id == law_id).delete(synchronize_session=False)

        db.commit()
        logger.info(f"Background delete completed for law '{title}' (id={law_id})")
    except Exception:
        db.rollback()
        logger.exception(f"Background delete failed for law '{title}' (id={law_id})")
    finally:
        db.close()


def _background_delete_single_version(law_id: int, version_id: int):
    """Delete a single version in a background thread and recalculate is_current."""
    db = SessionLocal()
    try:
        _bulk_delete_versions(db, [version_id])
        _recalculate_current_version(db, law_id)
        db.commit()
        logger.info(f"Background delete of version id={version_id} completed for law_id={law_id}")
    except Exception:
        db.rollback()
        logger.exception(f"Background delete of version id={version_id} failed for law_id={law_id}")
    finally:
        db.close()


def _background_delete_old_versions(law_id: int, version_ids: list[int]):
    """Run old-version deletion in a background thread with its own DB session."""
    db = SessionLocal()
    try:
        _bulk_delete_versions(db, version_ids)
        db.commit()
        logger.info(f"Background delete of {len(version_ids)} old version(s) completed for law_id={law_id}")
    except Exception:
        db.rollback()
        logger.exception(f"Background delete of old versions failed for law_id={law_id}")
    finally:
        db.close()


@router.delete("/{law_id}")
async def delete_law(law_id: int, db: Session = Depends(get_db)):
    """Delete a law and all its versions (runs in background)."""
    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    title = law.title
    version_count = len(law.versions)

    # Fire off deletion in background thread so it survives client disconnect
    t = threading.Thread(target=_background_delete_law, args=(law_id, title), daemon=True)
    t.start()

    return {
        "message": f"Deleting '{title}' with {version_count} version(s)…",
    }


@router.delete("/{law_id}/versions/{version_id}")
async def delete_single_version(law_id: int, version_id: int, db: Session = Depends(get_db)):
    """Delete a single version of a law (runs in background).

    After deletion, is_current is recalculated: only the version whose ver_id
    matches the KnownVersion marked current by LegislatieJust gets is_current=True.
    If that version isn't imported, no imported version is marked current.
    """
    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    version = db.query(LawVersion).filter(
        LawVersion.id == version_id, LawVersion.law_id == law_id
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    ver_id = version.ver_id
    t = threading.Thread(
        target=_background_delete_single_version,
        args=(law_id, version_id),
        daemon=True,
    )
    t.start()

    return {
        "message": f"Deleting version '{ver_id}' of '{law.title}'…",
    }


@router.delete("/{law_id}/versions/old")
async def delete_old_versions(law_id: int, db: Session = Depends(get_db)):
    """Delete all non-current versions of a law (runs in background)."""
    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    old_versions = [v for v in law.versions if not v.is_current]
    if not old_versions:
        return {"message": "No old versions to delete", "deleted_count": 0}

    version_ids = [v.id for v in old_versions]
    count = len(version_ids)

    # Fire off deletion in background thread so it survives client disconnect
    t = threading.Thread(target=_background_delete_old_versions, args=(law_id, version_ids), daemon=True)
    t.start()

    return {
        "message": f"Deleting {count} old version(s) of '{law.title}'…",
        "deleted_count": count,
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

    version_a and version_b are LawVersion IDs.
    Returns a tree of article → paragraph → subparagraph diffs. Articles
    that are byte-for-byte unchanged are excluded.
    """
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

    articles_a = (
        db.query(Article)
        .filter(Article.law_version_id == version_a)
        .options(
            subqueryload(Article.paragraphs).subqueryload(Paragraph.subparagraphs)
        )
        .order_by(Article.order_index)
        .all()
    )
    articles_b = (
        db.query(Article)
        .filter(Article.law_version_id == version_b)
        .options(
            subqueryload(Article.paragraphs).subqueryload(Paragraph.subparagraphs)
        )
        .order_by(Article.order_index)
        .all()
    )

    changes = diff_articles(articles_a, articles_b)

    common = {a.article_number for a in articles_a} & {b.article_number for b in articles_b}
    summary = {
        "added": sum(1 for c in changes if c["change_type"] == "added"),
        "removed": sum(1 for c in changes if c["change_type"] == "removed"),
        "modified": sum(1 for c in changes if c["change_type"] == "modified"),
        "unchanged": (
            len(common) - sum(1 for c in changes if c["change_type"] == "modified")
        ),
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
