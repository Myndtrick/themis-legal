"""Tests for CELEX number parsing and EU document type mapping."""
from app.services.eu_cellar_service import parse_celex, celex_to_document_type, celex_to_category_slug


def test_parse_celex_regulation():
    result = parse_celex("32016R0679")
    assert result == {"sector": "3", "year": "2016", "type_code": "R", "number": "0679"}


def test_parse_celex_directive():
    result = parse_celex("32022L2555")
    assert result == {"sector": "3", "year": "2022", "type_code": "L", "number": "2555"}


def test_parse_celex_decision():
    result = parse_celex("32021D0914")
    assert result == {"sector": "3", "year": "2021", "type_code": "D", "number": "0914"}


def test_parse_celex_consolidated():
    result = parse_celex("02016R0679-20160504")
    assert result == {"sector": "0", "year": "2016", "type_code": "R", "number": "0679", "consol_date": "20160504"}


def test_parse_celex_treaty():
    result = parse_celex("12012M/TXT")
    assert result == {"sector": "1", "year": "2012", "type_code": "M", "number": "TXT"}


def test_parse_celex_invalid_returns_none():
    assert parse_celex("not-a-celex") is None
    assert parse_celex("") is None


def test_celex_to_document_type():
    assert celex_to_document_type("32016R0679") == "regulation"
    assert celex_to_document_type("32022L2555") == "directive"
    assert celex_to_document_type("32021D0914") == "eu_decision"
    assert celex_to_document_type("12012M/TXT") == "treaty"
    assert celex_to_document_type("invalid") == "other"


def test_celex_to_category_slug():
    assert celex_to_category_slug("32016R0679") == "eu.regulation"
    assert celex_to_category_slug("32022L2555") == "eu.directive"
    assert celex_to_category_slug("32021D0914") == "eu.decision"
    assert celex_to_category_slug("12012M/TXT") == "eu.treaty"
    assert celex_to_category_slug("invalid") is None
