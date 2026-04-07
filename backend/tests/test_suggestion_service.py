"""Tests for the user-editable suggestion service.

Covers the orchestration that turns a public URL (legislatie.just.ro
or eur-lex.europa.eu) into a draft LawMapping with auto-fetched
title, plus the fork-on-edit semantic for system→user transitions.
"""
import datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.category import Category, CategoryGroup, LawMapping
import app.models.law  # noqa: F401 — register laws table for FK targets


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _make_category(db, slug="ro.civil"):
    group = CategoryGroup(
        slug="civil", name_ro="Civil", name_en="Civil",
        color_hex="#000000", sort_order=1,
    )
    db.add(group)
    db.flush()
    cat = Category(
        group_id=group.id, slug=slug, name_ro="Civil",
        name_en="Civil", sort_order=1,
    )
    db.add(cat)
    db.commit()
    return cat


# ---------- create_user_mapping_from_url ----------

def test_create_from_ro_url_extracts_ver_id_and_fetches_title():
    """A legislatie.just.ro URL gets parsed for ver_id and the title is
    fetched from upstream when no explicit title is provided."""
    db = _make_db()
    cat = _make_category(db)

    url = "https://legislatie.just.ro/Public/DetaliiDocument/267625"
    fake_doc = {"document": {"title": "Legea 31/1990 — societăți"}}

    from app.services.suggestion_service import create_user_mapping_from_url
    with patch(
        "app.services.suggestion_service.fetch_document",
        return_value=fake_doc,
    ):
        mapping = create_user_mapping_from_url(db, url=url, category_id=cat.id)

    assert mapping.id is not None
    assert mapping.source == "user"
    assert mapping.source_url == url
    assert mapping.source_ver_id == "267625"
    assert mapping.celex_number is None
    assert mapping.title == "Legea 31/1990 — societăți"
    assert mapping.category_id == cat.id


def test_create_from_eu_url_extracts_celex_and_fetches_title():
    """An eur-lex URL gets parsed for CELEX and the title comes from
    fetch_eu_metadata, not fetch_document."""
    db = _make_db()
    cat = _make_category(db, slug="eu.regulation")

    url = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679"
    fake_meta = {"title": "Regulation (EU) 2016/679 — GDPR", "cellar_uri": "x", "date": "2016-04-27", "in_force": True, "issuers": []}

    from app.services.suggestion_service import create_user_mapping_from_url
    with patch(
        "app.services.suggestion_service.fetch_eu_metadata",
        return_value=fake_meta,
    ):
        mapping = create_user_mapping_from_url(db, url=url, category_id=cat.id)

    assert mapping.source == "user"
    assert mapping.celex_number == "32016R0679"
    assert mapping.source_ver_id is None
    assert mapping.title == "Regulation (EU) 2016/679 — GDPR"


def test_create_with_explicit_title_skips_upstream_fetch():
    """When the caller provides a title, no network call is made."""
    db = _make_db()
    cat = _make_category(db)

    url = "https://legislatie.just.ro/Public/DetaliiDocument/267625"

    from app.services.suggestion_service import create_user_mapping_from_url
    with patch(
        "app.services.suggestion_service.fetch_document",
        side_effect=AssertionError("must not be called"),
    ):
        mapping = create_user_mapping_from_url(
            db, url=url, category_id=cat.id, title="Manual title",
        )

    assert mapping.title == "Manual title"


def test_create_from_unknown_host_raises_value_error():
    db = _make_db()
    cat = _make_category(db)

    from app.services.suggestion_service import create_user_mapping_from_url
    try:
        create_user_mapping_from_url(
            db, url="https://example.com/foo", category_id=cat.id,
        )
    except ValueError as e:
        assert "host" in str(e).lower() or "url" in str(e).lower()
    else:
        raise AssertionError("expected ValueError")


def test_create_from_url_without_identifier_raises_value_error():
    """A legislatie.just.ro URL with no extractable ver_id is rejected."""
    db = _make_db()
    cat = _make_category(db)

    from app.services.suggestion_service import create_user_mapping_from_url
    try:
        create_user_mapping_from_url(
            db, url="https://legislatie.just.ro/Public/DetaliiDocument/", category_id=cat.id,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_create_is_idempotent_when_source_url_already_mapped():
    """Posting the same URL twice returns the existing mapping, not a duplicate."""
    db = _make_db()
    cat = _make_category(db)

    url = "https://legislatie.just.ro/Public/DetaliiDocument/267625"
    fake_doc = {"document": {"title": "Legea 31/1990"}}

    from app.services.suggestion_service import create_user_mapping_from_url
    with patch(
        "app.services.suggestion_service.fetch_document",
        return_value=fake_doc,
    ):
        first = create_user_mapping_from_url(db, url=url, category_id=cat.id)
        second = create_user_mapping_from_url(db, url=url, category_id=cat.id)

    assert first.id == second.id
    count = db.query(LawMapping).filter(LawMapping.source_url == url).count()
    assert count == 1


# ---------- fork_to_user_if_needed ----------

def test_fork_flips_system_mapping_to_user():
    db = _make_db()
    cat = _make_category(db)
    m = LawMapping(title="x", category_id=cat.id, source="system")
    db.add(m)
    db.commit()

    from app.services.suggestion_service import fork_to_user_if_needed
    fork_to_user_if_needed(m)

    assert m.source == "user"


def test_fork_leaves_user_mapping_unchanged():
    db = _make_db()
    cat = _make_category(db)
    m = LawMapping(title="x", category_id=cat.id, source="user")
    db.add(m)
    db.commit()

    from app.services.suggestion_service import fork_to_user_if_needed
    fork_to_user_if_needed(m)

    assert m.source == "user"
