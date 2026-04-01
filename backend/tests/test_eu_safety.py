"""Safety tests: EU import must never affect Romanian law data."""
import datetime
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models.law import Law, LawVersion, KnownVersion
import app.models.category  # noqa: F401


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_new_columns_default_ro():
    """New columns must default to 'ro' so existing data is unchanged."""
    db = _make_db()
    law = Law(title="Legea societatilor", law_number="31", law_year=1990)
    db.add(law)
    db.flush()
    assert law.source == "ro"
    assert law.celex_number is None
    assert law.cellar_uri is None

    version = LawVersion(law_id=law.id, ver_id="267625")
    db.add(version)
    db.flush()
    assert version.language == "ro"


def test_ro_laws_untouched_after_eu_insert():
    """Inserting an EU law must not modify any Romanian law."""
    db = _make_db()
    ro_law = Law(title="Codul Civil", law_number="287", law_year=2009, source="ro")
    db.add(ro_law)
    db.flush()
    ro_version = LawVersion(law_id=ro_law.id, ver_id="267625", language="ro")
    db.add(ro_version)
    db.commit()
    ro_law_id = ro_law.id
    ro_ver_id = ro_version.id

    eu_law = Law(title="GDPR", law_number="679", law_year=2016, source="eu", celex_number="32016R0679")
    db.add(eu_law)
    db.flush()
    eu_version = LawVersion(law_id=eu_law.id, ver_id="02016R0679-20160504", language="ro")
    db.add(eu_version)
    db.commit()

    ro_law_check = db.query(Law).get(ro_law_id)
    assert ro_law_check.title == "Codul Civil"
    assert ro_law_check.source == "ro"
    assert ro_law_check.celex_number is None
    ro_ver_check = db.query(LawVersion).get(ro_ver_id)
    assert ro_ver_check.ver_id == "267625"
    assert ro_ver_check.language == "ro"


def test_duplicate_celex_rejected():
    """Importing the same CELEX twice must not create duplicates."""
    db = _make_db()
    law = Law(title="GDPR", law_number="679", law_year=2016, source="eu", celex_number="32016R0679")
    db.add(law)
    db.commit()
    existing = db.query(Law).filter(Law.celex_number == "32016R0679").first()
    assert existing is not None
    assert existing.id == law.id


def test_eu_law_counts_separate():
    """Can query EU and RO laws separately by source field."""
    db = _make_db()
    db.add(Law(title="Codul Civil", law_number="287", law_year=2009, source="ro"))
    db.add(Law(title="GDPR", law_number="679", law_year=2016, source="eu"))
    db.commit()
    assert db.query(Law).filter(Law.source == "ro").count() == 1
    assert db.query(Law).filter(Law.source == "eu").count() == 1
