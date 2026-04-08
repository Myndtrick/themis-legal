"""Unit tests for note_text_cleaner.strip — removing inline (la <date>, …) annotations."""
from app.services.note_text_cleaner import strip


def test_text_with_no_notes_is_unchanged():
    assert strip("Articolul are un singur alineat.") == "Articolul are un singur alineat."


def test_strips_single_inline_note_at_end():
    raw = (
        "Operatorul economic plătește accize. "
        "(la 31-03-2026, Articolul 336 a fost completat de Punctul 9., "
        "Articolul I din ORDONANȚA DE URGENȚĂ nr. 89 din 23 decembrie 2025)"
    )
    cleaned = strip(raw)
    assert cleaned == "Operatorul economic plătește accize."


def test_strips_multiple_inline_notes():
    raw = (
        "Prima frază. (la 01-01-2024, Articolul 1 a fost modificat de Legea nr. 5/2023) "
        "A doua frază. (la 02-02-2025, Articolul 1 a fost completat de OUG nr. 7/2024)"
    )
    cleaned = strip(raw)
    assert cleaned == "Prima frază. A doua frază."


def test_handles_nested_parentheses_inside_note():
    raw = (
        "Textul de bază. "
        "(la 31-03-2026, Articolul 5 (definiții) a fost modificat de Legea nr. 10/2025)"
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
    raw = "Înainte (la 01-01-2024, Articolul 1 a fost modificat de Legea nr. 5/2023) după."
    assert strip(raw) == "Înainte după."
