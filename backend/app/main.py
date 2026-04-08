import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import Base, engine
from app.models import assistant, pipeline, prompt, category, user, favorite, law  # noqa: F401 — register models
from app.models import model_config  # noqa: F401 — register model config tables
from app.models import scheduler_settings  # noqa: F401 — register scheduler_settings table
from app.models import job as job_model  # noqa: F401 — register jobs table
from app.models.scheduler_run_log import SchedulerRunLog  # noqa: F401 — register scheduler_run_logs table
from app.models.law_check_log import LawCheckLog  # noqa: F401 — register law_check_logs table
from app.routers import assistant as assistant_router
from app.routers import categories, jobs as jobs_router, law_mappings, laws, notifications
from app.routers import settings_categories, settings_pipeline, settings_prompts
from app.routers import settings_models
from app.routers import compare
from app.routers import admin as admin_router
from app.routers import settings_schedulers
from app.scheduler import scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_update_check():
    """Scheduled job: discover new versions for all laws (metadata only)."""
    import datetime as _dt
    from app.services.version_discovery import run_daily_discovery
    from app.database import SessionLocal
    from app.models.scheduler_settings import SchedulerSetting

    logger.info("Running scheduled version discovery...")
    results = run_daily_discovery()
    logger.info(
        f"Version discovery complete: {results['checked']} checked, "
        f"{results['discovered']} new versions discovered, {results['errors']} errors"
    )

    db = SessionLocal()
    try:
        setting = db.query(SchedulerSetting).filter(SchedulerSetting.id == "ro").first()
        if setting:
            setting.last_run_at = _dt.datetime.now(_dt.timezone.utc)
            setting.last_run_status = "ok" if results.get("errors", 0) == 0 else "error"
            setting.last_run_summary = results
            db.commit()
        from app.services.scheduler_log_service import record_run
        record_run(db, "ro", results, "scheduled")
    finally:
        db.close()


def run_eu_update_check():
    """Scheduled job: discover new consolidated versions for all EU laws."""
    import datetime as _dt
    from app.services.eu_version_discovery import run_eu_weekly_discovery
    from app.database import SessionLocal
    from app.models.scheduler_settings import SchedulerSetting

    logger.info("Running scheduled EU version discovery...")
    results = run_eu_weekly_discovery()
    logger.info(f"EU discovery complete: {results}")

    db = SessionLocal()
    try:
        setting = db.query(SchedulerSetting).filter(SchedulerSetting.id == "eu").first()
        if setting:
            setting.last_run_at = _dt.datetime.now(_dt.timezone.utc)
            setting.last_run_status = "ok" if results.get("errors", 0) == 0 else "error"
            setting.last_run_summary = results
            db.commit()
        from app.services.scheduler_log_service import record_run
        record_run(db, "eu", results, "scheduled")
    finally:
        db.close()


def _add_column_if_missing(db: Session, table: str, column: str, col_type: str, default: str | None = None):
    """Add a column to a table if it doesn't exist. Safe for repeated runs."""
    from sqlalchemy import text, inspect as sa_inspect
    inspector = sa_inspect(engine)
    existing = [c["name"] for c in inspector.get_columns(table)]
    if column not in existing:
        default_clause = f" DEFAULT {default}" if default is not None else ""
        db.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}"))
        db.commit()
        logger.info(f"Added column {table}.{column}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create data directories and database tables on startup
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/chroma", exist_ok=True)
    Base.metadata.create_all(bind=engine)

    # Seed default prompts for the Legal Assistant pipeline
    from app.database import SessionLocal
    from app.services.prompt_service import seed_defaults, sync_prompts_from_files

    db = SessionLocal()
    try:
        # Additive migration: EU integration columns
        _add_column_if_missing(db, "laws", "source", "VARCHAR(10)", "'ro'")
        _add_column_if_missing(db, "laws", "celex_number", "VARCHAR(50)", None)
        _add_column_if_missing(db, "laws", "cellar_uri", "VARCHAR(200)", None)
        _add_column_if_missing(db, "law_versions", "language", "VARCHAR(10)", "'ro'")
        _add_column_if_missing(db, "known_versions", "language", "VARCHAR(10)", "'ro'")
        _add_column_if_missing(db, "law_mappings", "celex_number", "VARCHAR(50)", None)
        _add_column_if_missing(db, "law_mappings", "source_url", "TEXT", None)
        _add_column_if_missing(db, "law_mappings", "source_ver_id", "VARCHAR(50)", None)
        _add_column_if_missing(db, "law_mappings", "deleted_at", "DATETIME", None)

        # Paragraph-notes migration (Spec 1: 2026-04-08-paragraph-notes-and-backfill)
        _add_column_if_missing(db, "amendment_notes", "paragraph_id", "INTEGER", None)
        _add_column_if_missing(db, "amendment_notes", "note_source_id", "VARCHAR(200)", None)
        _add_column_if_missing(db, "articles", "text_clean", "TEXT", None)
        _add_column_if_missing(db, "paragraphs", "text_clean", "TEXT", None)
        db.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_amendment_notes_paragraph_id "
            "ON amendment_notes(paragraph_id)"
        ))
        db.execute(text("DROP INDEX IF EXISTS ux_amendment_notes_dedupe"))
        db.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_amendment_notes_dedupe "
            "ON amendment_notes(article_id, COALESCE(paragraph_id, 0), note_source_id) "
            "WHERE note_source_id IS NOT NULL"
        ))
        db.commit()

        seed_defaults(db)
        sync_prompts_from_files(db)
        from app.services.category_service import seed_categories, backfill_law_mapping_fields, ensure_eu_decision_category, seed_eu_celex_mappings
        seed_categories(db)
        ensure_eu_decision_category(db)
        seed_eu_celex_mappings(db)
        backfill_law_mapping_fields(db)

        # One-time rename: 'seed' source label is now 'system'.
        # Runs after backfill so any pending backfills complete first.
        db.execute(text("UPDATE law_mappings SET source='system' WHERE source='seed'"))
        db.commit()

        from app.services.user_service import seed_admin_users
        seed_admin_users(db)
        from app.services.model_seed import seed_models
        seed_models(db)
        from app.services.bm25_service import ensure_fts_index
        ensure_fts_index(db)

        # Add diff_summary column if it doesn't exist (SQLite migration)
        # Must run before any query that touches LawVersion
        from sqlalchemy import inspect
        inspector = inspect(engine)
        columns = [c["name"] for c in inspector.get_columns("law_versions")]
        if "diff_summary" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE law_versions ADD COLUMN diff_summary JSON"))
            logger.info("Added diff_summary column to law_versions")

        from app.services.version_discovery import seed_known_versions_from_imported
        seeded = seed_known_versions_from_imported(db)
        if seeded:
            logger.info(f"Seeded {seeded} KnownVersion rows from existing imports")

        from app.services.scheduler_config import seed_scheduler_settings
        seed_scheduler_settings(db)

        # Mark any jobs left running by a previous process as failed.
        # Without this, the UI would spin forever on rows orphaned by a crash.
        from app.services.job_service import recover_interrupted_jobs
        recover_interrupted_jobs(db)

        # Diff summary backfill skipped on startup (too slow with many versions).
        # Run manually via /api/admin/backfill-diffs if needed.
    finally:
        db.close()

    # Load scheduler settings from DB and register jobs
    from app.services.scheduler_config import schedule_jobs
    from app.database import SessionLocal as _SessionLocal
    _sched_db = _SessionLocal()
    try:
        schedule_jobs(_sched_db)
    finally:
        _sched_db.close()
    scheduler.start()
    logger.info("Scheduler started with DB-configured jobs")

    yield

    scheduler.shutdown()
    logger.info("Scheduler stopped")


app = FastAPI(
    title="Themis L&C API",
    description="Legal & Compliance AI",
    version="0.1.0",
    lifespan=lifespan,
)

_cors_origins = ["http://localhost:3000", "http://localhost:4000"]
if os.environ.get("CORS_ORIGIN"):
    _cors_origins.append(os.environ["CORS_ORIGIN"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.responses import JSONResponse
from app.errors import ThemisError, map_exception_to_error
import sqlite3


@app.exception_handler(ThemisError)
async def themis_error_handler(request, exc: ThemisError):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


@app.exception_handler(sqlite3.OperationalError)
async def sqlite_error_handler(request, exc: sqlite3.OperationalError):
    error = map_exception_to_error(exc)
    return JSONResponse(
        status_code=error.status_code,
        content=error.to_dict(),
    )


@app.exception_handler(Exception)
async def generic_error_handler(request, exc: Exception):
    import logging
    logging.getLogger(__name__).exception(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"code": "internal", "message": "Something went wrong. Please try again."},
    )


app.include_router(categories.router)
app.include_router(law_mappings.router)
app.include_router(laws.router)
app.include_router(notifications.router)
app.include_router(assistant_router.router)
app.include_router(settings_prompts.router)
app.include_router(settings_pipeline.router)
app.include_router(settings_categories.router)
app.include_router(settings_models.router)
app.include_router(compare.router)
app.include_router(admin_router.router)
app.include_router(settings_schedulers.router)
app.include_router(jobs_router.router)


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
