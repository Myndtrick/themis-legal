"""Tests for the version discovery service."""
import datetime
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.law import Law, LawVersion, KnownVersion
import app.models.category  # register categories table


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _make_law_with_version(db, law_number="31", law_year=1990, ver_id="267625", date_in_force=None):
    law = Law(title=f"Law {law_number}/{law_year}", law_number=law_number, law_year=law_year)
    db.add(law)
    db.flush()
    version = LawVersion(
        law_id=law.id,
        ver_id=ver_id,
        date_in_force=date_in_force or datetime.date(2024, 12, 6),
        is_current=True,
    )
    db.add(version)
    db.commit()
    return law


def test_discover_versions_for_law_finds_new():
    """Discovery finds versions in history that aren't in KnownVersion yet."""
    db = _make_db()
    law = _make_law_with_version(db)

    mock_result = {
        "document": {
            "next_ver": None,
            "history": [
                {"ver_id": "300000", "date": "2025-09-15"},
                {"ver_id": "267625", "date": "2024-12-06"},
                {"ver_id": "250000", "date": "2024-06-15"},
            ],
        }
    }

    from app.services.version_discovery import discover_versions_for_law

    with patch("app.services.version_discovery.fetch_document", return_value=mock_result):
        new_count = discover_versions_for_law(db, law)

    assert new_count == 2  # 300000 and 250000 are new (267625 = current, also added)
    known = db.query(KnownVersion).filter(KnownVersion.law_id == law.id).all()
    assert len(known) == 3  # all 3 history entries
    assert law.last_checked_at is not None

    # Check is_current set correctly (newest = first in history)
    current = [kv for kv in known if kv.is_current]
    assert len(current) == 1
    assert current[0].ver_id == "300000"


def test_discover_versions_skips_existing():
    """Versions already in KnownVersion are not re-inserted."""
    db = _make_db()
    law = _make_law_with_version(db)

    # Pre-populate one known version
    kv = KnownVersion(
        law_id=law.id, ver_id="267625",
        date_in_force=datetime.date(2024, 12, 6),
        is_current=True, discovered_at=datetime.datetime.utcnow(),
    )
    db.add(kv)
    db.commit()

    mock_result = {
        "document": {
            "next_ver": None,
            "history": [
                {"ver_id": "267625", "date": "2024-12-06"},
            ],
        }
    }

    from app.services.version_discovery import discover_versions_for_law

    with patch("app.services.version_discovery.fetch_document", return_value=mock_result):
        new_count = discover_versions_for_law(db, law)

    assert new_count == 0
    known = db.query(KnownVersion).filter(KnownVersion.law_id == law.id).all()
    assert len(known) == 1


def test_discover_versions_handles_fetch_error():
    """If legislatie.just.ro is unreachable, last_checked_at stays unchanged."""
    db = _make_db()
    law = _make_law_with_version(db)
    original_checked = law.last_checked_at  # None

    from app.services.version_discovery import discover_versions_for_law

    with patch("app.services.version_discovery.fetch_document", side_effect=Exception("Connection refused")):
        new_count = discover_versions_for_law(db, law)

    assert new_count == 0
    assert law.last_checked_at == original_checked  # unchanged


def test_discover_versions_uses_next_ver():
    """Discovery follows next_ver pointer to find newer version."""
    db = _make_db()
    law = _make_law_with_version(db)

    # First fetch returns next_ver
    first_result = {
        "document": {
            "next_ver": "300000",
            "history": [{"ver_id": "267625", "date": "2024-12-06"}],
        }
    }
    # Second fetch (of the next_ver) returns its own history
    second_result = {
        "document": {
            "next_ver": None,
            "date_in_force": "2025-09-15",
            "history": [
                {"ver_id": "300000", "date": "2025-09-15"},
                {"ver_id": "267625", "date": "2024-12-06"},
            ],
        }
    }

    from app.services.version_discovery import discover_versions_for_law

    with patch("app.services.version_discovery.fetch_document", side_effect=[first_result, second_result]):
        new_count = discover_versions_for_law(db, law)

    known = db.query(KnownVersion).filter(KnownVersion.law_id == law.id).all()
    ver_ids = {kv.ver_id for kv in known}
    assert "300000" in ver_ids
    assert "267625" in ver_ids


def test_probe_ver_id_prefers_is_current_law_version():
    """When a LawVersion is marked is_current, the probe helper returns its ver_id."""
    db = _make_db()
    law = Law(title="Test", law_number="100", law_year=2020)
    db.add(law)
    db.flush()

    db.add(LawVersion(law_id=law.id, ver_id="OLD",
                      date_in_force=datetime.date(2020, 1, 1), is_current=False))
    db.add(LawVersion(law_id=law.id, ver_id="CURRENT",
                      date_in_force=datetime.date(2024, 6, 1), is_current=True))
    db.commit()

    from app.services.version_discovery import _get_probe_ver_id
    assert _get_probe_ver_id(db, law) == "CURRENT"


def test_probe_ver_id_falls_back_to_newest_law_version_by_date():
    """When no LawVersion is_current, the probe helper returns the newest by date_in_force."""
    db = _make_db()
    law = Law(title="Test", law_number="100", law_year=2020)
    db.add(law)
    db.flush()

    db.add(LawVersion(law_id=law.id, ver_id="OLDEST",
                      date_in_force=datetime.date(2020, 1, 1), is_current=False))
    db.add(LawVersion(law_id=law.id, ver_id="NEWEST",
                      date_in_force=datetime.date(2024, 6, 1), is_current=False))
    db.add(LawVersion(law_id=law.id, ver_id="MIDDLE",
                      date_in_force=datetime.date(2022, 3, 1), is_current=False))
    db.commit()

    from app.services.version_discovery import _get_probe_ver_id
    assert _get_probe_ver_id(db, law) == "NEWEST"


def test_probe_ver_id_falls_back_to_newest_known_version_when_no_imports():
    """When no LawVersions exist at all, the probe helper returns the newest KnownVersion."""
    db = _make_db()
    law = Law(title="Test", law_number="100", law_year=2020)
    db.add(law)
    db.flush()

    db.add(KnownVersion(law_id=law.id, ver_id="KV_OLD",
                        date_in_force=datetime.date(2020, 1, 1),
                        is_current=False, discovered_at=datetime.datetime.utcnow()))
    db.add(KnownVersion(law_id=law.id, ver_id="KV_NEW",
                        date_in_force=datetime.date(2024, 6, 1),
                        is_current=True, discovered_at=datetime.datetime.utcnow()))
    db.commit()

    from app.services.version_discovery import _get_probe_ver_id
    assert _get_probe_ver_id(db, law) == "KV_NEW"


def test_probe_ver_id_returns_none_when_truly_empty():
    """A law with no LawVersions and no KnownVersions returns None."""
    db = _make_db()
    law = Law(title="Test", law_number="100", law_year=2020)
    db.add(law)
    db.commit()

    from app.services.version_discovery import _get_probe_ver_id
    assert _get_probe_ver_id(db, law) is None
