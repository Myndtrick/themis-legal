"""Tests for the article tokenizer."""
from app.services.article_tokenizer import tokenize_article, AtomicUnit


def test_empty_string_returns_empty_list():
    assert tokenize_article("") == []
