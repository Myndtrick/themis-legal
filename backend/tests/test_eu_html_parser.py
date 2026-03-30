"""Tests for EUR-Lex XHTML parser."""
from pathlib import Path
from app.services.eu_html_parser import parse_eu_xhtml

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_gdpr_title():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    assert "REGULATION" in result["title"]
    assert "2016/679" in result["title"]


def test_parse_gdpr_articles():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    articles = result["articles"]
    assert len(articles) >= 3
    art1 = next(a for a in articles if a["number"] == "1")
    assert "Subject-matter" in art1["label"]
    assert "protection of natural persons" in art1["full_text"]


def test_parse_gdpr_article_paragraphs():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    art1 = next(a for a in result["articles"] if a["number"] == "1")
    assert len(art1["paragraphs"]) == 3
    assert "lays down rules" in art1["paragraphs"][0]["text"]


def test_parse_gdpr_chapters():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    chapters = result["structure"]
    assert len(chapters) >= 2
    ch1 = chapters[0]
    assert ch1["type"] == "chapter"
    assert "I" in ch1["number"]
    assert "General provisions" in ch1["title"]


def test_parse_gdpr_article_chapter_assignment():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    art1 = next(a for a in result["articles"] if a["number"] == "1")
    assert art1["chapter_number"] == "I"


def test_parse_gdpr_annexes():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    annexes = result["annexes"]
    assert len(annexes) >= 1
    assert "ANNEX" in annexes[0]["title"]


def test_parse_directive_sample():
    html = (FIXTURES / "eu_directive_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    assert "DIRECTIVE" in result["title"]
    assert len(result["articles"]) >= 3
    assert len(result["structure"]) >= 2


def test_parse_empty_html():
    result = parse_eu_xhtml("<html><body></body></html>")
    assert result["title"] == ""
    assert result["articles"] == []
    assert result["structure"] == []
    assert result["annexes"] == []
