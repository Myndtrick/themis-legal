"""Tests for importing a single missing consolidated version of an EU law.

Covers the helper `import_eu_known_version` and the router branch in
POST /api/laws/{id}/known-versions/import for EU laws.
"""
import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import Base, get_db
from app.main import app as fastapi_app
from app.models.category import CategoryGroup, Category
from app.models.law import KnownVersion, Law, LawVersion
from app.models.user import User
import app.models.category  # noqa: F401  register tables

FIXTURES = Path(__file__).parent / "fixtures"


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


def _seed_eu_law(db):
    group = CategoryGroup(slug="eu", name_ro="UE", name_en="EU", color_hex="#185FA5", sort_order=9)
    db.add(group)
    db.flush()
    cat = Category(group_id=group.id, slug="eu.regulation", name_ro="Regs", name_en="Regs", is_eu=True, sort_order=1)
    db.add(cat)
    db.flush()

    law = Law(
        title="Reg Test",
        law_number="2065",
        law_year=2022,
        document_type="regulation",
        source="eu",
        celex_number="32022R2065",
        cellar_uri="http://publications.europa.eu/resource/cellar/base-uri",
        category_id=cat.id,
    )
    db.add(law)
    db.flush()
    base = LawVersion(
        law_id=law.id,
        ver_id="32022R2065",
        date_in_force=datetime.date(2022, 10, 19),
        is_current=True,
        language="ro",
    )
    db.add(base)
    db.add(KnownVersion(
        law_id=law.id,
        ver_id="02022R2065-20221027",
        date_in_force=datetime.date(2022, 10, 27),
        is_current=False,
        language="ro",
    ))
    db.commit()
    return law


def _parsed_xhtml():
    from app.services.eu_html_parser import parse_eu_xhtml
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    return parse_eu_xhtml(html)


def test_router_imports_eu_known_version(client_and_db):
    """Clicking Import on a missing EU consolidated version should store a new LawVersion."""
    client, db = client_and_db
    law = _seed_eu_law(db)

    consol = [{
        "celex": "02022R2065-20221027",
        "cellar_uri": "http://publications.europa.eu/resource/cellar/cv-uri",
        "date": "2022-10-27",
    }]

    with patch("app.services.eu_cellar_service.fetch_consolidated_versions", return_value=consol), \
         patch("app.services.eu_cellar_service.fetch_eu_content", return_value=(_parsed_xhtml(), "ro")):
        resp = client.post(
            f"/api/laws/{law.id}/known-versions/import",
            json={"ver_id": "02022R2065-20221027"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "imported"
    assert body["ver_id"] == "02022R2065-20221027"

    # New version should be persisted
    versions = db.query(LawVersion).filter_by(law_id=law.id).order_by(LawVersion.date_in_force).all()
    assert [v.ver_id for v in versions] == ["32022R2065", "02022R2065-20221027"]


def test_router_eu_returns_structured_error_when_celex_not_in_consolidated(client_and_db):
    """If SPARQL doesn't return the requested CELEX, surface a structured 502 with code."""
    client, db = client_and_db
    law = _seed_eu_law(db)

    with patch("app.services.eu_cellar_service.fetch_consolidated_versions", return_value=[]):
        resp = client.post(
            f"/api/laws/{law.id}/known-versions/import",
            json={"ver_id": "02022R2065-20221027"},
        )

    assert resp.status_code == 502
    body = resp.json()
    assert body["code"] == "eu_content_unavailable"
    assert "02022R2065-20221027" in body["message"]


def test_router_eu_returns_structured_error_when_fetch_content_fails(client_and_db):
    """When CELLAR has SPARQL metadata but no XHTML manifestation, return structured 502."""
    client, db = client_and_db
    law = _seed_eu_law(db)

    consol = [{
        "celex": "02022R2065-20221027",
        "cellar_uri": "http://publications.europa.eu/resource/cellar/cv-uri",
        "date": "2022-10-27",
    }]

    with patch("app.services.eu_cellar_service.fetch_consolidated_versions", return_value=consol), \
         patch(
             "app.services.eu_cellar_service.fetch_eu_content",
             side_effect=RuntimeError("Could not fetch content for 02022R2065-20221027 in any language"),
         ):
        resp = client.post(
            f"/api/laws/{law.id}/known-versions/import",
            json={"ver_id": "02022R2065-20221027"},
        )

    assert resp.status_code == 502
    body = resp.json()
    assert body["code"] == "eu_content_unavailable"


def test_router_import_all_missing_eu(client_and_db):
    """import-all should also handle EU laws via the new helper."""
    client, db = client_and_db
    law = _seed_eu_law(db)
    db.add(KnownVersion(
        law_id=law.id,
        ver_id="02022R2065-20240101",
        date_in_force=datetime.date(2024, 1, 1),
        is_current=False,
        language="ro",
    ))
    db.commit()

    consol = [
        {
            "celex": "02022R2065-20221027",
            "cellar_uri": "http://publications.europa.eu/resource/cellar/cv1",
            "date": "2022-10-27",
        },
        {
            "celex": "02022R2065-20240101",
            "cellar_uri": "http://publications.europa.eu/resource/cellar/cv2",
            "date": "2024-01-01",
        },
    ]

    with patch("app.services.eu_cellar_service.fetch_consolidated_versions", return_value=consol), \
         patch("app.services.eu_cellar_service.fetch_eu_content", return_value=(_parsed_xhtml(), "ro")), \
         patch("time.sleep", return_value=None):
        resp = client.post(f"/api/laws/{law.id}/known-versions/import-all")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "done"
    assert body["imported"] == 2
    assert body["errors"] == []
