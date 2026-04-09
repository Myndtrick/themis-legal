"""Integration tests for GET /api/laws/{id}/diff (note-augmented structural diff)."""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import Base, get_db
from app.main import app as fastapi_app
from app.models.law import (
    AmendmentNote,
    Article,
    Law,
    LawVersion,
    Paragraph,
)
from app.models.user import User
import app.models.category  # noqa: F401 — register categories table


@pytest.fixture
def client_and_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_get_current_user():
        return User(id=1, email="test@example.com")

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_current_user] = override_get_current_user
    db = TestingSessionLocal()
    yield TestClient(fastapi_app), db
    db.close()
    fastapi_app.dependency_overrides.clear()


def _seed_modified_paragraph(db):
    """Two versions; v2 modifies paragraph (1) of article 5 and attaches a note."""
    law = Law(title="Test Law", law_number="100", law_year=2024)
    db.add(law)
    db.flush()

    v1 = LawVersion(
        law_id=law.id, ver_id="100",
        date_in_force=datetime.date(2024, 1, 1),
        state="actual", is_current=False,
    )
    v2 = LawVersion(
        law_id=law.id, ver_id="200",
        date_in_force=datetime.date(2025, 1, 1),
        state="actual", is_current=True,
    )
    db.add_all([v1, v2])
    db.flush()

    art_a = Article(
        law_version_id=v1.id, article_number="5", label="5",
        full_text="Operatorul economic plătește accize.",
        text_clean="Operatorul economic plătește accize.",
        order_index=0,
    )
    art_b = Article(
        law_version_id=v2.id, article_number="5", label="5",
        full_text="Operatorul economic plătește accize și taxe.",
        text_clean="Operatorul economic plătește accize și taxe.",
        order_index=0,
    )
    db.add_all([art_a, art_b])
    db.flush()

    par_a = Paragraph(
        article_id=art_a.id, paragraph_number="(1)", label="(1)",
        text="Operatorul economic plătește accize.",
        text_clean="Operatorul economic plătește accize.",
        order_index=0,
    )
    par_b = Paragraph(
        article_id=art_b.id, paragraph_number="(1)", label="(1)",
        text="Operatorul economic plătește accize și taxe.",
        text_clean="Operatorul economic plătește accize și taxe.",
        order_index=0,
    )
    db.add_all([par_a, par_b])
    db.flush()

    db.add(AmendmentNote(
        article_id=art_b.id, paragraph_id=par_b.id,
        note_source_id="src-1",
        date="01-01-2025",
        subject="Alineatul (1) al articolului 5",
        law_number="89", law_date="23-12-2024",
        monitor_number="1203", monitor_date="24-12-2024",
        text="(la 01-01-2025, …)",
    ))
    db.commit()
    return law, v1, v2


def test_diff_endpoint_returns_hierarchical_tree(client_and_db):
    client, db = client_and_db
    law, v1, v2 = _seed_modified_paragraph(db)

    r = client.get(f"/api/laws/{law.id}/diff?version_a={v1.id}&version_b={v2.id}")
    assert r.status_code == 200
    body = r.json()

    assert body["law_id"] == law.id
    assert body["version_a"]["id"] == v1.id
    assert body["version_b"]["id"] == v2.id
    assert "articles" in body
    assert "changes" not in body  # old field is gone

    assert body["summary"]["modified"] == 1
    assert body["summary"]["added"] == 0
    assert body["summary"]["removed"] == 0
    assert body["summary"]["unchanged"] == 0

    art_entries = body["articles"]
    assert len(art_entries) == 1
    art = art_entries[0]
    assert art["article_label"] == "5"
    assert art["change_type"] == "modified"
    assert art["renumbered_from"] is None
    assert isinstance(art["paragraphs"], list)
    assert len(art["paragraphs"]) == 1

    par = art["paragraphs"][0]
    assert par["paragraph_label"] == "(1)"
    assert par["change_type"] == "modified"
    assert par["text_clean_a"] == "Operatorul economic plătește accize."
    assert par["text_clean_b"] == "Operatorul economic plătește accize și taxe."
    assert "<ins>" in par["diff_html"]
    assert len(par["notes"]) == 1
    note = par["notes"][0]
    assert note["date"] == "01-01-2025"
    assert note["law_number"] == "89"
    assert note["monitor_number"] == "1203"


def test_diff_endpoint_404_when_versions_missing(client_and_db):
    client, _ = client_and_db
    r = client.get("/api/laws/9999/diff?version_a=1&version_b=2")
    assert r.status_code == 404
