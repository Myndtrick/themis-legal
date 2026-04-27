"""One-shot reindex: drop and rebuild the Chroma collection used when
EMBEDDING_PROVIDER=aicc.

Forces EMBEDDING_PROVIDER=aicc in this process regardless of the actual env,
so the operator can run it before flipping the prod env var. Connects to the
production DB + AICC and rebuilds legal_articles_v2 from scratch.

Usage (from backend/):
  AICC_KEY=sk-cc-... \\
  AICC_BASE_URL=https://aicommandcenter-production-d7b1.up.railway.app/v1 \\
  EMBEDDING_MODEL_AICC=voyage-3 \\
  PYTHONPATH=. uv run python scripts/reindex_with_aicc.py

Idempotent: run again, it drops and rebuilds.

Resilience: per-version exceptions are caught, logged, and the run continues.
At the end, exits non-zero with a list of failed version IDs so the operator
can retry just those (re-running the whole script is also safe — it drops
and rebuilds from scratch).
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
logger = logging.getLogger("reindex-aicc")


def main() -> int:
    from app.database import SessionLocal
    from app.models.law import LawVersion
    from app.services.chroma_service import (
        get_chroma_client,
        get_collection_name,
        get_collection,
        index_law_version,
    )

    # Defense-in-depth: even though we forced EMBEDDING_PROVIDER above, verify
    # both the env and the resolved collection name agree before doing
    # destructive work. Belt + suspenders.
    if os.environ.get("EMBEDDING_PROVIDER") != "aicc":
        logger.error("EMBEDDING_PROVIDER is not 'aicc' (got %r); aborting.",
                     os.environ.get("EMBEDDING_PROVIDER"))
        return 2

    client = get_chroma_client()
    name = get_collection_name()
    if name == "legal_articles":
        logger.error(
            "Refusing to operate on the local-provider collection 'legal_articles'."
            " Check chroma_service.get_collection_name() — it should return"
            " 'legal_articles_v2' when EMBEDDING_PROVIDER=aicc."
        )
        return 2

    logger.info("Dropping existing collection if present: %s", name)
    try:
        client.delete_collection(name)
    except Exception as e:
        # Already absent — fine.
        logger.info("(no existing collection to drop: %s)", e)

    logger.info("Creating fresh collection: %s", name)
    get_collection()  # creates on first access

    db = SessionLocal()
    total = 0
    failed_version_ids: list[int] = []
    try:
        versions = db.query(LawVersion).all()
        logger.info("Re-indexing %d law versions through AICC...", len(versions))
        for i, v in enumerate(versions, start=1):
            try:
                count = index_law_version(db, v.law_id, v.id)
                total += count
            except Exception as e:
                logger.error(
                    "[reindex-aicc] version_id=%s law_id=%s failed: %s",
                    v.id, v.law_id, e,
                )
                failed_version_ids.append(v.id)
                # Continue — better to ship a partial index than abort the run.
            if i % 10 == 0:
                logger.info(
                    "  ...%d/%d versions processed, %d docs indexed, %d failed so far",
                    i, len(versions), total, len(failed_version_ids),
                )
    finally:
        db.close()

    logger.info(
        "Reindex finished: %d documents indexed into %s; %d versions failed",
        total, name, len(failed_version_ids),
    )
    if failed_version_ids:
        logger.error(
            "Failed version IDs (retry by re-running this script — drop+rebuild is idempotent): %s",
            failed_version_ids,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
