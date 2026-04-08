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


def test_dedupe_index_does_not_collide_on_legacy_null_source_ids():
    """Pre-existing amendment_notes (note_source_id IS NULL) must not collide
    on the dedupe index, no matter how many share the same article_id.
    Regression: production has ~100 laws of legacy notes that would otherwise
    trip the constraint on first restart after this migration."""
    import datetime as _dt
    from sqlalchemy import text
    from app.models.law import AmendmentNote, Article, Law, LawVersion
    import app.models.category  # noqa: F401

    engine = _fresh_engine()
    Base.metadata.create_all(bind=engine)
    # Create the partial unique index the way lifespan() would
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ux_amendment_notes_dedupe"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_amendment_notes_dedupe "
            "ON amendment_notes(article_id, COALESCE(paragraph_id, 0), note_source_id) "
            "WHERE note_source_id IS NOT NULL"
        ))

    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        law = Law(title="T", law_number="1", law_year=2020)
        db.add(law); db.flush()
        v = LawVersion(law_id=law.id, ver_id="1",
                       date_in_force=_dt.date(2024, 1, 1),
                       state="actual", is_current=True)
        db.add(v); db.flush()
        art = Article(law_version_id=v.id, article_number="1", label="1",
                      full_text="x", order_index=0)
        db.add(art); db.flush()
        # Two legacy-style notes on the same article — both NULL source_id.
        # Must not collide.
        db.add(AmendmentNote(article_id=art.id, text="first", note_source_id=None))
        db.add(AmendmentNote(article_id=art.id, text="second", note_source_id=None))
        db.commit()
        assert db.query(AmendmentNote).count() == 2
    finally:
        db.close()


def test_dedupe_index_blocks_duplicate_source_ids_on_same_article():
    """Two notes with the same (article_id, paragraph_id, note_source_id)
    must violate the unique constraint."""
    import datetime as _dt
    import pytest as _pytest
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from app.models.law import AmendmentNote, Article, Law, LawVersion
    import app.models.category  # noqa: F401

    engine = _fresh_engine()
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ux_amendment_notes_dedupe"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_amendment_notes_dedupe "
            "ON amendment_notes(article_id, COALESCE(paragraph_id, 0), note_source_id) "
            "WHERE note_source_id IS NOT NULL"
        ))

    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        law = Law(title="T", law_number="1", law_year=2020)
        db.add(law); db.flush()
        v = LawVersion(law_id=law.id, ver_id="1",
                       date_in_force=_dt.date(2024, 1, 1),
                       state="actual", is_current=True)
        db.add(v); db.flush()
        art = Article(law_version_id=v.id, article_number="1", label="1",
                      full_text="x", order_index=0)
        db.add(art); db.flush()
        db.add(AmendmentNote(article_id=art.id, text="first", note_source_id="src-1"))
        db.commit()
        db.add(AmendmentNote(article_id=art.id, text="dup", note_source_id="src-1"))
        with _pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.close()
