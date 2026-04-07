# Version Diff Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the parsed-tree-based version diff (which produces garbage matchings and 28 k-char text blobs for definition-list articles like art 5) with a tokenizer-based diff that scans `Article.full_text`, emits flat per-alineat items, and aligns them by content via `difflib.SequenceMatcher`.

**Architecture:** Two backend modules — a pure `article_tokenizer` that converts `full_text` into a flat `list[AtomicUnit]` with marker false-positive filtering, and a rewritten `structured_diff` that groups units by `alineat_label` and aligns each group with SequenceMatcher + greedy similarity pairing inside `replace` opcodes. Frontend renders the resulting flat units grouped by alineat header. No DB, parser, or migration changes.

**Tech Stack:** Python 3.12 + pytest + SQLAlchemy (backend tests already use a real DB-backed session via `app.database.SessionLocal`). TypeScript + Next.js + React on the frontend. The backend uses `difflib.SequenceMatcher` from the stdlib (already in use today in `structured_diff.py`).

**Spec:** `docs/superpowers/specs/2026-04-07-version-diff-redesign-design.md`

**Branch:** Continue on `fix/version-discovery-dead-state`.

---

## File structure

**Created:**

- `backend/app/services/article_tokenizer.py` — pure: `tokenize_article(full_text) -> list[AtomicUnit]` plus the `AtomicUnit` dataclass and the `MarkerKind` constants. No SQLAlchemy, no logging, no DB. ~250 lines.
- `backend/tests/test_article_tokenizer.py` — unit tests + parameterized snapshot tests. ~200 lines.
- `backend/tests/fixtures/tokenizer/art5-definitions.txt` — real `Article.full_text` snapshot for art 5 of Romanian insolvency law (extracted from the dev DB).
- `backend/tests/fixtures/tokenizer/art5-definitions.expected.json` — expected `list[AtomicUnit]` for art 5 (generated once, then frozen as a regression baseline).
- `backend/tests/fixtures/tokenizer/art7-simple.txt` + `.expected.json` — small two-alineat article, hand-written.
- `backend/tests/fixtures/tokenizer/art-with-bullets.txt` + `.expected.json` — litera bodies containing en-dash bullets.
- `backend/tests/fixtures/tokenizer/art-abrogat.txt` + `.expected.json` — `Abrogat.` only.
- `backend/tests/fixtures/tokenizer/art-no-alineate.txt` + `.expected.json` — single sentence, no markers.
- `backend/tests/fixtures/tokenizer/art-renumbered-marker.txt` + `.expected.json` — `^N` markers at all three depths.
- `backend/tests/fixtures/diff/art5-v517-fulltext.txt` — `Article.full_text` for art 5 v517 (regression input).
- `backend/tests/fixtures/diff/art5-v529-fulltext.txt` — `Article.full_text` for art 5 v529 (regression input).

**Modified:**

- `backend/app/services/structured_diff.py` — internal rewrite. Public surface (`diff_articles(arts_a, arts_b) -> list[dict]`) and `_pair_renumbered` are kept. The old `word_diff_html`, `_diff_subparagraphs`, `_diff_paragraphs_list`, `diff_paragraph`, `diff_article` are replaced by a new tokenizer-driven `diff_article` and a new `_diff_alineat_items` helper. `word_diff_html` itself is **kept** (still used at the leaf level).
- `backend/tests/test_structured_diff.py` — rewritten. Old paragraph/subparagraph fake-class tests are deleted; new tests cover tokenizer-driven diffing, content-based alignment, replace-block pairing, fallback path, and the art 5 regression.
- `frontend/src/lib/api.ts` — replace `DiffSubparagraph` and `DiffParagraph` types with a single `DiffUnit` type; update `DiffArticle` to carry `units: DiffUnit[]` instead of `paragraphs: DiffParagraph[]`.
- `frontend/src/app/laws/[id]/diff/components/diff-leaf.tsx` — rewritten. The old `DiffParagraphLeaf` and `DiffSubparagraphLeaf` exports become a single `DiffUnitRow`. `CollapsedRun` is kept and adapted to take `DiffUnit[]`.
- `frontend/src/app/laws/[id]/diff/components/structured-diff-article.tsx` — body now groups `article.units` by `alineat_label` and renders each group as an alineat section with a header and a stream of `DiffUnitRow`s + `CollapsedRun`s.
- `frontend/src/app/laws/[id]/diff/page.tsx` — only if a type compile error surfaces. No behavior change planned.
- `frontend/src/app/laws/[id]/diff/diff.css` — no functional change planned. Class names referenced from the new components must already exist or be added.

**Not touched:** the parser (`leropa_service.py`, `eu_html_parser.py`), the DB schema, the import pipeline, `backend/app/routers/laws.py` (the `/laws/{id}/diff` endpoint reads from `diff_articles` whose signature is unchanged), the version-list view, and `diff_summary.py`.

---

## Task 1: Scaffold the tokenizer module

**Files:**
- Create: `backend/app/services/article_tokenizer.py`
- Create: `backend/tests/test_article_tokenizer.py`

- [ ] **Step 1.1: Write the failing test**

Create `backend/tests/test_article_tokenizer.py` with:

```python
"""Tests for the article tokenizer."""
from app.services.article_tokenizer import tokenize_article, AtomicUnit


def test_empty_string_returns_empty_list():
    assert tokenize_article("") == []
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.article_tokenizer'`.

- [ ] **Step 1.3: Write minimal implementation**

Create `backend/app/services/article_tokenizer.py`:

```python
"""Pure tokenizer for Romanian legal article text.

Walks Article.full_text, finds marker positions (alineate, numbered points,
litere, bullets), filters out false-positive matches inside legal references
like 'art. 90 alin. (1)', and emits a flat list of AtomicUnit dataclasses
in document order. The tokenizer does NOT try to reconstruct parent-child
relationships between numbered points and their literae — investigation of
real Article.full_text showed that the leropa parser does not preserve
that structure in full_text. Diff matching is content-based (see
structured_diff.py), so a flat representation is sufficient.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AtomicUnit:
    """One leaf item from an article: an alineat header, a numbered point,
    a litera, an upper-case litera, a bullet, or pre-marker intro text.

    `alineat_label` is the alineat the item lives inside, or None for
    items emitted before the first alineat marker (or for articles with
    no alineate at all). `label` is the marker as it appears in the
    source ("(1)", "32.", "a)", "A.", "–", or "" for intro). `text` is
    the body content after the marker, whitespace-normalized. `marker_kind`
    is one of the MarkerKind constants.
    """
    alineat_label: str | None
    marker_kind: str
    label: str
    text: str


class MarkerKind:
    INTRO = "intro"
    ALINEAT = "alineat"
    NUMBERED = "numbered"
    LITERA = "litera"
    UPPER_LITERA = "upper_litera"
    BULLET = "bullet"


def tokenize_article(full_text: str) -> list[AtomicUnit]:
    """Tokenize an article's full_text into a flat list of AtomicUnit.

    Empty input returns an empty list. See module docstring for the
    overall algorithm.
    """
    if not full_text:
        return []
    return []  # filled in by later tasks
```

- [ ] **Step 1.4: Run test to verify it passes**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py -v`

Expected: PASS — `test_empty_string_returns_empty_list` is green.

- [ ] **Step 1.5: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/app/services/article_tokenizer.py backend/tests/test_article_tokenizer.py
git commit -m "feat(backend): scaffold article_tokenizer module"
```

---

## Task 2: Tokenizer — pre-marker intro text

When `full_text` has content but no marker has been recognized yet (or no markers at all), the entire pre-marker prefix becomes one `intro` `AtomicUnit` with `alineat_label=None`, `marker_kind="intro"`, `label=""`, and `text` set to the whitespace-normalized content.

**Files:**
- Modify: `backend/app/services/article_tokenizer.py`
- Modify: `backend/tests/test_article_tokenizer.py`

- [ ] **Step 2.1: Write the failing tests**

Append to `backend/tests/test_article_tokenizer.py`:

```python
def test_plain_sentence_no_markers_returns_one_intro_unit():
    units = tokenize_article("Articolul 100 se abrogă.")
    assert units == [
        AtomicUnit(
            alineat_label=None,
            marker_kind="intro",
            label="",
            text="Articolul 100 se abrogă.",
        )
    ]


def test_plain_sentence_collapses_internal_whitespace():
    units = tokenize_article("  Articolul 100   se abrogă.\n  ")
    assert len(units) == 1
    assert units[0].text == "Articolul 100 se abrogă."
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py -v`

Expected: FAIL — `tokenize_article` returns `[]` instead of the expected unit.

- [ ] **Step 2.3: Implement whitespace normalization helper + intro emission**

Edit `backend/app/services/article_tokenizer.py`. Add this helper above `tokenize_article`:

```python
import re

_WHITESPACE_RUN = re.compile(r"\s+")


def _normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace to a single space and strip ends."""
    return _WHITESPACE_RUN.sub(" ", text).strip()
```

Replace the body of `tokenize_article` with:

```python
def tokenize_article(full_text: str) -> list[AtomicUnit]:
    if not full_text:
        return []

    # No markers recognized yet — emit the whole text as one intro unit.
    normalized = _normalize_whitespace(full_text)
    if not normalized:
        return []
    return [
        AtomicUnit(
            alineat_label=None,
            marker_kind=MarkerKind.INTRO,
            label="",
            text=normalized,
        )
    ]
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py -v`

Expected: PASS — all three tests green.

- [ ] **Step 2.5: Commit**

```bash
git add backend/app/services/article_tokenizer.py backend/tests/test_article_tokenizer.py
git commit -m "feat(backend): tokenizer emits intro unit for pre-marker text"
```

---

## Task 3: Tokenizer — alineat marker recognition

Add the `alineat` marker pattern. When `(N)` is found in the text, the text **before** that match becomes a pre-alineat intro unit (already handled by Task 2 for the no-marker case — now we generalize), the alineat itself becomes one `AtomicUnit` with `marker_kind="alineat"` whose `text` is the slice from `match.end()` to the next marker (or end of string), and subsequent items are tagged with this `alineat_label`.

**Files:**
- Modify: `backend/app/services/article_tokenizer.py`
- Modify: `backend/tests/test_article_tokenizer.py`

- [ ] **Step 3.1: Write the failing tests**

Append to `backend/tests/test_article_tokenizer.py`:

```python
def test_single_alineat_emits_alineat_unit():
    units = tokenize_article("(1) Statul român este suveran.")
    assert units == [
        AtomicUnit(
            alineat_label=None,  # the alineat marker itself sits at the boundary
            marker_kind="alineat",
            label="(1)",
            text="Statul român este suveran.",
        )
    ]


def test_two_alineate_emit_two_units():
    units = tokenize_article("(1) Primul alineat. (2) Al doilea alineat.")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", "Primul alineat."),
        AtomicUnit(None, "alineat", "(2)", "Al doilea alineat."),
    ]


def test_text_before_first_alineat_becomes_intro():
    units = tokenize_article("Preambul al articolului. (1) Conținutul.")
    assert units == [
        AtomicUnit(None, "intro", "", "Preambul al articolului."),
        AtomicUnit(None, "alineat", "(1)", "Conținutul."),
    ]
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py -v`

Expected: FAIL — current tokenizer emits one giant intro unit.

- [ ] **Step 3.3: Implement the marker scanning algorithm with alineat support**

Edit `backend/app/services/article_tokenizer.py`. Replace the imports section and add new constants + helpers below them:

```python
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AtomicUnit:
    alineat_label: str | None
    marker_kind: str
    label: str
    text: str


class MarkerKind:
    INTRO = "intro"
    ALINEAT = "alineat"
    NUMBERED = "numbered"
    LITERA = "litera"
    UPPER_LITERA = "upper_litera"
    BULLET = "bullet"


# Each entry: (kind, compiled_regex). The regex MUST have one capture group
# returning the marker label as it should appear in the output (e.g. "(1)",
# "32.", "a)"). Order matters only for tie-breaking when two patterns match
# at the same start position — see _resolve_overlaps.
_MARKER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (MarkerKind.ALINEAT, re.compile(r"\(\s*(\d+(?:\^\d+)?)\s*\)")),
]


@dataclass(frozen=True)
class _Match:
    start: int        # inclusive byte offset in full_text where the marker begins
    end: int          # exclusive byte offset where the marker ends (body starts here)
    kind: str
    label: str        # rendered label as it will appear in the AtomicUnit


def _find_all_markers(full_text: str) -> list[_Match]:
    """Scan full_text for every marker candidate, deduplicating overlaps.

    Returns matches sorted by start offset. Overlapping matches at the same
    start position are resolved by _MARKER_PATTERNS order (earlier wins).
    Matches whose start offset falls inside an already-accepted match's body
    are dropped to prevent nested false positives.
    """
    candidates: list[_Match] = []
    for kind, pattern in _MARKER_PATTERNS:
        for m in pattern.finditer(full_text):
            label = _format_label(kind, m.group(1))
            candidates.append(_Match(start=m.start(), end=m.end(), kind=kind, label=label))
    candidates.sort(key=lambda c: (c.start, _kind_priority(c.kind)))
    return candidates


def _kind_priority(kind: str) -> int:
    """Lower wins when two markers match at the same start position."""
    return {
        MarkerKind.ALINEAT: 0,
        MarkerKind.NUMBERED: 1,
        MarkerKind.UPPER_LITERA: 2,
        MarkerKind.LITERA: 3,
        MarkerKind.BULLET: 4,
    }.get(kind, 99)


def _format_label(kind: str, raw_group: str) -> str:
    """Build the AtomicUnit.label from the regex group capture."""
    if kind == MarkerKind.ALINEAT:
        return f"({raw_group})"
    return raw_group  # filled in by later tasks


_WHITESPACE_RUN = re.compile(r"\s+")


def _normalize_whitespace(text: str) -> str:
    return _WHITESPACE_RUN.sub(" ", text).strip()
```

Replace the body of `tokenize_article` with:

```python
def tokenize_article(full_text: str) -> list[AtomicUnit]:
    if not full_text:
        return []

    matches = _find_all_markers(full_text)

    # No markers — entire text is one intro unit.
    if not matches:
        normalized = _normalize_whitespace(full_text)
        if not normalized:
            return []
        return [AtomicUnit(None, MarkerKind.INTRO, "", normalized)]

    units: list[AtomicUnit] = []
    current_alineat: str | None = None

    # Pre-marker text: everything before matches[0].start
    pre = _normalize_whitespace(full_text[: matches[0].start])
    if pre:
        units.append(AtomicUnit(None, MarkerKind.INTRO, "", pre))

    for i, m in enumerate(matches):
        body_end = matches[i + 1].start if i + 1 < len(matches) else len(full_text)
        body = _normalize_whitespace(full_text[m.end : body_end])

        if m.kind == MarkerKind.ALINEAT:
            # The alineat unit's alineat_label is None — the marker itself
            # is the alineat header. Children inside it carry alineat_label=label.
            units.append(AtomicUnit(None, MarkerKind.ALINEAT, m.label, body))
            current_alineat = m.label
        else:
            units.append(AtomicUnit(current_alineat, m.kind, m.label, body))

    return units
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py -v`

Expected: PASS — all six tests so far green.

- [ ] **Step 3.5: Commit**

```bash
git add backend/app/services/article_tokenizer.py backend/tests/test_article_tokenizer.py
git commit -m "feat(backend): tokenizer recognizes alineat markers"
```

---

## Task 4: Tokenizer — numbered, litera, upper_litera, bullet markers

Extend `_MARKER_PATTERNS` with the four remaining marker kinds. Numbered points and literae require **trailing whitespace** in the pattern so we don't eat partial decimal numbers like `1.617` as a numbered marker. Upper-case literae use `[A-Z]\.` (single capital letter + dot). Bullet uses an en-dash (parsers often use `–` U+2013) followed by a space.

**Files:**
- Modify: `backend/app/services/article_tokenizer.py`
- Modify: `backend/tests/test_article_tokenizer.py`

- [ ] **Step 4.1: Write the failing tests**

Append to `backend/tests/test_article_tokenizer.py`:

```python
def test_numbered_marker_inside_alineat():
    units = tokenize_article("(1) Intro: 1. primul punct. 2. al doilea punct.")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", "Intro:"),
        AtomicUnit("(1)", "numbered", "1.", "primul punct."),
        AtomicUnit("(1)", "numbered", "2.", "al doilea punct."),
    ]


def test_litera_marker_inside_alineat():
    units = tokenize_article("(1) Intro: a) prima literă; b) a doua literă;")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", "Intro:"),
        AtomicUnit("(1)", "litera", "a)", "prima literă;"),
        AtomicUnit("(1)", "litera", "b)", "a doua literă;"),
    ]


def test_upper_litera_marker():
    units = tokenize_article("(1) Intro: A. primul; B. al doilea;")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", "Intro:"),
        AtomicUnit("(1)", "upper_litera", "A.", "primul;"),
        AtomicUnit("(1)", "upper_litera", "B.", "al doilea;"),
    ]


def test_bullet_marker():
    # Bullet uses U+2013 en-dash + space.
    units = tokenize_article("(1) Intro: – primul; – al doilea;")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", "Intro:"),
        AtomicUnit("(1)", "bullet", "–", "primul;"),
        AtomicUnit("(1)", "bullet", "–", "al doilea;"),
    ]
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py -v`

Expected: FAIL — `numbered`/`litera`/`upper_litera`/`bullet` patterns not registered yet.

- [ ] **Step 4.3: Add the four marker patterns**

Edit `backend/app/services/article_tokenizer.py`. Replace the `_MARKER_PATTERNS` list with:

```python
_MARKER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (MarkerKind.ALINEAT, re.compile(r"\(\s*(\d+(?:\^\d+)?)\s*\)")),
    # Numbered: digit(s) [+ ^N suffix] + dot + space. The trailing \s avoids
    # eating decimals like '1.617'. The leading lookbehind requires the digit
    # NOT to be preceded by another digit or '^' so 'art. 234^1.' (a citation)
    # does not produce a numbered marker for '1'.
    (MarkerKind.NUMBERED, re.compile(r"(?<![\d\^])(\d+(?:\^\d+)?)\.\s")),
    # Upper-case litera: single capital letter + dot + space.
    (MarkerKind.UPPER_LITERA, re.compile(r"(?<![A-Za-z])([A-Z])\.\s")),
    # Lower-case litera: single lowercase letter [+ ^N] + closing paren + space.
    (MarkerKind.LITERA, re.compile(r"(?<![A-Za-z])([a-z](?:\^\d+)?)\)\s")),
    # Bullet: en-dash + space (most common in parser output).
    (MarkerKind.BULLET, re.compile(r"(–)\s")),
]
```

Update `_format_label` to handle the new kinds:

```python
def _format_label(kind: str, raw_group: str) -> str:
    if kind == MarkerKind.ALINEAT:
        return f"({raw_group})"
    if kind == MarkerKind.NUMBERED:
        return f"{raw_group}."
    if kind == MarkerKind.UPPER_LITERA:
        return f"{raw_group}."
    if kind == MarkerKind.LITERA:
        return f"{raw_group})"
    if kind == MarkerKind.BULLET:
        return raw_group  # "–"
    return raw_group
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py -v`

Expected: PASS — ten tests green.

- [ ] **Step 4.5: Commit**

```bash
git add backend/app/services/article_tokenizer.py backend/tests/test_article_tokenizer.py
git commit -m "feat(backend): tokenizer recognizes numbered, litera, upper_litera, bullet markers"
```

---

## Task 5: Tokenizer — `^N` variants on alineat, numbered, litera

Confirm the `^N` suffix renders correctly across all marker kinds. The regexes from Task 3 and Task 4 already include `(?:\^\d+)?` for alineat, numbered, and litera. This task adds explicit tests so a future regex tweak cannot silently break the variants.

**Files:**
- Modify: `backend/tests/test_article_tokenizer.py`

- [ ] **Step 5.1: Write the failing tests**

Append:

```python
def test_alineat_caret_variant():
    units = tokenize_article("(4^1) Conținut.")
    assert units == [AtomicUnit(None, "alineat", "(4^1)", "Conținut.")]


def test_numbered_caret_variant():
    units = tokenize_article("(1) 42^2. punct nou.")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", ""),
        AtomicUnit("(1)", "numbered", "42^2.", "punct nou."),
    ]


def test_litera_caret_variant():
    units = tokenize_article("(1) a^1) variantă a literei a;")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", ""),
        AtomicUnit("(1)", "litera", "a^1)", "variantă a literei a;"),
    ]
```

- [ ] **Step 5.2: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py -v`

Expected: PASS immediately — the `^N` variants are already covered by the regexes from Task 3/4. If any test fails, the regex needs adjustment in Task 4.

- [ ] **Step 5.3: Commit**

```bash
git add backend/tests/test_article_tokenizer.py
git commit -m "test(backend): tokenizer ^N marker variants"
```

---

## Task 6: Tokenizer — false-positive filter

Reject marker matches that fall inside legal references like `art. 90 alin. (1)`, `art. 125`, `pct. 8`, `lit. a)`, `Legea nr. 19/2020`. The filter inspects the **20 characters before** the match's `start`.

**Files:**
- Modify: `backend/app/services/article_tokenizer.py`
- Modify: `backend/tests/test_article_tokenizer.py`

- [ ] **Step 6.1: Write the failing tests**

Append to `backend/tests/test_article_tokenizer.py`:

```python
def test_false_positive_alineat_in_alin_reference():
    units = tokenize_article(
        "(1) Conform art. 90 alin. (1) și (2) se aplică prevederile."
    )
    # Only ONE alineat unit — the leading (1). The (1) and (2) inside
    # 'alin. (1) și (2)' are references and must NOT spawn extra alineat units.
    assert len(units) == 1
    assert units[0].marker_kind == "alineat"
    assert units[0].label == "(1)"


def test_false_positive_numbered_in_art_reference():
    units = tokenize_article("(1) Conform art. 125. din lege.")
    # Only the (1) alineat — '125.' must NOT become a numbered marker because
    # it follows 'art. '.
    assert len(units) == 1
    assert units[0].label == "(1)"


def test_false_positive_numbered_in_nr_reference():
    units = tokenize_article("(1) Decizie HP nr. 19/2020 publicată.")
    assert len(units) == 1
    assert units[0].label == "(1)"


def test_false_positive_numbered_in_pct_reference():
    units = tokenize_article("(1) Conform pct. 8. din alineatul anterior.")
    assert len(units) == 1
    assert units[0].label == "(1)"


def test_false_positive_litera_in_lit_reference():
    units = tokenize_article("(1) Conform lit. a) din alineatul anterior.")
    # 'a)' here is a reference, not a litera.
    assert len(units) == 1
    assert units[0].label == "(1)"


def test_real_marker_after_reference_still_recognized():
    units = tokenize_article(
        "(1) Conform art. 90 alin. (1) se aplică: a) prima literă; b) a doua;"
    )
    # The (1) inside 'alin. (1)' is rejected, but the leading (1) and the
    # a) / b) literae must still be recognized.
    labels = [(u.marker_kind, u.label) for u in units]
    assert ("alineat", "(1)") in labels
    assert ("litera", "a)") in labels
    assert ("litera", "b)") in labels
    # No second alineat from the reference:
    assert sum(1 for k, _ in labels if k == "alineat") == 1
```

- [ ] **Step 6.2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py -v`

Expected: FAIL — current implementation accepts the reference matches as real markers.

- [ ] **Step 6.3: Implement the false-positive filter**

Edit `backend/app/services/article_tokenizer.py`. Add this constant and helper near the other helpers:

```python
_FP_LOOKBACK = 20  # characters of context to inspect before each candidate

# Substrings that, when present in the lookback window, mark the marker
# as a false-positive reference rather than a real structural marker.
# Each tuple is (substring, list of marker kinds it disqualifies).
_FALSE_POSITIVE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("art. ",   (MarkerKind.NUMBERED, MarkerKind.ALINEAT)),
    ("alin. ",  (MarkerKind.ALINEAT,)),
    ("alin.(",  (MarkerKind.ALINEAT,)),  # tolerate missing space
    ("pct. ",   (MarkerKind.NUMBERED,)),
    ("pct.",    (MarkerKind.NUMBERED,)),
    ("lit. ",   (MarkerKind.LITERA, MarkerKind.UPPER_LITERA)),
    ("lit.",    (MarkerKind.LITERA, MarkerKind.UPPER_LITERA)),
    ("nr. ",    (MarkerKind.NUMBERED,)),
    ("nr.",     (MarkerKind.NUMBERED,)),
    ("Legea ",  (MarkerKind.NUMBERED,)),
    ("legii ",  (MarkerKind.NUMBERED,)),
]


def _is_false_positive(full_text: str, match_start: int, kind: str) -> bool:
    """Return True if a marker candidate at `match_start` should be dropped
    because it falls inside a legal reference like 'art. 90 alin. (1)'.
    """
    window_start = max(0, match_start - _FP_LOOKBACK)
    window = full_text[window_start:match_start]
    for needle, disqualified_kinds in _FALSE_POSITIVE_RULES:
        if kind in disqualified_kinds and needle in window:
            return True
    return False
```

Update `_find_all_markers` to call the filter:

```python
def _find_all_markers(full_text: str) -> list[_Match]:
    candidates: list[_Match] = []
    for kind, pattern in _MARKER_PATTERNS:
        for m in pattern.finditer(full_text):
            if _is_false_positive(full_text, m.start(), kind):
                continue
            label = _format_label(kind, m.group(1))
            candidates.append(_Match(start=m.start(), end=m.end(), kind=kind, label=label))
    candidates.sort(key=lambda c: (c.start, _kind_priority(c.kind)))
    return candidates
```

- [ ] **Step 6.4: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py -v`

Expected: PASS — all tests green including the six new false-positive tests.

- [ ] **Step 6.5: Commit**

```bash
git add backend/app/services/article_tokenizer.py backend/tests/test_article_tokenizer.py
git commit -m "feat(backend): tokenizer false-positive filter for legal references"
```

---

## Task 7: Tokenizer — overlap suppression

When two marker candidates overlap (e.g. numbered `1.` matched at the same position as a literal `1.617` decimal that the lookahead allowed through), keep only the lowest-priority kind at that position and drop any later candidate whose `start` falls **inside** an already-accepted match's body span. This prevents nested false matches.

**Files:**
- Modify: `backend/app/services/article_tokenizer.py`
- Modify: `backend/tests/test_article_tokenizer.py`

- [ ] **Step 7.1: Write the failing test**

Append:

```python
def test_decimal_inside_body_does_not_match_numbered():
    # The decimal '2.347' must NOT be picked up as numbered '347.'.
    units = tokenize_article("(1) Conform art. 2.347 din Codul civil.")
    assert len(units) == 1
    assert units[0].label == "(1)"
```

- [ ] **Step 7.2: Run test to verify it fails (or already passes)**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py::test_decimal_inside_body_does_not_match_numbered -v`

If it passes already, skip to commit. If it fails, continue to step 7.3. The lookbehind in Task 4's regex (`(?<![\d\^])`) should prevent `347.` from matching after `2.`, so this test is mostly a guard against future regex regressions.

- [ ] **Step 7.3: If failing, add overlap suppression to `_find_all_markers`**

Edit `_find_all_markers` to drop candidates whose start falls inside the body of an earlier accepted match:

```python
def _find_all_markers(full_text: str) -> list[_Match]:
    candidates: list[_Match] = []
    for kind, pattern in _MARKER_PATTERNS:
        for m in pattern.finditer(full_text):
            if _is_false_positive(full_text, m.start(), kind):
                continue
            label = _format_label(kind, m.group(1))
            candidates.append(_Match(start=m.start(), end=m.end(), kind=kind, label=label))
    candidates.sort(key=lambda c: (c.start, _kind_priority(c.kind)))

    # Suppress candidates whose start falls inside an earlier accepted match.
    # Two matches that share the same start are deduped by _kind_priority above.
    accepted: list[_Match] = []
    last_end = -1
    for c in candidates:
        if c.start < last_end:
            continue  # nested inside a previous match's marker span
        accepted.append(c)
        last_end = c.end
    return accepted
```

- [ ] **Step 7.4: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py -v`

Expected: PASS — all tests including the new decimal-suppression test.

- [ ] **Step 7.5: Commit**

```bash
git add backend/app/services/article_tokenizer.py backend/tests/test_article_tokenizer.py
git commit -m "feat(backend): tokenizer suppresses overlapping marker candidates"
```

---

## Task 8: Tokenizer — extract real fixture data + snapshot test infrastructure

Extract `Article.full_text` snapshots from the dev DB for art 5 v517 and v529, drop them into the fixture directories, and add a parameterized snapshot test that runs `tokenize_article` against each `*.txt` and compares to the matching `*.expected.json`.

The art 5 expected.json is too large to hand-write — for it, the test will fail loudly if `art5-definitions.expected.json` is missing, and we generate it once with a small helper script (Step 8.4) and then **review** it for correctness against the source text before committing.

**Files:**
- Create: `backend/tests/fixtures/tokenizer/art5-definitions.txt`
- Create: `backend/tests/fixtures/tokenizer/art5-definitions.expected.json`
- Create: `backend/tests/fixtures/diff/art5-v517-fulltext.txt`
- Create: `backend/tests/fixtures/diff/art5-v529-fulltext.txt`
- Modify: `backend/tests/test_article_tokenizer.py`

- [ ] **Step 8.1: Extract `full_text` snapshots from the DB**

Run from the backend directory:

```bash
cd /Users/anaandrei/projects/themis-legal/backend
source .venv/bin/activate
mkdir -p tests/fixtures/tokenizer tests/fixtures/diff
python -c "
import app.models.category, app.models.user, app.models.favorite, app.models.law
from app.database import SessionLocal
from app.models.law import Article

db = SessionLocal()
for vid, out_name in [(517, 'art5-v517-fulltext.txt'), (529, 'art5-v529-fulltext.txt')]:
    a5 = db.query(Article).filter(
        Article.law_version_id == vid, Article.article_number == '5'
    ).first()
    assert a5 is not None, f'art 5 not found in version {vid}'
    with open(f'tests/fixtures/diff/{out_name}', 'w', encoding='utf-8') as f:
        f.write(a5.full_text)
    print(f'wrote tests/fixtures/diff/{out_name} ({len(a5.full_text)} chars)')

# Use the v517 snapshot as the tokenizer fixture too.
import shutil
shutil.copy(
    'tests/fixtures/diff/art5-v517-fulltext.txt',
    'tests/fixtures/tokenizer/art5-definitions.txt',
)
print('copied tokenizer/art5-definitions.txt')
"
```

Expected: three new files exist, art5-v517 and art5-v529 are ~38 k chars, art5-definitions is identical to v517.

- [ ] **Step 8.2: Write the failing snapshot test**

Append to `backend/tests/test_article_tokenizer.py`:

```python
import json
from dataclasses import asdict
from pathlib import Path

import pytest

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tokenizer"


def _all_fixture_names() -> list[str]:
    return sorted(p.stem for p in _FIXTURE_DIR.glob("*.txt"))


@pytest.mark.parametrize("name", _all_fixture_names())
def test_tokenizer_snapshot(name: str):
    txt_path = _FIXTURE_DIR / f"{name}.txt"
    json_path = _FIXTURE_DIR / f"{name}.expected.json"

    full_text = txt_path.read_text(encoding="utf-8")
    actual = [asdict(u) for u in tokenize_article(full_text)]

    if not json_path.exists():
        pytest.fail(
            f"Missing snapshot file {json_path}. Generate it once with:\n"
            f"  python -c \""
            f"from app.services.article_tokenizer import tokenize_article; "
            f"from dataclasses import asdict; import json; "
            f"print(json.dumps([asdict(u) for u in tokenize_article("
            f"open('{txt_path}').read())], ensure_ascii=False, indent=2))"
            f"\" > {json_path}\n"
            f"Then OPEN AND REVIEW THE FILE before committing."
        )

    expected = json.loads(json_path.read_text(encoding="utf-8"))
    assert actual == expected, (
        f"Tokenizer output for {name} does not match snapshot. "
        f"If the change is intentional, regenerate {json_path}."
    )
```

- [ ] **Step 8.3: Run the snapshot test — expect a missing-fixture failure**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py::test_tokenizer_snapshot -v`

Expected: FAIL with "Missing snapshot file ... art5-definitions.expected.json" (per Step 8.2's `pytest.fail` message).

- [ ] **Step 8.4: Generate the art 5 snapshot baseline**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
source .venv/bin/activate
python -c "
from app.services.article_tokenizer import tokenize_article
from dataclasses import asdict
import json
ft = open('tests/fixtures/tokenizer/art5-definitions.txt', encoding='utf-8').read()
units = tokenize_article(ft)
out = json.dumps([asdict(u) for u in units], ensure_ascii=False, indent=2)
open('tests/fixtures/tokenizer/art5-definitions.expected.json', 'w', encoding='utf-8').write(out)
print(f'wrote {len(units)} units')
"
```

- [ ] **Step 8.5: Manually review the generated snapshot**

Open `backend/tests/fixtures/tokenizer/art5-definitions.expected.json` in an editor. Spot-check that:

1. The first unit is `alineat_label=null, marker_kind="alineat", label="(1)"` with the intro text up to (but not including) `1.`.
2. There is exactly one unit with `marker_kind="alineat", label="(2)"` (the second alineat), and zero false-positive `(1)` or `(2)` units inside `alin. (1) și (2)` references.
3. There are units with `label="42^1.", "42^2."` etc. (count them in the source text and confirm they appear in the snapshot — there should be one `42^2.` in v529 specifically, but this fixture is v517 so `42^2.` may or may not appear depending on which version was extracted).
4. Numbered units run from `1.` to `75.` with no gaps caused by false-positive filtering.
5. The litera units appear after the numbered units. Each litera body is short (<500 chars). No blob.

If any of these are wrong, fix the tokenizer (loop back to Tasks 3-7), regenerate the snapshot, and re-review.

Once the snapshot looks correct, the test should pass:

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py::test_tokenizer_snapshot -v`

Expected: PASS.

- [ ] **Step 8.6: Commit**

```bash
git add backend/tests/fixtures/tokenizer/art5-definitions.txt \
        backend/tests/fixtures/tokenizer/art5-definitions.expected.json \
        backend/tests/fixtures/diff/art5-v517-fulltext.txt \
        backend/tests/fixtures/diff/art5-v529-fulltext.txt \
        backend/tests/test_article_tokenizer.py
git commit -m "test(backend): tokenizer snapshot fixture for art 5 (Romanian insolvency law)"
```

---

## Task 9: Tokenizer — additional small fixtures

Hand-write five more small fixtures with their expected.json so the snapshot test covers the basic cases without depending on the dev DB.

**Files:**
- Create: `backend/tests/fixtures/tokenizer/art7-simple.txt` + `.expected.json`
- Create: `backend/tests/fixtures/tokenizer/art-with-bullets.txt` + `.expected.json`
- Create: `backend/tests/fixtures/tokenizer/art-abrogat.txt` + `.expected.json`
- Create: `backend/tests/fixtures/tokenizer/art-no-alineate.txt` + `.expected.json`
- Create: `backend/tests/fixtures/tokenizer/art-renumbered-marker.txt` + `.expected.json`

- [ ] **Step 9.1: Write the fixtures**

Create each `.txt` and `.expected.json` pair:

`art7-simple.txt`:
```
(1) Statul român este suveran, independent, unitar și indivizibil. (2) Forma de guvernământ a statului român este republica.
```

`art7-simple.expected.json`:
```json
[
  {
    "alineat_label": null,
    "marker_kind": "alineat",
    "label": "(1)",
    "text": "Statul român este suveran, independent, unitar și indivizibil."
  },
  {
    "alineat_label": null,
    "marker_kind": "alineat",
    "label": "(2)",
    "text": "Forma de guvernământ a statului român este republica."
  }
]
```

`art-with-bullets.txt`:
```
(1) Următoarele sunt interzise: a) acțiunile care: – au caracter discriminatoriu; – produc prejudicii materiale; b) inacțiunile.
```

`art-with-bullets.expected.json`:
```json
[
  {"alineat_label": null, "marker_kind": "alineat", "label": "(1)", "text": "Următoarele sunt interzise:"},
  {"alineat_label": "(1)", "marker_kind": "litera", "label": "a)", "text": "acțiunile care:"},
  {"alineat_label": "(1)", "marker_kind": "bullet", "label": "–", "text": "au caracter discriminatoriu;"},
  {"alineat_label": "(1)", "marker_kind": "bullet", "label": "–", "text": "produc prejudicii materiale;"},
  {"alineat_label": "(1)", "marker_kind": "litera", "label": "b)", "text": "inacțiunile."}
]
```

`art-abrogat.txt`:
```
Abrogat.
```

`art-abrogat.expected.json`:
```json
[
  {"alineat_label": null, "marker_kind": "intro", "label": "", "text": "Abrogat."}
]
```

`art-no-alineate.txt`:
```
Prezenta lege intră în vigoare la data publicării în Monitorul Oficial al României.
```

`art-no-alineate.expected.json`:
```json
[
  {"alineat_label": null, "marker_kind": "intro", "label": "", "text": "Prezenta lege intră în vigoare la data publicării în Monitorul Oficial al României."}
]
```

`art-renumbered-marker.txt`:
```
(4^1) Pentru această alineat: 42^2. punct nou: a^1) prima sub-literă;
```

`art-renumbered-marker.expected.json`:
```json
[
  {"alineat_label": null, "marker_kind": "alineat", "label": "(4^1)", "text": "Pentru această alineat:"},
  {"alineat_label": "(4^1)", "marker_kind": "numbered", "label": "42^2.", "text": "punct nou:"},
  {"alineat_label": "(4^1)", "marker_kind": "litera", "label": "a^1)", "text": "prima sub-literă;"}
]
```

- [ ] **Step 9.2: Run the snapshot tests**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_article_tokenizer.py::test_tokenizer_snapshot -v`

Expected: PASS — six fixtures (art5 + the five new ones) all green.

If any fail because the tokenizer output differs from the hand-written expected, **inspect the actual output**, decide whether the expected or the implementation is wrong, and fix the wrong one. Do NOT just regenerate the expected from the actual — these fixtures are hand-written specifications of correct behavior.

- [ ] **Step 9.3: Commit**

```bash
git add backend/tests/fixtures/tokenizer/
git commit -m "test(backend): hand-written tokenizer fixtures for the simple cases"
```

---

## Task 10: Diff — `_diff_alineat_items` helper with content-based alignment

Add a new helper inside `structured_diff.py` that takes two flat `list[AtomicUnit]` (already filtered to one alineat group) and returns a list of leaf-diff dicts using `difflib.SequenceMatcher` over a `(label, normalized_text[:200])` key.

**Files:**
- Modify: `backend/app/services/structured_diff.py`
- Modify: `backend/tests/test_structured_diff.py`

- [ ] **Step 10.1: Delete the old test file body and write the failing tests**

Replace `backend/tests/test_structured_diff.py` entirely with:

```python
"""Tests for structured version diff service."""
import difflib

from app.services.article_tokenizer import AtomicUnit
from app.services.structured_diff import _diff_alineat_items, word_diff_html


# --- word_diff_html (kept from the previous version) ---


def test_word_diff_html_marks_replacement():
    a = "pensiile facultative din fonduri"
    b = "pensiile ocupaționale din fonduri"
    html = word_diff_html(a, b)
    assert "<del>facultative</del>" in html
    assert "<ins>ocupaționale</ins>" in html


def test_word_diff_html_identical_returns_plain():
    text = "același text neschimbat"
    assert word_diff_html(text, text) == text


# --- _diff_alineat_items: content-based alignment ---


def _u(label: str, text: str, alineat: str = "(1)", kind: str = "numbered") -> AtomicUnit:
    return AtomicUnit(alineat_label=alineat, marker_kind=kind, label=label, text=text)


def test_diff_alineat_identical_lists_all_unchanged():
    items = [_u("1.", "primul"), _u("2.", "al doilea")]
    leaves = _diff_alineat_items(items, items)
    assert [l["change_type"] for l in leaves] == ["unchanged", "unchanged"]


def test_diff_alineat_pure_insert_in_b():
    a = [_u("1.", "primul"), _u("3.", "al treilea")]
    b = [_u("1.", "primul"), _u("2.", "al doilea"), _u("3.", "al treilea")]
    leaves = _diff_alineat_items(a, b)
    types = [l["change_type"] for l in leaves]
    labels = [l["label"] for l in leaves]
    assert "added" in types
    added_idx = types.index("added")
    assert labels[added_idx] == "2."
    assert leaves[added_idx]["text_b"] == "al doilea"


def test_diff_alineat_pure_delete_in_b():
    a = [_u("1.", "primul"), _u("2.", "al doilea"), _u("3.", "al treilea")]
    b = [_u("1.", "primul"), _u("3.", "al treilea")]
    leaves = _diff_alineat_items(a, b)
    types = [l["change_type"] for l in leaves]
    labels = [l["label"] for l in leaves]
    assert "removed" in types
    removed_idx = types.index("removed")
    assert labels[removed_idx] == "2."


def test_diff_alineat_replace_with_high_similarity_becomes_modified():
    # Same label, slightly edited text — should be one modified leaf, not add+remove.
    a = [_u("1.", "fonduri facultative din pensii")]
    b = [_u("1.", "fonduri ocupaționale din pensii")]
    leaves = _diff_alineat_items(a, b)
    assert len(leaves) == 1
    assert leaves[0]["change_type"] == "modified"
    assert "<ins>ocupaționale</ins>" in leaves[0]["diff_html"]


def test_diff_alineat_replace_with_low_similarity_becomes_add_plus_remove():
    # Same label slot but completely different content — must NOT pair.
    a = [_u("1.", "primul punct vorbește despre A")]
    b = [_u("1.", "complet diferit subiect total")]
    leaves = _diff_alineat_items(a, b)
    types = sorted(l["change_type"] for l in leaves)
    assert types == ["added", "removed"]


def test_diff_alineat_duplicate_labels_match_by_content():
    """The original art-5 bug: many items share label 'a)'. Content-based
    matching must pair them by text, not by collapsing into one bucket."""
    a = [
        _u("a)", "orice acord master de netting"),
        _u("a)", "continuarea activităților contractate"),
        _u("a)", "sediul social al persoanei juridice"),
    ]
    b = [
        _u("a)", "orice acord master de netting"),
        _u("a)", "continuarea activităților contractate"),
        _u("a)", "sediul social al persoanei juridice"),
        _u("a)", "definiție complet nouă"),  # genuinely new
    ]
    leaves = _diff_alineat_items(a, b)
    types = [l["change_type"] for l in leaves]
    assert types.count("unchanged") == 3
    assert types.count("added") == 1
    # Critically: zero fake 'modified' between unrelated 'a)' items.
    assert types.count("modified") == 0
```

- [ ] **Step 10.2: Run the tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_structured_diff.py -v`

Expected: FAIL — `_diff_alineat_items` does not exist. `word_diff_html` tests should still pass.

- [ ] **Step 10.3: Implement `_diff_alineat_items`**

Edit `backend/app/services/structured_diff.py`. Add this helper near the bottom of the file, BEFORE the existing `_pair_renumbered`:

```python
from app.services.article_tokenizer import AtomicUnit, MarkerKind, tokenize_article


REPLACE_PAIRING_THRESHOLD = 0.5


def _normalize_for_key(text: str) -> str:
    """Lowercase + collapse whitespace for SequenceMatcher key matching."""
    return " ".join(text.lower().split())


def _item_key(item: AtomicUnit) -> tuple[str, str]:
    """Hashable key used by SequenceMatcher to align items by content."""
    return (item.label, _normalize_for_key(item.text)[:200])


def _greedy_pair_by_text_ratio(
    items_a: list[AtomicUnit],
    items_b: list[AtomicUnit],
    threshold: float,
) -> tuple[
    list[tuple[AtomicUnit, AtomicUnit]],
    list[AtomicUnit],
    list[AtomicUnit],
]:
    """For items inside a SequenceMatcher 'replace' opcode, greedily pair
    them by text-ratio similarity. Returns (pairs, leftover_a, leftover_b).
    """
    used_b: set[int] = set()
    pairs: list[tuple[AtomicUnit, AtomicUnit]] = []
    for ra in items_a:
        best_idx = -1
        best_ratio = 0.0
        for j, rb in enumerate(items_b):
            if j in used_b:
                continue
            ratio = difflib.SequenceMatcher(None, ra.text, rb.text).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = j
        if best_idx >= 0 and best_ratio >= threshold:
            used_b.add(best_idx)
            pairs.append((ra, items_b[best_idx]))
    leftover_a = [a for a in items_a if all(a is not pa for pa, _ in pairs)]
    leftover_b = [b for j, b in enumerate(items_b) if j not in used_b]
    return pairs, leftover_a, leftover_b


def _leaf(item: AtomicUnit, change_type: str, **extra: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "alineat_label": item.alineat_label,
        "marker_kind": item.marker_kind,
        "label": item.label,
        "change_type": change_type,
    }
    base.update(extra)
    return base


def _diff_alineat_items(
    items_a: list[AtomicUnit], items_b: list[AtomicUnit]
) -> list[dict[str, Any]]:
    """Content-based diff of two flat item lists belonging to one alineat
    (or one pre-alineat group). Uses difflib.SequenceMatcher over
    (label, normalized text prefix) keys for primary alignment, then
    greedy text-ratio pairing inside replace opcodes.
    """
    keys_a = [_item_key(i) for i in items_a]
    keys_b = [_item_key(i) for i in items_b]
    matcher = difflib.SequenceMatcher(a=keys_a, b=keys_b, autojunk=False)

    out: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out.append(_leaf(items_b[j1 + k], "unchanged"))
        elif tag == "delete":
            for k in range(i1, i2):
                out.append(_leaf(items_a[k], "removed", text_a=items_a[k].text))
        elif tag == "insert":
            for k in range(j1, j2):
                out.append(_leaf(items_b[k], "added", text_b=items_b[k].text))
        elif tag == "replace":
            block_a = items_a[i1:i2]
            block_b = items_b[j1:j2]
            pairs, left_a, left_b = _greedy_pair_by_text_ratio(
                block_a, block_b, REPLACE_PAIRING_THRESHOLD
            )
            for ra, rb in pairs:
                out.append(_leaf(
                    rb,
                    "modified",
                    text_a=ra.text,
                    text_b=rb.text,
                    diff_html=word_diff_html(ra.text, rb.text),
                ))
            for ra in left_a:
                out.append(_leaf(ra, "removed", text_a=ra.text))
            for rb in left_b:
                out.append(_leaf(rb, "added", text_b=rb.text))
    return out
```

- [ ] **Step 10.4: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_structured_diff.py -v`

Expected: PASS — all `_diff_alineat_items` tests green.

- [ ] **Step 10.5: Commit**

```bash
git add backend/app/services/structured_diff.py backend/tests/test_structured_diff.py
git commit -m "feat(backend): _diff_alineat_items uses SequenceMatcher + greedy pairing"
```

---

## Task 11: Diff — rewrite `diff_article` to use the tokenizer

Replace the old paragraph/subparagraph-based `diff_article` with a new implementation that tokenizes both articles, groups units by `alineat_label`, runs `_diff_alineat_items` per group, and assembles the article-level dict.

**Files:**
- Modify: `backend/app/services/structured_diff.py`
- Modify: `backend/tests/test_structured_diff.py`

- [ ] **Step 11.1: Write the failing tests**

Append to `backend/tests/test_structured_diff.py`:

```python
from dataclasses import dataclass, field
from app.services.structured_diff import diff_article


@dataclass
class FakeArt:
    article_number: str
    full_text: str
    label: str | None = None


def test_diff_article_unchanged_returns_unchanged():
    a = FakeArt("62", "(1) Conținut neschimbat.")
    b = FakeArt("62", "(1) Conținut neschimbat.")
    result = diff_article(a, b)
    assert result["change_type"] == "unchanged"
    assert result["units"] == []


def test_diff_article_modified_returns_units_grouped_by_alineat():
    a = FakeArt("62", "(1) Intro: 1. primul punct.")
    b = FakeArt("62", "(1) Intro: 1. primul punct. 2. punct nou.")
    result = diff_article(a, b)
    assert result["article_number"] == "62"
    assert result["change_type"] == "modified"
    units = result["units"]
    # Units include: alineat (1) [unchanged], 1. [unchanged], 2. [added]
    types = [u["change_type"] for u in units]
    assert "added" in types
    added = next(u for u in units if u["change_type"] == "added")
    assert added["label"] == "2."
    assert added["text_b"] == "punct nou."
    assert added["alineat_label"] == "(1)"
```

- [ ] **Step 11.2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_structured_diff.py -v`

Expected: FAIL — current `diff_article` still expects `paragraphs` attribute.

- [ ] **Step 11.3: Replace `diff_article` and delete the obsolete helpers**

Edit `backend/app/services/structured_diff.py`. **Delete** the following functions entirely (they will be replaced):

- `_leaf_for_unchanged`, `_leaf_for_added`, `_leaf_for_removed`, `_leaf_for_modified`
- `_diff_subparagraphs`
- `_diff_paragraphs_list`
- `diff_paragraph`
- the existing `diff_article`

(The `_SubLike`, `_ParaLike`, `_ArticleLike` Protocol classes can stay or go — `_ArticleLike` is still useful as the duck-typing target for `diff_article`'s parameters.)

Add the new `diff_article` (place it directly above `_pair_renumbered`):

```python
def _group_by_alineat(units: list[AtomicUnit]) -> dict[str | None, list[AtomicUnit]]:
    """Group AtomicUnits by their alineat_label, preserving order within each group.

    The alineat marker units themselves (marker_kind='alineat') are placed in
    the bucket of the alineat they introduce, NOT in the parent bucket.
    """
    groups: dict[str | None, list[AtomicUnit]] = {}
    for u in units:
        if u.marker_kind == MarkerKind.ALINEAT:
            key = u.label
        else:
            key = u.alineat_label
        groups.setdefault(key, []).append(u)
    return groups


def _ordered_alineat_keys(
    groups_a: dict[str | None, list[AtomicUnit]],
    groups_b: dict[str | None, list[AtomicUnit]],
) -> list[str | None]:
    """Return the union of alineat keys, preserving B's insertion order
    first (since B is the new version) and appending any keys only in A.
    """
    seen: list[str | None] = []
    for k in groups_b:
        if k not in seen:
            seen.append(k)
    for k in groups_a:
        if k not in seen:
            seen.append(k)
    return seen


def diff_article(art_a: _ArticleLike, art_b: _ArticleLike) -> dict[str, Any]:
    """Diff two articles by tokenizing their full_text and aligning items
    per alineat with content-based matching.
    """
    units_a = tokenize_article(art_a.full_text or "")
    units_b = tokenize_article(art_b.full_text or "")

    groups_a = _group_by_alineat(units_a)
    groups_b = _group_by_alineat(units_b)

    leaves: list[dict[str, Any]] = []
    for key in _ordered_alineat_keys(groups_a, groups_b):
        leaves.extend(
            _diff_alineat_items(groups_a.get(key, []), groups_b.get(key, []))
        )

    has_changes = any(l["change_type"] != "unchanged" for l in leaves)
    return {
        "article_number": art_b.article_number,
        "change_type": "modified" if has_changes else "unchanged",
        "title": art_b.label,
        "renumbered_from": None,
        "units": leaves if has_changes else [],
    }
```

- [ ] **Step 11.4: Run all backend tests to verify diff_article works and nothing else broke**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_structured_diff.py tests/test_article_tokenizer.py -v`

Expected: PASS — both files green.

- [ ] **Step 11.5: Commit**

```bash
git add backend/app/services/structured_diff.py backend/tests/test_structured_diff.py
git commit -m "feat(backend): rewrite diff_article on top of the tokenizer"
```

---

## Task 12: Diff — update `diff_articles` payload shape (units instead of paragraphs)

The top-level `diff_articles` function still references the old `paragraphs: []` field in its `added` / `removed` short-circuit branches. Switch them to `units: []` for shape consistency, and ensure renumbered (article-level) entries also use `units`.

**Files:**
- Modify: `backend/app/services/structured_diff.py`
- Modify: `backend/tests/test_structured_diff.py`

- [ ] **Step 12.1: Write the failing tests**

Append to `backend/tests/test_structured_diff.py`:

```python
from app.services.structured_diff import diff_articles


def test_diff_articles_added_only_uses_units_field():
    a: list[FakeArt] = []
    b = [FakeArt("1", "(1) primul articol nou.")]
    changes = diff_articles(a, b)
    assert len(changes) == 1
    assert changes[0]["change_type"] == "added"
    assert changes[0]["text_b"] == "(1) primul articol nou."
    assert "units" in changes[0]
    assert changes[0]["units"] == []
    assert "paragraphs" not in changes[0]


def test_diff_articles_removed_only_uses_units_field():
    a = [FakeArt("1", "(1) articolul vechi.")]
    b: list[FakeArt] = []
    changes = diff_articles(a, b)
    assert changes[0]["change_type"] == "removed"
    assert changes[0]["text_a"] == "(1) articolul vechi."
    assert "units" in changes[0]
    assert "paragraphs" not in changes[0]


def test_diff_articles_modified_keeps_units_from_diff_article():
    a = [FakeArt("5", "(1) Intro: 1. unu.")]
    b = [FakeArt("5", "(1) Intro: 1. unu. 2. doi.")]
    changes = diff_articles(a, b)
    assert len(changes) == 1
    assert changes[0]["change_type"] == "modified"
    assert isinstance(changes[0]["units"], list)
    assert any(u["change_type"] == "added" and u["label"] == "2." for u in changes[0]["units"])


def test_diff_articles_identical_returns_empty():
    a = [FakeArt("1", "(1) același conținut.")]
    b = [FakeArt("1", "(1) același conținut.")]
    assert diff_articles(a, b) == []
```

- [ ] **Step 12.2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_structured_diff.py -v`

Expected: FAIL — the `added` and `removed` branches still emit `"paragraphs": []`.

- [ ] **Step 12.3: Update `diff_articles`**

Edit `backend/app/services/structured_diff.py`. In the existing `diff_articles` function, change the two trailing `for ad in leftover_added` / `for r in leftover_removed` blocks to use `"units": []` instead of `"paragraphs": []`. The renumbered-pair branch should already get `units` from the new `diff_article`:

```python
    for r, ad in pairs:
        d = diff_article(r, ad)
        d["change_type"] = "modified"
        d["renumbered_from"] = r.article_number
        changes.append(d)

    for ad in leftover_added:
        if id(ad) in paired_added_ids:
            continue
        changes.append({
            "article_number": ad.article_number,
            "change_type": "added",
            "title": ad.label,
            "text_b": ad.full_text,
            "units": [],
            "renumbered_from": None,
        })

    for r in leftover_removed:
        if id(r) in paired_removed_ids:
            continue
        changes.append({
            "article_number": r.article_number,
            "change_type": "removed",
            "title": r.label,
            "text_a": r.full_text,
            "units": [],
            "renumbered_from": None,
        })

    return changes
```

- [ ] **Step 12.4: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_structured_diff.py -v`

Expected: PASS — all tests green.

- [ ] **Step 12.5: Commit**

```bash
git add backend/app/services/structured_diff.py backend/tests/test_structured_diff.py
git commit -m "feat(backend): diff_articles payload uses units instead of paragraphs"
```

---

## Task 13: Diff — tokenizer fallback path with logging

If `tokenize_article` raises or returns an empty list for an article that has non-empty `full_text` on both sides, fall back to a coarse article-level word diff and log a warning. This keeps the page rendering when one weird article would otherwise crash the response.

**Files:**
- Modify: `backend/app/services/structured_diff.py`
- Modify: `backend/tests/test_structured_diff.py`

- [ ] **Step 13.1: Write the failing tests**

Append to `backend/tests/test_structured_diff.py`:

```python
import logging


def test_diff_article_falls_back_when_tokenizer_raises(monkeypatch, caplog):
    def boom(text):
        raise ValueError("synthetic tokenizer crash")

    monkeypatch.setattr("app.services.structured_diff.tokenize_article", boom)
    a = FakeArt("99", "(1) text vechi.")
    b = FakeArt("99", "(1) text nou.")

    with caplog.at_level(logging.WARNING):
        result = diff_article(a, b)

    assert result["change_type"] == "modified"
    assert "diff_html" in result
    assert "text vechi" in result["text_a"]
    assert "text nou" in result["text_b"]
    assert result["units"] == []  # no structural units in fallback
    # Warning logged
    assert any("tokenizer" in r.message.lower() or "fallback" in r.message.lower()
               for r in caplog.records)


def test_diff_article_falls_back_when_tokenizer_returns_empty(monkeypatch):
    monkeypatch.setattr("app.services.structured_diff.tokenize_article", lambda t: [])
    a = FakeArt("99", "ceva text")
    b = FakeArt("99", "ceva text editat")
    result = diff_article(a, b)
    assert result["change_type"] == "modified"
    assert "diff_html" in result
    assert result["units"] == []
```

- [ ] **Step 13.2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_structured_diff.py -v`

Expected: FAIL — `diff_article` does not have a fallback path.

- [ ] **Step 13.3: Implement the fallback in `diff_article`**

Edit `backend/app/services/structured_diff.py`. Add the logger near the top:

```python
import logging

log = logging.getLogger(__name__)
```

Replace `diff_article` body to wrap tokenization in try/except and detect empty results:

```python
def diff_article(art_a: _ArticleLike, art_b: _ArticleLike) -> dict[str, Any]:
    text_a = art_a.full_text or ""
    text_b = art_b.full_text or ""

    try:
        units_a = tokenize_article(text_a)
        units_b = tokenize_article(text_b)
    except Exception as exc:  # noqa: BLE001 — broad on purpose, fallback path
        log.warning(
            "tokenizer fallback for article %s: %s",
            art_b.article_number, exc,
        )
        return _fallback_article_diff(art_a, art_b)

    if text_a and text_b and (not units_a or not units_b):
        log.warning(
            "tokenizer fallback for article %s: empty unit list "
            "(units_a=%d units_b=%d)",
            art_b.article_number, len(units_a), len(units_b),
        )
        return _fallback_article_diff(art_a, art_b)

    groups_a = _group_by_alineat(units_a)
    groups_b = _group_by_alineat(units_b)

    leaves: list[dict[str, Any]] = []
    for key in _ordered_alineat_keys(groups_a, groups_b):
        leaves.extend(
            _diff_alineat_items(groups_a.get(key, []), groups_b.get(key, []))
        )

    has_changes = any(l["change_type"] != "unchanged" for l in leaves)
    return {
        "article_number": art_b.article_number,
        "change_type": "modified" if has_changes else "unchanged",
        "title": art_b.label,
        "renumbered_from": None,
        "units": leaves if has_changes else [],
    }


def _fallback_article_diff(art_a: _ArticleLike, art_b: _ArticleLike) -> dict[str, Any]:
    """Coarse fallback when tokenization fails — one big word-level diff."""
    text_a = art_a.full_text or ""
    text_b = art_b.full_text or ""
    return {
        "article_number": art_b.article_number,
        "change_type": "modified",
        "title": art_b.label,
        "renumbered_from": None,
        "units": [],
        "text_a": text_a,
        "text_b": text_b,
        "diff_html": word_diff_html(text_a, text_b),
    }
```

- [ ] **Step 13.4: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_structured_diff.py -v`

Expected: PASS — all tests including the two new fallback tests.

- [ ] **Step 13.5: Commit**

```bash
git add backend/app/services/structured_diff.py backend/tests/test_structured_diff.py
git commit -m "feat(backend): tokenizer fallback path in diff_article with warning log"
```

---

## Task 14: Diff — art 5 v517 vs v529 regression test

Add the explicit regression test that proves the original bug is fixed. Loads the two `full_text` snapshots created in Task 8, runs them through `diff_article`, and asserts the structural properties the original code violated.

**Files:**
- Modify: `backend/tests/test_structured_diff.py`

- [ ] **Step 14.1: Write the test**

Append to `backend/tests/test_structured_diff.py`:

```python
from pathlib import Path

_DIFF_FIXTURES = Path(__file__).parent / "fixtures" / "diff"


def test_art5_v517_to_v529_regression():
    """The original bug: 17+ duplicate-labeled subparagraph rows in art 5 §(1)
    were collapsed under dict-based matching, producing fake 'modified' leaves
    comparing unrelated definitions. The new tokenizer + content-based matching
    must produce structurally correct output.
    """
    text_a = (_DIFF_FIXTURES / "art5-v517-fulltext.txt").read_text(encoding="utf-8")
    text_b = (_DIFF_FIXTURES / "art5-v529-fulltext.txt").read_text(encoding="utf-8")

    art_a = FakeArt("5", text_a, label="Definiții")
    art_b = FakeArt("5", text_b, label="Definiții")
    result = diff_article(art_a, art_b)

    assert result["change_type"] == "modified", \
        "art 5 differs between v517 and v529, must be modified"
    assert result["units"], "must have at least one non-unchanged unit"

    # 1. The new definition 42^2. must appear as an `added` unit in alineat (1).
    added_42_2 = [
        u for u in result["units"]
        if u["change_type"] == "added"
        and u["label"] == "42^2."
        and u["alineat_label"] == "(1)"
    ]
    assert len(added_42_2) == 1, \
        f"expected exactly one added 42^2. unit, got {len(added_42_2)}"

    # 2. The original bug: there must be ZERO 'modified' units in §(1) whose
    #    text_a and text_b are completely unrelated. We assert that for every
    #    `modified` unit in §(1), the SequenceMatcher ratio between its
    #    text_a and text_b is >= 0.5 (the same threshold used for replace
    #    pairing). The old code emitted units with ratio near zero.
    bad_modifications = []
    for u in result["units"]:
        if u["change_type"] != "modified":
            continue
        if u["alineat_label"] != "(1)":
            continue
        ratio = difflib.SequenceMatcher(None, u["text_a"], u["text_b"]).ratio()
        if ratio < 0.5:
            bad_modifications.append((u["label"], ratio))
    assert not bad_modifications, (
        f"Found {len(bad_modifications)} 'modified' units in §(1) with "
        f"text similarity < 0.5 (this is the original bug): "
        f"{bad_modifications[:5]}"
    )
```

- [ ] **Step 14.2: Run the regression test**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_structured_diff.py::test_art5_v517_to_v529_regression -v`

Expected: PASS. If it fails, it means either the tokenizer or the diff algorithm is producing wrong output for the real art 5 data — investigate which by inspecting `result["units"]` for the failing case (add a temporary `print(result["units"])` and re-run with `-s`).

- [ ] **Step 14.3: Run the entire backend test suite to confirm nothing else regressed**

Run: `cd backend && source .venv/bin/activate && pytest tests/ -v --tb=short 2>&1 | tail -50`

Expected: All tests pass except any tests for components unrelated to the diff/tokenizer (those should be unchanged from before this task).

- [ ] **Step 14.4: Commit**

```bash
git add backend/tests/test_structured_diff.py
git commit -m "test(backend): art 5 v517-vs-v529 regression test for the duplicate-label bug"
```

---

## Task 15: Frontend — update API types

Replace the old `DiffSubparagraph` and `DiffParagraph` types with a single `DiffUnit`, and update `DiffArticle` to carry `units: DiffUnit[]` instead of `paragraphs: DiffParagraph[]`. The new type also tolerates the fallback shape (top-level `text_a`, `text_b`, `diff_html` on a `DiffArticle`).

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 15.1: Replace the diff type block**

Open `frontend/src/lib/api.ts`. Replace lines 336–375 (the entire `DiffSubparagraph` / `DiffParagraph` / `DiffArticle` / `DiffResult` block) with:

```typescript
export interface DiffUnit {
  alineat_label: string | null;
  marker_kind: "alineat" | "numbered" | "litera" | "upper_litera" | "bullet" | "intro";
  label: string;
  change_type: "added" | "removed" | "modified" | "unchanged";
  text_a?: string;
  text_b?: string;
  diff_html?: string;
}

export interface DiffArticle {
  article_number: string;
  change_type: "added" | "removed" | "modified" | "unchanged";
  title?: string | null;
  renumbered_from: string | null;
  units: DiffUnit[];
  // For added/removed articles and the tokenizer-fallback path:
  text_a?: string;
  text_b?: string;
  diff_html?: string;
}

export interface DiffResult {
  law_id: number;
  version_a: { id: number; ver_id: string; date_in_force: string | null };
  version_b: { id: number; ver_id: string; date_in_force: string | null };
  summary: {
    added: number;
    removed: number;
    modified: number;
    unchanged: number;
  };
  changes: DiffArticle[];
}
```

- [ ] **Step 15.2: Find any other references to the deleted types**

Run: `cd /Users/anaandrei/projects/themis-legal/frontend && rg "DiffParagraph|DiffSubparagraph" src/`

Expected: matches in `src/app/laws/[id]/diff/components/diff-leaf.tsx` and `src/app/laws/[id]/diff/components/structured-diff-article.tsx`. These are rewritten in Tasks 16-17. No other references should appear; if they do, note them so they can be fixed.

- [ ] **Step 15.3: Type-check the frontend (will fail in the leaf component but compile errors should be limited to those files)**

Run: `cd /Users/anaandrei/projects/themis-legal/frontend && npx tsc --noEmit 2>&1 | head -40`

Expected: errors only inside `src/app/laws/[id]/diff/components/diff-leaf.tsx` and `structured-diff-article.tsx`. No errors elsewhere in the codebase.

- [ ] **Step 15.4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): DiffUnit type replaces DiffParagraph/DiffSubparagraph"
```

---

## Task 16: Frontend — rewrite `diff-leaf.tsx` as `DiffUnitRow`

Replace the old `DiffParagraphLeaf` and `DiffSubparagraphLeaf` exports with a single `DiffUnitRow` that renders one `DiffUnit` as a row, plus a `CollapsedRun` adapted to take `DiffUnit[]`.

**Files:**
- Modify: `frontend/src/app/laws/[id]/diff/components/diff-leaf.tsx`

- [ ] **Step 16.1: Replace the file body**

Replace `frontend/src/app/laws/[id]/diff/components/diff-leaf.tsx` entirely with:

```typescript
"use client";

import { useState, type ReactNode } from "react";
import type { DiffUnit } from "@/lib/api";

function renderLabel(label: string): ReactNode {
  if (!label) return null;
  // "d^1)" -> d<sup>1</sup>)
  const lit = label.match(/^([a-z])\^(\d+)(\).*)$/);
  if (lit) {
    return (
      <>
        {lit[1]}
        <sup>{lit[2]}</sup>
        {lit[3]}
      </>
    );
  }
  // "(4^1)" -> (4<sup>1</sup>)
  const para = label.match(/^\((\d+)\^(\d+)(\).*)$/);
  if (para) {
    return (
      <>
        ({para[1]}
        <sup>{para[2]}</sup>
        {para[3]}
      </>
    );
  }
  // "42^2." -> 42<sup>2</sup>.
  const num = label.match(/^(\d+)\^(\d+)(\..*)$/);
  if (num) {
    return (
      <>
        {num[1]}
        <sup>{num[2]}</sup>
        {num[3]}
      </>
    );
  }
  return label;
}

function leafBodyStyle(changeType: DiffUnit["change_type"]): string {
  if (changeType === "added") return "text-green-800 bg-green-50/50 rounded px-1";
  if (changeType === "removed")
    return "text-red-800 bg-red-50/50 rounded px-1 line-through";
  return "text-gray-700";
}

function NewBadge() {
  return (
    <span className="inline-block text-[10px] uppercase tracking-wide font-semibold px-1.5 py-0.5 rounded bg-green-100 text-green-800 border border-green-200 ml-2">
      New
    </span>
  );
}

export function DiffUnitRow({ unit }: { unit: DiffUnit }) {
  if (unit.change_type === "unchanged") return null;

  let body: ReactNode;
  if (unit.change_type === "modified" && unit.diff_html) {
    body = (
      <span
        className="diff-content text-[15px] leading-[1.75] text-gray-700"
        dangerouslySetInnerHTML={{ __html: unit.diff_html }}
      />
    );
  } else if (unit.change_type === "added") {
    body = (
      <span className={`text-[15px] leading-[1.75] ${leafBodyStyle("added")}`}>
        {unit.text_b}
      </span>
    );
  } else {
    body = (
      <span className={`text-[15px] leading-[1.75] ${leafBodyStyle("removed")}`}>
        {unit.text_a}
      </span>
    );
  }

  return (
    <div className="flex gap-2 pl-6 mt-1">
      {unit.label && (
        <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-500">
          {renderLabel(unit.label)}
          {unit.change_type === "added" && <NewBadge />}
        </span>
      )}
      {body}
    </div>
  );
}

export function CollapsedRun({
  units,
  forceShowAll,
}: {
  units: DiffUnit[];
  forceShowAll: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const open = expanded || forceShowAll;

  if (units.length === 0) return null;

  if (open) {
    return (
      <div className="space-y-1">
        {units.map((u, i) => (
          <div key={i} className="flex gap-2 pl-6 mt-1">
            {u.label && (
              <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-400">
                {renderLabel(u.label)}
              </span>
            )}
            <span className="text-[15px] leading-[1.75] text-gray-500">
              (unchanged — full text hidden in diff view)
            </span>
          </div>
        ))}
      </div>
    );
  }

  const first = units[0].label;
  const last = units[units.length - 1].label;
  const range = units.length === 1 ? first : `${first}–${last}`;

  return (
    <div className="text-xs text-gray-400 italic pl-6 py-1 border-t border-dashed border-gray-200 mt-2">
      … {range} — unchanged{" "}
      <button
        type="button"
        className="text-blue-600 hover:underline not-italic ml-1"
        onClick={() => setExpanded(true)}
      >
        show
      </button>
    </div>
  );
}
```

- [ ] **Step 16.2: Type-check**

Run: `cd /Users/anaandrei/projects/themis-legal/frontend && npx tsc --noEmit 2>&1 | head -30`

Expected: errors remain only in `structured-diff-article.tsx` (it still imports the old `DiffParagraphLeaf` and `DiffSubparagraphLeaf`).

- [ ] **Step 16.3: Commit**

```bash
git add frontend/src/app/laws/\[id\]/diff/components/diff-leaf.tsx
git commit -m "feat(frontend): DiffUnitRow + CollapsedRun consume DiffUnit"
```

---

## Task 17: Frontend — rewrite `structured-diff-article.tsx` to render unit groups

Replace the paragraph-walking body with a flat-units-grouped-by-alineat walk. Each alineat group becomes a section: optional alineat header, then a stream of `DiffUnitRow` and `CollapsedRun` (collapsing consecutive unchanged units). Also handle the `added` / `removed` / fallback shapes (article-level `text_a` / `text_b` / `diff_html` with empty `units`).

**Files:**
- Modify: `frontend/src/app/laws/[id]/diff/components/structured-diff-article.tsx`

- [ ] **Step 17.1: Replace the file body**

Replace `frontend/src/app/laws/[id]/diff/components/structured-diff-article.tsx` entirely with:

```typescript
"use client";

import { useState } from "react";
import type { DiffArticle, DiffUnit } from "@/lib/api";
import { DiffUnitRow, CollapsedRun } from "./diff-leaf";

function badgeStyle(changeType: string): string {
  switch (changeType) {
    case "modified":
      return "bg-yellow-50 text-yellow-800 border-yellow-200";
    case "added":
      return "bg-green-50 text-green-800 border-green-200";
    case "removed":
      return "bg-red-50 text-red-800 border-red-200";
    default:
      return "bg-gray-50 text-gray-600 border-gray-200";
  }
}

function badgeLabel(changeType: string): string {
  if (changeType === "modified") return "Modified";
  if (changeType === "added") return "Added";
  if (changeType === "removed") return "Removed";
  return "Unchanged";
}

/** Group units by their effective alineat key, preserving first-seen order. */
function groupByAlineat(units: DiffUnit[]): Array<{ key: string | null; units: DiffUnit[] }> {
  const order: Array<string | null> = [];
  const buckets = new Map<string | null, DiffUnit[]>();
  for (const u of units) {
    // alineat marker units sit in their OWN bucket (the alineat they introduce)
    const key = u.marker_kind === "alineat" ? u.label : u.alineat_label;
    if (!buckets.has(key)) {
      buckets.set(key, []);
      order.push(key);
    }
    buckets.get(key)!.push(u);
  }
  return order.map((k) => ({ key: k, units: buckets.get(k)! }));
}

function renderUnitsWithCollapse(units: DiffUnit[], forceShowAll: boolean) {
  const out: React.ReactNode[] = [];
  let run: DiffUnit[] = [];

  const flush = (key: string) => {
    if (run.length === 0) return;
    if (forceShowAll) {
      // Render every unchanged unit as a faint stub line.
      run.forEach((u, i) =>
        out.push(
          <div key={`${key}-${i}`} className="flex gap-2 pl-6 mt-1">
            {u.label && (
              <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-400">
                {u.label}
              </span>
            )}
            <span className="text-[15px] leading-[1.75] text-gray-500">(unchanged)</span>
          </div>,
        ),
      );
    } else {
      out.push(<CollapsedRun key={key} units={run} forceShowAll={false} />);
    }
    run = [];
  };

  units.forEach((u, i) => {
    if (u.change_type === "unchanged") {
      run.push(u);
      return;
    }
    flush(`run-${i}`);
    out.push(<DiffUnitRow key={`u-${i}`} unit={u} />);
  });
  flush("run-end");
  return out;
}

export function StructuredDiffArticle({ article }: { article: DiffArticle }) {
  const [showAll, setShowAll] = useState(false);
  const isModified = article.change_type === "modified";

  const headerLabel = article.renumbered_from
    ? `Art. ${article.article_number} (was Art. ${article.renumbered_from})`
    : `Art. ${article.article_number}`;

  // Fallback shape: a modified article with no units but a top-level diff_html.
  const isFallback = isModified && article.units.length === 0 && !!article.diff_html;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <button
        type="button"
        disabled={!isModified || isFallback}
        onClick={() => setShowAll((v) => !v)}
        className={`w-full flex items-center justify-between gap-3 px-4 py-2 text-sm font-medium border-b text-left ${badgeStyle(
          article.change_type,
        )} ${isModified && !isFallback ? "hover:brightness-95 cursor-pointer" : "cursor-default"}`}
      >
        <span>
          {headerLabel}
          {article.title && <span className="font-bold"> — {article.title}</span>}
        </span>
        <span className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wide opacity-80">
            {badgeLabel(article.change_type)}
          </span>
          {isModified && !isFallback && (
            <span className="text-xs underline">
              {showAll ? "hide unchanged" : "show full article"}
            </span>
          )}
        </span>
      </button>

      <div className="p-4">
        {isModified && !isFallback && (
          <div className="space-y-1">
            {groupByAlineat(article.units).map(({ key, units }, i) => (
              <div key={`${key ?? "intro"}-${i}`} className="mt-2">
                {key && (
                  <div className="font-mono text-xs text-gray-500 mb-1">{key}</div>
                )}
                {renderUnitsWithCollapse(units, showAll)}
              </div>
            ))}
          </div>
        )}
        {isFallback && (
          <div>
            <div
              className="diff-content text-sm text-gray-700 whitespace-pre-wrap"
              dangerouslySetInnerHTML={{ __html: article.diff_html! }}
            />
            <div className="mt-3 text-xs text-gray-400 italic">
              structural diff unavailable for this article
            </div>
          </div>
        )}
        {article.change_type === "added" && (
          <div className="text-sm text-green-800 bg-green-50/50 rounded p-2 whitespace-pre-wrap">
            {article.text_b}
          </div>
        )}
        {article.change_type === "removed" && (
          <div className="text-sm text-red-800 bg-red-50/50 rounded p-2 line-through whitespace-pre-wrap">
            {article.text_a}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 17.2: Type-check the frontend**

Run: `cd /Users/anaandrei/projects/themis-legal/frontend && npx tsc --noEmit 2>&1 | head -40`

Expected: zero errors. If `page.tsx` complains about anything, it's because of a stale type reference; check it.

- [ ] **Step 17.3: Build the frontend**

Run: `cd /Users/anaandrei/projects/themis-legal/frontend && npm run build 2>&1 | tail -30`

Expected: build succeeds.

- [ ] **Step 17.4: Commit**

```bash
git add frontend/src/app/laws/\[id\]/diff/components/structured-diff-article.tsx
git commit -m "feat(frontend): StructuredDiffArticle renders flat unit groups by alineat"
```

---

## Task 18: Manual smoke test on the live diff page

The whole point of this work is fixing `/laws/5/diff?a=517&b=529`. Verify it manually.

- [ ] **Step 18.1: Start the backend and frontend dev servers**

Open two terminals.

Terminal 1:
```bash
cd /Users/anaandrei/projects/themis-legal/backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Terminal 2:
```bash
cd /Users/anaandrei/projects/themis-legal/frontend
npm run dev
```

- [ ] **Step 18.2: Open the diff page in a browser**

Navigate to `http://localhost:3000/laws/5/diff?a=517&b=529`.

- [ ] **Step 18.3: Verify the five spec-required properties**

Confirm each of the following on the rendered page:

1. **No 28 k-char text blob.** No single row in the diff is longer than ~3 screens of text. If you see a giant wall of unhighlighted text with one tiny green span inside it, the tokenizer fallback is firing on art 5 — capture the backend warning log and investigate.
2. **Art 5 §(1) shows the new `42^2.` definition as one green `added` row** with the "New" badge. Search the page for "42^2" — there should be exactly one green row.
3. **Items render under their alineat header** (e.g. `(1)`, `(2)`) with bare marker labels (`1.`, `42^2.`, `a)`). The alineat header appears as a small monospace gray line above the units in that group.
4. **Collapsed runs show a sensible label range** like `… 1.–41. — unchanged · show`. Click "show" on one and verify it expands in place.
5. **Clicking "show full article"** in the article header expands every collapsed run in that article. Clicking "hide unchanged" collapses them back.

If any of these fail, capture the page (browser screenshot is fine), inspect the JSON returned by `/api/laws/5/diff?a=517&b=529` directly (e.g. via `curl`), and trace whether the bug is in the backend payload or the frontend rendering.

- [ ] **Step 18.4: Check the network response shape**

```bash
curl -s 'http://localhost:8000/api/laws/5/diff?version_a=517&version_b=529' | python -m json.tool | head -80
```

Expected: a JSON document with `summary`, `changes`. The `changes[?].units` field exists (not `paragraphs`). At least one unit in art 5's changes has `label="42^2."`, `change_type="added"`, `alineat_label="(1)"`.

- [ ] **Step 18.5: Run the entire backend test suite one more time**

```bash
cd /Users/anaandrei/projects/themis-legal/backend
source .venv/bin/activate
pytest tests/ --tb=short 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 18.6: Commit any final cleanup if needed**

If the smoke test surfaced any small fixes (e.g. missing CSS class, type annotation), apply them and commit:

```bash
git add -p   # review and stage
git commit -m "fix(frontend): <whatever the cleanup was>"
```

If nothing needed fixing, skip this step.

---

## Done

At this point:

- The backend tokenizer is implemented, unit-tested, snapshot-tested, and exercised by the regression test against real art 5 data.
- `structured_diff.py` produces a flat `units` list per article via content-based alignment, with a logged fallback for any article the tokenizer chokes on.
- The frontend renders the new payload as inline track-changes, grouped by alineat header, with collapsible unchanged runs.
- The art 5 v517-vs-v529 diff page renders the new `42^2.` definition as one `added` row, with no fake "modified" rows comparing unrelated definitions, and no 28 k-char text blobs anywhere.

The original brainstorming question — "is there a better way to ensure that you compare versions accurately and display the changes" — is answered: yes, by tokenizing the canonical text source at diff time, aligning items by content (not by colliding labels), and rendering the result as a flat per-alineat unit stream with the same inline track-changes display style the user picked in the brainstorming session.
