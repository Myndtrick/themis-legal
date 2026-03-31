"""One-time script to re-index law versions missing from ChromaDB."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Register all ORM models before using the session (mirrors app/main.py)
import app.models.category  # noqa: F401
import app.models.pipeline  # noqa: F401
import app.models.prompt    # noqa: F401
import app.models.assistant  # noqa: F401

from app.database import SessionLocal
from app.services.chroma_service import index_law_version, verify_index_completeness

db = SessionLocal()

print("Checking for missing ChromaDB indexes...")
mismatches = verify_index_completeness(db)

if not mismatches:
    print("All current versions are fully indexed.")
else:
    print(f"Found {len(mismatches)} versions missing from ChromaDB:")
    for m in mismatches:
        print(f"  law_id={m['law_id']}, version_id={m['law_version_id']}, "
              f"DB articles={m['db_count']}")

    print("\nRe-indexing...")
    for m in mismatches:
        count = index_law_version(db, m["law_id"], m["law_version_id"])
        print(f"  version {m['law_version_id']}: indexed {count} items")

    # Verify
    remaining = verify_index_completeness(db)
    if remaining:
        print(f"\nWARNING: {len(remaining)} versions still incomplete after re-index")
    else:
        print("\nAll versions now fully indexed.")

db.close()
