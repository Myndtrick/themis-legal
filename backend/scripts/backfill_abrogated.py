"""One-time backfill: scan article full_text for abrogation patterns."""
import re
import sqlite3

ABROGATION_PATTERNS = [
    r"^\s*\(?\s*[Aa]brogat",
    r"^\s*\(?\s*[Aa]brogat[ăa]\)",
    r"^\s*[Aa]rt\.\s*\d+.*[Aa]brogat",
]

def backfill(db_path: str = "data/themis.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, full_text FROM articles")
    updated = 0
    for art_id, text in cursor.fetchall():
        if not text:
            continue
        for pattern in ABROGATION_PATTERNS:
            if re.search(pattern, text[:200]):
                cursor.execute(
                    "UPDATE articles SET is_abrogated = 1 WHERE id = ?", (art_id,)
                )
                updated += 1
                break
    conn.commit()
    conn.close()
    print(f"Marked {updated} articles as abrogated")

if __name__ == "__main__":
    backfill()
