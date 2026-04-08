"""Read-only additive backfill of paragraph-level amendment notes and text_clean.

This job re-fetches each LawVersion through leropa and:
  1. INSERTs any paragraph-level AmendmentNote rows that aren't already present
     (deduped at the DB level via the ux_amendment_notes_dedupe unique index).
  2. INSERTs any article-level notes whose note_source_id is missing.
  3. UPDATEs Article.text_clean and Paragraph.text_clean ONLY when they are NULL.

It NEVER touches existing rows in laws / law_versions / articles / paragraphs /
subparagraphs beyond writing the new text_clean column. A SQLAlchemy before_flush
guardrail enforces this at runtime: any forbidden mutation aborts the job
immediately.

Idempotent. Resumable (per-version transactions). Dry-run by default.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.orm import Session

from app.models.law import (
    AmendmentNote,
    Article,
    Law,
    LawVersion,
    Paragraph,
    Subparagraph,
)
from app.services.fetcher import fetch_document
from app.services.note_text_cleaner import strip as strip_notes

logger = logging.getLogger(__name__)

# Tables that the backfill must not modify in any way
_FORBIDDEN_TYPES = {Law, LawVersion, Subparagraph}
# Tables where the only allowed mutation is writing text_clean on a NULL column
_TEXT_CLEAN_ONLY_TYPES = {Article, Paragraph}


class BackfillSafetyError(RuntimeError):
    """Raised when the guardrail detects a forbidden mutation."""


@dataclass
class BackfillReport:
    versions_processed: int = 0
    versions_failed: int = 0
    paragraph_notes_to_insert: int = 0
    article_notes_to_insert: int = 0
    text_clean_writes: int = 0
    unknown_paragraph_labels: list[str] = field(default_factory=list)
    unparsed_subjects: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def backfill_notes(
    db: Session,
    *,
    law_id: int | None = None,
    dry_run: bool = True,
    on_progress: Callable[[int, int], None] | None = None,
    fetch_delay_seconds: float = 0.5,
) -> BackfillReport:
    """Run the additive backfill. Returns a BackfillReport.

    Args:
        db: SQLAlchemy session bound to the production engine.
        law_id: Restrict to a single law (None = all laws).
        dry_run: When True, the per-version transaction is rolled back after
                 counting; nothing is persisted.
        on_progress: Optional callback (i, total) for progress UIs.
        fetch_delay_seconds: Sleep between leropa fetches to be polite.
    """
    report = BackfillReport()

    # Restrict to Romanian-source laws. The backfill re-fetches each version
    # via leropa (legislatie.just.ro), which only knows how to parse Romanian
    # documents. EU laws live under a different parser (eu_html_parser /
    # cellar) and have CELEX ver_ids that legislatie.just.ro returns 500 for.
    versions_q = (
        db.query(LawVersion)
        .join(Law, LawVersion.law_id == Law.id)
        .filter(Law.source == "ro")
    )
    if law_id is not None:
        versions_q = versions_q.filter(LawVersion.law_id == law_id)
    versions = versions_q.order_by(LawVersion.id).all()
    total = len(versions)

    _install_guardrail(db)
    try:
        for i, version in enumerate(versions, start=1):
            try:
                _process_version(db, version, dry_run=dry_run, report=report)
                report.versions_processed += 1
            except BackfillSafetyError:
                # Guardrail violations are fatal; surface immediately
                db.rollback()
                raise
            except Exception as exc:
                logger.exception(
                    "Backfill failed for version_id=%s ver_id=%s",
                    version.id, version.ver_id,
                )
                report.versions_failed += 1
                report.errors.append(f"version {version.ver_id}: {exc}")
                db.rollback()
            if on_progress is not None:
                on_progress(i, total)
            if fetch_delay_seconds > 0 and i < total:
                time.sleep(fetch_delay_seconds)
    finally:
        _uninstall_guardrail(db)

    return report


def _process_version(
    db: Session,
    version: LawVersion,
    *,
    dry_run: bool,
    report: BackfillReport,
) -> None:
    """Process one version inside its own transaction."""
    result = fetch_document(version.ver_id)
    parsed_articles = result.get("articles", [])

    # Build label → row lookups for THIS version's existing data
    existing_articles = (
        db.query(Article).filter(Article.law_version_id == version.id).all()
    )
    article_by_label: dict[str, Article] = {}
    for a in existing_articles:
        key = a.label or a.article_number
        if key:
            article_by_label[key] = a

    paragraph_by_key: dict[tuple[str, str], Paragraph] = {}
    for art in existing_articles:
        pars = db.query(Paragraph).filter(Paragraph.article_id == art.id).all()
        art_key = art.label or art.article_number
        for p in pars:
            paragraph_by_key[(art_key, p.label or "")] = p

    # Pre-load existing note source ids for this version's articles to dedupe
    existing_source_ids: set[tuple[int, int | None, str | None]] = set()
    for art in existing_articles:
        for n in (
            db.query(AmendmentNote)
            .filter(AmendmentNote.article_id == art.id)
            .all()
        ):
            existing_source_ids.add((n.article_id, n.paragraph_id, n.note_source_id))

    for parsed_art in parsed_articles:
        art_label = parsed_art.get("label")
        if not art_label:
            continue
        art_row = article_by_label.get(art_label)
        if art_row is None:
            report.unknown_paragraph_labels.append(f"{version.ver_id}:art:{art_label}")
            continue

        # text_clean for the article (only if currently NULL)
        if art_row.text_clean is None:
            art_row.text_clean = strip_notes(parsed_art.get("full_text", ""))
            report.text_clean_writes += 1

        # Paragraph-level notes
        for parsed_par in parsed_art.get("paragraphs", []):
            par_label = parsed_par.get("label")
            par_row = paragraph_by_key.get((art_label, par_label or ""))
            if par_row is None:
                report.unknown_paragraph_labels.append(
                    f"{version.ver_id}:{art_label}:{par_label}"
                )
                logger.warning(
                    "Backfill: paragraph (%s, %s) not found in version %s — skipping",
                    art_label, par_label, version.ver_id,
                )
                continue

            if par_row.text_clean is None:
                par_row.text_clean = strip_notes(parsed_par.get("text", ""))
                report.text_clean_writes += 1

            for note in parsed_par.get("notes", []):
                key = (art_row.id, par_row.id, note.get("note_id"))
                if key in existing_source_ids:
                    continue
                report.paragraph_notes_to_insert += 1
                db.add(AmendmentNote(
                    article_id=art_row.id,
                    paragraph_id=par_row.id,
                    note_source_id=note.get("note_id"),
                    text=note.get("text"),
                    date=note.get("date"),
                    subject=note.get("subject"),
                    law_number=note.get("law_number"),
                    law_date=note.get("law_date"),
                    monitor_number=note.get("monitor_number"),
                    monitor_date=note.get("monitor_date"),
                    original_text=note.get("replaced"),
                    replacement_text=note.get("replacement"),
                ))
                existing_source_ids.add(key)

        # Article-level notes (catches notes added to source HTML after original import)
        for note in parsed_art.get("notes", []):
            key = (art_row.id, None, note.get("note_id"))
            if key in existing_source_ids:
                continue
            report.article_notes_to_insert += 1
            db.add(AmendmentNote(
                article_id=art_row.id,
                paragraph_id=None,
                note_source_id=note.get("note_id"),
                text=note.get("text"),
                date=note.get("date"),
                subject=note.get("subject"),
                law_number=note.get("law_number"),
                law_date=note.get("law_date"),
                monitor_number=note.get("monitor_number"),
                monitor_date=note.get("monitor_date"),
                original_text=note.get("replaced"),
                replacement_text=note.get("replacement"),
            ))
            existing_source_ids.add(key)

    if dry_run:
        db.rollback()
    else:
        db.commit()


# ---------------------------------------------------------------------------
# Safety guardrail
# ---------------------------------------------------------------------------

_GUARDRAIL_LISTENER = None


def _install_guardrail(db: Session) -> None:
    global _GUARDRAIL_LISTENER

    def _before_flush(session, flush_context, instances):  # noqa: ARG001
        for obj in session.deleted:
            if type(obj) in _FORBIDDEN_TYPES or type(obj) in _TEXT_CLEAN_ONLY_TYPES:
                raise BackfillSafetyError(
                    f"Backfill attempted to DELETE {type(obj).__name__} id={getattr(obj, 'id', '?')}"
                )
        for obj in session.dirty:
            t = type(obj)
            if t in _FORBIDDEN_TYPES:
                raise BackfillSafetyError(
                    f"Backfill attempted to UPDATE {t.__name__} id={getattr(obj, 'id', '?')}"
                )
            if t in _TEXT_CLEAN_ONLY_TYPES:
                state = sa_inspect(obj)
                for attr in state.attrs:
                    if attr.history.has_changes() and attr.key != "text_clean":
                        raise BackfillSafetyError(
                            f"Backfill attempted to UPDATE {t.__name__}.{attr.key} "
                            f"id={getattr(obj, 'id', '?')} — only text_clean writes are allowed"
                        )

    _GUARDRAIL_LISTENER = _before_flush
    event.listen(db, "before_flush", _GUARDRAIL_LISTENER)


def _uninstall_guardrail(db: Session) -> None:
    global _GUARDRAIL_LISTENER
    if _GUARDRAIL_LISTENER is not None:
        try:
            event.remove(db, "before_flush", _GUARDRAIL_LISTENER)
        except Exception:
            pass
        _GUARDRAIL_LISTENER = None
