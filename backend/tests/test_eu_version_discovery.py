"""Tests for the EU version discovery service.

These tests cover the dead-state self-heal bug class: discovery must
re-derive `is_current` on every successful run, not just when new
versions are found, and must propagate the truth to LawVersion rows
the same way the RO discovery does.
"""
import datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.law import KnownVersion, Law, LawVersion
import app.models.category  # register categories table  # noqa: F401


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _make_eu_law(db, celex="32016R0679"):
    law = Law(
        title="Test EU Reg",
        law_number="679",
        law_year=2016,
        source="eu",
        celex_number=celex,
    )
    db.add(law)
    db.flush()
    return law


def test_eu_discovery_self_heals_known_version_is_current_when_no_new_versions():
    """Dead state: KnownVersions exist but none is_current. Discovery finds
    nothing new upstream. The newest existing KnownVersion must be flipped
    to is_current=True anyway."""
    db = _make_db()
    law = _make_eu_law(db)

    db.add(KnownVersion(
        law_id=law.id, ver_id="32016R0679-20160504",
        date_in_force=datetime.date(2016, 5, 4),
        is_current=False, discovered_at=datetime.datetime.utcnow(),
    ))
    db.add(KnownVersion(
        law_id=law.id, ver_id="32016R0679-20180523",
        date_in_force=datetime.date(2018, 5, 23),
        is_current=False, discovered_at=datetime.datetime.utcnow(),
    ))
    db.commit()

    # SPARQL returns the same two versions — no new discoveries
    mock_versions = [
        {"celex": "32016R0679-20180523", "date": "2018-05-23"},
        {"celex": "32016R0679-20160504", "date": "2016-05-04"},
    ]

    from app.services.eu_version_discovery import discover_eu_versions_for_law
    with patch(
        "app.services.eu_version_discovery.fetch_consolidated_versions",
        return_value=mock_versions,
    ):
        new_count = discover_eu_versions_for_law(db, law)

    assert new_count == 0
    current = db.query(KnownVersion).filter(
        KnownVersion.law_id == law.id, KnownVersion.is_current == True  # noqa: E712
    ).all()
    assert len(current) == 1
    assert current[0].ver_id == "32016R0679-20180523"


def test_eu_discovery_self_heals_law_version_is_current_when_no_new_versions():
    """When the LawVersion for the newest CELEX has is_current=False but
    upstream confirms it's the latest, discovery must flip the LawVersion's
    is_current to True — even though no new versions were found."""
    db = _make_db()
    law = _make_eu_law(db)

    db.add(LawVersion(
        law_id=law.id, ver_id="32016R0679-20180523",
        date_in_force=datetime.date(2018, 5, 23), is_current=False,
    ))
    db.add(KnownVersion(
        law_id=law.id, ver_id="32016R0679-20180523",
        date_in_force=datetime.date(2018, 5, 23),
        is_current=False, discovered_at=datetime.datetime.utcnow(),
    ))
    db.commit()

    mock_versions = [
        {"celex": "32016R0679-20180523", "date": "2018-05-23"},
    ]

    from app.services.eu_version_discovery import discover_eu_versions_for_law
    with patch(
        "app.services.eu_version_discovery.fetch_consolidated_versions",
        return_value=mock_versions,
    ):
        discover_eu_versions_for_law(db, law)

    lv = db.query(LawVersion).filter(LawVersion.ver_id == "32016R0679-20180523").one()
    assert lv.is_current is True


def test_eu_discovery_does_not_falsely_mark_unimported_law_version_current():
    """When upstream's newest CELEX is NOT imported as a LawVersion, no
    LawVersion should be marked current. (Same semantic as the RO
    `preserves_dead_state` test — we're not up to date and that's the truth.)"""
    db = _make_db()
    law = _make_eu_law(db)

    db.add(LawVersion(
        law_id=law.id, ver_id="32016R0679-20160504",
        date_in_force=datetime.date(2016, 5, 4), is_current=True,
    ))
    db.commit()

    # Upstream has a newer consolidated version we don't have imported
    mock_versions = [
        {"celex": "32016R0679-20180523", "date": "2018-05-23"},
        {"celex": "32016R0679-20160504", "date": "2016-05-04"},
    ]

    from app.services.eu_version_discovery import discover_eu_versions_for_law
    with patch(
        "app.services.eu_version_discovery.fetch_consolidated_versions",
        return_value=mock_versions,
    ):
        discover_eu_versions_for_law(db, law)

    # The KnownVersion for the newer one should be is_current=True
    kv_new = db.query(KnownVersion).filter(
        KnownVersion.ver_id == "32016R0679-20180523"
    ).one()
    assert kv_new.is_current is True

    # But the imported LawVersion (which is the OLDER one) must NOT
    # remain falsely marked current.
    lv = db.query(LawVersion).filter(LawVersion.ver_id == "32016R0679-20160504").one()
    assert lv.is_current is False
