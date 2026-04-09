# Version Diff Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the tokenizer-based diff with a label-based structural matcher that consumes the paragraph-level amendment notes and `text_clean` data shipped in Spec 1, producing accurate, readable diffs that explain themselves with citations from the official record.

**Architecture:** A new pure module `structural_diff.py` walks both versions' `Article → Paragraph` trees, matches by stable `(article_label, paragraph_label)` chain, compares `text_clean` (annotation-stripped), runs `difflib` for word-level highlights inside modified paragraphs, and attaches paragraph-level `AmendmentNote` rows from version B as enrichment metadata. The existing `structured_diff.diff_articles` function name is kept as a thin shim so the router doesn't change. Frontend `DiffResult` shape becomes hierarchical (`articles → paragraphs`) and the diff page is rewritten to render it minimally — Spec 3 owns polish.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x with `selectinload` for eager loading, pytest, FastAPI, Next.js, TypeScript.

**Spec:** `docs/superpowers/specs/2026-04-09-version-diff-backend-design.md`

---

## File map

```
backend/
  app/services/
    structural_diff.py                    NEW  — pure label-based matcher + tests' main target
    diff_renumbering.py                   NEW  — pure greedy text-similarity pairing helper
    structured_diff.py                    EDIT — replace internals with a thin shim that calls structural_diff
    article_tokenizer.py                  DELETE (after verifying it has no other consumers)
  app/routers/laws.py                     EDIT — eager load paragraphs + notes; rename `changes` → `articles`
  tests/
    test_structural_diff.py               NEW  — pure unit tests for the matcher
    test_diff_renumbering.py              NEW  — pure unit tests for the greedy pairing helper
    test_diff_endpoint.py                 EDIT — rewrite assertions against the new response shape

frontend/
  src/lib/api.ts                          EDIT — replace DiffUnit/DiffArticle with new types
  src/app/laws/[id]/diff/page.tsx         EDIT — rewrite to render the new hierarchy
  src/app/laws/[id]/diff/components/
    structured-diff-article.tsx           DELETE
    diff-leaf.tsx                         DELETE
```

---

## Task 1: `diff_renumbering.py` — greedy text-similarity pairing

**Files:**
- Create: `backend/app/services/diff_renumbering.py`
- Test: `backend/tests/test_diff_renumbering.py`

The matcher uses this helper twice — once for article-level renumbering and once for paragraph-level renumbering. It's the only place text similarity matters, so it gets its own pure module.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_diff_renumbering.py`:

```python
"""Unit tests for diff_renumbering.greedy_pair_by_text_ratio."""
from app.services.diff_renumbering import greedy_pair_by_text_ratio


def test_empty_inputs_return_empty_pairs_and_leftovers():
    pairs, left_a, left_b = greedy_pair_by_text_ratio([], [], threshold=0.85)
    assert pairs == []
    assert left_a == []
    assert left_b == []


def test_single_pair_above_threshold():
    a = [("a1", "Operatorul economic plătește accize.")]
    b = [("b1", "Operatorul economic plătește accize.")]
    pairs, left_a, left_b = greedy_pair_by_text_ratio(a, b, threshold=0.85)
    assert pairs == [("a1", "b1")]
    assert left_a == []
    assert left_b == []


def test_single_pair_below_threshold_left_in_leftovers():
    a = [("a1", "Apple banana cherry.")]
    b = [("b1", "Completely different content here.")]
    pairs, left_a, left_b = greedy_pair_by_text_ratio(a, b, threshold=0.85)
    assert pairs == []
    assert left_a == ["a1"]
    assert left_b == ["b1"]


def test_picks_best_match_greedily():
    """Each A item is paired with the highest-similarity B item available."""
    a = [
        ("a1", "Operatorul economic plătește accize."),
        ("a2", "Procedura de autorizare se aplică."),
    ]
    b = [
        ("b1", "Procedura de autorizare se aplică."),
        ("b2", "Operatorul economic plătește accize."),
    ]
    pairs, left_a, left_b = greedy_pair_by_text_ratio(a, b, threshold=0.85)
    assert sorted(pairs) == [("a1", "b2"), ("a2", "b1")]
    assert left_a == []
    assert left_b == []


def test_b_item_is_consumed_only_once():
    """Once a B item is paired, it cannot be re-paired with another A item."""
    a = [
        ("a1", "Operatorul economic plătește accize."),
        ("a2", "Operatorul economic plătește accize."),  # identical to a1
    ]
    b = [("b1", "Operatorul economic plătește accize.")]
    pairs, left_a, left_b = greedy_pair_by_text_ratio(a, b, threshold=0.85)
    assert len(pairs) == 1
    assert pairs[0][1] == "b1"
    assert len(left_a) == 1  # one A item is left over
    assert left_b == []


def test_partial_match_above_threshold_pairs():
    """Slightly different text above 0.85 ratio should still pair."""
    a = [("a1", "Operatorul economic plătește accize și taxe.")]
    b = [("b1", "Operatorul economic plătește accize și taxe vamale.")]
    pairs, left_a, left_b = greedy_pair_by_text_ratio(a, b, threshold=0.85)
    assert pairs == [("a1", "b1")]


def test_none_text_treated_as_empty_string():
    """A row with None text shouldn't crash; it just doesn't match anything."""
    a = [("a1", None)]
    b = [("b1", "Some content.")]
    pairs, left_a, left_b = greedy_pair_by_text_ratio(a, b, threshold=0.85)
    assert pairs == []
    assert left_a == ["a1"]
    assert left_b == ["b1"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_diff_renumbering.py -v
```

Expected: FAIL — module `app.services.diff_renumbering` does not exist.

- [ ] **Step 3: Implement the helper**

Create `backend/app/services/diff_renumbering.py`:

```python
"""Greedy text-similarity pairing for renumbering detection.

When the structural matcher can't pair items by stable label (e.g. an article
was renumbered, or a paragraph label collides), it falls back to this helper to
pair items from the leftover pools by content similarity. Pure: no DB, no I/O.
"""

from __future__ import annotations

from difflib import SequenceMatcher


def greedy_pair_by_text_ratio(
    items_a: list[tuple[str, str | None]],
    items_b: list[tuple[str, str | None]],
    *,
    threshold: float,
) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """Pair items from A and B by greedy text-similarity matching.

    Each item is a `(key, text)` tuple. The key is opaque — it identifies the
    item to the caller (e.g. an article label or a paragraph row id).

    Returns `(pairs, leftover_a_keys, leftover_b_keys)`. Each pair is
    `(a_key, b_key)`. Items below the threshold are left in the leftover lists
    so the caller can mark them as added/removed.

    Greedy means: for each A item in input order, find the highest-similarity
    B item that hasn't been claimed yet. Once a B item is paired, it cannot be
    paired with a later A item. This is `O(N*M)` and that's fine — leftover
    pools are typically small (the well-matched items have already been
    consumed by exact-label pairing one level up).
    """
    consumed_b: set[int] = set()
    pairs: list[tuple[str, str]] = []

    for a_key, a_text in items_a:
        a_norm = a_text or ""
        best_idx: int | None = None
        best_ratio = 0.0
        for b_idx, (_, b_text) in enumerate(items_b):
            if b_idx in consumed_b:
                continue
            b_norm = b_text or ""
            if not a_norm and not b_norm:
                # Both empty — skip; nothing meaningful to compare
                continue
            ratio = SequenceMatcher(None, a_norm, b_norm).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = b_idx
        if best_idx is not None and best_ratio >= threshold:
            pairs.append((a_key, items_b[best_idx][0]))
            consumed_b.add(best_idx)

    paired_a_keys = {a for a, _ in pairs}
    paired_b_keys = {b for _, b in pairs}
    leftover_a = [a_key for a_key, _ in items_a if a_key not in paired_a_keys]
    leftover_b = [b_key for b_key, _ in items_b if b_key not in paired_b_keys]
    return pairs, leftover_a, leftover_b
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_diff_renumbering.py -v
```

Expected: all 7 PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal && git add backend/app/services/diff_renumbering.py backend/tests/test_diff_renumbering.py
git commit -m "$(cat <<'EOF'
feat(diff): add diff_renumbering greedy text-similarity pairing helper

Pure helper used by the upcoming structural diff matcher to pair leftover
articles/paragraphs by content similarity when stable-label matching fails.
Greedy: for each A item, take the highest-similarity unclaimed B item above
the threshold. Items below threshold land in the leftover lists so the
caller can mark them added/removed. Spec 2.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `structural_diff.py` — the matcher

**Files:**
- Create: `backend/app/services/structural_diff.py`
- Test: `backend/tests/test_structural_diff.py`

This is the heart of Spec 2. Single file, single public function `diff_versions(articles_a, articles_b) -> list[DiffArticleEntry]`. Many TDD cycles inside.

- [ ] **Step 1: Write the dataclasses + identical-versions test**

Create `backend/tests/test_structural_diff.py`:

```python
"""Unit tests for structural_diff — label-based matching with note enrichment."""
from dataclasses import dataclass, field
from typing import Optional

from app.services.structural_diff import (
    AmendmentNoteRef,
    DiffArticleEntry,
    DiffParagraphEntry,
    diff_versions,
)


# Lightweight stand-ins for the SQLAlchemy ORM rows. The matcher only reads
# attributes, never queries the DB, so any object with the right attributes
# works. We use frozen dataclasses to keep the tests pure and deterministic.
@dataclass
class FakeNote:
    id: int = 0
    paragraph_id: Optional[int] = None
    note_source_id: Optional[str] = None
    text: Optional[str] = None
    date: Optional[str] = None
    subject: Optional[str] = None
    law_number: Optional[str] = None
    law_date: Optional[str] = None
    monitor_number: Optional[str] = None
    monitor_date: Optional[str] = None


@dataclass
class FakeParagraph:
    id: int = 0
    label: Optional[str] = None
    text: str = ""
    text_clean: Optional[str] = None
    amendment_notes: list = field(default_factory=list)


@dataclass
class FakeArticle:
    id: int = 0
    label: Optional[str] = None
    article_number: str = ""
    full_text: str = ""
    text_clean: Optional[str] = None
    is_abrogated: bool = False
    paragraphs: list = field(default_factory=list)
    amendment_notes: list = field(default_factory=list)


def _par(label: str, text_clean: str, *, par_id: int = 0, notes=None) -> FakeParagraph:
    return FakeParagraph(
        id=par_id, label=label, text=text_clean, text_clean=text_clean,
        amendment_notes=notes or [],
    )


def _art(
    label: str,
    *,
    text_clean: str | None = None,
    paragraphs: list[FakeParagraph] | None = None,
    notes=None,
    is_abrogated: bool = False,
) -> FakeArticle:
    pars = paragraphs or []
    full = text_clean if text_clean is not None else " ".join(
        (p.text_clean or "") for p in pars
    )
    return FakeArticle(
        id=hash(label) & 0xffff, label=label, article_number=label,
        full_text=full, text_clean=full, is_abrogated=is_abrogated,
        paragraphs=pars, amendment_notes=notes or [],
    )


def test_identical_versions_produce_all_unchanged():
    a = [_art("1", paragraphs=[_par("(1)", "Content of art 1 par 1.")])]
    b = [_art("1", paragraphs=[_par("(1)", "Content of art 1 par 1.")])]
    result = diff_versions(a, b)
    assert len(result) == 1
    entry = result[0]
    assert entry.article_label == "1"
    assert entry.change_type == "unchanged"
    assert entry.renumbered_from is None
    assert entry.notes == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_structural_diff.py -v
```

Expected: FAIL — module `app.services.structural_diff` does not exist.

- [ ] **Step 3: Create the module skeleton with dataclasses + identical-versions implementation**

Create `backend/app/services/structural_diff.py`:

```python
"""Label-based structural diff between two LawVersions.

The matcher walks the Article → Paragraph trees of both versions and pairs
nodes by their stable `(article_label, paragraph_label)` chain, then compares
`text_clean` (annotation-stripped). Word-level highlights inside a modified
paragraph come from `difflib`. Paragraph-level amendment notes from version B
are attached to each paragraph entry as enrichment metadata — they are never
used to determine state.

Pure: no SQLAlchemy, no I/O. Takes objects with the right attributes (Article,
Paragraph, AmendmentNote duck-typed) and returns dataclass instances.

Public API:
    diff_versions(articles_a, articles_b) -> list[DiffArticleEntry]
    word_diff_html(text_a, text_b) -> str
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable, Protocol

from app.services.diff_renumbering import greedy_pair_by_text_ratio


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AmendmentNoteRef:
    date: str | None = None
    subject: str | None = None
    law_number: str | None = None
    law_date: str | None = None
    monitor_number: str | None = None
    monitor_date: str | None = None


@dataclass
class DiffParagraphEntry:
    paragraph_label: str | None
    change_type: str  # "added" | "removed" | "modified" | "unchanged"
    renumbered_from: str | None = None
    text_clean: str | None = None        # for added/removed/unchanged
    text_clean_a: str | None = None      # for modified
    text_clean_b: str | None = None      # for modified
    diff_html: str | None = None         # for modified
    notes: list[AmendmentNoteRef] = field(default_factory=list)


@dataclass
class DiffArticleEntry:
    article_label: str
    change_type: str  # "added" | "removed" | "modified" | "unchanged"
    renumbered_from: str | None = None
    text_clean: str | None = None                       # for added/removed
    paragraphs: list[DiffParagraphEntry] = field(default_factory=list)
    notes: list[AmendmentNoteRef] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Lightweight protocols so this module stays pure (no SQLAlchemy import)
# ---------------------------------------------------------------------------


class _NoteLike(Protocol):
    paragraph_id: int | None
    date: str | None
    subject: str | None
    law_number: str | None
    law_date: str | None
    monitor_number: str | None
    monitor_date: str | None


class _ParagraphLike(Protocol):
    id: int
    label: str | None
    text: str
    text_clean: str | None
    amendment_notes: list


class _ArticleLike(Protocol):
    id: int
    label: str | None
    article_number: str
    full_text: str
    text_clean: str | None
    is_abrogated: bool
    paragraphs: list
    amendment_notes: list


# ---------------------------------------------------------------------------
# Word-level diff (moved from structured_diff.py)
# ---------------------------------------------------------------------------


def word_diff_html(text_a: str, text_b: str) -> str:
    """Return text_b with <del>old</del><ins>new</ins> spans for word-level changes.

    HTML-escapes the source text so it's safe to render directly.
    """
    words_a = (text_a or "").split()
    words_b = (text_b or "").split()
    matcher = SequenceMatcher(None, words_a, words_b)
    out: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            out.append(html.escape(" ".join(words_b[j1:j2])))
        elif tag == "replace":
            out.append("<del>" + html.escape(" ".join(words_a[i1:i2])) + "</del>")
            out.append("<ins>" + html.escape(" ".join(words_b[j1:j2])) + "</ins>")
        elif tag == "delete":
            out.append("<del>" + html.escape(" ".join(words_a[i1:i2])) + "</del>")
        elif tag == "insert":
            out.append("<ins>" + html.escape(" ".join(words_b[j1:j2])) + "</ins>")
    return " ".join(p for p in out if p)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clean(par_or_art) -> str:
    """Return text_clean if populated, else fall back to text/full_text."""
    tc = getattr(par_or_art, "text_clean", None)
    if tc is not None:
        return tc
    # Paragraphs have .text; articles have .full_text
    return getattr(par_or_art, "text", None) or getattr(par_or_art, "full_text", "") or ""


def _note_to_ref(note: _NoteLike) -> AmendmentNoteRef:
    return AmendmentNoteRef(
        date=note.date,
        subject=note.subject,
        law_number=note.law_number,
        law_date=note.law_date,
        monitor_number=note.monitor_number,
        monitor_date=note.monitor_date,
    )


def _article_label(art: _ArticleLike) -> str:
    return art.label or art.article_number or ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def diff_versions(
    articles_a: Iterable[_ArticleLike],
    articles_b: Iterable[_ArticleLike],
) -> list[DiffArticleEntry]:
    """Compute the structural diff between two ordered article lists."""
    list_a = list(articles_a)
    list_b = list(articles_b)

    # Article matching by label
    by_label_a: dict[str, _ArticleLike] = {}
    for art in list_a:
        key = _article_label(art)
        if key:
            by_label_a.setdefault(key, art)

    matched: list[tuple[_ArticleLike, _ArticleLike, str | None]] = []
    consumed_a: set[int] = set()
    consumed_b: set[int] = set()
    for art_b in list_b:
        key = _article_label(art_b)
        art_a = by_label_a.get(key)
        if art_a is not None and id(art_a) not in consumed_a:
            matched.append((art_a, art_b, None))
            consumed_a.add(id(art_a))
            consumed_b.add(id(art_b))

    # Renumbering pairing on leftovers
    leftover_a = [a for a in list_a if id(a) not in consumed_a]
    leftover_b = [b for b in list_b if id(b) not in consumed_b]
    if leftover_a and leftover_b:
        a_keys = [(str(id(a)), _clean(a)) for a in leftover_a]
        b_keys = [(str(id(b)), _clean(b)) for b in leftover_b]
        pairs, _, _ = greedy_pair_by_text_ratio(a_keys, b_keys, threshold=0.85)
        a_by_id = {str(id(a)): a for a in leftover_a}
        b_by_id = {str(id(b)): b for b in leftover_b}
        for a_id, b_id in pairs:
            a_obj = a_by_id[a_id]
            b_obj = b_by_id[b_id]
            matched.append((a_obj, b_obj, _article_label(a_obj)))
            consumed_a.add(id(a_obj))
            consumed_b.add(id(b_obj))

    # Build entries in B's order, with leftover A entries (pure removals)
    # interleaved at the end
    entries: list[DiffArticleEntry] = []
    matched_b_to_pair: dict[int, tuple[_ArticleLike, _ArticleLike, str | None]] = {
        id(b): (a, b, rn) for a, b, rn in matched
    }
    for art_b in list_b:
        pair = matched_b_to_pair.get(id(art_b))
        if pair is not None:
            a, b, renumbered_from = pair
            entries.append(_diff_article_pair(a, b, renumbered_from))
        else:
            entries.append(_emit_added_article(art_b))
    for art_a in list_a:
        if id(art_a) not in consumed_a:
            entries.append(_emit_removed_article(art_a))

    return entries


# ---------------------------------------------------------------------------
# Article pair → entry
# ---------------------------------------------------------------------------


def _diff_article_pair(
    art_a: _ArticleLike,
    art_b: _ArticleLike,
    renumbered_from: str | None,
) -> DiffArticleEntry:
    art_notes = [_note_to_ref(n) for n in art_b.amendment_notes if getattr(n, "paragraph_id", None) is None]

    if _clean(art_a) == _clean(art_b):
        return DiffArticleEntry(
            article_label=_article_label(art_b),
            change_type="unchanged",
            renumbered_from=renumbered_from,
            notes=art_notes,
        )

    paragraphs = _diff_paragraph_lists(
        list(art_a.paragraphs or []),
        list(art_b.paragraphs or []),
        fallback_a=_clean(art_a),
        fallback_b=_clean(art_b),
    )
    return DiffArticleEntry(
        article_label=_article_label(art_b),
        change_type="modified",
        renumbered_from=renumbered_from,
        paragraphs=paragraphs,
        notes=art_notes,
    )


def _emit_added_article(art_b: _ArticleLike) -> DiffArticleEntry:
    art_notes = [_note_to_ref(n) for n in art_b.amendment_notes if getattr(n, "paragraph_id", None) is None]
    return DiffArticleEntry(
        article_label=_article_label(art_b),
        change_type="added",
        text_clean=_clean(art_b),
        notes=art_notes,
    )


def _emit_removed_article(art_a: _ArticleLike) -> DiffArticleEntry:
    return DiffArticleEntry(
        article_label=_article_label(art_a),
        change_type="removed",
        text_clean=_clean(art_a),
    )


# ---------------------------------------------------------------------------
# Paragraph matching within an article pair
# ---------------------------------------------------------------------------


def _diff_paragraph_lists(
    pars_a: list[_ParagraphLike],
    pars_b: list[_ParagraphLike],
    *,
    fallback_a: str,
    fallback_b: str,
) -> list[DiffParagraphEntry]:
    # If neither side has paragraph rows, fall back to a single synthetic
    # paragraph holding the entire article body. This is the only place where
    # word-diff runs over a whole article.
    if not pars_a and not pars_b:
        if fallback_a == fallback_b:
            return [DiffParagraphEntry(
                paragraph_label=None, change_type="unchanged", text_clean=fallback_b,
            )]
        return [DiffParagraphEntry(
            paragraph_label=None,
            change_type="modified",
            text_clean_a=fallback_a,
            text_clean_b=fallback_b,
            diff_html=word_diff_html(fallback_a, fallback_b),
        )]

    # Group A and B paragraphs by label, keeping document order within each
    # label bucket. This protects us from the "two paragraphs share label"
    # pathological case (insolvency law art. 5).
    a_by_label: dict[str, list[_ParagraphLike]] = {}
    for p in pars_a:
        a_by_label.setdefault(p.label or "", []).append(p)
    b_by_label: dict[str, list[_ParagraphLike]] = {}
    for p in pars_b:
        b_by_label.setdefault(p.label or "", []).append(p)

    pair_list: list[tuple[_ParagraphLike, _ParagraphLike]] = []
    consumed_a_ids: set[int] = set()
    consumed_b_ids: set[int] = set()

    # Pair within label buckets first (positionally — same index in each list)
    for label, b_items in b_by_label.items():
        a_items = a_by_label.get(label, [])
        for i in range(min(len(a_items), len(b_items))):
            pair_list.append((a_items[i], b_items[i]))
            consumed_a_ids.add(id(a_items[i]))
            consumed_b_ids.add(id(b_items[i]))

    # Renumbering pairing on leftovers
    leftover_a = [p for p in pars_a if id(p) not in consumed_a_ids]
    leftover_b = [p for p in pars_b if id(p) not in consumed_b_ids]
    renumbered_map: dict[int, _ParagraphLike] = {}
    if leftover_a and leftover_b:
        a_keys = [(str(id(p)), _clean(p)) for p in leftover_a]
        b_keys = [(str(id(p)), _clean(p)) for p in leftover_b]
        pairs, _, _ = greedy_pair_by_text_ratio(a_keys, b_keys, threshold=0.85)
        a_by_id = {str(id(p)): p for p in leftover_a}
        b_by_id = {str(id(p)): p for p in leftover_b}
        for a_id, b_id in pairs:
            a_obj = a_by_id[a_id]
            b_obj = b_by_id[b_id]
            pair_list.append((a_obj, b_obj))
            consumed_a_ids.add(id(a_obj))
            consumed_b_ids.add(id(b_obj))
            renumbered_map[id(b_obj)] = a_obj

    # Build entries in B order, then leftover A entries at the end
    pair_index_b: dict[int, _ParagraphLike] = {id(b): a for a, b in pair_list}
    entries: list[DiffParagraphEntry] = []
    for par_b in pars_b:
        par_a = pair_index_b.get(id(par_b))
        if par_a is not None:
            renumbered_from = (par_a.label or None) if id(par_b) in renumbered_map else None
            entries.append(_diff_paragraph_pair(par_a, par_b, renumbered_from))
        else:
            entries.append(_emit_added_paragraph(par_b))
    for par_a in pars_a:
        if id(par_a) not in consumed_a_ids:
            entries.append(_emit_removed_paragraph(par_a))
    return entries


def _diff_paragraph_pair(
    par_a: _ParagraphLike,
    par_b: _ParagraphLike,
    renumbered_from: str | None,
) -> DiffParagraphEntry:
    par_notes = [_note_to_ref(n) for n in par_b.amendment_notes]
    text_a = _clean(par_a)
    text_b = _clean(par_b)
    if text_a == text_b:
        return DiffParagraphEntry(
            paragraph_label=par_b.label,
            change_type="unchanged",
            renumbered_from=renumbered_from,
            text_clean=text_b,
            notes=par_notes,
        )
    return DiffParagraphEntry(
        paragraph_label=par_b.label,
        change_type="modified",
        renumbered_from=renumbered_from,
        text_clean_a=text_a,
        text_clean_b=text_b,
        diff_html=word_diff_html(text_a, text_b),
        notes=par_notes,
    )


def _emit_added_paragraph(par_b: _ParagraphLike) -> DiffParagraphEntry:
    return DiffParagraphEntry(
        paragraph_label=par_b.label,
        change_type="added",
        text_clean=_clean(par_b),
        notes=[_note_to_ref(n) for n in par_b.amendment_notes],
    )


def _emit_removed_paragraph(par_a: _ParagraphLike) -> DiffParagraphEntry:
    return DiffParagraphEntry(
        paragraph_label=par_a.label,
        change_type="removed",
        text_clean=_clean(par_a),
    )
```

- [ ] **Step 4: Run test to verify identical-versions case passes**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_structural_diff.py::test_identical_versions_produce_all_unchanged -v
```

Expected: PASS.

- [ ] **Step 5: Add the modified-paragraph test, run, watch it pass (it should already work)**

Append to `backend/tests/test_structural_diff.py`:

```python
def test_modified_paragraph_emits_word_level_diff_html():
    a = [_art("336", paragraphs=[_par("(1)", "Operatorul economic plătește accize.")])]
    b = [_art("336", paragraphs=[_par("(1)", "Operatorul economic plătește accize și taxe.")])]
    result = diff_versions(a, b)
    assert len(result) == 1
    art = result[0]
    assert art.change_type == "modified"
    assert len(art.paragraphs) == 1
    par = art.paragraphs[0]
    assert par.paragraph_label == "(1)"
    assert par.change_type == "modified"
    assert par.text_clean_a == "Operatorul economic plătește accize."
    assert par.text_clean_b == "Operatorul economic plătește accize și taxe."
    assert "<ins>" in par.diff_html
    assert "și taxe" in par.diff_html
```

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_structural_diff.py::test_modified_paragraph_emits_word_level_diff_html -v
```

Expected: PASS.

- [ ] **Step 6: Add added/removed paragraph tests**

Append:

```python
def test_paragraph_added_in_b():
    a = [_art("5", paragraphs=[_par("(1)", "First.")])]
    b = [_art("5", paragraphs=[_par("(1)", "First."), _par("(2)", "Second, new.")])]
    result = diff_versions(a, b)
    art = result[0]
    assert art.change_type == "modified"
    assert len(art.paragraphs) == 2
    assert art.paragraphs[0].change_type == "unchanged"
    assert art.paragraphs[1].change_type == "added"
    assert art.paragraphs[1].paragraph_label == "(2)"
    assert art.paragraphs[1].text_clean == "Second, new."


def test_paragraph_removed_in_a():
    a = [_art("5", paragraphs=[_par("(1)", "First."), _par("(2)", "Second, gone.")])]
    b = [_art("5", paragraphs=[_par("(1)", "First.")])]
    result = diff_versions(a, b)
    art = result[0]
    assert art.change_type == "modified"
    assert len(art.paragraphs) == 2
    # B order first, then leftover A entries
    assert art.paragraphs[0].change_type == "unchanged"
    assert art.paragraphs[1].change_type == "removed"
    assert art.paragraphs[1].paragraph_label == "(2)"
    assert art.paragraphs[1].text_clean == "Second, gone."
```

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_structural_diff.py -v
```

Expected: 4 PASS.

- [ ] **Step 7: Add article-level renumbering test**

Append:

```python
def test_article_renumbered_pairs_by_text_similarity():
    """Article 23 in A is renumbered to 24 in B with identical content."""
    a = [_art("23", paragraphs=[_par("(1)", "Same content here.")])]
    b = [_art("24", paragraphs=[_par("(1)", "Same content here.")])]
    result = diff_versions(a, b)
    assert len(result) == 1
    art = result[0]
    assert art.article_label == "24"
    assert art.renumbered_from == "23"
    assert art.change_type == "unchanged"
```

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_structural_diff.py::test_article_renumbered_pairs_by_text_similarity -v
```

Expected: PASS.

- [ ] **Step 8: Add paragraph-level renumbering test**

Append:

```python
def test_paragraph_renumbered_within_article():
    """Paragraph (1) in A becomes (2) in B with same text."""
    a = [_art("5", paragraphs=[_par("(1)", "Definiții comune.")])]
    b = [_art("5", paragraphs=[
        _par("(0)", "Preamble paragraph."),
        _par("(2)", "Definiții comune."),
    ])]
    result = diff_versions(a, b)
    art = result[0]
    assert art.change_type == "modified"
    # B order: (0), (2)
    pars_by_label = {p.paragraph_label: p for p in art.paragraphs}
    assert pars_by_label["(0)"].change_type == "added"
    assert pars_by_label["(2)"].change_type == "unchanged"
    assert pars_by_label["(2)"].renumbered_from == "(1)"
```

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_structural_diff.py::test_paragraph_renumbered_within_article -v
```

Expected: PASS.

- [ ] **Step 9: Add the label-collision test (insolvency art. 5 bug)**

Append:

```python
def test_two_paragraphs_share_label_no_over_pairing():
    """When two paragraphs share label '(1)' (pathological case), pair positionally
    within the label bucket — never collapse them onto a single map entry."""
    a = [_art("5", paragraphs=[
        _par("(1)", "First text.", par_id=1),
        _par("(1)", "Second text.", par_id=2),
    ])]
    b = [_art("5", paragraphs=[
        _par("(1)", "First text.", par_id=11),
        _par("(1)", "Second text MODIFIED.", par_id=12),
    ])]
    result = diff_versions(a, b)
    art = result[0]
    assert art.change_type == "modified"
    assert len(art.paragraphs) == 2
    assert art.paragraphs[0].change_type == "unchanged"
    assert art.paragraphs[0].text_clean == "First text."
    assert art.paragraphs[1].change_type == "modified"
    assert art.paragraphs[1].text_clean_a == "Second text."
    assert art.paragraphs[1].text_clean_b == "Second text MODIFIED."
```

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_structural_diff.py::test_two_paragraphs_share_label_no_over_pairing -v
```

Expected: PASS.

- [ ] **Step 10: Add inline-annotation invariance test**

Append:

```python
def test_inline_annotation_does_not_affect_state():
    """If text_clean is identical between A and B, the paragraph is unchanged
    regardless of what's in raw .text. The (la …) annotation lives only in
    .text and never in .text_clean."""
    par_a = FakeParagraph(
        id=1, label="(1)",
        text="Operatorul plătește accize.",
        text_clean="Operatorul plătește accize.",
    )
    par_b = FakeParagraph(
        id=2, label="(1)",
        text="Operatorul plătește accize. (la 31-03-2026, … a fost modificat de OUG nr. 89/2025)",
        text_clean="Operatorul plătește accize.",
    )
    a = [_art("336", paragraphs=[par_a])]
    b = [_art("336", paragraphs=[par_b])]
    result = diff_versions(a, b)
    art = result[0]
    # Article-level text_clean is identical → article unchanged, no paragraph walk
    assert art.change_type == "unchanged"
```

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_structural_diff.py::test_inline_annotation_does_not_affect_state -v
```

Expected: PASS.

- [ ] **Step 11: Add note-enrichment test**

Append:

```python
def test_amendment_note_surfaces_as_enrichment_on_modified_paragraph():
    par_a = _par("(1)", "Old text.", par_id=1)
    par_b = _par(
        "(1)", "New text.", par_id=2,
        notes=[FakeNote(
            id=10, paragraph_id=2, note_source_id="src-1",
            date="31-03-2026", subject="Alineatul (1) al articolului 336",
            law_number="89", law_date="23-12-2025",
            monitor_number="1203", monitor_date="24-12-2025",
        )],
    )
    a = [_art("336", paragraphs=[par_a])]
    b = [_art("336", paragraphs=[par_b])]
    result = diff_versions(a, b)
    art = result[0]
    par = art.paragraphs[0]
    assert par.change_type == "modified"
    assert len(par.notes) == 1
    note = par.notes[0]
    assert note.date == "31-03-2026"
    assert note.law_number == "89"
    assert note.monitor_number == "1203"
```

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_structural_diff.py::test_amendment_note_surfaces_as_enrichment_on_modified_paragraph -v
```

Expected: PASS.

- [ ] **Step 12: Add abrogated-article test**

Append:

```python
def test_abrogated_article_renders_as_modified():
    """An article that becomes 'Abrogat.' in B is a normal modified pair."""
    a = [_art("99", paragraphs=[_par("(1)", "Once a real article.")])]
    b = [_art("99", text_clean="Abrogat.", paragraphs=[], is_abrogated=True)]
    result = diff_versions(a, b)
    art = result[0]
    assert art.change_type == "modified"
    # B has no paragraphs → synthetic paragraph fallback
    assert len(art.paragraphs) == 1
    par = art.paragraphs[0]
    assert par.paragraph_label is None
    assert par.change_type == "modified"
    assert par.text_clean_a == "Once a real article."
    assert par.text_clean_b == "Abrogat."
    assert "Abrogat" in par.diff_html
```

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_structural_diff.py::test_abrogated_article_renders_as_modified -v
```

Expected: PASS.

- [ ] **Step 13: Add NULL `text_clean` fallback test**

Append:

```python
def test_null_text_clean_falls_back_to_raw_text():
    """If text_clean is None, _clean() falls back to .text/.full_text without crashing."""
    par_a = FakeParagraph(id=1, label="(1)", text="Real text.", text_clean=None)
    par_b = FakeParagraph(id=2, label="(1)", text="Real text modified.", text_clean=None)
    a = [_art("1", paragraphs=[par_a])]
    b = [_art("1", paragraphs=[par_b])]
    result = diff_versions(a, b)
    art = result[0]
    par = art.paragraphs[0]
    assert par.change_type == "modified"
    assert par.text_clean_a == "Real text."
    assert par.text_clean_b == "Real text modified."
```

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_structural_diff.py::test_null_text_clean_falls_back_to_raw_text -v
```

Expected: PASS.

- [ ] **Step 14: Add article-with-no-paragraphs test**

Append:

```python
def test_article_with_no_paragraphs_uses_synthetic_paragraph_diff():
    """When neither side has paragraph rows, the matcher emits one synthetic
    paragraph entry holding the whole article body."""
    a = [_art("7", text_clean="Old article body.", paragraphs=[])]
    b = [_art("7", text_clean="New article body.", paragraphs=[])]
    result = diff_versions(a, b)
    art = result[0]
    assert art.change_type == "modified"
    assert len(art.paragraphs) == 1
    par = art.paragraphs[0]
    assert par.paragraph_label is None
    assert par.change_type == "modified"
    assert par.text_clean_a == "Old article body."
    assert par.text_clean_b == "New article body."
    assert "<ins>" in par.diff_html
```

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_structural_diff.py::test_article_with_no_paragraphs_uses_synthetic_paragraph_diff -v
```

Expected: PASS.

- [ ] **Step 15: Add added/removed article tests**

Append:

```python
def test_article_added_in_b():
    a: list = []
    b = [_art("1", paragraphs=[_par("(1)", "Brand new article.")])]
    result = diff_versions(a, b)
    assert len(result) == 1
    art = result[0]
    assert art.change_type == "added"
    assert art.text_clean == "Brand new article."


def test_article_removed_in_a():
    a = [_art("1", paragraphs=[_par("(1)", "About to be removed.")])]
    b: list = []
    result = diff_versions(a, b)
    assert len(result) == 1
    art = result[0]
    assert art.change_type == "removed"
    assert art.text_clean == "About to be removed."


def test_article_level_note_surfaces_in_response():
    """Notes with paragraph_id IS NULL belong on the article entry."""
    art_b = _art(
        "1", paragraphs=[_par("(1)", "Body.")],
        notes=[FakeNote(
            id=10, paragraph_id=None, note_source_id="art-1",
            date="01-01-2024", subject="Articolul 1",
            law_number="5", law_date="01-01-2023",
        )],
    )
    a = [_art("1", paragraphs=[_par("(1)", "Body.")])]
    b = [art_b]
    result = diff_versions(a, b)
    art = result[0]
    # Article-level notes survive even when the article itself is unchanged
    assert art.change_type == "unchanged"
    assert len(art.notes) == 1
    assert art.notes[0].law_number == "5"
```

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_structural_diff.py -v
```

Expected: all 13 PASS.

- [ ] **Step 16: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal && git add backend/app/services/structural_diff.py backend/tests/test_structural_diff.py
git commit -m "$(cat <<'EOF'
feat(diff): add structural_diff label-based matcher with note enrichment

Pure module that walks the Article → Paragraph trees of two LawVersions,
matches by stable (article_label, paragraph_label) chain, compares
text_clean (annotation-stripped), and runs difflib for word-level
highlights inside modified paragraphs. Paragraph-level amendment notes
from version B are attached as enrichment metadata. 13 unit tests cover
identical/modified/added/removed at both levels, article and paragraph
renumbering, label collisions, abrogation, NULL text_clean fallback,
synthetic-paragraph fallback for articles with no paragraph rows, inline
annotation invariance, and note enrichment at both article and paragraph
level. Spec 2.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Replace `structured_diff.py` internals with a shim

**Files:**
- Modify: `backend/app/services/structured_diff.py` (replace contents)

The router calls `from app.services.structured_diff import diff_articles`. Keep that function name and signature, but have it delegate to `structural_diff.diff_versions` and convert the dataclass tree into the dict shape the router serializes.

- [ ] **Step 1: Read the existing file to confirm what's being replaced**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && wc -l app/services/structured_diff.py
```

Expected: ~344 lines. We're replacing the whole thing.

- [ ] **Step 2: Replace the file with a thin shim**

Overwrite `backend/app/services/structured_diff.py` with:

```python
"""Backwards-compatible shim around structural_diff.

The router (`backend/app/routers/laws.py`) imports `diff_articles` from this
module. Spec 2 replaced the matching algorithm with structural_diff.diff_versions,
but we keep this entry point so the router doesn't change.

The shim's job is to:
  1. Call structural_diff.diff_versions() with the SQLAlchemy Article rows
  2. Convert the returned dataclass tree into plain dicts for JSON serialization

It is intentionally trivial. All real work lives in structural_diff.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.services.structural_diff import (
    DiffArticleEntry,
    diff_versions,
)


def diff_articles(articles_a, articles_b) -> list[dict[str, Any]]:
    """Return the diff as a list of plain dicts (one per article).

    Each dict has the shape produced by `dataclasses.asdict(DiffArticleEntry)`,
    with `paragraphs` nested as a list of dicts and `notes` as a list of dicts.
    """
    entries: list[DiffArticleEntry] = diff_versions(articles_a, articles_b)
    return [asdict(e) for e in entries]
```

- [ ] **Step 3: Run the structural_diff tests to confirm nothing broke**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_structural_diff.py tests/test_diff_renumbering.py -v
```

Expected: 7 + 13 = 20 PASS.

- [ ] **Step 4: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal && git add backend/app/services/structured_diff.py
git commit -m "$(cat <<'EOF'
refactor(diff): replace structured_diff internals with shim around structural_diff

The 344-line tokenizer-based diff is replaced by a 30-line shim that calls
structural_diff.diff_versions() and serializes the dataclass tree to dicts
for the router. The router import path stays stable so the endpoint and
tests don't have to change in lockstep. Spec 2.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Router endpoint — eager loading + new return shape

**Files:**
- Modify: `backend/app/routers/laws.py:1981-2048` (the `diff_versions` handler)

The handler currently loads `Article` rows without eager-loading paragraphs or notes. With the new matcher, every article walk hits `art.paragraphs` and `art.amendment_notes`, which would N+1 query the DB. Add `selectinload`. Also rename `changes` → `articles` in the response, and recompute the summary from the new structure.

- [ ] **Step 1: Read the current handler one more time**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && sed -n '1981,2048p' app/routers/laws.py
```

- [ ] **Step 2: Edit the handler**

Replace the body of `diff_versions` in `backend/app/routers/laws.py`. The new handler:

```python
@router.get("/{law_id}/diff")
def diff_versions(
    law_id: int,
    version_a: int,
    version_b: int,
    db: Session = Depends(get_db),
):
    """Compare two versions of a law as a structural tree.

    version_a and version_b are LawVersion IDs. Returns a hierarchical
    article → paragraph diff. Articles whose text_clean is identical are
    emitted as 'unchanged' so the frontend can still show their summary line.
    """
    from sqlalchemy.orm import selectinload
    from app.services.structured_diff import diff_articles

    ver_a = (
        db.query(LawVersion)
        .filter(LawVersion.id == version_a, LawVersion.law_id == law_id)
        .first()
    )
    ver_b = (
        db.query(LawVersion)
        .filter(LawVersion.id == version_b, LawVersion.law_id == law_id)
        .first()
    )
    if not ver_a or not ver_b:
        raise HTTPException(status_code=404, detail="Version not found")

    def _load_articles(version_id: int) -> list[Article]:
        return (
            db.query(Article)
            .filter(Article.law_version_id == version_id)
            .options(
                selectinload(Article.paragraphs).selectinload(
                    Paragraph.amendment_notes
                ),
                selectinload(Article.amendment_notes),
            )
            .order_by(Article.order_index)
            .all()
        )

    articles_a = _load_articles(version_a)
    articles_b = _load_articles(version_b)

    article_entries = diff_articles(articles_a, articles_b)

    summary = {
        "added": sum(1 for e in article_entries if e["change_type"] == "added"),
        "removed": sum(1 for e in article_entries if e["change_type"] == "removed"),
        "modified": sum(1 for e in article_entries if e["change_type"] == "modified"),
        "unchanged": sum(1 for e in article_entries if e["change_type"] == "unchanged"),
    }

    return {
        "law_id": law_id,
        "version_a": {
            "id": ver_a.id,
            "ver_id": ver_a.ver_id,
            "date_in_force": str(ver_a.date_in_force) if ver_a.date_in_force else None,
        },
        "version_b": {
            "id": ver_b.id,
            "ver_id": ver_b.ver_id,
            "date_in_force": str(ver_b.date_in_force) if ver_b.date_in_force else None,
        },
        "summary": summary,
        "articles": article_entries,
    }
```

Important: this requires `Paragraph` to be imported in the router. Check the existing imports near the top of `laws.py` and add `Paragraph` if it's not already there:

```bash
cd /Users/anaandrei/projects/themis-legal/backend && grep -n "from app.models.law import" app/routers/laws.py | head -3
```

If `Paragraph` is not in that import, add it.

- [ ] **Step 3: Sanity check the handler imports and syntax**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run python -c "from app.routers.laws import router; print('OK')"
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal && git add backend/app/routers/laws.py
git commit -m "$(cat <<'EOF'
feat(diff): eager-load paragraphs + notes; rename diff response field to 'articles'

Wires the router to use the new structural diff matcher. Adds selectinload
for Article.paragraphs → Paragraph.amendment_notes and Article.amendment_notes
so the matcher walks attached objects without N+1 queries. Renames the
response field from `changes` to `articles` to match the new hierarchical
shape. Recomputes the summary directly from article_entries. Spec 2.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Rewrite the endpoint integration test

**Files:**
- Modify: `backend/tests/test_diff_endpoint.py` (rewrite assertions against the new shape)

- [ ] **Step 1: Read the existing test**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && cat tests/test_diff_endpoint.py | head -120
```

- [ ] **Step 2: Replace the test file with a new version against the new shape**

Overwrite `backend/tests/test_diff_endpoint.py`:

```python
"""Integration tests for GET /api/laws/{id}/diff (note-augmented structural diff)."""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import Base, get_db
from app.main import app as fastapi_app
from app.models.law import (
    AmendmentNote,
    Article,
    Law,
    LawVersion,
    Paragraph,
)
from app.models.user import User
import app.models.category  # noqa: F401 — register categories table


@pytest.fixture
def client_and_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_get_current_user():
        return User(id=1, email="test@example.com")

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_current_user] = override_get_current_user
    db = TestingSessionLocal()
    yield TestClient(fastapi_app), db
    db.close()
    fastapi_app.dependency_overrides.clear()


def _seed_modified_paragraph(db):
    """Two versions; v2 modifies paragraph (1) of article 5 and attaches a note."""
    law = Law(title="Test Law", law_number="100", law_year=2024)
    db.add(law)
    db.flush()

    v1 = LawVersion(
        law_id=law.id, ver_id="100",
        date_in_force=datetime.date(2024, 1, 1),
        state="actual", is_current=False,
    )
    v2 = LawVersion(
        law_id=law.id, ver_id="200",
        date_in_force=datetime.date(2025, 1, 1),
        state="actual", is_current=True,
    )
    db.add_all([v1, v2])
    db.flush()

    art_a = Article(
        law_version_id=v1.id, article_number="5", label="5",
        full_text="Operatorul economic plătește accize.",
        text_clean="Operatorul economic plătește accize.",
        order_index=0,
    )
    art_b = Article(
        law_version_id=v2.id, article_number="5", label="5",
        full_text="Operatorul economic plătește accize și taxe.",
        text_clean="Operatorul economic plătește accize și taxe.",
        order_index=0,
    )
    db.add_all([art_a, art_b])
    db.flush()

    par_a = Paragraph(
        article_id=art_a.id, paragraph_number="(1)", label="(1)",
        text="Operatorul economic plătește accize.",
        text_clean="Operatorul economic plătește accize.",
        order_index=0,
    )
    par_b = Paragraph(
        article_id=art_b.id, paragraph_number="(1)", label="(1)",
        text="Operatorul economic plătește accize și taxe.",
        text_clean="Operatorul economic plătește accize și taxe.",
        order_index=0,
    )
    db.add_all([par_a, par_b])
    db.flush()

    db.add(AmendmentNote(
        article_id=art_b.id, paragraph_id=par_b.id,
        note_source_id="src-1",
        date="01-01-2025",
        subject="Alineatul (1) al articolului 5",
        law_number="89", law_date="23-12-2024",
        monitor_number="1203", monitor_date="24-12-2024",
        text="(la 01-01-2025, …)",
    ))
    db.commit()
    return law, v1, v2


def test_diff_endpoint_returns_hierarchical_tree(client_and_db):
    client, db = client_and_db
    law, v1, v2 = _seed_modified_paragraph(db)

    r = client.get(f"/api/laws/{law.id}/diff?version_a={v1.id}&version_b={v2.id}")
    assert r.status_code == 200
    body = r.json()

    assert body["law_id"] == law.id
    assert body["version_a"]["id"] == v1.id
    assert body["version_b"]["id"] == v2.id
    assert "articles" in body
    assert "changes" not in body  # old field is gone

    assert body["summary"]["modified"] == 1
    assert body["summary"]["added"] == 0
    assert body["summary"]["removed"] == 0
    assert body["summary"]["unchanged"] == 0

    art_entries = body["articles"]
    assert len(art_entries) == 1
    art = art_entries[0]
    assert art["article_label"] == "5"
    assert art["change_type"] == "modified"
    assert art["renumbered_from"] is None
    assert isinstance(art["paragraphs"], list)
    assert len(art["paragraphs"]) == 1

    par = art["paragraphs"][0]
    assert par["paragraph_label"] == "(1)"
    assert par["change_type"] == "modified"
    assert par["text_clean_a"] == "Operatorul economic plătește accize."
    assert par["text_clean_b"] == "Operatorul economic plătește accize și taxe."
    assert "<ins>" in par["diff_html"]
    assert len(par["notes"]) == 1
    note = par["notes"][0]
    assert note["date"] == "01-01-2025"
    assert note["law_number"] == "89"
    assert note["monitor_number"] == "1203"


def test_diff_endpoint_404_when_versions_missing(client_and_db):
    client, _ = client_and_db
    r = client.get("/api/laws/9999/diff?version_a=1&version_b=2")
    assert r.status_code == 404
```

- [ ] **Step 3: Run the endpoint test**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_diff_endpoint.py -v
```

Expected: 2 PASS.

- [ ] **Step 4: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal && git add backend/tests/test_diff_endpoint.py
git commit -m "$(cat <<'EOF'
test(diff): rewrite endpoint test against new hierarchical response shape

Asserts against the new article → paragraph hierarchy with text_clean_a /
text_clean_b / diff_html on modified paragraphs and notes attached as
enrichment. Confirms the old `changes` field is gone and replaced by
`articles`. Spec 2.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Frontend types in `api.ts`

**Files:**
- Modify: `frontend/src/lib/api.ts` (replace DiffUnit / DiffArticle / DiffResult)

- [ ] **Step 1: Replace the diff types**

In `frontend/src/lib/api.ts`, find the existing `DiffUnit`, `DiffArticle`, and `DiffResult` interfaces (around lines 340-373). Replace them with:

```typescript
export interface AmendmentNoteRef {
  date: string | null;
  subject: string | null;
  law_number: string | null;
  law_date: string | null;
  monitor_number: string | null;
  monitor_date: string | null;
}

export type DiffChangeType = "added" | "removed" | "modified" | "unchanged";

export interface DiffParagraphEntry {
  paragraph_label: string | null;
  change_type: DiffChangeType;
  renumbered_from: string | null;
  text_clean?: string | null;       // for added/removed/unchanged
  text_clean_a?: string | null;     // for modified
  text_clean_b?: string | null;     // for modified
  diff_html?: string | null;        // for modified
  notes: AmendmentNoteRef[];
}

export interface DiffArticleEntry {
  article_label: string;
  change_type: DiffChangeType;
  renumbered_from: string | null;
  text_clean?: string | null;       // for added/removed
  paragraphs: DiffParagraphEntry[];
  notes: AmendmentNoteRef[];
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
  articles: DiffArticleEntry[];
}
```

The old `DiffUnit` and `DiffArticle` (with `units`) types are removed entirely. The TypeScript compiler will surface every consumer that needs updating in the next task.

- [ ] **Step 2: Run the type checker — expect failures in the diff page consumer**

```bash
cd /Users/anaandrei/projects/themis-legal/frontend && npx tsc --noEmit 2>&1 | grep -E "diff/page|structured-diff-article|diff-leaf" | head -20
```

Expected: errors in `diff/page.tsx`, `structured-diff-article.tsx`, `diff-leaf.tsx` because they reference the old types. That's the signal for Task 7.

- [ ] **Step 3: Commit (broken state — frontend doesn't compile yet)**

Hold off on committing this in isolation. Roll it into Task 7's commit so the working tree only has a broken state for one task.

Instead, just stage the file and proceed:

```bash
cd /Users/anaandrei/projects/themis-legal && git add frontend/src/lib/api.ts
```

---

## Task 7: Rewrite the frontend diff page

**Files:**
- Modify: `frontend/src/app/laws/[id]/diff/page.tsx`
- Delete: `frontend/src/app/laws/[id]/diff/components/structured-diff-article.tsx`
- Delete: `frontend/src/app/laws/[id]/diff/components/diff-leaf.tsx`

Minimal rendering of the new hierarchy. No collapsibles, no sticky headers, no sub-components. The whole page lives in `page.tsx`.

- [ ] **Step 1: Replace `page.tsx`**

Overwrite `frontend/src/app/laws/[id]/diff/page.tsx` with:

```tsx
"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  api,
  type DiffArticleEntry,
  type DiffParagraphEntry,
  type DiffResult,
  type AmendmentNoteRef,
} from "@/lib/api";
import "./diff.css";

export default function DiffPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = params.id as string;
  const lawId = parseInt(id, 10);
  const versionA = parseInt(searchParams.get("a") || "", 10);
  const versionB = parseInt(searchParams.get("b") || "", 10);

  const [diff, setDiff] = useState<DiffResult | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!versionA || !versionB) {
      setLoading(false);
      return;
    }
    api.laws
      .diff(lawId, versionA, versionB)
      .then(setDiff)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [lawId, versionA, versionB]);

  if (loading) {
    return <div className="text-center py-12 text-gray-400">Loading...</div>;
  }

  if (!versionA || !versionB) {
    return (
      <div className="text-center py-12">
        <h2 className="text-xl font-medium text-gray-900">
          Select two versions to compare
        </h2>
        <Link
          href={`/laws/${id}`}
          className="text-blue-600 hover:underline mt-4 inline-block"
        >
          Back to law
        </Link>
      </div>
    );
  }

  if (error || !diff) {
    return (
      <div className="text-center py-12">
        <h2 className="text-xl font-medium text-red-600">
          Failed to generate diff
        </h2>
        <Link
          href={`/laws/${id}`}
          className="text-blue-600 hover:underline mt-4 inline-block"
        >
          Back to law
        </Link>
      </div>
    );
  }

  const changedArticles = diff.articles.filter(
    (a) => a.change_type !== "unchanged"
  );

  return (
    <div>
      <div className="mb-6">
        <Link
          href={`/laws/${id}`}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          &larr; Back to law
        </Link>
      </div>

      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Version Comparison</h1>
        <div className="flex items-center gap-3 mt-2 text-sm text-gray-600">
          <span className="px-2 py-1 bg-red-50 border border-red-200 rounded">
            {diff.version_a.date_in_force || diff.version_a.ver_id}
          </span>
          <span>&rarr;</span>
          <span className="px-2 py-1 bg-green-50 border border-green-200 rounded">
            {diff.version_b.date_in_force || diff.version_b.ver_id}
          </span>
        </div>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        {[
          { label: "Modified", count: diff.summary.modified, color: "bg-yellow-50 text-yellow-700 border-yellow-200" },
          { label: "Added", count: diff.summary.added, color: "bg-green-50 text-green-700 border-green-200" },
          { label: "Removed", count: diff.summary.removed, color: "bg-red-50 text-red-700 border-red-200" },
          { label: "Unchanged", count: diff.summary.unchanged, color: "bg-gray-50 text-gray-500 border-gray-200" },
        ].map((stat) => (
          <div key={stat.label} className={`rounded-lg border p-4 text-center ${stat.color}`}>
            <div className="text-2xl font-bold">{stat.count}</div>
            <div className="text-sm">{stat.label}</div>
          </div>
        ))}
      </div>

      {changedArticles.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
          <p className="text-gray-500">
            No differences found between these versions.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-gray-900">
            Changes ({changedArticles.length} articles)
          </h2>
          {changedArticles.map((art) => (
            <ArticleCard key={art.article_label} article={art} />
          ))}
        </div>
      )}
    </div>
  );
}

function ArticleCard({ article }: { article: DiffArticleEntry }) {
  const headerColor =
    article.change_type === "modified"
      ? "bg-yellow-50 border-yellow-200"
      : article.change_type === "added"
        ? "bg-green-50 border-green-200"
        : "bg-red-50 border-red-200";

  return (
    <div className={`rounded-lg border ${headerColor}`}>
      <div className="px-4 py-3 border-b border-inherit flex items-baseline justify-between">
        <div className="font-semibold text-gray-900">
          Art. {article.article_label}
          {article.renumbered_from && (
            <span className="ml-2 text-xs text-gray-500">
              (was {article.renumbered_from})
            </span>
          )}
        </div>
        <span className="uppercase text-xs font-semibold text-gray-600">
          {article.change_type}
        </span>
      </div>

      {article.notes.length > 0 && (
        <div className="px-4 py-2 border-b border-inherit bg-white">
          {article.notes.map((n, i) => (
            <NoteLine key={i} note={n} />
          ))}
        </div>
      )}

      <div className="bg-white p-4 space-y-3">
        {article.change_type === "added" || article.change_type === "removed" ? (
          <pre className={`whitespace-pre-wrap font-sans text-sm ${
            article.change_type === "added" ? "text-green-900" : "text-red-900 line-through"
          }`}>
            {article.text_clean}
          </pre>
        ) : (
          article.paragraphs.map((p, i) => (
            <ParagraphRow key={`${p.paragraph_label}-${i}`} paragraph={p} />
          ))
        )}
      </div>
    </div>
  );
}

function ParagraphRow({ paragraph }: { paragraph: DiffParagraphEntry }) {
  const label = paragraph.paragraph_label ?? "";
  const labelEl = label ? (
    <span className="text-gray-500 font-mono text-xs mr-2">{label}</span>
  ) : null;

  if (paragraph.change_type === "unchanged") {
    return (
      <div className="text-sm text-gray-700">
        {labelEl}
        <span>{paragraph.text_clean}</span>
      </div>
    );
  }
  if (paragraph.change_type === "added") {
    return (
      <div className="text-sm bg-green-50 border-l-2 border-green-400 pl-2 py-1">
        {labelEl}
        <span className="text-green-900">{paragraph.text_clean}</span>
      </div>
    );
  }
  if (paragraph.change_type === "removed") {
    return (
      <div className="text-sm bg-red-50 border-l-2 border-red-400 pl-2 py-1">
        {labelEl}
        <span className="text-red-900 line-through">{paragraph.text_clean}</span>
      </div>
    );
  }
  // modified
  return (
    <div className="text-sm bg-yellow-50 border-l-2 border-yellow-400 pl-2 py-1">
      {labelEl}
      {paragraph.renumbered_from && (
        <span className="text-xs text-gray-500 mr-2">(was {paragraph.renumbered_from})</span>
      )}
      <span
        className="diff-html"
        dangerouslySetInnerHTML={{ __html: paragraph.diff_html ?? "" }}
      />
      {paragraph.notes.length > 0 && (
        <div className="mt-1">
          {paragraph.notes.map((n, i) => (
            <NoteLine key={i} note={n} />
          ))}
        </div>
      )}
    </div>
  );
}

function NoteLine({ note }: { note: AmendmentNoteRef }) {
  const parts: string[] = [];
  if (note.date) parts.push(note.date);
  if (note.law_number) parts.push(`Legea/OUG nr. ${note.law_number}`);
  if (note.monitor_number) parts.push(`MO ${note.monitor_number}`);
  if (note.subject) parts.push(note.subject);
  if (parts.length === 0) return null;
  return (
    <div className="text-xs text-gray-500 italic">
      modified by {parts.join(" — ")}
    </div>
  );
}
```

- [ ] **Step 2: Make sure `diff.css` has `del` / `ins` styles**

```bash
cd /Users/anaandrei/projects/themis-legal && grep -E "del|ins|diff-html" frontend/src/app/laws/\[id\]/diff/diff.css
```

If the file does not contain styling for `<del>` and `<ins>` inside `.diff-html`, append:

```css
.diff-html del { background: #fee2e2; color: #991b1b; text-decoration: line-through; padding: 0 2px; border-radius: 2px; }
.diff-html ins { background: #d1fae5; color: #065f46; text-decoration: none; padding: 0 2px; border-radius: 2px; }
```

If the file already has those, leave it alone.

- [ ] **Step 3: Delete the orphaned components**

```bash
cd /Users/anaandrei/projects/themis-legal && rm frontend/src/app/laws/\[id\]/diff/components/structured-diff-article.tsx frontend/src/app/laws/\[id\]/diff/components/diff-leaf.tsx
```

- [ ] **Step 4: Type-check the frontend**

```bash
cd /Users/anaandrei/projects/themis-legal/frontend && npx tsc --noEmit 2>&1 | tail -20
```

Expected: zero errors. (If anything fails, fix the imports or types and re-run before committing.)

- [ ] **Step 5: Commit (rolls in the api.ts change from Task 6)**

```bash
cd /Users/anaandrei/projects/themis-legal && git add frontend/src/lib/api.ts frontend/src/app/laws/\[id\]/diff/page.tsx frontend/src/app/laws/\[id\]/diff/diff.css frontend/src/app/laws/\[id\]/diff/components/
git commit -m "$(cat <<'EOF'
feat(diff): rewrite diff page against new hierarchical API; delete legacy components

Replaces DiffUnit/DiffArticle (flat AtomicUnits) with the new
DiffArticleEntry → DiffParagraphEntry hierarchy. The page renders article
cards with paragraph rows inside; modified paragraphs show their diff_html
inline; added/removed paragraphs get green/red side bars; unchanged ones
render in gray. Notes attached to a modified paragraph show as a small
italic line below the body. Intentionally minimal — Spec 3 will reintroduce
collapsibles, sticky headers, and per-article navigation. The orphaned
structured-diff-article and diff-leaf components are deleted. Spec 2.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Delete the orphaned `article_tokenizer.py`

**Files:**
- Delete: `backend/app/services/article_tokenizer.py`
- Delete: `backend/tests/test_article_tokenizer.py`

`article_tokenizer.py` is now only referenced by the deleted `structured_diff.py` internals. It has no other consumers. Same for its test file.

- [ ] **Step 1: Confirm no other consumers**

```bash
cd /Users/anaandrei/projects/themis-legal && grep -rn "article_tokenizer\|tokenize_article\|AtomicUnit" backend/app/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx" 2>&1 | grep -v __pycache__
```

Expected: zero results. If anything matches, **stop and read it** before deleting — there may be a consumer the spec missed.

- [ ] **Step 2: Delete the files**

```bash
cd /Users/anaandrei/projects/themis-legal && rm backend/app/services/article_tokenizer.py backend/tests/test_article_tokenizer.py
```

- [ ] **Step 3: Run the full backend test suite to make sure nothing depends on it**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/ --tb=short 2>&1 | tail -15
```

Expected: pre-existing failures the same as before (the 10 unrelated `test_compare_endpoint` / `test_settings_endpoints` / `test_step7_revised` failures from Spec 1's verification). No new failures.

- [ ] **Step 4: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal && git add -u backend/app/services/article_tokenizer.py backend/tests/test_article_tokenizer.py
git commit -m "$(cat <<'EOF'
chore(diff): delete article_tokenizer — orphaned by Spec 2 structural matcher

article_tokenizer.py was only used by the old tokenizer-based path inside
structured_diff.py, which is now a thin shim around structural_diff. Verified
no other consumers in backend or frontend. Spec 2.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Manual smoke test

**Files:** none — verification only.

- [ ] **Step 1: Start the dev backend**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run uvicorn app.main:app --port 8000 --reload
```

Leave it running.

- [ ] **Step 2: Start the dev frontend in a second terminal**

```bash
cd /Users/anaandrei/projects/themis-legal/frontend && npm run dev
```

Leave it running.

- [ ] **Step 3: Open the diff page on the same case the user screenshotted earlier**

In a browser, open:
```
http://localhost:3000/laws/5/diff?a=517&b=529
```

(Or pick another `a`/`b` pair from any law that has multiple versions in the local DB.)

Verify visually:
- The page loads with the summary card showing modified/added/removed/unchanged counts.
- For each modified article, the new article card shows the article label and a list of paragraph rows.
- Modified paragraphs show clean word-level highlights via `<del>` (red strikethrough) and `<ins>` (green underline).
- **No `(la <date>, …)` annotation blocks appear in the diff text** — they should be invisible because `text_clean` strips them.
- Where a paragraph has an amendment note, a small italic "modified by …" line appears beneath it.
- Unchanged paragraphs render in gray as plain text, not highlighted.
- For added or removed articles (if any), the whole article body appears in green or red.

If anything looks wrong, debug it before moving on. Don't commit a fix without re-running `tests/test_structural_diff.py` first.

- [ ] **Step 4: Stop the dev servers**

`Ctrl-C` in both terminals.

- [ ] **Step 5: Verify the full backend test suite is green for our scope**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && uv run pytest tests/test_structural_diff.py tests/test_diff_renumbering.py tests/test_diff_endpoint.py -v
```

Expected: 13 + 7 + 2 = 22 PASS.

- [ ] **Step 6: Verify the frontend type-checks cleanly**

```bash
cd /Users/anaandrei/projects/themis-legal/frontend && npx tsc --noEmit 2>&1 | wc -l
```

Expected: `0` (no errors).

- [ ] **Step 7: No commit needed for verification — Spec 2 is done**

If the smoke test surfaced issues you fixed, those go in their own commits with descriptive messages. Otherwise, Spec 2 ships as-is.

---

## Done criteria

- All 22 tests in scope pass: `test_structural_diff.py` (13), `test_diff_renumbering.py` (7), `test_diff_endpoint.py` (2).
- Frontend type-checks with zero errors.
- Manual smoke test: the diff page renders the same article that broke the old diff (Codul Insolventei art. 5 / 23) without any `(la <date>, …)` annotation soup, with clean paragraph-level word highlights, and with note metadata showing as small italic citation lines.
- `article_tokenizer.py` and its test file are deleted.
- The router endpoint `/api/laws/{id}/diff` returns the new hierarchical shape with `articles` (not `changes`).

When all of these are true, Spec 2 is shipped and we can plan Spec 3 (collapsibles, sticky headers, per-article navigation, citation chips, anchor links).
