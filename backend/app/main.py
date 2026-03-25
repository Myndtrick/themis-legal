import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.models import assistant, pipeline, prompt, category  # noqa: F401 — register models
from app.routers import assistant as assistant_router
from app.routers import categories, laws, notifications
from app.routers import settings_categories, settings_pipeline, settings_prompts
from app.scheduler import scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_update_check():
    """Scheduled job: check all laws for new versions."""
    from app.services.update_checker import check_for_updates

    logger.info("Running scheduled law update check...")
    results = check_for_updates()
    logger.info(
        f"Update check complete: {results['checked']} checked, "
        f"{results['updated']} updated, {results['errors']} errors"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create data directories and database tables on startup
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/chroma", exist_ok=True)
    Base.metadata.create_all(bind=engine)

    # Seed default prompts for the Legal Assistant pipeline
    from app.database import SessionLocal
    from app.services.prompt_service import seed_defaults

    db = SessionLocal()
    try:
        seed_defaults(db)
        from app.services.category_service import seed_categories, backfill_law_mapping_fields
        seed_categories(db)
        backfill_law_mapping_fields(db)
        from app.services.bm25_service import ensure_fts_index
        ensure_fts_index(db)
    finally:
        db.close()

    # Schedule daily update check at 3:00 AM
    scheduler.add_job(
        run_update_check,
        "cron",
        hour=3,
        minute=0,
        id="daily_law_update",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — daily law update check at 03:00")

    yield

    scheduler.shutdown()
    logger.info("Scheduler stopped")


app = FastAPI(
    title="Themis L&C API",
    description="Legal & Compliance AI",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(categories.router)
app.include_router(laws.router)
app.include_router(notifications.router)
app.include_router(assistant_router.router)
app.include_router(settings_prompts.router)
app.include_router(settings_pipeline.router)
app.include_router(settings_categories.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/admin/check-updates")
def trigger_update_check():
    """Manually trigger an update check for all stored laws."""
    from app.services.update_checker import check_for_updates

    results = check_for_updates()
    return results


@app.post("/api/admin/index-chroma")
def index_chroma():
    """Bulk index all articles into ChromaDB. Run once after Phase 1 data exists."""
    from app.database import SessionLocal
    from app.services.chroma_service import index_all

    db = SessionLocal()
    try:
        count = index_all(db)
        return {"indexed": count}
    finally:
        db.close()
