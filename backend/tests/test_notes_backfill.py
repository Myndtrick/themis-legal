"""Tests for the additive paragraph-notes backfill job."""
import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.law import (
    AmendmentNote,
    Article,
    Law,
    LawVersion,
    Paragraph,
)
import app.models.category  # noqa: F401
from app.services.notes_backfill import (
    BackfillSafetyError,
    backfill_notes,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    # The lifespan-only partial unique index is required for the dedupe path
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ux_amendment_notes_dedupe"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_amendment_notes_dedupe "
            "ON amendment_notes(article_id, COALESCE(paragraph_id, 0), note_source_id) "
            "WHERE note_source_id IS NOT NULL"
        ))
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _seed_one_version_no_notes(db):
    """Seed a law version with one article and one paragraph, NO notes yet."""
    law = Law(title="T", law_number="1", law_year=2020)
    db.add(law)
    db.flush()
    v = LawVersion(
        law_id=law.id, ver_id="100",
        date_in_force=datetime.date(2024, 1, 1),
        state="actual", is_current=True,
    )
    db.add(v)
    db.flush()
    art = Article(
        law_version_id=v.id, article_number="5", label="5",
        full_text="Articolul 5. (1) Definiții. (la 02-02-2025, Alineatul (1) a fost modificat de OUG nr. 7/2024)",
        order_index=0,
    )
    db.add(art)
    db.flush()
    par = Paragraph(
        article_id=art.id, paragraph_number="(1)", label="(1)",
        text="Definiții. (la 02-02-2025, Alineatul (1) a fost modificat de OUG nr. 7/2024)",
        order_index=0,
    )
    db.add(par)
    db.commit()
    return law, v, art, par


def _fake_leropa_result_with_paragraph_note(version_ver_id: str) -> dict:
    return {
        "document": {"title": "T"},
        "articles": [
            {
                "label": "5",
                "full_text": "Articolul 5. (1) Definiții.",
                "paragraphs": [
                    {
                        "label": "(1)",
                        "text": "Definiții.",
                        "subparagraphs": [],
                        "notes": [
                            {
                                "note_id": "par-note-xyz",
                                "text": "(la 02-02-2025, Alineatul (1) al articolului 5 a fost modificat …)",
                                "date": "02-02-2025",
                                "subject": "Alineatul (1) al articolului 5",
                                "law_number": "7",
                            }
                        ],
                    }
                ],
                "notes": [],
            }
        ],
        "books": [],
    }


def test_dry_run_inserts_nothing(db):
    law, v, art, par = _seed_one_version_no_notes(db)
    with patch(
        "app.services.notes_backfill.fetch_document",
        return_value=_fake_leropa_result_with_paragraph_note(v.ver_id),
    ):
        report = backfill_notes(db, dry_run=True, fetch_delay_seconds=0)
    db.expire_all()
    assert db.query(AmendmentNote).count() == 0
    assert report.paragraph_notes_to_insert == 1
    assert report.versions_processed == 1


def test_live_run_inserts_paragraph_note_with_paragraph_id(db):
    law, v, art, par = _seed_one_version_no_notes(db)
    with patch(
        "app.services.notes_backfill.fetch_document",
        return_value=_fake_leropa_result_with_paragraph_note(v.ver_id),
    ):
        backfill_notes(db, dry_run=False, fetch_delay_seconds=0)
    db.expire_all()
    notes = db.query(AmendmentNote).all()
    assert len(notes) == 1
    assert notes[0].paragraph_id == par.id
    assert notes[0].article_id == art.id
    assert notes[0].note_source_id == "par-note-xyz"


def test_live_run_writes_text_clean_only_when_null(db):
    law, v, art, par = _seed_one_version_no_notes(db)
    with patch(
        "app.services.notes_backfill.fetch_document",
        return_value=_fake_leropa_result_with_paragraph_note(v.ver_id),
    ):
        backfill_notes(db, dry_run=False, fetch_delay_seconds=0)
    db.expire_all()
    art_after = db.query(Article).one()
    par_after = db.query(Paragraph).one()
    assert art_after.text_clean == "Articolul 5. (1) Definiții."
    assert par_after.text_clean == "Definiții."


def test_re_running_is_a_noop(db):
    law, v, art, par = _seed_one_version_no_notes(db)
    fake = _fake_leropa_result_with_paragraph_note(v.ver_id)
    with patch("app.services.notes_backfill.fetch_document", return_value=fake):
        backfill_notes(db, dry_run=False, fetch_delay_seconds=0)
        backfill_notes(db, dry_run=False, fetch_delay_seconds=0)
    db.expire_all()
    # Unique index + IS NULL gating means the second run inserts nothing
    assert db.query(AmendmentNote).count() == 1


def test_guardrail_blocks_update_to_existing_article_text(db):
    """The guardrail must abort the job if anything tries to UPDATE Article.full_text."""
    law, v, art, par = _seed_one_version_no_notes(db)

    def evil_fetch(*args, **kwargs):
        # Simulate a buggy backfill that mutates an existing Article during the job
        existing = db.query(Article).first()
        existing.full_text = "MUTATED"
        return _fake_leropa_result_with_paragraph_note(v.ver_id)

    with patch("app.services.notes_backfill.fetch_document", side_effect=evil_fetch):
        with pytest.raises(BackfillSafetyError):
            backfill_notes(db, dry_run=False, fetch_delay_seconds=0)


def test_unknown_paragraph_label_skips_with_warning(db, caplog):
    """If leropa returns a paragraph our DB doesn't have, log + skip — never guess."""
    law, v, art, par = _seed_one_version_no_notes(db)
    fake = _fake_leropa_result_with_paragraph_note(v.ver_id)
    fake["articles"][0]["paragraphs"][0]["label"] = "(99)"  # nonexistent label

    with patch("app.services.notes_backfill.fetch_document", return_value=fake):
        backfill_notes(db, dry_run=False, fetch_delay_seconds=0)
    db.expire_all()
    assert db.query(AmendmentNote).count() == 0
