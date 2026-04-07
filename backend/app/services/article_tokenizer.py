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

import re
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


_WHITESPACE_RUN = re.compile(r"\s+")


def _normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace to a single space and strip ends."""
    return _WHITESPACE_RUN.sub(" ", text).strip()


def tokenize_article(full_text: str) -> list[AtomicUnit]:
    """Tokenize an article's full_text into a flat list of AtomicUnit.

    Empty input returns an empty list. See module docstring for the
    overall algorithm.
    """
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
