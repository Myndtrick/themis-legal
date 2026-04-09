"""Integration test: leropa importer stores paragraph-level notes and text_clean."""
import datetime

import pytest
from sqlalchemy import create_engine
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
from app.services.leropa_service import _import_article


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _make_version(db):
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
    return v


def test_imports_article_level_note_unchanged(db):
    """Existing behaviour: article-level notes still land in amendment_notes."""
    version = _make_version(db)
    art_data = {
        "label": "1",
        "full_text": "Articolul 1. Text.",
        "paragraphs": [],
        "notes": [
            {
                "note_id": "art-note-1",
                "text": "(la 01-01-2024, Articolul 1 a fost modificat …)",
                "date": "01-01-2024",
                "subject": "Articolul 1",
                "law_number": "5",
            }
        ],
    }
    _import_article(db, version, parent=None, art_data=art_data, order_index=0)
    db.flush()
    notes = db.query(AmendmentNote).all()
    assert len(notes) == 1
    assert notes[0].paragraph_id is None
    assert notes[0].note_source_id == "art-note-1"


def test_imports_paragraph_level_note_with_paragraph_id(db):
    """New behaviour: paragraph-level notes are stored and linked to the paragraph."""
    version = _make_version(db)
    art_data = {
        "label": "5",
        "full_text": "Articolul 5. (1) Definiții.",
        "paragraphs": [
            {
                "label": "(1)",
                "text": "Definiții.",
                "subparagraphs": [],
                "notes": [
                    {
                        "note_id": "par-note-1",
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
    _import_article(db, version, parent=None, art_data=art_data, order_index=0)
    db.flush()
    notes = db.query(AmendmentNote).all()
    assert len(notes) == 1
    note = notes[0]
    assert note.note_source_id == "par-note-1"
    assert note.paragraph_id is not None
    par = db.query(Paragraph).filter_by(id=note.paragraph_id).one()
    assert par.label == "(1)"
    assert note.article_id == par.article_id


def test_writes_text_clean_for_article_and_paragraph(db):
    """Article.text_clean and Paragraph.text_clean strip inline (la …) annotations."""
    version = _make_version(db)
    raw_full = (
        "Articolul 1. Text. (la 01-01-2024, Articolul 1 a fost modificat de Legea nr. 5/2023, "
        "publicată în MONITORUL OFICIAL nr. 5 din 01 ianuarie 2024)"
    )
    raw_par = (
        "Conținut. (la 02-02-2025, Alineatul (1) a fost modificat de OUG nr. 7/2024, "
        "publicată în MONITORUL OFICIAL nr. 7 din 02 februarie 2025)"
    )
    art_data = {
        "label": "1",
        "full_text": raw_full,
        "paragraphs": [
            {"label": "(1)", "text": raw_par, "subparagraphs": [], "notes": []}
        ],
        "notes": [],
    }
    _import_article(db, version, parent=None, art_data=art_data, order_index=0)
    db.flush()
    art = db.query(Article).one()
    par = db.query(Paragraph).one()
    assert art.text_clean == "Articolul 1. Text."
    assert par.text_clean == "Conținut."
    # Original full_text / text are untouched
    assert art.full_text == raw_full
    assert par.text == raw_par
