"""One-time backfill: fetch issuers for EU laws that have none."""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.eu_cellar_service import _fetch_eu_issuers, fetch_eu_metadata


def backfill(db_path: str = "data/themis.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, celex_number, cellar_uri FROM laws WHERE source = 'eu' AND (issuer IS NULL OR issuer = '')"
    )
    rows = cursor.fetchall()
    print(f"Found {len(rows)} EU laws without issuers")

    for law_id, celex, cellar_uri in rows:
        if cellar_uri:
            issuers = _fetch_eu_issuers(cellar_uri)
        else:
            meta = fetch_eu_metadata(celex)
            issuers = meta.get("issuers", []) if meta else []

        if issuers:
            joined = ", ".join(issuers)
            cursor.execute("UPDATE laws SET issuer = ? WHERE id = ?", (joined, law_id))
            print(f"  {celex}: {joined}")
        else:
            print(f"  {celex}: no issuers found")

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "data/themis.db"
    backfill(db)
