# backend/app/services/article_expander.py
"""
Structural article expansion:
- Add neighbor articles from the same chapter (N-2 to N+2)
- Extract and fetch cross-referenced articles
"""
from __future__ import annotations
import re
import logging
from sqlalchemy.orm import Session
from app.models.law import Article

logger = logging.getLogger(__name__)


def expand_articles(
    db: Session,
    article_ids: list[int],
    neighbor_range: int = 2,
    selected_versions: dict | None = None,
    primary_date: str | None = None,
) -> tuple[list[int], dict]:
    """Expand a set of article IDs with neighbors and cross-references.
    Returns (deduplicated list of article IDs including originals, expansion_details).
    """
    expanded = set(article_ids)
    neighbors_added = 0
    crossrefs_added = 0
    expansion_triggers = []

    for art_id in article_ids:
        article = db.query(Article).filter(Article.id == art_id).first()
        if not article:
            continue

        neighbors = _get_neighbors(db, article, neighbor_range)
        new_neighbor_ids = [n.id for n in neighbors if n.id not in expanded]
        if new_neighbor_ids:
            expanded.update(new_neighbor_ids)
            neighbors_added += len(new_neighbor_ids)
            expansion_triggers.append({
                "source_article": article.article_number,
                "source_law": f"{article.law_version.law.law_number}/{article.law_version.law.law_year}" if article.law_version and article.law_version.law else "",
                "type": "neighbors",
                "added_count": len(new_neighbor_ids),
            })

        xrefs = _extract_cross_references(db, article)
        new_xref_ids = [xid for xid in xrefs if xid not in expanded]
        if new_xref_ids:
            expanded.update(new_xref_ids)
            crossrefs_added += len(new_xref_ids)
            expansion_triggers.append({
                "source_article": article.article_number,
                "source_law": f"{article.law_version.law.law_number}/{article.law_version.law.law_year}" if article.law_version and article.law_version.law else "",
                "type": "cross_reference",
                "added_count": len(new_xref_ids),
            })

        # Cross-law references (art. N din Codul Civil, etc.)
        cross_law_refs = _extract_cross_law_references(
            db, article, selected_versions or {}, primary_date
        )
        new_crosslaw = [r for r in cross_law_refs if r not in expanded]
        expanded.update(new_crosslaw)
        crossrefs_added += len(new_crosslaw)

    details = {
        "neighbors_added": neighbors_added,
        "crossrefs_added": crossrefs_added,
        "expansion_triggers": expansion_triggers,
    }

    return list(expanded), details


def _get_neighbors(
    db: Session,
    article: Article,
    range_: int = 2,
) -> list[Article]:
    """Get neighboring articles within the same structural section or law version."""
    if article.structural_element_id:
        return (
            db.query(Article)
            .filter(
                Article.law_version_id == article.law_version_id,
                Article.structural_element_id == article.structural_element_id,
                Article.order_index.between(
                    article.order_index - range_,
                    article.order_index + range_,
                ),
                Article.id != article.id,
            )
            .all()
        )
    else:
        return (
            db.query(Article)
            .filter(
                Article.law_version_id == article.law_version_id,
                Article.order_index.between(
                    article.order_index - range_,
                    article.order_index + range_,
                ),
                Article.id != article.id,
            )
            .all()
        )


def _extract_cross_references(
    db: Session,
    article: Article,
) -> list[int]:
    """Parse article text for cross-references and return referenced article IDs."""
    text = article.full_text or ""
    for note in article.amendment_notes:
        if note.text:
            text += " " + note.text

    article_ids = []

    # Pattern: "art. 123" or "art. 123^1" — same law
    for match in re.finditer(r"art\.\s*(\d+(?:\^\d+)?)", text, re.IGNORECASE):
        ref_number = match.group(1)
        ref_art = (
            db.query(Article)
            .filter(
                Article.law_version_id == article.law_version_id,
                Article.article_number == ref_number,
            )
            .first()
        )
        if ref_art:
            article_ids.append(ref_art.id)

    return article_ids


# ---------------------------------------------------------------------------
# Exception / exclusion retrieval
# ---------------------------------------------------------------------------

# Patterns that indicate an article creates an exception to another article
_EXCEPTION_PATTERNS_FORWARD = [
    r"cu\s+excep[tț]ia\s+(?:prevederilor\s+)?art\.\s*{art_num}",
    r"nu\s+se\s+aplic[aă]\s+(?:prevederile\s+)?art\.\s*{art_num}",
    r"prin\s+derogare\s+de\s+la\s+(?:prevederile\s+)?art\.\s*{art_num}",
    r"f[aă]r[aă]\s+a\s+aduce\s+atingere\s+(?:prevederilor\s+)?art\.\s*{art_num}",
    r"se\s+excepteaz[aă].*art\.\s*{art_num}",
]

# Keywords that indicate an article itself contains exception language
_EXCEPTION_KEYWORDS = [
    r"cu\s+excep[tț]ia",
    r"nu\s+se\s+aplic[aă]",
    r"prin\s+derogare",
    r"se\s+excepteaz[aă]",
    r"sunt\s+excluse",
]


def expand_with_exceptions(
    db: Session,
    articles: list[dict],
) -> tuple[list[int], dict]:
    """Find exception/exclusion articles related to the retrieved articles.

    Two-direction search:
    1. Forward: find other articles that create exceptions TO the retrieved articles
    2. Reverse: if a retrieved article contains exception language, fetch the articles it references

    Returns (list of new article IDs, exception_details).
    """
    existing_ids = {a["article_id"] for a in articles if "article_id" in a}
    exception_ids = set()
    forward_matches = []
    reverse_matches = []

    # Cache: law_version_id -> list of Article objects (avoid re-querying same version)
    _version_cache: dict[int, list[Article]] = {}

    for art in articles:
        art_id = art.get("article_id")
        art_number = art.get("article_number")
        law_version_id = art.get("law_version_id")

        if not art_number or not law_version_id:
            # Try to look up from DB
            if art_id:
                db_art = db.query(Article).filter(Article.id == art_id).first()
                if db_art:
                    art_number = art_number or db_art.article_number
                    law_version_id = law_version_id or db_art.law_version_id
            if not art_number or not law_version_id:
                continue

        # Forward search: find articles that reference this article in exception context
        escaped_num = re.escape(str(art_number))

        # Use cached articles for this law version
        if law_version_id not in _version_cache:
            _version_cache[law_version_id] = (
                db.query(Article)
                .filter(Article.law_version_id == law_version_id)
                .all()
            )
        all_articles_in_version = [
            a for a in _version_cache[law_version_id]
            if a.id not in existing_ids and a.id not in exception_ids
        ]

        for candidate in all_articles_in_version:
            candidate_text = (candidate.full_text or "").lower()
            for pattern in _EXCEPTION_PATTERNS_FORWARD:
                compiled = pattern.format(art_num=escaped_num)
                if re.search(compiled, candidate_text, re.IGNORECASE):
                    exception_ids.add(candidate.id)
                    forward_matches.append({
                        "found_article": candidate.article_number,
                        "references_article": str(art_number),
                        "pattern": pattern.split(r"\s+")[0],
                    })
                    logger.debug(
                        f"Exception article found: Art. {candidate.article_number} "
                        f"references Art. {art_number} in exception context"
                    )
                    break

        # Reverse search: if this article contains exception keywords,
        # extract referenced article numbers and fetch them
        art_text = (art.get("text") or "").lower()
        has_exception_language = any(
            re.search(kw, art_text, re.IGNORECASE)
            for kw in _EXCEPTION_KEYWORDS
        )

        if has_exception_language:
            # Extract all article references from this text
            for match in re.finditer(r"art\.\s*(\d+(?:\^\d+)?)", art_text, re.IGNORECASE):
                ref_number = match.group(1)
                if ref_number == str(art_number):
                    continue  # Skip self-reference
                ref_art = (
                    db.query(Article)
                    .filter(
                        Article.law_version_id == law_version_id,
                        Article.article_number == ref_number,
                    )
                    .first()
                )
                if ref_art and ref_art.id not in existing_ids and ref_art.id not in exception_ids:
                    exception_ids.add(ref_art.id)
                    reverse_matches.append({
                        "source_article": str(art_number),
                        "referenced_article": ref_number,
                    })
                    logger.debug(
                        f"Reverse exception: Art. {art_number} has exception language "
                        f"referencing Art. {ref_number}"
                    )

    if exception_ids:
        logger.info(f"Exception retrieval found {len(exception_ids)} additional articles")

    details = {
        "forward_matches": forward_matches,
        "reverse_matches": reverse_matches,
        "forward_count": len(forward_matches),
        "reverse_count": len(reverse_matches),
    }

    return list(exception_ids), details


def _extract_cross_law_references(
    db: Session,
    article: Article,
    selected_versions: dict,
    primary_date: str | None,
) -> list[int]:
    """Parse cross-references to articles in OTHER laws and resolve them."""
    from app.services.legal_aliases import CODE_ABBREVIATIONS
    from app.models.law import Law, LawVersion

    text = article.full_text or ""
    for note in article.amendment_notes:
        if note.text:
            text += " " + note.text

    article_ids = []

    # Pattern: "art. N din Legea nr. M/YYYY"
    for match in re.finditer(
        r"art\.\s*(\d+(?:\^\d+)?)\s+din\s+(?:Legea|legea)\s+(?:nr\.\s*)?(\d+)/(\d{4})",
        text, re.IGNORECASE
    ):
        ref_num, law_num, law_year = match.group(1), match.group(2), int(match.group(3))
        aid = _resolve_cross_law_article(db, ref_num, law_num, law_year, selected_versions, primary_date)
        if aid:
            article_ids.append(aid)

    # Pattern: "art. N C.civ." / "art. N Codul Civil" etc.
    for match in re.finditer(
        r"art\.\s*(\d+(?:\^\d+)?)\s+(?:din\s+)?([A-Za-zăîâșțĂÎÂȘȚ][A-Za-zăîâșțĂÎÂȘȚ\s.]+?)(?=[,;.\s\)\]]|$)",
        text, re.IGNORECASE
    ):
        ref_num = match.group(1)
        law_ref = match.group(2).strip().lower().rstrip(".")

        for abbrev, (law_num, law_year) in CODE_ABBREVIATIONS.items():
            if law_ref == abbrev or law_ref.startswith(abbrev):
                aid = _resolve_cross_law_article(
                    db, ref_num, law_num, law_year, selected_versions, primary_date
                )
                if aid:
                    article_ids.append(aid)
                break

    return article_ids


def _resolve_cross_law_article(
    db: Session,
    article_number: str,
    law_number: str,
    law_year: int,
    selected_versions: dict,
    primary_date: str | None,
) -> int | None:
    """Resolve a cross-law article reference to a specific article ID."""
    from app.models.law import Law, LawVersion

    version_key = f"{law_number}/{law_year}"
    version_info = selected_versions.get(version_key)

    if version_info:
        law_version_id = version_info["law_version_id"]
    else:
        law = (
            db.query(Law)
            .filter(Law.law_number == law_number, Law.law_year == law_year)
            .first()
        )
        if not law:
            return None

        version = None
        if primary_date:
            version = (
                db.query(LawVersion)
                .filter(LawVersion.law_id == law.id)
                .filter(LawVersion.date_in_force <= primary_date)
                .order_by(LawVersion.date_in_force.desc())
                .first()
            )

        if not version:
            version = (
                db.query(LawVersion)
                .filter(LawVersion.law_id == law.id, LawVersion.is_current == True)
                .first()
            )
        if not version:
            return None
        law_version_id = version.id

    ref_art = (
        db.query(Article)
        .filter(
            Article.law_version_id == law_version_id,
            Article.article_number == article_number,
        )
        .first()
    )
    return ref_art.id if ref_art else None
