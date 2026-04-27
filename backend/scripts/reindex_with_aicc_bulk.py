"""Bulk reindex through AICC — optimized for cutover.

Differs from reindex_with_aicc.py in two ways:
1. Loads ALL law versions + articles + annexes + amendment_notes in O(1)
   DB roundtrips using selectinload, avoiding the N+1 lazy-load that made
   the per-version path take ~60s/version on Railway's network volume.
2. Builds the full (ids, documents, metadatas) tuple in memory and does
   ONE batched Chroma upsert so the HNSW persistence overhead is amortized
   over thousands of documents instead of per-version.

Forces EMBEDDING_PROVIDER=aicc in this process. Idempotent — drops + rebuilds
the legal_articles_v2 collection from scratch.

Usage (from backend/, inside Railway container via railway ssh):
  PYTHONPATH=. uv run python scripts/reindex_with_aicc_bulk.py

Resilience: per-batch errors are caught + logged + counted; the script
continues. Exits non-zero with a count of failed batches at the end.
"""
from __future__ import annotations

import logging
import os
import sys

# MUST be set before importing app.* — app.config reads EMBEDDING_PROVIDER at
# module load time and chroma_service caches the resulting embedding function
# at module level. Setting it later has no effect inside this process.
os.environ["EMBEDDING_PROVIDER"] = "aicc"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("reindex-aicc-bulk")

# Chroma upsert batch size. AiccEmbeddingFunction further chunks into 128/call
# for Voyage. Larger batches here reduce HNSW persistence overhead but increase
# memory usage; 500 is the same value as the per-version script.
_UPSERT_BATCH_SIZE = 500

# How many LawVersion rows to load+process per chunk. Loading ALL versions at
# once OOMs the container at the 3 GB cap (article.full_text averages a few KB,
# 2300 versions x ~17 articles + amendment_notes => GBs of Python objects).
# 50 keeps peak memory bounded while still amortizing eager-load overhead.
_VERSION_CHUNK_SIZE = 50


def main() -> int:
    from sqlalchemy.orm import selectinload

    from app.database import SessionLocal
    # Register all SQLAlchemy models so cross-model relationships resolve.
    from app.models import (  # noqa: F401
        assistant,
        category,
        favorite,
        job as job_model,
        law,
        model_config,
        pipeline,
        prompt,
        scheduler_settings,
        user,
    )
    from app.models.law_check_log import LawCheckLog  # noqa: F401
    from app.models.scheduler_run_log import SchedulerRunLog  # noqa: F401
    from app.models.law import Annex, Article, Law, LawVersion
    from app.services.chroma_service import (
        get_chroma_client,
        get_collection_name,
        get_collection,
    )

    if os.environ.get("EMBEDDING_PROVIDER") != "aicc":
        logger.error("EMBEDDING_PROVIDER is not 'aicc' (got %r); aborting.",
                     os.environ.get("EMBEDDING_PROVIDER"))
        return 2

    client = get_chroma_client()
    name = get_collection_name()
    if name == "legal_articles":
        logger.error(
            "Refusing to operate on the local-provider collection 'legal_articles'."
        )
        return 2

    logger.info("Dropping existing collection if present: %s", name)
    try:
        client.delete_collection(name)
    except Exception as e:
        logger.info("(no existing collection to drop: %s)", e)

    logger.info("Creating fresh collection: %s", name)
    collection = get_collection()  # creates on first access

    # Helper: build (ids, documents, metadatas) for a chunk of versions.
    # Caller is responsible for the DB session lifecycle.
    def build_payload_for_versions(versions: list) -> tuple[list[str], list[str], list[dict], int, int]:
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []
        a_count = 0
        x_count = 0
        for v in versions:
            law = v.law
            if law is None:
                logger.warning("LawVersion id=%s has no parent law; skipping", v.id)
                continue

            for article in v.articles:
                if not article.full_text or not article.full_text.strip():
                    continue
                ids.append(f"art-{article.id}")
                documents.append(article.full_text)
                metadatas.append({
                    "law_id": law.id,
                    "law_version_id": v.id,
                    "article_id": article.id,
                    "law_number": law.law_number,
                    "law_year": str(law.law_year),
                    "law_title": law.title[:200] if law.title else "",
                    "article_number": article.article_number,
                    "date_in_force": str(v.date_in_force) if v.date_in_force else "",
                    "is_current": str(v.is_current),
                    "is_abrogated": str(getattr(article, "is_abrogated", False)),
                    "amendment_count": str(len(article.amendment_notes)) if article.amendment_notes else "0",
                })
                a_count += 1

            for annex in v.annexes:
                if not annex.full_text or not annex.full_text.strip():
                    continue
                ids.append(f"anx-{annex.id}")
                documents.append(annex.full_text)
                metadatas.append({
                    "law_id": law.id,
                    "law_version_id": v.id,
                    "article_id": annex.id,
                    "law_number": law.law_number,
                    "law_year": str(law.law_year),
                    "law_title": law.title[:200] if law.title else "",
                    "article_number": annex.title[:100] if annex.title else "",
                    "date_in_force": str(v.date_in_force) if v.date_in_force else "",
                    "is_current": str(v.is_current),
                    "is_abrogated": "False",
                    "amendment_count": "0",
                    "doc_type": "annex",
                    "annex_title": annex.title[:200] if annex.title else "",
                })
                x_count += 1

        return ids, documents, metadatas, a_count, x_count

    db = SessionLocal()
    failed_batches = 0
    total_articles = 0
    total_annexes = 0
    total_docs = 0
    try:
        # Get just the CURRENT version IDs first — small payload, gives us
        # chunkable units. Search only ever needs the current version per law;
        # historical versions are still in the DB but not in the vector index.
        # If a user explicitly searches a historical version, BM25 still works.
        all_version_ids = [
            row[0]
            for row in db.query(LawVersion.id)
            .filter(LawVersion.is_current.is_(True))
            .order_by(LawVersion.id)
            .all()
        ]
        total_versions = len(all_version_ids)
        logger.info(
            "Found %d CURRENT law versions; processing in chunks of %d.",
            total_versions, _VERSION_CHUNK_SIZE,
        )

        for chunk_start in range(0, total_versions, _VERSION_CHUNK_SIZE):
            chunk_ids = all_version_ids[chunk_start : chunk_start + _VERSION_CHUNK_SIZE]
            # Eager-load just this chunk. selectinload runs an IN(...) per
            # relationship — O(1) DB roundtrips for the whole chunk.
            chunk_versions = (
                db.query(LawVersion)
                .options(
                    selectinload(LawVersion.law),
                    selectinload(LawVersion.articles).selectinload(Article.amendment_notes),
                    selectinload(LawVersion.annexes),
                )
                .filter(LawVersion.id.in_(chunk_ids))
                .all()
            )

            ids, documents, metadatas, a_count, x_count = build_payload_for_versions(chunk_versions)
            total_articles += a_count
            total_annexes += x_count
            total_docs += len(ids)

            # Upsert this chunk's docs in batches of _UPSERT_BATCH_SIZE.
            for start in range(0, len(ids), _UPSERT_BATCH_SIZE):
                end = min(start + _UPSERT_BATCH_SIZE, len(ids))
                try:
                    collection.upsert(
                        ids=ids[start:end],
                        documents=documents[start:end],
                        metadatas=metadatas[start:end],
                    )
                except Exception as e:
                    logger.error(
                        "[reindex-aicc-bulk] upsert batch failed (chunk_start=%d, batch=%d-%d): %s",
                        chunk_start, start, end, e,
                    )
                    failed_batches += 1

            # Free memory: drop SQLAlchemy identity-map references and the local lists.
            db.expunge_all()
            del chunk_versions, ids, documents, metadatas

            chunk_end = min(chunk_start + _VERSION_CHUNK_SIZE, total_versions)
            logger.info(
                "  versions %d-%d / %d processed (%.0f%%); cumulative %d articles + %d annexes",
                chunk_start, chunk_end, total_versions,
                100.0 * chunk_end / total_versions,
                total_articles, total_annexes,
            )
    finally:
        db.close()

    logger.info(
        "Reindex finished: %d articles + %d annexes = %d docs into %s; %d batches failed",
        total_articles, total_annexes, total_docs, name, failed_batches,
    )
    if failed_batches:
        logger.error(
            "Some batches failed. Re-run the script (drops + rebuilds idempotently) "
            "or investigate AICC rate limits."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
