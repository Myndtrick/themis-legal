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


def test_eu_laws_are_skipped_entirely(db):
    """EU laws (Law.source='eu') must not be passed to the leropa fetcher.

    Regression: legislatie.just.ro returns HTTP 500 for CELEX-numbered ver_ids,
    so the backfill must filter to source='ro' before iterating versions.
    """
    # Romanian law that should be processed
    ro_law = Law(title="RO", law_number="1", law_year=2020, source="ro")
    db.add(ro_law)
    db.flush()
    ro_version = LawVersion(
        law_id=ro_law.id, ver_id="100",
        date_in_force=datetime.date(2024, 1, 1),
        state="actual", is_current=True,
    )
    db.add(ro_version)
    db.flush()
    db.add(Article(
        law_version_id=ro_version.id, article_number="1", label="1",
        full_text="x", order_index=0,
    ))
    # EU law that must be skipped
    eu_law = Law(title="EU", law_number="1925", law_year=2022, source="eu")
    db.add(eu_law)
    db.flush()
    eu_version = LawVersion(
        law_id=eu_law.id, ver_id="32022R1925",
        date_in_force=datetime.date(2022, 9, 14),
        state="actual", is_current=True,
    )
    db.add(eu_version)
    db.commit()

    fetched_ver_ids: list[str] = []

    def spy_fetch(ver_id, *args, **kwargs):
        fetched_ver_ids.append(ver_id)
        return {"document": {}, "articles": [], "books": []}

    with patch("app.services.notes_backfill.fetch_document", side_effect=spy_fetch):
        report = backfill_notes(db, dry_run=True, fetch_delay_seconds=0)

    # The leropa fetcher must only have been called for the Romanian version
    assert fetched_ver_ids == ["100"]
    # The report counts only the RO version
    assert report.versions_processed == 1
    assert report.versions_failed == 0


from fastapi.testclient import TestClient

from app.auth import require_admin
from app.database import get_db
from app.main import app as fastapi_app
from app.models.user import User


def test_admin_endpoint_spawns_job_and_returns_job_id(db):
    """The endpoint must spawn a backfill job and return its job_id immediately.

    The actual backfill runs in the JobService thread pool with its own session
    pointing at the production engine, not the test in-memory engine — so we
    don't try to assert end-to-end behaviour through the endpoint here. The
    backfill_notes() function itself is covered by the six tests above.
    """
    _seed_one_version_no_notes(db)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_admin():
        return User(id=1, email="admin@example.com")

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[require_admin] = override_admin
    try:
        # Stub out job_service.submit so we don't actually kick off the worker
        # thread (it would race against the test DB and is also unnecessary).
        with patch("app.services.job_service.submit", return_value="test-job-123") as submit:
            with patch("app.services.job_service.has_active", return_value=False):
                client = TestClient(fastapi_app)
                r = client.post("/api/admin/backfill/notes", json={"dry_run": True})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "started"
        assert body["job_id"] == "test-job-123"
        assert body["dry_run"] is True
        # Confirm the runner was wired correctly
        submit.assert_called_once()
        kwargs = submit.call_args.kwargs
        assert kwargs["kind"] == "backfill_notes"
        assert kwargs["params"] == {"law_id": None, "dry_run": True}
        assert callable(kwargs["runner"])
        # Sanity: nothing was written to the DB by the endpoint itself
        assert db.query(AmendmentNote).count() == 0
    finally:
        fastapi_app.dependency_overrides.clear()


def test_admin_endpoint_returns_409_when_already_running(db):
    """Two POSTs in quick succession must not spawn two backfills."""
    _seed_one_version_no_notes(db)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_admin():
        return User(id=1, email="admin@example.com")

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[require_admin] = override_admin
    try:
        with patch("app.services.job_service.has_active", return_value=True):
            client = TestClient(fastapi_app)
            r = client.post("/api/admin/backfill/notes", json={"dry_run": True})
        assert r.status_code == 409
    finally:
        fastapi_app.dependency_overrides.clear()
