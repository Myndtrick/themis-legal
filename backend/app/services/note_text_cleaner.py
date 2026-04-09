"""Strip inline modification annotations of the form `(la <date>, …)` from law text.

These annotations are embedded by legislatie.just.ro inside article and paragraph
text and act as an inline changelog. They are stored as separate `AmendmentNote`
rows by the importer; for diffing we want them removed from the body so that
text comparisons reflect substance, not metadata.

The annotation always ends with the canonical end marker
`MONITORUL OFICIAL nr. <num> din <date>)`. We find that marker and remove
everything from the `(la <date>` start to the closing `)` after it. This is
robust against literă references like `Litera a)` that appear inside the
annotation body — those stray closing parens used to trip a naive depth counter
and exit early, leaving annotation fragments in the cleaned text.

If a `(la <date>` start has no `MONITORUL OFICIAL ... )` end marker within a
reasonable distance, the text is returned unchanged from that point — better to
leave a malformed annotation in than to mangle real content.
"""

from __future__ import annotations

import re

# Match the start of an inline note: `(la ` followed by a date token. Date
# format on legislatie.just.ro is DD-MM-YYYY, occasionally DD.MM.YYYY or
# DD/MM/YYYY, with 2- or 4-digit year.
_NOTE_START = re.compile(r"\(la \d{1,2}[-./]\d{1,2}[-./]\d{2,4}")

# Match the canonical end marker: "MONITORUL OFICIAL" (case insensitive,
# flexible whitespace) up to and including the next `)`. The character class
# `[^)]*` cannot match `)`, so this stops at the FIRST `)` after MO regardless
# of regex greediness — exactly what we want.
_NOTE_END = re.compile(r"MONITORUL\s+OFICIAL[^)]*\)", re.IGNORECASE)

# Maximum distance (in characters) we'll search for the end marker after a
# (la start. Real annotations are 100-400 chars; 1500 is a generous safety
# bound that prevents catastrophically over-removing if a `(la <date>` happens
# to appear in normal text far from any MO reference.
_MAX_ANNOTATION_LEN = 1500


def strip(text: str) -> str:
    """Return `text` with every inline `(la <date>, …)` annotation removed.

    Walks the string, finds each note start, then searches forward for the
    canonical `MONITORUL OFICIAL ... )` end marker. Removes from the start of
    the note up to and including that closing paren.

    Conservative: if no clean end marker is found within `_MAX_ANNOTATION_LEN`
    characters of a `(la <date>` start, the text is returned unchanged from
    that point — we never mangle.

    Whitespace runs left behind by removed notes are collapsed to a single
    space, and leading/trailing whitespace on the result is stripped.
    """
    if not text:
        return text

    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        m_start = _NOTE_START.search(text, i)
        if m_start is None:
            out.append(text[i:])
            break

        # Emit content before the annotation
        out.append(text[i : m_start.start()])

        # Search forward for the canonical end marker, bounded
        search_end = min(n, m_start.end() + _MAX_ANNOTATION_LEN)
        m_end = _NOTE_END.search(text, m_start.end(), search_end)
        if m_end is None:
            # No clean end marker — leave the rest of the text intact
            out.append(text[m_start.start():])
            break

        # Skip the annotation entirely; resume after the closing paren
        i = m_end.end()

    cleaned = "".join(out)
    # Collapse runs of whitespace introduced by the removal and trim edges
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([.,;:])", r"\1", cleaned)  # " ." → "."
    return cleaned.strip()
