"""Tests for structured version diff service."""
from app.services.structured_diff import word_diff_html


def test_word_diff_html_marks_replacement():
    a = "pensiile facultative din fonduri"
    b = "pensiile ocupaționale din fonduri"
    html = word_diff_html(a, b)
    assert "<del>facultative</del>" in html
    assert "<ins>ocupaționale</ins>" in html
    assert "pensiile" in html
    assert "fonduri" in html


def test_word_diff_html_identical_returns_plain():
    text = "același text neschimbat"
    assert word_diff_html(text, text) == text


def test_word_diff_html_pure_insertion():
    html = word_diff_html("a b", "a b c d")
    assert html == "a b <ins>c d</ins>"


def test_word_diff_html_pure_deletion():
    html = word_diff_html("a b c d", "a b")
    assert html == "a b <del>c d</del>"
