"""Unit tests for note_text_cleaner.strip — removing inline (la <date>, …) annotations."""
from app.services.note_text_cleaner import strip


def test_text_with_no_notes_is_unchanged():
    assert strip("Articolul are un singur alineat.") == "Articolul are un singur alineat."


def test_strips_single_inline_note_at_end():
    raw = (
        "Operatorul economic plătește accize. "
        "(la 31-03-2026, Articolul 336 a fost completat de Punctul 9., "
        "Articolul I din ORDONANȚA DE URGENȚĂ nr. 89 din 23 decembrie 2025, publicată în "
        "MONITORUL OFICIAL nr. 89 din 23 decembrie 2025)"
    )
    cleaned = strip(raw)
    assert cleaned == "Operatorul economic plătește accize."


def test_strips_multiple_inline_notes():
    raw = (
        "Prima frază. (la 01-01-2024, Articolul 1 a fost modificat de Legea nr. 5/2023, publicată în "
        "MONITORUL OFICIAL nr. 5 din 10 ianuarie 2024) "
        "A doua frază. (la 02-02-2025, Articolul 1 a fost completat de OUG nr. 7/2024, publicată în "
        "MONITORUL OFICIAL nr. 7 din 02 februarie 2025)"
    )
    cleaned = strip(raw)
    assert cleaned == "Prima frază. A doua frază."


def test_handles_nested_parentheses_inside_note():
    raw = (
        "Textul de bază. "
        "(la 31-03-2026, Articolul 5 (definiții) a fost modificat de Legea nr. 10/2025, publicată în "
        "MONITORUL OFICIAL nr. 10 din 31 martie 2026)"
    )
    cleaned = strip(raw)
    assert cleaned == "Textul de bază."


def test_unbalanced_note_returns_text_unchanged():
    raw = "Frază netulburată. (la 31-03-2026, Articolul 5 a fost modificat"
    # Defensive: malformed input is left as-is rather than mangled
    assert strip(raw) == raw


def test_only_strips_la_prefix_not_other_parens():
    raw = "Capitalul social (minimum 200 lei) trebuie depus."
    assert strip(raw) == "Capitalul social (minimum 200 lei) trebuie depus."


def test_collapses_double_spaces_left_after_stripping():
    raw = (
        "Înainte (la 01-01-2024, Articolul 1 a fost modificat de Legea nr. 5/2023, publicată în "
        "MONITORUL OFICIAL nr. 5 din 01 ianuarie 2024) după."
    )
    assert strip(raw) == "Înainte după."


def test_strips_annotation_with_litera_reference_inside():
    """Regression: 'Litera a)' inside an annotation has an unmatched ')' that
    used to trip the depth counter and exit early."""
    raw = (
        "Body text; "
        "(la 18-12-2025, Litera a), Articolul 19 a fost modificată de Punctul 8., "
        "Articolul XXIX din LEGEA nr. 239 din 15 decembrie 2025, publicată în "
        "MONITORUL OFICIAL nr. 1160 din 15 decembrie 2025) a^1) justifică."
    )
    cleaned = strip(raw)
    assert "Litera" not in cleaned
    assert "MONITORUL" not in cleaned
    assert "Punctul 8" not in cleaned
    assert cleaned == "Body text; a^1) justifică."


def test_strips_two_consecutive_annotations_with_litera_inside():
    """Two annotations in a row, both containing literă-style stray parens."""
    raw = (
        "Body. "
        "(la 18-12-2025, Litera a), Articolul 19 a fost modificată de Punctul 8., "
        "Articolul XXIX din LEGEA nr. 239 din 15 decembrie 2025, publicată în "
        "MONITORUL OFICIAL nr. 1160 din 15 decembrie 2025) "
        "a^1) middle text. "
        "(la 18-12-2025, Articolul 19 a fost completat de Punctul 9., "
        "Articolul XXIX din LEGEA nr. 239 din 15 decembrie 2025, publicată în "
        "MONITORUL OFICIAL nr. 1160 din 15 decembrie 2025) end text."
    )
    cleaned = strip(raw)
    assert "Litera" not in cleaned
    assert "MONITORUL" not in cleaned
    assert cleaned == "Body. a^1) middle text. end text."


def test_annotation_without_monitorul_oficial_is_left_unchanged():
    """Conservative: if there's no canonical end marker, do NOT remove anything.
    The text is returned unchanged from that point, even if a (la <date> is present."""
    raw = "Body text. (la 18-12-2025, some unusual reference without the canonical close pattern."
    cleaned = strip(raw)
    # The cleaner should NOT mangle this — it should return it as-is
    assert "(la 18-12-2025" in cleaned
