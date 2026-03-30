# EU Legislation Import — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import EU legislation (directives, regulations, decisions, treaties) from the CELLAR API into the Legal Library alongside existing Romanian laws.

**Architecture:** New `eu_cellar_service.py` talks to the EU Publications Office SPARQL + REST APIs. A new `eu_html_parser.py` extracts articles/chapters from EUR-Lex XHTML. Existing models get additive columns (`source`, `celex_number`, `language`). Frontend gets a source toggle on the search bar. EU laws flow into the same database tables and appear under `eu.*` categories.

**Tech Stack:** Python/FastAPI, SQLAlchemy, requests, BeautifulSoup4, SPARQL (HTTP POST), Next.js/React/TypeScript

**Design spec:** `docs/superpowers/specs/2026-03-30-eu-legislation-import-design.md`

---

## File Structure

**New files:**
- `backend/app/services/eu_cellar_service.py` — SPARQL search, CELLAR REST fetch, import orchestration
- `backend/app/services/eu_html_parser.py` — EUR-Lex XHTML → articles/structure dict
- `backend/app/services/eu_version_discovery.py` — weekly version discovery for EU laws
- `backend/tests/test_celex_parser.py` — CELEX number parsing tests
- `backend/tests/test_eu_html_parser.py` — XHTML parser tests
- `backend/tests/test_eu_import.py` — import service tests
- `backend/tests/test_eu_safety.py` — production safety tests
- `backend/tests/fixtures/eu_gdpr_sample.xhtml` — test fixture (GDPR excerpt)
- `backend/tests/fixtures/eu_directive_sample.xhtml` — test fixture (directive excerpt)

**Modified files:**
- `backend/app/models/law.py` — add `source`, `celex_number`, `cellar_uri` to Law; `language` to LawVersion/KnownVersion; new DocumentType enum values
- `backend/app/models/category.py` — add `celex_number` to LawMapping
- `backend/app/services/category_service.py` — add `eu.decision` category; add `celex_number` to EU LawMapping seeds
- `backend/app/routers/laws.py` — new EU endpoints + `source` param on search
- `backend/app/main.py` — additive migration in lifespan, weekly EU discovery job
- `frontend/src/lib/api.ts` — EU search/import API methods, `source` param
- `frontend/src/app/laws/search-import-form.tsx` — source toggle pills, EU doc types, badges
- `frontend/src/app/laws/library-page.tsx` — RO/EU and language badges on law cards

---

## Task 1: Data Model — Add New Fields to Law, LawVersion, KnownVersion

**Files:**
- Modify: `backend/app/models/law.py`

- [ ] **Step 1: Add new enum values to DocumentType**

In `backend/app/models/law.py`, add these values to the `DocumentType` enum after the existing `OTHER` entry:

```python
class DocumentType(str, enum.Enum):
    # ... existing values ...
    OTHER = "other"
    # EU-specific document types
    DIRECTIVE = "directive"
    REGULATION = "regulation"
    EU_DECISION = "eu_decision"
    TREATY = "treaty"
```

- [ ] **Step 2: Add `source`, `celex_number`, `cellar_uri` columns to Law model**

Add these fields to the `Law` class after the `last_checked_at` field:

```python
    # EU integration fields
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="ro")
    celex_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cellar_uri: Mapped[str | None] = mapped_column(String(200), nullable=True)
```

- [ ] **Step 3: Add `language` column to LawVersion model**

Add this field to the `LawVersion` class after the `diff_summary` field:

```python
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="ro")
```

- [ ] **Step 4: Add `language` column to KnownVersion model**

Add this field to the `KnownVersion` class after the `discovered_at` field:

```python
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="ro")
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/law.py
git commit -m "feat: add EU fields to Law, LawVersion, KnownVersion models"
```

---

## Task 2: Data Model — Add `celex_number` to LawMapping

**Files:**
- Modify: `backend/app/models/category.py`

- [ ] **Step 1: Add `celex_number` field to LawMapping**

In the `LawMapping` class, add after the `document_type` field:

```python
    celex_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/models/category.py
git commit -m "feat: add celex_number field to LawMapping model"
```

---

## Task 3: Additive Database Migration in Lifespan

**Files:**
- Modify: `backend/app/main.py`

This adds new columns to existing tables without dropping anything. Follows the exact pattern used for the `diff_summary` column backfill.

- [ ] **Step 1: Add migration helper in lifespan**

In `backend/app/main.py`, add a function before the `lifespan` function:

```python
def _add_column_if_missing(db: Session, table: str, column: str, col_type: str, default: str | None = None):
    """Add a column to a table if it doesn't exist. Safe for repeated runs."""
    from sqlalchemy import text, inspect as sa_inspect
    inspector = sa_inspect(engine)
    existing = [c["name"] for c in inspector.get_columns(table)]
    if column not in existing:
        default_clause = f" DEFAULT {default}" if default is not None else ""
        db.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}"))
        db.commit()
        logger.info(f"Added column {table}.{column}")
```

- [ ] **Step 2: Call migration in lifespan after `Base.metadata.create_all`**

Inside the `lifespan` function's `try` block, after `Base.metadata.create_all(bind=engine)` and before `seed_defaults(db)`, add:

```python
        # Additive migration: EU integration columns
        _add_column_if_missing(db, "laws", "source", "VARCHAR(10)", "'ro'")
        _add_column_if_missing(db, "laws", "celex_number", "VARCHAR(50)", None)
        _add_column_if_missing(db, "laws", "cellar_uri", "VARCHAR(200)", None)
        _add_column_if_missing(db, "law_versions", "language", "VARCHAR(10)", "'ro'")
        _add_column_if_missing(db, "known_versions", "language", "VARCHAR(10)", "'ro'")
        _add_column_if_missing(db, "law_mappings", "celex_number", "VARCHAR(50)", None)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: additive DB migration for EU integration columns"
```

---

## Task 4: Seed `eu.decision` Category and EU LawMapping CELEX Numbers

**Files:**
- Modify: `backend/app/services/category_service.py`

- [ ] **Step 1: Add `eu.decision` category to the categories_data list**

Find the EU categories section (around line 88-91) and add after the `eu.caselaw` entry:

```python
        ("eu", "eu.decision", "Decizii UE", "EU decisions", "Decizii ale Consiliului, Comisiei, BCE — obligatorii pentru destinatari", True, 5),
```

- [ ] **Step 2: Update EU LawMapping seeds with celex_number**

The existing EU law mappings (around lines 274-294) need `celex_number` added. Since `seed_categories` checks `if existing: return`, we need a separate function for this. Add a new function after `seed_categories`:

```python
def seed_eu_celex_mappings(db: Session) -> None:
    """Backfill celex_number on EU law mappings. Safe to run multiple times."""
    celex_map = {
        "Regulamentul (UE) 2016/679 — GDPR": "32016R0679",
        "Regulamentul (UE) 2024/1689 — AI Act": "32024R1689",
        "Regulamentul (UE) 2022/2065 — DSA (Digital Services Act)": "32022R2065",
        "Regulamentul (UE) 2022/1925 — DMA (Digital Markets Act)": "32022R1925",
        "Regulamentul (UE) 2017/745 — MDR (dispozitive medicale)": "32017R0745",
        "Regulamentul (UE) 1215/2012 — competența judiciară în materie civilă (Bruxelles I)": "32012R1215",
        "Regulamentul (UE) 593/2008 — legea aplicabilă obligațiilor contractuale (Roma I)": "32008R0593",
        "Regulamentul (UE) 864/2007 — legea aplicabilă obligațiilor necontractuale (Roma II)": "32007R0864",
        "Directiva 2011/83/UE — drepturile consumatorilor (transpusă prin OUG 34/2014)": "32011L0083",
        "Directiva 2019/1023/UE — restructurare și insolvență (transpusă prin Legea 216/2022)": "32019L1023",
        "Directiva 2022/2557/UE — reziliența entităților critice (CER)": "32022L2557",
        "Directiva 2022/2555/UE — NIS2": "32022L2555",
        "Directiva 2023/970/UE — transparența salarială": "32023L0970",
        "Directiva 2009/72/CE — piața internă a energiei electrice": "32009L0072",
    }
    updated = 0
    for title, celex in celex_map.items():
        mapping = db.query(LawMapping).filter(LawMapping.title == title, LawMapping.celex_number.is_(None)).first()
        if mapping:
            mapping.celex_number = celex
            updated += 1
    if updated:
        db.commit()
        logger.info(f"Backfilled celex_number on {updated} EU law mappings")
```

- [ ] **Step 3: Handle the new `eu.decision` category in seed_categories**

Since `seed_categories` returns early if any CategoryGroup exists, the new category won't be added on existing deployments. Add a separate function:

```python
def ensure_eu_decision_category(db: Session) -> None:
    """Add eu.decision category if missing. Safe for repeated runs."""
    existing = db.query(Category).filter_by(slug="eu.decision").first()
    if existing:
        return
    eu_group = db.query(CategoryGroup).filter_by(slug="eu").first()
    if not eu_group:
        return
    cat = Category(
        group_id=eu_group.id,
        slug="eu.decision",
        name_ro="Decizii UE",
        name_en="EU decisions",
        description="Decizii ale Consiliului, Comisiei, BCE — obligatorii pentru destinatari",
        is_eu=True,
        sort_order=5,
    )
    db.add(cat)
    db.commit()
    logger.info("Added eu.decision category")
```

- [ ] **Step 4: Call new seed functions from main.py lifespan**

In `backend/app/main.py`, add imports and calls inside the lifespan `try` block, after `seed_categories(db)`:

```python
from app.services.category_service import seed_categories, backfill_law_mapping_fields, ensure_eu_decision_category, seed_eu_celex_mappings

# ... inside try block, after seed_categories(db):
        ensure_eu_decision_category(db)
        seed_eu_celex_mappings(db)
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/category_service.py backend/app/main.py
git commit -m "feat: add eu.decision category and celex_number backfill for EU mappings"
```

---

## Task 5: Test Fixtures — Sample EU XHTML Files

**Files:**
- Create: `backend/tests/fixtures/eu_gdpr_sample.xhtml`
- Create: `backend/tests/fixtures/eu_directive_sample.xhtml`

- [ ] **Step 1: Create GDPR regulation sample fixture**

Create `backend/tests/fixtures/eu_gdpr_sample.xhtml` with a minimal but realistic excerpt showing the structural CSS classes used by EUR-Lex XHTML:

```html
<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>EUR-Lex - 32016R0679</title></head>
<body>
<div id="document1">
  <p class="oj-doc-ti">REGULATION (EU) 2016/679 OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL</p>
  <p class="oj-doc-ti">of 27 April 2016</p>
  <p class="oj-doc-ti">on the protection of natural persons with regard to the processing of personal data and on the free movement of such data, and repealing Directive 95/46/EC (General Data Protection Regulation)</p>
  <div class="eli-main-title">
    <p class="oj-ti-section-1">CHAPTER I</p>
    <p class="oj-sti-section-1">General provisions</p>
  </div>
  <div class="eli-subdivision" id="art_1">
    <p class="oj-ti-art">Article 1</p>
    <p class="oj-sti-art">Subject-matter and objectives</p>
    <table class="oj-table">
      <tbody>
        <tr><td><p class="oj-normal">1.   This Regulation lays down rules relating to the protection of natural persons with regard to the processing of personal data and rules relating to the free movement of personal data.</p></td></tr>
        <tr><td><p class="oj-normal">2.   This Regulation protects fundamental rights and freedoms of natural persons and in particular their right to the protection of personal data.</p></td></tr>
        <tr><td><p class="oj-normal">3.   The free movement of personal data within the Union shall neither be restricted nor prohibited for reasons connected with the protection of natural persons with regard to the processing of personal data.</p></td></tr>
      </tbody>
    </table>
  </div>
  <div class="eli-subdivision" id="art_2">
    <p class="oj-ti-art">Article 2</p>
    <p class="oj-sti-art">Material scope</p>
    <table class="oj-table">
      <tbody>
        <tr><td><p class="oj-normal">1.   This Regulation applies to the processing of personal data wholly or partly by automated means and to the processing other than by automated means of personal data which form part of a filing system or are intended to form part of a filing system.</p></td></tr>
        <tr><td><p class="oj-normal">2.   This Regulation does not apply to the processing of personal data:</p></td></tr>
        <tr><td><p class="oj-normal">(a) in the course of an activity which falls outside the scope of Union law;</p></td></tr>
        <tr><td><p class="oj-normal">(b) by the Member States when carrying out activities which fall within the scope of Chapter 2 of Title V of the TEU;</p></td></tr>
        <tr><td><p class="oj-normal">(c) by a natural person in the course of a purely personal or household activity;</p></td></tr>
        <tr><td><p class="oj-normal">(d) by competent authorities for the purposes of the prevention, investigation, detection or prosecution of criminal offences or the execution of criminal penalties, including the safeguarding against and the prevention of threats to public security.</p></td></tr>
      </tbody>
    </table>
  </div>
  <div class="eli-main-title">
    <p class="oj-ti-section-1">CHAPTER II</p>
    <p class="oj-sti-section-1">Principles</p>
  </div>
  <div class="eli-subdivision" id="art_5">
    <p class="oj-ti-art">Article 5</p>
    <p class="oj-sti-art">Principles relating to processing of personal data</p>
    <table class="oj-table">
      <tbody>
        <tr><td><p class="oj-normal">1.   Personal data shall be:</p></td></tr>
        <tr><td><p class="oj-normal">(a) processed lawfully, fairly and in a transparent manner in relation to the data subject ('lawfulness, fairness and transparency');</p></td></tr>
        <tr><td><p class="oj-normal">(b) collected for specified, explicit and legitimate purposes and not further processed in a manner that is incompatible with those purposes ('purpose limitation');</p></td></tr>
      </tbody>
    </table>
  </div>
  <div class="eli-subdivision" id="anx_I">
    <p class="oj-ti-section-1">ANNEX I</p>
    <p class="oj-normal">List of processing operations subject to data protection impact assessment.</p>
  </div>
</div>
</body>
</html>
```

- [ ] **Step 2: Create directive sample fixture**

Create `backend/tests/fixtures/eu_directive_sample.xhtml` with a NIS2-style directive excerpt:

```html
<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>EUR-Lex - 32022L2555</title></head>
<body>
<div id="document1">
  <p class="oj-doc-ti">DIRECTIVE (EU) 2022/2555 OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL</p>
  <p class="oj-doc-ti">of 14 December 2022</p>
  <p class="oj-doc-ti">on measures for a high common level of cybersecurity across the Union (NIS 2 Directive)</p>
  <div class="eli-main-title">
    <p class="oj-ti-section-1">CHAPTER I</p>
    <p class="oj-sti-section-1">GENERAL PROVISIONS</p>
  </div>
  <div class="eli-subdivision" id="art_1">
    <p class="oj-ti-art">Article 1</p>
    <p class="oj-sti-art">Subject matter</p>
    <table class="oj-table">
      <tbody>
        <tr><td><p class="oj-normal">1.   This Directive lays down measures that aim to achieve a high common level of cybersecurity across the Union, with a view to improving the functioning of the internal market.</p></td></tr>
        <tr><td><p class="oj-normal">2.   To that end, this Directive:</p></td></tr>
        <tr><td><p class="oj-normal">(a) lays down obligations that require Member States to adopt national cybersecurity strategies;</p></td></tr>
        <tr><td><p class="oj-normal">(b) establishes cybersecurity risk-management measures and reporting obligations;</p></td></tr>
      </tbody>
    </table>
  </div>
  <div class="eli-subdivision" id="art_2">
    <p class="oj-ti-art">Article 2</p>
    <p class="oj-sti-art">Scope</p>
    <table class="oj-table">
      <tbody>
        <tr><td><p class="oj-normal">1.   This Directive applies to public and private entities that qualify as medium-sized enterprises or exceed the ceilings for medium-sized enterprises.</p></td></tr>
      </tbody>
    </table>
  </div>
  <div class="eli-main-title">
    <p class="oj-ti-section-1">CHAPTER II</p>
    <p class="oj-sti-section-1">COORDINATED CYBERSECURITY FRAMEWORKS</p>
  </div>
  <div class="eli-subdivision" id="art_7">
    <p class="oj-ti-art">Article 7</p>
    <p class="oj-sti-art">National cybersecurity strategy</p>
    <table class="oj-table">
      <tbody>
        <tr><td><p class="oj-normal">1.   Each Member State shall adopt a national cybersecurity strategy that provides for strategic objectives and appropriate policy and regulatory measures.</p></td></tr>
      </tbody>
    </table>
  </div>
</div>
</body>
</html>
```

- [ ] **Step 3: Commit**

```bash
git add backend/tests/fixtures/
git commit -m "test: add EU XHTML sample fixtures for GDPR and NIS2 directive"
```

---

## Task 6: CELEX Number Parser Utility

**Files:**
- Create: `backend/app/services/eu_cellar_service.py` (partial — just the CELEX utilities)
- Test: `backend/tests/test_celex_parser.py`

- [ ] **Step 1: Write failing tests for CELEX parsing**

Create `backend/tests/test_celex_parser.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/anaandrei/projects/themis-legal && python -m pytest backend/tests/test_celex_parser.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.eu_cellar_service'`

- [ ] **Step 3: Implement CELEX parsing functions**

Create `backend/app/services/eu_cellar_service.py` with the initial utilities:

```python
"""EU legislation service — CELLAR SPARQL + REST API integration."""
import re
import logging

logger = logging.getLogger(__name__)

# --- CELEX parsing ---

_CELEX_LEGISLATION_RE = re.compile(r"^([03])(\d{4})([RLDHF])(\d+)(?:-(\d{8}))?$")
_CELEX_TREATY_RE = re.compile(r"^(1)(\d{4})([A-Z])(.+)$")

_TYPE_CODE_TO_DOC_TYPE = {"R": "regulation", "L": "directive", "D": "eu_decision"}
_TYPE_CODE_TO_CATEGORY = {"R": "eu.regulation", "L": "eu.directive", "D": "eu.decision"}


def parse_celex(celex: str) -> dict | None:
    """Parse a CELEX number into its components. Returns None if invalid."""
    if not celex:
        return None
    m = _CELEX_LEGISLATION_RE.match(celex)
    if m:
        result = {"sector": m.group(1), "year": m.group(2), "type_code": m.group(3), "number": m.group(4)}
        if m.group(5):
            result["consol_date"] = m.group(5)
        return result
    m = _CELEX_TREATY_RE.match(celex)
    if m:
        return {"sector": m.group(1), "year": m.group(2), "type_code": m.group(3), "number": m.group(4)}
    return None


def celex_to_document_type(celex: str) -> str:
    """Map a CELEX number to an internal document_type string."""
    parsed = parse_celex(celex)
    if not parsed:
        return "other"
    if parsed["sector"] == "1":
        return "treaty"
    return _TYPE_CODE_TO_DOC_TYPE.get(parsed["type_code"], "other")


def celex_to_category_slug(celex: str) -> str | None:
    """Map a CELEX number to a category slug (e.g., 'eu.regulation')."""
    parsed = parse_celex(celex)
    if not parsed:
        return None
    if parsed["sector"] == "1":
        return "eu.treaty"
    return _TYPE_CODE_TO_CATEGORY.get(parsed["type_code"])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/anaandrei/projects/themis-legal && python -m pytest backend/tests/test_celex_parser.py -v
```

Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/eu_cellar_service.py backend/tests/test_celex_parser.py
git commit -m "feat: add CELEX number parser and document type mapping"
```

---

## Task 7: EU XHTML Parser

**Files:**
- Create: `backend/app/services/eu_html_parser.py`
- Test: `backend/tests/test_eu_html_parser.py`

- [ ] **Step 1: Write failing tests for XHTML parser**

Create `backend/tests/test_eu_html_parser.py`:

```python
"""Tests for EUR-Lex XHTML parser."""
import os
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/anaandrei/projects/themis-legal && python -m pytest backend/tests/test_eu_html_parser.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.eu_html_parser'`

- [ ] **Step 3: Implement the XHTML parser**

Create `backend/app/services/eu_html_parser.py`:

```python
"""Parse EUR-Lex XHTML into structured articles, chapters, and annexes."""
import re
import logging
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

_PARA_NUM_RE = re.compile(r"^(\d+)\.\s+")
_SUBPARA_RE = re.compile(r"^\(([a-z])\)\s*")
_ARTICLE_NUM_RE = re.compile(r"Article\s+(\d+[a-z]?)", re.IGNORECASE)
_CHAPTER_NUM_RE = re.compile(r"CHAPTER\s+([IVXLCDM]+)", re.IGNORECASE)
_ANNEX_RE = re.compile(r"ANNEX\s*([IVXLCDM]*)", re.IGNORECASE)


def parse_eu_xhtml(html: str) -> dict:
    """Parse EUR-Lex XHTML and return {title, articles, structure, annexes}.

    The output shape mirrors what leropa_service expects so downstream
    storage code can be shared.
    """
    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup)
    structure, articles, annexes = _extract_body(soup)
    return {"title": title, "articles": articles, "structure": structure, "annexes": annexes}


def _extract_title(soup: BeautifulSoup) -> str:
    """Join all oj-doc-ti paragraphs into a single title string."""
    parts = []
    for p in soup.find_all("p", class_="oj-doc-ti"):
        text = p.get_text(strip=True)
        if text:
            parts.append(text)
    return " ".join(parts)


def _extract_body(soup: BeautifulSoup) -> tuple[list, list, list]:
    """Walk the document and extract chapters, articles, and annexes."""
    structure = []  # list of chapter dicts
    articles = []
    annexes = []
    current_chapter = None

    doc = soup.find("div", id="document1")
    if not doc:
        return structure, articles, annexes

    for element in doc.children:
        if not isinstance(element, Tag):
            continue

        # Check for chapter headings
        chapter_title_p = element.find("p", class_="oj-ti-section-1")
        if chapter_title_p and not element.find("p", class_="oj-ti-art"):
            chapter_text = chapter_title_p.get_text(strip=True)
            # Check if it's an annex
            annex_match = _ANNEX_RE.match(chapter_text)
            if annex_match:
                annex_text_parts = []
                for p in element.find_all("p", class_="oj-normal"):
                    annex_text_parts.append(p.get_text(strip=True))
                annexes.append({
                    "title": chapter_text,
                    "source_id": f"annex_{annex_match.group(1) or '1'}",
                    "full_text": "\n".join(annex_text_parts),
                })
                continue

            chapter_num_match = _CHAPTER_NUM_RE.match(chapter_text)
            subtitle_p = element.find("p", class_="oj-sti-section-1")
            current_chapter = {
                "type": "chapter",
                "number": chapter_num_match.group(1) if chapter_num_match else chapter_text,
                "title": subtitle_p.get_text(strip=True) if subtitle_p else "",
                "article_ids": [],
            }
            structure.append(current_chapter)
            continue

        # Check for articles (eli-subdivision divs)
        art_title_p = element.find("p", class_="oj-ti-art")
        if art_title_p:
            art_text = art_title_p.get_text(strip=True)
            art_match = _ARTICLE_NUM_RE.match(art_text)
            if not art_match:
                continue
            art_num = art_match.group(1)

            subtitle_p = element.find("p", class_="oj-sti-art")
            label = subtitle_p.get_text(strip=True) if subtitle_p else ""

            paragraphs = _extract_paragraphs(element)
            full_text = _build_full_text(art_text, label, paragraphs)

            article = {
                "number": art_num,
                "label": label,
                "full_text": full_text,
                "paragraphs": paragraphs,
                "chapter_number": current_chapter["number"] if current_chapter else None,
            }
            articles.append(article)
            if current_chapter:
                current_chapter["article_ids"].append(art_num)

    # Handle annexes that are standalone eli-subdivision divs
    for div in doc.find_all("div", class_="eli-subdivision"):
        div_id = div.get("id", "")
        if div_id.startswith("anx_"):
            title_p = div.find("p", class_="oj-ti-section-1")
            if title_p and _ANNEX_RE.match(title_p.get_text(strip=True)):
                # Already processed as chapter-level annex? Check duplicates
                annex_title = title_p.get_text(strip=True)
                if any(a["title"] == annex_title for a in annexes):
                    continue
                text_parts = [p.get_text(strip=True) for p in div.find_all("p", class_="oj-normal")]
                annex_match = _ANNEX_RE.match(annex_title)
                annexes.append({
                    "title": annex_title,
                    "source_id": f"annex_{annex_match.group(1) if annex_match else '1'}",
                    "full_text": "\n".join(text_parts),
                })

    return structure, articles, annexes


def _extract_paragraphs(article_div: Tag) -> list[dict]:
    """Extract numbered paragraphs from oj-normal <p> elements."""
    paragraphs = []
    current_para = None

    for p in article_div.find_all("p", class_="oj-normal"):
        text = p.get_text(strip=True)
        if not text:
            continue

        para_match = _PARA_NUM_RE.match(text)
        if para_match:
            if current_para:
                paragraphs.append(current_para)
            current_para = {
                "number": para_match.group(1),
                "text": text,
                "subparagraphs": [],
            }
        elif _SUBPARA_RE.match(text) and current_para:
            sub_match = _SUBPARA_RE.match(text)
            current_para["subparagraphs"].append({
                "label": f"({sub_match.group(1)})",
                "text": text,
            })
        elif current_para:
            # Continuation text — append to current paragraph
            current_para["text"] += " " + text
        else:
            # Standalone paragraph without number
            if current_para is None:
                current_para = {"number": "", "text": text, "subparagraphs": []}

    if current_para:
        paragraphs.append(current_para)

    return paragraphs


def _build_full_text(art_title: str, label: str, paragraphs: list[dict]) -> str:
    """Build full article text from title + label + paragraph texts."""
    parts = [art_title]
    if label:
        parts.append(label)
    for para in paragraphs:
        parts.append(para["text"])
        for sub in para["subparagraphs"]:
            parts.append(sub["text"])
    return "\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/anaandrei/projects/themis-legal && python -m pytest backend/tests/test_eu_html_parser.py -v
```

Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/eu_html_parser.py backend/tests/test_eu_html_parser.py
git commit -m "feat: add EUR-Lex XHTML parser for articles, chapters, annexes"
```

---

## Task 8: SPARQL Query Builder and Search

**Files:**
- Modify: `backend/app/services/eu_cellar_service.py`

- [ ] **Step 1: Add SPARQL constants and query builder**

Append to `backend/app/services/eu_cellar_service.py`:

```python
import requests
from dataclasses import dataclass, asdict

SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
CELLAR_BASE = "https://publications.europa.eu/resource/cellar"

SPARQL_HEADERS = {
    "Accept": "application/sparql-results+json",
    "Content-Type": "application/x-www-form-urlencoded",
}

RESOURCE_TYPE_BASE = "http://publications.europa.eu/resource/authority/resource-type"
LANGUAGE_BASE = "http://publications.europa.eu/resource/authority/language"

EU_DOC_TYPE_TO_RESOURCE = {
    "directive": f"{RESOURCE_TYPE_BASE}/DIR",
    "regulation": f"{RESOURCE_TYPE_BASE}/REG",
    "eu_decision": f"{RESOURCE_TYPE_BASE}/DEC",
    "treaty": f"{RESOURCE_TYPE_BASE}/TREATY",
}


@dataclass
class EUSearchResult:
    celex: str
    title: str
    date: str
    doc_type: str
    in_force: bool
    cellar_uri: str
    already_imported: bool = False

    def to_dict(self):
        return asdict(self)


def build_search_sparql(
    keyword: str | None = None,
    doc_type: str | None = None,
    year: str | None = None,
    number: str | None = None,
    in_force_only: bool = False,
    language: str = "ENG",
    limit: int = 50,
) -> str:
    """Build a SPARQL query to search EU legislation via CELLAR."""
    filters = []
    type_clause = ""

    if doc_type and doc_type in EU_DOC_TYPE_TO_RESOURCE:
        type_clause = f"?work cdm:work_has_resource-type <{EU_DOC_TYPE_TO_RESOURCE[doc_type]}> ."
    else:
        # Search across all binding act types
        type_values = " ".join(f"<{uri}>" for uri in EU_DOC_TYPE_TO_RESOURCE.values())
        type_clause = f"VALUES ?type {{ {type_values} }}\n  ?work cdm:work_has_resource-type ?type ."

    if keyword:
        escaped = keyword.replace('"', '\\"')
        filters.append(f'FILTER(CONTAINS(LCASE(?title), LCASE("{escaped}")))')

    if year:
        filters.append(f'FILTER(STRSTARTS(?date, "{year}"))')

    if number:
        filters.append(f'FILTER(CONTAINS(?celex, "{number}"))')

    if in_force_only:
        filters.append('FILTER(?inForce = "true"^^xsd:boolean)')

    filter_block = "\n  ".join(filters)

    return f"""PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT DISTINCT ?work ?celex ?title ?date ?inForce WHERE {{
  {type_clause}
  ?work cdm:resource_legal_id_celex ?celex .
  ?expr cdm:expression_belongs_to_work ?work .
  ?expr cdm:expression_uses_language <{LANGUAGE_BASE}/{language}> .
  ?expr cdm:expression_title ?title .
  OPTIONAL {{ ?work cdm:work_date_document ?date }}
  OPTIONAL {{ ?work cdm:resource_legal_in-force ?inForce }}
  FILTER(STRSTARTS(?celex, "3"))
  {filter_block}
}} ORDER BY DESC(?date) LIMIT {limit}"""


def search_eu_legislation(
    keyword: str | None = None,
    doc_type: str | None = None,
    year: str | None = None,
    number: str | None = None,
    in_force_only: bool = False,
    limit: int = 50,
) -> list[EUSearchResult]:
    """Search EU legislation via CELLAR SPARQL endpoint."""
    # Try Romanian first, then English
    for lang in ("RON", "ENG"):
        sparql = build_search_sparql(
            keyword=keyword, doc_type=doc_type, year=year, number=number,
            in_force_only=in_force_only, language=lang, limit=limit,
        )
        try:
            resp = requests.post(
                SPARQL_ENDPOINT, data={"query": sparql}, headers=SPARQL_HEADERS, timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            bindings = data.get("results", {}).get("bindings", [])
            if bindings:
                return _parse_sparql_results(bindings)
        except Exception as e:
            logger.warning(f"SPARQL search failed (lang={lang}): {e}")
    return []


def _parse_sparql_results(bindings: list[dict]) -> list[EUSearchResult]:
    """Convert SPARQL JSON bindings to EUSearchResult list."""
    results = []
    seen_celex = set()
    for b in bindings:
        celex = b.get("celex", {}).get("value", "")
        if not celex or celex in seen_celex:
            continue
        seen_celex.add(celex)
        in_force_val = b.get("inForce", {}).get("value", "")
        results.append(EUSearchResult(
            celex=celex,
            title=b.get("title", {}).get("value", ""),
            date=b.get("date", {}).get("value", ""),
            doc_type=celex_to_document_type(celex),
            in_force=in_force_val.lower() == "true" if in_force_val else True,
            cellar_uri=b.get("work", {}).get("value", ""),
        ))
    return results
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/eu_cellar_service.py
git commit -m "feat: add SPARQL query builder and EU legislation search"
```

---

## Task 9: CELLAR REST Content Fetcher

**Files:**
- Modify: `backend/app/services/eu_cellar_service.py`

- [ ] **Step 1: Add content fetching and caching functions**

Append to `backend/app/services/eu_cellar_service.py`:

```python
import time
from pathlib import Path
from app.services.eu_html_parser import parse_eu_xhtml

CACHE_DIR = Path.home() / ".cellar"

CELLAR_HEADERS = {
    "User-Agent": "Themis-Legal/1.0 (EU legislation import)",
}


def fetch_eu_content(cellar_uri: str, celex: str, language: str = "ron", use_cache: bool = True) -> tuple[dict, str]:
    """Fetch and parse EU legislation content from CELLAR.

    Tries Romanian first, falls back to English.
    Returns (parsed_content, language_code) where language_code is 'ro' or 'en'.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for lang_code, accept_lang in [("ro", "ron"), ("en", "eng")]:
        if language == "eng" and lang_code == "ro":
            continue  # Skip Romanian if English explicitly requested

        cache_file = CACHE_DIR / f"{celex}_{lang_code}.xhtml"

        if use_cache and cache_file.exists():
            html = cache_file.read_text(encoding="utf-8")
            return parse_eu_xhtml(html), lang_code

        try:
            resp = requests.get(
                cellar_uri,
                headers={
                    **CELLAR_HEADERS,
                    "Accept": "application/xhtml+xml",
                    "Accept-Language": accept_lang,
                },
                timeout=60,
                allow_redirects=True,
            )
            if resp.status_code == 200 and "html" in resp.headers.get("content-type", "").lower():
                html = resp.text
                cache_file.write_text(html, encoding="utf-8")
                return parse_eu_xhtml(html), lang_code
        except Exception as e:
            logger.warning(f"CELLAR fetch failed (lang={lang_code}, celex={celex}): {e}")

    raise RuntimeError(f"Could not fetch content for {celex} in any language")


def fetch_eu_metadata(celex: str) -> dict | None:
    """Fetch metadata for a single EU act via SPARQL by CELEX number."""
    sparql = f"""PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT ?work ?title ?date ?inForce WHERE {{
  ?work cdm:resource_legal_id_celex "{celex}" .
  ?expr cdm:expression_belongs_to_work ?work .
  ?expr cdm:expression_uses_language <{LANGUAGE_BASE}/ENG> .
  ?expr cdm:expression_title ?title .
  OPTIONAL {{ ?work cdm:work_date_document ?date }}
  OPTIONAL {{ ?work cdm:resource_legal_in-force ?inForce }}
}} LIMIT 1"""

    try:
        resp = requests.post(SPARQL_ENDPOINT, data={"query": sparql}, headers=SPARQL_HEADERS, timeout=30)
        resp.raise_for_status()
        bindings = resp.json().get("results", {}).get("bindings", [])
        if not bindings:
            return None
        b = bindings[0]
        in_force_val = b.get("inForce", {}).get("value", "")
        return {
            "celex": celex,
            "cellar_uri": b.get("work", {}).get("value", ""),
            "title": b.get("title", {}).get("value", ""),
            "date": b.get("date", {}).get("value", ""),
            "in_force": in_force_val.lower() == "true" if in_force_val else True,
            "doc_type": celex_to_document_type(celex),
        }
    except Exception as e:
        logger.error(f"Failed to fetch metadata for {celex}: {e}")
        return None


def fetch_consolidated_versions(celex: str) -> list[dict]:
    """Fetch all consolidated versions for a base act via SPARQL.

    Consolidated CELEX numbers have sector 0 and a date suffix,
    e.g. 02016R0679-20160504.
    """
    parsed = parse_celex(celex)
    if not parsed:
        return []
    # Build pattern: 0{year}{type}{number}-*
    base_pattern = f"0{parsed['year']}{parsed['type_code']}{parsed['number']}"

    sparql = f"""PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT ?work ?celex ?date WHERE {{
  ?work cdm:resource_legal_id_celex ?celex .
  FILTER(STRSTARTS(?celex, "{base_pattern}"))
  OPTIONAL {{ ?work cdm:work_date_document ?date }}
}} ORDER BY DESC(?date)"""

    try:
        resp = requests.post(SPARQL_ENDPOINT, data={"query": sparql}, headers=SPARQL_HEADERS, timeout=30)
        resp.raise_for_status()
        bindings = resp.json().get("results", {}).get("bindings", [])
        versions = []
        for b in bindings:
            cons_celex = b.get("celex", {}).get("value", "")
            versions.append({
                "celex": cons_celex,
                "cellar_uri": b.get("work", {}).get("value", ""),
                "date": b.get("date", {}).get("value", ""),
            })
        return versions
    except Exception as e:
        logger.error(f"Failed to fetch consolidated versions for {celex}: {e}")
        return []
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/eu_cellar_service.py
git commit -m "feat: add CELLAR REST content fetcher with caching and language fallback"
```

---

## Task 10: EU Import Orchestration

**Files:**
- Modify: `backend/app/services/eu_cellar_service.py`

- [ ] **Step 1: Add the main import function**

Append to `backend/app/services/eu_cellar_service.py`:

```python
import datetime
from sqlalchemy.orm import Session
from app.models.law import Law, LawVersion, KnownVersion, Article, StructuralElement, Paragraph, Subparagraph, Annex
from app.models.category import Category


def import_eu_law(db: Session, celex: str, import_history: bool = True, rate_limit_delay: float = 2.0) -> dict:
    """Import an EU law by CELEX number. Returns dict with law_id, title, versions_imported.

    Checks for duplicates before inserting. Fetches metadata, content, and
    optionally all consolidated versions.
    """
    # Duplicate check
    existing = db.query(Law).filter(Law.celex_number == celex).first()
    if existing:
        raise ValueError(f"Law with CELEX {celex} already imported (law_id={existing.id})")

    # Fetch metadata
    meta = fetch_eu_metadata(celex)
    if not meta:
        raise RuntimeError(f"Could not fetch metadata for CELEX {celex}")

    # Determine document type and category
    doc_type = celex_to_document_type(celex)
    category_slug = celex_to_category_slug(celex)
    category = db.query(Category).filter_by(slug=category_slug).first() if category_slug else None

    # Parse year and number from CELEX
    parsed = parse_celex(celex)
    law_number = parsed["number"].lstrip("0") if parsed else ""
    law_year = int(parsed["year"]) if parsed else 0

    # Create Law record
    eli_url = _build_eli_url(doc_type, parsed)
    law = Law(
        title=meta["title"],
        law_number=law_number,
        law_year=law_year,
        document_type=doc_type,
        source_url=eli_url,
        source="eu",
        celex_number=celex,
        cellar_uri=meta["cellar_uri"],
        status="in_force" if meta["in_force"] else "unknown",
        category_id=category.id if category else None,
        category_confidence="auto" if category else None,
    )
    db.add(law)
    db.flush()

    # Fetch and store the main version content
    content, lang = fetch_eu_content(meta["cellar_uri"], celex)
    version = _store_eu_version(db, law, celex, meta["date"], content, lang, is_current=True)
    versions_imported = 1

    # Fetch consolidated versions if requested
    if import_history:
        consol_versions = fetch_consolidated_versions(celex)
        for cv in consol_versions:
            if db.query(LawVersion).filter_by(ver_id=cv["celex"]).first():
                continue  # Already imported
            try:
                time.sleep(rate_limit_delay)
                cv_content, cv_lang = fetch_eu_content(cv["cellar_uri"], cv["celex"])
                _store_eu_version(db, law, cv["celex"], cv["date"], cv_content, cv_lang, is_current=False)
                versions_imported += 1
            except Exception as e:
                logger.warning(f"Failed to import consolidated version {cv['celex']}: {e}")

        # Mark the newest version as current
        _update_current_version(db, law)

    db.commit()

    # Index in ChromaDB and FTS5
    try:
        from app.services.indexing_service import index_law_to_chroma, rebuild_bm25
        index_law_to_chroma(db, law.id)
        rebuild_bm25(db)
    except Exception as e:
        logger.warning(f"Indexing failed for EU law {celex}: {e}")

    return {
        "law_id": law.id,
        "title": law.title,
        "law_number": law_number,
        "law_year": law_year,
        "document_type": doc_type,
        "versions_imported": versions_imported,
    }


def _store_eu_version(
    db: Session, law: Law, ver_celex: str, date_str: str,
    content: dict, language: str, is_current: bool,
) -> LawVersion:
    """Store a single EU law version with its articles and structure."""
    # Parse date
    date_in_force = None
    if date_str:
        try:
            date_in_force = datetime.date.fromisoformat(date_str[:10])
        except ValueError:
            pass

    version = LawVersion(
        law_id=law.id,
        ver_id=ver_celex,
        date_in_force=date_in_force,
        state="actual",
        is_current=is_current,
        language=language,
    )
    db.add(version)
    db.flush()

    # Store structural elements (chapters)
    chapter_element_map = {}
    for idx, ch in enumerate(content.get("structure", [])):
        se = StructuralElement(
            law_version_id=version.id,
            element_type="chapter",
            number=ch["number"],
            title=ch.get("title", ""),
            order_index=idx,
        )
        db.add(se)
        db.flush()
        chapter_element_map[ch["number"]] = se

    # Store articles
    for idx, art_data in enumerate(content.get("articles", [])):
        parent_se = chapter_element_map.get(art_data.get("chapter_number"))
        article = Article(
            law_version_id=version.id,
            structural_element_id=parent_se.id if parent_se else None,
            article_number=f"Art. {art_data['number']}",
            label=art_data.get("label", ""),
            full_text=art_data.get("full_text", ""),
            order_index=idx,
        )
        db.add(article)
        db.flush()

        for p_idx, para in enumerate(art_data.get("paragraphs", [])):
            paragraph = Paragraph(
                article_id=article.id,
                paragraph_number=para.get("number", ""),
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

    # Store annexes
    for idx, annex_data in enumerate(content.get("annexes", [])):
        annex = Annex(
            law_version_id=version.id,
            source_id=annex_data.get("source_id", f"annex_{idx}"),
            title=annex_data.get("title", ""),
            full_text=annex_data.get("full_text", ""),
            order_index=idx,
        )
        db.add(annex)

    return version


def _update_current_version(db: Session, law: Law):
    """Mark the newest version as is_current=True, all others False."""
    versions = db.query(LawVersion).filter_by(law_id=law.id).order_by(LawVersion.date_in_force.desc()).all()
    for i, v in enumerate(versions):
        v.is_current = (i == 0)


def _build_eli_url(doc_type: str, parsed: dict | None) -> str:
    """Build a EUR-Lex ELI URL from document type and parsed CELEX."""
    if not parsed:
        return ""
    type_map = {"regulation": "reg", "directive": "dir", "eu_decision": "dec", "treaty": "treaty"}
    eli_type = type_map.get(doc_type, "act")
    return f"http://data.europa.eu/eli/{eli_type}/{parsed['year']}/{parsed['number'].lstrip('0')}/oj"
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/eu_cellar_service.py
git commit -m "feat: add EU law import orchestration with version storage"
```

---

## Task 11: EU Import Safety Tests

**Files:**
- Create: `backend/tests/test_eu_safety.py`

- [ ] **Step 1: Write safety tests**

Create `backend/tests/test_eu_safety.py`:

```python
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

    # Pre-existing Romanian law
    ro_law = Law(title="Codul Civil", law_number="287", law_year=2009, source="ro")
    db.add(ro_law)
    db.flush()
    ro_version = LawVersion(law_id=ro_law.id, ver_id="267625", language="ro")
    db.add(ro_version)
    db.commit()
    ro_law_id = ro_law.id
    ro_ver_id = ro_version.id

    # Insert EU law
    eu_law = Law(
        title="GDPR", law_number="679", law_year=2016,
        source="eu", celex_number="32016R0679",
    )
    db.add(eu_law)
    db.flush()
    eu_version = LawVersion(law_id=eu_law.id, ver_id="02016R0679-20160504", language="ro")
    db.add(eu_version)
    db.commit()

    # Verify Romanian law is unchanged
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

    # Check that a query for the same celex finds the existing law
    existing = db.query(Law).filter(Law.celex_number == "32016R0679").first()
    assert existing is not None
    assert existing.id == law.id


def test_eu_law_counts_separate():
    """Can query EU and RO laws separately by source field."""
    db = _make_db()
    db.add(Law(title="Codul Civil", law_number="287", law_year=2009, source="ro"))
    db.add(Law(title="GDPR", law_number="679", law_year=2016, source="eu"))
    db.commit()

    ro_count = db.query(Law).filter(Law.source == "ro").count()
    eu_count = db.query(Law).filter(Law.source == "eu").count()
    assert ro_count == 1
    assert eu_count == 1
```

- [ ] **Step 2: Run tests**

```bash
cd /Users/anaandrei/projects/themis-legal && python -m pytest backend/tests/test_eu_safety.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_eu_safety.py
git commit -m "test: add production safety tests for EU import"
```

---

## Task 12: EU Import Integration Tests

**Files:**
- Create: `backend/tests/test_eu_import.py`

- [ ] **Step 1: Write integration tests with mocked CELLAR API**

Create `backend/tests/test_eu_import.py`:

```python
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
    # Seed EU categories
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
```

- [ ] **Step 2: Run tests**

```bash
cd /Users/anaandrei/projects/themis-legal && python -m pytest backend/tests/test_eu_import.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_eu_import.py
git commit -m "test: add EU import integration tests with mocked CELLAR API"
```

---

## Task 13: API Routes — EU Search and Import Endpoints

**Files:**
- Modify: `backend/app/routers/laws.py`

- [ ] **Step 1: Add EU request/response models**

At the top of `backend/app/routers/laws.py`, after the existing `ImportRequest` model, add:

```python
class EUImportRequest(BaseModel):
    celex_number: str
    import_history: bool = True


class EUSearchParams(BaseModel):
    keyword: str | None = None
    doc_type: str | None = None
    year: str | None = None
    number: str | None = None
    in_force_only: bool = False
```

- [ ] **Step 2: Add EU search endpoint**

Add after the existing `/api/laws/emitents` endpoint:

```python
@router.get("/eu/search")
def eu_search(
    keyword: str | None = None,
    doc_type: str | None = None,
    year: str | None = None,
    number: str | None = None,
    in_force_only: bool = False,
    db: Session = Depends(get_db),
):
    """Search EU legislation via CELLAR SPARQL."""
    from app.services.eu_cellar_service import search_eu_legislation
    results = search_eu_legislation(
        keyword=keyword, doc_type=doc_type, year=year,
        number=number, in_force_only=in_force_only,
    )
    # Mark already-imported laws
    for r in results:
        existing = db.query(Law).filter(Law.celex_number == r.celex).first()
        r.already_imported = existing is not None
    return [r.to_dict() for r in results]
```

- [ ] **Step 3: Add EU import endpoint**

Add after the EU search endpoint:

```python
@router.post("/eu/import")
def eu_import(req: EUImportRequest, db: Session = Depends(get_db)):
    """Import an EU law by CELEX number."""
    from app.services.eu_cellar_service import import_eu_law
    # Check for duplicate
    existing = db.query(Law).filter(Law.celex_number == req.celex_number).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Already imported as law_id={existing.id}")
    try:
        result = import_eu_law(db, req.celex_number, import_history=req.import_history)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"EU import failed for {req.celex_number}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 4: Add EU filter options endpoint**

```python
@router.get("/eu/filter-options")
def eu_filter_options():
    """Return available EU document type filters."""
    return {
        "doc_types": [
            {"value": "directive", "label": "Directive"},
            {"value": "regulation", "label": "Regulation"},
            {"value": "eu_decision", "label": "Decision"},
            {"value": "treaty", "label": "Treaty"},
        ]
    }
```

- [ ] **Step 5: Add `source` param to existing search endpoint**

Modify the existing `GET /api/laws/search` endpoint to accept an optional `source` query param. Find the function (around line 43) and update it:

```python
@router.get("/search")
def search_laws_endpoint(q: str, source: str | None = None, db: Session = Depends(get_db)):
    """Search laws from external sources. source: 'ro', 'eu', or None (both)."""
    results = []

    if source != "eu":
        # Existing Romanian search
        from app.services.search_service import search_laws
        ro_results = search_laws(q)
        for r in ro_results:
            d = r.to_dict()
            d["source"] = "ro"
            results.append(d)

    if source != "ro":
        # EU search
        from app.services.eu_cellar_service import search_eu_legislation
        eu_results = search_eu_legislation(keyword=q)
        for r in eu_results:
            existing = db.query(Law).filter(Law.celex_number == r.celex).first()
            r.already_imported = existing is not None
            d = r.to_dict()
            d["source"] = "eu"
            results.append(d)

    return results
```

- [ ] **Step 6: Add `source` param to advanced search endpoint**

Find the existing `GET /api/laws/advanced-search` endpoint and add `source: str | None = None` to its query params. Add early return if `source == "eu"`:

At the top of the function body, add:

```python
    if source == "eu":
        from app.services.eu_cellar_service import search_eu_legislation
        eu_results = search_eu_legislation(keyword=keyword, doc_type=doc_type, year=year, number=number)
        for r in eu_results:
            existing = db.query(Law).filter(Law.celex_number == r.celex).first()
            r.already_imported = existing is not None
        return {"results": [r.to_dict() for r in eu_results], "total": len(eu_results)}
```

Leave the rest of the function unchanged for `source != "eu"`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/laws.py
git commit -m "feat: add EU search, import, and filter API endpoints"
```

---

## Task 14: EU Version Discovery Service

**Files:**
- Create: `backend/app/services/eu_version_discovery.py`

- [ ] **Step 1: Implement weekly EU version discovery**

Create `backend/app/services/eu_version_discovery.py`:

```python
"""Weekly version discovery for EU legislation."""
import logging
import time
import datetime
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.law import Law, KnownVersion
from app.services.eu_cellar_service import fetch_consolidated_versions, parse_celex

logger = logging.getLogger(__name__)


def discover_eu_versions_for_law(db: Session, law: Law) -> int:
    """Discover new consolidated versions for a single EU law.

    Returns count of new versions discovered.
    """
    if not law.celex_number:
        return 0

    consol_versions = fetch_consolidated_versions(law.celex_number)
    if not consol_versions:
        return 0

    new_count = 0
    existing_ver_ids = {kv.ver_id for kv in db.query(KnownVersion).filter_by(law_id=law.id).all()}

    for cv in consol_versions:
        celex = cv["celex"]
        if celex in existing_ver_ids:
            continue

        date_in_force = None
        if cv.get("date"):
            try:
                date_in_force = datetime.date.fromisoformat(cv["date"][:10])
            except ValueError:
                date_in_force = datetime.date(1900, 1, 1)

        if date_in_force is None:
            # Try to extract from CELEX date suffix
            parsed = parse_celex(celex)
            if parsed and "consol_date" in parsed:
                ds = parsed["consol_date"]
                try:
                    date_in_force = datetime.date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
                except ValueError:
                    date_in_force = datetime.date(1900, 1, 1)

        if date_in_force is None:
            date_in_force = datetime.date(1900, 1, 1)

        kv = KnownVersion(
            law_id=law.id,
            ver_id=celex,
            date_in_force=date_in_force,
            is_current=False,
            discovered_at=datetime.datetime.utcnow(),
        )
        db.add(kv)
        new_count += 1

    if new_count:
        # Update is_current: newest date_in_force
        all_known = db.query(KnownVersion).filter_by(law_id=law.id).order_by(KnownVersion.date_in_force.desc()).all()
        for i, kv in enumerate(all_known):
            kv.is_current = (i == 0)

        law.last_checked_at = datetime.datetime.utcnow()
        db.commit()

    return new_count


def run_eu_weekly_discovery(rate_limit_delay: float = 2.0) -> dict:
    """Run version discovery for all EU laws. Called by scheduler."""
    db = SessionLocal()
    try:
        eu_laws = db.query(Law).filter(Law.source == "eu").all()
        checked = 0
        discovered = 0
        errors = 0

        for law in eu_laws:
            try:
                new = discover_eu_versions_for_law(db, law)
                discovered += new
                checked += 1
                if rate_limit_delay:
                    time.sleep(rate_limit_delay)
            except Exception as e:
                logger.error(f"EU version discovery failed for law {law.id} ({law.celex_number}): {e}")
                errors += 1
                db.rollback()

        logger.info(f"EU weekly discovery: checked={checked}, discovered={discovered}, errors={errors}")
        return {"checked": checked, "discovered": discovered, "errors": errors}
    finally:
        db.close()
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/eu_version_discovery.py
git commit -m "feat: add weekly EU version discovery service"
```

---

## Task 15: Register EU Discovery Job in Scheduler

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add EU weekly discovery job**

In `backend/app/main.py`, add a new run function alongside the existing `run_update_check`:

```python
def run_eu_update_check():
    """Scheduled job: discover new consolidated versions for all EU laws."""
    from app.services.eu_version_discovery import run_eu_weekly_discovery
    logger.info("Running scheduled EU version discovery...")
    results = run_eu_weekly_discovery()
    logger.info(f"EU discovery complete: {results}")
```

Then inside the `lifespan` function, after the existing `scheduler.add_job(run_update_check, ...)` block, add:

```python
    scheduler.add_job(
        run_eu_update_check,
        "cron",
        day_of_week="sun",
        hour=4,
        minute=0,
        id="weekly_eu_discovery",
        replace_existing=True,
    )
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: register weekly EU version discovery in scheduler (Sunday 04:00)"
```

---

## Task 16: Frontend API Client — EU Methods

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add EU TypeScript interfaces**

Add these interfaces after the existing `AdvancedSearchResult` interface:

```typescript
export interface EUSearchResult {
  celex: string
  title: string
  date: string
  doc_type: string
  in_force: boolean
  cellar_uri: string
  already_imported: boolean
  source: 'eu'
}

export interface EUFilterOptions {
  doc_types: { value: string; label: string }[]
}
```

- [ ] **Step 2: Add EU API methods**

In the `api.laws` object, add these methods:

```typescript
    euSearch(params: {
      keyword?: string; doc_type?: string; year?: string;
      number?: string; in_force_only?: boolean
    }): Promise<EUSearchResult[]> {
      const searchParams = new URLSearchParams()
      if (params.keyword) searchParams.set('keyword', params.keyword)
      if (params.doc_type) searchParams.set('doc_type', params.doc_type)
      if (params.year) searchParams.set('year', params.year)
      if (params.number) searchParams.set('number', params.number)
      if (params.in_force_only) searchParams.set('in_force_only', 'true')
      return apiFetch(`/api/laws/eu/search?${searchParams}`)
    },

    euImport(celexNumber: string, importHistory: boolean): Promise<{ law_id: number; title: string; versions_imported: number }> {
      return apiFetch('/api/laws/eu/import', {
        method: 'POST',
        body: JSON.stringify({ celex_number: celexNumber, import_history: importHistory }),
      })
    },

    euFilterOptions(): Promise<EUFilterOptions> {
      return apiFetch('/api/laws/eu/filter-options')
    },
```

- [ ] **Step 3: Update existing search method to accept source param**

Find the existing `advancedSearch` method and add `source?: string` to its params. Append `if (params.source) searchParams.set('source', params.source)` to the URLSearchParams builder.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add EU search, import, and filter API methods to frontend client"
```

---

## Task 17: Frontend — Source Toggle on Search Form

**Files:**
- Modify: `frontend/src/app/laws/search-import-form.tsx`

- [ ] **Step 1: Add source state and EU document types**

Add state variable at the top of the component's state declarations:

```typescript
const [source, setSource] = useState<'all' | 'ro' | 'eu'>('all')
```

Add EU document type defaults:

```typescript
const EU_DOC_TYPES: FilterOption[] = [
  { value: 'directive', label: 'Directive' },
  { value: 'regulation', label: 'Regulation' },
  { value: 'eu_decision', label: 'Decision' },
  { value: 'treaty', label: 'Treaty' },
]
```

- [ ] **Step 2: Add source toggle pills UI**

Add above the search input (before the existing `<form>` element):

```tsx
<div className="flex gap-1 mb-3 p-1 bg-neutral-100 dark:bg-neutral-800 rounded-lg w-fit">
  {(['all', 'ro', 'eu'] as const).map((s) => (
    <button
      key={s}
      type="button"
      onClick={() => { setSource(s); setResults([]); }}
      className={`px-3 py-1 text-sm rounded-md transition-colors ${
        source === s
          ? 'bg-white dark:bg-neutral-700 shadow-sm font-medium'
          : 'text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300'
      }`}
    >
      {s === 'all' ? 'All' : s === 'ro' ? 'Romanian' : 'EU'}
    </button>
  ))}
</div>
```

- [ ] **Step 3: Update document type dropdown based on source**

In the document type filter section, conditionally show EU or RO types:

```typescript
const visibleDocTypes = source === 'eu' ? EU_DOC_TYPES : source === 'ro' ? actTypes : [...actTypes, ...EU_DOC_TYPES]
```

Use `visibleDocTypes` instead of `actTypes` in the dropdown rendering.

- [ ] **Step 4: Update handleSearch to pass source param**

In the `handleSearch` function, if `source === 'eu'`, call the EU search endpoint instead:

```typescript
if (source === 'eu') {
  const euResults = await api.laws.euSearch({
    keyword: keyword || undefined,
    doc_type: selectedDocTypes.size === 1 ? [...selectedDocTypes][0] : undefined,
    year: year || undefined,
    number: lawNumber || undefined,
  })
  setResults(euResults.map(r => ({
    ver_id: r.celex,
    title: r.title,
    doc_type: r.doc_type,
    number: r.celex,
    date: r.date,
    date_iso: r.date,
    issuer: 'European Union',
    description: '',
    already_imported: r.already_imported,
    local_law_id: null,
    source: 'eu' as const,
  })))
  setTotal(euResults.length)
} else {
  // existing search logic, add source param
  searchParams.append('source', source === 'ro' ? 'ro' : '')
  // ... rest of existing code
}
```

- [ ] **Step 5: Update handleImport for EU results**

In `handleImport`, detect EU results and call the EU import endpoint:

```typescript
const handleImport = async (verId: string, importHistory: boolean) => {
  // Check if this is an EU result
  const result = results.find(r => r.ver_id === verId)
  if (result && (result as any).source === 'eu') {
    setImportingIds(prev => new Set(prev).add(verId))
    try {
      const res = await api.laws.euImport(verId, importHistory)
      setImportedIds(prev => new Map(prev).set(verId, res.law_id))
    } catch (err: any) {
      setImportErrors(prev => new Map(prev).set(verId, err.message || 'Import failed'))
    } finally {
      setImportingIds(prev => { const next = new Set(prev); next.delete(verId); return next })
    }
    return
  }
  // ... existing RO import logic
}
```

- [ ] **Step 6: Add source badge to search results**

In the result card rendering, add a badge showing the source:

```tsx
<span className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium ${
  (result as any).source === 'eu'
    ? 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300'
    : 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
}`}>
  {(result as any).source === 'eu' ? 'EU' : 'RO'}
</span>
```

- [ ] **Step 7: Add EUR-Lex URL detection for direct import**

In the URL detection regex (the `detectedUrl` computed value), add EUR-Lex patterns:

```typescript
const detectedUrl = keyword.match(
  /(?:https?:\/\/)?(?:legislatie\.just\.ro\/Public\/DetaliiDocument\/(\d+)|(?:eur-lex\.europa\.eu|data\.europa\.eu)\/.*?(\d{5}[A-Z]\d+))/i
)
```

When a EUR-Lex URL is detected, extract the CELEX and call `api.laws.euImport`.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/app/laws/search-import-form.tsx
git commit -m "feat: add source toggle, EU search, and EU import to search form"
```

---

## Task 18: Frontend — Law Card Badges (RO/EU and Language)

**Files:**
- Modify: `frontend/src/app/laws/library-page.tsx`

- [ ] **Step 1: Add source and language badges to law cards**

Find the law card rendering section. Each law card currently shows the title and metadata. Add a badge area. After the law title element, add:

```tsx
{/* Source and language badges */}
<div className="flex gap-1 ml-2">
  {law.source === 'eu' ? (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300">
      EU
    </span>
  ) : (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300">
      RO
    </span>
  )}
  {law.language === 'en' && (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-neutral-100 text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400">
      EN
    </span>
  )}
</div>
```

Note: The `LibraryLaw` interface in `api.ts` needs `source` and `language` fields added. Update the `LibraryLaw` interface:

```typescript
export interface LibraryLaw extends LawSummary {
  // ... existing fields ...
  source?: string
  language?: string
}
```

- [ ] **Step 2: Update the `/api/laws/` list endpoint to return source and language**

In `backend/app/routers/laws.py`, in the `GET /api/laws/` endpoint (the `list_laws` function around line 316), add `source` and `language` to the returned dict for each law. After the existing fields:

```python
            "source": law.source if hasattr(law, 'source') else "ro",
```

And for the `current_version` section, add:

```python
            "language": current.language if current and hasattr(current, 'language') else "ro",
```

- [ ] **Step 3: Update `get_library_data` to include source**

In `backend/app/services/category_service.py`, in the `get_library_data` function, add `source` to the law dict returned for each law. Find where law dicts are built and add:

```python
                "source": getattr(law, "source", "ro"),
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/laws/library-page.tsx frontend/src/lib/api.ts backend/app/routers/laws.py backend/app/services/category_service.py
git commit -m "feat: add RO/EU and language badges to law cards in library"
```

---

## Task 19: Run Full Test Suite

**Files:** None (verification only)

- [ ] **Step 1: Run all backend tests**

```bash
cd /Users/anaandrei/projects/themis-legal && python -m pytest backend/tests/ -v --tb=short
```

Expected: All tests pass, including new EU tests and all existing tests.

- [ ] **Step 2: Run frontend build check**

```bash
cd /Users/anaandrei/projects/themis-legal/frontend && npm run build
```

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 3: Fix any failures**

If any tests fail, fix the issues and commit fixes.

- [ ] **Step 4: Final commit if fixes were needed**

```bash
git add -A && git commit -m "fix: resolve test failures after EU integration"
```

---

## Task 20: Manual Smoke Test Checklist

This is a verification task — no code changes, just manual checks.

- [ ] **Step 1: Start the backend**

```bash
cd /Users/anaandrei/projects/themis-legal && python -m uvicorn backend.app.main:app --reload --port 8000
```

Verify in logs:
- "Added column laws.source" (first run only)
- "Added eu.decision category" (first run only)
- No errors about missing tables or columns

- [ ] **Step 2: Test EU search endpoint**

```bash
curl "http://localhost:8000/api/laws/eu/search?keyword=data+protection&doc_type=regulation" | python -m json.tool
```

Verify: Returns SPARQL results with CELEX numbers.

- [ ] **Step 3: Test EU import endpoint**

```bash
curl -X POST http://localhost:8000/api/laws/eu/import -H "Content-Type: application/json" -d '{"celex_number": "32016R0679", "import_history": false}'
```

Verify: Returns `{law_id, title, versions_imported: 1}`.

- [ ] **Step 4: Test duplicate rejection**

```bash
curl -X POST http://localhost:8000/api/laws/eu/import -H "Content-Type: application/json" -d '{"celex_number": "32016R0679", "import_history": false}'
```

Verify: Returns 409 Conflict.

- [ ] **Step 5: Verify library shows EU law**

```bash
curl http://localhost:8000/api/laws/library | python -m json.tool | grep -A5 "eu.regulation"
```

Verify: GDPR appears under the EU regulations category.

- [ ] **Step 6: Verify Romanian laws unchanged**

```bash
curl http://localhost:8000/api/laws/ | python -m json.tool | head -50
```

Verify: Existing Romanian laws still present with `source: "ro"`.
