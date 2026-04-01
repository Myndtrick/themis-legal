"""Tests for rewritten EU XHTML parser (ID-driven structural parsing)."""
from pathlib import Path
from app.services.eu_html_parser import parse_eu_xhtml

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_gdpr_title():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    assert "REGULAMENTUL" in result["title"]
    assert "2016/679" in result["title"]


def test_gdpr_has_chapters_in_default_book():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    books = result["books_data"]
    assert len(books) == 1
    book = books[0]
    assert book["book_id"] == "default"
    titles = book["titles"]
    assert len(titles) == 1
    chapters = titles[0]["chapters"]
    assert len(chapters) >= 2
    ch1 = chapters[0]
    assert ch1["chapter_id"] == "I"
    assert "Dispoziții generale" in ch1["title"]


def test_gdpr_chapter_articles():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    chapters = result["books_data"][0]["titles"][0]["chapters"]
    ch1 = chapters[0]
    assert "1" in ch1["articles"]
    assert "2" in ch1["articles"]
    ch2 = chapters[1]
    assert "5" in ch2["articles"]


def test_directive_has_title_chapter_section_hierarchy():
    html = (FIXTURES / "eu_directive_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    books = result["books_data"]
    book = books[0]
    titles = book["titles"]
    assert len(titles) >= 2
    tis1 = titles[0]
    assert tis1["title_id"] == "I"
    assert "INTRODUCTIVE" in tis1["title"]
    tis2 = titles[1]
    assert tis2["title_id"] == "II"
    chapters = tis2["chapters"]
    assert len(chapters) >= 1
    cpt1 = chapters[0]
    assert cpt1["chapter_id"] == "I"
    sections = cpt1["sections"]
    assert len(sections) >= 2
    assert sections[0]["section_id"] == "1"
    assert "Definiții" in sections[0]["title"]
    assert "2" in sections[0]["articles"]


def test_gdpr_all_articles_present():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    articles = result["articles"]
    assert "1" in articles
    assert "2" in articles
    assert "5" in articles


def test_article_number_and_title():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    art1 = result["articles"]["1"]
    assert art1["label"] == "1"
    assert art1["article_title"] == "Obiect și obiective"


def test_article_paragraphs_separated():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    art1 = result["articles"]["1"]
    assert len(art1["paragraphs"]) == 3
    assert art1["paragraphs"][0]["label"] == "(1)"
    assert "stabilește normele" in art1["paragraphs"][0]["text"]
    assert art1["paragraphs"][1]["label"] == "(2)"
    assert art1["paragraphs"][2]["label"] == "(3)"


def test_table_subclauses_extracted():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    art2 = result["articles"]["2"]
    para2 = art2["paragraphs"][1]  # paragraph (2)
    assert len(para2["subparagraphs"]) == 3
    assert para2["subparagraphs"][0]["label"] == "(a)"
    assert para2["subparagraphs"][1]["label"] == "(b)"
    assert para2["subparagraphs"][2]["label"] == "(c)"


def test_nested_subclauses():
    html = (FIXTURES / "eu_directive_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    art2 = result["articles"]["2"]
    para1 = art2["paragraphs"][0]
    sub_f = [s for s in para1["subparagraphs"] if s["label"] == "(f)"]
    assert len(sub_f) == 1
    assert "(i)" in sub_f[0]["text"] or "planificarea" in sub_f[0]["text"]


def test_preamble_citations():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    preamble = result["preamble"]
    assert len(preamble["citations"]) == 2
    assert "Tratatul" in preamble["citations"][0]["text"]


def test_preamble_recitals():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    preamble = result["preamble"]
    assert len(preamble["recitals"]) == 2
    assert preamble["recitals"][0]["number"] == "1"
    assert "drept fundamental" in preamble["recitals"][0]["text"]


def test_parse_empty_html():
    result = parse_eu_xhtml("<html><body></body></html>")
    assert result["title"] == ""
    assert result["articles"] == {}
    assert result["books_data"] == []
    assert result["preamble"]["citations"] == []
    assert result["preamble"]["recitals"] == []


def test_annexes_empty_for_gdpr_sample():
    """The GDPR sample fixture has no annexes."""
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    assert result["annexes"] == []


def test_article_full_text_assembled():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    art1 = result["articles"]["1"]
    assert "Articolul 1" in art1["full_text"]
    assert "Obiect și obiective" in art1["full_text"]
    assert "(1)" in art1["full_text"]
    assert "(2)" in art1["full_text"]
    assert "(3)" in art1["full_text"]


def test_directive_article_in_section():
    html = (FIXTURES / "eu_directive_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    titles = result["books_data"][0]["titles"]
    tis2 = titles[1]
    cpt1 = tis2["chapters"][0]
    sct2 = cpt1["sections"][1]
    assert sct2["section_id"] == "2"
    assert "Membri" in sct2["title"]
    assert "3" in sct2["articles"]


def test_directive_article_title_in_title():
    """Article 1 should be directly in Title I (no chapter)."""
    html = (FIXTURES / "eu_directive_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    tis1 = result["books_data"][0]["titles"][0]
    assert "1" in tis1["articles"]
