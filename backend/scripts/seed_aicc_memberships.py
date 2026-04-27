"""One-shot bootstrap: dump Themis users + admin emails as a seed list for
AICC ProjectMembership.

Usage (read from local DB and emit JSON):
  cd backend
  uv run python scripts/seed_aicc_memberships.py [--dry-run] [--format=json|csv]

Reads:
  - users  (existing Themis users; their role decides projectRole)
  - allowed_emails  (whitelisted but not yet signed in; default projectRole)
                    NOTE: this table may already be dropped after the migration —
                    the script tolerates that.

Writes:
  - JSON or CSV to stdout, suitable for paste into the AICC dashboard's
    project-members import UI, or for piping into a future direct-API call
    once AICC exposes a virtual-key-authenticated /api/v2/projects/:id/members
    endpoint (the current dashboard endpoint requires an admin session cookie,
    which is not scriptable from this context).

Idempotent: running twice produces the same output. Safe.

Why this isn't a direct API call: at the time of writing, the AICC
ProjectMembership API is `POST /api/projects/:id/members` and requires
dashboard session auth (see /Users/radugogoasa/aicommandcenter/docs/api/dashboard-api.md).
A v2 virtual-key-authenticated equivalent does not exist yet. Until it does,
we emit a seed file and ask the operator to use the AICC dashboard.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from io import StringIO

from sqlalchemy import text

from app.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
logger = logging.getLogger("seed-aicc")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="log to stderr only; no stdout output")
    parser.add_argument("--format", choices=["json", "csv"], default="json")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        users = db.execute(text("SELECT email, role FROM users")).all()
        try:
            allowed = db.execute(text("SELECT email FROM allowed_emails")).all()
        except Exception:
            # Table may have been dropped already by the auth migration.
            allowed = []
    finally:
        db.close()

    targets: dict[str, str] = {}  # email (lower) -> projectRole
    for email, role in users:
        targets[email.lower()] = "admin" if role == "admin" else "editor"
    for (email,) in allowed:
        targets.setdefault(email.lower(), "editor")

    logger.info("Found %d unique emails to seed", len(targets))

    if args.dry_run:
        for email, role in sorted(targets.items()):
            logger.info("[dry-run] %s -> %s", email, role)
        return 0

    if args.format == "json":
        rows = [{"email": e, "projectRole": r} for e, r in sorted(targets.items())]
        sys.stdout.write(json.dumps(rows, indent=2) + "\n")
    else:  # csv
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(["email", "projectRole"])
        for email, role in sorted(targets.items()):
            writer.writerow([email, role])
        sys.stdout.write(buf.getvalue())

    logger.info("Seed list emitted. Import via AICC dashboard:")
    logger.info("  1. Go to AICC dashboard → THEMIS project → Members")
    logger.info("  2. Bulk-import the rows above")
    logger.info("  3. Verify each Themis admin has projectRole=admin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
