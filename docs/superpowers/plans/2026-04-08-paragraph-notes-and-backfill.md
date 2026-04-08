# Paragraph Notes & Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make paragraph-level amendment notes and `text_clean` available for every law version (new and existing) so that the upcoming diff backend (Spec 2) can do label-based structural matching with note enrichment, without modifying any existing imported content.

**Architecture:** Three layers, shipped in order. (1) An additive SQLite migration in the existing `lifespan()` startup hook adds `amendment_notes.paragraph_id`, `amendment_notes.note_source_id`, and `articles.text_clean` / `paragraphs.text_clean`. (2) Two pure helpers (`note_text_cleaner`, `note_subject_parser`) plus an importer edit make new imports populate the new fields. (3) A read-only, idempotent backfill job re-fetches each existing version through leropa, inserts paragraph-level notes, and writes `text_clean`, all guarded by a SQLAlchemy `before_flush` listener that hard-aborts on any forbidden mutation.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x (declarative + Mapped), FastAPI, SQLite (production + tests), pytest, leropa parser, uv.

**Spec:** `docs/superpowers/specs/2026-04-08-paragraph-notes-and-backfill-design.md`

---

## File map

```
backend/
  app/main.py                              EDIT (lifespan: add columns + indexes)
  app/models/law.py                        EDIT (AmendmentNote, Article, Paragraph)
  app/services/leropa_service.py           EDIT (_import_article)
  app/services/note_text_cleaner.py        NEW (pure helper)
  app/services/note_subject_parser.py      NEW (pure helper)
  app/services/notes_backfill.py           NEW (read-only additive backfill)
  app/routers/admin.py                     EDIT (POST /admin/backfill/notes)
  scripts/backfill_paragraph_notes.py      NEW (CLI wrapper)
  tests/test_note_text_cleaner.py          NEW
  tests/test_note_subject_parser.py        NEW
  tests/test_notes_backfill.py             NEW
  tests/test_paragraph_notes_schema.py     NEW (smoke test for migration)
  tests/test_leropa_paragraph_notes.py     NEW (importer integration)
```

---

## Task 1: Schema migration (lifespan ALTERs + model fields)

**Files:**
- Modify: `backend/app/models/law.py:194-223` (Paragraph, Article relationships) and `backend/app/models/law.py:226-243` (AmendmentNote columns + relationship)
- Modify: `backend/app/main.py:108-117` (additive migration block in lifespan)
- Test: `backend/tests/test_paragraph_notes_schema.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_paragraph_notes_schema.py`:

```python
"""Smoke test that the paragraph-notes migration adds the expected columns + indexes."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models.law  # noqa: F401 — register tables


def _fresh_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_amendment_notes_has_paragraph_id_and_note_source_id():
    engine = _fresh_engine()
    Base.metadata.create_all(bind=engine)
    cols = {c["name"] for c in inspect(engine).get_columns("amendment_notes")}
    assert "paragraph_id" in cols
    assert "note_source_id" in cols


def test_articles_and_paragraphs_have_text_clean():
    engine = _fresh_engine()
    Base.metadata.create_all(bind=engine)
    art_cols = {c["name"] for c in inspect(engine).get_columns("articles")}
    par_cols = {c["name"] for c in inspect(engine).get_columns("paragraphs")}
    assert "text_clean" in art_cols
    assert "text_clean" in par_cols


def test_amendment_note_has_paragraph_relationship():
    from app.models.law import AmendmentNote, Paragraph
    assert hasattr(AmendmentNote, "paragraph")
    # The relationship is configured to back-populate from Paragraph
    rel = AmendmentNote.paragraph.property
    assert rel.mapper.class_ is Paragraph
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_paragraph_notes_schema.py -v
```

Expected: all three tests FAIL — `paragraph_id`/`note_source_id`/`text_clean` columns don't exist; `AmendmentNote.paragraph` attribute does not exist.

- [ ] **Step 3: Add the new columns + relationship to `app/models/law.py`**

In `backend/app/models/law.py`:

Change the `Article` block (around line 168-191) — add `text_clean`:

```python
class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    law_version_id: Mapped[int] = mapped_column(
        ForeignKey("law_versions.id"), nullable=False, index=True
    )
    structural_element_id: Mapped[int | None] = mapped_column(
        ForeignKey("structural_elements.id"), nullable=True, index=True
    )
    article_number: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    text_clean: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_abrogated: Mapped[bool] = mapped_column(Boolean, default=False)

    law_version: Mapped["LawVersion"] = relationship(back_populates="articles")
    structural_element: Mapped["StructuralElement | None"] = relationship(
        back_populates="articles"
    )
    paragraphs: Mapped[list["Paragraph"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
    amendment_notes: Mapped[list["AmendmentNote"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
```

(Match the existing column types and ordering from the file — only the `text_clean` line is new. If your file's `Article` has additional columns I haven't shown here, leave them; only add `text_clean`.)

Change the `Paragraph` block (around line 194-209) — add `text_clean` and a `paragraph_notes` relationship:

```python
class Paragraph(Base):
    __tablename__ = "paragraphs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id"), nullable=False, index=True
    )
    paragraph_number: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_clean: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    article: Mapped["Article"] = relationship(back_populates="paragraphs")
    subparagraphs: Mapped[list["Subparagraph"]] = relationship(
        back_populates="paragraph", cascade="all, delete-orphan"
    )
    amendment_notes: Mapped[list["AmendmentNote"]] = relationship(
        back_populates="paragraph", cascade="all, delete-orphan",
        foreign_keys="AmendmentNote.paragraph_id",
    )
```

Change the `AmendmentNote` block (around line 226-243) — add `paragraph_id`, `note_source_id`, `paragraph` relationship:

```python
class AmendmentNote(Base):
    __tablename__ = "amendment_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id"), nullable=False, index=True
    )
    paragraph_id: Mapped[int | None] = mapped_column(
        ForeignKey("paragraphs.id"), nullable=True, index=True
    )
    note_source_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    law_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    law_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    monitor_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    monitor_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    replacement_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    article: Mapped["Article"] = relationship(back_populates="amendment_notes")
    paragraph: Mapped["Paragraph | None"] = relationship(
        back_populates="amendment_notes",
        foreign_keys=[paragraph_id],
    )
```

- [ ] **Step 4: Run model-level tests**

```bash
cd backend && uv run pytest tests/test_paragraph_notes_schema.py -v
```

Expected: PASS. `Base.metadata.create_all` now provisions the new columns and the relationship attribute exists.

- [ ] **Step 5: Add the runtime ALTERs in `lifespan()` for live-DB upgrades**

In `backend/app/main.py`, locate the additive migration block inside `lifespan()` (currently around lines 108-117 after `_add_column_if_missing(...)` calls) and **append** these lines right after the existing `_add_column_if_missing(...)` calls, before `seed_defaults(db)`:

```python
        # Paragraph-notes migration (Spec 1: 2026-04-08-paragraph-notes-and-backfill)
        _add_column_if_missing(db, "amendment_notes", "paragraph_id", "INTEGER", None)
        _add_column_if_missing(db, "amendment_notes", "note_source_id", "VARCHAR(200)", None)
        _add_column_if_missing(db, "articles", "text_clean", "TEXT", None)
        _add_column_if_missing(db, "paragraphs", "text_clean", "TEXT", None)
        db.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_amendment_notes_paragraph_id "
            "ON amendment_notes(paragraph_id)"
        ))
        db.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_amendment_notes_dedupe "
            "ON amendment_notes(article_id, COALESCE(paragraph_id, 0), COALESCE(note_source_id, ''))"
        ))
        db.commit()
```

(`text` is already imported at the top of `main.py` for the existing `UPDATE law_mappings` line — verify and add the import if not.)

- [ ] **Step 6: Run the full test suite for regressions**

```bash
cd backend && uv run pytest tests/test_paragraph_notes_schema.py tests/test_diff_endpoint.py -v
```

Expected: PASS. The diff endpoint test should still work — only nullable columns and a new relationship were added.

- [ ] **Step 7: Commit**

```bash
cd backend && git add app/models/law.py app/main.py tests/test_paragraph_notes_schema.py
git commit -m "$(cat <<'EOF'
feat(schema): add paragraph_id/note_source_id to amendment_notes + text_clean

Additive SQLite migration via the existing lifespan _add_column_if_missing
helper. New columns are nullable; nothing reads them yet. Adds a unique
dedupe index on (article_id, paragraph_id, note_source_id) so the upcoming
backfill is idempotent at the DB level. Spec 1 of the version-diff redesign.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `note_text_cleaner` — strip inline `(la <date>, …)` annotations

**Files:**
- Create: `backend/app/services/note_text_cleaner.py`
- Test: `backend/tests/test_note_text_cleaner.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_note_text_cleaner.py`:

```python
"""Unit tests for note_text_cleaner.strip — removing inline (la <date>, …) annotations."""
from app.services.note_text_cleaner import strip


def test_text_with_no_notes_is_unchanged():
    assert strip("Articolul are un singur alineat.") == "Articolul are un singur alineat."


def test_strips_single_inline_note_at_end():
    raw = (
        "Operatorul economic plătește accize. "
        "(la 31-03-2026, Articolul 336 a fost completat de Punctul 9., "
        "Articolul I din ORDONANȚA DE URGENȚĂ nr. 89 din 23 decembrie 2025)"
    )
    cleaned = strip(raw)
    assert cleaned == "Operatorul economic plătește accize."


def test_strips_multiple_inline_notes():
    raw = (
        "Prima frază. (la 01-01-2024, Articolul 1 a fost modificat de Legea nr. 5/2023) "
        "A doua frază. (la 02-02-2025, Articolul 1 a fost completat de OUG nr. 7/2024)"
    )
    cleaned = strip(raw)
    assert cleaned == "Prima frază. A doua frază."


def test_handles_nested_parentheses_inside_note():
    raw = (
        "Textul de bază. "
        "(la 31-03-2026, Articolul 5 (definiții) a fost modificat de Legea nr. 10/2025)"
    )
    cleaned = strip(raw)
    assert cleaned == "Textul de bază."


def test_unbalanced_note_returns_text_unchanged():
    raw = "Frază netulburată. (la 31-03-2026, Articolul 5 a fost modificat"
    # Defensive: malformed input is left as-is rather than mangled
    assert strip(raw) == raw


def test_only_strips_la_prefix_not_other_parens():
    raw = "Capitalul social (minimum 200 lei) trebuie depus."
    assert strip(raw) == "Capitalul social (minimum 200 lei) trebuie depus."


def test_collapses_double_spaces_left_after_stripping():
    raw = "Înainte (la 01-01-2024, Articolul 1 a fost modificat de Legea nr. 5/2023) după."
    assert strip(raw) == "Înainte după."
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_note_text_cleaner.py -v
```

Expected: FAIL — module `app.services.note_text_cleaner` does not exist.

- [ ] **Step 3: Implement the cleaner**

Create `backend/app/services/note_text_cleaner.py`:

```python
"""Strip inline modification annotations of the form `(la <date>, …)` from law text.

These annotations are embedded by legislatie.just.ro inside article and paragraph
text and act as an inline changelog. They are stored as separate `AmendmentNote`
rows by the importer; for diffing we want them removed from the body so that
text comparisons reflect substance, not metadata.
"""

from __future__ import annotations

import re

# Match the start of an inline note: an opening paren immediately followed by
# the literal "la " and a date-like token. Date format on legislatie.just.ro is
# DD-MM-YYYY, occasionally DD.MM.YYYY. We accept both.
_NOTE_START = re.compile(r"\(la \d{1,2}[-./]\d{1,2}[-./]\d{2,4}")


def strip(text: str) -> str:
    """Return `text` with every inline `(la <date>, …)` annotation removed.

    The scanner walks the string, finds each note start, then advances a
    parenthesis-depth counter to find the matching close. If a note start has
    no balanced close (malformed input), the text is returned unchanged from
    that point — we never mangle.

    Whitespace runs left behind by removed notes are collapsed to a single
    space, and leading/trailing whitespace on the result is stripped.
    """
    if not text:
        return text

    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        m = _NOTE_START.search(text, i)
        if m is None:
            out.append(text[i:])
            break

        # Emit everything before the note
        out.append(text[i : m.start()])

        # Walk parens from the note's opening "("
        depth = 0
        j = m.start()
        end = -1
        while j < n:
            ch = text[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
            j += 1

        if end == -1:
            # Unbalanced — bail out without modifying anything from this point
            out.append(text[m.start() :])
            break

        # Skip the note entirely; continue after the closing paren
        i = end

    cleaned = "".join(out)
    # Collapse runs of whitespace introduced by the removal and trim edges
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([.,;:])", r"\1", cleaned)  # " ." → "."
    return cleaned.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_note_text_cleaner.py -v
```

Expected: all 7 PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/note_text_cleaner.py tests/test_note_text_cleaner.py
git commit -m "$(cat <<'EOF'
feat(notes): add note_text_cleaner pure helper

Strips inline (la <date>, …) modification annotations from article and
paragraph text using a balanced-paren scanner. Conservative on malformed
input (returns unchanged). Will be used by the importer and backfill to
populate the new text_clean columns. Spec 1.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `note_subject_parser` — map a leropa note's subject to (article, paragraph)

**Files:**
- Create: `backend/app/services/note_subject_parser.py`
- Test: `backend/tests/test_note_subject_parser.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_note_subject_parser.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_note_subject_parser.py -v
```

Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the parser**

Create `backend/app/services/note_subject_parser.py`:

```python
"""Parse leropa Note.subject strings into structural labels.

The `subject` field of a leropa amendment note is freeform Romanian. We map a
small set of common phrasings to (article_label, paragraph_label?,
subparagraph_label?). Anything we cannot match returns an all-None ParsedSubject
and the caller falls back to article-level attribution.

This module is pure: no DB, no I/O, total (never raises).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A label is one or more digits/roman numerals/letters, optionally with a
# caret-suffix (e.g. "1^2"). Romanian source uses the caret instead of a
# superscript.
_LABEL = r"[A-Za-z0-9]+(?:\^[A-Za-z0-9]+)?"
_PARAG = r"\([A-Za-z0-9]+(?:\^[A-Za-z0-9]+)?\)"  # e.g. (1), (2^1)
_LITERA = rf"{_LABEL}\)"  # e.g. a), b^1)


@dataclass(frozen=True)
class ParsedSubject:
    article_label: str | None = None
    paragraph_label: str | None = None
    subparagraph_label: str | None = None


# Patterns are tried in order. The first match wins. Each pattern uses named
# groups (`art`, `par`, `sub`) for the labels we want.
_PATTERNS: list[re.Pattern[str]] = [
    # "Litera a) a alineatului (2) al articolului 336"
    re.compile(
        rf"Litera\s+(?P<sub>{_LITERA})\s+a\s+alineatului\s+(?P<par>{_PARAG})"
        rf"\s+al\s+articolului\s+(?P<art>{_LABEL})",
        re.IGNORECASE,
    ),
    # "Articolul 5, alineatul (1), litera c)"
    re.compile(
        rf"Articolul\s+(?P<art>{_LABEL}),\s*alineatul\s+(?P<par>{_PARAG}),"
        rf"\s*litera\s+(?P<sub>{_LITERA})",
        re.IGNORECASE,
    ),
    # "Alineatul (1) al articolului 336"
    re.compile(
        rf"Alineatul\s+(?P<par>{_PARAG})\s+al\s+articolului\s+(?P<art>{_LABEL})",
        re.IGNORECASE,
    ),
    # "Articolul 5, alineatul (1)"
    re.compile(
        rf"Articolul\s+(?P<art>{_LABEL}),\s*alineatul\s+(?P<par>{_PARAG})",
        re.IGNORECASE,
    ),
    # "Articolul 336" (must be last — most generic)
    re.compile(
        rf"^\s*Articolul\s+(?P<art>{_LABEL})\s*$",
        re.IGNORECASE,
    ),
    # "articolului 336" (lowercase, used inside compound subjects we already
    # tried above; this catches stragglers like "Punctul 9. al articolului I")
    re.compile(
        rf"articolului\s+(?P<art>{_LABEL})",
        re.IGNORECASE,
    ),
]


def parse(subject: str | None) -> ParsedSubject:
    """Map a freeform note subject to a ParsedSubject. Always returns; never raises."""
    if not subject:
        return ParsedSubject()
    s = subject.strip()
    for pat in _PATTERNS:
        m = pat.search(s)
        if m:
            groups = m.groupdict()
            return ParsedSubject(
                article_label=groups.get("art"),
                paragraph_label=groups.get("par"),
                subparagraph_label=groups.get("sub"),
            )
    return ParsedSubject()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_note_subject_parser.py -v
```

Expected: all 10 PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/note_subject_parser.py tests/test_note_subject_parser.py
git commit -m "$(cat <<'EOF'
feat(notes): add note_subject_parser pure helper

Parses leropa Note.subject strings into (article, paragraph, subparagraph)
labels via a small ordered regex set. Total — never raises; unrecognised
subjects return all-None and the caller falls back to article-level
attribution. Spec 1.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Importer change — store paragraph notes + populate `text_clean`

**Files:**
- Modify: `backend/app/services/leropa_service.py:497-552` (the `_import_article` function)
- Test: `backend/tests/test_leropa_paragraph_notes.py`

- [ ] **Step 1: Write the failing integration test**

Create `backend/tests/test_leropa_paragraph_notes.py`:

```python
"""Integration test: leropa importer stores paragraph-level notes and text_clean."""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.law import (
    AmendmentNote,
    Article,
    Law,
    LawVersion,
    Paragraph,
)
import app.models.category  # noqa: F401
from app.services.leropa_service import _import_article


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _make_version(db):
    law = Law(title="T", law_number="1", law_year=2020)
    db.add(law)
    db.flush()
    v = LawVersion(
        law_id=law.id, ver_id="100",
        date_in_force=datetime.date(2024, 1, 1),
        state="actual", is_current=True,
    )
    db.add(v)
    db.flush()
    return v


def test_imports_article_level_note_unchanged(db):
    """Existing behaviour: article-level notes still land in amendment_notes."""
    version = _make_version(db)
    art_data = {
        "label": "1",
        "full_text": "Articolul 1. Text.",
        "paragraphs": [],
        "notes": [
            {
                "note_id": "art-note-1",
                "text": "(la 01-01-2024, Articolul 1 a fost modificat …)",
                "date": "01-01-2024",
                "subject": "Articolul 1",
                "law_number": "5",
            }
        ],
    }
    _import_article(db, version, parent=None, art_data=art_data, order_index=0)
    db.flush()
    notes = db.query(AmendmentNote).all()
    assert len(notes) == 1
    assert notes[0].paragraph_id is None
    assert notes[0].note_source_id == "art-note-1"


def test_imports_paragraph_level_note_with_paragraph_id(db):
    """New behaviour: paragraph-level notes are stored and linked to the paragraph."""
    version = _make_version(db)
    art_data = {
        "label": "5",
        "full_text": "Articolul 5. (1) Definiții.",
        "paragraphs": [
            {
                "label": "(1)",
                "text": "Definiții.",
                "subparagraphs": [],
                "notes": [
                    {
                        "note_id": "par-note-1",
                        "text": "(la 02-02-2025, Alineatul (1) al articolului 5 a fost modificat …)",
                        "date": "02-02-2025",
                        "subject": "Alineatul (1) al articolului 5",
                        "law_number": "7",
                    }
                ],
            }
        ],
        "notes": [],
    }
    _import_article(db, version, parent=None, art_data=art_data, order_index=0)
    db.flush()
    notes = db.query(AmendmentNote).all()
    assert len(notes) == 1
    note = notes[0]
    assert note.note_source_id == "par-note-1"
    assert note.paragraph_id is not None
    par = db.query(Paragraph).filter_by(id=note.paragraph_id).one()
    assert par.label == "(1)"
    assert note.article_id == par.article_id


def test_writes_text_clean_for_article_and_paragraph(db):
    """Article.text_clean and Paragraph.text_clean strip inline (la …) annotations."""
    version = _make_version(db)
    raw_full = "Articolul 1. Text. (la 01-01-2024, Articolul 1 a fost modificat de Legea nr. 5/2023)"
    raw_par = "Conținut. (la 02-02-2025, Alineatul (1) a fost modificat de OUG nr. 7/2024)"
    art_data = {
        "label": "1",
        "full_text": raw_full,
        "paragraphs": [
            {"label": "(1)", "text": raw_par, "subparagraphs": [], "notes": []}
        ],
        "notes": [],
    }
    _import_article(db, version, parent=None, art_data=art_data, order_index=0)
    db.flush()
    art = db.query(Article).one()
    par = db.query(Paragraph).one()
    assert art.text_clean == "Articolul 1. Text."
    assert par.text_clean == "Conținut."
    # Original full_text / text are untouched
    assert art.full_text == raw_full
    assert par.text == raw_par
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_leropa_paragraph_notes.py -v
```

Expected: the first test PASSes (existing behaviour), the second and third FAIL — paragraph-level notes are dropped, `text_clean` is None, `note_source_id` is None on the existing note.

- [ ] **Step 3: Edit `_import_article` in `app/services/leropa_service.py`**

In `backend/app/services/leropa_service.py`, replace the body of `_import_article` (currently around lines 497-552 — the part starting at `full_text = art_data.get("full_text", "")` and ending after the article-level notes loop) with this. The existing function signature stays the same:

```python
def _import_article(
    db: Session,
    version: LawVersion,
    parent: StructuralElement | None,
    art_data: dict,
    order_index: int,
) -> None:
    from app.services.note_text_cleaner import strip as strip_notes

    full_text = art_data.get("full_text", "")
    is_abrogated = bool(re.search(r"^\s*\(?\s*[Aa]brogat", full_text[:200]))

    article = Article(
        law_version_id=version.id,
        structural_element_id=parent.id if parent else None,
        article_number=art_data.get("label", "?"),
        label=art_data.get("label"),
        full_text=full_text,
        text_clean=strip_notes(full_text),
        order_index=order_index,
        is_abrogated=is_abrogated,
    )
    db.add(article)
    db.flush()

    # Paragraphs
    for p_idx, par in enumerate(art_data.get("paragraphs", [])):
        par_text = par.get("text", "")
        paragraph = Paragraph(
            article_id=article.id,
            paragraph_number=par.get("label") or str(p_idx + 1),
            label=par.get("label"),
            text=par_text,
            text_clean=strip_notes(par_text),
            order_index=p_idx,
        )
        db.add(paragraph)
        db.flush()

        # Subparagraphs
        for sp_idx, sub in enumerate(par.get("subparagraphs", [])):
            subparagraph = Subparagraph(
                paragraph_id=paragraph.id,
                label=sub.get("label"),
                text=sub.get("text", ""),
                order_index=sp_idx,
            )
            db.add(subparagraph)

        # Paragraph-level amendment notes (NEW — previously discarded)
        for note in par.get("notes", []):
            db.add(AmendmentNote(
                article_id=article.id,
                paragraph_id=paragraph.id,
                note_source_id=note.get("note_id"),
                text=note.get("text"),
                date=note.get("date"),
                subject=note.get("subject"),
                law_number=note.get("law_number"),
                law_date=note.get("law_date"),
                monitor_number=note.get("monitor_number"),
                monitor_date=note.get("monitor_date"),
                original_text=note.get("replaced"),
                replacement_text=note.get("replacement"),
            ))

    # Article-level amendment notes (existing behaviour)
    for note in art_data.get("notes", []):
        db.add(AmendmentNote(
            article_id=article.id,
            paragraph_id=None,
            note_source_id=note.get("note_id"),
            text=note.get("text"),
            date=note.get("date"),
            subject=note.get("subject"),
            law_number=note.get("law_number"),
            law_date=note.get("law_date"),
            monitor_number=note.get("monitor_number"),
            monitor_date=note.get("monitor_date"),
            original_text=note.get("replaced"),
            replacement_text=note.get("replacement"),
        ))
```

- [ ] **Step 4: Run integration tests**

```bash
cd backend && uv run pytest tests/test_leropa_paragraph_notes.py tests/test_paragraph_notes_schema.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the existing import-touching tests for regressions**

```bash
cd backend && uv run pytest tests/ -v -k "leropa or import or diff" 2>&1 | tail -40
```

Expected: no new failures. (Existing failures unrelated to this change are acceptable; investigate any that touch articles/paragraphs/notes.)

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/services/leropa_service.py tests/test_leropa_paragraph_notes.py
git commit -m "$(cat <<'EOF'
feat(import): store paragraph-level notes + text_clean on fresh imports

leropa exposes amendment notes both at article and paragraph level. The
importer was iterating only the article-level set and dropping paragraph
notes on the floor. This adds the paragraph-level loop, persists each
note's leropa note_id as note_source_id (used as the dedupe key), and
populates Article/Paragraph.text_clean by stripping inline (la <date>, …)
annotations via note_text_cleaner. Existing article-level behaviour is
unchanged. Spec 1.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `notes_backfill` — read-only additive backfill with safety guardrail

**Files:**
- Create: `backend/app/services/notes_backfill.py`
- Test: `backend/tests/test_notes_backfill.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_notes_backfill.py`:

```python
"""Tests for the additive paragraph-notes backfill job."""
import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.law import (
    AmendmentNote,
    Article,
    Law,
    LawVersion,
    Paragraph,
)
import app.models.category  # noqa: F401
from app.services.notes_backfill import (
    BackfillSafetyError,
    backfill_notes,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _seed_one_version_no_notes(db):
    """Seed a law version with one article and one paragraph, NO notes yet."""
    law = Law(title="T", law_number="1", law_year=2020)
    db.add(law)
    db.flush()
    v = LawVersion(
        law_id=law.id, ver_id="100",
        date_in_force=datetime.date(2024, 1, 1),
        state="actual", is_current=True,
    )
    db.add(v)
    db.flush()
    art = Article(
        law_version_id=v.id, article_number="5", label="5",
        full_text="Articolul 5. (1) Definiții. (la 02-02-2025, Alineatul (1) a fost modificat de OUG nr. 7/2024)",
        order_index=0,
    )
    db.add(art)
    db.flush()
    par = Paragraph(
        article_id=art.id, paragraph_number="(1)", label="(1)",
        text="Definiții. (la 02-02-2025, Alineatul (1) a fost modificat de OUG nr. 7/2024)",
        order_index=0,
    )
    db.add(par)
    db.commit()
    return law, v, art, par


def _fake_leropa_result_with_paragraph_note(version_ver_id: str) -> dict:
    return {
        "document": {"title": "T"},
        "articles": [
            {
                "label": "5",
                "full_text": "Articolul 5. (1) Definiții.",
                "paragraphs": [
                    {
                        "label": "(1)",
                        "text": "Definiții.",
                        "subparagraphs": [],
                        "notes": [
                            {
                                "note_id": "par-note-xyz",
                                "text": "(la 02-02-2025, Alineatul (1) al articolului 5 a fost modificat …)",
                                "date": "02-02-2025",
                                "subject": "Alineatul (1) al articolului 5",
                                "law_number": "7",
                            }
                        ],
                    }
                ],
                "notes": [],
            }
        ],
        "books": [],
    }


def test_dry_run_inserts_nothing(db):
    law, v, art, par = _seed_one_version_no_notes(db)
    with patch(
        "app.services.notes_backfill.fetch_document",
        return_value=_fake_leropa_result_with_paragraph_note(v.ver_id),
    ):
        report = backfill_notes(db, dry_run=True)
    db.expire_all()
    assert db.query(AmendmentNote).count() == 0
    assert report.paragraph_notes_to_insert == 1
    assert report.versions_processed == 1


def test_live_run_inserts_paragraph_note_with_paragraph_id(db):
    law, v, art, par = _seed_one_version_no_notes(db)
    with patch(
        "app.services.notes_backfill.fetch_document",
        return_value=_fake_leropa_result_with_paragraph_note(v.ver_id),
    ):
        backfill_notes(db, dry_run=False)
    db.expire_all()
    notes = db.query(AmendmentNote).all()
    assert len(notes) == 1
    assert notes[0].paragraph_id == par.id
    assert notes[0].article_id == art.id
    assert notes[0].note_source_id == "par-note-xyz"


def test_live_run_writes_text_clean_only_when_null(db):
    law, v, art, par = _seed_one_version_no_notes(db)
    with patch(
        "app.services.notes_backfill.fetch_document",
        return_value=_fake_leropa_result_with_paragraph_note(v.ver_id),
    ):
        backfill_notes(db, dry_run=False)
    db.expire_all()
    art_after = db.query(Article).one()
    par_after = db.query(Paragraph).one()
    assert art_after.text_clean == "Articolul 5. (1) Definiții."
    assert par_after.text_clean == "Definiții."


def test_re_running_is_a_noop(db):
    law, v, art, par = _seed_one_version_no_notes(db)
    fake = _fake_leropa_result_with_paragraph_note(v.ver_id)
    with patch("app.services.notes_backfill.fetch_document", return_value=fake):
        backfill_notes(db, dry_run=False)
        backfill_notes(db, dry_run=False)
    db.expire_all()
    # Unique index + IS NULL gating means the second run inserts nothing
    assert db.query(AmendmentNote).count() == 1


def test_guardrail_blocks_update_to_existing_article_text(db):
    """The guardrail must abort the job if anything tries to UPDATE Article.full_text."""
    law, v, art, par = _seed_one_version_no_notes(db)

    def evil_fetch(*args, **kwargs):
        # Simulate a buggy backfill that mutates an existing Article during the job
        existing = db.query(Article).first()
        existing.full_text = "MUTATED"
        return _fake_leropa_result_with_paragraph_note(v.ver_id)

    with patch("app.services.notes_backfill.fetch_document", side_effect=evil_fetch):
        with pytest.raises(BackfillSafetyError):
            backfill_notes(db, dry_run=False)


def test_unknown_paragraph_label_skips_with_warning(db, caplog):
    """If leropa returns a paragraph our DB doesn't have, log + skip — never guess."""
    law, v, art, par = _seed_one_version_no_notes(db)
    fake = _fake_leropa_result_with_paragraph_note(v.ver_id)
    fake["articles"][0]["paragraphs"][0]["label"] = "(99)"  # nonexistent label

    with patch("app.services.notes_backfill.fetch_document", return_value=fake):
        backfill_notes(db, dry_run=False)
    db.expire_all()
    assert db.query(AmendmentNote).count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_notes_backfill.py -v
```

Expected: FAIL — module `app.services.notes_backfill` does not exist.

- [ ] **Step 3: Implement the backfill module**

Create `backend/app/services/notes_backfill.py`:

```python
"""Read-only additive backfill of paragraph-level amendment notes and text_clean.

This job re-fetches each LawVersion through leropa and:
  1. INSERTs any paragraph-level AmendmentNote rows that aren't already present
     (deduped at the DB level via the ux_amendment_notes_dedupe unique index).
  2. INSERTs any article-level notes whose note_source_id is missing.
  3. UPDATEs Article.text_clean and Paragraph.text_clean ONLY when they are NULL.

It NEVER touches existing rows in laws / law_versions / articles / paragraphs /
subparagraphs beyond writing the new text_clean column. A SQLAlchemy before_flush
guardrail enforces this at runtime: any forbidden mutation aborts the job
immediately.

Idempotent. Resumable (per-version transactions). Dry-run by default.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.orm import Session

from app.models.law import (
    AmendmentNote,
    Article,
    Law,
    LawVersion,
    Paragraph,
    Subparagraph,
)
from app.services.fetcher import fetch_document
from app.services.note_text_cleaner import strip as strip_notes

logger = logging.getLogger(__name__)

# Tables that the backfill must not modify
_FORBIDDEN_TYPES = {Law, LawVersion, Subparagraph}
# Tables where the only allowed mutation is writing text_clean on a NULL column
_TEXT_CLEAN_ONLY_TYPES = {Article, Paragraph}


class BackfillSafetyError(RuntimeError):
    """Raised when the guardrail detects a forbidden mutation."""


@dataclass
class BackfillReport:
    versions_processed: int = 0
    versions_failed: int = 0
    paragraph_notes_to_insert: int = 0
    article_notes_to_insert: int = 0
    text_clean_writes: int = 0
    unknown_paragraph_labels: list[str] = field(default_factory=list)
    unparsed_subjects: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def backfill_notes(
    db: Session,
    *,
    law_id: int | None = None,
    dry_run: bool = True,
    on_progress: Callable[[int, int], None] | None = None,
    fetch_delay_seconds: float = 0.5,
) -> BackfillReport:
    """Run the additive backfill. Returns a BackfillReport.

    Args:
        db: SQLAlchemy session bound to the production engine.
        law_id: Restrict to a single law (None = all laws).
        dry_run: When True, the per-version transaction is rolled back after
                 counting; nothing is persisted.
        on_progress: Optional callback (i, total) for progress UIs.
        fetch_delay_seconds: Sleep between leropa fetches to be polite.
    """
    report = BackfillReport()

    versions_q = db.query(LawVersion)
    if law_id is not None:
        versions_q = versions_q.filter(LawVersion.law_id == law_id)
    versions = versions_q.order_by(LawVersion.id).all()
    total = len(versions)

    _install_guardrail(db)
    try:
        for i, version in enumerate(versions, start=1):
            try:
                _process_version(db, version, dry_run=dry_run, report=report)
                report.versions_processed += 1
            except BackfillSafetyError:
                # Guardrail violations are fatal; surface immediately
                db.rollback()
                raise
            except Exception as exc:
                logger.exception(
                    "Backfill failed for version_id=%s ver_id=%s",
                    version.id, version.ver_id,
                )
                report.versions_failed += 1
                report.errors.append(f"version {version.ver_id}: {exc}")
                db.rollback()
            if on_progress is not None:
                on_progress(i, total)
            if fetch_delay_seconds > 0 and i < total:
                time.sleep(fetch_delay_seconds)
    finally:
        _uninstall_guardrail(db)

    return report


def _process_version(
    db: Session,
    version: LawVersion,
    *,
    dry_run: bool,
    report: BackfillReport,
) -> None:
    """Process one version inside its own transaction."""
    result = fetch_document(version.ver_id)
    parsed_articles = result.get("articles", [])

    # Build label → row lookups for THIS version's existing data
    existing_articles = (
        db.query(Article).filter(Article.law_version_id == version.id).all()
    )
    article_by_label: dict[str, Article] = {a.label or a.article_number: a for a in existing_articles}
    paragraph_by_key: dict[tuple[str, str], Paragraph] = {}
    article_id_to_paragraphs: dict[int, list[Paragraph]] = {}
    for art in existing_articles:
        pars = (
            db.query(Paragraph).filter(Paragraph.article_id == art.id).all()
        )
        article_id_to_paragraphs[art.id] = pars
        for p in pars:
            key = (art.label or art.article_number, p.label or "")
            paragraph_by_key[key] = p

    # Pre-load existing note_source_ids for this version's articles to dedupe
    existing_source_ids: set[tuple[int, int | None, str | None]] = set()
    for art in existing_articles:
        for n in db.query(AmendmentNote).filter(AmendmentNote.article_id == art.id).all():
            existing_source_ids.add((n.article_id, n.paragraph_id, n.note_source_id))

    for parsed_art in parsed_articles:
        art_label = parsed_art.get("label")
        if not art_label:
            continue
        art_row = article_by_label.get(art_label)
        if art_row is None:
            report.unknown_paragraph_labels.append(f"{version.ver_id}:art:{art_label}")
            continue

        # text_clean for the article (only if currently NULL)
        if art_row.text_clean is None:
            art_row.text_clean = strip_notes(parsed_art.get("full_text", ""))
            report.text_clean_writes += 1

        # Paragraph-level notes
        for parsed_par in parsed_art.get("paragraphs", []):
            par_label = parsed_par.get("label")
            par_row = paragraph_by_key.get((art_label, par_label or ""))
            if par_row is None:
                report.unknown_paragraph_labels.append(
                    f"{version.ver_id}:{art_label}:{par_label}"
                )
                logger.warning(
                    "Backfill: paragraph (%s, %s) not found in version %s — skipping",
                    art_label, par_label, version.ver_id,
                )
                continue

            if par_row.text_clean is None:
                par_row.text_clean = strip_notes(parsed_par.get("text", ""))
                report.text_clean_writes += 1

            for note in parsed_par.get("notes", []):
                key = (art_row.id, par_row.id, note.get("note_id"))
                if key in existing_source_ids:
                    continue
                report.paragraph_notes_to_insert += 1
                db.add(AmendmentNote(
                    article_id=art_row.id,
                    paragraph_id=par_row.id,
                    note_source_id=note.get("note_id"),
                    text=note.get("text"),
                    date=note.get("date"),
                    subject=note.get("subject"),
                    law_number=note.get("law_number"),
                    law_date=note.get("law_date"),
                    monitor_number=note.get("monitor_number"),
                    monitor_date=note.get("monitor_date"),
                    original_text=note.get("replaced"),
                    replacement_text=note.get("replacement"),
                ))
                existing_source_ids.add(key)

        # Article-level notes (catches notes added to source HTML after original import)
        for note in parsed_art.get("notes", []):
            key = (art_row.id, None, note.get("note_id"))
            if key in existing_source_ids:
                continue
            report.article_notes_to_insert += 1
            db.add(AmendmentNote(
                article_id=art_row.id,
                paragraph_id=None,
                note_source_id=note.get("note_id"),
                text=note.get("text"),
                date=note.get("date"),
                subject=note.get("subject"),
                law_number=note.get("law_number"),
                law_date=note.get("law_date"),
                monitor_number=note.get("monitor_number"),
                monitor_date=note.get("monitor_date"),
                original_text=note.get("replaced"),
                replacement_text=note.get("replacement"),
            ))
            existing_source_ids.add(key)

    if dry_run:
        db.rollback()
    else:
        db.commit()


# ---------------------------------------------------------------------------
# Safety guardrail
# ---------------------------------------------------------------------------

_GUARDRAIL_LISTENER = None


def _install_guardrail(db: Session) -> None:
    global _GUARDRAIL_LISTENER

    def _before_flush(session, flush_context, instances):  # noqa: ARG001
        for obj in session.deleted:
            if type(obj) in _FORBIDDEN_TYPES or type(obj) in _TEXT_CLEAN_ONLY_TYPES:
                raise BackfillSafetyError(
                    f"Backfill attempted to DELETE {type(obj).__name__} id={getattr(obj, 'id', '?')}"
                )
        for obj in session.dirty:
            t = type(obj)
            if t in _FORBIDDEN_TYPES:
                raise BackfillSafetyError(
                    f"Backfill attempted to UPDATE {t.__name__} id={getattr(obj, 'id', '?')}"
                )
            if t in _TEXT_CLEAN_ONLY_TYPES:
                state = sa_inspect(obj)
                for attr in state.attrs:
                    if attr.history.has_changes() and attr.key != "text_clean":
                        raise BackfillSafetyError(
                            f"Backfill attempted to UPDATE {t.__name__}.{attr.key} "
                            f"id={getattr(obj, 'id', '?')} — only text_clean writes are allowed"
                        )

    _GUARDRAIL_LISTENER = _before_flush
    event.listen(db, "before_flush", _GUARDRAIL_LISTENER)


def _uninstall_guardrail(db: Session) -> None:
    global _GUARDRAIL_LISTENER
    if _GUARDRAIL_LISTENER is not None:
        try:
            event.remove(db, "before_flush", _GUARDRAIL_LISTENER)
        except Exception:
            pass
        _GUARDRAIL_LISTENER = None
```

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_notes_backfill.py -v
```

Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/notes_backfill.py tests/test_notes_backfill.py
git commit -m "$(cat <<'EOF'
feat(notes): add read-only additive backfill for paragraph notes + text_clean

Re-fetches each LawVersion through leropa and inserts any missing
paragraph-level AmendmentNote rows. Idempotent via the unique dedupe index.
Per-version transactions; dry-run by default. A SQLAlchemy before_flush
guardrail aborts the job immediately if anything tries to DELETE or UPDATE
laws / law_versions / subparagraphs, or to UPDATE any column on
articles / paragraphs other than text_clean. Spec 1.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Admin endpoint + CLI script

**Files:**
- Modify: `backend/app/routers/admin.py` (append a new endpoint)
- Create: `backend/scripts/backfill_paragraph_notes.py`
- Test: extend `backend/tests/test_notes_backfill.py` with one endpoint test (using TestClient)

- [ ] **Step 1: Write the failing endpoint test**

Append to `backend/tests/test_notes_backfill.py`:

```python
from fastapi.testclient import TestClient

from app.auth import require_admin
from app.database import get_db
from app.main import app as fastapi_app
from app.models.user import User


def test_admin_endpoint_dry_run(db):
    law, v, art, par = _seed_one_version_no_notes(db)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_admin():
        return User(id=1, email="admin@example.com")

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[require_admin] = override_admin
    try:
        with patch(
            "app.services.notes_backfill.fetch_document",
            return_value=_fake_leropa_result_with_paragraph_note(v.ver_id),
        ):
            client = TestClient(fastapi_app)
            r = client.post("/api/admin/backfill/notes", json={"dry_run": True})
        assert r.status_code == 200
        body = r.json()
        assert body["versions_processed"] == 1
        assert body["paragraph_notes_to_insert"] == 1
        assert db.query(AmendmentNote).count() == 0
    finally:
        fastapi_app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_notes_backfill.py::test_admin_endpoint_dry_run -v
```

Expected: FAIL — endpoint does not exist (404).

- [ ] **Step 3: Add the endpoint to `app/routers/admin.py`**

Append to `backend/app/routers/admin.py`:

```python
# ---------------------------------------------------------------------------
# Paragraph-notes backfill (Spec 1: 2026-04-08-paragraph-notes-and-backfill)
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _BaseModel  # already imported elsewhere — keep one


class BackfillNotesRequest(_BaseModel):
    law_id: int | None = None
    dry_run: bool = True


@router.post("/backfill/notes")
def trigger_backfill_notes(
    req: BackfillNotesRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.notes_backfill import backfill_notes

    report = backfill_notes(
        db,
        law_id=req.law_id,
        dry_run=req.dry_run,
    )
    return {
        "dry_run": req.dry_run,
        "versions_processed": report.versions_processed,
        "versions_failed": report.versions_failed,
        "paragraph_notes_to_insert": report.paragraph_notes_to_insert,
        "article_notes_to_insert": report.article_notes_to_insert,
        "text_clean_writes": report.text_clean_writes,
        "unknown_paragraph_labels": report.unknown_paragraph_labels[:50],
        "errors": report.errors[:50],
    }
```

If `BaseModel`, `Session`, `User`, `Depends`, or `get_db` are not yet imported in `admin.py`, add them at the top of the file in the existing import block (check what's already imported and add only the missing ones).

- [ ] **Step 4: Run the endpoint test**

```bash
cd backend && uv run pytest tests/test_notes_backfill.py::test_admin_endpoint_dry_run -v
```

Expected: PASS.

- [ ] **Step 5: Create the CLI wrapper script**

Create `backend/scripts/backfill_paragraph_notes.py`:

```python
"""CLI: run the paragraph-notes backfill against a SQLite database file.

Usage:
    uv run python -m scripts.backfill_paragraph_notes [--law-id N] [--no-dry-run] [--db PATH]

Examples:
    # Dry run against the default DB
    uv run python -m scripts.backfill_paragraph_notes

    # Live run against the default DB
    uv run python -m scripts.backfill_paragraph_notes --no-dry-run

    # Dry run for a single law against a specific DB file
    uv run python -m scripts.backfill_paragraph_notes --law-id 5 --db data/themis.db
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Make `app` importable when run as a script from backend/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.services.notes_backfill import backfill_notes  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Paragraph-notes backfill")
    parser.add_argument("--law-id", type=int, default=None)
    parser.add_argument("--no-dry-run", action="store_true",
                        help="Actually persist changes (default is dry run)")
    parser.add_argument("--db", default="data/themis.db", help="Path to the SQLite DB file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    engine = create_engine(
        f"sqlite:///{args.db}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Session = sessionmaker(bind=engine)
    db = Session()

    def progress(i: int, total: int) -> None:
        print(f"  [{i}/{total}] versions", flush=True)

    try:
        report = backfill_notes(
            db,
            law_id=args.law_id,
            dry_run=not args.no_dry_run,
            on_progress=progress,
        )
    finally:
        db.close()

    print()
    print("=" * 60)
    print(f"DRY RUN" if not args.no_dry_run else "LIVE RUN")
    print("=" * 60)
    print(f"versions_processed:        {report.versions_processed}")
    print(f"versions_failed:           {report.versions_failed}")
    print(f"paragraph_notes_to_insert: {report.paragraph_notes_to_insert}")
    print(f"article_notes_to_insert:   {report.article_notes_to_insert}")
    print(f"text_clean_writes:         {report.text_clean_writes}")
    if report.unknown_paragraph_labels:
        print(f"unknown_paragraph_labels (first 20):")
        for s in report.unknown_paragraph_labels[:20]:
            print(f"  - {s}")
    if report.errors:
        print(f"errors (first 20):")
        for e in report.errors[:20]:
            print(f"  - {e}")
    return 1 if report.versions_failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Smoke-test the CLI locally**

```bash
cd backend && uv run python scripts/backfill_paragraph_notes.py --db /tmp/nonexistent.db --verbose 2>&1 | head -10
```

Expected: it runs, finds zero versions, prints the report (versions_processed=0, exit code 0). If the script blows up on import, fix and re-run.

- [ ] **Step 7: Commit**

```bash
cd backend && git add app/routers/admin.py scripts/backfill_paragraph_notes.py tests/test_notes_backfill.py
git commit -m "$(cat <<'EOF'
feat(admin): expose backfill_notes via admin endpoint and CLI

POST /api/admin/backfill/notes triggers the read-only backfill from the
admin UI / curl, defaulting to dry-run. scripts/backfill_paragraph_notes.py
provides a one-shot CLI wrapper for ops use against the SQLite file on
the Railway volume. Spec 1.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Operator runbook (docs only)

**Files:**
- Create: `docs/superpowers/runbooks/2026-04-08-paragraph-notes-backfill.md`

- [ ] **Step 1: Write the runbook**

Create `docs/superpowers/runbooks/2026-04-08-paragraph-notes-backfill.md`:

````markdown
# Runbook: Paragraph-Notes Backfill

**Owner:** Ana
**Spec:** `docs/superpowers/specs/2026-04-08-paragraph-notes-and-backfill-design.md`
**Last reviewed:** 2026-04-08

## What this does
Inserts paragraph-level amendment notes and populates `text_clean` for every
existing `LawVersion` in production. Fully additive — never modifies or
deletes existing `laws`, `law_versions`, `articles`, `paragraphs`, or
`subparagraphs` rows (enforced by a runtime guardrail).

## Pre-flight checklist

- [ ] Migration deployed: confirm `paragraph_id`, `note_source_id`, and
      `text_clean` columns exist in production by inspecting the live DB
      (e.g. `sqlite3 /data/themis.db ".schema amendment_notes"`).
- [ ] Importer change deployed: confirm any law imported after the deploy
      shows paragraph-level notes in `amendment_notes` (smoke test by
      importing one tiny law via the admin UI and querying
      `SELECT COUNT(*) FROM amendment_notes WHERE paragraph_id IS NOT NULL`).
- [ ] **Snapshot the SQLite file** off the Railway volume:
      `railway run -- cp /data/themis.db /tmp/themis-pre-backfill-$(date +%F).db`
      Then download it locally with `railway volume download` or equivalent.
- [ ] (Optional but recommended) Mount a Railway volume at `/root/.leropa`
      so the leropa HTML cache survives container restarts. The backfill
      will work without it but will hit legislatie.just.ro for every fetch.

## Run order

### 1. Dry run on one small law
Pick the smallest law in the library — go to `/laws` and find one with
≤3 versions and a short article list. Note its `id`.

```bash
# From local machine, against a downloaded copy of the prod DB:
cd backend
uv run python scripts/backfill_paragraph_notes.py --law-id <ID> --db /path/to/prod.db
```

Review the report:
- `versions_processed` should equal the law's version count.
- `paragraph_notes_to_insert` should be > 0 if the law has any modification history.
- `unknown_paragraph_labels` should be small (or empty). A few warnings are
  acceptable; many indicate parser drift and need investigation before the
  full run.
- `errors` should be empty.

### 2. Dry run on all laws

```bash
uv run python scripts/backfill_paragraph_notes.py --db /path/to/prod.db
```

Read the full report. Expected outcomes:
- `versions_failed == 0` (any failure means we investigate before live).
- `unknown_paragraph_labels` count: anything over ~5% of total notes is a
  red flag — likely a missing pattern in `note_subject_parser` or a parser
  divergence. Investigate, add patterns, re-run.
- `errors` should be empty.

### 3. Live run (production)

Either via the admin endpoint:

```bash
curl -X POST https://<your-prod-url>/api/admin/backfill/notes \
     -H "Authorization: Bearer <admin-token>" \
     -H "Content-Type: application/json" \
     -d '{"dry_run": false}'
```

…or via the CLI on a Railway shell:

```bash
railway run -- uv run python backend/scripts/backfill_paragraph_notes.py --no-dry-run --db /data/themis.db
```

The endpoint runs synchronously in this version — for ~100 laws that may
take 10–30 minutes depending on network. If it times out, re-run; the job
is idempotent.

### 4. Verify

```sql
-- Should be > 0
SELECT COUNT(*) FROM amendment_notes WHERE paragraph_id IS NOT NULL;

-- Should be ~equal to total articles count
SELECT COUNT(*) FROM articles WHERE text_clean IS NOT NULL;

-- Should be ~equal to total paragraphs count
SELECT COUNT(*) FROM paragraphs WHERE text_clean IS NOT NULL;
```

## Rollback

The backfill is additive, so the rollback is "restore the snapshot from the
pre-flight checklist". On Railway:

```bash
railway run -- cp /tmp/themis-pre-backfill-YYYY-MM-DD.db /data/themis.db
# then restart the backend service
```

No data is destroyed by re-running the backfill on the restored DB.
````

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/runbooks/2026-04-08-paragraph-notes-backfill.md
git commit -m "$(cat <<'EOF'
docs: runbook for paragraph-notes backfill

Operator-facing checklist for running the Spec 1 backfill in production:
preflight (snapshot, migration verification), dry runs, live run, verify
queries, rollback procedure.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Final verification — full test suite + manual smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

```bash
cd backend && uv run pytest tests/ -x --tb=short 2>&1 | tail -40
```

Expected: no new failures introduced by Spec 1 changes. Pre-existing failures unrelated to articles/paragraphs/notes/diff are acceptable but should be noted.

- [ ] **Step 2: Start the dev server and verify lifespan migration runs cleanly**

```bash
cd backend && uv run uvicorn app.main:app --port 8000 2>&1 | head -50
```

Expected log lines (interleaved with normal startup):
```
Added column amendment_notes.paragraph_id
Added column amendment_notes.note_source_id
Added column articles.text_clean
Added column paragraphs.text_clean
```

(Subsequent restarts should NOT print these — `_add_column_if_missing` is idempotent.)

Hit `Ctrl-C` to stop.

- [ ] **Step 3: Sanity-check the schema in the local DB**

```bash
cd backend && sqlite3 data/themis.db ".schema amendment_notes" 2>&1 | head -30
```

Expected: the output shows `paragraph_id` and `note_source_id` columns and the `ux_amendment_notes_dedupe` unique index.

- [ ] **Step 4: Run a dry-run backfill against the local DB**

```bash
cd backend && uv run python scripts/backfill_paragraph_notes.py --verbose
```

Expected: it iterates through whatever local versions exist, prints a report, makes no DB changes. If the local DB has no laws, the report shows zeros and exits cleanly.

- [ ] **Step 5: Final commit (only if any tweaks were needed in steps 1-4)**

If everything passed without changes, skip this step. Otherwise:

```bash
cd backend && git add -A
git commit -m "$(cat <<'EOF'
chore: spec 1 verification fixes

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Infra — persistent leropa cache volume on Railway (manual)

**Files:** none in this repo (Railway dashboard / config)

This is a manual operator step done at deploy time, not code. Documented here so it isn't forgotten.

- [ ] **Step 1: In the Railway dashboard for the backend service, add a volume**
  - Mount path: `/root/.leropa`
  - Size: 1 GB

- [ ] **Step 2: Redeploy** so the volume mounts.

- [ ] **Step 3: Verify**
  ```bash
  railway run -- ls -la /root/.leropa
  ```
  Expected: empty directory exists. After the first backfill the directory
  fills with `<ver_id>.html` files and survives subsequent redeploys.

- [ ] **Step 4: Update the runbook** to note that the volume is mounted (so
      the next operator doesn't have to wonder).

---

## Done criteria

- All tests in `backend/tests/test_paragraph_notes_schema.py`,
  `test_note_text_cleaner.py`, `test_note_subject_parser.py`,
  `test_leropa_paragraph_notes.py`, and `test_notes_backfill.py` pass.
- Local dev server starts cleanly and the migration log lines appear once.
- `/api/admin/backfill/notes` returns a populated report on dry run.
- Production has been backfilled (operator runs Task 7 runbook end-to-end).
- Production now satisfies: `SELECT COUNT(*) FROM amendment_notes WHERE paragraph_id IS NOT NULL > 0` and `text_clean` is non-null on every article and paragraph.

When all of the above are true, Spec 1 is shipped and we're ready to write Spec 2 (the new note-augmented diff backend).
