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


# Each entry: (kind, compiled_regex). The regex MUST have one capture group
# returning the marker label as it should appear in the output (e.g. "(1)",
# "32.", "a)"). Order matters only for tie-breaking when two patterns match
# at the same start position — see _resolve_overlaps.
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


@dataclass(frozen=True)
class _Match:
    start: int        # inclusive byte offset in full_text where the marker begins
    end: int          # exclusive byte offset where the marker ends (body starts here)
    kind: str
    label: str        # rendered label as it will appear in the AtomicUnit


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
            if _is_false_positive(full_text, m.start(), kind):
                continue
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
    if kind == MarkerKind.NUMBERED:
        return f"{raw_group}."
    if kind == MarkerKind.UPPER_LITERA:
        return f"{raw_group}."
    if kind == MarkerKind.LITERA:
        return f"{raw_group})"
    if kind == MarkerKind.BULLET:
        return raw_group  # "–"
    return raw_group


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
