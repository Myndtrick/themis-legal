# Structured Version Diff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unreadable full-text word-diff in `/laws/{id}/diff` with a structural diff that reuses parsed Paragraph/Subparagraph rows, hides unchanged leaves, and renders modified leaves in their alineat/litera context with inline word-level highlighting.

**Architecture:** A new pure-Python module `app/services/structured_diff.py` walks the existing `Article → Paragraph → Subparagraph` tree, matches nodes by label, runs word-level `difflib` on leaf text only, and (as a fallback) pairs stray adds/removes that look like the same content shifted by a label change. The router endpoint `GET /api/laws/{id}/diff` is rewritten to return the resulting tree. The frontend gets a new `StructuredDiffArticle` component that mirrors the layout primitives of `paragraph-renderer.tsx` and consumes the tree.

**Tech Stack:** FastAPI / SQLAlchemy / pytest on the backend; Next.js / React / TypeScript / Tailwind on the frontend.

**Source spec:** `docs/superpowers/specs/2026-04-07-structured-version-diff-design.md`

---

## File Structure

**Backend (created):**
- `backend/app/services/structured_diff.py` — pure functions: `diff_articles(arts_a, arts_b) -> list[ArticleDiff]`, plus internal helpers `diff_article`, `diff_paragraph`, `_pair_renumbered`, `word_diff_html`. No DB access.
- `backend/tests/test_structured_diff.py` — unit tests for the service.

**Backend (modified):**
- `backend/app/routers/laws.py` — `diff_versions` endpoint (lines 1478–1607) replaced with a thin wrapper that loads the rows, calls the service, and serializes. `_word_diff` (lines 1590–1607) deleted from the router (its replacement lives in the service).

**Frontend (created):**
- `frontend/src/app/laws/[id]/diff/components/structured-diff-article.tsx` — article card with header, click-to-expand-all, and the per-paragraph render loop.
- `frontend/src/app/laws/[id]/diff/components/diff-leaf.tsx` — `DiffParagraphLeaf`, `DiffSubparagraphLeaf`, `CollapsedRun` building blocks. Mirrors the JSX shape of `paragraph-renderer.tsx`.
- `frontend/src/app/laws/[id]/diff/diff.css` — `<ins>`/`<del>` styles scoped to `.diff-content`.

**Frontend (modified):**
- `frontend/src/lib/api.ts` — `DiffChange` and `DiffResult` interfaces (lines 297–316) replaced with the structured tree shape.
- `frontend/src/app/laws/[id]/diff/page.tsx` — the per-article render block (lines 144–184) replaced with `<StructuredDiffArticle />`. The summary cards and version pills are untouched.

---

## Task 1: Backend — pure word-diff helper

**Files:**
- Create: `backend/app/services/structured_diff.py`
- Test: `backend/tests/test_structured_diff.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_structured_diff.py
"""Tests for structured version diff service."""
from app.services.structured_diff import word_diff_html


def test_word_diff_html_marks_replacement():
    a = "pensiile facultative din fonduri"
    b = "pensiile ocupaționale din fonduri"
    html = word_diff_html(a, b)
    assert "<del>facultative</del>" in html
    assert "<ins>ocupaționale</ins>" in html
    assert "pensiile" in html
    assert "fonduri" in html


def test_word_diff_html_identical_returns_plain():
    text = "același text neschimbat"
    assert word_diff_html(text, text) == text


def test_word_diff_html_pure_insertion():
    html = word_diff_html("a b", "a b c d")
    assert html == "a b <ins>c d</ins>"


def test_word_diff_html_pure_deletion():
    html = word_diff_html("a b c d", "a b")
    assert html == "a b <del>c d</del>"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_structured_diff.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.structured_diff'`.

- [ ] **Step 3: Create the module with the helper**

```python
# backend/app/services/structured_diff.py
"""Structural diff between two parsed law versions.

Compares the existing Article → Paragraph → Subparagraph tree by label
and produces a tree of changes suitable for the /api/laws/{id}/diff endpoint.
All functions are pure (no DB access) so they can be unit-tested in isolation.
"""
from __future__ import annotations

import difflib


def word_diff_html(text_a: str, text_b: str) -> str:
    """Word-level diff returned as HTML with <ins>/<del> tags.

    The same algorithm the router used to use, extracted so the structured
    diff can apply it at the leaf level instead of over a whole article.
    """
    if text_a == text_b:
        return text_a

    words_a = text_a.split()
    words_b = text_b.split()
    matcher = difflib.SequenceMatcher(None, words_a, words_b)

    parts: list[str] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            parts.append(" ".join(words_a[i1:i2]))
        elif op == "delete":
            parts.append(f'<del>{" ".join(words_a[i1:i2])}</del>')
        elif op == "insert":
            parts.append(f'<ins>{" ".join(words_b[j1:j2])}</ins>')
        elif op == "replace":
            parts.append(f'<del>{" ".join(words_a[i1:i2])}</del>')
            parts.append(f'<ins>{" ".join(words_b[j1:j2])}</ins>')
    return " ".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_structured_diff.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/structured_diff.py backend/tests/test_structured_diff.py
git commit -m "feat(backend): add word_diff_html helper for structured diff"
```

---

## Task 2: Backend — diff a single paragraph by subparagraph label

Compare two `Paragraph` objects (or anything with `.label`, `.text`, `.subparagraphs`) and return a paragraph-level diff dict whose `subparagraphs` list contains one entry per matched/unmatched leaf.

**Files:**
- Modify: `backend/app/services/structured_diff.py`
- Modify: `backend/tests/test_structured_diff.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_structured_diff.py`:

```python
from dataclasses import dataclass, field
from app.services.structured_diff import diff_paragraph


@dataclass
class FakeSub:
    label: str | None
    text: str
    order_index: int = 0


@dataclass
class FakePara:
    label: str | None
    text: str
    order_index: int = 0
    subparagraphs: list[FakeSub] = field(default_factory=list)


def test_diff_paragraph_unchanged_subparagraph():
    a = FakePara(label="(1)", text="", subparagraphs=[FakeSub("a)", "lit a text")])
    b = FakePara(label="(1)", text="", subparagraphs=[FakeSub("a)", "lit a text")])
    result = diff_paragraph(a, b)
    assert result["change_type"] == "unchanged"
    assert result["subparagraphs"][0]["change_type"] == "unchanged"
    assert "text_a" not in result["subparagraphs"][0]
    assert "text_b" not in result["subparagraphs"][0]


def test_diff_paragraph_modified_subparagraph_carries_diff_html():
    a = FakePara(label="(1)", text="", subparagraphs=[FakeSub("k)", "fonduri facultative")])
    b = FakePara(label="(1)", text="", subparagraphs=[FakeSub("k)", "fonduri ocupaționale")])
    result = diff_paragraph(a, b)
    assert result["change_type"] == "modified"
    leaf = result["subparagraphs"][0]
    assert leaf["change_type"] == "modified"
    assert leaf["text_a"] == "fonduri facultative"
    assert leaf["text_b"] == "fonduri ocupaționale"
    assert "<del>facultative</del>" in leaf["diff_html"]
    assert "<ins>ocupaționale</ins>" in leaf["diff_html"]


def test_diff_paragraph_added_subparagraph():
    a = FakePara(label="(1)", text="", subparagraphs=[FakeSub("a)", "x")])
    b = FakePara(label="(1)", text="", subparagraphs=[
        FakeSub("a)", "x"),
        FakeSub("b)", "brand new"),
    ])
    result = diff_paragraph(a, b)
    assert result["change_type"] == "modified"
    labels = [s["label"] for s in result["subparagraphs"]]
    assert labels == ["a)", "b)"]
    assert result["subparagraphs"][1]["change_type"] == "added"
    assert result["subparagraphs"][1]["text_b"] == "brand new"
    assert "text_a" not in result["subparagraphs"][1]


def test_diff_paragraph_removed_subparagraph():
    a = FakePara(label="(1)", text="", subparagraphs=[FakeSub("a)", "x"), FakeSub("b)", "old")])
    b = FakePara(label="(1)", text="", subparagraphs=[FakeSub("a)", "x")])
    result = diff_paragraph(a, b)
    assert result["change_type"] == "modified"
    removed = [s for s in result["subparagraphs"] if s["change_type"] == "removed"]
    assert len(removed) == 1
    assert removed[0]["label"] == "b)"
    assert removed[0]["text_a"] == "old"


def test_diff_paragraph_intro_text_modified():
    """Paragraph itself has an intro line above its subparagraphs."""
    a = FakePara(label="(5)", text="Intro vechi:", subparagraphs=[FakeSub("a)", "x")])
    b = FakePara(label="(5)", text="Intro nou:", subparagraphs=[FakeSub("a)", "x")])
    result = diff_paragraph(a, b)
    assert result["change_type"] == "modified"
    assert result["text_a"] == "Intro vechi:"
    assert result["text_b"] == "Intro nou:"
    assert "<del>vechi:</del>" in result["diff_html"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_structured_diff.py -v`
Expected: 5 new FAILs with `ImportError: cannot import name 'diff_paragraph'`.

- [ ] **Step 3: Implement `diff_paragraph` and the leaf builder**

Append to `backend/app/services/structured_diff.py`:

```python
from typing import Any, Iterable, Protocol


class _SubLike(Protocol):
    label: str | None
    text: str
    order_index: int


class _ParaLike(Protocol):
    label: str | None
    text: str
    order_index: int
    subparagraphs: list[_SubLike]


def _leaf_for_unchanged(label: str | None) -> dict[str, Any]:
    return {"label": label, "change_type": "unchanged"}


def _leaf_for_added(node: _SubLike | _ParaLike) -> dict[str, Any]:
    return {
        "label": node.label,
        "change_type": "added",
        "text_b": node.text,
    }


def _leaf_for_removed(node: _SubLike | _ParaLike) -> dict[str, Any]:
    return {
        "label": node.label,
        "change_type": "removed",
        "text_a": node.text,
    }


def _leaf_for_modified(label: str | None, text_a: str, text_b: str) -> dict[str, Any]:
    return {
        "label": label,
        "change_type": "modified",
        "text_a": text_a,
        "text_b": text_b,
        "diff_html": word_diff_html(text_a, text_b),
    }


def _diff_subparagraphs(
    subs_a: list[_SubLike], subs_b: list[_SubLike]
) -> list[dict[str, Any]]:
    """Match by label, fall back to position for unlabeled subs."""
    map_a: dict[str, _SubLike] = {}
    map_b: dict[str, _SubLike] = {}
    unlabeled_a: list[_SubLike] = []
    unlabeled_b: list[_SubLike] = []

    for s in subs_a:
        if s.label:
            map_a[s.label] = s
        else:
            unlabeled_a.append(s)
    for s in subs_b:
        if s.label:
            map_b[s.label] = s
        else:
            unlabeled_b.append(s)

    # Preserve B's order for matched/added labels, then append A-only.
    seen: set[str] = set()
    result: list[dict[str, Any]] = []

    for s in subs_b:
        if not s.label:
            continue
        seen.add(s.label)
        if s.label in map_a:
            a = map_a[s.label]
            if a.text.strip() == s.text.strip():
                result.append(_leaf_for_unchanged(s.label))
            else:
                result.append(_leaf_for_modified(s.label, a.text, s.text))
        else:
            result.append(_leaf_for_added(s))

    for s in subs_a:
        if s.label and s.label not in seen:
            result.append(_leaf_for_removed(s))

    # Position-match unlabeled subs.
    for i in range(max(len(unlabeled_a), len(unlabeled_b))):
        a = unlabeled_a[i] if i < len(unlabeled_a) else None
        b = unlabeled_b[i] if i < len(unlabeled_b) else None
        if a and b:
            if a.text.strip() == b.text.strip():
                result.append(_leaf_for_unchanged(None))
            else:
                result.append(_leaf_for_modified(None, a.text, b.text))
        elif b:
            result.append(_leaf_for_added(b))
        elif a:
            result.append(_leaf_for_removed(a))

    return result


def diff_paragraph(para_a: _ParaLike, para_b: _ParaLike) -> dict[str, Any]:
    """Diff one paragraph and its subparagraphs.

    Returns a dict with: label, change_type, optional text_a/text_b/diff_html
    for the paragraph's own intro line, and a `subparagraphs` list of leaves.
    """
    sub_leaves = _diff_subparagraphs(
        list(para_a.subparagraphs), list(para_b.subparagraphs)
    )

    result: dict[str, Any] = {
        "label": para_b.label or para_a.label,
        "change_type": "unchanged",
        "subparagraphs": sub_leaves,
    }

    intro_a = (para_a.text or "").strip()
    intro_b = (para_b.text or "").strip()
    intro_changed = intro_a != intro_b
    if intro_changed:
        result["text_a"] = para_a.text
        result["text_b"] = para_b.text
        result["diff_html"] = word_diff_html(para_a.text or "", para_b.text or "")

    has_changed_sub = any(s["change_type"] != "unchanged" for s in sub_leaves)
    if intro_changed or has_changed_sub:
        result["change_type"] = "modified"

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_structured_diff.py -v`
Expected: 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/structured_diff.py backend/tests/test_structured_diff.py
git commit -m "feat(backend): add diff_paragraph for label-based subparagraph matching"
```

---

## Task 3: Backend — diff a single article

Compare two `Article` objects and return an article-level diff dict containing a `paragraphs` list.

**Files:**
- Modify: `backend/app/services/structured_diff.py`
- Modify: `backend/tests/test_structured_diff.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_structured_diff.py`:

```python
from app.services.structured_diff import diff_article


@dataclass
class FakeArt:
    article_number: str
    full_text: str
    label: str | None = None
    paragraphs: list[FakePara] = field(default_factory=list)


def test_diff_article_unchanged():
    a = FakeArt("62", "same", paragraphs=[FakePara("(1)", "", subparagraphs=[FakeSub("a)", "x")])])
    b = FakeArt("62", "same", paragraphs=[FakePara("(1)", "", subparagraphs=[FakeSub("a)", "x")])])
    result = diff_article(a, b)
    assert result["change_type"] == "unchanged"


def test_diff_article_modified_in_one_litera():
    a = FakeArt("62", "x", paragraphs=[FakePara("(1)", "", subparagraphs=[
        FakeSub("a)", "alpha"),
        FakeSub("k)", "fonduri facultative"),
    ])])
    b = FakeArt("62", "x", paragraphs=[FakePara("(1)", "", subparagraphs=[
        FakeSub("a)", "alpha"),
        FakeSub("k)", "fonduri ocupaționale"),
    ])])
    result = diff_article(a, b)
    assert result["article_number"] == "62"
    assert result["change_type"] == "modified"
    assert len(result["paragraphs"]) == 1
    para = result["paragraphs"][0]
    assert para["label"] == "(1)"
    assert para["change_type"] == "modified"
    leaves = para["subparagraphs"]
    assert leaves[0]["change_type"] == "unchanged"
    assert leaves[1]["change_type"] == "modified"
    assert "<ins>ocupaționale</ins>" in leaves[1]["diff_html"]


def test_diff_article_added_paragraph():
    a = FakeArt("76", "x", paragraphs=[FakePara("(1)", "intro")])
    b = FakeArt("76", "x", paragraphs=[
        FakePara("(1)", "intro"),
        FakePara("(4^1)", "noul alineat"),
    ])
    result = diff_article(a, b)
    assert result["change_type"] == "modified"
    labels = [p["label"] for p in result["paragraphs"]]
    assert labels == ["(1)", "(4^1)"]
    assert result["paragraphs"][1]["change_type"] == "added"
    assert result["paragraphs"][1]["text_b"] == "noul alineat"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_structured_diff.py -v`
Expected: 3 new FAILs.

- [ ] **Step 3: Implement `diff_article`**

Append to `backend/app/services/structured_diff.py`:

```python
class _ArticleLike(Protocol):
    article_number: str
    full_text: str
    label: str | None
    paragraphs: list[_ParaLike]


def _diff_paragraphs_list(
    paras_a: list[_ParaLike], paras_b: list[_ParaLike]
) -> list[dict[str, Any]]:
    """Match paragraphs by label, fall back to position for unlabeled."""
    seen: set[str] = set()
    map_a: dict[str, _ParaLike] = {p.label: p for p in paras_a if p.label}
    result: list[dict[str, Any]] = []

    unlabeled_a = [p for p in paras_a if not p.label]
    unlabeled_b = [p for p in paras_b if not p.label]

    for p in paras_b:
        if not p.label:
            continue
        seen.add(p.label)
        if p.label in map_a:
            result.append(diff_paragraph(map_a[p.label], p))
        else:
            # Whole paragraph added: emit as a one-off leaf with no children diff.
            result.append({
                "label": p.label,
                "change_type": "added",
                "text_b": p.text,
                "subparagraphs": [
                    _leaf_for_added(s) for s in p.subparagraphs
                ],
            })

    for p in paras_a:
        if p.label and p.label not in seen:
            result.append({
                "label": p.label,
                "change_type": "removed",
                "text_a": p.text,
                "subparagraphs": [
                    _leaf_for_removed(s) for s in p.subparagraphs
                ],
            })

    # Position-match unlabeled paragraphs.
    for i in range(max(len(unlabeled_a), len(unlabeled_b))):
        a = unlabeled_a[i] if i < len(unlabeled_a) else None
        b = unlabeled_b[i] if i < len(unlabeled_b) else None
        if a and b:
            result.append(diff_paragraph(a, b))
        elif b:
            result.append({
                "label": None,
                "change_type": "added",
                "text_b": b.text,
                "subparagraphs": [_leaf_for_added(s) for s in b.subparagraphs],
            })
        elif a:
            result.append({
                "label": None,
                "change_type": "removed",
                "text_a": a.text,
                "subparagraphs": [_leaf_for_removed(s) for s in a.subparagraphs],
            })

    return result


def diff_article(art_a: _ArticleLike, art_b: _ArticleLike) -> dict[str, Any]:
    """Diff two articles by structural recursion."""
    if (art_a.full_text or "").strip() == (art_b.full_text or "").strip():
        return {
            "article_number": art_b.article_number,
            "change_type": "unchanged",
            "title": art_b.label,
            "paragraphs": [],
            "renumbered_from": None,
        }

    paragraph_diffs = _diff_paragraphs_list(
        list(art_a.paragraphs), list(art_b.paragraphs)
    )

    return {
        "article_number": art_b.article_number,
        "change_type": "modified",
        "title": art_b.label,
        "paragraphs": paragraph_diffs,
        "renumbered_from": None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_structured_diff.py -v`
Expected: 12 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/structured_diff.py backend/tests/test_structured_diff.py
git commit -m "feat(backend): add diff_article with paragraph label matching"
```

---

## Task 4: Backend — top-level `diff_articles` with renumbering pairing

Compare two lists of articles and return the full `changes` array. Handles whole-article add/remove/modify and runs the similarity-pairing fallback to recognize renumbered articles.

**Files:**
- Modify: `backend/app/services/structured_diff.py`
- Modify: `backend/tests/test_structured_diff.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_structured_diff.py`:

```python
from app.services.structured_diff import diff_articles


def _art(num: str, text: str = "", paras: list[FakePara] | None = None) -> FakeArt:
    return FakeArt(article_number=num, full_text=text, paragraphs=paras or [])


def test_diff_articles_pure_add_and_remove():
    a = [_art("1", "a"), _art("2", "b")]
    b = [_art("1", "a"), _art("3", "c")]  # 2 removed, 3 added — texts unrelated
    changes = diff_articles(a, b)
    types = {c["article_number"]: c["change_type"] for c in changes}
    assert types == {"1": "unchanged", "2": "removed", "3": "added"}


def test_diff_articles_renumbering_pair_threshold():
    """Article 73 was renumbered to 74; same body. Should pair as one modified."""
    body = "lorem ipsum dolor sit amet consectetur adipiscing elit"
    a = [_art("73", body)]
    b = [_art("74", body)]
    changes = diff_articles(a, b)
    assert len(changes) == 1
    c = changes[0]
    assert c["change_type"] == "modified"
    assert c["article_number"] == "74"
    assert c["renumbered_from"] == "73"


def test_diff_articles_unrelated_texts_do_not_pair():
    a = [_art("5", "complete unrelated text about taxes")]
    b = [_art("6", "totally different content about pensions and stuff")]
    changes = diff_articles(a, b)
    types = sorted(c["change_type"] for c in changes)
    assert types == ["added", "removed"]


def test_diff_articles_unchanged_articles_excluded():
    a = [_art("1", "same"), _art("2", "different")]
    b = [_art("1", "same"), _art("2", "different changed")]
    changes = diff_articles(a, b)
    nums = [c["article_number"] for c in changes]
    assert "1" not in nums  # unchanged article excluded
    assert "2" in nums
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_structured_diff.py -v`
Expected: 4 new FAILs.

- [ ] **Step 3: Implement `diff_articles` with the pairing fallback**

Append to `backend/app/services/structured_diff.py`:

```python
RENUMBER_SIMILARITY_THRESHOLD = 0.85


def _pair_renumbered(
    removed: list[_ArticleLike], added: list[_ArticleLike]
) -> list[tuple[_ArticleLike, _ArticleLike]]:
    """Greedy pair removed/added articles whose texts are >=85% similar."""
    pairs: list[tuple[_ArticleLike, _ArticleLike]] = []
    used_added: set[int] = set()

    for r in removed:
        best_idx = -1
        best_ratio = 0.0
        for i, ad in enumerate(added):
            if i in used_added:
                continue
            ratio = difflib.SequenceMatcher(None, r.full_text, ad.full_text).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = i
        if best_idx >= 0 and best_ratio >= RENUMBER_SIMILARITY_THRESHOLD:
            used_added.add(best_idx)
            pairs.append((r, added[best_idx]))

    return pairs


def diff_articles(
    arts_a: list[_ArticleLike], arts_b: list[_ArticleLike]
) -> list[dict[str, Any]]:
    """Top-level: diff two lists of articles. Excludes unchanged articles.

    1. Match by article_number.
    2. Run renumbering pairing on the leftovers (added + removed) so true
       renumberings show as one modified card instead of one add + one remove.
    """
    map_a = {a.article_number: a for a in arts_a}
    map_b = {b.article_number: b for b in arts_b}

    changes: list[dict[str, Any]] = []
    leftover_added: list[_ArticleLike] = []
    leftover_removed: list[_ArticleLike] = []

    all_numbers = sorted(
        set(map_a.keys()) | set(map_b.keys()),
        key=lambda x: (len(x), x),
    )

    for num in all_numbers:
        a = map_a.get(num)
        b = map_b.get(num)
        if a and b:
            d = diff_article(a, b)
            if d["change_type"] != "unchanged":
                changes.append(d)
        elif b:
            leftover_added.append(b)
        else:
            assert a is not None
            leftover_removed.append(a)

    pairs = _pair_renumbered(leftover_removed, leftover_added)
    paired_removed_ids = {id(r) for r, _ in pairs}
    paired_added_ids = {id(ad) for _, ad in pairs}

    for r, ad in pairs:
        d = diff_article(r, ad)
        # Force modified even if texts compare equal-after-strip (they won't, but be safe)
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
            "paragraphs": [],
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
            "paragraphs": [],
            "renumbered_from": None,
        })

    return changes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_structured_diff.py -v`
Expected: 16 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/structured_diff.py backend/tests/test_structured_diff.py
git commit -m "feat(backend): add diff_articles with renumbering pairing fallback"
```

---

## Task 5: Backend — wire the service into the router

Replace the body of `diff_versions` in `backend/app/routers/laws.py` so it loads articles with their paragraph/subparagraph children eagerly, calls `diff_articles`, and returns the new envelope. Delete the now-unused `_word_diff` from the router.

**Files:**
- Modify: `backend/app/routers/laws.py:1478-1607`
- Test: `backend/tests/test_compare_endpoint.py` (existing — verify it still passes or update it)

- [ ] **Step 1: Read the existing endpoint test**

Run: `cd backend && python -m pytest tests/test_compare_endpoint.py -v`
Take note of what assertions exist; we'll need them to keep passing or be updated to match the new tree shape.

- [ ] **Step 2: Write the new failing endpoint test**

Add to `backend/tests/test_compare_endpoint.py` (or create a new test file `tests/test_diff_endpoint.py` if the existing one is for a different endpoint):

```python
def test_diff_endpoint_returns_structured_tree(client, db_with_two_versions):
    law, v1, v2 = db_with_two_versions
    response = client.get(f"/api/laws/{law.id}/diff?a={v1.id}&b={v2.id}")
    assert response.status_code == 200
    body = response.json()

    assert "summary" in body
    assert "changes" in body

    for change in body["changes"]:
        assert "paragraphs" in change  # new tree shape
        assert "renumbered_from" in change
        if change["change_type"] == "modified":
            for para in change["paragraphs"]:
                assert "label" in para
                assert "change_type" in para
                if para["change_type"] != "unchanged":
                    assert "subparagraphs" in para
```

If there is no `db_with_two_versions` fixture, copy the structure from `backend/tests/test_diff_summary.py`'s `law_with_two_versions` fixture and adapt it to also create `Paragraph` and `Subparagraph` rows.

- [ ] **Step 3: Run the new test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compare_endpoint.py::test_diff_endpoint_returns_structured_tree -v`
Expected: FAIL — the current router returns the flat shape without `paragraphs`.

- [ ] **Step 4: Replace the router endpoint**

In `backend/app/routers/laws.py`, replace lines 1478–1607 with:

```python
@router.get("/{law_id}/diff")
def diff_versions(
    law_id: int,
    version_a: int,
    version_b: int,
    db: Session = Depends(get_db),
):
    """Compare two versions of a law as a structural tree.

    version_a and version_b are LawVersion IDs.
    Returns a tree of article → paragraph → subparagraph diffs. Articles
    that are byte-for-byte unchanged are excluded.
    """
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

    articles_a = (
        db.query(Article)
        .filter(Article.law_version_id == version_a)
        .options(
            subqueryload(Article.paragraphs).subqueryload(Paragraph.subparagraphs)
        )
        .order_by(Article.order_index)
        .all()
    )
    articles_b = (
        db.query(Article)
        .filter(Article.law_version_id == version_b)
        .options(
            subqueryload(Article.paragraphs).subqueryload(Paragraph.subparagraphs)
        )
        .order_by(Article.order_index)
        .all()
    )

    changes = diff_articles(articles_a, articles_b)

    summary = {
        "added": sum(1 for c in changes if c["change_type"] == "added"),
        "removed": sum(1 for c in changes if c["change_type"] == "removed"),
        "modified": sum(1 for c in changes if c["change_type"] == "modified"),
        "unchanged": (
            len({a.article_number for a in articles_a} & {b.article_number for b in articles_b})
            - sum(1 for c in changes if c["change_type"] == "modified")
        ),
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
        "changes": changes,
    }
```

The `_word_diff` function (previously at lines 1590–1607) is no longer referenced — delete it.

- [ ] **Step 5: Run all backend diff tests**

Run: `cd backend && python -m pytest tests/test_structured_diff.py tests/test_compare_endpoint.py tests/test_diff_summary.py -v`
Expected: all PASS (the new endpoint test, all 16 service tests, and the unchanged diff_summary tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/laws.py backend/tests/test_compare_endpoint.py
git commit -m "feat(backend): rewrite /laws/{id}/diff to return structured tree"
```

---

## Task 6: Frontend — update API types

**Files:**
- Modify: `frontend/src/lib/api.ts:297-316`

- [ ] **Step 1: Replace `DiffChange` and `DiffResult`**

In `frontend/src/lib/api.ts`, replace lines 297–316 with:

```typescript
export interface DiffSubparagraph {
  label: string | null;
  change_type: "added" | "removed" | "modified" | "unchanged";
  text_a?: string;
  text_b?: string;
  diff_html?: string;
  renumbered_from?: string | null;
}

export interface DiffParagraph {
  label: string | null;
  change_type: "added" | "removed" | "modified" | "unchanged";
  text_a?: string;
  text_b?: string;
  diff_html?: string;
  subparagraphs: DiffSubparagraph[];
}

export interface DiffArticle {
  article_number: string;
  change_type: "added" | "removed" | "modified" | "unchanged";
  title?: string | null;
  text_a?: string;
  text_b?: string;
  paragraphs: DiffParagraph[];
  renumbered_from: string | null;
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

- [ ] **Step 2: Verify the project still type-checks**

Run: `cd frontend && npx tsc --noEmit`
Expected: errors only in `frontend/src/app/laws/[id]/diff/page.tsx` (it still references the old `DiffChange` shape — Task 9 fixes that). Any other type errors mean a different file also imported `DiffChange` and needs to be migrated.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): update DiffResult types for structured diff tree"
```

---

## Task 7: Frontend — diff CSS

**Files:**
- Create: `frontend/src/app/laws/[id]/diff/diff.css`

- [ ] **Step 1: Create the stylesheet**

```css
/* frontend/src/app/laws/[id]/diff/diff.css */

.diff-content ins {
  background: #d1fae5;
  color: #065f46;
  text-decoration: none;
  padding: 0 2px;
  border-radius: 2px;
}

.diff-content del {
  background: #fee2e2;
  color: #991b1b;
  text-decoration: line-through;
  padding: 0 2px;
  border-radius: 2px;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/laws/[id]/diff/diff.css
git commit -m "feat(frontend): add diff ins/del styles"
```

---

## Task 8: Frontend — leaf renderers

`DiffParagraphLeaf`, `DiffSubparagraphLeaf`, and `CollapsedRun`. Mirrors the JSX shape of `paragraph-renderer.tsx` so the diff view looks identical to the normal version view. Reuses the label/superscript helper.

**Files:**
- Create: `frontend/src/app/laws/[id]/diff/components/diff-leaf.tsx`

- [ ] **Step 1: Create the file**

```tsx
// frontend/src/app/laws/[id]/diff/components/diff-leaf.tsx
"use client";

import { useState } from "react";
import { DiffParagraph, DiffSubparagraph } from "@/lib/api";

function renderLabel(label: string | null) {
  if (!label) return null;
  // Handle "d^1)" -> d<sup>1</sup>)
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
  // Handle "(4^1)" -> (4<sup>1</sup>)
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
  return label;
}

function renumberedSuffix(renumberedFrom: string | null | undefined) {
  if (!renumberedFrom) return null;
  return (
    <span className="text-xs text-gray-400 ml-1">(was {renumberedFrom})</span>
  );
}

function leafBodyStyle(changeType: string): string {
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

export function DiffSubparagraphLeaf({ leaf }: { leaf: DiffSubparagraph }) {
  const showText =
    leaf.change_type === "modified" ||
    leaf.change_type === "added" ||
    leaf.change_type === "removed";

  if (!showText) return null; // unchanged leaves are rendered by CollapsedRun

  let body: JSX.Element;
  if (leaf.change_type === "modified" && leaf.diff_html) {
    body = (
      <span
        className="diff-content text-[15px] leading-[1.75] text-gray-700"
        dangerouslySetInnerHTML={{ __html: leaf.diff_html }}
      />
    );
  } else if (leaf.change_type === "added") {
    body = (
      <span className={`text-[15px] leading-[1.75] ${leafBodyStyle("added")}`}>
        {leaf.text_b}
      </span>
    );
  } else {
    body = (
      <span className={`text-[15px] leading-[1.75] ${leafBodyStyle("removed")}`}>
        {leaf.text_a}
      </span>
    );
  }

  return (
    <div className="flex gap-2 pl-6 mt-1">
      {leaf.label && (
        <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-500">
          {renderLabel(leaf.label)}
          {renumberedSuffix(leaf.renumbered_from)}
          {leaf.change_type === "added" && <NewBadge />}
        </span>
      )}
      {body}
    </div>
  );
}

export function DiffParagraphLeaf({
  para,
  forceShowAll,
}: {
  para: DiffParagraph;
  forceShowAll: boolean;
}) {
  // Render the paragraph's intro line if it's modified/added/removed.
  let intro: JSX.Element | null = null;
  if (para.change_type === "modified" && para.diff_html) {
    intro = (
      <div className="flex gap-2">
        {para.label && (
          <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-500">
            {renderLabel(para.label)}
          </span>
        )}
        <span
          className="diff-content text-[15px] leading-[1.75] text-gray-700"
          dangerouslySetInnerHTML={{ __html: para.diff_html }}
        />
      </div>
    );
  } else if (para.change_type === "added") {
    intro = (
      <div className="flex gap-2">
        {para.label && (
          <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-500">
            {renderLabel(para.label)}
            <NewBadge />
          </span>
        )}
        <span className={`text-[15px] leading-[1.75] ${leafBodyStyle("added")}`}>
          {para.text_b}
        </span>
      </div>
    );
  } else if (para.change_type === "removed") {
    intro = (
      <div className="flex gap-2">
        {para.label && (
          <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-500">
            {renderLabel(para.label)}
          </span>
        )}
        <span
          className={`text-[15px] leading-[1.75] ${leafBodyStyle("removed")}`}
        >
          {para.text_a}
        </span>
      </div>
    );
  } else if (forceShowAll && para.label) {
    // Unchanged paragraph being shown because the user clicked "show full article".
    intro = (
      <div className="flex gap-2">
        <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-400">
          {renderLabel(para.label)}
        </span>
        <span className="text-[15px] leading-[1.75] text-gray-500">
          (unchanged)
        </span>
      </div>
    );
  }

  // Children: collapse runs of consecutive unchanged subparagraphs into one CollapsedRun.
  const children: JSX.Element[] = [];
  let unchangedRun: DiffSubparagraph[] = [];
  const flushRun = (key: string) => {
    if (unchangedRun.length === 0) return;
    children.push(
      <CollapsedRun
        key={`run-${key}`}
        leaves={unchangedRun}
        forceShowAll={forceShowAll}
      />
    );
    unchangedRun = [];
  };

  para.subparagraphs.forEach((s, i) => {
    if (s.change_type === "unchanged") {
      unchangedRun.push(s);
      return;
    }
    flushRun(`before-${i}`);
    children.push(<DiffSubparagraphLeaf key={i} leaf={s} />);
  });
  flushRun("end");

  return (
    <div className="mt-2 space-y-1">
      {intro}
      {children}
    </div>
  );
}

export function CollapsedRun({
  leaves,
  forceShowAll,
}: {
  leaves: DiffSubparagraph[];
  forceShowAll: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const open = expanded || forceShowAll;

  if (leaves.length === 0) return null;

  if (open) {
    return (
      <div className="space-y-1">
        {leaves.map((s, i) => (
          <div key={i} className="flex gap-2 pl-6 mt-1">
            {s.label && (
              <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-400">
                {renderLabel(s.label)}
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

  const first = leaves[0].label;
  const last = leaves[leaves.length - 1].label;
  const range =
    leaves.length === 1
      ? first
      : `${first}–${last}`;

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

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors in `diff-leaf.tsx`. Any error in `page.tsx` is fine — Task 9 fixes it.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/laws/[id]/diff/components/diff-leaf.tsx
git commit -m "feat(frontend): add diff leaf renderers with collapsed runs"
```

---

## Task 9: Frontend — `StructuredDiffArticle` and wire into page

The article-level component plus the page-level swap. After this step the new diff view is live.

**Files:**
- Create: `frontend/src/app/laws/[id]/diff/components/structured-diff-article.tsx`
- Modify: `frontend/src/app/laws/[id]/diff/page.tsx:144-184`

- [ ] **Step 1: Create the article component**

```tsx
// frontend/src/app/laws/[id]/diff/components/structured-diff-article.tsx
"use client";

import { useState } from "react";
import { DiffArticle } from "@/lib/api";
import { DiffParagraphLeaf } from "./diff-leaf";

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

export function StructuredDiffArticle({ article }: { article: DiffArticle }) {
  const [showAll, setShowAll] = useState(false);
  const isModified = article.change_type === "modified";

  const headerLabel = article.renumbered_from
    ? `Art. ${article.article_number} (was Art. ${article.renumbered_from})`
    : `Art. ${article.article_number}`;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <button
        type="button"
        disabled={!isModified}
        onClick={() => setShowAll((v) => !v)}
        className={`w-full flex items-center justify-between gap-3 px-4 py-2 text-sm font-medium border-b text-left ${badgeStyle(
          article.change_type
        )} ${isModified ? "hover:brightness-95 cursor-pointer" : "cursor-default"}`}
      >
        <span>
          {headerLabel}
          {article.title && (
            <span className="font-bold"> — {article.title}</span>
          )}
        </span>
        <span className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wide opacity-80">
            {badgeLabel(article.change_type)}
          </span>
          {isModified && (
            <span className="text-xs underline">
              {showAll ? "hide unchanged" : "show full article"}
            </span>
          )}
        </span>
      </button>

      <div className="p-4">
        {article.change_type === "modified" && (
          <div className="space-y-1">
            {article.paragraphs.map((p, i) => {
              // Skip wholly-unchanged paragraphs unless showAll is on.
              if (p.change_type === "unchanged" && !showAll) {
                return (
                  <div
                    key={i}
                    className="text-xs text-gray-400 italic py-1 border-t border-dashed border-gray-200"
                  >
                    … {p.label ?? "(intro)"} — unchanged
                  </div>
                );
              }
              return <DiffParagraphLeaf key={i} para={p} forceShowAll={showAll} />;
            })}
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

- [ ] **Step 2: Replace the per-article render block in `page.tsx`**

In `frontend/src/app/laws/[id]/diff/page.tsx`:

1. Add these imports near the existing `import { api, DiffResult } from "@/lib/api";`:

```tsx
import { StructuredDiffArticle } from "./components/structured-diff-article";
import "./diff.css";
```

2. Replace lines 144–184 (the entire `{changedArticles.map(...)}` block, ending with the closing `</div>` of that map's container) with:

```tsx
{changedArticles.map((change) => (
  <StructuredDiffArticle key={change.article_number} article={change} />
))}
```

3. The surrounding `<div className="space-y-4">` and the `<h2>Changes (...)` line stay as they are.

- [ ] **Step 3: Type-check the whole project**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 4: Manual visual smoke test**

Start backend and frontend dev servers (whatever the project's normal commands are — typically `cd backend && uvicorn app.main:app --reload` and `cd frontend && npm run dev`). Open `http://localhost:3000/laws/24/diff?a=331&b=519` (the same URL from the user screenshots). Verify:

- Each changed article renders as a card with a clickable header.
- Unchanged litere/alineate are collapsed into dashed `… range — unchanged` lines with a `show` button.
- Modified leaves are shown in their `(N) → x)` structural context with inline red/green word highlighting.
- Clicking the article header expands the full article including unchanged leaves; clicking again collapses.
- Newly added litere display the "New" badge and full green text.
- The summary cards and version date pills above the changes are unchanged from before.
- No console errors.

If anything looks wrong, open the diff mockup at `.superpowers/brainstorm/78790-1775569962/content/diff-mockup.html` and compare side-by-side.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/laws/[id]/diff/components/structured-diff-article.tsx \
        frontend/src/app/laws/[id]/diff/page.tsx
git commit -m "feat(frontend): render structured diff with collapsible unchanged sections"
```

---

## Task 10: Final regression sweep

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: same pass rate as before this branch (no regressions). Investigate any new failures.

- [ ] **Step 2: Frontend type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 3: Frontend lint (if configured)**

Run: `cd frontend && npm run lint --silent`
Expected: zero new lint errors. Skip this step if the project has no lint script.

- [ ] **Step 4: Visual re-check of the original screenshot URL**

Open `http://localhost:3000/laws/24/diff?a=331&b=519` in the browser one more time. Compare against the user's original screenshots in the conversation: the same articles (Art. 62 lit. k, Art. 68 alin. (5) lit. g, Art. 76 alin. (4^1) lit. e and the new e^1) should now read cleanly with structured layout and inline highlights, no walls of repeated text.

- [ ] **Step 5: No commit needed** — this task just verifies the previous tasks landed cleanly.

---

## Self-Review Notes

- **Spec coverage:** every spec section maps to a task — `word_diff_html` (T1), structural matching (T2, T3), renumbering fallback (T4), router rewrite (T5), API types (T6), styling (T7), structured rendering with collapsed runs and click-to-expand-all (T8, T9), regression sweep (T10).
- **No placeholders:** every code step contains the actual code.
- **Type/name consistency:** `diff_paragraph` / `diff_article` / `diff_articles` are used consistently across tasks; `DiffArticle` / `DiffParagraph` / `DiffSubparagraph` types match what the backend emits. The component name `StructuredDiffArticle` is identical in T9 step 1 and T9 step 2 imports. The `forceShowAll` prop is the same name in `DiffParagraphLeaf` and `CollapsedRun`.
