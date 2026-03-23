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
) -> list[dict]:
    """Semantic search for relevant articles via ChromaDB embeddings."""
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

    articles = []
    if results["ids"] and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            meta = results["metadatas"][0][i]
            articles.append({
                "article_id": meta["article_id"],
                "law_number": meta["law_number"],
                "law_year": meta["law_year"],
                "law_title": meta.get("law_title", ""),
                "article_number": meta["article_number"],
                "date_in_force": meta.get("date_in_force", ""),
                "is_current": meta.get("is_current", ""),
                "text": results["documents"][0][i],
                "distance": results["distances"][0][i],
            })

    return articles
