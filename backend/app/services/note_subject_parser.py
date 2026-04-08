"""Parse leropa Note.subject strings into structural labels.

The `subject` field of a leropa amendment note is freeform Romanian. We map a
small set of common phrasings to (article_label, paragraph_label?,
subparagraph_label?). Anything we cannot match returns an all-None ParsedSubject
and the caller falls back to article-level attribution.

This module is pure: no DB, no I/O, total (never raises).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A label is one or more digits/roman numerals/letters, optionally with a
# caret-suffix (e.g. "1^2"). Romanian source uses the caret instead of a
# superscript.
_LABEL = r"[A-Za-z0-9]+(?:\^[A-Za-z0-9]+)?"
_PARAG = r"\([A-Za-z0-9]+(?:\^[A-Za-z0-9]+)?\)"  # e.g. (1), (2^1)
_LITERA = rf"{_LABEL}\)"  # e.g. a), b^1)


@dataclass(frozen=True)
class ParsedSubject:
    article_label: str | None = None
    paragraph_label: str | None = None
    subparagraph_label: str | None = None


# Patterns are tried in order. The first match wins. Each pattern uses named
# groups (`art`, `par`, `sub`) for the labels we want.
_PATTERNS: list[re.Pattern[str]] = [
    # "Litera a) a alineatului (2) al articolului 336"
    re.compile(
        rf"Litera\s+(?P<sub>{_LITERA})\s+a\s+alineatului\s+(?P<par>{_PARAG})"
        rf"\s+al\s+articolului\s+(?P<art>{_LABEL})",
        re.IGNORECASE,
    ),
    # "Articolul 5, alineatul (1), litera c)"
    re.compile(
        rf"Articolul\s+(?P<art>{_LABEL}),\s*alineatul\s+(?P<par>{_PARAG}),"
        rf"\s*litera\s+(?P<sub>{_LITERA})",
        re.IGNORECASE,
    ),
    # "Alineatul (1) al articolului 336"
    re.compile(
        rf"Alineatul\s+(?P<par>{_PARAG})\s+al\s+articolului\s+(?P<art>{_LABEL})",
        re.IGNORECASE,
    ),
    # "Articolul 5, alineatul (1)"
    re.compile(
        rf"Articolul\s+(?P<art>{_LABEL}),\s*alineatul\s+(?P<par>{_PARAG})",
        re.IGNORECASE,
    ),
    # "Articolul 336" (must be last among article-only — most generic)
    re.compile(
        rf"^\s*Articolul\s+(?P<art>{_LABEL})\s*$",
        re.IGNORECASE,
    ),
    # "articolului 336" (lowercase, used inside compound subjects we already
    # tried above; this catches stragglers like "Punctul 9. al articolului I")
    re.compile(
        rf"articolului\s+(?P<art>{_LABEL})",
        re.IGNORECASE,
    ),
]


def parse(subject: str | None) -> ParsedSubject:
    """Map a freeform note subject to a ParsedSubject. Always returns; never raises."""
    if not subject:
        return ParsedSubject()
    s = subject.strip()
    for pat in _PATTERNS:
        m = pat.search(s)
        if m:
            groups = m.groupdict()
            return ParsedSubject(
                article_label=groups.get("art"),
                paragraph_label=groups.get("par"),
                subparagraph_label=groups.get("sub"),
            )
    return ParsedSubject()
