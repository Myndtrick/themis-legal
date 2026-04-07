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
