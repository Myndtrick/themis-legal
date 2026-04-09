"""Tests for diff summary computation."""
import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.law import Article, Law, LawVersion
from app.models.category import Category  # noqa: F401 – needed so Base.metadata includes categories table


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def law_with_two_versions(db):
    """Create a law with two versions, each having articles."""
    law = Law(title="Test Law", law_number="1", law_year=2025)
    db.add(law)
    db.flush()

    v1 = LawVersion(
        law_id=law.id,
        ver_id="100",
        date_in_force=datetime.date(2025, 1, 1),
        state="actual",
        is_current=False,
    )
    db.add(v1)
    db.flush()

    for num, text in [("1", "First article text"), ("2", "Second article"), ("3", "Third article")]:
        db.add(Article(law_version_id=v1.id, article_number=num, full_text=text, order_index=int(num)))
    db.flush()

    v2 = LawVersion(
        law_id=law.id,
        ver_id="200",
        date_in_force=datetime.date(2025, 6, 1),
        state="actual",
        is_current=True,
    )
    db.add(v2)
    db.flush()

    for num, text in [("1", "First article text AMENDED"), ("2", "Second article"), ("4", "Brand new article")]:
        db.add(Article(law_version_id=v2.id, article_number=num, full_text=text, order_index=int(num)))
    db.flush()

    return law, v1, v2


def test_compute_diff_summary(db, law_with_two_versions):
    from app.services.diff_summary import compute_diff_summary
    law, v1, v2 = law_with_two_versions
    result = compute_diff_summary(db, v2)
    assert result == {"modified": 1, "added": 1, "removed": 1}


def test_compute_diff_summary_no_predecessor(db):
    from app.services.diff_summary import compute_diff_summary
    law = Law(title="Test", law_number="2", law_year=2025)
    db.add(law)
    db.flush()
    v1 = LawVersion(law_id=law.id, ver_id="300", date_in_force=datetime.date(2025, 1, 1), state="actual", is_current=True)
    db.add(v1)
    db.flush()
    result = compute_diff_summary(db, v1)
    assert result is None


def test_compute_diff_summary_identical_versions(db):
    from app.services.diff_summary import compute_diff_summary
    law = Law(title="Test", law_number="3", law_year=2025)
    db.add(law)
    db.flush()
    v1 = LawVersion(law_id=law.id, ver_id="400", date_in_force=datetime.date(2025, 1, 1), state="actual")
    db.add(v1)
    db.flush()
    db.add(Article(law_version_id=v1.id, article_number="1", full_text="Same text", order_index=0))
    db.flush()
    v2 = LawVersion(law_id=law.id, ver_id="500", date_in_force=datetime.date(2025, 6, 1), state="actual")
    db.add(v2)
    db.flush()
    db.add(Article(law_version_id=v2.id, article_number="1", full_text="Same text", order_index=0))
    db.flush()
    result = compute_diff_summary(db, v2)
    assert result == {"modified": 0, "added": 0, "removed": 0}


def test_backfill_diff_summaries(db, law_with_two_versions):
    from app.services.diff_summary import backfill_diff_summaries
    law, v1, v2 = law_with_two_versions
    count = backfill_diff_summaries(db)
    assert count == 1
    db.refresh(v2)
    assert v2.diff_summary == {"modified": 1, "added": 1, "removed": 1}
    db.refresh(v1)
    assert v1.diff_summary is None


def test_backfill_diff_summaries_scoped_to_law(db, law_with_two_versions):
    """When law_id is given, only that law's versions are touched.

    Regression: a global scan from per-import runners caused SQLite writer
    contention and stuck `running` jobs when two imports ran in parallel.
    """
    from app.services.diff_summary import backfill_diff_summaries

    target_law, _, target_v2 = law_with_two_versions

    # A second, unrelated law also has a NULL-summary version.
    other_law = Law(title="Other Law", law_number="99", law_year=2025)
    db.add(other_law)
    db.flush()
    other_v1 = LawVersion(
        law_id=other_law.id,
        ver_id="900",
        date_in_force=datetime.date(2025, 1, 1),
        state="actual",
    )
    db.add(other_v1)
    db.flush()
    db.add(Article(law_version_id=other_v1.id, article_number="1", full_text="A", order_index=0))
    other_v2 = LawVersion(
        law_id=other_law.id,
        ver_id="901",
        date_in_force=datetime.date(2025, 6, 1),
        state="actual",
    )
    db.add(other_v2)
    db.flush()
    db.add(Article(law_version_id=other_v2.id, article_number="1", full_text="B", order_index=0))
    db.flush()

    count = backfill_diff_summaries(db, law_id=target_law.id)
    assert count == 1

    db.refresh(target_v2)
    assert target_v2.diff_summary == {"modified": 1, "added": 1, "removed": 1}

    # The other law's NULL summary must be untouched.
    db.refresh(other_v2)
    assert other_v2.diff_summary is None
