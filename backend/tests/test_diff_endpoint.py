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
from app.models.law import Article, Law, LawVersion
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
    """Two versions: v2 modifies litera k) of alineat (1) in art 62."""
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

    # v1 article 62 — full_text is the source of truth for the new tokenizer-based diff
    art_a = Article(
        law_version_id=v1.id, article_number="62",
        full_text="(1) k) fonduri facultative din pensii",
        order_index=62,
    )
    # v2 article 62 — litera k) changes "facultative" → "ocupaționale"
    art_b = Article(
        law_version_id=v2.id, article_number="62",
        full_text="(1) k) fonduri ocupaționale din pensii",
        order_index=62,
    )
    db.add_all([art_a, art_b])
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

    # Exactly one modified article
    assert len(body["changes"]) == 1
    change = body["changes"][0]
    assert change["article_number"] == "62"
    assert change["change_type"] == "modified"
    assert "units" in change
    assert "renumbered_from" in change

    # units is a non-empty list of DiffUnit dicts
    units = change["units"]
    assert isinstance(units, list)
    assert len(units) > 0

    # Find the litera k) unit — the tokenizer emits label="k)" for "k) "
    leaf_k = next(
        (u for u in units if u.get("marker_kind") == "litera" and u.get("label") == "k)"),
        None,
    )
    assert leaf_k is not None, f"No litera k) unit found in units: {units}"
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
