"""When a LawMapping has source_ver_id set, import_suggestion must
skip advanced_search and pass that ver_id straight to do_import."""
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


def _make_mapping(db, *, source_ver_id: str | None) -> int:
    g = CategoryGroup(slug="civil", name_ro="x", name_en="x", color_hex="#000", sort_order=1)
    db.add(g); db.flush()
    cat = Category(group_id=g.id, slug="ro.civil", name_ro="x", name_en="x", sort_order=1)
    db.add(cat); db.flush()
    m = LawMapping(
        title="Pinned test law",
        law_number="42",
        law_year=2099,
        document_type="law",
        category_id=cat.id,
        source="user",
        source_ver_id=source_ver_id,
    )
    db.add(m); db.commit()
    return m.id


def test_pinned_mapping_skips_search(client_and_db):
    client, db = client_and_db
    mid = _make_mapping(db, source_ver_id="555555")

    with patch("app.services.search_service.advanced_search") as mock_search, \
         patch("app.services.leropa_service.import_law", return_value={"law_id": 1, "title": "ok"}) as mock_import:
        resp = client.post(
            "/api/laws/import-suggestion",
            json={"mapping_id": mid, "import_history": False},
        )

    assert resp.status_code == 200, resp.text
    assert mock_search.call_count == 0
    assert mock_import.called
    args, kwargs = mock_import.call_args
    # Signature: do_import(db, ver_id, import_history=...)
    assert args[1] == "555555"


def test_unpinned_mapping_falls_back_to_search(client_and_db):
    client, db = client_and_db
    mid = _make_mapping(db, source_ver_id=None)

    class FakeResult:
        ver_id = "888888"

    with patch("app.services.search_service.advanced_search", return_value=[FakeResult()]) as mock_search, \
         patch("app.services.leropa_service.import_law", return_value={"law_id": 2, "title": "ok"}) as mock_import:
        resp = client.post(
            "/api/laws/import-suggestion",
            json={"mapping_id": mid, "import_history": False},
        )

    assert resp.status_code == 200, resp.text
    assert mock_search.called
    assert mock_import.called
    args, kwargs = mock_import.call_args
    assert args[1] == "888888"


def test_successful_search_import_pins_ver_id(client_and_db):
    """After import_suggestion resolves a ver_id via search, the mapping is pinned."""
    client, db = client_and_db
    mid = _make_mapping(db, source_ver_id=None)

    class FakeResult:
        ver_id = "777777"

    with patch("app.services.search_service.advanced_search", return_value=[FakeResult()]), \
         patch("app.services.leropa_service.import_law", return_value={"law_id": 1, "title": "ok"}):
        resp = client.post(
            "/api/laws/import-suggestion",
            json={"mapping_id": mid, "import_history": False},
        )

    assert resp.status_code == 200, resp.text

    # Re-query the mapping
    from app.models.category import LawMapping
    m = db.query(LawMapping).filter(LawMapping.id == mid).first()
    assert m.source_ver_id == "777777"


def test_pinned_import_does_not_overwrite_pin(client_and_db):
    """If a mapping is already pinned, import does not change source_ver_id."""
    client, db = client_and_db
    mid = _make_mapping(db, source_ver_id="555555")

    with patch("app.services.search_service.advanced_search") as mock_search, \
         patch("app.services.leropa_service.import_law", return_value={"law_id": 2, "title": "ok"}):
        client.post(
            "/api/laws/import-suggestion",
            json={"mapping_id": mid, "import_history": False},
        )

    assert mock_search.call_count == 0
    from app.models.category import LawMapping
    m = db.query(LawMapping).filter(LawMapping.id == mid).first()
    assert m.source_ver_id == "555555"  # unchanged
