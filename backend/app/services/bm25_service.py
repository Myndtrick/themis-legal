# backend/app/services/bm25_service.py
"""
BM25 full-text search via SQLite FTS5.
Indexes article text + amendment notes for exact keyword matching.
"""
from __future__ import annotations
import logging
from sqlalchemy.orm import Session
from app.models.law import Article

logger = logging.getLogger(__name__)


def ensure_fts_index(db: Session):
    """Create the FTS5 virtual table if it doesn't exist, then populate."""
    conn = db.get_bind().raw_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='articles_fts'"
    )
    if cursor.fetchone():
        conn.close()
        return

    logger.info("Creating FTS5 index for articles...")

    cursor.execute("""
        CREATE VIRTUAL TABLE articles_fts USING fts5(
            article_text,
            law_version_id UNINDEXED,
            article_id UNINDEXED,
            tokenize='unicode61 remove_diacritics 2'
        )
    """)

    articles = db.query(Article).all()
    for art in articles:
        parts = [art.full_text or ""]
        for note in art.amendment_notes:
            if note.text:
                parts.append(note.text)
        combined = " ".join(parts)

        cursor.execute(
            "INSERT INTO articles_fts(rowid, article_text, law_version_id, article_id) VALUES (?, ?, ?, ?)",
            (art.id, combined, art.law_version_id, art.id),
        )

    conn.commit()
    conn.close()
    logger.info(f"FTS5 index created with {len(articles)} articles")


def rebuild_fts_index(db: Session):
    """Drop and recreate the FTS5 index."""
    conn = db.get_bind().raw_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS articles_fts")
    conn.commit()
    conn.close()
    ensure_fts_index(db)


def search_bm25(
    db: Session,
    query: str,
    law_version_ids: list[int] | None = None,
    limit: int = 15,
) -> list[dict]:
    """Search articles using BM25 ranking.
    FTS5 with remove_diacritics handles ă/â/î/ș/ț automatically.
    """
    import re
    words = re.findall(r"[a-zA-ZăîâșțĂÎÂȘȚ]{3,}", query)
    if not words:
        return []

    fts_query = " OR ".join(words)

    conn = db.get_bind().raw_connection()
    cursor = conn.cursor()

    try:
        if law_version_ids:
            placeholders = ",".join("?" * len(law_version_ids))
            sql = f"""
                SELECT article_id, law_version_id, rank
                FROM articles_fts
                WHERE articles_fts MATCH ?
                AND law_version_id IN ({placeholders})
                ORDER BY rank
                LIMIT ?
            """
            params = [fts_query] + law_version_ids + [limit]
        else:
            sql = """
                SELECT article_id, law_version_id, rank
                FROM articles_fts
                WHERE articles_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """
            params = [fts_query, limit]

        cursor.execute(sql, params)
        rows = cursor.fetchall()
    except Exception as e:
        logger.warning(f"FTS5 search failed: {e}")
        rows = []
    finally:
        conn.close()

    results = []
    for article_id, law_version_id, rank in rows:
        art = db.query(Article).filter(Article.id == article_id).first()
        if not art:
            continue
        law = art.law_version.law
        version = art.law_version

        text_parts = [art.full_text]
        for note in art.amendment_notes:
            if note.text and note.text.strip():
                text_parts.append(f"[Amendment: {note.text.strip()}]")

        results.append({
            "article_id": art.id,
            "law_number": law.law_number,
            "law_year": str(law.law_year),
            "law_title": law.title[:200],
            "article_number": art.article_number,
            "date_in_force": str(version.date_in_force) if version.date_in_force else "",
            "is_current": str(version.is_current),
            "text": "\n".join(text_parts),
            "bm25_rank": rank,
            "source": "bm25",
        })

    return results
