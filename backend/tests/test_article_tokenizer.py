"""Tests for the article tokenizer."""
from app.services.article_tokenizer import tokenize_article, AtomicUnit


def test_empty_string_returns_empty_list():
    assert tokenize_article("") == []


def test_plain_sentence_no_markers_returns_one_intro_unit():
    units = tokenize_article("Articolul 100 se abrogă.")
    assert units == [
        AtomicUnit(
            alineat_label=None,
            marker_kind="intro",
            label="",
            text="Articolul 100 se abrogă.",
        )
    ]


def test_plain_sentence_collapses_internal_whitespace():
    units = tokenize_article("  Articolul 100   se abrogă.\n  ")
    assert len(units) == 1
    assert units[0].text == "Articolul 100 se abrogă."


def test_single_alineat_emits_alineat_unit():
    units = tokenize_article("(1) Statul român este suveran.")
    assert units == [
        AtomicUnit(
            alineat_label=None,  # the alineat marker itself sits at the boundary
            marker_kind="alineat",
            label="(1)",
            text="Statul român este suveran.",
        )
    ]


def test_two_alineate_emit_two_units():
    units = tokenize_article("(1) Primul alineat. (2) Al doilea alineat.")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", "Primul alineat."),
        AtomicUnit(None, "alineat", "(2)", "Al doilea alineat."),
    ]


def test_text_before_first_alineat_becomes_intro():
    units = tokenize_article("Preambul al articolului. (1) Conținutul.")
    assert units == [
        AtomicUnit(None, "intro", "", "Preambul al articolului."),
        AtomicUnit(None, "alineat", "(1)", "Conținutul."),
    ]


def test_numbered_marker_inside_alineat():
    units = tokenize_article("(1) Intro: 1. primul punct. 2. al doilea punct.")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", "Intro:"),
        AtomicUnit("(1)", "numbered", "1.", "primul punct."),
        AtomicUnit("(1)", "numbered", "2.", "al doilea punct."),
    ]


def test_litera_marker_inside_alineat():
    units = tokenize_article("(1) Intro: a) prima literă; b) a doua literă;")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", "Intro:"),
        AtomicUnit("(1)", "litera", "a)", "prima literă;"),
        AtomicUnit("(1)", "litera", "b)", "a doua literă;"),
    ]


def test_upper_litera_marker():
    units = tokenize_article("(1) Intro: A. primul; B. al doilea;")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", "Intro:"),
        AtomicUnit("(1)", "upper_litera", "A.", "primul;"),
        AtomicUnit("(1)", "upper_litera", "B.", "al doilea;"),
    ]


def test_bullet_marker():
    # Bullet uses U+2013 en-dash + space.
    units = tokenize_article("(1) Intro: – primul; – al doilea;")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", "Intro:"),
        AtomicUnit("(1)", "bullet", "–", "primul;"),
        AtomicUnit("(1)", "bullet", "–", "al doilea;"),
    ]
