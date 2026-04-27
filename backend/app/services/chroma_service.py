from __future__ import annotations

import logging

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils import embedding_functions
from sqlalchemy.orm import Session

from app.config import (
    AICC_BASE_URL,
    AICC_KEY,
    CHROMA_PATH,
    CHROMA_COLLECTION,
    EMBEDDING_MODEL,
    EMBEDDING_MODEL_AICC,
    EMBEDDING_PROVIDER,
)
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


def get_collection_name() -> str:
    """Collection name varies by provider so old + new can coexist on disk."""
    if EMBEDDING_PROVIDER == "aicc":
        return f"{CHROMA_COLLECTION}_v2"
    return CHROMA_COLLECTION


def get_embedding_function():
    global _embedding_fn
    if _embedding_fn is not None:
        return _embedding_fn

    if EMBEDDING_PROVIDER == "local":
        _embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
        logger.info("Embedding provider: local (model=%s)", EMBEDDING_MODEL)
    elif EMBEDDING_PROVIDER == "aicc":
        from app.services.aicc_embedding import AiccEmbeddingFunction
        _embedding_fn = AiccEmbeddingFunction(
            api_key=AICC_KEY,
            base_url=AICC_BASE_URL,
            model=EMBEDDING_MODEL_AICC,
        )
        logger.info("Embedding provider: aicc (model=%s)", EMBEDDING_MODEL_AICC)
    else:
        raise ValueError(
            f"Unknown EMBEDDING_PROVIDER={EMBEDDING_PROVIDER!r}; expected 'local' or 'aicc'"
        )

    return _embedding_fn


def get_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=get_collection_name(),
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

        # Index only the consolidated article text — amendment metadata
        # is stored in DB metadata fields, not in the searchable document.
        doc_id = f"art-{article.id}"
        ids.append(doc_id)
        documents.append(article.full_text)
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
            "is_abrogated": str(getattr(article, 'is_abrogated', False)),
            "amendment_count": str(len(article.amendment_notes)) if article.amendment_notes else "0",
        })

    # Batch upsert (keep batches manageable)
    batch_size = 500
    for i in range(0, len(ids), batch_size):
        collection.upsert(
            ids=ids[i : i + batch_size],
            documents=documents[i : i + batch_size],
            metadatas=metadatas[i : i + batch_size],
        )

    # Index annexes
    from app.models.law import Annex as AnnexModel
    annexes = (
        db.query(AnnexModel).filter(AnnexModel.law_version_id == law_version_id).all()
    )
    anx_ids, anx_documents, anx_metadatas = [], [], []
    for annex in annexes:
        if not annex.full_text or not annex.full_text.strip():
            continue
        doc_id = f"anx-{annex.id}"
        anx_ids.append(doc_id)
        anx_documents.append(annex.full_text)
        anx_metadatas.append({
            "law_id": law.id,
            "law_version_id": version.id,
            "article_id": annex.id,
            "law_number": law.law_number,
            "law_year": str(law.law_year),
            "law_title": law.title[:200],
            "article_number": annex.title[:100],
            "date_in_force": str(version.date_in_force) if version.date_in_force else "",
            "is_current": str(version.is_current),
            "is_abrogated": "False",
            "amendment_count": "0",
            "doc_type": "annex",
            "annex_title": annex.title[:200],
        })

    for i in range(0, len(anx_ids), batch_size):
        collection.upsert(
            ids=anx_ids[i : i + batch_size],
            documents=anx_documents[i : i + batch_size],
            metadatas=anx_metadatas[i : i + batch_size],
        )

    logger.info(
        f"Indexed {len(ids)} articles + {len(anx_ids)} annexes for "
        f"{law.law_number}/{law.law_year} version {version.id}"
    )
    return len(ids) + len(anx_ids)


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
    """Remove all articles and annexes for a law from ChromaDB."""
    collection = get_collection()
    articles = (
        db.query(Article.id)
        .join(LawVersion)
        .filter(LawVersion.law_id == law_id)
        .all()
    )
    from app.models.law import Annex as AnnexModel
    annexes = (
        db.query(AnnexModel.id)
        .join(LawVersion)
        .filter(LawVersion.law_id == law_id)
        .all()
    )
    ids = [f"art-{a.id}" for a in articles] + [f"anx-{a.id}" for a in annexes]
    if ids:
        batch_size = 500
        for i in range(0, len(ids), batch_size):
            collection.delete(ids=ids[i : i + batch_size])
    logger.info(f"Removed {len(ids)} items from ChromaDB for law_id={law_id}")


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
                "is_abrogated": meta.get("is_abrogated", "False") == "True",
                "distance": results["distances"][0][i],
                "doc_type": meta.get("doc_type", "article"),
                "annex_title": meta.get("annex_title", ""),
            })

    return articles
