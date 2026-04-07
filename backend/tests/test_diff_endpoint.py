"""Tests for GET /api/laws/{id}/diff (structured diff tree)."""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import Base, get_db
from app.main import app as fastapi_app
from app.models.law import Article, Law, LawVersion, Paragraph, Subparagraph
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


def _seed_law_with_two_versions(db):
    """Two versions: v2 modifies one subparagraph in art 62 (1)k)."""
    law = Law(title="Test Law", law_number="411", law_year=2004)
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

    # v1 article 62
    art_a = Article(
        law_version_id=v1.id, article_number="62",
        full_text="art 62 v1", order_index=62,
    )
    db.add(art_a)
    db.flush()
    para_a = Paragraph(
        article_id=art_a.id, label="(1)", text="", order_index=1,
    )
    db.add(para_a)
    db.flush()
    db.add(Subparagraph(
        paragraph_id=para_a.id, label="k)",
        text="fonduri facultative", order_index=1,
    ))

    # v2 article 62 — same label, modified subparagraph
    art_b = Article(
        law_version_id=v2.id, article_number="62",
        full_text="art 62 v2", order_index=62,
    )
    db.add(art_b)
    db.flush()
    para_b = Paragraph(
        article_id=art_b.id, label="(1)", text="", order_index=1,
    )
    db.add(para_b)
    db.flush()
    db.add(Subparagraph(
        paragraph_id=para_b.id, label="k)",
        text="fonduri ocupaționale", order_index=1,
    ))

    db.commit()
    return law, v1, v2


def test_diff_endpoint_returns_structured_tree(client_and_db):
    client, db = client_and_db
    law, v1, v2 = _seed_law_with_two_versions(db)

    resp = client.get(
        f"/api/laws/{law.id}/diff?version_a={v1.id}&version_b={v2.id}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "summary" in body
    assert "changes" in body
    assert body["version_a"]["id"] == v1.id
    assert body["version_b"]["id"] == v2.id

    # All returned changes are in tree shape with paragraphs and renumbered_from
    assert len(body["changes"]) == 1
    change = body["changes"][0]
    assert change["article_number"] == "62"
    assert change["change_type"] == "modified"
    assert "paragraphs" in change
    assert "renumbered_from" in change

    # Paragraph (1) modified, with the litera k) showing inline highlight
    para = change["paragraphs"][0]
    assert para["label"] == "(1)"
    assert para["change_type"] == "modified"
    assert "subparagraphs" in para

    leaf_k = next(s for s in para["subparagraphs"] if s["label"] == "k)")
    assert leaf_k["change_type"] == "modified"
    assert "<del>facultative</del>" in leaf_k["diff_html"]
    assert "<ins>ocupaționale</ins>" in leaf_k["diff_html"]


def test_diff_endpoint_404_when_versions_missing(client_and_db):
    client, db = client_and_db
    law = Law(title="x", law_number="1", law_year=2020)
    db.add(law)
    db.commit()

    resp = client.get(f"/api/laws/{law.id}/diff?version_a=999&version_b=998")
    assert resp.status_code == 404
