"""Strip inline modification annotations of the form `(la <date>, …)` from law text.

These annotations are embedded by legislatie.just.ro inside article and paragraph
text and act as an inline changelog. They are stored as separate `AmendmentNote`
rows by the importer; for diffing we want them removed from the body so that
text comparisons reflect substance, not metadata.
"""

from __future__ import annotations

import re

# Match the start of an inline note: an opening paren immediately followed by
# the literal "la " and a date-like token. Date format on legislatie.just.ro is
# DD-MM-YYYY, occasionally DD.MM.YYYY. We accept both.
_NOTE_START = re.compile(r"\(la \d{1,2}[-./]\d{1,2}[-./]\d{2,4}")


def strip(text: str) -> str:
    """Return `text` with every inline `(la <date>, …)` annotation removed.

    The scanner walks the string, finds each note start, then advances a
    parenthesis-depth counter to find the matching close. If a note start has
    no balanced close (malformed input), the text is returned unchanged from
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
        m = _NOTE_START.search(text, i)
        if m is None:
            out.append(text[i:])
            break

        # Emit everything before the note
        out.append(text[i : m.start()])

        # Walk parens from the note's opening "("
        depth = 0
        j = m.start()
        end = -1
        while j < n:
            ch = text[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
            j += 1

        if end == -1:
            # Unbalanced — bail out without modifying anything from this point
            out.append(text[m.start() :])
            break

        # Skip the note entirely; continue after the closing paren
        i = end

    cleaned = "".join(out)
    # Collapse runs of whitespace introduced by the removal and trim edges
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([.,;:])", r"\1", cleaned)  # " ." → "."
    return cleaned.strip()
