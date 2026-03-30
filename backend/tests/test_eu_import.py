"""Integration tests for EU law import with mocked CELLAR API."""
import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models.law import Law, LawVersion, Article, StructuralElement, Annex
from app.models.category import CategoryGroup, Category
import app.models.category  # noqa: F401
from app.services.eu_cellar_service import import_eu_law

FIXTURES = Path(__file__).parent / "fixtures"


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    group = CategoryGroup(slug="eu", name_ro="UE", name_en="EU", color_hex="#185FA5", sort_order=9)
    db.add(group)
    db.flush()
    for slug, name_en in [("eu.regulation", "EU regulations"), ("eu.directive", "EU directives"),
                           ("eu.decision", "EU decisions"), ("eu.treaty", "EU treaties")]:
        db.add(Category(group_id=group.id, slug=slug, name_ro=name_en, name_en=name_en, is_eu=True, sort_order=1))
    db.commit()
    return db


def _mock_metadata(celex="32016R0679"):
    return {
        "celex": celex,
        "cellar_uri": "http://publications.europa.eu/resource/cellar/fake-uuid",
        "title": "REGULATION (EU) 2016/679 (General Data Protection Regulation)",
        "date": "2016-04-27",
        "in_force": True,
        "doc_type": "regulation",
    }


@patch("app.services.eu_cellar_service.fetch_consolidated_versions", return_value=[])
@patch("app.services.eu_cellar_service.fetch_eu_content")
@patch("app.services.eu_cellar_service.fetch_eu_metadata")
def test_import_eu_law_basic(mock_meta, mock_content, mock_consol):
    db = _make_db()
    mock_meta.return_value = _mock_metadata()
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    from app.services.eu_html_parser import parse_eu_xhtml
    mock_content.return_value = (parse_eu_xhtml(html), "ro")

    result = import_eu_law(db, "32016R0679", import_history=False)

    assert result["law_id"] is not None
    assert result["document_type"] == "regulation"
    assert result["versions_imported"] == 1

    law = db.query(Law).get(result["law_id"])
    assert law.source == "eu"
    assert law.celex_number == "32016R0679"
    assert law.category.slug == "eu.regulation"

    version = db.query(LawVersion).filter_by(law_id=law.id).first()
    assert version.language == "ro"
    assert version.is_current is True

    articles = db.query(Article).filter_by(law_version_id=version.id).all()
    assert len(articles) >= 3

    chapters = db.query(StructuralElement).filter_by(law_version_id=version.id).all()
    assert len(chapters) >= 2


@patch("app.services.eu_cellar_service.fetch_consolidated_versions", return_value=[])
@patch("app.services.eu_cellar_service.fetch_eu_content")
@patch("app.services.eu_cellar_service.fetch_eu_metadata")
def test_import_duplicate_celex_raises(mock_meta, mock_content, mock_consol):
    db = _make_db()
    mock_meta.return_value = _mock_metadata()
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    from app.services.eu_html_parser import parse_eu_xhtml
    mock_content.return_value = (parse_eu_xhtml(html), "ro")

    import_eu_law(db, "32016R0679", import_history=False)

    try:
        import_eu_law(db, "32016R0679", import_history=False)
        assert False, "Should have raised ValueError for duplicate"
    except ValueError as e:
        assert "already imported" in str(e)


@patch("app.services.eu_cellar_service.fetch_consolidated_versions", return_value=[])
@patch("app.services.eu_cellar_service.fetch_eu_content")
@patch("app.services.eu_cellar_service.fetch_eu_metadata")
def test_import_directive_autocategorized(mock_meta, mock_content, mock_consol):
    db = _make_db()
    meta = _mock_metadata("32022L2555")
    meta["title"] = "DIRECTIVE (EU) 2022/2555 (NIS 2 Directive)"
    meta["doc_type"] = "directive"
    mock_meta.return_value = meta
    html = (FIXTURES / "eu_directive_sample.xhtml").read_text()
    from app.services.eu_html_parser import parse_eu_xhtml
    mock_content.return_value = (parse_eu_xhtml(html), "en")

    result = import_eu_law(db, "32022L2555", import_history=False)

    law = db.query(Law).get(result["law_id"])
    assert law.category.slug == "eu.directive"
    assert law.category_confidence == "auto"

    version = db.query(LawVersion).filter_by(law_id=law.id).first()
    assert version.language == "en"
