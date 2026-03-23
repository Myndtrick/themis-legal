import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import laws, notifications

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


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
    # Create data directory and database tables on startup
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(bind=engine)

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
    title="Legalese API",
    description="Legal & Compliance AI for Romanian Wealth Management",
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

app.include_router(laws.router)
app.include_router(notifications.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/admin/check-updates")
def trigger_update_check():
    """Manually trigger an update check for all stored laws."""
    from app.services.update_checker import check_for_updates

    results = check_for_updates()
    return results
