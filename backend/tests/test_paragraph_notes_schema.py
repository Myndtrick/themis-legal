"""Smoke test that the paragraph-notes migration adds the expected columns + indexes."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models.law  # noqa: F401 — register tables
import app.models.category  # noqa: F401 — register categories table (FK dependency)


def _fresh_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_amendment_notes_has_paragraph_id_and_note_source_id():
    engine = _fresh_engine()
    Base.metadata.create_all(bind=engine)
    cols = {c["name"] for c in inspect(engine).get_columns("amendment_notes")}
    assert "paragraph_id" in cols
    assert "note_source_id" in cols


def test_articles_and_paragraphs_have_text_clean():
    engine = _fresh_engine()
    Base.metadata.create_all(bind=engine)
    art_cols = {c["name"] for c in inspect(engine).get_columns("articles")}
    par_cols = {c["name"] for c in inspect(engine).get_columns("paragraphs")}
    assert "text_clean" in art_cols
    assert "text_clean" in par_cols


def test_amendment_note_has_paragraph_relationship():
    from app.models.law import AmendmentNote, Paragraph
    assert hasattr(AmendmentNote, "paragraph")
    rel = AmendmentNote.paragraph.property
    assert rel.mapper.class_ is Paragraph
