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
