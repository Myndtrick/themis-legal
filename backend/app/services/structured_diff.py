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
