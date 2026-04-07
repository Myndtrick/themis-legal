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


class _ArticleLike(Protocol):
    article_number: str
    full_text: str
    label: str | None


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
