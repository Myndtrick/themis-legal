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
    # If exactly one side (or both) has no paragraph rows, fall back to a
    # single synthetic paragraph holding the entire article body.
    if not pars_a or not pars_b:
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
