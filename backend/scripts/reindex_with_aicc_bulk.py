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

    db = SessionLocal()
    try:
        # ONE big query that eager-loads everything we need. selectinload
        # avoids N+1: it does one IN(...) query per relationship, so the
        # whole graph loads in O(num_relationships) roundtrips, not O(N).
        logger.info("Loading all law versions with eager-loaded children...")
        versions = (
            db.query(LawVersion)
            .options(
                selectinload(LawVersion.law),
                selectinload(LawVersion.articles).selectinload(Article.amendment_notes),
                selectinload(LawVersion.annexes),
            )
            .all()
        )
        logger.info("Loaded %d law versions.", len(versions))

        # Build full document lists in memory (small — ~12K articles + a few annexes).
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []
        article_count = 0
        annex_count = 0

        for v in versions:
            law = v.law  # eager-loaded, no DB roundtrip
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
                article_count += 1

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
                annex_count += 1
    finally:
        db.close()

    total = len(ids)
    logger.info(
        "Built in-memory payload: %d articles + %d annexes = %d total documents",
        article_count, annex_count, total,
    )

    # Batch upsert — Chroma will call our AiccEmbeddingFunction once per
    # upsert call, which then auto-chunks into 128/call for Voyage.
    failed_batches = 0
    for start in range(0, total, _UPSERT_BATCH_SIZE):
        end = min(start + _UPSERT_BATCH_SIZE, total)
        try:
            collection.upsert(
                ids=ids[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )
            logger.info(
                "  upsert batch %d-%d / %d (%.0f%%)",
                start, end, total, 100.0 * end / total,
            )
        except Exception as e:
            logger.error(
                "[reindex-aicc-bulk] batch %d-%d failed: %s",
                start, end, e,
            )
            failed_batches += 1
            # Continue — better to ship a partial index than abort.

    logger.info(
        "Reindex finished: %d documents into %s; %d batches failed",
        total, name, failed_batches,
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
