"""Tests for the /api/law-mappings router (user-editable suggestion list)."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import Base, get_db
from app.main import app as fastapi_app
from app.models.category import Category, CategoryGroup, LawMapping
from app.models.user import User
import app.models.law  # noqa: F401 — register tables


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


def _seed_category(db, slug="ro.civil"):
    g = CategoryGroup(slug="civil", name_ro="x", name_en="x", color_hex="#000", sort_order=1)
    db.add(g)
    db.flush()
    cat = Category(group_id=g.id, slug=slug, name_ro="x", name_en="x", sort_order=1)
    db.add(cat)
    db.commit()
    return cat


# ---------- POST /api/law-mappings ----------

def test_post_creates_user_mapping_from_ro_url(client_and_db):
    client, db = client_and_db
    cat = _seed_category(db)

    fake_doc = {"document": {"title": "Legea 31/1990 — societăți"}}
    with patch(
        "app.services.suggestion_service.fetch_document",
        return_value=fake_doc,
    ):
        resp = client.post(
            "/api/law-mappings",
            json={
                "url": "https://legislatie.just.ro/Public/DetaliiDocument/267625",
                "category_id": cat.id,
            },
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source"] == "user"
    assert body["source_ver_id"] == "267625"
    assert body["title"] == "Legea 31/1990 — societăți"
    assert body["category_id"] == cat.id


def test_post_creates_user_mapping_from_eu_url(client_and_db):
    client, db = client_and_db
    cat = _seed_category(db, slug="eu.regulation")

    fake_meta = {"title": "GDPR", "cellar_uri": "x", "date": "2016-04-27", "in_force": True, "issuers": []}
    with patch(
        "app.services.suggestion_service.fetch_eu_metadata",
        return_value=fake_meta,
    ):
        resp = client.post(
            "/api/law-mappings",
            json={
                "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679",
                "category_id": cat.id,
            },
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["celex_number"] == "32016R0679"


def test_post_unknown_host_returns_422(client_and_db):
    client, db = client_and_db
    cat = _seed_category(db)
    resp = client.post(
        "/api/law-mappings",
        json={"url": "https://example.com/foo", "category_id": cat.id},
    )
    assert resp.status_code == 422


def test_post_idempotent_returns_existing(client_and_db):
    client, db = client_and_db
    cat = _seed_category(db)

    fake_doc = {"document": {"title": "Legea 31/1990"}}
    url = "https://legislatie.just.ro/Public/DetaliiDocument/267625"
    with patch(
        "app.services.suggestion_service.fetch_document",
        return_value=fake_doc,
    ):
        first = client.post("/api/law-mappings", json={"url": url, "category_id": cat.id})
        second = client.post("/api/law-mappings", json={"url": url, "category_id": cat.id})

    assert first.status_code == 201
    assert second.status_code in (200, 201)
    assert first.json()["id"] == second.json()["id"]
    assert db.query(LawMapping).filter(LawMapping.source_url == url).count() == 1


# ---------- PUT /api/law-mappings/{id} ----------

def test_put_edits_user_mapping(client_and_db):
    client, db = client_and_db
    cat = _seed_category(db)
    m = LawMapping(title="old", category_id=cat.id, source="user")
    db.add(m)
    db.commit()

    resp = client.put(
        f"/api/law-mappings/{m.id}",
        json={"title": "new"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "new"
    db.refresh(m)
    assert m.title == "new"
    assert m.source == "user"


def test_put_forks_system_mapping_to_user(client_and_db):
    client, db = client_and_db
    cat = _seed_category(db)
    m = LawMapping(title="seeded", category_id=cat.id, source="system")
    db.add(m)
    db.commit()

    resp = client.put(
        f"/api/law-mappings/{m.id}",
        json={"title": "user-edited"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "user"
    db.refresh(m)
    assert m.source == "user"
    assert m.title == "user-edited"


def test_put_returns_404_when_missing(client_and_db):
    client, db = client_and_db
    resp = client.put("/api/law-mappings/9999", json={"title": "x"})
    assert resp.status_code == 404


# ---------- DELETE /api/law-mappings/{id} ----------

def test_delete_removes_user_mapping(client_and_db):
    client, db = client_and_db
    cat = _seed_category(db)
    m = LawMapping(title="x", category_id=cat.id, source="user")
    db.add(m)
    db.commit()
    mid = m.id

    resp = client.delete(f"/api/law-mappings/{mid}")
    assert resp.status_code == 204
    assert db.query(LawMapping).filter(LawMapping.id == mid).first() is None


def test_delete_refuses_system_mapping(client_and_db):
    client, db = client_and_db
    cat = _seed_category(db)
    m = LawMapping(title="x", category_id=cat.id, source="system")
    db.add(m)
    db.commit()
    mid = m.id

    resp = client.delete(f"/api/law-mappings/{mid}")
    assert resp.status_code == 403
    assert db.query(LawMapping).filter(LawMapping.id == mid).first() is not None


# ---------- GET /api/law-mappings ----------

def test_list_returns_all_mappings(client_and_db):
    client, db = client_and_db
    cat = _seed_category(db)
    db.add(LawMapping(title="A", category_id=cat.id, source="system",
                      law_number="1", law_year=2000, document_type="law"))
    db.add(LawMapping(title="B", category_id=cat.id, source="user",
                      law_number="2", law_year=2001, document_type="law",
                      source_ver_id="555"))
    db.commit()

    resp = client.get("/api/law-mappings")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 2
    titles = {row["title"] for row in body}
    assert titles == {"A", "B"}
    # Spot-check shape
    row = next(r for r in body if r["title"] == "B")
    assert row["source"] == "user"
    assert row["source_ver_id"] == "555"
    assert row["category_id"] == cat.id
    assert row["category_name"] == "x"  # _seed_category sets name_en="x"
    assert row["group_slug"] == "civil"
    assert row["is_imported"] is False


def test_list_filter_by_source(client_and_db):
    client, db = client_and_db
    cat = _seed_category(db)
    db.add(LawMapping(title="sys", category_id=cat.id, source="system"))
    db.add(LawMapping(title="usr", category_id=cat.id, source="user"))
    db.commit()

    resp = client.get("/api/law-mappings?source=system")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "sys"


def test_list_filter_by_group_slug(client_and_db):
    client, db = client_and_db
    cat = _seed_category(db, slug="ro.civil")  # group slug = "civil" via _seed_category
    db.add(LawMapping(title="hit", category_id=cat.id, source="user"))
    db.commit()

    resp = client.get("/api/law-mappings?group_slug=civil")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp2 = client.get("/api/law-mappings?group_slug=nonexistent")
    assert resp2.status_code == 200
    assert resp2.json() == []


def test_list_filter_by_pinned(client_and_db):
    client, db = client_and_db
    cat = _seed_category(db)
    db.add(LawMapping(title="pinned-ro", category_id=cat.id, source="user", source_ver_id="111"))
    db.add(LawMapping(title="pinned-eu", category_id=cat.id, source="user", celex_number="32016R0679"))
    db.add(LawMapping(title="unpinned", category_id=cat.id, source="user"))
    db.commit()

    resp = client.get("/api/law-mappings?pinned=true")
    assert resp.status_code == 200
    titles = {r["title"] for r in resp.json()}
    assert titles == {"pinned-ro", "pinned-eu"}

    resp = client.get("/api/law-mappings?pinned=false")
    titles = {r["title"] for r in resp.json()}
    assert titles == {"unpinned"}


def test_list_filter_by_search_query(client_and_db):
    client, db = client_and_db
    cat = _seed_category(db)
    db.add(LawMapping(title="Codul Civil", category_id=cat.id, source="user"))
    db.add(LawMapping(title="Codul Penal", category_id=cat.id, source="user"))
    db.commit()

    resp = client.get("/api/law-mappings?q=civil")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Codul Civil"


# ---------- POST /api/law-mappings/probe-url ----------

def test_probe_ro_url(client_and_db):
    client, _ = client_and_db
    resp = client.post(
        "/api/law-mappings/probe-url",
        json={"url": "https://legislatie.just.ro/Public/DetaliiDocument/109884"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "ro"
    assert body["identifier"] == "109884"
    assert body["error"] is None


def test_probe_eu_url(client_and_db):
    client, _ = client_and_db
    resp = client.post(
        "/api/law-mappings/probe-url",
        json={"url": "https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32016R0679"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "eu"
    assert body["identifier"] == "32016R0679"
    assert body["error"] is None


def test_probe_unknown_host(client_and_db):
    client, _ = client_and_db
    resp = client.post(
        "/api/law-mappings/probe-url",
        json={"url": "https://example.com/foo"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "unknown"
    assert body["identifier"] is None
    assert body["error"] == "URL host not recognized"


def test_probe_known_host_no_identifier(client_and_db):
    client, _ = client_and_db
    resp = client.post(
        "/api/law-mappings/probe-url",
        json={"url": "https://eur-lex.europa.eu/homepage.html"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "eu"
    assert body["identifier"] is None
    assert body["error"] == "Could not extract identifier"
