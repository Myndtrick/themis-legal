"""Tests for version-aware law mapping using KnownVersion."""
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.law import KnownVersion, Law, LawVersion
from app.services.law_mapping import check_laws_in_db
import app.models.category  # register categories table


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _setup_law_with_versions(db):
    """Create a law with one imported version and three known versions."""
    law = Law(title="Legea societatilor", law_number="31", law_year=1990)
    db.add(law)
    db.flush()

    # Imported version (older)
    lv = LawVersion(
        law_id=law.id, ver_id="250000",
        date_in_force=datetime.date(2024, 6, 15), is_current=True,
    )
    db.add(lv)

    # Known versions
    for vid, dif, current in [
        ("300000", datetime.date(2025, 9, 15), True),
        ("267625", datetime.date(2024, 12, 6), False),
        ("250000", datetime.date(2024, 6, 15), False),
    ]:
        kv = KnownVersion(
            law_id=law.id, ver_id=vid, date_in_force=dif,
            is_current=current, discovered_at=datetime.datetime.utcnow(),
        )
        db.add(kv)

    db.commit()
    return law


def test_version_status_stale():
    """Law has imported version but a newer known version exists."""
    db = _make_db()
    _setup_law_with_versions(db)

    laws = [{"law_number": "31", "law_year": "1990", "role": "PRIMARY"}]
    result = check_laws_in_db(laws, db, law_date_map={"31/1990": "2026-03-27"})

    assert result[0]["availability"] == "available"
    assert result[0]["version_status"] == "stale"
    assert result[0]["official_current_ver_id"] == "300000"
    assert result[0]["official_current_date"] == "2025-09-15"


def test_version_status_up_to_date():
    """Law's current known version is imported."""
    db = _make_db()
    law = Law(title="Test", law_number="5", law_year=2020)
    db.add(law)
    db.flush()

    lv = LawVersion(
        law_id=law.id, ver_id="111", date_in_force=datetime.date(2025, 1, 1),
        is_current=True,
    )
    db.add(lv)

    kv = KnownVersion(
        law_id=law.id, ver_id="111", date_in_force=datetime.date(2025, 1, 1),
        is_current=True, discovered_at=datetime.datetime.utcnow(),
    )
    db.add(kv)
    db.commit()

    laws = [{"law_number": "5", "law_year": "2020", "role": "PRIMARY"}]
    result = check_laws_in_db(laws, db, law_date_map={"5/2020": "2026-03-27"})

    assert result[0]["version_status"] == "up_to_date"


def test_version_status_not_checked():
    """Law exists and is imported but has no KnownVersion records."""
    db = _make_db()
    law = Law(title="Test", law_number="10", law_year=2021)
    db.add(law)
    db.flush()

    lv = LawVersion(
        law_id=law.id, ver_id="222", date_in_force=datetime.date(2024, 1, 1),
        is_current=True,
    )
    db.add(lv)
    db.commit()

    laws = [{"law_number": "10", "law_year": "2021", "role": "PRIMARY"}]
    result = check_laws_in_db(laws, db, law_date_map={"10/2021": "2026-03-27"})

    assert result[0]["availability"] == "available"
    assert result[0]["version_status"] == "not_checked"


def test_version_status_missing_law():
    """Law not in DB at all."""
    db = _make_db()
    laws = [{"law_number": "999", "law_year": "2099", "role": "PRIMARY"}]
    result = check_laws_in_db(laws, db)
    assert result[0]["availability"] == "missing"
    assert result[0]["version_status"] == "not_checked"
