"""Compute and store article-level diff summaries between consecutive law versions."""
import logging

from sqlalchemy.orm import Session

from app.models.law import Article, Law, LawVersion

logger = logging.getLogger(__name__)


def compute_diff_summary(db: Session, version: LawVersion) -> dict | None:
    """Compute diff summary for a version against its predecessor.

    Returns {"modified": N, "added": N, "removed": N} or None if no predecessor.
    """
    if not version.date_in_force:
        return None

    prev = (
        db.query(LawVersion)
        .filter(
            LawVersion.law_id == version.law_id,
            LawVersion.id != version.id,
            LawVersion.date_in_force < version.date_in_force,
        )
        .order_by(LawVersion.date_in_force.desc())
        .first()
    )

    if not prev:
        return None

    arts_prev = {
        a.article_number: a.full_text
        for a in db.query(Article).filter(Article.law_version_id == prev.id).all()
    }
    arts_curr = {
        a.article_number: a.full_text
        for a in db.query(Article).filter(Article.law_version_id == version.id).all()
    }

    all_numbers = set(arts_prev.keys()) | set(arts_curr.keys())

    modified = 0
    added = 0
    removed = 0

    for num in all_numbers:
        in_prev = num in arts_prev
        in_curr = num in arts_curr
        if in_prev and not in_curr:
            removed += 1
        elif in_curr and not in_prev:
            added += 1
        elif arts_prev[num].strip() != arts_curr[num].strip():
            modified += 1

    return {"modified": modified, "added": added, "removed": removed}


def backfill_diff_summaries(db: Session, *, law_id: int | None = None) -> int:
    """Compute diff_summary for LawVersion rows that don't have one yet.

    When `law_id` is provided, the scan is scoped to that single law. This is
    what import runners use — a full-DB scan inside a per-import transaction
    causes long-running writes that contend on the SQLite writer lock when two
    imports run in parallel, leaving jobs stuck in `running` long after the
    visible import work is done.
    """
    q = db.query(LawVersion).filter(LawVersion.diff_summary.is_(None))
    if law_id is not None:
        q = q.filter(LawVersion.law_id == law_id)
    versions = q.order_by(LawVersion.law_id, LawVersion.date_in_force).all()

    count = 0
    for v in versions:
        summary = compute_diff_summary(db, v)
        if summary is not None:
            v.diff_summary = summary
            count += 1

    db.flush()
    return count
