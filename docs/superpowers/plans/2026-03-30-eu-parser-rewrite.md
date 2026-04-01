# EU XHTML Parser Rewrite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the EU XHTML parser to use ID-driven structural parsing, producing the same hierarchy shape as Romanian laws for identical display.

**Architecture:** The new parser walks `div#enc_1` recursively using element `id` attributes (`tis_`, `cpt_`, `sct_`, `art_`) to build a `books_data` + `articles` dict. Table-based sub-clauses are extracted from `<table>` elements with 4%/96% column layout. Preamble is stored as a special "Preambul" article. Storage in `eu_cellar_service.py` creates the same StructuralElement parent-child tree as Romanian laws.

**Tech Stack:** Python, BeautifulSoup4, SQLAlchemy, pytest

**Design spec:** `docs/superpowers/specs/2026-03-30-eu-parser-rewrite-design.md`

---

## File Structure

**Rewrite:**
- `backend/app/services/eu_html_parser.py` — complete rewrite with ID-driven parsing
- `backend/tests/test_eu_html_parser.py` — rewrite all tests for new output shape
- `backend/tests/fixtures/eu_gdpr_sample.xhtml` — update to match real EUR-Lex structure
- `backend/tests/fixtures/eu_directive_sample.xhtml` — update with title→chapter→section nesting

**Modify:**
- `backend/app/services/eu_cellar_service.py` — replace `_store_eu_version` with hierarchy-aware storage
- `backend/tests/test_eu_import.py` — update mocks for new parser output shape

---

## Task 1: Update Test Fixtures to Match Real EUR-Lex XHTML

**Files:**
- Modify: `backend/tests/fixtures/eu_gdpr_sample.xhtml`
- Modify: `backend/tests/fixtures/eu_directive_sample.xhtml`

The current fixtures use `<div id="document1">` and `<table class="oj-table">` which don't match real EUR-Lex HTML. Real XHTML uses `<div class="eli-container">`, `<div id="enc_1">`, `<div id="cpt_I">`, `<div id="art_1">`, and separate tables for each sub-clause.

- [ ] **Step 1: Rewrite GDPR sample fixture**

Replace `backend/tests/fixtures/eu_gdpr_sample.xhtml` with a realistic excerpt that includes:
- `div.eli-container` root
- `div#pbl_1` preamble with 2 citations (`cit_1`, `cit_2`) and 2 recitals (`rct_1`, `rct_2`) using table format
- `div#enc_1` enacting clause
- `div#cpt_I` Chapter I with `eli-title` → `oj-ti-section-2` for chapter title
- `div#art_1` Article 1 with `oj-sti-art` subtitle, 3 paragraphs in `div#001.001`, `div#001.002`, `div#001.003`
- `div#art_2` Article 2 with paragraph (2) containing table-based sub-clauses (a), (b), (c)
- `div#cpt_II` Chapter II with Article 5
- `div#anx_I` Annex I

Each paragraph `<div id="NNN.MMM">` contains `<p class="oj-normal">(N) text...</p>`. Sub-clauses are separate `<table>` elements with `<td>(a)</td><td><p class="oj-normal">text</p></td>`.

The fixture must be a valid, parseable XHTML file that represents the real structure. Use Romanian text labels ("CAPITOLUL I", "Articolul 1", etc.) since the cached files are Romanian.

```html
<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>EUR-Lex - 32016R0679</title></head>
<body>
<div class="eli-container">
  <div class="eli-main-title" id="tit_1">
    <p class="oj-doc-ti">REGULAMENTUL (UE) 2016/679 AL PARLAMENTULUI EUROPEAN ȘI AL CONSILIULUI</p>
    <p class="oj-doc-ti">din 27 aprilie 2016</p>
    <p class="oj-doc-ti">privind protecția persoanelor fizice în ceea ce privește prelucrarea datelor cu caracter personal (Regulamentul general privind protecția datelor)</p>
  </div>
  <div class="eli-subdivision" id="pbl_1">
    <p class="oj-normal">PARLAMENTUL EUROPEAN ȘI CONSILIUL UNIUNII EUROPENE,</p>
    <div class="eli-subdivision" id="cit_1">
      <p class="oj-normal">având în vedere Tratatul privind funcționarea Uniunii Europene, în special articolul 16,</p>
    </div>
    <div class="eli-subdivision" id="cit_2">
      <p class="oj-normal">având în vedere propunerea Comisiei Europene,</p>
    </div>
    <p class="oj-normal">întrucât:</p>
    <div class="eli-subdivision" id="rct_1">
      <table width="100%" border="0" cellspacing="0" cellpadding="0">
        <col width="4%"/><col width="96%"/>
        <tbody><tr>
          <td valign="top"><p class="oj-normal">(1)</p></td>
          <td valign="top"><p class="oj-normal">Protecția persoanelor fizice în ceea ce privește prelucrarea datelor cu caracter personal este un drept fundamental.</p></td>
        </tr></tbody>
      </table>
    </div>
    <div class="eli-subdivision" id="rct_2">
      <table width="100%" border="0" cellspacing="0" cellpadding="0">
        <col width="4%"/><col width="96%"/>
        <tbody><tr>
          <td valign="top"><p class="oj-normal">(2)</p></td>
          <td valign="top"><p class="oj-normal">Principiile și normele referitoare la protecția persoanelor fizice în ceea ce privește prelucrarea datelor lor cu caracter personal ar trebui să le respecte drepturile fundamentale.</p></td>
        </tr></tbody>
      </table>
    </div>
    <p class="oj-normal">ADOPTĂ PREZENTUL REGULAMENT:</p>
  </div>
  <div class="eli-subdivision" id="enc_1">
    <div id="cpt_I">
      <p class="oj-ti-section-1"><span class="oj-italic">CAPITOLUL I</span></p>
      <div class="eli-title" id="cpt_I.tit_1">
        <p class="oj-ti-section-2"><span class="oj-bold"><span class="oj-italic">Dispoziții generale</span></span></p>
      </div>
      <div class="eli-subdivision" id="art_1">
        <p class="oj-ti-art">Articolul 1</p>
        <div class="eli-title" id="art_1.tit_1">
          <p class="oj-sti-art">Obiect și obiective</p>
        </div>
        <div id="001.001">
          <p class="oj-normal">(1)   Prezentul regulament stabilește normele referitoare la protecția persoanelor fizice în ceea ce privește prelucrarea datelor cu caracter personal, precum și normele referitoare la libera circulație a datelor cu caracter personal.</p>
        </div>
        <div id="001.002">
          <p class="oj-normal">(2)   Prezentul regulament asigură protecția drepturilor și libertăților fundamentale ale persoanelor fizice și în special a dreptului acestora la protecția datelor cu caracter personal.</p>
        </div>
        <div id="001.003">
          <p class="oj-normal">(3)   Libera circulație a datelor cu caracter personal în interiorul Uniunii nu poate fi restricționată sau interzisă din motive legate de protecția persoanelor fizice.</p>
        </div>
      </div>
      <div class="eli-subdivision" id="art_2">
        <p class="oj-ti-art">Articolul 2</p>
        <div class="eli-title" id="art_2.tit_1">
          <p class="oj-sti-art">Domeniul de aplicare material</p>
        </div>
        <div id="002.001">
          <p class="oj-normal">(1)   Prezentul regulament se aplică prelucrării datelor cu caracter personal, efectuată total sau parțial prin mijloace automatizate.</p>
        </div>
        <div id="002.002">
          <p class="oj-normal">(2)   Prezentul regulament nu se aplică prelucrării datelor cu caracter personal:</p>
          <table width="100%" border="0" cellspacing="0" cellpadding="0">
            <col width="4%"/><col width="96%"/>
            <tbody><tr>
              <td valign="top"><p class="oj-normal">(a)</p></td>
              <td valign="top"><p class="oj-normal">în cadrul unei activități care nu intră sub incidența dreptului Uniunii;</p></td>
            </tr></tbody>
          </table>
          <table width="100%" border="0" cellspacing="0" cellpadding="0">
            <col width="4%"/><col width="96%"/>
            <tbody><tr>
              <td valign="top"><p class="oj-normal">(b)</p></td>
              <td valign="top"><p class="oj-normal">de către statele membre atunci când desfășoară activități care intră sub incidența capitolului 2 al titlului V din Tratatul UE;</p></td>
            </tr></tbody>
          </table>
          <table width="100%" border="0" cellspacing="0" cellpadding="0">
            <col width="4%"/><col width="96%"/>
            <tbody><tr>
              <td valign="top"><p class="oj-normal">(c)</p></td>
              <td valign="top"><p class="oj-normal">de către o persoană fizică în cadrul unei activități exclusiv personale sau domestice;</p></td>
            </tr></tbody>
          </table>
        </div>
      </div>
    </div>
    <div id="cpt_II">
      <p class="oj-ti-section-1"><span class="oj-italic">CAPITOLUL II</span></p>
      <div class="eli-title" id="cpt_II.tit_1">
        <p class="oj-ti-section-2"><span class="oj-bold"><span class="oj-italic">Principii</span></span></p>
      </div>
      <div class="eli-subdivision" id="art_5">
        <p class="oj-ti-art">Articolul 5</p>
        <div class="eli-title" id="art_5.tit_1">
          <p class="oj-sti-art">Principii legate de prelucrarea datelor cu caracter personal</p>
        </div>
        <div id="005.001">
          <p class="oj-normal">(1)   Datele cu caracter personal sunt:</p>
          <table width="100%" border="0" cellspacing="0" cellpadding="0">
            <col width="4%"/><col width="96%"/>
            <tbody><tr>
              <td valign="top"><p class="oj-normal">(a)</p></td>
              <td valign="top"><p class="oj-normal">prelucrate în mod legal, echitabil și transparent față de persoana vizată;</p></td>
            </tr></tbody>
          </table>
          <table width="100%" border="0" cellspacing="0" cellpadding="0">
            <col width="4%"/><col width="96%"/>
            <tbody><tr>
              <td valign="top"><p class="oj-normal">(b)</p></td>
              <td valign="top"><p class="oj-normal">colectate în scopuri determinate, explicite și legitime;</p></td>
            </tr></tbody>
          </table>
        </div>
        <div id="005.002">
          <p class="oj-normal">(2)   Operatorul este responsabil de respectarea alineatului (1) și poate demonstra această respectare.</p>
        </div>
      </div>
    </div>
  </div>
  <div class="eli-subdivision" id="fnp_1">
    <div class="oj-final">
      <p class="oj-normal">Prezentul regulament este obligatoriu în toate elementele sale și se aplică direct în toate statele membre.</p>
    </div>
  </div>
</div>
</body>
</html>
```

- [ ] **Step 2: Rewrite directive sample fixture with Title→Chapter→Section nesting**

Replace `backend/tests/fixtures/eu_directive_sample.xhtml` with a structure that uses titles containing chapters containing sections (like Regulation 891/2017):

```html
<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>EUR-Lex - 32017R0891</title></head>
<body>
<div class="eli-container">
  <div class="eli-main-title" id="tit_1">
    <p class="oj-doc-ti">REGULAMENTUL DELEGAT (UE) 2017/891 AL COMISIEI</p>
    <p class="oj-doc-ti">din 13 martie 2017</p>
    <p class="oj-doc-ti">de completare a Regulamentului (UE) nr. 1308/2013</p>
  </div>
  <div class="eli-subdivision" id="pbl_1">
    <p class="oj-normal">COMISIA EUROPEANĂ,</p>
    <div class="eli-subdivision" id="cit_1">
      <p class="oj-normal">având în vedere Tratatul privind funcționarea Uniunii Europene,</p>
    </div>
    <p class="oj-normal">întrucât:</p>
    <div class="eli-subdivision" id="rct_1">
      <table width="100%" border="0" cellspacing="0" cellpadding="0">
        <col width="4%"/><col width="96%"/>
        <tbody><tr>
          <td valign="top"><p class="oj-normal">(1)</p></td>
          <td valign="top"><p class="oj-normal">Regulamentul (UE) nr. 1308/2013 stabilește norme privind organizarea comună a piețelor produselor agricole.</p></td>
        </tr></tbody>
      </table>
    </div>
    <p class="oj-normal">ADOPTĂ PREZENTUL REGULAMENT:</p>
  </div>
  <div class="eli-subdivision" id="enc_1">
    <div id="tis_I">
      <p class="oj-ti-section-1">TITLUL I</p>
      <div class="eli-title" id="tis_I.tit_1">
        <p class="oj-ti-section-2"><span class="oj-bold">DISPOZIȚII INTRODUCTIVE</span></p>
      </div>
      <div class="eli-subdivision" id="art_1">
        <p class="oj-ti-art">Articolul 1</p>
        <div class="eli-title" id="art_1.tit_1">
          <p class="oj-sti-art">Obiect</p>
        </div>
        <div id="001.001">
          <p class="oj-normal">Prezentul regulament completează Regulamentul (UE) nr. 1308/2013 în ceea ce privește sectorul fructelor și legumelor.</p>
        </div>
      </div>
    </div>
    <div id="tis_II">
      <p class="oj-ti-section-1">TITLUL II</p>
      <div class="eli-title" id="tis_II.tit_1">
        <p class="oj-ti-section-2"><span class="oj-bold">ORGANIZAȚII DE PRODUCĂTORI</span></p>
      </div>
      <div id="tis_II.cpt_I">
        <p class="oj-ti-section-1"><span class="oj-italic">CAPITOLUL I</span></p>
        <div class="eli-title" id="tis_II.cpt_I.tit_1">
          <p class="oj-ti-section-2"><span class="oj-bold"><span class="oj-italic">Cerințe și recunoaștere</span></span></p>
        </div>
        <div id="tis_II.cpt_I.sct_1">
          <p class="oj-ti-section-1"><span class="oj-expanded">Secțiunea 1</span></p>
          <div class="eli-title" id="tis_II.cpt_I.sct_1.tit_1">
            <p class="oj-ti-section-2"><span class="oj-bold"><span class="oj-expanded">Definiții</span></span></p>
          </div>
          <div class="eli-subdivision" id="art_2">
            <p class="oj-ti-art">Articolul 2</p>
            <div class="eli-title" id="art_2.tit_1">
              <p class="oj-sti-art">Definiții</p>
            </div>
            <div id="002.001">
              <p class="oj-normal">În sensul prezentului regulament, se aplică următoarele definiții:</p>
              <table width="100%" border="0" cellspacing="0" cellpadding="0">
                <col width="4%"/><col width="96%"/>
                <tbody><tr>
                  <td valign="top"><p class="oj-normal">(a)</p></td>
                  <td valign="top"><p class="oj-normal">„produs de bază" înseamnă un produs din sectorul fructelor și legumelor;</p></td>
                </tr></tbody>
              </table>
              <table width="100%" border="0" cellspacing="0" cellpadding="0">
                <col width="4%"/><col width="96%"/>
                <tbody><tr>
                  <td valign="top"><p class="oj-normal">(b)</p></td>
                  <td valign="top"><p class="oj-normal">„pregătire" înseamnă activități de pregătire a produsului;</p></td>
                </tr></tbody>
              </table>
              <table width="100%" border="0" cellspacing="0" cellpadding="0">
                <col width="4%"/><col width="96%"/>
                <tbody><tr>
                  <td valign="top"><p class="oj-normal">(f)</p></td>
                  <td valign="top">
                    <p class="oj-normal">„măsură" înseamnă una dintre următoarele:</p>
                    <table width="100%" border="0" cellspacing="0" cellpadding="0">
                      <col width="4%"/><col width="96%"/>
                      <tbody><tr>
                        <td valign="top"><p class="oj-normal">(i)</p></td>
                        <td valign="top"><p class="oj-normal">acțiuni care vizează planificarea producției;</p></td>
                      </tr></tbody>
                    </table>
                    <table width="100%" border="0" cellspacing="0" cellpadding="0">
                      <col width="4%"/><col width="96%"/>
                      <tbody><tr>
                        <td valign="top"><p class="oj-normal">(ii)</p></td>
                        <td valign="top"><p class="oj-normal">acțiuni care vizează îmbunătățirea calității produselor;</p></td>
                      </tr></tbody>
                    </table>
                  </td>
                </tr></tbody>
              </table>
            </div>
          </div>
        </div>
        <div id="tis_II.cpt_I.sct_2">
          <p class="oj-ti-section-1"><span class="oj-expanded">Secțiunea 2</span></p>
          <div class="eli-title" id="tis_II.cpt_I.sct_2.tit_1">
            <p class="oj-ti-section-2"><span class="oj-bold"><span class="oj-expanded">Membri</span></span></p>
          </div>
          <div class="eli-subdivision" id="art_3">
            <p class="oj-ti-art">Articolul 3</p>
            <div class="eli-title" id="art_3.tit_1">
              <p class="oj-sti-art">Membri</p>
            </div>
            <div id="003.001">
              <p class="oj-normal">(1)   Statele membre pot stabili dacă producătorii care sunt persoane fizice pot fi membri ai organizațiilor de producători.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
```

- [ ] **Step 3: Commit**

```bash
git add backend/tests/fixtures/
git commit -m "test: update EU XHTML fixtures to match real EUR-Lex structure"
```

---

## Task 2: Rewrite Parser — Core + Structural Extraction

**Files:**
- Rewrite: `backend/app/services/eu_html_parser.py`

- [ ] **Step 1: Write failing tests for new output shape**

Create/replace `backend/tests/test_eu_html_parser.py`:

```python
"""Tests for rewritten EU XHTML parser (ID-driven structural parsing)."""
from pathlib import Path
from app.services.eu_html_parser import parse_eu_xhtml

FIXTURES = Path(__file__).parent / "fixtures"


# --- Title extraction ---

def test_parse_gdpr_title():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    assert "REGULAMENTUL" in result["title"]
    assert "2016/679" in result["title"]


# --- Structural hierarchy (books_data) ---

def test_gdpr_has_chapters_in_default_book():
    html = (FIXTURES / "eu_gdpr_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    books = result["books_data"]
    assert len(books) == 1
    book = books[0]
    assert book["book_id"] == "default"
    # Chapters should be nested inside a default title
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
    assert "1" in tis1.get("articles", []) or len(tis1.get("chapters", [])) == 0
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


# --- Article extraction ---

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
    assert art1["label"] == "Art. 1"
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
    assert "activității" in para2["subparagraphs"][0]["text"] or "activitate" in para2["subparagraphs"][0]["text"]
    assert para2["subparagraphs"][1]["label"] == "(b)"
    assert para2["subparagraphs"][2]["label"] == "(c)"


def test_nested_subclauses():
    html = (FIXTURES / "eu_directive_sample.xhtml").read_text()
    result = parse_eu_xhtml(html)
    art2 = result["articles"]["2"]
    para1 = art2["paragraphs"][0]
    # Sub-clause (f) should exist and contain nested (i), (ii) text
    sub_f = [s for s in para1["subparagraphs"] if s["label"] == "(f)"]
    assert len(sub_f) == 1
    assert "(i)" in sub_f[0]["text"] or "planificarea" in sub_f[0]["text"]


# --- Preamble ---

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


# --- Empty input ---

def test_parse_empty_html():
    result = parse_eu_xhtml("<html><body></body></html>")
    assert result["title"] == ""
    assert result["articles"] == {}
    assert result["books_data"] == []
    assert result["preamble"]["citations"] == []
    assert result["preamble"]["recitals"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/anaandrei/projects/themis-legal && python -m pytest backend/tests/test_eu_html_parser.py -v
```

Expected: FAIL — current parser returns different output shape (list instead of dict for articles, no books_data, no preamble).

- [ ] **Step 3: Implement the rewritten parser**

Replace `backend/app/services/eu_html_parser.py` entirely:

```python
"""Parse EUR-Lex XHTML into structured hierarchy using ID-driven parsing.

Produces the same books_data + articles dict shape as leropa_service
so storage code can be shared and EU laws display identically to Romanian laws.
"""
import re
import logging
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

_ARTICLE_NUM_RE = re.compile(
    r"(?:Article|Articolul|Artikel|Articolo|Artículo)\s+(\d+[a-z]?)", re.IGNORECASE
)
_TITLE_NUM_RE = re.compile(
    r"(?:TITLUL|TITLE|TITRE|TITEL)\s+([IVXLCDM]+)", re.IGNORECASE
)
_CHAPTER_NUM_RE = re.compile(
    r"(?:CAPITOLUL|CHAPTER|CHAPITRE|KAPITEL)\s+([IVXLCDM]+)", re.IGNORECASE
)
_SECTION_NUM_RE = re.compile(
    r"(?:Secțiunea|Section|Sektion|Abschnitt)\s+(\d+)", re.IGNORECASE
)
_ANNEX_RE = re.compile(
    r"(?:ANNEX|ANEXA|ANNEXE|ANHANG)\s*([IVXLCDM]*)", re.IGNORECASE
)


def parse_eu_xhtml(html: str) -> dict:
    """Parse EUR-Lex XHTML and return structured data.

    Returns:
        {
            "title": str,
            "preamble": {"citations": [...], "recitals": [...]},
            "books_data": [...],   # same shape as leropa
            "articles": {...},     # dict keyed by article number
            "annexes": [...]
        }
    """
    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup)
    preamble = _extract_preamble(soup)
    books_data, articles = _extract_hierarchy(soup)
    annexes = _extract_annexes(soup)
    return {
        "title": title,
        "preamble": preamble,
        "books_data": books_data,
        "articles": articles,
        "annexes": annexes,
    }


def _extract_title(soup: BeautifulSoup) -> str:
    """Join all oj-doc-ti paragraphs into a single title string."""
    parts = []
    for p in soup.find_all("p", class_="oj-doc-ti"):
        text = p.get_text(strip=True)
        if text:
            parts.append(text)
    return " ".join(parts)


# --- Preamble extraction ---

def _extract_preamble(soup: BeautifulSoup) -> dict:
    """Extract citations and recitals from div#pbl_1."""
    result = {"citations": [], "recitals": []}
    pbl = soup.find("div", id="pbl_1")
    if not pbl:
        return result

    # Citations: div#cit_N
    for cit_div in pbl.find_all("div", id=lambda x: x and x.startswith("cit_")):
        p = cit_div.find("p", class_="oj-normal")
        if p:
            result["citations"].append({
                "number": cit_div.get("id", ""),
                "text": p.get_text(strip=True),
            })

    # Recitals: div#rct_N with table structure
    for rct_div in pbl.find_all("div", id=lambda x: x and x.startswith("rct_")):
        number, text = _parse_table_row(rct_div)
        if text:
            result["recitals"].append({"number": number, "text": text})

    return result


# --- Hierarchy extraction (ID-driven) ---

def _extract_hierarchy(soup: BeautifulSoup) -> tuple[list, dict]:
    """Walk enc_1 recursively using IDs to build books_data + articles dict."""
    articles = {}

    doc = soup.find("div", id="enc_1")
    if not doc:
        doc = soup.find("div", class_="eli-container")
    if not doc:
        return [], articles

    # Detect top-level structure type
    has_titles = any(_child_id_contains(doc, "tis_"))
    has_chapters = any(_child_id_contains(doc, "cpt_"))

    if has_titles:
        titles = _extract_titles(doc, articles)
        book = {
            "book_id": "default",
            "title": None,
            "description": None,
            "articles": [],
            "titles": titles,
        }
    elif has_chapters:
        chapters = _extract_chapters(doc, articles)
        book = {
            "book_id": "default",
            "title": None,
            "description": None,
            "articles": [],
            "titles": [{
                "title_id": "default",
                "title": None,
                "chapters": chapters,
                "articles": [],
            }],
        }
    else:
        # No structural divisions — extract articles directly
        _extract_articles_from(doc, articles)
        book = {
            "book_id": "default",
            "title": None,
            "description": None,
            "articles": list(articles.keys()),
            "titles": [],
        }

    if not articles and not book["titles"]:
        return [], articles

    return [book], articles


def _extract_titles(parent: Tag, articles: dict) -> list:
    """Extract Title-level divisions (tis_I, tis_II, etc.)."""
    titles = []
    for div in _children_with_id_containing(parent, "tis_"):
        div_id = div.get("id", "")
        heading_text = _get_section_heading(div)
        title_match = _TITLE_NUM_RE.search(heading_text)
        title_num = title_match.group(1) if title_match else div_id
        title_name = _get_section_title(div)

        # Titles can contain chapters or articles directly
        chapters = _extract_chapters(div, articles)
        direct_articles = []
        if not chapters:
            _extract_articles_from(div, articles)
            direct_articles = [a_id for a_id in articles if _article_in_div(div, a_id)]

        titles.append({
            "title_id": title_num,
            "title": title_name,
            "chapters": chapters,
            "articles": direct_articles,
        })
    return titles


def _extract_chapters(parent: Tag, articles: dict) -> list:
    """Extract Chapter-level divisions (cpt_I, cpt_II, etc.)."""
    chapters = []
    for div in _children_with_id_containing(parent, "cpt_"):
        div_id = div.get("id", "")
        heading_text = _get_section_heading(div)
        ch_match = _CHAPTER_NUM_RE.search(heading_text)
        ch_num = ch_match.group(1) if ch_match else div_id
        ch_title = _get_section_title(div)

        sections = _extract_sections(div, articles)
        direct_articles = []
        if not sections:
            _extract_articles_from(div, articles)
            direct_articles = [k for k in articles if _article_in_div(div, k)]
        else:
            # Also collect articles directly in chapter (not in any section)
            for art_div in div.find_all("div", id=lambda x: x and x.startswith("art_"), recursive=False):
                _parse_article(art_div, articles)

        chapters.append({
            "chapter_id": ch_num,
            "title": ch_title,
            "description": None,
            "sections": sections,
            "articles": direct_articles,
        })
    return chapters


def _extract_sections(parent: Tag, articles: dict) -> list:
    """Extract Section-level divisions (sct_1, sct_2, etc.)."""
    sections = []
    for div in _children_with_id_containing(parent, "sct_"):
        heading_text = _get_section_heading(div)
        sec_match = _SECTION_NUM_RE.search(heading_text)
        sec_num = sec_match.group(1) if sec_match else div.get("id", "")
        sec_title = _get_section_title(div)

        art_ids = []
        _extract_articles_from(div, articles)
        for art_div in div.find_all("div", id=lambda x: x and x.startswith("art_")):
            art_num = _get_article_number(art_div)
            if art_num and art_num in articles:
                art_ids.append(art_num)

        sections.append({
            "section_id": sec_num,
            "title": sec_title,
            "description": None,
            "articles": art_ids,
            "subsections": [],
        })
    return sections


def _extract_articles_from(parent: Tag, articles: dict):
    """Find all art_N divs in parent and parse them into articles dict."""
    for art_div in parent.find_all("div", id=lambda x: x and x.startswith("art_")):
        _parse_article(art_div, articles)


# --- Article parsing ---

def _parse_article(art_div: Tag, articles: dict):
    """Parse a single article div into the articles dict."""
    art_num = _get_article_number(art_div)
    if not art_num or art_num in articles:
        return

    # Article title from oj-sti-art
    title_p = art_div.find("p", class_="oj-sti-art")
    article_title = title_p.get_text(strip=True) if title_p else ""

    # Extract paragraphs
    paragraphs = _extract_paragraphs(art_div)

    # Build full text
    full_text = _build_full_text(f"Art. {art_num}", article_title, paragraphs)

    articles[art_num] = {
        "article_id": art_num,
        "label": f"Art. {art_num}",
        "article_title": article_title,
        "full_text": full_text,
        "paragraphs": paragraphs,
        "notes": [],
    }


def _extract_paragraphs(art_div: Tag) -> list:
    """Extract paragraphs from NNN.MMM divs and table sub-clauses."""
    paragraphs = []
    para_divs = art_div.find_all("div", id=lambda x: x and re.match(r"\d{3}\.\d{3}", x or ""))

    if para_divs:
        for para_div in para_divs:
            para_num, para_text, subparagraphs = _parse_paragraph_div(para_div)
            paragraphs.append({
                "label": f"({para_num})" if para_num else "",
                "text": para_text,
                "subparagraphs": subparagraphs,
            })
    else:
        # No NNN.MMM divs — collect all oj-normal as single paragraph
        texts = []
        for p in art_div.find_all("p", class_="oj-normal"):
            t = p.get_text(strip=True)
            if t:
                texts.append(t)
        if texts:
            paragraphs.append({
                "label": "",
                "text": "\n".join(texts),
                "subparagraphs": [],
            })

    return paragraphs


def _parse_paragraph_div(para_div: Tag) -> tuple[str, str, list]:
    """Parse a paragraph div (id=NNN.MMM).

    Returns (para_number, para_text, subparagraphs).
    """
    div_id = para_div.get("id", "")
    # Extract paragraph number from id (e.g., "001.002" → "2")
    parts = div_id.split(".")
    para_num = str(int(parts[1])) if len(parts) == 2 else ""

    # Get the intro text (first oj-normal p that's a direct child or in a direct div)
    intro_text = ""
    first_p = para_div.find("p", class_="oj-normal", recursive=False)
    if not first_p:
        # May be inside a direct child div
        for child in para_div.children:
            if isinstance(child, Tag) and child.name == "p" and "oj-normal" in (child.get("class") or []):
                first_p = child
                break
    if first_p:
        intro_text = first_p.get_text(strip=True)

    # Extract table-based sub-clauses
    subparagraphs = _extract_table_subclauses(para_div)

    return para_num, intro_text, subparagraphs


def _extract_table_subclauses(parent: Tag, depth: int = 0) -> list:
    """Extract lettered sub-clauses from table elements.

    Each sub-clause is a separate <table> with two columns (4%/96%).
    Nested sub-clauses (i), (ii) are tables inside the second <td>.
    """
    subparagraphs = []

    for table in parent.find_all("table", recursive=False):
        tds = table.find_all("td")
        if len(tds) < 2:
            continue

        label_td = tds[0]
        text_td = tds[1]

        label = label_td.get_text(strip=True)  # e.g., "(a)", "(i)"
        # Get the main text from the text cell
        text_parts = []
        for p in text_td.find_all("p", class_="oj-normal", recursive=False):
            text_parts.append(p.get_text(strip=True))

        # Check for nested tables (sub-sub-clauses)
        nested = _extract_table_subclauses(text_td, depth + 1)
        if nested:
            # Append nested items as text lines in this subparagraph
            for n in nested:
                text_parts.append(f"{n['label']} {n['text']}")

        text = "\n".join(text_parts) if text_parts else ""

        if label or text:
            subparagraphs.append({"label": label, "text": text})

    return subparagraphs


# --- Annex extraction ---

def _extract_annexes(soup: BeautifulSoup) -> list:
    """Extract annexes from anx_* divs."""
    annexes = []
    doc = soup.find("div", class_="eli-container") or soup
    for div in doc.find_all("div", id=lambda x: x and x.startswith("anx_")):
        heading = _get_section_heading(div)
        text_parts = [p.get_text(strip=True) for p in div.find_all("p", class_="oj-normal")]
        annexes.append({
            "annex_id": div.get("id", ""),
            "title": heading or div.get("id", ""),
            "text": "\n".join(text_parts),
        })
    return annexes


# --- Helper functions ---

def _get_section_heading(div: Tag) -> str:
    """Get the heading text from oj-ti-section-1 in a structural div."""
    p = div.find("p", class_="oj-ti-section-1", recursive=False)
    if not p:
        # Check one level deeper
        for child in div.children:
            if isinstance(child, Tag):
                p = child.find("p", class_="oj-ti-section-1") if child.name != "p" else None
                if not p and child.name == "p" and "oj-ti-section-1" in (child.get("class") or []):
                    p = child
                if p:
                    break
    return p.get_text(strip=True) if p else ""


def _get_section_title(div: Tag) -> str:
    """Get the title from eli-title → oj-ti-section-2."""
    title_div = div.find("div", class_="eli-title", recursive=False)
    if not title_div:
        # Also check child divs
        for child in div.children:
            if isinstance(child, Tag) and "eli-title" in (child.get("class") or []):
                title_div = child
                break
    if title_div:
        p = title_div.find("p", class_=lambda c: c and ("oj-ti-section-2" in c or "oj-sti-art" in c))
        if p:
            return p.get_text(strip=True)
    return ""


def _get_article_number(art_div: Tag) -> str | None:
    """Extract article number from oj-ti-art paragraph."""
    p = art_div.find("p", class_="oj-ti-art")
    if not p:
        return None
    match = _ARTICLE_NUM_RE.search(p.get_text(strip=True))
    return match.group(1) if match else None


def _children_with_id_containing(parent: Tag, pattern: str) -> list[Tag]:
    """Find direct and near-direct child divs whose id contains pattern."""
    results = []
    for child in parent.children:
        if not isinstance(child, Tag) or child.name != "div":
            continue
        child_id = child.get("id", "")
        if pattern in child_id:
            results.append(child)
    # Also check one level deeper (inside enc_1, the actual structure divs may not be direct children)
    if not results:
        for child in parent.find_all("div", recursive=False):
            child_id = child.get("id", "")
            if pattern in child_id:
                results.append(child)
    return results


def _article_in_div(div: Tag, art_num: str) -> bool:
    """Check if an article div with this number exists inside the div."""
    return div.find("div", id=f"art_{art_num}") is not None


def _parse_table_row(container: Tag) -> tuple[str, str]:
    """Parse a table row with number in first td, text in second td."""
    table = container.find("table")
    if not table:
        return "", ""
    tds = table.find_all("td")
    if len(tds) < 2:
        return "", ""
    number = tds[0].get_text(strip=True).strip("()")
    text = tds[1].get_text(strip=True)
    return number, text


def _build_full_text(art_label: str, title: str, paragraphs: list) -> str:
    """Build full article text from label + title + paragraphs."""
    parts = [art_label]
    if title:
        parts.append(title)
    for para in paragraphs:
        parts.append(para["text"])
        for sub in para.get("subparagraphs", []):
            parts.append(f"{sub['label']} {sub['text']}")
    return "\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/anaandrei/projects/themis-legal && python -m pytest backend/tests/test_eu_html_parser.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Also test against real cached XHTML**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && python3 -c "
from app.services.eu_html_parser import parse_eu_xhtml
html = open('/Users/anaandrei/.cellar/32016R0679_ro.xhtml').read()
r = parse_eu_xhtml(html)
print(f'Title: {r[\"title\"][:60]}')
print(f'Articles: {len(r[\"articles\"])}')
print(f'Books: {len(r[\"books_data\"])}')
if r['books_data']:
    b = r['books_data'][0]
    print(f'Titles in book: {len(b[\"titles\"])}')
    for t in b['titles']:
        chs = t.get('chapters', [])
        print(f'  Title {t[\"title_id\"]}: {len(chs)} chapters')
        for ch in chs[:3]:
            print(f'    Ch {ch[\"chapter_id\"]}: {ch[\"title\"][:40]} ({len(ch[\"articles\"])} arts, {len(ch.get(\"sections\",[]))} secs)')
print(f'Preamble citations: {len(r[\"preamble\"][\"citations\"])}')
print(f'Preamble recitals: {len(r[\"preamble\"][\"recitals\"])}')
art1 = r['articles'].get('1', {})
print(f'Art 1 label: {art1.get(\"label\")}')
print(f'Art 1 title: {art1.get(\"article_title\")}')
print(f'Art 1 paragraphs: {len(art1.get(\"paragraphs\", []))}')
art2 = r['articles'].get('2', {})
if art2:
    p2 = art2['paragraphs'][1] if len(art2.get('paragraphs',[])) > 1 else {}
    print(f'Art 2 para 2 subclauses: {len(p2.get(\"subparagraphs\", []))}')
"
```

Expected: 99 articles, 11 chapters, preamble with 6 citations and 173 recitals, Art 1 has 3 paragraphs, Art 2 para 2 has multiple subclauses.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/eu_html_parser.py backend/tests/test_eu_html_parser.py
git commit -m "feat: rewrite EU XHTML parser with ID-driven structural parsing"
```

---

## Task 3: Rewrite Storage in eu_cellar_service.py

**Files:**
- Modify: `backend/app/services/eu_cellar_service.py`

Replace the custom `_store_eu_version` function with hierarchy-aware storage that creates the same StructuralElement tree as Romanian laws.

- [ ] **Step 1: Replace `_store_eu_version` and update `import_eu_law`**

In `backend/app/services/eu_cellar_service.py`, find and replace the `_store_eu_version` function (and its callers) with new storage code.

The key changes:
1. Delete `_store_eu_version` function entirely
2. Add a new `_store_eu_version_v2` that creates the StructuralElement hierarchy from `books_data`
3. Store preamble as a special article with `order_index=-1`
4. Update `import_eu_law` to call the new function

```python
def _store_eu_version_v2(
    db: Session, law: Law, ver_celex: str, date_str: str,
    content: dict, language: str, is_current: bool,
) -> LawVersion:
    """Store a single EU law version with full hierarchy from parsed content."""
    date_in_force = None
    if date_str:
        try:
            date_in_force = datetime.date.fromisoformat(date_str[:10])
        except ValueError:
            pass

    version = LawVersion(
        law_id=law.id, ver_id=ver_celex, date_in_force=date_in_force,
        state="actual", is_current=is_current, language=language,
    )
    db.add(version)
    db.flush()

    articles = content.get("articles", {})
    order_counter = [0]  # mutable counter for article ordering

    # Store preamble as special article
    preamble = content.get("preamble", {})
    if preamble.get("citations") or preamble.get("recitals"):
        _store_preamble_article(db, version, preamble)

    # Store hierarchy from books_data
    for book_data in content.get("books_data", []):
        for title_data in book_data.get("titles", []):
            title_el = None
            if title_data.get("title_id") and title_data["title_id"] != "default":
                title_el = StructuralElement(
                    law_version_id=version.id, element_type="title",
                    number=title_data["title_id"], title=title_data.get("title"),
                    order_index=order_counter[0],
                )
                db.add(title_el)
                db.flush()
                order_counter[0] += 1

            # Articles directly in title (no chapters)
            for art_id in title_data.get("articles", []):
                if art_id in articles:
                    _store_eu_article(db, version, articles[art_id], title_el, order_counter)

            for ch_data in title_data.get("chapters", []):
                ch_el = StructuralElement(
                    law_version_id=version.id, parent_id=title_el.id if title_el else None,
                    element_type="chapter", number=ch_data["chapter_id"],
                    title=ch_data.get("title"), order_index=order_counter[0],
                )
                db.add(ch_el)
                db.flush()
                order_counter[0] += 1

                # Articles directly in chapter (no sections)
                for art_id in ch_data.get("articles", []):
                    if art_id in articles:
                        _store_eu_article(db, version, articles[art_id], ch_el, order_counter)

                for sec_data in ch_data.get("sections", []):
                    sec_el = StructuralElement(
                        law_version_id=version.id, parent_id=ch_el.id,
                        element_type="section", number=sec_data["section_id"],
                        title=sec_data.get("title"), order_index=order_counter[0],
                    )
                    db.add(sec_el)
                    db.flush()
                    order_counter[0] += 1

                    for art_id in sec_data.get("articles", []):
                        if art_id in articles:
                            _store_eu_article(db, version, articles[art_id], sec_el, order_counter)

        # Articles directly in book (no titles)
        for art_id in book_data.get("articles", []):
            if art_id in articles:
                _store_eu_article(db, version, articles[art_id], None, order_counter)

    # Store annexes
    for idx, annex_data in enumerate(content.get("annexes", [])):
        annex = Annex(
            law_version_id=version.id,
            source_id=annex_data.get("annex_id", f"annex_{idx}"),
            title=annex_data.get("title", ""),
            full_text=annex_data.get("text", ""),
            order_index=idx,
        )
        db.add(annex)

    return version


def _store_eu_article(db, version, art_data, parent_el, order_counter):
    """Store an EU article with proper article_number and label fields."""
    full_text = art_data.get("full_text", "")
    is_abrogated = bool(re.search(r"^\s*\(?\s*[Aa]brogat", full_text[:200]))

    article = Article(
        law_version_id=version.id,
        structural_element_id=parent_el.id if parent_el else None,
        article_number=art_data.get("label", ""),  # "Art. 1"
        label=art_data.get("article_title") or art_data.get("label", ""),  # article title or fallback
        full_text=full_text,
        order_index=order_counter[0],
        is_abrogated=is_abrogated,
    )
    db.add(article)
    db.flush()
    order_counter[0] += 1

    for p_idx, para in enumerate(art_data.get("paragraphs", [])):
        paragraph = Paragraph(
            article_id=article.id,
            paragraph_number=para.get("label", "").strip("()") or str(p_idx + 1),
            label=para.get("label", ""),
            text=para.get("text", ""),
            order_index=p_idx,
        )
        db.add(paragraph)
        db.flush()

        for s_idx, sub in enumerate(para.get("subparagraphs", [])):
            subparagraph = Subparagraph(
                paragraph_id=paragraph.id,
                label=sub.get("label", ""),
                text=sub.get("text", ""),
                order_index=s_idx,
            )
            db.add(subparagraph)


def _store_preamble_article(db, version, preamble):
    """Store preamble as a special article with order_index=-1."""
    paragraphs_data = []

    # Citations as paragraphs
    for cit in preamble.get("citations", []):
        paragraphs_data.append({
            "label": cit.get("number", ""),
            "text": cit.get("text", ""),
        })

    # Recitals as paragraphs
    for rct in preamble.get("recitals", []):
        paragraphs_data.append({
            "label": f"({rct['number']})",
            "text": rct.get("text", ""),
        })

    full_parts = ["Preambul"]
    for p in paragraphs_data:
        full_parts.append(p["text"])

    article = Article(
        law_version_id=version.id,
        structural_element_id=None,
        article_number="Preambul",
        label="Preambul",
        full_text="\n".join(full_parts),
        order_index=-1,
    )
    db.add(article)
    db.flush()

    for p_idx, para in enumerate(paragraphs_data):
        paragraph = Paragraph(
            article_id=article.id,
            paragraph_number=para.get("label", "").strip("()") or str(p_idx + 1),
            label=para.get("label", ""),
            text=para.get("text", ""),
            order_index=p_idx,
        )
        db.add(paragraph)
```

Then update all call sites in `import_eu_law` to replace `_store_eu_version(...)` with `_store_eu_version_v2(...)`.

- [ ] **Step 2: Run integration tests**

```bash
cd /Users/anaandrei/projects/themis-legal && python -m pytest backend/tests/test_eu_import.py -v
```

The existing integration tests will need updating since they mock `parse_eu_xhtml` which now returns a different shape. Update the mocks to return the new format.

- [ ] **Step 3: Update integration test mocks**

In `backend/tests/test_eu_import.py`, update the mock content to match the new parser output shape. Instead of mocking `parse_eu_xhtml` directly, mock `fetch_eu_content` to return content in the new format:

```python
def _mock_parsed_content():
    """Return mock parsed content in the new parser output shape."""
    return {
        "title": "REGULATION (EU) 2016/679 (GDPR)",
        "preamble": {"citations": [{"number": "cit_1", "text": "Having regard to..."}], "recitals": [{"number": "1", "text": "Data protection is fundamental."}]},
        "books_data": [{
            "book_id": "default",
            "title": None,
            "description": None,
            "articles": [],
            "titles": [{
                "title_id": "default",
                "title": None,
                "chapters": [{
                    "chapter_id": "I",
                    "title": "General provisions",
                    "description": None,
                    "sections": [],
                    "articles": ["1", "2"],
                }],
                "articles": [],
            }],
        }],
        "articles": {
            "1": {
                "article_id": "1", "label": "Art. 1", "article_title": "Subject-matter",
                "full_text": "Art. 1\nSubject-matter\n(1) This Regulation lays down rules.",
                "paragraphs": [{"label": "(1)", "text": "(1) This Regulation lays down rules.", "subparagraphs": []}],
                "notes": [],
            },
            "2": {
                "article_id": "2", "label": "Art. 2", "article_title": "Material scope",
                "full_text": "Art. 2\nMaterial scope\n(1) Applies to processing.",
                "paragraphs": [{"label": "(1)", "text": "(1) Applies to processing.", "subparagraphs": []}],
                "notes": [],
            },
        },
        "annexes": [],
    }
```

Update the mock for `fetch_eu_content` to return `(_mock_parsed_content(), "en")`.

- [ ] **Step 4: Run all EU tests**

```bash
cd /Users/anaandrei/projects/themis-legal && python -m pytest backend/tests/test_eu_html_parser.py backend/tests/test_eu_import.py backend/tests/test_eu_safety.py backend/tests/test_celex_parser.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/eu_cellar_service.py backend/tests/test_eu_import.py
git commit -m "feat: replace EU storage with hierarchy-aware version matching Romanian law display"
```

---

## Task 4: Delete Broken EU Laws and Re-Import

**Files:** None (database cleanup + verification)

- [ ] **Step 1: Delete existing broken EU law data**

```bash
curl -s -X DELETE http://localhost:8000/api/laws/9
curl -s -X DELETE http://localhost:8000/api/laws/11
```

Also clear the cache so fresh content is fetched:

```bash
rm -f ~/.cellar/32016R0679_*.xhtml ~/.cellar/32017R0891_*.xhtml
```

- [ ] **Step 2: Re-import GDPR with new parser**

```bash
curl -s -X POST http://localhost:8000/api/laws/eu/import \
  -H "Content-Type: application/json" \
  -d '{"celex_number": "32016R0679", "import_history": false}' | python3 -m json.tool
```

Verify the response shows `versions_imported: 1`.

- [ ] **Step 3: Verify GDPR content in database**

```bash
sqlite3 /path/to/themis.db "
SELECT COUNT(*) as articles FROM articles WHERE law_version_id = (SELECT id FROM law_versions WHERE ver_id='32016R0679');
SELECT COUNT(*) as structures FROM structural_elements WHERE law_version_id = (SELECT id FROM law_versions WHERE ver_id='32016R0679');
SELECT element_type, number, title FROM structural_elements WHERE law_version_id = (SELECT id FROM law_versions WHERE ver_id='32016R0679') ORDER BY order_index LIMIT 10;
SELECT article_number, label FROM articles WHERE law_version_id = (SELECT id FROM law_versions WHERE ver_id='32016R0679') AND article_number = 'Preambul';
"
```

Expected: ~100 articles (99 + preamble), structural elements with chapters, article_number="Art. 1" with label="Obiect și obiective", preamble article exists.

- [ ] **Step 4: Verify in browser**

Open `http://localhost:3000/laws/{law_id}/versions/{version_id}` and verify:
- Chapters show with correct names (not "Capitolul")
- Articles numbered correctly (Art. 1, Art. 2, ... Art. 99 — no gaps)
- Paragraphs separated (not merged into one block)
- Sub-clauses (a), (b), (c) visible under paragraphs
- Preamble article appears at the top

- [ ] **Step 5: Commit any fixes needed**

```bash
git add -A && git commit -m "fix: post-rewrite adjustments for EU law display"
```
