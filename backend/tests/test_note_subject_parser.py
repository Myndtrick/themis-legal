"""Unit tests for note_subject_parser — leropa Note.subject → structural labels."""
from app.services.note_subject_parser import parse, ParsedSubject


def test_article_only():
    assert parse("Articolul 336") == ParsedSubject(
        article_label="336", paragraph_label=None, subparagraph_label=None
    )


def test_article_with_caret_label():
    assert parse("Articolul 1^2") == ParsedSubject(
        article_label="1^2", paragraph_label=None, subparagraph_label=None
    )


def test_paragraph_of_article():
    assert parse("Alineatul (1) al articolului 336") == ParsedSubject(
        article_label="336", paragraph_label="(1)", subparagraph_label=None
    )


def test_paragraph_with_caret_label():
    assert parse("Alineatul (2^1) al articolului 5") == ParsedSubject(
        article_label="5", paragraph_label="(2^1)", subparagraph_label=None
    )


def test_litera_of_paragraph_of_article():
    assert parse("Litera a) a alineatului (2) al articolului 336") == ParsedSubject(
        article_label="336", paragraph_label="(2)", subparagraph_label="a)"
    )


def test_comma_separated_form():
    assert parse("Articolul 5, alineatul (1), litera c)") == ParsedSubject(
        article_label="5", paragraph_label="(1)", subparagraph_label="c)"
    )


def test_unknown_subject_returns_empty():
    assert parse("Punctul 9. al articolului I") == ParsedSubject(
        article_label="I", paragraph_label=None, subparagraph_label=None
    )


def test_completely_unknown_returns_all_none():
    assert parse("Anexa 1") == ParsedSubject(
        article_label=None, paragraph_label=None, subparagraph_label=None
    )


def test_none_input_returns_empty():
    assert parse(None) == ParsedSubject(
        article_label=None, paragraph_label=None, subparagraph_label=None
    )


def test_empty_string_returns_empty():
    assert parse("") == ParsedSubject(
        article_label=None, paragraph_label=None, subparagraph_label=None
    )
