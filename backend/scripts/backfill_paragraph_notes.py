"""CLI: run the paragraph-notes backfill against a SQLite database file.

Usage:
    cd backend
    uv run python scripts/backfill_paragraph_notes.py [--law-id N] [--no-dry-run] [--db PATH]

Examples:
    # Dry run against the default DB
    uv run python scripts/backfill_paragraph_notes.py

    # Live run against the default DB
    uv run python scripts/backfill_paragraph_notes.py --no-dry-run

    # Dry run for a single law against a specific DB file
    uv run python scripts/backfill_paragraph_notes.py --law-id 5 --db data/themis.db
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Make `app` importable when run as a script from backend/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

# Register all ORM models so SQLAlchemy can resolve relationships
import app.models.assistant  # noqa: F401, E402
import app.models.pipeline  # noqa: F401, E402
import app.models.prompt  # noqa: F401, E402
import app.models.category  # noqa: F401, E402
import app.models.user  # noqa: F401, E402
import app.models.favorite  # noqa: F401, E402
import app.models.law  # noqa: F401, E402
import app.models.model_config  # noqa: F401, E402
import app.models.scheduler_settings  # noqa: F401, E402
import app.models.job  # noqa: F401, E402
import app.models.scheduler_run_log  # noqa: F401, E402
import app.models.law_check_log  # noqa: F401, E402

from app.services.notes_backfill import backfill_notes  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Paragraph-notes backfill")
    parser.add_argument("--law-id", type=int, default=None)
    parser.add_argument("--no-dry-run", action="store_true",
                        help="Actually persist changes (default is dry run)")
    parser.add_argument("--db", default="data/themis.db", help="Path to the SQLite DB file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    engine = create_engine(
        f"sqlite:///{args.db}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Session = sessionmaker(bind=engine)
    db = Session()

    def progress(i: int, total: int) -> None:
        print(f"  [{i}/{total}] versions", flush=True)

    try:
        report = backfill_notes(
            db,
            law_id=args.law_id,
            dry_run=not args.no_dry_run,
            on_progress=progress,
        )
    finally:
        db.close()

    print()
    print("=" * 60)
    print("DRY RUN" if not args.no_dry_run else "LIVE RUN")
    print("=" * 60)
    print(f"versions_processed:        {report.versions_processed}")
    print(f"versions_failed:           {report.versions_failed}")
    print(f"paragraph_notes_to_insert: {report.paragraph_notes_to_insert}")
    print(f"article_notes_to_insert:   {report.article_notes_to_insert}")
    print(f"text_clean_writes:         {report.text_clean_writes}")
    if report.unknown_paragraph_labels:
        print("unknown_paragraph_labels (first 20):")
        for s in report.unknown_paragraph_labels[:20]:
            print(f"  - {s}")
    if report.errors:
        print("errors (first 20):")
        for e in report.errors[:20]:
            print(f"  - {e}")
    return 1 if report.versions_failed else 0


if __name__ == "__main__":
    sys.exit(main())
