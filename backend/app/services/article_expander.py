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
) -> list[int]:
    """Expand a set of article IDs with neighbors and cross-references.
    Returns a deduplicated list of article IDs including the originals.
    """
    expanded = set(article_ids)

    for art_id in article_ids:
        article = db.query(Article).filter(Article.id == art_id).first()
        if not article:
            continue

        neighbors = _get_neighbors(db, article, neighbor_range)
        expanded.update(n.id for n in neighbors)

        xrefs = _extract_cross_references(db, article)
        expanded.update(xrefs)

    return list(expanded)


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
