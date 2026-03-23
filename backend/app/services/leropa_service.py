"""Service layer for fetching and storing Romanian laws using leropa."""

import datetime
import logging
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.law import (
    AmendmentNote,
    Article,
    Law,
    LawVersion,
    Paragraph,
    StructuralElement,
    Subparagraph,
)
from app.models.notification import AuditLog, Notification

logger = logging.getLogger(__name__)

# Map leropa document kind codes to our enum
KIND_MAP = {
    "LEGE": "law",
    "COD": "code",
    "OG": "government_ordinance",
    "OUG": "government_ordinance",
    "HG": "government_resolution",
    "DECRET": "decree",
    "ORDIN": "order",
    "HOTARARE": "resolution",
    "REGULAMENT": "regulation",
    "PROCEDURA": "procedure",
    "NORMA": "norm",
    "DECIZIE": "decision",
}

STATE_MAP = {
    "A": "actual",
    "R": "republished",
    "M": "amended",
    "D": "deprecated",
}


def _parse_date(date_str: str | None) -> datetime.date | None:
    """Parse a DD.MM.YYYY date string into a date object."""
    if not date_str:
        return None
    try:
        parts = date_str.strip().split(".")
        if len(parts) == 3:
            return datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
    except (ValueError, IndexError):
        pass
    return None


def _date_from_list(date_list: list[int] | None) -> datetime.date | None:
    """Parse a [day, month, year] list into a date object."""
    if not date_list or len(date_list) < 3:
        return None
    try:
        return datetime.date(date_list[2], date_list[1], date_list[0])
    except (ValueError, IndexError):
        return None


def _extract_law_number_and_year(title: str) -> tuple[str, int]:
    """Try to extract law number and year from the document title.

    Titles look like:
    - 'LEGE nr. 129 din 11 iulie 2019'
    - 'Legea 31 din 16.11.1990'
    - 'CODUL CIVIL din 17 iulie 2009 (Legea nr. 287/2009)'
    - 'Ordinul 509 din 03.05.2023'
    """
    import re

    # Pattern 1: nr. NNN din ... YYYY or nr. NNN/YYYY
    match = re.search(r"nr\.\s*(\d+[^/\s]*)\s*(?:din\s+.*?(\d{4})|/(\d{4}))", title, re.IGNORECASE)
    if match:
        number = match.group(1).strip()
        year = int(match.group(2) or match.group(3))
        return number, year

    # Pattern 2: "Legea NNN din DD.MM.YYYY" or "Ordinul NNN din DD.MM.YYYY"
    match = re.search(r"(?:Legea|Ordinul|Norma|Hotărârea|Decizia|Codul)\s+(\d+)\s+din\s+\d{1,2}\.\d{1,2}\.(\d{4})", title, re.IGNORECASE)
    if match:
        return match.group(1), int(match.group(2))

    # Pattern 3: "Legea NNN din DD luna YYYY"
    match = re.search(r"(?:Legea|Ordinul|Norma|Hotărârea|Decizia)\s+(\d+)\s+din\s+.*?(\d{4})", title, re.IGNORECASE)
    if match:
        return match.group(1), int(match.group(2))

    # Fallback: just find a year in the title
    year_match = re.search(r"(\d{4})", title)
    year = int(year_match.group(1)) if year_match else 0

    return "unknown", year


def fetch_and_store_version(
    db: Session,
    ver_id: str,
    law: Law | None = None,
    rate_limit_delay: float = 0,
    override_date: datetime.date | None = None,
) -> tuple[Law, LawVersion]:
    """Fetch a single version of a law from legislatie.just.ro and store it.

    Returns the (Law, LawVersion) tuple.
    If `law` is None, creates a new Law record.
    `override_date` is the correct consolidation date from the history list.
    """
    from app.services.fetcher import fetch_document

    if rate_limit_delay > 0:
        time.sleep(rate_limit_delay)

    logger.info(f"Fetching document ver_id={ver_id}")
    result = fetch_document(ver_id)

    doc = result["document"]
    articles_data = result["articles"]
    books_data = result["books"]

    # Build article lookup by article_id
    article_lookup: dict[str, dict] = {}
    for art in articles_data:
        article_lookup[art["article_id"]] = art

    # Check if this version already exists
    existing = db.query(LawVersion).filter(LawVersion.ver_id == ver_id).first()
    if existing:
        logger.info(f"Version ver_id={ver_id} already exists, skipping")
        # Update date if we now have a better one
        if override_date and not existing.date_in_force:
            existing.date_in_force = override_date
        return existing.law, existing

    # Create Law record if needed
    if law is None:
        title = doc.get("title") or f"Document {ver_id}"
        law_number, law_year = _extract_law_number_and_year(title)

        law = Law(
            title=title,
            law_number=law_number,
            law_year=law_year,
            document_type=KIND_MAP.get(doc.get("kind", ""), "other"),
            description=doc.get("description"),
            keywords=doc.get("keywords"),
            issuer=", ".join(doc.get("issuer") or []) or None,
            source_url=doc.get("source"),
        )
        db.add(law)
        db.flush()  # Get the ID

    # Use override_date (from history list) if provided; otherwise fall back
    # to the document date (which is typically the law's original date, not
    # the consolidation date — so override_date is strongly preferred).
    version_date = override_date
    state = STATE_MAP.get(doc.get("state", ""), "actual")

    # Create LawVersion
    version = LawVersion(
        law_id=law.id,
        ver_id=ver_id,
        date_in_force=version_date,
        state=state,
        is_current=False,  # Caller will set the current version
    )
    db.add(version)
    db.flush()

    # Store structural hierarchy and articles
    _store_hierarchy(db, version, books_data, article_lookup)

    # Store articles that aren't under any structural element
    _store_orphan_articles(db, version, articles_data, books_data)

    db.flush()
    return law, version


def _store_hierarchy(
    db: Session,
    version: LawVersion,
    books_data: list[dict],
    article_lookup: dict[str, dict],
) -> None:
    """Store the book → title → chapter → section hierarchy."""
    for book_idx, book in enumerate(books_data):
        # Skip default placeholder books if they have no meaningful content
        is_default = book.get("book_id", "").startswith("default")

        book_el = None
        if not is_default:
            book_el = StructuralElement(
                law_version_id=version.id,
                element_type="book",
                number=None,
                title=book.get("title"),
                description=book.get("description"),
                order_index=book_idx,
            )
            db.add(book_el)
            db.flush()

        # Store articles directly under book
        _store_articles_by_ids(
            db, version, book.get("articles", []),
            article_lookup, book_el,
        )

        # Titles
        for title_idx, title_data in enumerate(book.get("titles", [])):
            is_default_title = title_data.get("title_id", "").startswith("default")
            title_el = None
            if not is_default_title:
                title_el = StructuralElement(
                    law_version_id=version.id,
                    parent_id=book_el.id if book_el else None,
                    element_type="title",
                    number=None,
                    title=title_data.get("title"),
                    description=title_data.get("description"),
                    order_index=title_idx,
                )
                db.add(title_el)
                db.flush()

            _store_articles_by_ids(
                db, version, title_data.get("articles", []),
                article_lookup, title_el or book_el,
            )

            # Chapters under title
            _store_chapters(
                db, version, title_data.get("chapters", []),
                article_lookup, title_el or book_el,
            )

            # Sections directly under title (no chapter)
            _store_sections(
                db, version, title_data.get("sections", []),
                article_lookup, title_el or book_el,
            )

        # Chapters directly under book (no title)
        _store_chapters(
            db, version, book.get("chapters", []),
            article_lookup, book_el,
        )

        # Sections directly under book
        _store_sections(
            db, version, book.get("sections", []),
            article_lookup, book_el,
        )


def _store_chapters(
    db: Session,
    version: LawVersion,
    chapters: list[dict],
    article_lookup: dict[str, dict],
    parent: StructuralElement | None,
) -> None:
    for ch_idx, ch in enumerate(chapters):
        is_default = ch.get("chapter_id", "").startswith("default")
        ch_el = None
        if not is_default:
            ch_el = StructuralElement(
                law_version_id=version.id,
                parent_id=parent.id if parent else None,
                element_type="chapter",
                number=None,
                title=ch.get("title"),
                description=ch.get("description"),
                order_index=ch_idx,
            )
            db.add(ch_el)
            db.flush()

        _store_articles_by_ids(
            db, version, ch.get("articles", []),
            article_lookup, ch_el or parent,
        )

        _store_sections(
            db, version, ch.get("sections", []),
            article_lookup, ch_el or parent,
        )


def _store_sections(
    db: Session,
    version: LawVersion,
    sections: list[dict],
    article_lookup: dict[str, dict],
    parent: StructuralElement | None,
) -> None:
    for sec_idx, sec in enumerate(sections):
        sec_el = StructuralElement(
            law_version_id=version.id,
            parent_id=parent.id if parent else None,
            element_type="section",
            number=None,
            title=sec.get("title"),
            description=sec.get("description"),
            order_index=sec_idx,
        )
        db.add(sec_el)
        db.flush()

        _store_articles_by_ids(
            db, version, sec.get("articles", []),
            article_lookup, sec_el,
        )

        # Subsections (nested sections)
        _store_sections(
            db, version, sec.get("subsections", []),
            article_lookup, sec_el,
        )


# Track which article IDs have been stored to avoid duplicates
_stored_article_ids: set[str] = set()


def _store_articles_by_ids(
    db: Session,
    version: LawVersion,
    article_ids: list[str],
    article_lookup: dict[str, dict],
    parent: StructuralElement | None,
) -> None:
    """Store articles referenced by their IDs from a structural element."""
    for idx, art_id in enumerate(article_ids):
        art_data = article_lookup.get(art_id)
        if not art_data:
            continue

        # Use a version-scoped key to track stored articles
        key = f"{version.id}:{art_id}"
        if key in _stored_article_ids:
            continue
        _stored_article_ids.add(key)

        _store_single_article(db, version, art_data, parent, idx)


def _store_orphan_articles(
    db: Session,
    version: LawVersion,
    all_articles: list[dict],
    books_data: list[dict],
) -> None:
    """Store articles that aren't referenced in any structural element."""
    # Collect all article IDs referenced in the hierarchy
    referenced = set()
    _collect_referenced_ids(books_data, referenced)

    for idx, art_data in enumerate(all_articles):
        art_id = art_data["article_id"]
        key = f"{version.id}:{art_id}"
        if key in _stored_article_ids:
            continue
        if art_id in referenced:
            continue
        _stored_article_ids.add(key)
        _store_single_article(db, version, art_data, None, idx)


def _collect_referenced_ids(nodes: list[dict], result: set) -> None:
    """Recursively collect all article IDs from hierarchical nodes."""
    for node in nodes:
        for art_id in node.get("articles", []):
            result.add(art_id)
        for child_key in ("titles", "chapters", "sections", "subsections"):
            _collect_referenced_ids(node.get(child_key, []), result)


def _store_single_article(
    db: Session,
    version: LawVersion,
    art_data: dict,
    parent: StructuralElement | None,
    order_index: int,
) -> None:
    article = Article(
        law_version_id=version.id,
        structural_element_id=parent.id if parent else None,
        article_number=art_data.get("label", "?"),
        label=art_data.get("label"),
        full_text=art_data.get("full_text", ""),
        order_index=order_index,
    )
    db.add(article)
    db.flush()

    # Paragraphs
    for p_idx, par in enumerate(art_data.get("paragraphs", [])):
        paragraph = Paragraph(
            article_id=article.id,
            paragraph_number=par.get("label") or str(p_idx + 1),
            label=par.get("label"),
            text=par.get("text", ""),
            order_index=p_idx,
        )
        db.add(paragraph)
        db.flush()

        # Subparagraphs
        for sp_idx, sub in enumerate(par.get("subparagraphs", [])):
            subparagraph = Subparagraph(
                paragraph_id=paragraph.id,
                label=sub.get("label"),
                text=sub.get("text", ""),
                order_index=sp_idx,
            )
            db.add(subparagraph)

    # Amendment notes
    for note in art_data.get("notes", []):
        amendment = AmendmentNote(
            article_id=article.id,
            text=note.get("text"),
            date=note.get("date"),
            subject=note.get("subject"),
            law_number=note.get("law_number"),
            law_date=note.get("law_date"),
            monitor_number=note.get("monitor_number"),
            monitor_date=note.get("monitor_date"),
            original_text=note.get("replaced"),
            replacement_text=note.get("replacement"),
        )
        db.add(amendment)


def import_law(
    db: Session,
    ver_id: str,
    import_history: bool = True,
    rate_limit_delay: float = 2.0,
) -> dict:
    """Import a law and optionally all its historical versions.

    This is the main entry point for importing a law.
    Returns a summary dict.
    """
    global _stored_article_ids
    _stored_article_ids = set()

    logger.info(f"Starting import for ver_id={ver_id}")

    # First, fetch the document to get metadata and the full history list
    from app.services.fetcher import fetch_document
    result = fetch_document(ver_id)
    doc = result["document"]
    history = doc.get("history", [])

    # Build a date lookup from the history list: ver_id -> consolidation date
    # The history list contains the dates for all OTHER versions.
    # The version we're looking at (ver_id) is NOT in its own history list.
    date_lookup: dict[str, datetime.date | None] = {}
    for entry in history:
        date_lookup[entry["ver_id"]] = _parse_date(entry.get("date"))

    # For the requested ver_id itself, we need to find its date.
    # Strategy: fetch ANY other version's history to find our ver_id's date.
    # If history is empty, fall back to the document date.
    if history:
        # Fetch the first historical version to get its history list,
        # which should include our ver_id with the correct date.
        other_ver_id = history[0]["ver_id"]
        try:
            other_result = fetch_document(other_ver_id)
            other_history = other_result["document"].get("history", [])
            for entry in other_history:
                if entry["ver_id"] == ver_id:
                    date_lookup[ver_id] = _parse_date(entry.get("date"))
                    break
                # Also fill in any dates we might be missing
                if entry["ver_id"] not in date_lookup:
                    date_lookup[entry["ver_id"]] = _parse_date(entry.get("date"))
        except Exception as e:
            logger.warning(f"Could not fetch cross-reference for date of {ver_id}: {e}")

    # Fallback for the requested ver_id if we still don't have its date
    if ver_id not in date_lookup or date_lookup[ver_id] is None:
        date_lookup[ver_id] = _date_from_list(doc.get("date"))

    # Now import the requested version with the correct date
    law, main_version = fetch_and_store_version(
        db, ver_id, override_date=date_lookup.get(ver_id)
    )

    versions_imported = [ver_id]

    # Import historical versions
    if import_history and history:
        logger.info(f"Found {len(history)} historical versions to import")
        for entry in history:
            hist_ver_id = entry.get("ver_id")
            if not hist_ver_id or hist_ver_id == ver_id:
                continue

            hist_date = date_lookup.get(hist_ver_id) or _parse_date(entry.get("date"))

            try:
                _stored_article_ids = set()  # Reset for each version
                _, hist_version = fetch_and_store_version(
                    db, hist_ver_id, law=law,
                    rate_limit_delay=rate_limit_delay,
                    override_date=hist_date,
                )
                versions_imported.append(hist_ver_id)
                logger.info(
                    f"Imported version {hist_ver_id} "
                    f"(date={hist_date}, {len(versions_imported)}/{len(history)+1})"
                )
            except Exception as e:
                logger.error(f"Failed to import version {hist_ver_id}: {e}")
                # Don't let one failed version stop the rest
                continue

    # Determine which version is current (the one with the latest date)
    all_versions = db.query(LawVersion).filter(LawVersion.law_id == law.id).all()
    if all_versions:
        dated = [(v, v.date_in_force) for v in all_versions if v.date_in_force]
        if dated:
            dated.sort(key=lambda x: x[1], reverse=True)
            for v in all_versions:
                v.is_current = False
            dated[0][0].is_current = True
        else:
            for v in all_versions:
                v.is_current = v.ver_id == ver_id

    # Create notification
    notification = Notification(
        title=f"Law imported: {law.title}",
        message=f"Imported {len(versions_imported)} version(s) of Legea {law.law_number}/{law.law_year}",
        notification_type="law_update",
    )
    db.add(notification)

    # Audit log
    audit = AuditLog(
        action="import_law",
        module="legal_library",
        details=f"Imported {law.title} with {len(versions_imported)} versions",
    )
    db.add(audit)

    db.commit()

    _stored_article_ids = set()

    return {
        "law_id": law.id,
        "title": law.title,
        "law_number": law.law_number,
        "law_year": law.law_year,
        "versions_imported": len(versions_imported),
        "version_ids": versions_imported,
    }
