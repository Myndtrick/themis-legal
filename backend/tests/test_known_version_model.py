"""Tests for the KnownVersion model and Law.last_checked_at field."""
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models.law import Law, LawVersion, KnownVersion
import app.models.category  # noqa: F401 — registers Category table in metadata


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_known_version_creation():
    db = _make_db()
    law = Law(title="Legea societatilor", law_number="31", law_year=1990)
    db.add(law)
    db.flush()

    kv = KnownVersion(
        law_id=law.id,
        ver_id="267625",
        date_in_force=datetime.date(2024, 12, 6),
        is_current=True,
        discovered_at=datetime.datetime.utcnow(),
    )
    db.add(kv)
    db.commit()

    result = db.query(KnownVersion).filter(KnownVersion.law_id == law.id).all()
    assert len(result) == 1
    assert result[0].ver_id == "267625"
    assert result[0].is_current is True


def test_known_version_unique_constraint():
    db = _make_db()
    law = Law(title="Test law", law_number="1", law_year=2020)
    db.add(law)
    db.flush()

    kv1 = KnownVersion(
        law_id=law.id, ver_id="111", date_in_force=datetime.date(2020, 1, 1),
        discovered_at=datetime.datetime.utcnow(),
    )
    db.add(kv1)
    db.commit()

    kv2 = KnownVersion(
        law_id=law.id, ver_id="111", date_in_force=datetime.date(2020, 6, 1),
        discovered_at=datetime.datetime.utcnow(),
    )
    db.add(kv2)
    try:
        db.commit()
        assert False, "Should have raised IntegrityError"
    except Exception:
        db.rollback()


def test_law_last_checked_at_default_null():
    db = _make_db()
    law = Law(title="Test", law_number="2", law_year=2021)
    db.add(law)
    db.commit()
    assert law.last_checked_at is None


def test_law_last_checked_at_can_be_set():
    db = _make_db()
    law = Law(title="Test", law_number="3", law_year=2022)
    db.add(law)
    db.flush()
    law.last_checked_at = datetime.datetime(2026, 3, 27, 3, 15)
    db.commit()
    assert law.last_checked_at == datetime.datetime(2026, 3, 27, 3, 15)
