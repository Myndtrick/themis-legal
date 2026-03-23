from __future__ import annotations

import logging

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils import embedding_functions
from sqlalchemy.orm import Session

from app.config import CHROMA_PATH, CHROMA_COLLECTION, EMBEDDING_MODEL
from app.models.law import Article, Law, LawVersion

logger = logging.getLogger(__name__)

_client: chromadb.PersistentClient | None = None
_embedding_fn = None


def get_chroma_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=CHROMA_PATH,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client


def get_embedding_function():
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
    return _embedding_fn


def get_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def index_law_version(db: Session, law_id: int, law_version_id: int) -> int:
    """Index all articles of a law version into ChromaDB. Returns count indexed."""
    collection = get_collection()
    law = db.query(Law).filter(Law.id == law_id).first()
    version = db.query(LawVersion).filter(LawVersion.id == law_version_id).first()
    if not law or not version:
        return 0

    articles = (
        db.query(Article).filter(Article.law_version_id == law_version_id).all()
    )

    if not articles:
        return 0

    ids, documents, metadatas = [], [], []
    for article in articles:
        if not article.full_text or not article.full_text.strip():
            continue

        # Build searchable text: article text + amendment notes
        # Amendment notes often contain critical information (e.g., new minimum
        # capital requirements) that isn't in the article text itself.
        text_parts = [article.full_text]
        if article.amendment_notes:
            for note in article.amendment_notes:
                if note.text and note.text.strip():
                    text_parts.append(f"[Amendment: {note.text.strip()}]")

        doc_id = f"art-{article.id}"
        ids.append(doc_id)
        documents.append("\n".join(text_parts))
        metadatas.append({
            "law_id": law.id,
            "law_version_id": version.id,
            "article_id": article.id,
            "law_number": law.law_number,
            "law_year": str(law.law_year),
            "law_title": law.title[:200],
            "article_number": article.article_number,
            "date_in_force": str(version.date_in_force) if version.date_in_force else "",
            "is_current": str(version.is_current),
        })

    # Batch upsert (keep batches manageable)
    batch_size = 500
    for i in range(0, len(ids), batch_size):
        collection.upsert(
            ids=ids[i : i + batch_size],
            documents=documents[i : i + batch_size],
            metadatas=metadatas[i : i + batch_size],
        )

    logger.info(
        f"Indexed {len(ids)} articles for {law.law_number}/{law.law_year} "
        f"version {version.id}"
    )
    return len(ids)


def index_all(db: Session) -> int:
    """Bulk index all articles in the database. Returns total count."""
    versions = db.query(LawVersion).all()
    total = 0
    for v in versions:
        count = index_law_version(db, v.law_id, v.id)
        total += count
    logger.info(f"Bulk indexing complete: {total} articles indexed")
    return total


def remove_law_articles(db: Session, law_id: int):
    """Remove all articles for a law from ChromaDB."""
    collection = get_collection()
    articles = (
        db.query(Article.id)
        .join(LawVersion)
        .filter(LawVersion.law_id == law_id)
        .all()
    )
    ids = [f"art-{a.id}" for a in articles]
    if ids:
        batch_size = 500
        for i in range(0, len(ids), batch_size):
            collection.delete(ids=ids[i : i + batch_size])
    logger.info(f"Removed {len(ids)} articles from ChromaDB for law_id={law_id}")


def query_articles(
    query_text: str,
    law_ids: list[int] | None = None,
    law_version_ids: list[int] | None = None,
    n_results: int = 20,
    db: Session | None = None,
) -> list[dict]:
    """Combined semantic + keyword search for relevant articles.

    Semantic search finds conceptually related articles.
    Keyword search catches short articles that semantic search misses
    (e.g., "numărul asociaților nu poate fi mai mare de 50").
    Results are merged and deduplicated.
    """
    # 1. Semantic search via ChromaDB
    collection = get_collection()

    where_filter = None
    if law_version_ids:
        if len(law_version_ids) == 1:
            where_filter = {"law_version_id": law_version_ids[0]}
        else:
            where_filter = {"law_version_id": {"$in": law_version_ids}}
    elif law_ids:
        if len(law_ids) == 1:
            where_filter = {"law_id": law_ids[0]}
        else:
            where_filter = {"law_id": {"$in": law_ids}}

    results = collection.query(
        query_texts=[query_text],
        n_results=n_results,
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )

    seen_ids = set()
    articles = []
    if results["ids"] and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            meta = results["metadatas"][0][i]
            aid = meta["article_id"]
            seen_ids.add(aid)
            articles.append({
                "article_id": aid,
                "law_number": meta["law_number"],
                "law_year": meta["law_year"],
                "law_title": meta.get("law_title", ""),
                "article_number": meta["article_number"],
                "date_in_force": meta.get("date_in_force", ""),
                "is_current": meta.get("is_current", ""),
                "text": results["documents"][0][i],
                "distance": results["distances"][0][i],
            })

    # 2. Keyword search via SQLite (catches short articles missed by embeddings)
    if db:
        keyword_results = _keyword_search(
            db, query_text, law_version_ids, law_ids, limit=15
        )
        for kr in keyword_results:
            if kr["article_id"] not in seen_ids:
                seen_ids.add(kr["article_id"])
                articles.append(kr)

    return articles


def _keyword_search(
    db: Session,
    query_text: str,
    law_version_ids: list[int] | None = None,
    law_ids: list[int] | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search articles by keyword matching in SQLite.

    Extracts meaningful terms from the query and finds articles containing them.
    Prioritizes articles matching multiple terms.
    """
    import re
    from sqlalchemy import func

    # Normalize Romanian diacritics for matching
    def _normalize(text: str) -> str:
        """Remove diacritics so 'asociati' matches 'asociați'."""
        replacements = {
            "ă": "a", "â": "a", "î": "i", "ș": "s", "ț": "t",
            "Ă": "A", "Â": "A", "Î": "I", "Ș": "S", "Ț": "T",
        }
        for src, dst in replacements.items():
            text = text.replace(src, dst)
        return text

    # Extract meaningful keywords (3+ chars, skip common Romanian stop words)
    stop_words = {
        "care", "sunt", "este", "din", "sau", "pentru", "prin", "poate",
        "avea", "fost", "fiind", "cel", "mai", "dar", "daca", "cum",
        "aceasta", "acest", "intre", "despre", "privind", "legea",
        "exista", "vreo", "ceea", "priveste", "unei", "unui",
    }
    words = re.findall(r"[a-zA-ZăîâșțĂÎÂȘȚ]{3,}", query_text.lower())
    keywords = [w for w in words if _normalize(w) not in stop_words]

    # Expand abbreviations to legal terms
    expansions = {
        "srl": ["raspundere", "limitata"],
        "sa": ["actiuni"],
        "nr": ["numar", "numarul"],
    }
    extra = []
    for kw in keywords:
        normalized_kw = _normalize(kw)
        if normalized_kw in expansions:
            extra.extend(expansions[normalized_kw])
    keywords.extend(extra)

    if not keywords:
        return []

    # Build query — find articles containing any keyword
    query = db.query(Article).join(LawVersion).join(Law)

    if law_version_ids:
        query = query.filter(LawVersion.id.in_(law_version_ids))
    elif law_ids:
        query = query.filter(Law.id.in_(law_ids))

    # SQLite LIKE search: find articles containing any keyword.
    # Use REPLACE to normalize diacritics in the database text for matching,
    # so "asociati" matches "asociați".
    from sqlalchemy import case, or_, literal_column

    def _normalize_col(col):
        """Apply diacritic normalization to a SQLAlchemy column for comparison."""
        result = func.lower(col)
        for dia, plain in [("ă", "a"), ("â", "a"), ("î", "i"), ("ș", "s"), ("ț", "t")]:
            result = func.replace(result, dia, plain)
        return result

    normalized_text = _normalize_col(Article.full_text)

    conditions = []
    for kw in keywords:
        kw_normalized = _normalize(kw.lower())
        conditions.append(normalized_text.contains(kw_normalized))

    if not conditions:
        return []

    # Score: count how many distinct keywords match
    match_count = sum(
        case((cond, 1), else_=0) for cond in conditions
    )

    # Two-tier scoring:
    # 1. Articles matching more keywords rank higher
    # 2. Among ties, shorter articles rank higher (short = focused rule,
    #    e.g., Art. 12 "max 50 asociați" is more relevant than a 500-word
    #    article about mergers that also mentions asociați)
    # Get matching articles, re-rank by relevance
    matching = (
        query.filter(or_(*conditions))
        .all()
    )

    # Score each article: keyword matches + rule-language boost - length penalty
    import re as _re

    scored = []
    for art in matching:
        lower = _normalize(art.full_text.lower())
        kw_matches = sum(1 for kw in set(keywords) if _normalize(kw) in lower)
        rule_boost = 0
        for term in ["cel putin", "nu poate fi mai mare", "nu poate depasi",
                     "maxim", "minim", "nu va putea"]:
            if term in lower:
                rule_boost += 5
        if _re.search(r"\d+", lower):
            rule_boost += 2
        # Heavier length penalty so short focused articles rank higher
        length_penalty = len(art.full_text) / 50
        score = kw_matches * 10 + rule_boost - length_penalty
        scored.append((score, art))

    scored.sort(key=lambda x: -x[0])
    matching = [art for _, art in scored[:limit]]

    results = []
    for art in matching:
        law = art.law_version.law
        version = art.law_version

        # Build text with amendment notes (same as indexing)
        text_parts = [art.full_text]
        if art.amendment_notes:
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
            "distance": 0.1,  # High relevance since it's a keyword match
        })

    return results
