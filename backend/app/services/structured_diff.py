"""Structural diff between two parsed law versions.

Compares the existing Article → Paragraph → Subparagraph tree by label
and produces a tree of changes suitable for the /api/laws/{id}/diff endpoint.
All functions are pure (no DB access) so they can be unit-tested in isolation.
"""
from __future__ import annotations

import difflib
from typing import Any, Protocol


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
    """Diff two articles by structural recursion.

    Recurses into paragraphs and derives the article's change_type from
    whether any descendant changed. We do NOT short-circuit on
    art.full_text equality — denormalized full_text can drift from the
    authoritative paragraph tree, and short-circuiting would silently
    hide real changes when it does.
    """
    paragraph_diffs = _diff_paragraphs_list(
        list(art_a.paragraphs), list(art_b.paragraphs)
    )

    any_changed = any(p["change_type"] != "unchanged" for p in paragraph_diffs)
    change_type = "modified" if any_changed else "unchanged"

    return {
        "article_number": art_b.article_number,
        "change_type": change_type,
        "title": art_b.label,
        "paragraphs": paragraph_diffs if change_type == "modified" else [],
        "renumbered_from": None,
    }


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
    paired_added_ids = {id(ad) for _, ad in pairs}
    paired_removed_ids = {id(r) for r, _ in pairs}

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
